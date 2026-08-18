from collections import Counter
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dzmm_bot.runtime.contracts import InboundMessage

from .reply_templates import render_template, template_definition
from .repository import (
    BlameGameResult,
    CoreRepository,
    EmployeeNameTakenError,
    blame_settlement_template_values,
    format_employee_number,
    undercover_settlement_template_values,
)
from .service import CommandReply


_BEIJING = ZoneInfo("Asia/Shanghai")
_COMMANDS = {
    "/入职", "/我的物品", "/打卡", "/余额", "/修改名称", "/编辑档案", "/编辑档案形象", "/我的档案", "/发奖金", "/发红包", "/抢红包", "/打赏", "/我", "/商店", "/帮助", "/当前游戏", "/加入", "/退出", "/开始", "/摸鱼躲猫猫", "/记忆考核", "/继续", "/收手", "/投降", "/部门", "/部门人数", "/我的部门人数", "/加入部门", "/切换部门", "/部门申请列表", "/同意部门", "/全部同意部门", "/拒绝部门", "/全部拒绝部门", "/职位", "/晋升", "/晋升申请列表", "/同意", "/全部同意", "/拒绝", "/全部拒绝", "/谁是卧底", "/开始投票", "/投票", "/退出谁是卧底", "/结束游戏", "/甩锅游戏", "/甩锅", "/退出甩锅", "/蹦蹦数字炸弹", "/报数", "/跳过", "/德州扑克", "/看牌", "/过牌", "/跟注", "/加注", "/全下", "/弃牌",
}


def _valid_image_url(value: str | None) -> bool:
    if value is None:
        return False
    parsed = urlsplit(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class GroupCommandHandler:
    def __init__(self, repository: CoreRepository) -> None:
        self._repository = repository

    def handle(self, message: InboundMessage) -> str | list[str] | None:
        content = message.content.strip()
        if not content:
            return None
        command = content.split(maxsplit=1)[0]
        if command == "/摸鱼躲猫猫":
            return None
        if command in {"/开始摸鱼躲藏", "/躲"}:
            command = "/摸鱼躲猫猫"
        if command == "/me":
            command = "/我"
        if command == "/答案":
            parts = content.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                return None
            return self._memory_assessment_answer(
                message.sender_platform_id, parts[1].strip(), message.received_at.astimezone(_BEIJING)
            )
        if command not in _COMMANDS:
            return None
        self._repository.ensure_command_definitions()
        if not self._repository.is_command_enabled(command):
            return None
        received_at = message.received_at.astimezone(_BEIJING)
        group = (
            self._repository.resolve_enabled_group_chat(message.chatroom_id)
            if message.source_type == "group" and message.chatroom_id is not None
            else None
        )
        group_chat_id = None if group is None else group.id
        if (
            group is not None
            and not group.games_enabled
            and command in {
                "/发红包", "/摸鱼躲猫猫", "/记忆考核", "/谁是卧底",
                "/甩锅游戏", "/蹦蹦数字炸弹", "/德州扑克",
            }
        ):
            return self._reply(command, "disabled", received_at)
        if command == "/发红包":
            return self._red_packet_create(
                message, content, received_at, group_chat_id
            )
        if command == "/抢红包":
            return self._red_packet_claim(message, received_at, group_chat_id)
        if command == "/打赏":
            return self._random_event_tip(
                message, content, received_at, group_chat_id
            )
        if command == "/当前游戏":
            return self._current_game(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/入职":
            return self._join(message.sender_platform_id, content, received_at)
        if command == "/蹦蹦数字炸弹":
            return self._number_bomb_start(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/德州扑克":
            return self._texas_holdem_start(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/看牌":
            if message.source_type != "direct":
                return self._reply("/看牌", "group_only", received_at)
            parts = content.split()
            if len(parts) > 2:
                return self._reply("/看牌", "usage", received_at)
            result = self._repository.get_texas_holdem_private_cards(
                message.sender_platform_id, received_at
            )
            if result.status == "choose_group":
                group_list = "\n".join(
                    f"{candidate.index}. {candidate.group_name}"
                    for candidate in result.candidates
                )
                if len(parts) == 1:
                    return self._reply(
                        "/看牌",
                        "choose_group",
                        received_at,
                        {"{群聊列表}": group_list},
                    )
                try:
                    selected_index = int(parts[1])
                    selected = next(
                        candidate
                        for candidate in result.candidates
                        if candidate.index == selected_index
                    )
                except (ValueError, StopIteration):
                    return self._reply(
                        "/看牌",
                        "invalid_group",
                        received_at,
                        {"{群聊列表}": group_list},
                    )
                result = self._repository.get_texas_holdem_private_cards(
                    message.sender_platform_id,
                    received_at,
                    selected.group_chat_id,
                )
            elif len(parts) == 2:
                return self._reply("/看牌", "usage", received_at)
            if result.status == "shown":
                return result.private_message
            return self._reply("/看牌", "no_cards", received_at)
        if command in {"/过牌", "/跟注", "/加注", "/全下", "/弃牌"}:
            return self._texas_holdem_action(
                message.sender_platform_id,
                command,
                content,
                received_at,
                group_chat_id,
            )
        if command == "/开始":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id,
                received_at,
                group_chat_id,
            )
            if summary.game_type == "number_bomb":
                return self._number_bomb_manual_start(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "texas_holdem":
                return self._texas_holdem_manual_start(
                    message.sender_platform_id, received_at, group_chat_id
                )
            return self._reply("/开始", "no_current_game", received_at)
        if command == "/报数":
            if message.source_type != "direct":
                return self._reply("/报数", "group_only", received_at)
            return self._number_bomb_submit(message, content, received_at)
        if command == "/跳过":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id,
                received_at,
                group_chat_id,
            )
            if summary.game_type == "undercover":
                return self._undercover_skip(
                    message.sender_platform_id, content, received_at, group_chat_id
                )
            if summary.game_type == "number_bomb":
                return self._number_bomb_skip(
                    message.sender_platform_id, content, received_at, group_chat_id
                )
            if summary.game_type == "conflict":
                return self._reply("/当前游戏", "conflict", received_at)
            return self._reply("/跳过", "no_current_game", received_at)
        if command == "/甩锅游戏":
            return self._blame_start(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/甩锅":
            return self._blame_transfer(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/退出甩锅":
            return self._blame_leave(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/谁是卧底":
            return self._undercover_start(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/开始投票":
            return self._undercover_start_vote(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/投票":
            return self._undercover_vote(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/退出谁是卧底":
            return self._undercover_leave(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/结束游戏":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id,
                received_at,
                group_chat_id,
            )
            profile = self._repository.get_user_profile(
                message.sender_platform_id
            )
            if (
                profile is not None
                and profile.rank.is_board
                and summary.game_type not in {None, "conflict"}
                and summary.game_id is not None
                and self._repository.force_end_gameplay(
                    summary.game_type,
                    summary.game_id,
                    received_at,
                    group_chat_id,
                )
            ):
                return None
            if summary.game_type == "number_bomb":
                return self._number_bomb_end(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "texas_holdem":
                return self._reply("/结束游戏", "texas_cannot_end", received_at)
            if summary.game_type == "blame_bomb":
                return self._blame_end(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "undercover":
                return self._undercover_end(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "memory_duel" and summary.state == "waiting_opponent":
                return self._memory_assessment_cancel_waiting(
                    "/结束游戏",
                    message.sender_platform_id,
                    received_at,
                    group_chat_id,
                )
            if summary.game_type in {"memory_duel", "memory_single"}:
                return self._reply("/结束游戏", "memory_use_exit", received_at)
            if summary.game_type == "conflict":
                return self._reply("/当前游戏", "conflict", received_at)
            return self._reply("/结束游戏", "no_current_game", received_at)
        if command == "/打卡":
            return self._check_in(message.sender_platform_id, received_at)
        if command == "/余额":
            return self._balance(message.sender_platform_id, received_at)
        if command == "/修改名称":
            return self._rename(message.sender_platform_id, content, received_at)
        if command == "/编辑档案":
            return self._edit_profile(
                message.sender_platform_id, content, received_at
            )
        if command == "/编辑档案形象":
            return self._edit_profile_image(message, content, received_at)
        if command == "/我的档案":
            return self._my_profile(message.sender_platform_id, received_at)
        if command == "/发奖金":
            return self._grant_bonus(
                message.sender_platform_id, content, received_at
            )
        if command == "/我":
            return self._me(message.sender_platform_id, received_at)
        if command == "/我的物品":
            return self._inventory(message.sender_platform_id, received_at)
        if command == "/商店":
            return self._shop(received_at)
        if command == "/部门":
            return self._departments(received_at)
        if command == "/部门人数":
            return self._department_headcounts(
                message.sender_platform_id, command, received_at
            )
        if command == "/我的部门人数":
            return self._department_headcounts(
                message.sender_platform_id, command, received_at
            )
        if command == "/加入部门":
            return self._join_department(message.sender_platform_id, content, received_at)
        if command == "/切换部门":
            return self._switch_department(message.sender_platform_id, content, received_at)
        if command == "/部门申请列表":
            return self._department_request_list(message.sender_platform_id, received_at)
        if command in {"/同意部门", "/拒绝部门", "/全部同意部门", "/全部拒绝部门"}:
            return self._department_decision(
                message.sender_platform_id, command, content, received_at
            )
        if command == "/职位":
            return self._positions(received_at)
        if command == "/晋升":
            return self._request_promotion(message.sender_platform_id, received_at)
        if command == "/晋升申请列表":
            return self._promotion_list(message.sender_platform_id, received_at)
        if command in {"/同意", "/拒绝", "/全部同意", "/全部拒绝"}:
            return self._promotion_decision(
                message.sender_platform_id, command, content, received_at
            )
        if command == "/加入":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id,
                received_at,
                group_chat_id,
            )
            if summary.game_type == "number_bomb":
                return self._number_bomb_join(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "texas_holdem":
                return self._texas_holdem_join(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "blame_bomb":
                return self._blame_join(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "undercover":
                return self._undercover_join(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "conflict":
                return self._reply("/当前游戏", "conflict", received_at)
            return self._event_join(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/退出":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id,
                received_at,
                group_chat_id,
            )
            if summary.game_type == "number_bomb":
                return self._number_bomb_leave(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "texas_holdem":
                return self._texas_holdem_leave(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "blame_bomb":
                return self._blame_leave(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "undercover":
                return self._undercover_leave(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "memory_duel":
                if summary.state == "waiting_opponent":
                    return self._memory_assessment_cancel_waiting(
                        "/退出",
                        message.sender_platform_id,
                        received_at,
                        group_chat_id,
                    )
                return self._memory_assessment_surrender(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "conflict":
                return self._reply("/当前游戏", "conflict", received_at)
            return self._event_leave(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/摸鱼躲猫猫":
            return self._hide_and_seek(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/记忆考核":
            return self._memory_assessment_start(
                message.sender_platform_id, content, received_at, group_chat_id
            )
        if command == "/继续":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id,
                received_at,
                group_chat_id,
            )
            if summary.game_type == "number_bomb":
                return self._number_bomb_continue(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "undercover":
                return self._undercover_continue(
                    message.sender_platform_id, received_at, group_chat_id
                )
            if summary.game_type == "conflict":
                return self._reply("/当前游戏", "conflict", received_at)
            return self._memory_assessment_continue(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/收手":
            return self._memory_assessment_cash_out(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/投降":
            return self._memory_assessment_surrender(
                message.sender_platform_id, received_at, group_chat_id
            )
        return self._help(content, received_at)

    def _red_packet_create(
        self, message, content: str, received_at, group_chat_id=None
    ):
        if message.source_type != "group":
            return CommandReply(
                self._reply("/发红包", "group_only", received_at),
                destination_chatroom_id=message.chatroom_id,
                delivery_kind="direct",
            )
        parts = content.split()
        if len(parts) != 3:
            return self._reply("/发红包", "usage", received_at)
        if any(not part.isascii() or not part.isdigit() for part in parts[1:]):
            return self._reply("/发红包", "invalid_parameters", received_at)
        arguments = (
            message.sender_platform_id,
            int(parts[1]),
            int(parts[2]),
            received_at,
        )
        result = (
            self._repository.create_red_packet(*arguments)
            if group_chat_id is None
            else self._repository.create_red_packet(
                *arguments, group_chat_id=group_chat_id
            )
        )
        if result.status != "created":
            return self._reply("/发红包", result.status, received_at)
        settings = self._repository.get_red_packet_settings()
        return self._reply(
            "/发红包",
            "created",
            received_at,
            {
                "{发起者}": result.issuer_display_name,
                "{人数}": result.player_count,
                "{总金额}": result.total_amount,
                "{过期分钟}": settings.expiry_minutes,
            },
        )

    def _red_packet_claim(self, message, received_at, group_chat_id=None):
        if message.source_type != "group":
            return CommandReply(
                self._reply("/抢红包", "group_only", received_at),
                destination_chatroom_id=message.chatroom_id,
                delivery_kind="direct",
            )
        result = (
            self._repository.claim_red_packet(
                message.sender_platform_id, received_at
            )
            if group_chat_id is None
            else self._repository.claim_red_packet(
                message.sender_platform_id,
                received_at,
                group_chat_id=group_chat_id,
            )
        )
        if result.status not in {"claimed", "completed"}:
            return self._reply("/抢红包", result.status, received_at)
        claimed = self._reply(
            "/抢红包",
            "claimed",
            received_at,
            {
                "{领取者}": result.claimant_display_name,
                "{领取金额}": self._red_packet_amount(result.amount),
                "{剩余份数}": result.player_count - result.claimed_count,
                "{人数}": result.player_count,
            },
        )
        if result.status == "claimed":
            return claimed
        best = max(result.claims, key=lambda item: item.amount)
        worst = min(result.claims, key=lambda item: item.amount)
        lines = "\n".join(
            f"{index}. {item.display_name}：{self._red_packet_amount(item.amount)}"
            for index, item in enumerate(result.claims, 1)
        )
        completed = self._reply(
            "/抢红包",
            "completed",
            received_at,
            {
                "{领取结果}": lines,
                "{手气最佳}": f"{best.display_name}（{self._red_packet_amount(best.amount)}）",
                "{手气最差}": f"{worst.display_name}（{self._red_packet_amount(worst.amount)}）",
            },
        )
        return [claimed, completed]

    def _red_packet_amount(self, amount: int) -> str:
        if amount == 0:
            return "空包"
        return f"{amount} {self._repository.get_game_settings().currency_name}"

    def _current_game(self, platform_id: str, received_at, group_chat_id=None) -> str:
        summary = self._repository.active_gameplay_summary(
            platform_id, received_at, group_chat_id
        )
        if summary.game_type is None:
            return self._reply("/当前游戏", "none", received_at)
        if summary.game_type == "conflict":
            return self._reply("/当前游戏", "conflict", received_at)
        game_name = {
            "texas_holdem": "德州扑克",
            "number_bomb": "蹦蹦数字炸弹",
            "blame_bomb": "甩锅游戏",
            "undercover": "谁是卧底",
            "memory_duel": "记忆考核对战",
            "memory_single": "记忆考核",
            "random_event": "随机事件",
        }[summary.game_type]
        if (
            summary.game_type == "number_bomb"
            and summary.mode == "points_tournament"
        ):
            game_name = "蹦蹦数字炸弹积分赛"
        state_name = {
            "signup": "报名中",
            "waiting_opponent": "等待对手",
            "collecting": "报数中",
            "waiting_continue": "等待继续",
            "awaiting_continue": "等待继续",
            "in_progress": "进行中",
            "tipping": "打赏中",
            "dealing": "发牌中",
            "preflop": "翻牌前",
            "flop": "翻牌圈",
            "turn": "转牌圈",
            "river": "河牌圈",
        }.get(summary.state, "进行中")
        if (
            summary.game_type == "number_bomb"
            and summary.mode == "points_tournament"
        ):
            state_name = (
                f"{state_name}（第 {summary.round_number}/{summary.maximum_rounds} 轮；"
                f"你的积分：{summary.actor_total_points or 0} 分）"
            )
        role_name = {
            "participant": "参与者",
            "candidate": "下一轮候选",
            "nonparticipant": "未参与",
        }.get(summary.actor_role, summary.actor_role)
        return self._reply(
            "/当前游戏",
            "shown",
            received_at,
            {
                "{游戏}": game_name,
                "{状态}": state_name,
                "{身份}": role_name,
                "{参与者}": "、".join(summary.participant_names) or "暂无",
                "{可用指令}": "、".join(summary.available_commands) or "暂无",
            },
        )

    def _join(self, platform_id: str, content: str, received_at) -> str:
        parts = content.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            return self._reply("/入职", "missing_name", received_at)
        settings = self._repository.get_game_settings()
        try:
            employee, created = self._repository.create_user(
                platform_id,
                parts[1].strip(),
                received_at,
                settings.onboarding_bonus,
            )
        except EmployeeNameTakenError:
            return self._reply("/入职", "name_taken", received_at)
        if not created:
            return self._reply(
                "/入职",
                "already_joined",
                received_at,
                {"{昵称}": employee.display_name, "{余额}": employee.balance},
            )
        return self._reply(
            "/入职",
            "joined",
            received_at,
            {
                "{昵称}": employee.display_name,
                "{工号}": format_employee_number(employee.employee_number),
                "{余额}": employee.balance,
            },
        )

    def _check_in(self, platform_id: str, received_at) -> str:
        employee = self._repository.find_user(platform_id)
        if employee is None:
            return self._reply("/打卡", "not_joined", received_at)
        settings = self._repository.get_game_settings()
        if not self._repository.check_in(employee, received_at, settings.checkin_reward):
            return self._reply(
                "/打卡", "already_checked_in", received_at, {"{昵称}": employee.display_name}
            )
        return self._reply(
            "/打卡",
            "checked_in",
            received_at,
            {
                "{昵称}": employee.display_name,
                "{余额}": employee.balance,
                "{打卡奖励}": settings.checkin_reward,
            },
        )

    def _balance(self, platform_id: str, received_at) -> str:
        employee = self._repository.find_user(platform_id)
        if employee is None:
            return self._reply("/余额", "not_joined", received_at)
        return self._reply(
            "/余额",
            "shown",
            received_at,
            {"{昵称}": employee.display_name, "{余额}": employee.balance},
        )

    def _grant_bonus(self, platform_id: str, content: str, received_at) -> str:
        payload = content[len("/发奖金"):].strip()
        parts = payload.rsplit(maxsplit=1)
        if len(parts) != 2:
            return self._reply("/发奖金", "usage", received_at)
        target, amount_text = parts
        target = target.strip()
        if not target:
            return self._reply("/发奖金", "usage", received_at)
        if not amount_text.isascii() or not amount_text.isdigit():
            return self._reply("/发奖金", "invalid_amount", received_at)

        result = self._repository.grant_board_bonus(
            platform_id, target, int(amount_text), received_at
        )
        if result.status == "granted":
            values = {
                "{发放者}": result.issuer_display_name,
                "{金额}": result.amount,
                "{人数}": result.recipient_count,
                "{收款人}": result.recipient_display_name,
            }
            scenario = "all_granted" if target == "全部" else "single_granted"
            return self._reply("/发奖金", scenario, received_at, values)
        if result.status == "ambiguous_target":
            return self._reply(
                "/发奖金",
                "ambiguous_target",
                received_at,
                {"{候选员工}": "、".join(result.candidate_labels)},
            )
        return self._reply("/发奖金", result.status, received_at)

    def _rename(self, platform_id: str, content: str, received_at) -> str:
        new_name = content[len("/修改名称"):].strip()
        if not new_name:
            return self._reply("/修改名称", "usage", received_at)
        result = self._repository.rename_user(platform_id, new_name)
        if result.status == "renamed":
            return self._reply(
                "/修改名称",
                "renamed",
                received_at,
                {"{旧名称}": result.old_name, "{新名称}": result.new_name},
            )
        return self._reply("/修改名称", result.status, received_at)

    def _me(self, platform_id: str, received_at) -> str:
        profile = self._repository.get_user_profile(platform_id)
        if profile is None:
            return self._reply("/我", "not_joined", received_at)
        employee = profile.user
        activity = self._repository.personal_activity(platform_id, received_at)
        if activity is None:
            raise RuntimeError("employee disappeared")
        return self._reply(
            "/我",
            "shown",
            received_at,
            {
                "{昵称}": employee.display_name,
                "{工号}": format_employee_number(employee.employee_number),
                "{余额}": employee.balance,
                "{活跃等级}": f"LV{activity.level}",
                "{今日收益}": self._repository.today_income(employee.id, received_at),
                "{连续打卡天数}": self._repository.consecutive_checkin_days(
                    employee.id, received_at
                ),
                "{职位}": profile.rank.name,
                "{职级}": profile.rank.level_label,
                "{部门}": profile.department.name,
            },
        )

    def _edit_profile(self, platform_id: str, content: str, received_at) -> str:
        profile_text = content[len("/编辑档案"):].strip()
        if not profile_text:
            return self._reply("/编辑档案", "usage", received_at)
        if len(profile_text) > 800:
            return self._reply("/编辑档案", "too_long", received_at)
        result = self._repository.edit_own_profile(platform_id, profile_text)
        if result.status == "insufficient_balance":
            settings = self._repository.get_profile_settings()
            game_settings = self._repository.get_game_settings()
            return self._reply(
                "/编辑档案",
                result.status,
                received_at,
                {
                    "{编辑费用}": settings.edit_cost,
                    "{货币}": game_settings.currency_name,
                },
            )
        return self._reply("/编辑档案", result.status, received_at)

    def _edit_profile_image(
        self, message: InboundMessage, content: str, received_at
    ) -> str:
        profile_text = self._repository.get_personal_profile(
            message.sender_platform_id
        )
        if profile_text is None:
            return self._reply("/编辑档案形象", "not_joined", received_at)
        if not profile_text.strip():
            return self._reply("/编辑档案形象", "profile_required", received_at)
        reference = message.reference
        if (
            content != "/编辑档案形象"
            or reference is None
            or reference.content_type != "image"
            or not _valid_image_url(reference.image_url)
        ):
            return self._reply("/编辑档案形象", "usage", received_at)
        result = self._repository.edit_own_profile_image(
            message.sender_platform_id, reference.image_url
        )
        if result.status == "insufficient_balance":
            settings = self._repository.get_profile_settings()
            game_settings = self._repository.get_game_settings()
            return self._reply(
                "/编辑档案形象",
                result.status,
                received_at,
                {
                    "{编辑费用}": settings.edit_cost,
                    "{货币}": game_settings.currency_name,
                },
            )
        return self._reply("/编辑档案形象", result.status, received_at)

    def _my_profile(self, platform_id: str, received_at) -> str | list[CommandReply]:
        details = self._repository.get_personal_profile_details(platform_id)
        if details is None:
            return self._reply("/我的档案", "not_joined", received_at)
        profile_text, image_url = details
        if not profile_text:
            return self._reply("/我的档案", "empty", received_at)
        text = self._reply(
            "/我的档案", "shown", received_at, {"{档案内容}": profile_text}
        )
        if image_url is None:
            return text
        return [
            CommandReply(text),
            CommandReply(
                "", content_type="image", image_url=image_url, image_alt="档案形象"
            ),
        ]

    def _join_department(self, platform_id: str, content: str, received_at) -> str:
        parts = content.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            return self._reply("/加入部门", "usage", received_at)
        profile = self._repository.get_user_profile(platform_id)
        if profile is None:
            return self._reply("/加入部门", "not_joined", received_at)
        if not profile.department.is_default:
            return self._reply("/加入部门", "already_assigned", received_at)
        result = self._repository.request_department_change(
            platform_id, parts[1].strip(), received_at
        )
        if result.status == "not_joined":
            return self._reply("/加入部门", "not_joined", received_at)
        if result.status == "requested":
            return self._reply(
                "/加入部门",
                "requested",
                received_at,
                {"{昵称}": profile.user.display_name, "{部门}": parts[1].strip()},
            )
        if result.status == "joined":
            return self._reply(
                "/加入部门",
                "joined",
                received_at,
                {"{昵称}": profile.user.display_name, "{部门}": parts[1].strip()},
            )
        if result.status == "already_pending":
            return self._reply("/加入部门", "already_pending", received_at)
        return self._reply("/加入部门", "unknown_department", received_at)

    def _switch_department(self, platform_id: str, content: str, received_at) -> str:
        parts = content.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            return self._reply("/切换部门", "usage", received_at)
        profile = self._repository.get_user_profile(platform_id)
        if profile is None:
            return self._reply("/切换部门", "not_joined", received_at)
        if profile.department.is_default:
            return self._reply("/切换部门", "must_join_first", received_at)
        result = self._repository.request_department_change(
            platform_id, parts[1].strip(), received_at
        )
        if result.status == "requested":
            return self._reply(
                "/切换部门",
                "requested",
                received_at,
                {"{昵称}": profile.user.display_name, "{部门}": parts[1].strip()},
            )
        if result.status == "switched":
            return self._reply(
                "/切换部门",
                "switched",
                received_at,
                {"{昵称}": profile.user.display_name, "{部门}": parts[1].strip()},
            )
        if result.status == "already_in_department":
            return self._reply("/切换部门", "already_in_department", received_at)
        if result.status == "already_pending":
            return self._reply("/切换部门", "already_pending", received_at)
        return self._reply("/切换部门", "unknown_department", received_at)

    def _departments(self, received_at) -> str:
        lines = [
            f"{department.name}：{department.description or '暂无说明'}"
            for department in self._repository.list_departments()
            if department.enabled and not department.is_default
        ]
        return self._reply(
            "/部门", "shown", received_at, {"{部门列表}": "\n".join(lines)}
        )

    def _department_headcounts(
        self, platform_id: str, command: str, received_at
    ) -> str:
        profile = self._repository.get_user_profile(platform_id)
        if profile is None:
            return self._reply(command, "not_joined", received_at)
        if command == "/我的部门人数":
            headcount = self._repository.get_user_department_headcount(platform_id)
            headcounts = () if headcount is None else (headcount,)
        else:
            headcounts = self._repository.list_department_headcounts()
        blocks = []
        for item in headcounts:
            lines = [
                f"{item.department_name}：共 {item.total_count} 人",
                *(f"{rank.rank_name}：{rank.count} 人" for rank in item.ranks),
            ]
            if item.highest_rank_name and item.highest_rank_members:
                name_counts = Counter(
                    member.display_name for member in item.highest_rank_members
                )
                member_labels = [
                    (
                        f"{member.display_name} "
                        f"{format_employee_number(member.employee_number)}"
                        if name_counts[member.display_name] > 1
                        else member.display_name
                    )
                    for member in item.highest_rank_members
                ]
                lines.append(
                    f"最高职位者：{item.highest_rank_name} {'、'.join(member_labels)}"
                )
            blocks.append("\n".join(lines))
        return self._reply(
            command, "shown", received_at, {"{部门统计}": "\n\n".join(blocks)}
        )

    def _department_request_list(self, platform_id: str, received_at) -> str:
        requests = self._repository.list_approvable_department_requests(
            platform_id, received_at
        )
        if not requests:
            return self._reply("/部门申请列表", "empty", received_at)
        lines = [
            f"{request.number}. {request.applicant_name}：{request.source_department_name} → {request.target_department_name}（剩余 {max(0, int((request.expires_at - received_at).total_seconds() // 3600))} 小时）"
            for request in requests
        ]
        return self._reply(
            "/部门申请列表", "shown", received_at, {"{申请列表}": "\n".join(lines)}
        )

    def _department_decision(
        self, platform_id: str, command: str, content: str, received_at
    ) -> str:
        decision = "approved" if "同意" in command else "rejected"
        requests = self._repository.list_approvable_department_requests(
            platform_id, received_at
        )
        if command.startswith("/全部"):
            numbers = [request.number for request in requests]
        else:
            parts = content.split()[1:]
            if not parts or any(not part.isdigit() or int(part) < 1 for part in parts):
                return self._reply(command, "usage", received_at)
            numbers = [int(part) for part in parts]
        if not numbers:
            return self._reply(command, "empty", received_at)
        request_by_number = {request.number: request for request in requests}
        results = self._repository.decide_department_requests(
            platform_id, numbers, decision, received_at
        )
        replies: list[str] = []
        for result in results:
            request = request_by_number.get(result.number)
            if result.status == "approved" and request is not None:
                replies.append(
                    self._reply(
                        command,
                        "approved",
                        received_at,
                        {"{昵称}": request.applicant_name, "{部门}": request.target_department_name},
                    )
                )
            elif result.status == "rejected" and request is not None:
                replies.append(
                    self._reply(command, "rejected", received_at, {"{昵称}": request.applicant_name})
                )
            else:
                replies.append(self._reply(command, "unavailable", received_at))
        return "\n".join(replies)

    def _positions(self, received_at) -> str:
        currency_name = self._repository.get_game_settings().currency_name
        lines = []
        for rank in self._repository.list_ranks():
            if not rank.enabled:
                continue
            promotion = "不可申请" if rank.is_board else f"晋升价格 {rank.promotion_price} {currency_name}"
            games = "不限" if rank.multiplayer_game_limit < 0 else str(rank.multiplayer_game_limit)
            management = "可参与群内管理" if rank.has_group_management else "无群内管理权限"
            lines.append(
                f"{rank.name}（{rank.level_label}）：{promotion}；投票权益 {rank.vote_weight}；多人小游戏发起 {games} 次；{management}"
            )
        return self._reply(
            "/职位", "shown", received_at, {"{职位列表}": "\n".join(lines)}
        )

    def _request_promotion(self, platform_id: str, received_at) -> str:
        result = self._repository.request_promotion(platform_id, received_at)
        if result.status == "not_joined":
            return self._reply("/晋升", "not_joined", received_at)
        if result.status == "requested":
            profile = self._repository.get_user_profile(platform_id)
            if profile is None:
                raise RuntimeError("employee disappeared")
            target = next(
                rank
                for rank in self._repository.list_ranks()
                if rank.id == result.request.target_rank_id
            )
            return self._reply(
                "/晋升",
                "requested",
                received_at,
                {
                    "{昵称}": profile.user.display_name,
                    "{当前职位}": profile.rank.name,
                    "{目标职位}": target.name,
                    "{晋升价格}": result.request.price,
                    "{货币}": self._repository.get_game_settings().currency_name,
                },
            )
        if result.status == "already_pending":
            return self._reply("/晋升", "already_pending", received_at)
        return self._reply("/晋升", "no_next_rank", received_at)

    def _promotion_list(self, platform_id: str, received_at) -> str:
        requests = self._repository.list_approvable_promotions(platform_id, received_at)
        if not requests:
            return self._reply("/晋升申请列表", "empty", received_at)
        lines = [
            f"{request.number}. {request.applicant_name}：{request.source_rank_name} → {request.target_rank_name}（{request.price} {self._repository.get_game_settings().currency_name}，剩余 {max(0, int((request.expires_at - received_at).total_seconds() // 3600))} 小时）"
            for request in requests
        ]
        return self._reply(
            "/晋升申请列表", "shown", received_at, {"{申请列表}": "\n".join(lines)}
        )

    def _promotion_decision(
        self, platform_id: str, command: str, content: str, received_at
    ) -> str:
        decision = "approved" if "同意" in command else "rejected"
        requests = self._repository.list_approvable_promotions(platform_id, received_at)
        if command.startswith("/全部"):
            numbers = [request.number for request in requests]
        else:
            parts = content.split()[1:]
            if not parts or any(not part.isdigit() or int(part) < 1 for part in parts):
                return self._reply(command, "usage", received_at)
            numbers = [int(part) for part in parts]
        if not numbers:
            return self._reply(command, "empty", received_at)
        request_by_number = {request.number: request for request in requests}
        results = self._repository.decide_promotions(platform_id, numbers, decision, received_at)
        replies: list[str] = []
        for result in results:
            request = request_by_number.get(result.number)
            if result.status == "approved" and request is not None:
                replies.append(
                    self._reply(
                        command,
                        "approved",
                        received_at,
                        {
                            "{昵称}": request.applicant_name,
                            "{目标职位}": request.target_rank_name,
                            "{晋升价格}": request.price,
                            "{货币}": self._repository.get_game_settings().currency_name,
                        },
                    )
                )
            elif result.status == "rejected" and request is not None:
                replies.append(
                    self._reply(command, "rejected", received_at, {"{昵称}": request.applicant_name})
                )
            elif result.status == "insufficient_balance":
                replies.append(self._reply(command, "insufficient_balance", received_at))
            else:
                replies.append(self._reply(command, "unavailable", received_at))
        return "\n".join(replies)

    def _inventory(self, platform_id: str, received_at) -> str:
        employee = self._repository.find_user(platform_id)
        if employee is None:
            return self._reply("/我的物品", "not_joined", received_at)
        items = self._repository.list_user_items(employee.id)
        return self._reply(
            "/我的物品",
            "shown",
            received_at,
            {
                "{昵称}": employee.display_name,
                "{物品列表}": "暂时空空如也。"
                if not items
                else "\n".join(f"{name} × {quantity}" for name, quantity in items),
            },
        )

    def _shop(self, received_at) -> str:
        items = self._repository.list_active_items()
        if not items:
            return self._reply("/商店", "empty", received_at)
        currency_name = self._repository.get_game_settings().currency_name
        return self._reply(
            "/商店",
            "items_available",
            received_at,
            {
                "{商店列表}": "\n".join(
                    f"{item.name}（{item.price} {currency_name}，库存 {item.stock}）"
                    for item in items
                )
            },
        )

    def _undercover_start(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return self._reply("/谁是卧底", "usage", received_at)
        result = self._repository.start_undercover_signup(
            platform_id,
            int(parts[1]),
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "signup_started":
            return self._reply(
                "/谁是卧底",
                "signup_started",
                received_at,
                {"{人数}": int(parts[1]), "{当前人数}": result.player_count},
            )
        scenarios = {
            "not_joined": "not_joined",
            "direct_chat_required": "direct_chat_required",
            "disabled": "disabled",
            "multiplayer_active": "multiplayer_active",
            "already_active": "already_active",
            "invalid_player_count": "invalid_player_count",
        }
        return self._reply("/谁是卧底", scenarios[result.status], received_at)

    def _blame_start(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return self._reply("/甩锅游戏", "usage", received_at)
        player_count = int(parts[1])
        result = self._repository.start_blame_game(
            platform_id,
            player_count,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "signup_started":
            user = self._repository.find_user(platform_id)
            return self._reply(
                "/甩锅游戏",
                "signup_started",
                received_at,
                {"{昵称}": user.display_name, "{人数}": player_count, "{当前人数}": 1},
            )
        if result.status == "invalid_player_count":
            return self._reply("/甩锅游戏", "usage", received_at)
        return self._reply(
            "/甩锅游戏",
            result.status,
            received_at,
            {"{保证金}": max(player_count - 1, 0)},
        )

    def _number_bomb_start(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        modes = {
            "/蹦蹦数字炸弹": "standard",
            "/蹦蹦数字炸弹 积分赛": "points_tournament",
        }
        mode = modes.get(content)
        if mode is None:
            return self._reply("/蹦蹦数字炸弹", "usage", received_at)
        result = self._repository.start_number_bomb_game(
            platform_id,
            received_at,
            mode=mode,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "signup_started":
            user = self._repository.find_user(platform_id)
            return self._reply(
                "/蹦蹦数字炸弹",
                (
                    "points_signup_started"
                    if mode == "points_tournament"
                    else "signup_started"
                ),
                received_at,
                {
                    "{昵称}": user.display_name,
                    "{当前人数}": result.player_count,
                },
            )
        scenario = result.status if result.status in {
            "not_joined", "direct_chat_required", "disabled",
            "multiplayer_active", "already_active"
        } else "multiplayer_active"
        return self._reply("/蹦蹦数字炸弹", scenario, received_at)

    def _texas_holdem_start(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split()
        if len(parts) != 2:
            return self._reply("/德州扑克", "usage", received_at)
        try:
            buy_in = int(parts[1])
        except ValueError:
            return self._reply("/德州扑克", "usage", received_at)
        settings = self._repository.get_texas_holdem_settings()
        result = self._repository.start_texas_holdem_signup(
            platform_id,
            buy_in,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        values = {
            "{带入}": buy_in,
            "{最低带入}": settings.minimum_buy_in,
            "{最高带入}": settings.maximum_buy_in,
            "{最少人数}": settings.minimum_players,
        }
        if result.status == "created":
            user = self._repository.find_user(platform_id)
            values["{昵称}"] = "玩家" if user is None else user.display_name
        scenario = result.status if result.status in {
            "created", "not_joined", "direct_chat_required", "disabled",
            "invalid_buy_in", "insufficient_balance", "daily_limit",
            "already_active", "multiplayer_active",
        } else "multiplayer_active"
        return self._reply("/德州扑克", scenario, received_at, values)

    def _texas_holdem_join(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.join_texas_holdem(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        scenarios = {
            "joined": "texas_joined",
            "already_joined": "texas_already_joined",
            "direct_chat_required": "texas_direct_chat_required",
            "insufficient_balance": "texas_insufficient_balance",
            "full": "texas_full",
        }
        values = {"{当前人数}": result.player_count}
        if result.status == "joined":
            user = self._repository.find_user(platform_id)
            values["{昵称}"] = "玩家" if user is None else user.display_name
        return self._reply(
            "/加入",
            scenarios.get(result.status, "texas_cannot_join"),
            received_at,
            values,
        )

    def _texas_holdem_manual_start(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.start_texas_holdem_hand(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        settings = self._repository.get_texas_holdem_settings()
        scenario = {
            "dealing": "texas_dealing",
            "insufficient_players": "texas_insufficient_players",
            "missing_direct_chats": "texas_missing_direct_chats",
        }.get(result.status, "texas_cannot_start")
        return self._reply(
            "/开始",
            scenario,
            received_at,
            {"{人数}": result.player_count, "{最少人数}": settings.minimum_players},
        )

    def _texas_holdem_leave(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.leave_texas_holdem(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.public_message:
            return result.public_message
        scenario = {
            "signup_left": "texas_signup_left",
            "acted": "texas_folded",
            "settled": "texas_folded",
        }.get(result.status, "texas_cannot_leave")
        return self._reply("/退出", scenario, received_at)

    def _texas_holdem_action(
        self,
        platform_id: str,
        command: str,
        content: str,
        received_at,
        group_chat_id=None,
    ) -> str | list[str]:
        action = {
            "/过牌": "check",
            "/跟注": "call",
            "/加注": "raise",
            "/全下": "all_in",
            "/弃牌": "fold",
        }[command]
        parts = content.split()
        amount = None
        if command == "/加注":
            if len(parts) != 2:
                return self._reply(command, "usage", received_at)
            try:
                amount = int(parts[1])
            except ValueError:
                return self._reply(command, "usage", received_at)
        elif len(parts) != 1:
            return self._reply(command, "cannot_act", received_at, {"{原因}": "指令不带参数"})
        result = self._repository.act_texas_holdem(
            platform_id,
            action,
            amount,
            None,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status in {"acted", "street_advanced", "settled"}:
            user = self._repository.find_user(platform_id)
            acknowledgement = self._reply(
                command,
                "acted",
                received_at,
                {
                    "{昵称}": "玩家" if user is None else user.display_name,
                    "{座位}": result.actor_seat or "—",
                    "{投入}": result.committed_amount,
                    "{底池}": result.total_pot,
                    "{剩余筹码}": result.remaining_stack,
                    "{下一位}": (
                        f"{result.next_seat}号"
                        if result.next_seat is not None
                        else "本轮已结束"
                    ),
                },
            )
            return (
                [acknowledgement, result.public_message]
                if result.public_message
                else acknowledgement
            )
        reasons = {
            "not_your_turn": "还没轮到你",
            "cannot_check": "当前需要跟注或弃牌",
            "nothing_to_call": "当前无需跟注",
            "raise_too_small": "加注额度不足",
            "insufficient_stack": "筹码不足",
            "raise_not_reopened": "短码全下没有重新开放加注权",
            "no_game": "当前没有德州扑克牌局",
            "not_participant": "你不是本局参与者",
            "action_expired": "本次行动已经超时",
        }
        return self._reply(
            command,
            "cannot_act",
            received_at,
            {"{原因}": reasons.get(result.status, "当前状态不允许")},
        )

    def _number_bomb_manual_start(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> list[CommandReply] | str:
        result = self._repository.start_number_bomb_round(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "started":
            return self._number_bomb_round_started_replies(
                "/开始", result, received_at
            )
        scenario = {
            "insufficient_players": "number_bomb_insufficient",
            "missing_direct_chats": "number_bomb_missing_direct_chats",
        }.get(result.status, "number_bomb_cannot_start")
        values = {}
        if result.status == "missing_direct_chats":
            values["{玩家列表}"] = "、".join(
                f"{player.roster_order}号 {player.display_name}"
                for player in result.players
                if player.direct_chatroom_id is None
            )
        elif result.status == "insufficient_players":
            values["{当前人数}"] = result.player_count
        return self._reply("/开始", scenario, received_at, values)

    def _number_bomb_join(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str | list[CommandReply]:
        result = self._repository.join_number_bomb_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "started":
            return self._number_bomb_round_started_replies(
                "/加入", result, received_at
            )
        if result.status == "joined":
            user = self._repository.find_user(platform_id)
            return self._reply(
                "/加入",
                "number_bomb_joined",
                received_at,
                {
                    "{昵称}": user.display_name,
                    "{当前人数}": result.player_count,
                },
            )
        scenarios = {
            "queued": "number_bomb_queued",
            "already_joined": "number_bomb_already_joined",
            "not_joined": "number_bomb_not_joined",
            "direct_chat_required": "number_bomb_direct_chat_required",
            "full": "number_bomb_next_round_full",
        }
        return self._reply(
            "/加入",
            scenarios.get(result.status, "number_bomb_already_joined"),
            received_at,
        )

    def _number_bomb_leave(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.leave_number_bomb_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.public_message:
            return result.public_message
        scenarios = {
            "signup_left": "number_bomb_signup_left",
            "exit_queued": "number_bomb_exit_queued",
            "candidate_cancelled": "number_bomb_candidate_cancelled",
            "retired": "number_bomb_retired",
        }
        return self._reply(
            "/退出",
            scenarios.get(result.status, "number_bomb_cannot_leave"),
            received_at,
        )

    def _number_bomb_continue(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str | list[CommandReply]:
        result = self._repository.continue_number_bomb_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "started":
            return self._number_bomb_round_started_replies(
                "/继续", result, received_at
            )
        return self._reply(
            "/继续",
            "number_bomb_insufficient"
            if result.status == "insufficient_players"
            else "number_bomb_cannot_continue",
            received_at,
        )

    def _number_bomb_end(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.end_number_bomb_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.public_message:
            return result.public_message
        return self._reply(
            "/结束游戏",
            "number_bomb_ended"
            if result.status == "ended"
            else "number_bomb_cannot_end",
            received_at,
        )

    def _number_bomb_submit(
        self, message: InboundMessage, content: str, received_at
    ) -> list[CommandReply]:
        parts = content.split()
        candidates = self._repository.number_bomb_private_candidates(
            message.sender_platform_id
        )
        candidate_lines = "\n".join(
            f"{candidate.index}. {candidate.group_name}"
            for candidate in candidates
        )
        if len(candidates) > 1 and len(parts) != 3:
            return [CommandReply(
                self._reply(
                    "/报数", "ambiguous_group", received_at,
                    {"{群聊列表}": candidate_lines},
                ),
                destination_chatroom_id=message.chatroom_id,
                delivery_kind="number_bomb_private",
            )]
        selected = None
        if len(parts) == 3:
            if not parts[1].isdigit():
                selected = None
            else:
                selected = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.index == int(parts[1])
                    ),
                    None,
                )
            if selected is None:
                return [CommandReply(
                    self._reply(
                        "/报数", "invalid_group", received_at,
                        {"{群聊列表}": candidate_lines or "暂无可选群聊"},
                    ),
                    destination_chatroom_id=message.chatroom_id,
                    delivery_kind="number_bomb_private",
                )]
            number_text = parts[2]
        else:
            selected = candidates[0] if len(candidates) == 1 else None
            number_text = parts[1] if len(parts) == 2 else ""
        number = int(number_text) if number_text.isdigit() else 0
        result = self._repository.submit_number_bomb(
            message.sender_platform_id,
            number,
            received_at,
            **(
                {}
                if selected is None
                else {"group_chat_id": selected.group_chat_id}
            ),
        )
        group_destination = (
            None
            if selected is None
            else self._repository.group_chat_destination(selected.group_chat_id)
        )
        scenarios = {
            "submitted": "submitted",
            "settled": "submitted",
            "tournament_finished": "submitted",
            "invalid_round": "submitted",
            "invalid_number": "invalid_number",
            "already_submitted": "duplicate",
            "not_participant": "not_participant",
            "no_game": "not_collecting",
            "wrong_state": "not_collecting",
        }
        replies = [
            CommandReply(
                self._reply(
                    "/报数", scenarios.get(result.status, "not_collecting"), received_at
                ),
                destination_chatroom_id=message.chatroom_id,
                delivery_kind="number_bomb_private",
            )
        ]
        if result.status in {"settled", "invalid_round", "tournament_finished"}:
            replies.append(
                CommandReply(
                    self._reply(
                        "/报数",
                        "result",
                        received_at,
                        {"{结果正文}": result.public_message},
                    ),
                    force_group_destination=True,
                    group_chat_id=(None if selected is None else selected.group_chat_id),
                    destination_chatroom_id=group_destination,
                )
            )
        if result.status == "invalid_round":
            replies.extend(self._number_bomb_private_prompt_replies(result, received_at))
        return replies

    def _number_bomb_skip(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str | list[CommandReply]:
        parts = content.split()
        if len(parts) < 2:
            return self._reply("/跳过", "usage", received_at)
        result = self._repository.skip_number_bomb_players(
            platform_id,
            tuple(parts[1:]),
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status in {
            "skipped", "settled", "points_skipped", "points_settled",
            "ended_insufficient",
        }:
            values = {
                "{玩家列表}": "、".join(
                    f"{player.roster_order}号 {player.display_name}"
                    for player in result.players
                )
            }
            scenario = (
                "points_settled"
                if result.status == "points_settled"
                else "points_skipped"
                if result.status == "points_skipped"
                else
                "settled"
                if result.status == "settled"
                else "ended_insufficient"
                if result.status == "ended_insufficient"
                else "skipped"
            )
            replies = [
                CommandReply(
                    self._reply("/跳过", scenario, received_at, values),
                    force_group_destination=True,
                )
            ]
            if result.status in {"settled", "points_settled"}:
                replies.append(
                    CommandReply(
                        self._reply(
                            "/报数",
                            "result",
                            received_at,
                            {"{结果正文}": result.public_message},
                        ),
                        force_group_destination=True,
                    )
                )
            return replies
        scenario = {
            "skip_not_enabled": "not_enabled",
            "not_participant": "not_participant",
            "duplicate_target": "duplicate_target",
            "ambiguous_target": "ambiguous_target",
            "already_submitted": "already_submitted",
            "invalid_target": "invalid_target",
            "no_game": "no_game",
            "wrong_state": "no_game",
        }.get(result.status, "no_game")
        return self._reply("/跳过", scenario, received_at)

    def _number_bomb_round_started_replies(
        self, command: str, result, received_at
    ) -> list[CommandReply]:
        replies = [
            CommandReply(
                self._reply(
                    command,
                    "number_bomb_started",
                    received_at,
                    {
                        "{轮次}": (
                            f"{result.round_number}/{result.maximum_rounds}"
                            if result.mode == "points_tournament"
                            else result.round_number
                        ),
                        "{惩罚类型}": (
                            "大冒险"
                            if result.punishment_type == "dare"
                            else "真心话"
                        ),
                        "{玩家列表}": "、".join(
                            player.display_name
                            for player in result.players
                            if player.state == "current"
                        ),
                    },
                ),
                force_group_destination=True,
            )
        ]
        replies.extend(self._number_bomb_private_prompt_replies(result, received_at))
        return replies

    def _number_bomb_private_prompt_replies(
        self, result, received_at
    ) -> list[CommandReply]:
        prompt = self._reply("/开始", "number_bomb_private_prompt", received_at)
        return [
            CommandReply(
                prompt,
                destination_chatroom_id=player.direct_chatroom_id,
                delivery_kind="number_bomb_private",
            )
            for player in result.players
            if player.state == "current" and player.direct_chatroom_id is not None
        ]

    def _blame_join(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.join_blame_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "joined":
            user = self._repository.find_user(platform_id)
            return self._reply(
                "/加入",
                "blame_joined",
                received_at,
                {
                    "{昵称}": user.display_name,
                    "{当前人数}": result.player_count,
                    "{人数}": result.target_player_count,
                },
            )
        if result.status == "started":
            summary = self._repository.blame_game_summary(
                received_at,
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
            )
            holder = next(
                player for player in summary.players
                if player.seat_number == summary.current_holder_number
            )
            return self._reply(
                "/加入",
                "blame_started",
                received_at,
                {
                    "{玩家列表}": "、".join(
                        f"{player.seat_number}号 {player.display_name}"
                        for player in summary.players
                    ),
                    "{事故名称}": summary.incident_name,
                    "{事故描述}": summary.incident_description,
                    "{关键词}": "、".join(summary.incident_keywords),
                    "{持锅者}": f"{holder.seat_number}号 {holder.display_name}",
                    "{温度}": summary.temperature,
                },
            )
        if result.status == "game_started":
            return self._reply("/加入", "blame_game_started", received_at)
        if result.status == "signup_expired":
            return self._reply("/甩锅游戏", "signup_expired", received_at)
        reasons = {
            "not_joined": "请先入职。",
            "insufficient_balance": "余额不足，无法加入本局。",
            "already_joined": "你已经报名了本局。",
            "waiting_for_players": "余额不足的玩家已被移出，继续等待报名。",
        }
        return self._reply(
            "/加入",
            "blame_failed",
            received_at,
            {"{原因}": reasons.get(result.status, "当前无法加入甩锅游戏。")},
        )

    def _blame_transfer(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split(maxsplit=2)
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].strip():
            return self._reply("/甩锅", "usage", received_at)
        result = self._repository.transfer_blame(
            platform_id,
            int(parts[1]),
            parts[2].strip(),
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "transferred":
            return self._reply(
                "/甩锅",
                "transferred",
                received_at,
                {
                    "{原持锅者}": result.from_display_name,
                    "{新持锅者}": result.to_display_name,
                    "{温度}": result.temperature,
                },
            )
        if result.status == "missing_keywords":
            return self._reply(
                "/甩锅", "missing_keywords", received_at,
                {"{缺少关键词}": "、".join(result.missing_keywords)},
            )
        if result.status == "settled":
            return self._blame_settlement_reply(result, received_at)
        scenario = result.status if result.status in {
            "duplicate_reason", "invalid_target", "self_target",
            "immediate_return_blocked", "not_holder",
        } else "usage"
        return self._reply("/甩锅", scenario, received_at)

    def _blame_leave(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.leave_blame_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "left_signup":
            return self._reply("/退出甩锅", "left_signup", received_at)
        if result.status == "settled":
            return self._blame_settlement_reply(result, received_at)
        if result.status == "signup_expired":
            return self._reply("/甩锅游戏", "signup_expired", received_at)
        return self._reply("/退出甩锅", "cannot_leave", received_at)

    def _blame_end(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.end_blame_game(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "settled":
            return self._blame_settlement_reply(result, received_at)
        if result.status == "signup_expired":
            return self._reply("/甩锅游戏", "signup_expired", received_at)
        return self._reply(
            "/结束游戏",
            "blame_cancelled" if result.status == "cancelled" else "cannot_end",
            received_at,
        )

    def _blame_settlement_reply(
        self, result: BlameGameResult, received_at
    ) -> str:
        if result.settlement_reason in {"exploded", "turn_timeout"}:
            command = "/甩锅游戏"
            scenario = result.settlement_reason
        elif result.settlement_reason == "player_left":
            command = "/退出甩锅"
            scenario = "settled"
        else:
            command = "/甩锅"
            scenario = "settled"
        return self._reply(
            command,
            scenario,
            received_at,
            blame_settlement_template_values(result),
        )

    def _undercover_join(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.join_undercover(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "joined_signup":
            employee = self._repository.find_user(platform_id)
            summary = self._repository.undercover_session_summary(
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id})
            )
            return self._reply(
                "/加入",
                "undercover_joined",
                received_at,
                {
                    "{昵称}": employee.display_name,
                    "{当前人数}": result.player_count,
                    "{人数}": summary.target_player_count,
                },
            )
        if result.status == "dealing":
            return self._reply("/加入", "undercover_dealing", received_at)
        scenarios = {
            "queued": "undercover_queued",
            "direct_chat_required": "undercover_direct_chat_required",
            "already_joined": "undercover_already_joined",
            "cannot_rejoin": "undercover_cannot_rejoin",
            "not_joined": "undercover_not_joined",
        }
        return self._reply("/加入", scenarios.get(result.status, "invalid"), received_at)

    def _undercover_start_vote(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.start_undercover_vote(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status != "voting":
            return self._reply("/开始投票", "cannot_start", received_at)
        summary = self._repository.undercover_session_summary(
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id})
        )
        vote_seconds = (
            max(int((summary.vote_deadline - received_at).total_seconds()), 1)
            if summary.vote_deadline is not None
            else self._repository.get_undercover_settings().vote_seconds
        )
        return self._reply(
            "/开始投票",
            "started",
            received_at,
            {
                "{投票秒数}": vote_seconds,
                "{存活玩家}": "、".join(
                    f"{player.seat_number}号 {player.display_name}"
                    for player in summary.players
                    if player.state == "alive"
                ),
            },
        )

    def _undercover_vote(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split()
        if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) < 1:
            return self._reply("/投票", "usage", received_at)
        result = self._repository.cast_undercover_vote(
            platform_id,
            int(parts[1]),
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        scenarios = {
            "vote_recorded": "recorded",
            "duplicate_vote": "duplicate",
            "already_abstained": "already_abstained",
            "invalid_vote_target": "invalid_target",
            "cannot_vote": "cannot_vote",
        }
        if result.status in scenarios:
            values = None
            if result.status == "vote_recorded":
                values = {
                    "{编号}": result.actor_seat,
                    "{玩家名称}": result.actor_display_name,
                    "{已完成人数}": result.completed_count,
                    "{存活人数}": result.eligible_count,
                }
            return self._reply(
                "/投票", scenarios[result.status], received_at, values
            )
        if result.status == "tied":
            return self._reply(
                "/投票",
                "tied",
                received_at,
                {"{并列玩家}": self._undercover_player_labels(result.tied_seats, group_chat_id)},
            )
        if result.status in {"eliminated", "settled"}:
            if result.status == "settled":
                values = undercover_settlement_template_values(result)
            else:
                values = self._undercover_elimination_values(result, group_chat_id)
            return self._reply("/投票", result.status, received_at, values)
        return self._reply("/投票", "cannot_vote", received_at)

    def _undercover_skip(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split()
        if len(parts) != 2 or not parts[1].isdigit() or int(parts[1]) < 1:
            return self._reply("/跳过", "undercover_usage", received_at)
        result = self._repository.skip_undercover_vote(
            platform_id,
            int(parts[1]),
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "abstained":
            return self._reply(
                "/跳过",
                "undercover_abstained",
                received_at,
                {
                    "{编号}": result.actor_seat,
                    "{玩家名称}": result.actor_display_name,
                    "{已完成人数}": result.completed_count,
                    "{存活人数}": result.eligible_count,
                    "{投票人数}": result.vote_count,
                    "{弃票人数}": result.abstention_count,
                },
            )
        scenarios = {
            "cannot_skip_self": "undercover_cannot_skip_self",
            "already_voted": "undercover_already_voted",
            "already_abstained": "undercover_already_abstained",
            "invalid_skip_target": "undercover_invalid_target",
            "cannot_skip_vote": "undercover_cannot_skip",
        }
        if result.status in scenarios:
            return self._reply("/跳过", scenarios[result.status], received_at)
        if result.status == "vote_expired":
            return self._reply("/跳过", "undercover_vote_expired", received_at)
        if result.status == "tied":
            return self._reply(
                "/投票",
                "tied",
                received_at,
                {"{并列玩家}": self._undercover_player_labels(result.tied_seats, group_chat_id)},
            )
        if result.status in {"eliminated", "settled"}:
            if result.status == "settled":
                values = undercover_settlement_template_values(result)
            else:
                values = self._undercover_elimination_values(result, group_chat_id)
            return self._reply("/投票", result.status, received_at, values)
        return self._reply("/跳过", "undercover_cannot_skip", received_at)

    def _undercover_leave(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.leave_undercover(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status in {"left", "left_signup", "left_waiting_continue"}:
            return self._reply("/退出谁是卧底", "left", received_at)
        if result.status == "leave_after_round":
            return self._reply(
                "/退出谁是卧底",
                "leave_after_round",
                received_at,
                {
                    "{编号}": result.actor_seat,
                    "{玩家名称}": result.actor_display_name,
                },
            )
        if result.status == "settled":
            return self._reply(
                "/退出谁是卧底",
                "settled",
                received_at,
                {"{胜利阵营}": self._undercover_role_name(result.winner)},
            )
        return self._reply("/退出谁是卧底", "cannot_leave", received_at)

    def _undercover_end(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.end_undercover(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        return self._reply(
            "/结束游戏",
            "ended" if result.status == "ended" else "cannot_end",
            received_at,
        )

    def _undercover_continue(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.continue_undercover(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "dealing":
            return self._reply("/继续", "undercover_dealing", received_at)
        if result.status == "insufficient_players":
            return self._reply("/继续", "undercover_insufficient", received_at)
        return self._reply("/继续", "undercover_cannot_continue", received_at)

    def _undercover_player_labels(
        self, seats: tuple[int, ...], group_chat_id=None
    ) -> str:
        names = {
            player.seat_number: player.display_name
            for player in self._repository.undercover_session_summary(
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id})
            ).players
        }
        return "、".join(f"{seat}号 {names.get(seat, '玩家')}" for seat in seats)

    def _undercover_elimination_values(
        self, result, group_chat_id=None
    ) -> dict[str, str]:
        summary = self._repository.undercover_session_summary(
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id})
        )
        player = next(
            item
            for item in summary.players
            if item.seat_number == result.eliminated_seat
        )
        role_by_platform_id = dict(zip(result.player_ids, result.roles, strict=True))
        return {
            "{淘汰玩家}": f"{player.seat_number}号 {player.display_name}",
            "{身份}": self._undercover_role_name(role_by_platform_id[player.platform_id]),
        }

    @staticmethod
    def _undercover_role_name(role: str | None) -> str:
        return {
            "civilian": "平民",
            "undercover": "卧底",
            "whiteboard": "白板",
        }.get(role, "未知")

    def _event_join(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        parts = content.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip():
            if self._repository.blame_game_summary(
                received_at,
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
            ).state is not None:
                return self._blame_join(platform_id, received_at, group_chat_id)
            if self._repository.undercover_session_summary(
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id})
            ).state is not None:
                return self._undercover_join(
                    platform_id, received_at, group_chat_id
                )
            duel = self._repository.join_memory_assessment_duel(
                platform_id,
                received_at,
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
            )
            if duel.status == "duel_started":
                return self._memory_assessment_round_reply(
                    "/记忆考核", "duel_started", duel, received_at
                )
            if duel.status == "not_joined":
                return self._reply("/加入", "not_joined", received_at)
            if duel.status == "random_event_active":
                return self._reply("/记忆考核", "random_event_active", received_at)
            return self._reply("/加入", "invalid", received_at)
        status = self._repository.join_random_event(
            platform_id,
            parts[1].strip(),
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        employee = self._repository.find_user(platform_id)
        if status == "not_joined":
            return self._reply("/加入", status, received_at)
        if status == "no_event":
            return self._reply("/加入", status, received_at)
        if status == "joined":
            return self._reply(
                "/加入", status, received_at,
                {
                    "{昵称}": employee.display_name,
                    "{角色}": parts[1].strip(),
                    "{剩余席位}": self._repository.random_event_open_seats(
                        **(
                            {}
                            if group_chat_id is None
                            else {"group_chat_id": group_chat_id}
                        )
                    ),
                },
            )
        if status == "started":
            return self._reply(
                "/加入", status, received_at, {"{昵称}": employee.display_name}
            )
        reasons = {
            "event_started": "随机事件已经开始，无法再报名。",
            "already_joined": "你已经报名了当前随机事件。",
            "unknown_role": "这个角色不在当前随机事件的可选席位中。",
            "role_full": "这个角色的席位已经满了。",
        }
        return self._reply("/加入", "failed", received_at, {"{原因}": reasons[status]})

    def _event_leave(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        status = self._repository.leave_random_event(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if status == "not_joined":
            return self._reply("/退出", status, received_at)
        if status == "no_event":
            return self._reply("/退出", status, received_at)
        employee = self._repository.find_user(platform_id)
        if status == "rewarded":
            return self._reply(
                "/退出", status, received_at,
                {
                    "{昵称}": employee.display_name,
                    "{事件奖励}": self._event_reward(
                        platform_id, group_chat_id
                    ),
                },
            )
        if status == "left_signup":
            return self._reply(
                "/退出", "signup_left", received_at, {"{昵称}": employee.display_name}
            )
        if status == "left_without_reward":
            return self._reply(
                "/退出", "left", received_at, {"{昵称}": employee.display_name}
            )
        return self._reply(
            "/退出", "failed", received_at,
            {"{原因}": "你没有加入当前随机事件。"},
        )

    def _event_reward(self, platform_id: str, group_chat_id=None) -> int:
        return self._repository.last_random_event_reward(
            platform_id,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )

    def _random_event_tip(
        self,
        message: InboundMessage,
        content: str,
        received_at,
        group_chat_id=None,
    ) -> str:
        payload = content[len("/打赏") :].strip()
        if not payload:
            return self._reply("/打赏", "usage", received_at)
        parts = payload.rsplit(maxsplit=1)
        if (
            len(parts) != 2
            or not parts[0].strip()
            or not parts[1].isascii()
            or not parts[1].isdigit()
            or int(parts[1]) <= 0
        ):
            return self._reply("/打赏", "invalid_amount", received_at)
        result = self._repository.tip_random_event(
            message.sender_platform_id,
            parts[0].strip(),
            int(parts[1]),
            message.platform_message_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        currency = self._repository.get_game_settings().currency_name
        if result.status in {"tipped", "duplicate"}:
            return self._reply(
                "/打赏",
                "tipped",
                received_at,
                {
                    "{打赏者}": result.sender_display_name or "",
                    "{收款人}": result.recipient_display_name or "",
                    "{金额}": result.amount,
                    "{货币}": currency,
                },
            )
        if result.status == "insufficient_balance":
            return self._reply(
                "/打赏",
                result.status,
                received_at,
                {"{余额}": result.sender_balance or 0, "{货币}": currency},
            )
        scenario = (
            result.status
            if result.status
            in {
                "not_joined",
                "no_tipping_event",
                "expired",
                "invalid_amount",
                "recipient_not_found",
                "recipient_not_participant",
                "self_tip",
            }
            else "failed"
        )
        return self._reply("/打赏", scenario, received_at)

    def _hide_and_seek(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str | list[str]:
        parts = content.split()
        if content == "/开始摸鱼躲藏":
            result = self._repository.start_hide_and_seek(
                platform_id,
                received_at,
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
            )
            if result.status == "started":
                return self._reply(
                    "/摸鱼躲猫猫",
                    "started",
                    received_at,
                    {
                        "{昵称}": result.display_name,
                        "{入场费}": result.entry_fee,
                        "{场景列表}": "\n".join(
                            f"{number}（{name}）"
                            for number, name in enumerate(result.candidates, start=1)
                        ),
                        "{选择超时分钟}": self._repository.get_hide_and_seek_settings().selection_timeout_minutes,
                    },
                )
            return self._hide_and_seek_status_reply(result.status, received_at)
        if len(parts) == 2 and parts[0] == "/躲" and parts[1].isdigit():
            result = self._repository.choose_hide_and_seek(
                platform_id,
                int(parts[1]),
                received_at,
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
            )
            if result.status in {"won", "found"}:
                first_patrols = "、".join(
                    f"{number}（{name}）"
                    for number, name in zip(result.patrol_numbers[:3], result.patrol_scenes[:3])
                )
                values = {
                    "{昵称}": result.display_name,
                    "{巡查地点}": first_patrols,
                    "{巡查过程}": f"【系统巡查·第一轮】巡查 {first_patrols}",
                    "{奖励}": result.win_reward,
                    "{余额}": result.balance,
                    "{惩罚金额}": result.entry_fee,
                }
                if len(result.patrol_numbers) == 3:
                    return self._reply(
                        "/摸鱼躲猫猫", "found_first_round", received_at, values
                    )
                second_patrols = "、".join(
                    f"{number}（{name}）"
                    for number, name in zip(result.patrol_numbers[3:], result.patrol_scenes[3:])
                )
                values["{巡查地点}"] = second_patrols
                values["{巡查过程}"] = f"【系统巡查·第二轮】巡查 {second_patrols}"
                return [
                    self._reply(
                        "/摸鱼躲猫猫",
                        "first_round_missed",
                        received_at,
                        {
                            "{昵称}": result.display_name,
                            "{巡查地点}": first_patrols,
                            "{巡查过程}": f"【系统巡查·第一轮】巡查 {first_patrols}",
                        },
                    ),
                    self._reply("/摸鱼躲猫猫", result.status, received_at, values),
                ]
            return self._hide_and_seek_status_reply(result.status, received_at)
        return self._reply("/摸鱼躲猫猫", "usage", received_at)

    def _hide_and_seek_status_reply(self, status: str, received_at) -> str:
        scenarios = {
            "not_joined": "not_joined",
            "random_event_active": "blocked",
            "disabled": "disabled",
            "daily_limit": "daily_limit",
            "already_active": "already_active",
            "not_enough_scenes": "not_enough_scenes",
            "invalid_scene": "invalid_scene",
            "no_active_game": "no_active_game",
            "expired": "expired",
        }
        return self._reply("/摸鱼躲猫猫", scenarios[status], received_at)

    def _memory_assessment_start(
        self, platform_id: str, content: str, received_at, group_chat_id=None
    ) -> str:
        if content == "/记忆考核 对战":
            result = self._repository.start_memory_assessment_duel(
                platform_id,
                received_at,
                **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
            )
            if result.status == "waiting_opponent":
                return self._reply(
                    "/记忆考核",
                    "duel_waiting",
                    received_at,
                    {"{昵称}": result.display_name, "{等级}": result.level},
                )
            scenarios = {
                "not_joined": "not_joined",
                "disabled": "disabled",
                "multiplayer_active": "multiplayer_active",
                "already_active": "already_active",
            }
            return self._reply("/记忆考核", scenarios[result.status], received_at)
        if content != "/记忆考核":
            return self._reply("/记忆考核", "usage", received_at)
        result = self._repository.start_memory_assessment_single(
            platform_id,
            received_at,
            **({} if group_chat_id is None else {"group_chat_id": group_chat_id}),
        )
        if result.status == "started":
            return self._memory_assessment_round_reply("/记忆考核", "started", result, received_at)
        scenarios = {
            "not_joined": "not_joined",
            "disabled": "disabled",
            "daily_limit": "daily_limit",
            "already_active": "already_active",
            "random_event_active": "random_event_active",
        }
        return self._reply("/记忆考核", scenarios[result.status], received_at)

    def _memory_assessment_answer(
        self, platform_id: str, content: str, received_at
    ) -> str | None:
        result = self._repository.answer_memory_assessment(platform_id, content, received_at)
        if result.status in {"no_active_game", "answer_not_ready"}:
            return None
        if result.status == "correct":
            return self._reply(
                "/记忆考核",
                "correct",
                received_at,
                {
                    "{昵称}": result.display_name,
                    "{等级}": result.level,
                    "{奖励}": result.reward,
                },
            )
        if result.status == "completed":
            return self._reply(
                "/记忆考核",
                "completed",
                received_at,
                {
                    "{昵称}": result.display_name,
                    "{等级}": result.level,
                    "{奖励}": result.reward,
                    "{余额}": result.balance,
                },
            )
        if result.status == "failed":
            return self._reply("/记忆考核", "failed", received_at)
        if result.status == "duel_won":
            return self._reply(
                "/记忆考核",
                "duel_won",
                received_at,
                {
                    "{昵称}": result.display_name,
                    "{奖励}": result.reward,
                    "{余额}": result.balance,
                },
            )
        if result.status == "duel_incorrect":
            return self._reply(
                "/记忆考核",
                "duel_incorrect",
                received_at,
                {"{惩罚金额}": self._repository.get_memory_assessment_settings().duel_wrong_freeze},
            )
        if result.status == "duel_disqualified":
            return self._reply("/记忆考核", "duel_disqualified", received_at)
        if result.status == "duel_collected":
            return self._reply("/记忆考核", "duel_collected", received_at)
        return None

    def _memory_assessment_continue(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.continue_memory_assessment(
            platform_id, received_at, group_chat_id
        )
        if result.status == "continued":
            return self._memory_assessment_round_reply("/继续", "continued", result, received_at)
        return self._reply("/继续", "cannot_continue", received_at)

    def _memory_assessment_cash_out(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.cash_out_memory_assessment(
            platform_id, received_at, group_chat_id
        )
        if result.status == "cashed_out":
            return self._reply(
                "/收手",
                "cashed_out",
                received_at,
                {
                    "{昵称}": result.display_name,
                    "{奖励}": result.reward,
                    "{余额}": result.balance,
                },
            )
        return self._reply("/收手", "cannot_cash_out", received_at)

    def _memory_assessment_surrender(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.surrender_memory_assessment_duel(
            platform_id, received_at, group_chat_id
        )
        if result.status == "duel_won":
            return self._reply(
                "/投降",
                "lost",
                received_at,
                {
                    "{昵称}": self._repository.find_user(platform_id).display_name,
                    "{胜者}": result.display_name,
                    "{奖励}": result.reward,
                },
            )
        return self._reply("/投降", "cannot_surrender", received_at)

    def _memory_assessment_cancel_waiting(
        self, command: str, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        result = self._repository.cancel_waiting_memory_assessment_duel(
            platform_id, received_at, group_chat_id
        )
        return self._reply(
            command,
            "memory_waiting_cancelled"
            if result.status == "waiting_cancelled"
            else "memory_waiting_cannot_cancel",
            received_at,
        )

    def _memory_assessment_round_reply(self, command: str, scenario: str, result, received_at) -> CommandReply:
        return CommandReply(
            self._reply(
                command,
                scenario,
                received_at,
                {
                    "{昵称}": result.display_name,
                    "{等级}": result.level,
                    "{考核文本}": result.answer,
                    "{撤回秒数}": result.display_seconds,
                },
            ),
            recall_after_seconds=result.display_seconds,
            memory_round_id=result.round_id,
        )

    def _help(self, content: str, received_at) -> str:
        commands = {
            item.command for item in self._repository.list_enabled_command_definitions()
        }
        settings = self._repository.get_game_settings()
        topic = content.split(maxsplit=1)[1].strip() if len(content.split(maxsplit=1)) == 2 else ""
        topic = {
            "躲猫猫": "摸鱼躲藏",
            "摸鱼躲猫猫": "摸鱼躲藏",
            "卧底": "谁是卧底",
        }.get(topic, topic)

        guides = {
            "基础": (
                "【基础与资产】",
                (
                    ("/入职", "/入职 名字：登记成为员工"),
                    ("/打卡", f"/打卡：每日领取 {settings.checkin_reward} {settings.currency_name}"),
                    ("/余额", "/余额：查看当前余额"),
                    ("/修改名称", "/修改名称 新名称：修改自己的员工名称"),
                    ("/编辑档案", "/编辑档案 档案内容：更新个人档案"),
                    ("/编辑档案形象", "/编辑档案形象（回复一张图片）：更新档案形象"),
                    ("/我的档案", "/我的档案：查看自己的个人档案"),
                    ("/发奖金", "/发奖金 员工名 金额；/发奖金 全部 金额：仅核心董事会发放"),
                    ("/发红包", "/发红包 人数 总金额：发出随机运气红包"),
                    ("/抢红包", "/抢红包：领取当前红包"),
                    ("/我", "/我：查看个人资料、收益与活跃度"),
                    ("/我的物品", "/我的物品：查看持有物品"),
                    ("/商店", "/商店：查看可购买物品"),
                ),
            ),
            "随机事件": (
                "【随机事件】",
                (
                    ("/加入", "/加入 身份：选择身份报名随机事件"),
                    ("/退出", "/退出：退出或结算当前随机事件"),
                    ("/打赏", "/打赏 员工名称 金额：所有参与者退出后限时开放，真实转移摸鱼币且不能给自己打赏"),
                    ("/投稿", "/投稿 随机事件：进入私聊投稿向导"),
                    ("/我的投稿", "/我的投稿：查看最近投稿状态"),
                    ("/撤回投稿", "/撤回投稿 编号：撤回待审核投稿"),
                ),
            ),
            "摸鱼躲藏": (
                "【摸鱼躲藏】",
                (
                    ("/摸鱼躲猫猫", "/开始摸鱼躲藏：发起单人躲藏"),
                    ("/摸鱼躲猫猫", "/躲 序号：从系统给出的地点中选择"),
                ),
            ),
            "记忆考核": (
                "【记忆考核】",
                (
                    ("/记忆考核", "/记忆考核：发起单人挑战"),
                    ("/记忆考核", "/记忆考核 对战：发起双人对战"),
                    ("/加入", "/加入：加入等待中的对战"),
                    ("/记忆考核", "/答案 内容：提交记忆答案"),
                    ("/继续", "/继续：单人挑战进入下一等级"),
                    ("/收手", "/收手：结算当前单人挑战奖励"),
                    ("/退出", "/退出：立即退出当前记忆考核对战"),
                ),
            ),
            "谁是卧底": (
                "【谁是卧底】",
                (
                    ("/谁是卧底", "/谁是卧底 人数：创建 4 至 8 人报名局"),
                    ("/加入", "/加入：报名当前对局或加入下一局候场"),
                    ("/开始投票", "/开始投票：描述阶段后开启投票"),
                    ("/投票", "/投票 序号：投给指定玩家"),
                    ("/退出", "/退出：退出当前对局"),
                    ("/结束游戏", "/结束游戏：结束当前对局"),
                    ("/继续", "/继续：上一局结束后开启下一局"),
                ),
            ),
            "甩锅游戏": (
                "【甩锅游戏】",
                (
                    ("/甩锅游戏", "/甩锅游戏 人数：创建 2 至 10 人报名局"),
                    ("/加入", "/加入：报名当前甩锅游戏"),
                    ("/甩锅", "/甩锅 玩家编号 理由：把锅甩给指定玩家"),
                    ("/退出", "/退出：退出报名；开局后退出会直接背锅"),
                    ("/结束游戏", "/结束游戏：参与者结束并退款（到期局优先结算）"),
                ),
            ),
            "蹦蹦数字炸弹": (
                "【蹦蹦数字炸弹】",
                (
                    ("/蹦蹦数字炸弹", "/蹦蹦数字炸弹：创建普通报名局；至少3名玩家后手动开始\n/蹦蹦数字炸弹 积分赛：创建固定8人、12轮积分赛，第8人加入后自动开始"),
                    ("/蹦蹦数字炸弹", "积分规则：第1名 +10、第2名 +5、第3–6名 0、第7名 -3、第8名 +2；并列第一同为第1，并列最后同为实际报数人数对应的最后名次，其他并列取起始名次"),
                    ("/加入", "/加入：报名当前对局；积分赛开局后不接受替补"),
                    ("/开始", "/开始：报名阶段由任一参与者开始第一轮"),
                    ("/报数", "私聊 /报数 数字：提交 1–100 的本轮整数"),
                    ("/跳过", "/跳过 编号：首次未报数提醒后处理未报数玩家；积分赛中该玩家本轮 -3 分但下轮仍可参加"),
                    ("/退出", "/退出：普通局从下一轮退出；积分赛立即退赛且后续每轮 -3 分"),
                    ("/继续", "/继续：本轮结算后由任一未退赛参与者开启下一轮；积分赛第12轮自动结束"),
                    ("/结束游戏", "/结束游戏：任一未退赛参与者可提前结束积分赛；未完成轮次不计分"),
                ),
            ),
            "德州扑克": (
                "【德州扑克】",
                (
                    ("/德州扑克", "/德州扑克 带入金额：创建 2 至 9 人单局现金桌"),
                    ("/加入", "/加入：按本局统一带入加入报名"),
                    ("/开始", "/开始：至少2人后由任一参与者开始发牌"),
                    ("/看牌", "私聊 /看牌：仅查看自己的两张底牌"),
                    ("/过牌", "/过牌：无需跟注时让牌"),
                    ("/跟注", "/跟注：补足到当前下注"),
                    ("/加注", "/加注 金额：加到本轮总下注金额"),
                    ("/全下", "/全下：投入剩余全部筹码"),
                    ("/弃牌", "/弃牌：放弃本手牌"),
                    ("/退出", "/退出：开局前退出退款；开局后立即弃牌"),
                ),
            ),
            "部门": (
                "【部门与审批】",
                (
                    ("/部门", "/部门：查看部门列表与说明"),
                    ("/部门人数", "/部门人数：查看全部非空部门人数与职位分布"),
                    ("/我的部门人数", "/我的部门人数：查看自己部门人数与职位分布"),
                    ("/加入部门", "/加入部门 名称：申请加入部门"),
                    ("/切换部门", "/切换部门 名称：申请切换部门"),
                    ("/部门申请列表", "/部门申请列表：查看可处理的申请"),
                    ("/同意部门", "/同意部门 编号：同意部门申请"),
                    ("/全部同意部门", "/全部同意部门：同意全部可处理申请"),
                    ("/拒绝部门", "/拒绝部门 编号：拒绝部门申请"),
                    ("/全部拒绝部门", "/全部拒绝部门：拒绝全部可处理申请"),
                ),
            ),
            "职位": (
                "【职位与审批】",
                (
                    ("/职位", "/职位：查看职位与群内权益"),
                    ("/晋升", "/晋升：申请下一档职位"),
                    ("/晋升申请列表", "/晋升申请列表：查看可处理申请"),
                    ("/同意", "/同意 编号：同意晋升申请"),
                    ("/全部同意", "/全部同意：同意全部可处理申请"),
                    ("/拒绝", "/拒绝 编号：拒绝晋升申请"),
                    ("/全部拒绝", "/全部拒绝：拒绝全部可处理申请"),
                ),
            ),
        }

        def category_available(category: str) -> bool:
            if category == "游戏":
                return any(
                    any(command in commands for command, _ in guides[name][1])
                    for name in (
                        "摸鱼躲藏",
                        "记忆考核",
                        "谁是卧底",
                        "甩锅游戏",
                        "蹦蹦数字炸弹",
                        "德州扑克",
                    )
                )
            return any(command in commands for command, _ in guides[category][1])

        if not topic:
            categories = (
                ("基础", "/帮助 基础：入职、资产与商店"),
                (
                    "游戏",
                    "/帮助 游戏：玩法总览；/帮助 摸鱼躲藏、/帮助 记忆考核、/帮助 谁是卧底、/帮助 甩锅游戏、/帮助 蹦蹦数字炸弹、/帮助 德州扑克",
                ),
                ("随机事件", "/帮助 随机事件：报名与退出"),
                ("部门", "/帮助 部门：部门申请与审批"),
                ("职位", "/帮助 职位：职位晋升与审批"),
            )
            guide = "发送 /帮助 分类，查看详细用法：\n" + "\n".join(
                line
                for category, line in categories
                if category_available(category)
            )
        elif topic == "游戏":
            game_topics = [
                name
                for name in (
                    "摸鱼躲藏",
                    "记忆考核",
                    "谁是卧底",
                    "甩锅游戏",
                    "蹦蹦数字炸弹",
                    "德州扑克",
                )
                if any(command in commands for command, _ in guides[name][1])
            ]
            guide = "【游戏玩法】\n" + "\n".join(
                f"/帮助 {name}：查看{name}玩法" for name in game_topics
            )
            if "蹦蹦数字炸弹" in game_topics:
                guide += (
                    "\n蹦蹦数字炸弹主要指令：/蹦蹦数字炸弹、/加入、/开始、"
                    "私聊 /报数 数字、/跳过 编号、/继续、/结束游戏；"
                    "发送 /蹦蹦数字炸弹 积分赛 可开启固定8人、12轮积分赛"
                )
        elif topic in guides:
            title, entries = guides[topic]
            lines = [line for command, line in entries if command in commands]
            guide = "\n".join((title, *lines)) if lines else "该分类暂未开放。"
        else:
            guide = "未找到该分类。可发送 /帮助 查看分类入口。"
        return self._reply(
            "/帮助",
            "shown",
            received_at,
            {"{指令列表}": guide},
        )

    def _reply(self, command: str, scenario: str, received_at, values=None) -> str:
        definition = template_definition(command, scenario)
        template_record = self._repository.get_reply_template(command, scenario)
        template = template_record.template if template_record is not None else definition.default
        context = {
            "{日期}": received_at.date().isoformat(),
            "{货币}": self._repository.get_game_settings().currency_name,
            **(values or {}),
        }
        try:
            return render_template(definition, template, context)
        except ValueError:
            return render_template(definition, definition.default, context)
