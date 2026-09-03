from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import re

from dzmm_bot.runtime.contracts import InboundMessage

from .repository import (
    CoreRepository,
    RandomEventSubmission,
    RandomEventSubmissionDailyLimitError,
    _normalize_role_variable_braces,
)
from .reply_templates import render_template, template_definition


_ROLE_VARIABLE = re.compile(r"\{([^{}]*\S[^{}]*)\}")
SUBMISSION_COMMANDS = {
    "/投稿",
    "/上一步",
    "/取消投稿",
    "/确认取消投稿",
    "/确认投稿",
    "/我的投稿",
    "/撤回投稿",
    "/修改身份",
    "/删除身份",
    "/继续添加",
    "/事件完成",
    "/修改事件",
    "/删除事件",
}


@dataclass(frozen=True)
class SubmissionReply:
    text: str
    destination_chatroom_id: str | None = None
    delivery_kind: str = "group"


class RandomEventSubmissionHandler:
    def __init__(self, repository: CoreRepository) -> None:
        self._repository = repository

    def handle(
        self, message: InboundMessage
    ) -> SubmissionReply | list[SubmissionReply] | None:
        content = message.content.strip()
        if not content:
            return None
        parts = content.split(maxsplit=1)
        command = parts[0] if parts[0].startswith("/") else None
        now = message.received_at

        if command == "/投稿":
            if len(parts) != 2 or parts[1].strip() != "随机事件":
                return self._reply(message, self._text("/投稿", "usage", now))
            result = self._repository.start_random_event_submission(
                message.sender_platform_id, now
            )
            if result.status == "not_joined":
                return self._reply(message, self._text("/投稿", "not_joined", now))
            if result.status == "no_direct_chat":
                return self._reply(
                    message,
                    self._text("/投稿", "no_direct_chat", now),
                )
            if result.status == "disabled":
                return self._reply(message, self._text("/投稿", "disabled", now))
            if result.submission is None or result.direct_chatroom_id is None:
                raise RuntimeError("投稿草稿启动结果不完整")
            submission = self._normalize_legacy_role_capacity(
                result.submission, now
            )
            prompt = SubmissionReply(
                (
                    self._text("/投稿", "expired", now) + "\n"
                    if result.status == "expired_started"
                    else ""
                ) + self._prompt(submission),
                destination_chatroom_id=result.direct_chatroom_id,
                delivery_kind="direct",
            )
            if message.source_type == "direct":
                return prompt
            return [
                SubmissionReply(self._text("/投稿", "transferred", now)), prompt
            ]

        if command == "/我的投稿":
            return self._reply(
                message,
                self._text(
                    "/我的投稿",
                    "shown",
                    now,
                    {"{投稿列表}": self._submission_list(message.sender_platform_id)},
                ),
            )
        if command == "/撤回投稿":
            return self._withdraw(message, parts)

        draft = self._repository.active_random_event_submission(
            message.sender_platform_id, now
        )
        if draft is None:
            return None
        if message.source_type != "direct":
            return None
        if command is not None and command not in SUBMISSION_COMMANDS:
            return None
        draft = self._normalize_legacy_role_capacity(draft, now)
        if command == "/取消投稿":
            data = deepcopy(draft.content)
            data["_cancel_previous_step"] = draft.current_step
            draft = self._repository.replace_random_event_submission_content(
                draft.id, data, "cancel_confirm", now
            )
            return self._reply(
                message,
                self._text("/取消投稿", "confirm", now),
            )
        if command == "/确认取消投稿":
            if draft.current_step != "cancel_confirm":
                return self._reply(
                    message, self._text("/确认取消投稿", "required", now)
                )
            self._repository.cancel_random_event_submission(
                message.sender_platform_id, now
            )
            return self._reply(
                message, self._text("/确认取消投稿", "cancelled", now)
            )
        if command == "/上一步":
            return self._go_back(message, draft)
        if command == "/确认投稿":
            if draft.current_step != "preview":
                return self._reply(
                    message, self._text("/确认投稿", "incomplete", now)
                )
            try:
                submitted = self._repository.confirm_random_event_submission(
                    message.sender_platform_id, now
                )
            except RandomEventSubmissionDailyLimitError:
                return self._reply(
                    message,
                    self._text("/确认投稿", "daily_limit", now),
                )
            except ValueError as error:
                return self._reply(
                    message,
                    self._text(
                        "/投稿",
                        "invalid_input",
                        now,
                        {"{错误}": str(error), "{当前提示}": self._prompt(draft)},
                    ),
                )
            return self._reply(
                message,
                self._text(
                    "/确认投稿",
                    "submitted",
                    now,
                    {"{投稿编号}": f"{submitted.number:04d}"},
                ),
            )
        if command is not None:
            return self._handle_control(message, draft, command, parts)
        return self._accept_plain_value(message, draft, content)

    def _normalize_legacy_role_capacity(
        self, draft: RandomEventSubmission, now: datetime
    ) -> RandomEventSubmission:
        if draft.current_step != "role_capacity":
            return draft
        data = deepcopy(draft.content)
        roles = data.setdefault("roles", [])
        for role in roles:
            role["capacity"] = 1
        working_role = data.pop("_working_role", None)
        edit_index = data.pop("_editing_role_index", None)
        data.pop("_editing_role_original", None)
        data.pop("_editing_return_step", None)
        data.pop("_editing_events_original", None)
        total = int(data.get("participant_count", 0))
        if (
            isinstance(working_role, str)
            and 1 <= len(working_role) <= 32
            and all(item.get("role") != working_role for item in roles)
            and len(roles) < total
        ):
            role = {"role": working_role, "capacity": 1}
            if isinstance(edit_index, int) and 0 <= edit_index <= len(roles):
                roles.insert(edit_index, role)
            else:
                roles.append(role)
        next_step = "event_name" if len(roles) >= total else "role_name"
        return self._repository.replace_random_event_submission_content(
            draft.id, data, next_step, now
        )

    def _accept_plain_value(
        self, message: InboundMessage, draft: RandomEventSubmission, value: str
    ) -> SubmissionReply:
        data = deepcopy(draft.content)
        step = draft.current_step
        next_step = step
        error: str | None = None
        if step == "scene_name":
            if not 1 <= len(value) <= 64:
                error = "场景名称需为 1～64 字。"
            else:
                data["scene_name"] = value
                next_step = "signup_text"
        elif step == "signup_text":
            if not 1 <= len(value) <= 2000:
                error = "报名公告需为 1～2000 字。"
            else:
                data["signup_text"] = value
                next_step = "participant_count"
        elif step == "participant_count":
            settings = self._repository.get_random_event_settings()
            try:
                count = int(value)
            except ValueError:
                count = 0
            if not 1 <= count <= settings.submission_max_participants:
                error = f"参加人数需为 1～{settings.submission_max_participants} 的整数。"
            else:
                data["participant_count"] = count
                data["roles"] = []
                next_step = "role_name"
        elif step == "role_name":
            roles = data.setdefault("roles", [])
            if not 1 <= len(value) <= 32:
                error = "身份名称需为 1～32 字。"
            elif any(item["role"] == value for item in roles):
                error = "身份名称不能重复。"
            elif len(roles) >= int(data["participant_count"]):
                error = "身份已分配完成。"
            else:
                role = {"role": value, "capacity": 1}
                edit_index = data.pop("_editing_role_index", None)
                data.pop("_editing_role_original", None)
                data.pop("_editing_return_step", None)
                data.pop("_editing_events_original", None)
                if edit_index is None:
                    roles.append(role)
                else:
                    roles.insert(edit_index, role)
                next_step = (
                    "event_name"
                    if len(roles) == int(data["participant_count"])
                    else "role_name"
                )
        elif step == "role_capacity":
            try:
                capacity = int(value)
            except ValueError:
                capacity = 0
            remaining = int(data["participant_count"]) - sum(
                int(item["capacity"]) for item in data.get("roles", [])
            )
            if not 1 <= capacity <= remaining:
                error = f"身份人数需为 1～{remaining}。"
            else:
                role = {"role": data.pop("_working_role"), "capacity": capacity}
                edit_index = data.pop("_editing_role_index", None)
                data.pop("_editing_role_original", None)
                data.pop("_editing_return_step", None)
                data.pop("_editing_events_original", None)
                if edit_index is None:
                    data.setdefault("roles", []).append(role)
                else:
                    data.setdefault("roles", []).insert(edit_index, role)
                remaining -= capacity
                next_step = "role_name" if remaining else "event_name"
        elif step == "event_name":
            if not 1 <= len(value) <= 64:
                error = "事件名称需为 1～64 字。"
            elif len(data.get("events", [])) >= 20:
                error = "事件模板最多 20 个。"
            else:
                data["_working_event"] = value
                next_step = "event_opening"
        elif step == "event_opening":
            value = _normalize_role_variable_braces(
                value, {item["role"] for item in data.get("roles", [])}
            )
            if not 1 <= len(value) <= 2000:
                error = "剧情开场白需为 1～2000 字。"
            else:
                variables = set(_ROLE_VARIABLE.findall(value))
                text_without_variables = _ROLE_VARIABLE.sub("", value)
                if "{" in text_without_variables or "}" in text_without_variables:
                    error = "身份变量括号不完整。"
                elif variables - {item["role"] for item in data.get("roles", [])}:
                    error = "剧情开场白引用了不存在的身份。"
            if error is None:
                event = {
                    "name": data.pop("_working_event"),
                    "opening_text": value,
                }
                edit_index = data.pop("_editing_event_index", None)
                data.pop("_editing_event_original", None)
                data.pop("_editing_return_step", None)
                if edit_index is None:
                    data.setdefault("events", []).append(event)
                else:
                    data.setdefault("events", []).insert(edit_index, event)
                next_step = "event_controls"
        else:
            return self._reply(message, self._prompt(draft))

        if error is not None:
            return self._reply(
                message,
                self._text(
                    "/投稿",
                    "invalid_input",
                    message.received_at,
                    {"{错误}": error, "{当前提示}": self._prompt(draft)},
                ),
            )
        updated = self._repository.replace_random_event_submission_content(
            draft.id, data, next_step, message.received_at
        )
        return self._reply(message, self._prompt(updated))

    def _handle_control(
        self,
        message: InboundMessage,
        draft: RandomEventSubmission,
        command: str,
        parts: list[str],
    ) -> SubmissionReply:
        data = deepcopy(draft.content)
        argument = parts[1].strip() if len(parts) == 2 else ""
        if command == "/继续添加" and draft.current_step == "event_controls":
            updated = self._repository.replace_random_event_submission_content(
                draft.id, data, "event_name", message.received_at
            )
            return self._reply(message, self._prompt(updated))
        if command == "/事件完成" and draft.current_step == "event_controls":
            if not data.get("events"):
                return self._reply(message, "至少需要一个完整事件模板。")
            updated = self._repository.replace_random_event_submission_content(
                draft.id, data, "preview", message.received_at
            )
            return self._reply(message, self._prompt(updated))
        if command in {"/修改身份", "/修改事件"}:
            return self._edit_entry(message, draft, command, argument)
        if command in {"/删除身份", "/删除事件"}:
            return self._delete_entries(message, draft, command, argument)
        return self._reply(message, f"当前步骤不支持 {command}。\n{self._prompt(draft)}")

    def _edit_entry(
        self, message: InboundMessage, draft: RandomEventSubmission,
        command: str, argument: str,
    ) -> SubmissionReply:
        try:
            index = int(argument) - 1
        except ValueError:
            index = -1
        key = "roles" if command == "/修改身份" else "events"
        entries = list(draft.content.get(key, []))
        if not 0 <= index < len(entries):
            return self._reply(message, "编号无效。")
        data = deepcopy(draft.content)
        entry = data[key].pop(index)
        if key == "roles":
            data["_editing_role_index"] = index
            data["_editing_role_original"] = entry
            data["_editing_return_step"] = draft.current_step
            data["_editing_events_original"] = data.get("events", [])
            data["events"] = []
            step = "role_name"
        else:
            data["_editing_event_index"] = index
            data["_editing_event_original"] = entry
            data["_editing_return_step"] = draft.current_step
            step = "event_name"
        updated = self._repository.replace_random_event_submission_content(
            draft.id, data, step, message.received_at
        )
        return self._reply(message, self._prompt(updated))

    def _delete_entries(
        self, message: InboundMessage, draft: RandomEventSubmission,
        command: str, argument: str,
    ) -> SubmissionReply:
        try:
            indexes = sorted({int(value) - 1 for value in argument.split()}, reverse=True)
        except ValueError:
            indexes = []
        key = "roles" if command == "/删除身份" else "events"
        entries = list(draft.content.get(key, []))
        if not indexes or any(index < 0 or index >= len(entries) for index in indexes):
            return self._reply(message, "编号无效。")
        data = deepcopy(draft.content)
        for index in indexes:
            data[key].pop(index)
        if key == "roles":
            data["events"] = []
            step = "role_name"
        else:
            step = "event_name" if not data[key] else "event_controls"
        updated = self._repository.replace_random_event_submission_content(
            draft.id, data, step, message.received_at
        )
        return self._reply(message, self._prompt(updated))

    def _go_back(
        self, message: InboundMessage, draft: RandomEventSubmission
    ) -> SubmissionReply:
        data = deepcopy(draft.content)
        step = draft.current_step
        if step == "cancel_confirm":
            step = data.pop("_cancel_previous_step", "scene_name")
        elif step == "signup_text":
            step = "scene_name"
        elif step == "participant_count":
            step = "signup_text"
        elif step == "role_name":
            roles = data.get("roles", [])
            if "_editing_role_index" in data:
                index = data.pop("_editing_role_index")
                original = data.pop("_editing_role_original", None)
                if original is not None:
                    roles.insert(index, original)
                data["events"] = data.pop("_editing_events_original", [])
                step = data.pop("_editing_return_step", "role_name")
            elif roles:
                roles.pop()
                step = "role_name"
            else:
                step = "participant_count"
        elif step == "role_capacity":
            data.pop("_working_role", None)
            step = "role_name"
        elif step == "event_name":
            if "_editing_event_index" in data:
                index = data.pop("_editing_event_index")
                original = data.pop("_editing_event_original", None)
                if original is not None:
                    data.setdefault("events", []).insert(index, original)
                step = data.pop("_editing_return_step", "event_controls")
            elif data.get("roles"):
                data["roles"].pop()
                data["events"] = []
                step = "role_name"
        elif step == "event_opening":
            data.pop("_working_event", None)
            step = "event_name"
        elif step == "event_controls" and data.get("events"):
            event = data["events"].pop()
            data["_working_event"] = event["name"]
            step = "event_opening"
        elif step == "preview":
            step = "event_controls"
        updated = self._repository.replace_random_event_submission_content(
            draft.id, data, step, message.received_at
        )
        return self._reply(message, self._prompt(updated))

    def _prompt(self, draft: RandomEventSubmission) -> str:
        data = draft.content
        step = draft.current_step
        if step == "scene_name":
            return self._text("/投稿", "prompt_scene_name", draft.updated_at)
        if step == "signup_text":
            return self._text("/投稿", "prompt_signup_text", draft.updated_at)
        if step == "participant_count":
            maximum = self._repository.get_random_event_settings().submission_max_participants
            return self._text(
                "/投稿", "prompt_participant_count", draft.updated_at,
                {"{最大人数}": str(maximum)},
            )
        if step == "role_name":
            total = int(data.get("participant_count", 0))
            used = sum(int(item["capacity"]) for item in data.get("roles", []))
            return self._text(
                "/投稿", "prompt_role_name", draft.updated_at,
                {"{已分配人数}": str(used), "{总人数}": str(total), "{剩余人数}": str(total - used)},
            )
        if step == "role_capacity":
            total = int(data.get("participant_count", 0))
            used = sum(int(item["capacity"]) for item in data.get("roles", []))
            return self._text(
                "/投稿", "prompt_role_capacity", draft.updated_at,
                {"{身份}": data.get("_working_role", ""), "{剩余人数}": str(total - used)},
            )
        if step == "event_name":
            variables = "、".join(f"{{{item['role']}}}" for item in data.get("roles", []))
            return self._text(
                "/投稿", "prompt_event_name", draft.updated_at,
                {"{身份变量}": variables},
            )
        if step == "event_opening":
            return self._text(
                "/投稿", "prompt_event_opening", draft.updated_at,
                {"{事件名称}": data.get("_working_event", "")},
            )
        if step == "event_controls":
            return self._text("/投稿", "prompt_event_controls", draft.updated_at)
        if step == "preview":
            return self._text(
                "/投稿", "preview", draft.updated_at,
                {"{预览正文}": self._preview(draft)},
            )
        return "请继续完成当前投稿。"

    def _preview(self, draft: RandomEventSubmission) -> str:
        data = draft.content
        settings = self._repository.get_random_event_settings()
        roles = "\n".join(
            f"{index}. {item['role']} × {item['capacity']}"
            for index, item in enumerate(data.get("roles", []), 1)
        )
        events = "\n".join(
            f"{index}. {item['name']}：{item['opening_text']}"
            for index, item in enumerate(data.get("events", []), 1)
        )
        return (
            f"【投稿预览 #{draft.number:04d}】\n"
            f"场景：{data.get('scene_name', '')}\n"
            f"报名公告：{data.get('signup_text', '')}\n"
            f"参加人数：{data.get('participant_count', '')}\n"
            f"身份：\n{roles}\n事件模板：\n{events}\n"
            f"目标轮数：{settings.submission_default_target_rounds}\n"
            f"完成奖励：{settings.submission_default_event_reward} 摸鱼币\n"
            f"通过奖励：{settings.submission_approval_reward} 摸鱼币\n"
            "确认无误请发送 /确认投稿。"
        )

    def _submission_list(self, platform_id: str) -> str:
        records = self._repository.recent_random_event_submissions(platform_id)
        if not records:
            return "你还没有随机事件投稿。"
        labels = {
            "draft": "草稿",
            "cancelled": "已取消",
            "pending": "待审核",
            "approved": "已通过",
            "rejected": "已拒绝",
            "withdrawn": "已撤回",
            "expired": "已过期",
        }
        return "【我的投稿】\n" + "\n".join(
            f"#{record.number:04d} {record.content.get('scene_name', '未命名')} · "
            f"{labels.get(record.status, record.status)}"
            + (
                f" · 提交于 {record.submitted_at.strftime('%Y-%m-%d %H:%M')}"
                if record.submitted_at else ""
            )
            + (
                f" · 审核于 {record.reviewed_at.strftime('%Y-%m-%d %H:%M')}"
                if record.reviewed_at else ""
            )
            + (
                f" · 演绎次数：{record.performed_count}"
                if record.status == "approved"
                else ""
            )
            + (f" · {record.rejection_reason}" if record.rejection_reason else "")
            for record in records
        )

    def _withdraw(
        self, message: InboundMessage, parts: list[str]
    ) -> SubmissionReply:
        if len(parts) != 2:
            return self._reply(
                message, self._text("/撤回投稿", "usage", message.received_at)
            )
        try:
            number = int(parts[1].lstrip("#"))
        except ValueError:
            return self._reply(
                message,
                self._text("/撤回投稿", "invalid_number", message.received_at),
            )
        record = self._repository.withdraw_random_event_submission(
            message.sender_platform_id, number, message.received_at
        )
        if record is None:
            return self._reply(
                message, self._text("/撤回投稿", "not_found", message.received_at)
            )
        return self._reply(
            message,
            self._text(
                "/撤回投稿", "withdrawn", message.received_at,
                {"{投稿编号}": f"{number:04d}"},
            ),
        )

    def _text(
        self,
        command: str,
        scenario: str,
        received_at,
        values: dict[str, str] | None = None,
    ) -> str:
        definition = template_definition(command, scenario)
        record = self._repository.get_reply_template(command, scenario)
        template = record.template if record is not None else definition.default
        context = {"{日期}": received_at.date().isoformat(), **(values or {})}
        try:
            return render_template(definition, template, context)
        except ValueError:
            return render_template(definition, definition.default, context)

    @staticmethod
    def _reply(message: InboundMessage, text: str) -> SubmissionReply:
        if message.source_type == "direct":
            return SubmissionReply(
                text,
                destination_chatroom_id=message.chatroom_id,
                delivery_kind="direct",
            )
        return SubmissionReply(text)
