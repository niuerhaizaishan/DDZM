from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

import httpx

from dzmm_bot.runtime.contracts import InboundMessage

from .ai_mentions import ai_mention_content
from .repository import CoreRepository
from .schema import PRIMARY_GROUP_CHAT_ID
from .random_event_submissions import (
    RandomEventSubmissionHandler,
    SUBMISSION_COMMANDS,
    SubmissionReply,
)


_DIRECT_COMMANDS = {
    "/报数", "/发红包", "/抢红包", "/余额", "/我的物品", "/我",
    "/帮助", "/当前游戏", "/我的档案", "/我的部门人数", "/打卡",
    "/编辑档案", "/编辑档案形象", "/商店", "/购买",
    "/使用", "/邀请参与", "/取消使用", "/同意使用", "/拒绝使用",
    "/加入", "/退出", "/开始",
    "/答案", "/继续", "/收手", "/投降", "/跳过", "/结束游戏", "/看牌",
    "/上架暗网", "/取消上架", "/确认", "/报价", "/公开", "/不公开",
    "/查看暗网", "/登陆暗网", "/登录暗网", "/暗网", "/确认收货", "/投诉",
    "/我的公演预约", "/取消公演预约", "/延期",
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
    group_chat_id: UUID | None = None


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
        *,
        cover_image_validator=None,
    ) -> None:
        self._repository = repository
        self._command_handler = command_handler or NoopCommandHandler()
        self._submission_handler = RandomEventSubmissionHandler(repository)
        self._cover_image_validator = cover_image_validator

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
                command = parts[0] if parts else ""
                draft_step = self._repository.performance_draft_step(
                    message.sender_platform_id, message.received_at
                )
                if draft_step is not None and command not in {
                    "/我的公演预约", "/取消公演预约", "/延期"
                }:
                    if message.content_type == "image" and draft_step == "cover":
                        if self._cover_image_validator is None or message.image_url is None:
                            direct_reply = "公演封面读取失败，请重新发送图片。"
                        else:
                            try:
                                cover = self._cover_image_validator.validate(
                                    message.image_url
                                )
                            except ValueError as error:
                                direct_reply = str(error)
                            except httpx.HTTPError:
                                direct_reply = "公演封面读取失败，请重新发送图片。"
                            else:
                                result = self._repository.consume_performance_draft_input(
                                    message.sender_platform_id,
                                    stored.id,
                                    message.received_at,
                                    text=message.content,
                                    image_url=cover.url,
                                    image_alt=message.image_alt,
                                )
                                direct_reply = self._performance_draft_reply(result)
                    else:
                        result = self._repository.consume_performance_draft_input(
                            message.sender_platform_id,
                            stored.id,
                            message.received_at,
                            text=message.content,
                        )
                        direct_reply = self._performance_draft_reply(result)
                elif parts and command in _DIRECT_COMMANDS:
                    direct_reply = self._command_handler.handle(message)
                elif not message.content.lstrip().startswith("/"):
                    direct_reply = self._submission_handler.handle(message)
                    if direct_reply is None:
                        adult_result = self._repository.consume_adult_card_scene(
                            message.sender_platform_id,
                            message.content,
                            message.received_at,
                        )
                        direct_reply = self._adult_card_scene_reply(adult_result)
                        if direct_reply is None:
                            draft_reply = self._repository.consume_dark_market_draft_text(
                                message.sender_platform_id,
                                message.content,
                                message.received_at,
                            )
                            direct_reply = self._dark_market_draft_reply(draft_reply)
                else:
                    return ReceiveResult(stored.id, True)
                self._enqueue_replies(
                    stored.id,
                    direct_reply,
                    default_destination_chatroom_id=message.chatroom_id,
                )
                return ReceiveResult(stored.id, True)
            if group_context is not None:
                performance_state = self._repository.active_performance_state(
                    group_context.group_chat_id
                )
                if performance_state is not None:
                    allowed_command = (
                        performance_state == "performing" and command == "/end"
                    ) or (
                        performance_state == "tipping" and command == "/打赏"
                    )
                    if allowed_command:
                        performance_reply = self._command_handler.handle(message)
                        self._enqueue_replies(
                            stored.id,
                            performance_reply,
                            group_context=group_context,
                        )
                        self._repository.record_ai_memory_message(
                            stored.id,
                            message.sender_platform_id,
                            False,
                            message.received_at,
                        )
                        return ReceiveResult(stored.id, True)
                    if message.content.lstrip().startswith("/"):
                        blocked = (
                            "公演正在进行，仅参演人员可使用 /end。"
                            if performance_state == "performing"
                            else "公演打赏阶段仅开放 /打赏 指令。"
                        )
                        self._repository.enqueue_outbound(
                            stored.id,
                            blocked,
                            group_chat_id=group_context.group_chat_id,
                            destination_chatroom_id=group_context.chatroom_id,
                        )
                        self._repository.record_ai_memory_message(
                            stored.id,
                            message.sender_platform_id,
                            False,
                            message.received_at,
                        )
                        return ReceiveResult(stored.id, True)
                    stage = self._repository.classify_performance_message(
                        message.sender_platform_id,
                        stored.id,
                        message.content,
                        group_context.group_chat_id,
                    )
                    self._repository.record_ai_memory_message(
                        stored.id,
                        message.sender_platform_id,
                        False,
                        message.received_at,
                    )
                    if stage in {"participant", "observer_valid"}:
                        return ReceiveResult(stored.id, True)
                    if stage == "observer_invalid":
                        self._repository.enqueue_outbound(
                            stored.id,
                            "公演正在进行，请使用括号进行场外交流。",
                            group_chat_id=group_context.group_chat_id,
                            destination_chatroom_id=group_context.chatroom_id,
                        )
                        return ReceiveResult(stored.id, True)
            self._repository.record_activity(
                message.sender_platform_id, message.received_at, message.content
            )
            event_message_status = self._repository.record_random_event_round(
                message.sender_platform_id,
                message.received_at,
                message.content,
                (
                    PRIMARY_GROUP_CHAT_ID
                    if group_context is None
                    else group_context.group_chat_id
                ),
            )
            independent_command = bool(
                command_parts
                and command_parts[0] in _RANDOM_EVENT_INDEPENDENT_COMMANDS
            )
            replies: list[CommandReply] = []
            event_state = self._repository.active_random_event_state(
                PRIMARY_GROUP_CHAT_ID
                if group_context is None
                else group_context.group_chat_id
            )
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
                message.sender_platform_id,
                None if group_context is None else group_context.group_chat_id,
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
                settings = self._repository.get_ai_assistant_settings()
                mention_content = ai_mention_content(
                    message.content, settings.trigger_prefixes
                )
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
                    message.sender_platform_id,
                    None if group_context is None else group_context.group_chat_id,
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
                group_chat_id = reply.group_chat_id
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

    @staticmethod
    def _adult_card_scene_reply(result):
        if result is None:
            return None
        messages = {
            "invalid_scene": "场景要求必须是 1–200 字，请重新发送。",
            "invalid_m_count": "期望人数必须是 1–99 的整数，请重新发送。",
            "expired": "卡片局填写已超时，预留卡片已经退回。",
            "m_count_required": (
                f"场景已保存。请继续发送卡片局 #{result.session_number} 的期望人数（1–99）。"
            ),
            "m_completed": f"M卡片局 #{result.session_number} 已发布到来源群。",
            "participants_required": (
                f"场景已保存。请回到来源群回复其他目标发送 "
                f"/邀请参与 {result.session_number}。"
            ),
            "awaiting_consent": (
                f"场景已保存，卡片局 #{result.session_number} 的授权通知已发出。"
            ),
        }
        return messages.get(result.status)

    @staticmethod
    def _dark_market_draft_reply(result):
        if result is None:
            return None
        if result.status == "preview":
            return result.preview_text
        if result.status == "invalid":
            return "填写内容不符合要求，请按当前提示重新发送。"
        if result.status == "expired":
            return "暗网上架草稿已超时，请重新发送 /上架暗网。"
        prompts = {
            "name": "请发送商品名称（1–30 字）。",
            "purpose": "请发送商品用途（1–100 字）。",
            "details": "请发送商品详细信息（1–500 字）。",
            "gender": "请选择匿名性别并发送：男、女或保密。",
            "starting_price": "请发送起拍价（1–99999 的整数）。",
        }
        return prompts.get(result.step)

    @staticmethod
    def _performance_draft_reply(result):
        if result is None:
            return None
        if result.status == "expired":
            return "公演预约草稿已超时，请回群重新发送 /预约公演。"
        if result.status == "submitted":
            return "公演预约已提交审核。"
        if result.status == "date_taken":
            return "该日期已有公演预约，请修改时间后重新提交。"
        if result.status == "owner_busy":
            return "你已有一个未结束的公演预约。"
        if result.status == "image_required":
            return "请发送公演封面图片，或发送 /跳过。"
        if result.status == "confirmation_required":
            return "预约信息已填写完成，发送 /确认 提交审核。"
        if result.status == "invalid":
            return {
                "title": "标题需为 1–50 字，请重新发送。",
                "introduction": "简介需为 1–500 字，请重新发送。",
                "scheduled_at": "时间格式或范围无效，请按 YYYY/MM/DD-HH:MM:SS 重新发送。",
                "participants": "请填写 1–30 名不重复的已入职员工名称。",
            }.get(result.current_step, "填写内容无效，请重新发送。")
        return {
            "introduction": "请发送公演简介（1–500字）。",
            "scheduled_at": "请发送公演时间，格式：2026/12/01-12:00:00。",
            "participants": "请发送参演人员名称，多人请用顿号分隔（1–30人）。",
            "cover": "请发送公演封面图片，或发送 /跳过。",
            "confirm": "预约信息已填写完成，发送 /确认 提交审核。",
        }.get(result.current_step)

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
            group_chat_id = reply.group_chat_id
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
