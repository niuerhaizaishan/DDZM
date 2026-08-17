from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from dzmm_bot.runtime.contracts import InboundMessage

from .ai_mentions import BOT_MENTION_PREFIX, normalize_ai_mention
from .repository import CoreRepository
from .random_event_submissions import (
    RandomEventSubmissionHandler,
    SUBMISSION_COMMANDS,
    SubmissionReply,
)


_DIRECT_COMMANDS = {
    "/报数", "/发红包", "/抢红包", "/余额", "/我的物品", "/我",
    "/帮助", "/当前游戏", "/我的档案", "/我的部门人数", "/打卡",
    "/编辑档案", "/编辑档案形象", "/加入", "/退出", "/开始",
    "/答案", "/继续", "/收手", "/投降", "/跳过", "/结束游戏",
}
_RANDOM_EVENT_INDEPENDENT_COMMANDS = {
    "/发红包", "/抢红包", "/打赏", "/余额", "/当前游戏"
}


class CommandHandler(Protocol):
    def handle(self, message: InboundMessage) -> str | list[str] | None: ...


class NoopCommandHandler:
    def handle(self, message: InboundMessage) -> None:
        return None


@dataclass(frozen=True)
class CommandReply:
    text: str
    recall_after_seconds: int | None = None
    memory_round_id: UUID | None = None
    destination_chatroom_id: str | None = None
    delivery_kind: str = "group"
    content_type: str = "text"
    image_url: str | None = None
    image_alt: str | None = None
    force_group_destination: bool = False


@dataclass(frozen=True)
class ReceiveResult:
    message_id: UUID
    inserted: bool


@dataclass(frozen=True)
class GroupMessageContext:
    group_chat_id: UUID
    chatroom_id: str


class CoreService:
    def __init__(
        self,
        repository: CoreRepository,
        command_handler: CommandHandler | None = None,
    ) -> None:
        self._repository = repository
        self._command_handler = command_handler or NoopCommandHandler()
        self._submission_handler = RandomEventSubmissionHandler(repository)

    def receive_inbound(self, message: InboundMessage) -> ReceiveResult:
        with self._repository.transaction():
            group_context: GroupMessageContext | None = None
            if (
                message.source_type == "group"
                and self._repository.group_chat_bootstrap_ready()
            ):
                if message.chatroom_id is None:
                    return ReceiveResult(uuid4(), False)
                group = self._repository.resolve_enabled_group_chat(
                    message.chatroom_id
                )
                if group is None or group.chatroom_id is None:
                    return ReceiveResult(uuid4(), False)
                group_context = GroupMessageContext(group.id, group.chatroom_id)
            command_parts = message.content.strip().split(maxsplit=1)
            if command_parts and command_parts[0] == "/甩锅":
                self._repository.lock_gameplay_order()
            stored, inserted = self._repository.accept_inbound(
                message,
                None if group_context is None else group_context.group_chat_id,
            )
            if not inserted:
                return ReceiveResult(stored.id, False)
            command = command_parts[0] if command_parts else ""
            if command in SUBMISSION_COMMANDS:
                self._repository.ensure_command_definitions()
                if not self._repository.is_command_enabled(command):
                    return ReceiveResult(stored.id, True)
                submission_reply = self._submission_handler.handle(message)
                self._enqueue_replies(
                    stored.id, submission_reply, group_context=group_context
                )
                return ReceiveResult(stored.id, True)
            if message.source_type == "direct":
                parts = message.content.strip().split(maxsplit=1)
                if parts and parts[0] in _DIRECT_COMMANDS:
                    direct_reply = self._command_handler.handle(message)
                elif not message.content.lstrip().startswith("/"):
                    direct_reply = self._submission_handler.handle(message)
                else:
                    return ReceiveResult(stored.id, True)
                self._enqueue_replies(
                    stored.id,
                    direct_reply,
                    default_destination_chatroom_id=message.chatroom_id,
                )
                return ReceiveResult(stored.id, True)
            self._repository.record_activity(
                message.sender_platform_id, message.received_at, message.content
            )
            event_message_status = self._repository.record_random_event_round(
                message.sender_platform_id, message.received_at, message.content
            )
            independent_command = bool(
                command_parts
                and command_parts[0] in _RANDOM_EVENT_INDEPENDENT_COMMANDS
            )
            replies: list[CommandReply] = []
            event_state = self._repository.active_random_event_state()
            profile = (
                self._repository.get_user_profile(message.sender_platform_id)
                if message.content.strip() == "/结束游戏"
                else None
            )
            board_force_end = profile is not None and profile.rank.is_board
            if event_state is not None:
                ordinary_tipping_message = (
                    event_state == "tipping"
                    and not message.content.lstrip().startswith("/")
                )
                if (
                    not independent_command
                    and event_message_status in {"participant", "observer_valid"}
                ):
                    self._repository.record_ai_memory_message(
                        stored.id,
                        message.sender_platform_id,
                        False,
                        message.received_at,
                    )
                    return ReceiveResult(stored.id, True)
                settings = self._repository.get_random_event_settings()
                if (
                    not board_force_end
                    and not independent_command
                    and not ordinary_tipping_message
                    and not _allows_random_event_command(
                        message.content, event_state, settings
                    )
                ):
                    self._repository.record_ai_memory_message(
                        stored.id,
                        message.sender_platform_id,
                        False,
                        message.received_at,
                    )
                    self._repository.enqueue_outbound(
                        stored.id,
                        settings.blocked_message,
                        0,
                        group_chat_id=(
                            None
                            if group_context is None
                            else group_context.group_chat_id
                        ),
                        destination_chatroom_id=(
                            None
                            if group_context is None
                            else group_context.chatroom_id
                        ),
                    )
                    return ReceiveResult(stored.id, True)
            had_active_game_context = self._repository.user_has_active_game_context(
                message.sender_platform_id
            )
            reply = self._command_handler.handle(message)
            if isinstance(reply, list):
                replies.extend(
                    item if isinstance(item, CommandReply) else CommandReply(item)
                    for item in reply
                )
            elif reply is not None:
                replies.append(
                    reply if isinstance(reply, CommandReply) else CommandReply(reply)
                )
            if not replies:
                mention_content = _ai_mention_content(message.content)
                if mention_content is not None:
                    result = self._repository.try_enqueue_ai_request(
                        stored.id,
                        message.sender_platform_id,
                        mention_content,
                        message.received_at,
                    )
                    if result.state == "not_joined":
                        replies.append(CommandReply("请先用 /入职 名字 加入摸鱼公司。"))
                    elif result.state == "over_limit":
                        replies.append(
                            CommandReply(
                                self._repository.get_ai_assistant_settings().over_limit_reply
                            )
                        )
            eligible = (
                bool(message.content.strip())
                and not message.content.lstrip().startswith(("/", "(", "（"))
                and event_message_status == "none"
                and not had_active_game_context
                and not self._repository.user_has_active_game_context(
                    message.sender_platform_id
                )
            )
            self._repository.record_ai_memory_message(
                stored.id,
                message.sender_platform_id,
                eligible,
                message.received_at,
            )
            for reply_index, reply in enumerate(replies):
                destination_chatroom_id = reply.destination_chatroom_id
                group_chat_id = None
                if reply.delivery_kind == "group" and group_context is not None:
                    group_chat_id = group_context.group_chat_id
                    destination_chatroom_id = (
                        destination_chatroom_id or group_context.chatroom_id
                    )
                if reply.content_type == "image":
                    if reply.image_url is None:
                        raise RuntimeError("图片回复缺少图片地址")
                    self._repository.enqueue_image_outbound(
                        stored.id,
                        reply.image_url,
                        reply_index,
                        image_alt=reply.image_alt or "image",
                        group_chat_id=group_chat_id,
                        destination_chatroom_id=destination_chatroom_id,
                        delivery_kind=reply.delivery_kind,
                    )
                    continue
                if (
                    reply.recall_after_seconds is None
                    and reply.memory_round_id is None
                ):
                    if (
                        reply.destination_chatroom_id is None
                        and reply.delivery_kind == "group"
                    ):
                        self._repository.enqueue_outbound(
                            stored.id,
                            reply.text,
                            reply_index,
                            group_chat_id=group_chat_id,
                            destination_chatroom_id=destination_chatroom_id,
                        )
                    else:
                        self._repository.enqueue_outbound(
                            stored.id,
                            reply.text,
                            reply_index,
                            group_chat_id=group_chat_id,
                            destination_chatroom_id=destination_chatroom_id,
                            delivery_kind=reply.delivery_kind,
                        )
                    continue
                self._repository.enqueue_outbound(
                    stored.id,
                    reply.text,
                    reply_index,
                    recall_after_seconds=reply.recall_after_seconds,
                    memory_round_id=reply.memory_round_id,
                    group_chat_id=group_chat_id,
                    destination_chatroom_id=destination_chatroom_id,
                    delivery_kind=reply.delivery_kind,
                )
            return ReceiveResult(stored.id, True)

    def _enqueue_replies(
        self,
        inbound_message_id: UUID,
        response,
        *,
        default_destination_chatroom_id: str | None = None,
        group_context: GroupMessageContext | None = None,
    ) -> None:
        items = response if isinstance(response, list) else [response]
        for reply_index, item in enumerate(item for item in items if item is not None):
            if isinstance(item, SubmissionReply):
                reply = CommandReply(
                    item.text,
                    destination_chatroom_id=item.destination_chatroom_id,
                    delivery_kind=item.delivery_kind,
                )
            elif isinstance(item, CommandReply):
                reply = item
            else:
                reply = CommandReply(item)
            destination = reply.destination_chatroom_id
            delivery_kind = reply.delivery_kind
            group_chat_id = None
            if (
                destination is None
                and default_destination_chatroom_id is not None
                and not reply.force_group_destination
            ):
                destination = default_destination_chatroom_id
                delivery_kind = "direct"
            elif delivery_kind == "group" and group_context is not None:
                destination = destination or group_context.chatroom_id
                group_chat_id = group_context.group_chat_id
            if reply.content_type == "image":
                if reply.image_url is None:
                    raise RuntimeError("图片回复缺少图片地址")
                self._repository.enqueue_image_outbound(
                    inbound_message_id,
                    reply.image_url,
                    reply_index,
                    image_alt=reply.image_alt or "image",
                    group_chat_id=group_chat_id,
                    destination_chatroom_id=destination,
                    delivery_kind=delivery_kind,
                )
            else:
                self._repository.enqueue_outbound(
                    inbound_message_id,
                    reply.text,
                    reply_index,
                    recall_after_seconds=reply.recall_after_seconds,
                    memory_round_id=reply.memory_round_id,
                    group_chat_id=group_chat_id,
                    destination_chatroom_id=destination,
                    delivery_kind=delivery_kind,
                )


def _allows_random_event_command(content: str, event_state: str, settings) -> bool:
    parts = content.strip().split(maxsplit=1)
    if not parts:
        return False
    command = {
        "/me": "/我",
        "/开始摸鱼躲藏": "/摸鱼躲猫猫",
        "/躲": "/摸鱼躲猫猫",
    }.get(parts[0], parts[0])
    allowed = (
        settings.signup_allowed_commands
        if event_state == "signup"
        else settings.in_progress_allowed_commands
    )
    return command in allowed


def _ai_mention_content(content: str) -> str | None:
    if not content.startswith(BOT_MENTION_PREFIX):
        return None
    value = normalize_ai_mention(content)
    return value or None
