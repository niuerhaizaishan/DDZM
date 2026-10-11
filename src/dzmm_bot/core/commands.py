from collections import Counter
import json
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dzmm_bot.runtime.contracts import InboundMessage

from .group_games import GROUP_GAME_COMMANDS, GROUP_GAME_LABELS
from .birthday import parse_visibility
from .honors import honor_award_lines
from .liar_dice import (
    end_message as liar_dice_end_message,
    parse_call,
    statistic_lines as liar_dice_statistic_lines,
)

from .company_lottery import (
    ALL_TIERS,
    OrderKind,
    PrizeTier,
    TicketParseError,
    is_quick_pick,
    parse_order,
    parse_single,
    tier_counts,
    total_combinations,
    winning_combinations,
)
from .memory_guild_match import (
    parse_guild_match_start,
    parse_series_command,
    parse_team_command,
    split_roster_names,
)
from .performance import parse_postponement
from .reply_templates import render_template, template_definition
from .shop_cards import CATEGORY_DISPLAY_ORDER, CATEGORY_OTHER
from .schema import PRIMARY_GROUP_CHAT_ID
from .repository import (
    BlameGameResult,
    _short_author_name,
    CoreRepository,
    EmployeeNameTakenError,
    _FINE_FEEDBACK_HINT,
    blame_settlement_template_values,
    company_story_novel_resource_id,
    format_employee_number,
    render_never_have_i_ever_hearts,
    render_never_have_i_ever_player_lines,
    render_never_have_i_ever_round_settlement,
    undercover_settlement_template_values,
)
from .service import CommandReply


_BEIJING = ZoneInfo("Asia/Shanghai")

# 冲突自救提示用：玩法中文名（群玩法名取自 GROUP_GAME_LABELS，另补摘要里的记忆考核系列与随机事件）
_GAMEPLAY_LABELS = {
    **GROUP_GAME_LABELS,
    "memory_single": "记忆考核",
    "memory_duel": "记忆考核对战",
    "memory_guild": "记忆考核公会赛",
    "random_event": "随机事件",
}
_GAMEPLAY_STATE_LABELS = {
    "signup": "报名中",
    "dealing": "发牌中",
    "calling": "叫牌中",
    "round_end": "本轮已结束，待继续",
    "round_complete": "本轮已结束，待继续",
    "answering": "作答中",
    "awaiting_reveal": "等国王公开",
    "waiting": "等待中",
    "performing": "演出中",
    "tipping": "打赏中",
    "in_progress": "进行中",
}
# 冲突自救时优先展示的“收尾”指令：用户要先把一局结束掉，别被 N个X 之类的常规指令挤掉
_GAMEPLAY_WRAP_UP_COMMANDS = ("/结束游戏", "/收手", "/投降", "/退出")
_COMMANDS = {
    "/事件投票", "/事件投票情况",
    "/我的称号", "/佩戴称号", "/荣誉榜", "/荣誉历史",
    "/入职", "/我的物品", "/购买", "/使用", "/邀请参与", "/取消使用", "/同意使用", "/拒绝使用", "/打卡", "/余额", "/修改名称", "/编辑档案", "/编辑档案形象", "/我的档案", "/公司的故事集", "/发奖金", "/发红包", "/抢红包", "/打赏", "/我", "/商店", "/帮助", "/当前游戏", "/加入", "/退出", "/开始", "/摸鱼躲猫猫", "/记忆考核", "/答案", "/继续", "/收手", "/投降", "/队伍1", "/队伍2", "/队伍1人员", "/队伍2人员", "/公会赛场次", "/开始对战", "/上场", "/部门", "/部门人数", "/我的部门人数", "/加入部门", "/切换部门", "/部门申请列表", "/同意部门", "/全部同意部门", "/拒绝部门", "/全部拒绝部门", "/职位", "/晋升", "/晋升申请列表", "/同意", "/全部同意", "/拒绝", "/全部拒绝", "/谁是卧底", "/开始投票", "/投票", "/退出谁是卧底", "/结束游戏", "/甩锅游戏", "/甩锅", "/退出甩锅", "/我有你没有", "/发言", "/扣", "/不扣", "/国王游戏", "/国王游戏数据", "/蹦蹦数字炸弹", "/报数", "/跳过", "/德州扑克", "/看牌", "/过牌", "/跟注", "/加注", "/全下", "/弃牌", "/上架暗网", "/取消上架", "/确认", "/报价", "/公开", "/不公开", "/查看暗网", "/确认收货", "/投诉", "/预约公演", "/我的公演预约", "/取消公演预约", "/公演日程", "/延期", "/end", "/购买彩票", "/彩票", "/我的彩票", "/确认彩票", "/取消彩票", "/彩票验证",
    "/设置生日", "/我的生日", "/本月生日",
    "/随礼",
    "/大话骰子", "/开骰", "/看骰", "/牌局", "/大话骰子数据",
    "/真心换真心", "/真心换真心数据", "/问题", "/真心",
    "/罚款", "/我的罚款", "/我的津贴",
    "/凿", "/允许被凿", "/拒绝被凿", "/我的凿", "/人气榜",
    "/设置性别", "/修改性别",
}
_COMMANDS.add("/随机事件时间表")
_COMMANDS.add("/q")
_COMMANDS.update({"/黑历史", "/删除黑历史", "/下一页"})

_LOTTERY_COMMANDS = {
    "/购买彩票",
    "/彩票",
    "/我的彩票",
    "/确认彩票",
    "/取消彩票",
    "/彩票验证",
}

_DARK_MARKET_QUERY_ALIASES = {
    "/登陆暗网": "/查看暗网",
    "/登录暗网": "/查看暗网",
    "/暗网": "/查看暗网",
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
        command = _DARK_MARKET_QUERY_ALIASES.get(command, command)
        if re.fullmatch(r"/第[1-9]\d*场", command):
            command = "/公会赛场次"
        if command == "/摸鱼躲猫猫":
            return None
        if command in {"/开始摸鱼躲藏", "/躲"}:
            command = "/摸鱼躲猫猫"
        if command == "/me":
            command = "/我"
        if command in {"/装备称号", "/编辑称号"}:
            command = "/佩戴称号"
        if command == "/买彩票":
            command = "/购买彩票"
        if command in {"/问", "/问吧"}:
            command = "/问题"
        if command in {"/回答", "/答"}:
            command = "/真心"
        if command == "/罚":
            command = "/罚款"
        if command == "/修改性别":
            command = "/设置性别"
        if command in {"/今日最受欢迎", "/发情值排名", "/最受欢迎"}:
            command = "/人气榜"
        if command == "/我的发情值":
            command = "/我的凿"
        if command not in _COMMANDS:
            dice_reply = self._liar_dice_call_step(message, content)
            if dice_reply is not None:
                return dice_reply
            return self._company_lottery_draft_step(message, content)
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
        if command == "/q":
            if message.source_type != "group" or group_chat_id is None:
                return "请在群内回复一条消息后发送 /q。"
            reference = message.reference
            if reference is None or reference.content_type not in {"text", "image"}:
                return "请回复一条文字或图片消息后发送 /q。"
            text_content = (reference.text or "").strip()
            if reference.content_type == "text" and not text_content:
                return "不能记录空消息。"
            if reference.content_type == "image" and not _valid_image_url(reference.image_url):
                return "这张图片无法记录。"
            result = self._repository.record_black_history(
                message.sender_platform_id, reference.sender_platform_id,
                group_chat_id, reference.message_id, reference.content_type,
                text_content or None, reference.image_url, reference.alt, received_at,
            )
            if result.status == "recorded":
                subject = self._repository.find_user(reference.sender_platform_id)
                return f"已记入{subject.display_name}的黑历史册。"
            return {
                "duplicate": "这条已经在黑历史册里了。",
                "insufficient_balance": "摸鱼币不足，记录黑历史需要 1 摸鱼币。",
                "not_joined": "消息双方都需要先入职。",
            }.get(result.status, "记录失败，请稍后再试。")
        if command == "/黑历史":
            if message.source_type != "group" or message.reference is None:
                return "请在群内回复目标员工的一条消息后发送 /黑历史。"
            result = self._repository.draw_black_history(
                message.reference.sender_platform_id
            )
            if result.status == "not_joined":
                return "该员工尚未入职。"
            if result.entry is None or result.subject is None:
                return "这位员工还没有黑历史。"
            if result.entry.content_type == "image" and result.entry.image_url:
                return [
                    f"翻出了{result.subject.display_name}的一条黑历史。",
                    CommandReply(
                        json.dumps({
                            "image_url": result.entry.image_url,
                            "image_alt": result.entry.image_alt or "黑历史",
                        }, ensure_ascii=False),
                        content_type="history_image",
                    ),
                ]
            return CommandReply(
                json.dumps({
                    "display_name": result.subject.display_name,
                    "rank_name": result.subject_rank_name,
                    "text": result.entry.text_content or "（内容已失效）",
                }, ensure_ascii=False),
                content_type="history_card",
            )
        if command in {"/删除黑历史", "/下一页"}:
            if message.source_type != "direct":
                return "请私聊总监事管理自己的黑历史。"
            parts = content.split(maxsplit=1)
            if command == "/下一页" and not self._repository.has_black_history_delete_draft(
                message.sender_platform_id
            ):
                return "当前没有可翻页的黑历史列表，请先发送 /删除黑历史。"
            if command == "/删除黑历史" and len(parts) == 2 and parts[1].strip().isdigit():
                result = self._repository.delete_own_black_history(
                    message.sender_platform_id, int(parts[1].strip()), received_at
                )
                if result.status == "deleted":
                    return f"黑历史已删除，已扣除 5 摸鱼币。剩余 {result.remaining_count} 条。"
                return {
                    "not_found": "未找到这条属于你的黑历史。",
                    "insufficient_balance": "摸鱼币不足，删除需要 5 摸鱼币。",
                    "not_joined": "请先入职。",
                }[result.status]
            next_page = command == "/下一页" or (
                len(parts) == 2 and parts[1].strip() == "下一页"
            )
            page = self._repository.black_history_delete_page(
                message.sender_platform_id, next_page, received_at
            )
            entries, total = self._repository.list_own_black_history(message.sender_platform_id, page)
            if not entries:
                return "没有更多黑历史了。" if page > 1 else "你还没有可删除的黑历史。"
            lines = [f"你的黑历史（第 {page} 页，删除每条 5 摸鱼币）："]
            lines.extend(
                f"#{entry.id} {entry.created_at.astimezone(_BEIJING):%Y-%m-%d} "
                f"{'[图片]' if entry.content_type == 'image' else (entry.text_content or '')[:30]}"
                for entry in entries
            )
            if total > page * 5:
                lines.append("发送 /下一页 查看更多。")
            lines.append("发送 /删除黑历史 编号 删除。")
            return "\n".join(lines)
        if command in {"/我的称号", "/佩戴称号", "/荣誉榜", "/荣誉历史"}:
            return self._honors(message, command, content, received_at)
        if command in _LOTTERY_COMMANDS:
            return self._company_lottery(
                message, command, content, received_at, group_chat_id
            )
        if command == "/上场":
            return self._memory_guild_lineup(message, content, received_at)
        if command == "/答案":
            parts = content.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                return None
            if group_chat_id is not None:
                summary = self._repository.active_gameplay_summary(
                    message.sender_platform_id, received_at, group_chat_id
                )
                if summary.game_type == "memory_guild":
                    return self._memory_guild_answer(
                        message,
                        parts[1].strip(),
                        received_at,
                        group_chat_id,
                    )
            return self._memory_assessment_answer(
                message.sender_platform_id, parts[1].strip(), received_at
            )
        if command in {"/队伍1", "/队伍2", "/队伍1人员", "/队伍2人员"}:
            return self._memory_guild_team_config(
                message, content, received_at, group_chat_id
            )
        if command == "/公会赛场次":
            return self._memory_guild_series_config(
                message, content, received_at, group_chat_id
            )
        if command == "/开始对战":
            return self._memory_guild_start_round(
                message, received_at, group_chat_id
            )
        if command == "/预约公演":
            if message.source_type != "group" or group_chat_id is None:
                return "请在已启用的群聊中发送 /预约公演。"
            result = self._repository.begin_performance_draft(
                message.sender_platform_id, group_chat_id, received_at
            )
            error_messages = {
                "not_joined": "请先用 /入职 名称 加入摸鱼公司。",
                "disabled": "本群未开放公演预约。",
                "no_direct_chat": "请先私聊总监事发送任意消息，再回群预约公演。",
                "owner_busy": "你已有一个未结束的公演预约。",
            }
            if result.status in error_messages:
                return error_messages[result.status]
            return [
                "公演预约向导已通过私聊发送。",
                CommandReply(
                    "请发送公演标题（1–50字）。",
                    destination_chatroom_id=result.direct_chatroom_id,
                    delivery_kind="direct",
                ),
            ]
        if command == "/我的公演预约":
            view = self._repository.latest_own_performance(
                message.sender_platform_id
            )
            if view is None:
                return "你当前没有公演预约。"
            extension_text = ""
            if view.extension is not None:
                extension_text = (
                    f"\n延期：{view.extension.state}｜"
                    f"{view.extension.original_scheduled_at.strftime('%Y/%m/%d-%H:%M:%S')} → "
                    f"{view.extension.proposed_scheduled_at.strftime('%Y/%m/%d-%H:%M:%S')}"
                )
            reason_text = ""
            if view.rejection_reason:
                reason_text = f"\n拒绝原因：{view.rejection_reason}"
            elif view.cancellation_reason:
                reason_text = f"\n取消原因：{view.cancellation_reason}"
            return (
                f"公演：{view.title}\n状态：{view.state}\n"
                f"时间：{view.scheduled_at.strftime('%Y/%m/%d-%H:%M:%S')}\n"
                f"参演人员：{'、'.join(view.participant_names)}"
                f"{reason_text}{extension_text}"
            )
        if command == "/取消公演预约":
            result = self._repository.cancel_own_performance(
                message.sender_platform_id, received_at
            )
            return {
                "draft_cancelled": "公演预约草稿已取消。",
                "cancelled": "公演预约已取消。",
                "too_late": "公演已进入开场前 5 分钟，请联系董事会成员处理。",
                "not_joined": "请先用 /入职 名称 加入摸鱼公司。",
            }.get(result.status, "你当前没有可取消的公演预约。")
        if command == "/延期":
            if message.source_type != "direct":
                return "请私聊总监事发送 /延期 30m、/延期 1h 或 /延期 1d。"
            parts = content.split(maxsplit=1)
            if len(parts) != 2:
                return "延期格式应为 /延期 30m、/延期 1h 或 /延期 1d。"
            try:
                duration = parse_postponement(parts[1])
            except ValueError as error:
                return f"{error}。"
            result = self._repository.request_performance_postponement(
                message.sender_platform_id, duration, received_at
            )
            messages = {
                "not_joined": "请先用 /入职 名称 加入摸鱼公司。",
                "not_schedulable": "你当前没有可延期的公演预约。",
                "expired": "原定公演时间已到，不能再申请延期。",
                "already_pending": "当前已有一条待审核延期申请。",
                "out_of_range": "延期后的时间须在未来 30 分钟至 30 天内。",
                "date_taken": "延期目标日期已有公演，请更换延期时长。",
                "invalid_duration": "延期格式应为 /延期 30m、/延期 1h 或 /延期 1d。",
            }
            if result.status != "requested":
                return messages.get(result.status, "延期申请失败，请稍后重试。")
            return (
                f"已申请延期 {result.request.duration_minutes} 分钟，"
                f"新时间为 {result.request.proposed_scheduled_at.strftime('%Y/%m/%d-%H:%M:%S')}，"
                "等待管理员审核。"
            )
        if command == "/公演日程":
            if group_chat_id is None:
                return "请在群聊中发送 /公演日程。"
            views = self._repository.upcoming_performances(group_chat_id, received_at)
            if not views:
                return "本群暂无已审核的未来公演。"
            return "公演日程\n" + "\n".join(
                f"{index}. {view.title}｜{view.scheduled_at.strftime('%Y/%m/%d-%H:%M:%S')}"
                f"｜参演：{'、'.join(view.participant_names)}"
                for index, view in enumerate(views, 1)
            )
        if command == "/end":
            if message.source_type != "group" or group_chat_id is None:
                return "请在公演所在群发送 /end。"
            result = self._repository.end_performance(
                message.sender_platform_id, group_chat_id, received_at
            )
            return {
                "not_performing": "当前没有正在演出的公演。",
                "not_participant": "只有本场参演人员可以结束公演。",
                "already_tipping": "公演已进入打赏环节。",
            }.get(result.status)
        if command == "/上架暗网":
            return self._dark_market_start(message, received_at)
        if command == "/取消上架":
            return self._dark_market_cancel(message, received_at)
        if command == "/确认":
            return self._dark_market_confirm(message, received_at)
        if command == "/报价":
            return self._dark_market_bid(message, content, received_at)
        if command == "/公开" and group_chat_id is not None:
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id, received_at, group_chat_id
            )
            if summary.game_type == "king_game":
                return self._king_game_reveal(
                    message, content, received_at, group_chat_id
                )
        if command in {"/公开", "/不公开"}:
            return self._dark_market_disclose(
                message, command, content, received_at
            )
        if command in {"/确认收货", "/投诉"}:
            return self._dark_market_receipt(
                message, command, content, received_at
            )
        if command == "/查看暗网":
            return self._dark_market_login(
                message, content, received_at, group_chat_id
            )
        game_type = GROUP_GAME_COMMANDS.get(command)
        if (
            group_chat_id is not None
            and command
            in {
                "/发红包",
                "/摸鱼躲猫猫",
                "/记忆考核",
                "/谁是卧底",
                "/甩锅游戏",
                "/蹦蹦数字炸弹",
                "/德州扑克",
                "/国王游戏",
                "/大话骰子",
            }
            and self._repository.performance_blocks_new_game(group_chat_id)
        ):
            return "公演即将开始或正在进行，请稍后再创建游戏。"
        if (
            group is not None
            and not group.games_enabled
            and command in {
                "/发红包", "/摸鱼躲猫猫", "/记忆考核", "/谁是卧底",
                "/甩锅游戏", "/蹦蹦数字炸弹", "/德州扑克", "/国王游戏",
                "/大话骰子", "/真心换真心",
            }
        ):
            return self._reply(command, "disabled", received_at)
        if (
            group is not None
            and game_type is not None
            and game_type not in group.enabled_game_types
        ):
            return f"本群未开启「{GROUP_GAME_LABELS[game_type]}」。"
        if command == "/发红包":
            return self._red_packet_create(
                message, content, received_at, group_chat_id
            )
        if command == "/抢红包":
            return self._red_packet_claim(message, received_at, group_chat_id)
        if command == "/打赏":
            if (
                group_chat_id is not None
                and self._repository.active_performance_state(group_chat_id)
                == "tipping"
            ):
                return self._performance_tip(
                    message, content, received_at, group_chat_id
                )
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
        if command == "/国王游戏":
            return self._king_game_start(message, received_at, group_chat_id)
        if command == "/国王游戏数据":
            return self._king_game_statistics(message, group_chat_id)
        if command == "/大话骰子":
            return self._liar_dice_start(message, received_at, group_chat_id)
        if command == "/开骰":
            return self._liar_dice_open(message, received_at, group_chat_id)
        if command == "/牌局":
            return self._liar_dice_status(message, received_at, group_chat_id)
        if command == "/看骰":
            if message.source_type != "direct":
                return self._reply("/看骰", "group_only", received_at)
            return self._liar_dice_private_hands(message)
        if command == "/大话骰子数据":
            return self._liar_dice_statistics(message, group_chat_id)
        if command == "/真心换真心":
            return self._truth_trade_start(message, received_at, group_chat_id)
        if command == "/真心换真心数据":
            return self._truth_trade_statistics(message, group_chat_id)
        if command == "/问题":
            return self._truth_trade_ask(message, content, received_at, group_chat_id)
        if command == "/真心":
            return self._truth_trade_answer(message, content, received_at, group_chat_id)
        if command == "/罚款":
            return self._discipline_fine(message, content, received_at, group_chat_id)
        if command == "/我的罚款":
            if message.source_type != "direct":
                return "只能在私聊中使用 /我的罚款。"
            return self._my_discipline_fines(message, received_at)
        if command == "/我的津贴":
            return self._my_allowances(message.sender_platform_id, received_at)
        if command == "/凿":
            return self._estrus_chop(message, content, received_at, group_chat_id)
        if command == "/允许被凿":
            return self._set_estrus_opt_out(message, received_at, group_chat_id, False)
        if command == "/拒绝被凿":
            return self._set_estrus_opt_out(message, received_at, group_chat_id, True)
        if command == "/我的凿":
            return self._my_estrus(message, received_at, group_chat_id)
        if command == "/人气榜":
            return self._estrus_popularity(message, received_at, group_chat_id)
        if command in ("/设置性别", "/修改性别"):
            return self._set_gender(message, content, received_at)
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
        if command == "/我有你没有":
            return self._never_have_i_ever_start(
                message, received_at, group_chat_id
            )
        if command == "/发言":
            return self._never_have_i_ever_statement(
                message, content, received_at, group_chat_id
            )
        if command in {"/扣", "/不扣"}:
            return self._never_have_i_ever_response(
                message, command, received_at, group_chat_id
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
            if summary.game_type == "never_have_i_ever":
                return self._never_have_i_ever_begin(
                    message, received_at, group_chat_id
                )
            if summary.game_type == "king_game":
                return self._king_game_begin(message, received_at, group_chat_id)
            if summary.game_type == "liar_dice":
                return self._liar_dice_begin(message, received_at, group_chat_id)
            if summary.game_type == "truth_trade":
                return self._truth_trade_begin(message, received_at, group_chat_id)
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
                return self._gameplay_conflict_reply(
                    message.sender_platform_id, received_at, group_chat_id
                )
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
            if summary.game_type == "memory_guild":
                result = self._repository.end_memory_guild_match(
                    message.sender_platform_id,
                    received_at,
                    **(
                        {}
                        if group_chat_id is None
                        else {"group_chat_id": group_chat_id}
                    ),
                )
                if result.status == "forced_ended":
                    return "【记忆考核公会赛】主持人已结束本场比赛。"
                if result.status == "host_only":
                    return "只有本场主持人可以结束记忆考核公会赛。"
                return "当前没有可结束的记忆考核公会赛。"
            if summary.game_type == "never_have_i_ever":
                return self._never_have_i_ever_end(
                    message, received_at, group_chat_id
                )
            if summary.game_type == "king_game":
                return self._king_game_end(message, received_at, group_chat_id)
            if summary.game_type == "liar_dice":
                return self._liar_dice_end(message, received_at, group_chat_id)
            if summary.game_type == "truth_trade":
                return self._truth_trade_end(message, received_at, group_chat_id)
            if summary.game_type == "conflict":
                return self._gameplay_conflict_reply(
                    message.sender_platform_id, received_at, group_chat_id
                )
            return self._reply("/结束游戏", "no_current_game", received_at)
        if command == "/打卡":
            return self._check_in(message.sender_platform_id, received_at, group_chat_id)
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
        if command == "/设置生日":
            return self._set_birthday(
                message.sender_platform_id, content, received_at
            )
        if command == "/我的生日":
            return self._my_birthday(message.sender_platform_id, received_at)
        if command == "/本月生日":
            return self._month_birthdays(received_at)
        if command == "/随礼":
            return self._birthday_tip(message, content, received_at)
        if command == "/公司的故事集":
            resource_id = company_story_novel_resource_id(
                self._repository.get_game_settings().company_story_novel_url
            )
            if resource_id is None:
                return "公司故事集暂未配置，请联系管理员。"
            return CommandReply(resource_id, content_type="novel")
        if command == "/发奖金":
            return self._grant_bonus(message, content, received_at)
        if command == "/我":
            return self._me(message.sender_platform_id, received_at)
        if command == "/我的物品":
            return self._inventory(message, received_at)
        if command == "/商店":
            return self._shop(message, received_at, group_chat_id)
        if command == "/购买":
            return self._purchase(message, content, received_at, group_chat_id)
        if command == "/使用":
            return self._use_item(message, content, received_at, group_chat_id)
        if command == "/邀请参与":
            return self._invite_adult_participant(
                message, content, received_at, group_chat_id
            )
        if command == "/取消使用":
            return self._cancel_adult_use(
                message, content, received_at, group_chat_id
            )
        if command in {"/同意使用", "/拒绝使用"}:
            return self._decide_adult_use(
                message, command, received_at, group_chat_id
            )
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
        if command in {"/事件投票", "/事件投票情况"}:
            return self._random_event_vote(
                message, command, content, received_at
            )
        if command == "/随机事件时间表":
            return self._random_event_time_table(group_chat_id, received_at)
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
            if summary.game_type == "never_have_i_ever":
                return self._never_have_i_ever_join(
                    message, received_at, group_chat_id
                )
            if summary.game_type == "king_game":
                return self._king_game_join(message, received_at, group_chat_id)
            if summary.game_type == "liar_dice":
                return self._liar_dice_join(message, received_at, group_chat_id)
            if summary.game_type == "truth_trade":
                return self._truth_trade_join(message, received_at, group_chat_id)
            if summary.game_type == "conflict":
                return self._gameplay_conflict_reply(
                    message.sender_platform_id, received_at, group_chat_id
                )
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
            if summary.game_type == "memory_guild":
                return "记忆考核公会赛不支持退出或投降；仅主持人可发送 /结束游戏。"
            if summary.game_type == "never_have_i_ever":
                return self._never_have_i_ever_leave(
                    message, received_at, group_chat_id
                )
            if summary.game_type == "king_game":
                return self._king_game_leave(message, received_at, group_chat_id)
            if summary.game_type == "liar_dice":
                return self._liar_dice_leave(message, received_at, group_chat_id)
            if summary.game_type == "truth_trade":
                return self._truth_trade_leave(message, received_at, group_chat_id)
            if summary.game_type == "conflict":
                return self._gameplay_conflict_reply(
                    message.sender_platform_id, received_at, group_chat_id
                )
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
            if summary.game_type == "king_game":
                return self._king_game_continue(
                    message, received_at, group_chat_id
                )
            if summary.game_type == "liar_dice":
                return self._liar_dice_continue(message, received_at, group_chat_id)
            if summary.game_type == "truth_trade":
                return self._truth_trade_continue(message, received_at, group_chat_id)
            if summary.game_type == "conflict":
                return self._gameplay_conflict_reply(
                    message.sender_platform_id, received_at, group_chat_id
                )
            return self._memory_assessment_continue(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/收手":
            return self._memory_assessment_cash_out(
                message.sender_platform_id, received_at, group_chat_id
            )
        if command == "/投降":
            summary = self._repository.active_gameplay_summary(
                message.sender_platform_id, received_at, group_chat_id
            )
            if summary.game_type == "memory_guild":
                return "记忆考核公会赛不支持退出或投降；仅主持人可发送 /结束游戏。"
            return self._memory_assessment_surrender(
                message.sender_platform_id, received_at, group_chat_id
            )
        return self._help(content, received_at)

    def _dark_market_start(self, message: InboundMessage, received_at):
        if message.source_type != "direct":
            return self._reply("/上架暗网", "private_only", received_at)
        result = self._repository.start_dark_market_draft(
            message.sender_platform_id, received_at
        )
        if result.status == "not_joined":
            return self._reply("/上架暗网", "not_joined", received_at)
        if result.status == "unavailable":
            return self._reply("/上架暗网", "unavailable", received_at)
        return self._reply("/上架暗网", result.step or "name", received_at)

    def _dark_market_cancel(self, message: InboundMessage, received_at):
        if message.source_type != "direct":
            return self._reply("/取消上架", "private_only", received_at)
        result = self._repository.cancel_dark_market_draft(
            message.sender_platform_id, received_at
        )
        scenario = (
            result.status
            if result.status in {"cancelled", "not_joined"}
            else "no_draft"
        )
        return self._reply("/取消上架", scenario, received_at)

    def _dark_market_confirm(self, message: InboundMessage, received_at):
        if message.source_type != "direct":
            return self._reply("/确认", "private_only", received_at)
        result = self._repository.confirm_dark_market_listing(
            message.sender_platform_id,
            message.platform_message_id,
            received_at,
        )
        if result.status == "listed" and result.listing is not None:
            return self._reply(
                "/确认",
                "listed",
                received_at,
                {"{商品编号}": result.listing.public_number},
            )
        return self._reply("/确认", result.status, received_at)

    def _dark_market_bid(
        self, message: InboundMessage, content: str, received_at
    ):
        if message.source_type != "direct":
            return self._reply("/报价", "private_only", received_at)
        parts = content.split()
        if (
            len(parts) != 3
            or not all(part.isascii() and part.isdigit() for part in parts[1:])
        ):
            return self._reply("/报价", "usage", received_at)
        result = self._repository.place_dark_market_bid(
            message.sender_platform_id,
            int(parts[1]),
            int(parts[2]),
            message.platform_message_id,
            received_at,
        )
        if result.status == "accepted":
            return self._reply(
                "/报价",
                "accepted",
                received_at,
                {
                    "{商品编号}": result.public_number,
                    "{金额}": result.amount,
                    "{冻结金额}": result.frozen_amount,
                    "{货币}": self._repository.get_game_settings().currency_name,
                },
            )
        if result.status == "too_low":
            return self._reply(
                "/报价",
                "too_low",
                received_at,
                {
                    "{最低报价}": result.minimum_amount,
                    "{货币}": self._repository.get_game_settings().currency_name,
                },
            )
        return self._reply("/报价", result.status, received_at)

    def _dark_market_disclose(
        self,
        message: InboundMessage,
        command: str,
        content: str,
        received_at,
    ):
        if message.source_type != "direct":
            return self._reply(command, "private_only", received_at)
        parts = content.split()
        if len(parts) > 2 or (
            len(parts) == 2
            and (not parts[1].isascii() or not parts[1].isdigit())
        ):
            return self._reply(command, "usage", received_at)
        result = self._repository.decide_dark_market_disclosure(
            message.sender_platform_id,
            None if len(parts) == 1 else int(parts[1]),
            command == "/公开",
            message.platform_message_id,
            received_at,
        )
        if result.status == "choose_listing":
            numbers = "、".join(f"#{number}" for number in result.candidates)
            return self._reply(
                command,
                "choose_listing",
                received_at,
                {"{商品编号列表}": numbers},
            )
        return self._reply(command, result.status, received_at)

    def _dark_market_login(
        self,
        message: InboundMessage,
        content: str,
        received_at,
        group_chat_id,
    ):
        if message.source_type not in {"group", "direct"}:
            return self._reply("/查看暗网", "group_only", received_at)
        parts = content.split()
        if len(parts) > 2 or (
            len(parts) == 2
            and (not parts[1].isascii() or not parts[1].isdigit())
        ):
            return self._reply("/查看暗网", "usage", received_at)
        result = self._repository.browse_dark_market(
            group_chat_id,
            received_at,
            None if len(parts) == 1 else int(parts[1]),
            direct=message.source_type == "direct",
        )
        if result.status == "wrong_group":
            return self._reply("/查看暗网", result.status, received_at)
        is_full_list = len(parts) == 1
        if message.source_type == "group" and is_full_list:
            if (
                result.status == "shown"
                and message.chatroom_id is not None
                and self._repository.has_pending_dark_market_list_delivery(
                    message.chatroom_id
                )
            ):
                return None
            values = (
                {"{商品列表}": result.text or ""}
                if result.status == "shown"
                else None
            )
            return self._reply(
                "/查看暗网", result.status, received_at, values
            )
        if message.source_type == "group":
            direct_chatroom_id = self._repository.direct_chat_destination(
                message.sender_platform_id
            )
            if direct_chatroom_id is None:
                return "请先私聊总监事发送任意消息，再重新发送 /暗网。"
        elif is_full_list:
            settings = self._repository.get_dark_market_settings()
            destination_chatroom_id = (
                self._repository.group_chat_destination(
                    settings.announcement_group_id
                )
                if settings.announcement_group_id is not None
                else None
            )
            notice = self._reply("/查看暗网", "private_list", received_at)
            if destination_chatroom_id is None:
                return notice
            if self._repository.has_pending_dark_market_list_delivery(
                destination_chatroom_id
            ):
                return notice
            values = (
                {"{商品列表}": result.text or ""}
                if result.status == "shown"
                else None
            )
            return [
                CommandReply(
                    notice,
                    destination_chatroom_id=message.chatroom_id,
                    delivery_kind="direct",
                ),
                CommandReply(
                    self._reply("/查看暗网", result.status, received_at, values),
                    destination_chatroom_id=destination_chatroom_id,
                    delivery_kind="group",
                    group_chat_id=settings.announcement_group_id,
                ),
            ]
        values = (
            {"{商品列表}": result.text or ""}
            if result.status == "shown"
            else None
        )
        response = self._reply(
            "/查看暗网",
            result.status,
            received_at,
            values,
        )
        if message.source_type == "group":
            return CommandReply(
                response,
                destination_chatroom_id=direct_chatroom_id,
                delivery_kind="direct",
            )
        return response

    def _dark_market_receipt(
        self,
        message: InboundMessage,
        command: str,
        content: str,
        received_at,
    ):
        if message.source_type != "direct":
            return self._reply(command, "private_only", received_at)
        parts = content.split()
        if len(parts) > 2 or (
            len(parts) == 2
            and (not parts[1].isascii() or not parts[1].isdigit())
        ):
            return self._reply(command, "usage", received_at)
        result = self._repository.resolve_dark_market_receipt(
            message.sender_platform_id,
            None if len(parts) == 1 else int(parts[1]),
            "confirm" if command == "/确认收货" else "complain",
            message.platform_message_id,
            received_at,
        )
        if result.status == "choose_listing":
            numbers = "、".join(f"#{number}" for number in result.candidates)
            return self._reply(
                command,
                "choose_listing",
                received_at,
                {"{商品编号列表}": numbers},
            )
        return self._reply(
            command,
            result.status,
            received_at,
            {"{商品编号}": result.public_number or ""},
        )

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

    def _gameplay_conflict_reply(
        self, platform_id: str, received_at, group_chat_id=None
    ) -> str:
        """同群多局并存时列出各局与各自的收尾指令，让人能自己解开。

        历史文案只会说「检测到多个活动游戏，请联系管理员处理」，用户无从下手
        （而管理端的强制结束入口过去也不发公告）。这里改为只读地列出当前活跃玩法，
        不改动任何对局状态；列不出内容时回落到原模板。
        """
        conflicts = self._repository.active_gameplay_conflicts(
            platform_id, received_at, group_chat_id
        )
        if not conflicts:
            return self._reply("/当前游戏", "conflict", received_at)
        marks = "①②③④⑤⑥⑦⑧⑨"
        lines = [f"【当前游戏】检测到 {len(conflicts)} 局同时进行："]
        for index, item in enumerate(conflicts[:5]):
            label = _GAMEPLAY_LABELS.get(item.game_type or "", "当前玩法")
            details: list[str] = []
            if item.round_number:
                details.append(f"第 {item.round_number} 轮")
            state_label = _GAMEPLAY_STATE_LABELS.get(item.state or "")
            if state_label:
                details.append(state_label)
            suffix = f"（{'，'.join(details)}）" if details else ""
            commands = list(item.available_commands)
            wrap_up = [c for c in _GAMEPLAY_WRAP_UP_COMMANDS if c in commands]
            shown = (wrap_up + [c for c in commands if c not in wrap_up])[:3]
            action = f"发 {' 或 '.join(shown)}" if shown else "需由本局参与者操作"
            lines.append(f"{marks[index]} {label}{suffix} — {action}")
        if len(conflicts) > 5:
            lines.append(f"……以及另外 {len(conflicts) - 5} 局")
        lines.append("请先给其中一局收尾，另一局会继续。")
        return "\n".join(lines)

    def _current_game(self, platform_id: str, received_at, group_chat_id=None) -> str:
        summary = self._repository.active_gameplay_summary(
            platform_id, received_at, group_chat_id
        )
        if summary.game_type is None:
            return self._reply("/当前游戏", "none", received_at)
        if summary.game_type == "conflict":
            return self._gameplay_conflict_reply(
                platform_id, received_at, group_chat_id
            )
        game_name = _GAMEPLAY_LABELS[summary.game_type]
        if (
            summary.game_type == "number_bomb"
            and summary.mode == "points_tournament"
        ):
            game_name = "蹦蹦数字炸弹积分赛"
        state_name = {
            "signup": "报名中",
            "waiting_opponent": "等待对手",
            "configuring": "配置队伍中",
            "waiting_lineup": "等待私聊选手",
            "ready": "等待主持人开题",
            "showing": "题目展示中",
            "answering": "作答中",
            "waiting_round_start": "等待下一小局",
            "waiting_series": "等待配置下一场",
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
            "awaiting_statement": "等待发言",
            "awaiting_responses": "等待回应",
            "free_punishment": "自由惩罚",
            "awaiting_reveal": "等待国王公开",
            "revealed": "等待下一轮",
            "calling": "叫牌中",
            "round_end": "回合结束",
        }.get(summary.state, "进行中")
        if (
            summary.game_type == "number_bomb"
            and summary.mode == "points_tournament"
        ):
            state_name = (
                f"{state_name}（第 {summary.round_number}/{summary.maximum_rounds} 轮；"
                f"你的积分：{summary.actor_total_points or 0} 分）"
            )
        if summary.game_type == "never_have_i_ever":
            details = []
            if summary.actor_number is not None and summary.actor_hearts is not None:
                heart_display = self._never_have_i_ever_hearts(
                    summary.actor_hearts, len(summary.participant_names) + 2
                )
                details.append(
                    f"你的编号：{summary.actor_number}号，心数："
                    f"{heart_display}"
                )
            if summary.current_speaker_name is not None:
                details.append(f"当前发言者：{summary.current_speaker_name}")
            if summary.state == "awaiting_responses":
                details.append(
                    f"回应：{summary.responded_count}/"
                    f"{summary.expected_response_count}"
                )
            if summary.phase_deadline is not None:
                details.append(
                    f"截止：{summary.phase_deadline.strftime('%H:%M:%S')}"
                )
            if details:
                state_name = f"{state_name}（{'；'.join(details)}）"
        if summary.game_type == "truth_trade":
            state_name = {
                "asking": "提问轮",
                "answering": "回答轮",
                "round_complete": "轮次结束",
            }.get(summary.state, state_name)
            details = []
            if summary.state == "asking" and summary.current_speaker_name:
                details.append(
                    f"轮到 {summary.current_speaker_name} 提问，发送 /问题 你的问题"
                )
            if summary.state == "answering" and summary.current_speaker_name:
                details.append(
                    f"{summary.current_speaker_name} 的问题收集中："
                    f"{summary.responded_count}/{summary.expected_response_count}"
                )
            if summary.state == "round_complete":
                details.append("发送 /继续 开下一轮")
            if summary.actor_number is not None:
                details.append(f"你的编号：{summary.actor_number}号")
            details.append(f"当前玩家共 {len(summary.participant_names)} 人")
            if summary.phase_deadline is not None:
                details.append(
                    f"截止：{summary.phase_deadline.strftime('%H:%M:%S')}"
                )
            if details:
                state_name = f"{state_name}（{'；'.join(details)}）"
        role_name = {
            "participant": "参与者",
            "candidate": "下一轮候选",
            "host": "发起者",
            "eliminated": "已出局",
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

    @staticmethod
    def _never_have_i_ever_hearts(hearts: int, maximum_hearts: int) -> str:
        return render_never_have_i_ever_hearts(hearts, maximum_hearts)

    def _never_have_i_ever_player_lines(self, players) -> str:
        return render_never_have_i_ever_player_lines(players)

    def _never_have_i_ever_start(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /我有你没有。"
        result = self._repository.start_never_have_i_ever(
            message.sender_platform_id, received_at, group_chat_id
        )
        errors = {
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "disabled": "我有你没有当前未开放。",
            "daily_limit": "你今天可发起的多人小游戏次数已用完。",
            "multiplayer_active": "当前已有游戏或随机事件进行中。",
            "already_active": "当前已有我有你没有对局。",
        }
        if result.status in errors:
            return errors[result.status]
        return (
            f"【我有你没有】{result.display_name} 发起了报名，当前 "
            f"{len(result.players)} 人。请发送 /加入 报名；至少 3 人后由发起者发送 /开始。"
        )

    def _never_have_i_ever_join(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /加入。"
        result = self._repository.join_never_have_i_ever(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "joined":
            return (
                f"{result.display_name} 已加入我有你没有，当前 "
                f"{len(result.players)} 人。"
            )
        return {
            "no_game": "当前没有可加入的我有你没有报名局。",
            "already_started": "本局我有你没有已经开始，不能再加入。",
            "already_joined": "你已经在当前我有你没有对局中。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
        }.get(result.status, "当前不能加入我有你没有。")

    def _never_have_i_ever_begin(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /开始。"
        result = self._repository.begin_never_have_i_ever(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "started":
            speaker = next(
                player
                for player in result.players
                if player.number == result.current_speaker_number
            )
            timeout_seconds = (
                self._repository.get_never_have_i_ever_settings()
                .statement_timeout_seconds
            )
            return (
                "【我有你没有】游戏开始！\n"
                f"{self._never_have_i_ever_player_lines(result.players)}\n"
                f"请 {speaker.number}号 {speaker.display_name} 在 {timeout_seconds} 秒内发送 /发言 内容。"
            )
        return {
            "no_game": "当前没有可开始的我有你没有报名局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "host_only": "只有发起者可以开始我有你没有。",
            "not_enough_players": "当前人数不足，至少 3 人才能开始。",
            "already_started": "本局我有你没有已经开始。",
        }.get(result.status, "当前不能开始我有你没有。")

    def _never_have_i_ever_statement(
        self, message, content, received_at, group_chat_id
    ):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /发言 内容。"
        payload = content[len("/发言"):].strip()
        result = self._repository.submit_never_have_i_ever_statement(
            message.sender_platform_id, payload, received_at, group_chat_id
        )
        if result.status == "statement_recorded":
            timeout_seconds = (
                self._repository.get_never_have_i_ever_settings()
                .response_timeout_seconds
            )
            return (
                f"【我有你没有】{result.display_name} 发言：{payload}\n"
                f"其余存活玩家请在 {timeout_seconds} 秒内发送 /扣（没有这项经历）或 /不扣（也有这项经历）。"
            )
        return {
            "empty_statement": "请发送 /发言 内容，内容不能为空。",
            "no_game": "当前没有我有你没有对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "wrong_phase": "当前不是发言阶段。",
            "not_current_speaker": "还没有轮到你发言。",
        }.get(result.status, "当前不能发言。")

    def _never_have_i_ever_response(
        self, message, command, received_at, group_chat_id
    ):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /扣 或 /不扣。"
        result = self._repository.respond_never_have_i_ever(
            message.sender_platform_id,
            command == "/扣",
            received_at,
            group_chat_id,
        )
        if result.status == "response_recorded":
            return (
                f"{result.display_name} 已选择（{result.responded_count}/"
                f"{result.expected_response_count}）。"
            )
        if result.status in {"round_settled", "free_punishment"}:
            return render_never_have_i_ever_round_settlement(result)
        return {
            "no_game": "当前没有我有你没有对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "wrong_phase": "当前不是回应阶段。",
            "not_participant": "你不是本局参与者。",
            "speaker_cannot_respond": "发言者本人不需要回应。",
            "not_active": "你已出局，不能回应。",
            "already_responded": "你本轮已经选择，不能修改。",
        }.get(result.status, "当前不能回应。")

    def _never_have_i_ever_leave(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /退出。"
        result = self._repository.leave_never_have_i_ever(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "signup_cancelled":
            return "【我有你没有】发起者已退出，报名局已取消。"
        if result.status == "signup_left":
            return "你已退出我有你没有报名。"
        if result.status == "left_game":
            return "你已退出本局，心数归零并视为出局。"
        if result.status == "free_punishment":
            return "【我有你没有】已达到出局阈值，进入自由惩罚阶段。"
        return {
            "no_game": "当前没有我有你没有对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "你没有参与当前我有你没有对局。",
        }.get(result.status, "当前不能退出我有你没有。")

    def _never_have_i_ever_end(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /结束游戏。"
        result = self._repository.end_never_have_i_ever(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "completed":
            return (
                "【我有你没有】本局结束，最终心数排名：\n"
                f"{self._never_have_i_ever_player_lines(result.players)}"
            )
        return {
            "no_game": "当前没有可结束的我有你没有对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "你没有参与当前我有你没有对局。",
            "not_active": "你已出局，不能结束本局。",
            "cannot_end": "尚未进入自由惩罚阶段，不能结束本局。",
        }.get(result.status, "当前不能结束我有你没有。")

    def _king_game_start(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /国王游戏。"
        result = self._repository.start_king_game(
            message.sender_platform_id, received_at, group_chat_id
        )
        messages = {
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "disabled": "国王游戏当前未开放。",
            "multiplayer_active": "当前已有游戏或随机事件进行中。",
            "already_active": "当前已有国王游戏对局。",
        }
        if result.status in messages:
            return messages[result.status]
        return (
            "【国王游戏】报名已开启。请发送 /加入 报名；至少 3 人后，"
            "发起者发送 /开始 抽取本轮国王。"
        )

    def _king_game_join(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /加入。"
        result = self._repository.join_king_game(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "joined":
            return f"已加入国王游戏，当前 {len(result.players)} 人。"
        if result.status == "queued":
            return "已加入下一轮候选，下一轮开始时自动加入。"
        return {
            "no_game": "当前没有可加入的国王游戏报名局。",
            "already_joined": "你已经在当前国王游戏中。",
            "already_queued": "你已经在下一轮候选中。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
        }.get(result.status, "当前不能加入国王游戏。")

    def _king_game_begin(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /开始。"
        result = self._repository.begin_king_game(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "started":
            return self._king_game_turn_message(result)
        return {
            "no_game": "当前没有可开始的国王游戏报名局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "host_only": "只有发起者可以开始国王游戏。",
            "not_enough_players": "当前人数不足，至少 3 人才能开始。",
            "already_started": "本局国王游戏已经开始。",
        }.get(result.status, "当前不能开始国王游戏。")

    def _king_game_reveal(self, message, content, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在国王游戏所在群发送 /公开 编号。"
        payload = content[len("/公开"):].strip()
        result = self._repository.reveal_king_game_numbers(
            message.sender_platform_id, payload, received_at, group_chat_id
        )
        if result.status == "revealed":
            mapping = "、".join(
                f"{number}号：{name}" for number, name in result.number_map
            )
            return (
                f"【国王游戏】第 {result.round_number} 轮公开！\n{mapping}\n"
                "本轮命令已生效。任一参与者发送 /继续 开启下一轮。"
            )
        return {
            "no_game": "当前没有国王游戏对局。",
            "king_only": "只有本轮国王可以公开编号。",
            "invalid_numbers": "格式应为 /公开 2 5；编号不可重复，且必须在本轮人数范围内。",
            "wrong_state": "当前不是公开编号阶段。",
        }.get(result.status, "当前不能公开编号。")

    def _king_game_continue(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在国王游戏所在群发送 /继续。"
        result = self._repository.continue_king_game(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "next_round":
            return self._king_game_turn_message(result)
        if result.status == "completed":
            return "【国王游戏】剩余人数不足 3 人，本局结束。"
        return {
            "no_game": "当前没有国王游戏对局。",
            "not_participant": "只有本局参与者可以继续。",
            "wrong_state": "请等待国王先发送 /公开 编号。",
        }.get(result.status, "当前不能继续国王游戏。")

    def _king_game_leave(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在国王游戏所在群发送 /退出。"
        result = self._repository.leave_king_game(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "left_game":
            return "你已退出本局国王游戏。"
        if result.status == "leave_queued":
            return "已登记退出，本轮仍按当前编号参与；下一轮开始时生效。"
        if result.status == "completed":
            return "【国王游戏】剩余参与者不足 3 人，本局已结束。"
        return {
            "no_game": "当前没有国王游戏对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "你没有参与当前国王游戏。",
        }.get(result.status, "当前不能退出国王游戏。")

    def _king_game_end(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在国王游戏所在群发送 /结束游戏。"
        result = self._repository.end_king_game(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "completed":
            return "【国王游戏】参与者已结束本局游戏。\n" + self._king_game_statistics_message(
                result.statistics
            )
        return {
            "no_game": "当前没有可结束的国王游戏。",
            "not_participant": "只有本局参与者可以结束游戏。",
        }.get(result.status, "当前不能结束国王游戏。")

    def _king_game_statistics(self, message, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在国王游戏所在群发送 /国王游戏数据。"
        statistics = self._repository.king_game_statistics(group_chat_id)
        if statistics is None:
            return "当前没有国王游戏对局。"
        return self._king_game_statistics_message(statistics)

    @staticmethod
    def _king_game_statistics_message(statistics) -> str:
        def line(label, leaders) -> str:
            if not leaders:
                return f"{label}：暂无"
            return f"{label}：" + "、".join(
                f"{name}（{count} 次）" for name, count in leaders
            )

        return "\n".join((
            "【国王游戏数据】",
            line("国王次数最多", statistics.king_leaders),
            line("受罚次数最多", statistics.penalty_leaders),
            line("回旋镖次数最多", statistics.boomerang_leaders),
        ))

    def _king_game_turn_message(self, result) -> str:
        timeout = self._repository.get_king_game_settings().king_phase_timeout_seconds
        return (
            f"【国王游戏】第 {result.round_number} 轮\n"
            f"本轮国王：{result.king_name}。请国王先在群内发布命令，"
            f"再于 {timeout} 秒内发送 /公开 编号（例如 /公开 2 5）。\n"
            "号码在公开前仅国王可知；系统不会判断命令内容。"
        )

    def _liar_dice_start(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /大话骰子。"
        result = self._repository.start_liar_dice(
            message.sender_platform_id, received_at, group_chat_id
        )
        messages = {
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "disabled": "大话骰子当前未开放。",
            "multiplayer_active": "当前已有游戏或随机事件进行中。",
            "already_active": "当前已有大话骰子对局。",
        }
        if result.status in messages:
            return messages[result.status]
        settings = self._repository.get_liar_dice_settings()
        return (
            "【大话骰子】报名已开启！想玩的发 /加入（每人 5 骰、每轮随机万能点；"
            f"需要先和机器人私聊过），至少 {result.min_players} 人后发起者发 /开始 摇骰开局。"
            f"\n⏳ 报名 {settings.signup_timeout_minutes} 分钟内没人 /开始将自动取消；"
            f"每回合 {settings.turn_seconds} 秒，超时自动跳到最后。"
        )

    def _liar_dice_join(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /加入。"
        result = self._repository.join_liar_dice(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "signup_joined":
            return f"已加入大话骰子，当前 {len(result.players)} 人。"
        if result.status == "next_round_joined":
            return "已加入大话骰子，下一轮开骰时参战。"
        return {
            "no_game": "当前没有可加入的大话骰子报名局，发 /大话骰子 发起。",
            "already_joined": "你已经在当前大话骰子局中。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
        }.get(result.status, "当前不能加入大话骰子。")

    def _liar_dice_begin(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /开始。"
        result = self._repository.begin_liar_dice(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "dealing":
            return (
                f"【大话骰子】第 {result.round_number} 轮摇骰中（{len(result.players)} 人），"
                "骰子正在私聊发放，未收到的话稍后私聊发 /看骰。"
            )
        if result.status == "missing_direct_chats":
            return (
                "以下成员还没有和机器人私聊过，无法私发骰子："
                f"{result.public_message}。请先各自私聊机器人发一句话，再发 /开始。"
            )
        return {
            "no_game": "当前没有可开始的大话骰子报名局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "host_only": "只有发起者可以开始大话骰子。",
            "not_enough_players": f"当前人数不足，至少 {result.min_players} 人才能开始。",
            "already_started": "本局大话骰子已经开始。",
        }.get(result.status, "当前不能开始大话骰子。")

    def _liar_dice_call_step(self, message: InboundMessage, content: str):
        call = parse_call(content)
        if call is None or message.source_type != "group":
            return None
        group = self._repository.resolve_enabled_group_chat(message.chatroom_id)
        if group is None:
            return None
        received_at = message.received_at.astimezone(_BEIJING)
        result = self._repository.liar_dice_call(
            message.sender_platform_id, call, received_at, group.id
        )
        if result.status in {"no_game", "not_joined"}:
            # 本群没有大话骰子局 / 发送者还没入职：保持静默，否则群里任何人打「3个5」都会被搭话
            return None
        if result.status == "wrong_state":
            # 本局确实存在，但当前不在叫牌阶段（报名中 / 发牌中 / 本轮已结束或已作废）
            sender_in_game = any(
                player.platform_id == message.sender_platform_id
                for player in result.players
            )
            if not sender_in_game:
                return None
            if result.game_state == "signup":
                return "还在报名中，等发起者发 /开始 摇骰开局～"
            if result.game_state == "dealing":
                return "骰子还在私聊发放中，稍等一下再叫～"
            return "本轮已作废或已结束，发 /继续 开下一轮，或 /结束游戏 收尾。"
        if result.status == "called":
            return result.public_message
        if result.status == "invalid_raise":
            return "叫数不合法哦～要比上一个大（个数更多，或点数更大），首叫至少为在场人数～"
        if result.status == "not_your_turn":
            return f"还没轮到你哦～现在轮到 {result.turn_name}～"
        return None

    def _liar_dice_open(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在大话骰子所在群发送 /开骰。"
        result = self._repository.liar_dice_open(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "opened":
            return result.public_message
        if result.status == "not_your_turn":
            return f"还没轮到你哦～现在轮到 {result.turn_name}～"
        return {
            "no_game": "当前没有大话骰子对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "wrong_state": "当前不在叫牌阶段，无法开牌。",
            "no_call": "还没有人叫数呢，不能开～",
            "own_call": "你不能开自己叫的数哦～",
        }.get(result.status, "当前不能开牌。")

    def _liar_dice_continue(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /继续。"
        result = self._repository.liar_dice_continue(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "dealing":
            return (
                f"【大话骰子】第 {result.round_number} 轮摇骰中（{len(result.players)} 人），"
                "新骰子正在私聊发放，未收到的话稍后私聊发 /看骰。"
            )
        if result.status == "completed":
            return liar_dice_end_message(
                "【大话骰子】剩余人数不足 2 人，本局结束。", result.statistics
            )
        return {
            "no_game": "当前没有大话骰子对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "只有本局参与者可以继续。",
            "wrong_state": "本轮还在进行中，等开牌后再 /继续。",
        }.get(result.status, "当前不能继续大话骰子。")

    def _liar_dice_leave(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /退出。"
        result = self._repository.leave_liar_dice(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "left_game":
            return "你已退出本局大话骰子。"
        if result.status == "leave_queued":
            return "已登记退出，本轮结束后生效。"
        if result.status == "completed":
            return liar_dice_end_message(
                "【大话骰子】剩余人数不足 2 人，本局已结束。", result.statistics
            )
        return {
            "no_game": "当前没有大话骰子对局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "你没有参与当前大话骰子局。",
        }.get(result.status, "当前不能退出大话骰子。")

    def _liar_dice_end(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /结束游戏。"
        result = self._repository.liar_dice_end(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "completed":
            return liar_dice_end_message(
                "【大话骰子】本局结束。", result.statistics
            )
        return {
            "no_game": "当前没有可结束的大话骰子局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "只有本局参与者可以结束游戏。",
        }.get(result.status, "当前不能结束大话骰子。")

    def _liar_dice_status(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /牌局。"
        result = self._repository.liar_dice_status(received_at, group_chat_id)
        if result.status == "no_game":
            return "当前没有进行中的大话骰子局哦～发 /大话骰子 发起～"
        if result.status in {"status_signup", "status_round_end"}:
            return result.public_message or "【大话骰子】对局进行中。"
        return result.public_message or "【大话骰子】对局进行中。"

    def _liar_dice_private_hands(self, message):
        result = self._repository.liar_dice_private_hands(
            message.sender_platform_id,
            message.received_at.astimezone(_BEIJING),
        )
        if result.status == "shown":
            return result.private_message
        return "你当前没有进行中的大话骰子骰子哦～"

    def _liar_dice_statistics(self, message, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /大话骰子数据。"
        report = self._repository.liar_dice_statistics(group_chat_id)
        lines = ["【大话骰子数据】"]
        if report.current is not None:
            lines.append("本局：")
            lines.extend(self._liar_dice_statistic_lines(report.current))
        lines.append("总历史数据：")
        lines.extend(self._liar_dice_statistic_lines(report.career))
        return "\n".join(lines)

    @staticmethod
    def _liar_dice_statistic_lines(statistics) -> list[str]:
        return liar_dice_statistic_lines(statistics)

    @classmethod
    def _liar_dice_statistics_message(cls, statistics) -> str:
        return "\n".join(
            ("【大话骰子数据】", *cls._liar_dice_statistic_lines(statistics))
        )

    # ------------------------------------------------------------------
    # 真心换真心
    # ------------------------------------------------------------------

    def _truth_trade_start(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /真心换真心。"
        result = self._repository.start_truth_trade(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "disabled":
            return "真心换真心当前未开放。"
        if result.status == "already_active":
            return "当前已有真心换真心对局。"
        if result.status == "multiplayer_active":
            return "当前已有游戏或随机事件进行中。"
        return (
            f"【真心换真心】报名开启，发送 /加入 报名；"
            f"至少 {result.min_players} 人后发起者 /开始。"
        )

    def _truth_trade_join(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /加入。"
        result = self._repository.join_truth_trade(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "no_game":
            return "当前没有可加入的真心换真心局。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "already_joined":
            return "你已经在当前真心换真心局中。"
        return result.public_message or "当前不能加入真心换真心。"

    def _truth_trade_begin(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /开始。"
        result = self._repository.begin_truth_trade(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "no_game":
            return "当前没有可开始的真心换真心报名局。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "already_started":
            return "本局真心换真心已经开始。"
        if result.status == "host_only":
            return "只有发起者可以开始真心换真心。"
        if result.status == "not_enough_players":
            return f"报名人数不足 {result.min_players} 人，无法开始。"
        return result.public_message or "当前不能开始真心换真心。"

    def _truth_trade_ask(self, message, content, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /问 内容。"
        # /问、/问吧 是 /问题 的别名，handle 里归一化成 /问题 路由到这里；
        # content 保留原文，按实际前缀剥离（/问吧 必须在 /问 之前判断）
        prefix = next(
            p for p in ("/问吧", "/问题", "/问") if content.startswith(p)
        )
        payload = content[len(prefix):].strip()
        result = self._repository.ask_truth_trade(
            message.sender_platform_id,
            payload,
            received_at,
            group_chat_id,
        )
        if result.status == "no_game":
            return "当前没有进行中的真心换真心局。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "not_participant":
            return "只有当前玩家可以提问。"
        if result.status == "not_your_turn":
            if result.asker_position is not None and result.asker_name:
                return (
                    f"还没轮到你提问，当前轮到 {result.asker_position}号 "
                    f"{result.asker_name}。"
                )
            return "还没轮到你提问。"
        if result.status == "empty_question":
            return "请发送 /问 内容，问题不能为空。"
        return result.public_message or "当前不能提问。"

    def _truth_trade_answer(self, message, content, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /回答 内容。"
        # /回答、/答 是 /真心 的别名，handle 里归一化成 /真心 路由到这里；
        # content 保留原文，按实际前缀剥离
        prefix = next(
            p for p in ("/回答", "/真心", "/答") if content.startswith(p)
        )
        payload = content[len(prefix):].strip()
        result = self._repository.answer_truth_trade(
            message.sender_platform_id,
            payload,
            received_at,
            group_chat_id,
        )
        errors = {
            "no_game": "当前没有进行中的真心换真心局。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "not_participant": "只有当前玩家可以回答。",
            "wrong_state": "当前没有开放的问题。",
            "asker_cannot_answer": "这是你提的问题，等其他人的回答吧。",
            "not_required": "你加入晚于本题，无需回答。",
            "already_answered": "你已经回答过本题了。",
            "empty_answer": "请发送 /回答 内容，回答不能为空。",
        }
        if result.status in errors:
            return errors[result.status]
        return result.public_message or "当前不能回答。"

    def _discipline_fine(self, message, content, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中执行罚款。"
        # /罚 是 /罚款 的别名；content 保留原文，按实际前缀剥离（/罚款 必须在 /罚 之前判断）
        prefix = next(p for p in ("/罚款", "/罚") if content.startswith(p))
        payload = content[len(prefix):].strip()
        reference = message.reference
        if reference is not None and reference.sender_platform_id:
            # 引用形态：引用优先于名字参数，payload 整体作为理由
            target_platform_id = reference.sender_platform_id
            target_name = None
            reason = payload or None
            via_reply = True
        else:
            parts = payload.split(None, 1)
            if not parts:
                return (
                    "用法：引用对方消息发送 /罚款 [理由]，"
                    "或发送 /罚款 名字 [理由]。"
                )
            target_name = parts[0]
            reason = parts[1].strip() if len(parts) > 1 else None
            target_platform_id = None
            via_reply = False
        result = self._repository.execute_discipline_fine(
            message.sender_platform_id,
            target_name=target_name,
            target_platform_id=target_platform_id,
            reason=reason,
            via_reply=via_reply,
            received_at=received_at,
            group_chat_id=group_chat_id,
        )
        errors = {
            "disabled": "风纪罚款未开启。",
            "not_configured": "风纪罚款未配置执法部门，请在后台「职位与部门」的部门津贴中选择风纪执法。",
            "not_joined": "请先用 /入职 名字 加入摸鱼公司。",
            "quota_zero": "你的职级今日无可用的罚款次数（配额为 0）。",
            "quota_exhausted": "你今日的罚款次数已用完，明天再来吧。",
            "target_not_joined": "目标还未入职摸鱼公司。",
            "self": "不能罚款自己。",
            "same_department": "不能罚款执法部门内部成员。",
            "target_limit": "该员工今日被罚款次数已达上限。",
        }
        if result.status in errors:
            return errors[result.status]
        if result.status == "not_authorized":
            return "只有风纪执法部门（部门津贴=风纪执法）的成员可以执行罚款。"
        if result.status == "cooldown":
            return f"罚款冷却中，请 {max(1, result.cooldown_remaining_seconds)} 秒后再试。"
        if result.status == "ambiguous_target":
            candidates = "\n".join(result.candidate_labels)
            return f"重名员工，请按工号罚款：\n{candidates}"
        reason_label = reason or "未填写理由"
        deduction_note = (
            "" if result.actual_amount == result.amount
            else f"（余额不足，实扣 {result.actual_amount}）"
        )
        allowance_note = (
            f"稽查人获得 {result.kickback} 摸鱼币津贴"
            f"（今日津贴 {result.allowance_total}/{result.allowance_cap}）"
        )
        return (
            f"【风纪罚款】{result.issuer_display_name}（{result.department_name}）对 "
            f"{result.target_display_name} 处以 {result.amount} 摸鱼币罚款"
            f"{deduction_note}，理由：{reason_label}\n"
            f"已成功扣款 {result.actual_amount} 摸鱼币，{allowance_note}。\n"
            f"{_FINE_FEEDBACK_HINT}"
        )

    def _my_discipline_fines(self, message, received_at):
        view = self._repository.my_discipline_fines(message.sender_platform_id)
        if view is None:
            return "请先用 /入职 名字 加入摸鱼公司。"
        lines = [
            f"【我的罚款记录】累计被罚 {view.total_count} 次 / "
            f"{view.total_amount} 摸鱼币（不含已撤销）"
        ]
        if not view.records:
            lines.append("暂无记录。")
        for index, record in enumerate(view.records, 1):
            revoked = "（已撤销）" if record.revoked_at is not None else ""
            reason = record.reason or "未填写理由"
            lines.append(
                f"{index}. {record.created_at:%m-%d %H:%M} 由 "
                f"{record.issuer_display_name} 罚 {record.amount} 币｜{reason}{revoked}"
            )
        return "\n".join(lines)

    def _my_allowances(self, platform_id: str, received_at) -> str:
        breakdown = self._repository.my_allowance_breakdown(
            platform_id, received_at
        )
        if breakdown is None:
            return "请先用 /入职 名字 加入摸鱼公司。"
        detail, total, cap = breakdown
        date_label = received_at.astimezone(_BEIJING).strftime("%m-%d")
        if not detail:
            return f"【我的津贴】{date_label}\n今日暂无津贴入账（0/{cap}）。"
        lines = [f"【我的津贴】{date_label}"]
        lines.extend(f"{label} +{amount}" for label, amount in detail)
        capped = "（已封顶）" if total >= cap else ""
        lines.append(f"今日合计：{total}/{cap}{capped}")
        return "\n".join(lines)

    def _estrus_chop(self, message, content, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中使用 /凿。"
        payload = content[len("/凿"):].strip()
        reference = message.reference
        times = 1
        if reference is not None and reference.sender_platform_id:
            # 引用形态：引用优先于名字参数；payload 为纯数字时表示连凿次数
            target_platform_id = reference.sender_platform_id
            target_name = None
            if payload.isdigit():
                times = int(payload)
                note = None
            else:
                note = payload or None
        else:
            parts = payload.split()
            if not parts:
                return (
                    "用法：引用对方消息发送 /凿 [附言] 或 /凿 [次数]，"
                    "或发送 /凿 名字 [附言] [次数]。"
                )
            if parts[-1].isdigit() and len(parts) >= 2:
                times = int(parts[-1])
                parts = parts[:-1]
            target_name = parts[0]
            if target_name.startswith("/"):
                return "那是指令，不是人名。"
            note = " ".join(parts[1:]).strip() or None
            target_platform_id = None
        if times < 1:
            times = 1
        elif times > 50:
            times = 50
        result = self._repository.execute_estrus_chop(
            message.sender_platform_id,
            target_platform_id=target_platform_id,
            target_name=target_name,
            note=note,
            times=times,
            now=received_at,
            group_chat_id=group_chat_id,
        )
        if result.status == "disabled":
            return "凿与发情值玩法未开启。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "missing_target":
            return (
                "用法：引用对方消息发送 /凿 [附言] 或 /凿 [次数]，"
                "或发送 /凿 名字 [附言] [次数]。"
            )
        if result.status == "target_not_found":
            return f"没找到员工「{target_name}」。"
        if result.status == "boss_not_found":
            return "胆子不小，连 TA 都敢凿？不过 TA 还没入职摸鱼公司。"
        if result.status == "group_target":
            return "你有几个牛子？还想凿这么多！"
        if result.status == "bot_target":
            return "机器人大工没法被凿——TA 只负责看戏，偶尔扣你工资。"
        if result.status == "target_not_joined":
            return "目标还未入职摸鱼公司。"
        if result.status == "self":
            return "不能凿自己。"
        if result.status == "ambiguous_target":
            candidates = "\n".join(result.candidate_labels)
            return f"重名员工，请按工号凿：\n{candidates}"
        if result.status == "cooldown":
            return f"凿冷却中，请 {max(1, result.cooldown_remaining_seconds)} 秒后再试。"
        if result.status == "combo_disabled":
            return (
                f"连续凿未开启，{result.chopper_name} 只能一下一下地凿"
                f"（后台可开启「允许连续凿」）。"
            )
        if result.status == "chopper_limit":
            return (
                f"你今天已经凿了 {result.today_chops_given} 次，"
                f"达到职级配额（{result.daily_chops_limit} 次），明天再来吧。"
            )
        if result.status == "target_limit":
            return (
                f"{result.target_name} 今天已经被凿了 {result.today_chops_received} 次，"
                f"达到每日上限（{result.daily_received_limit} 次），明天再来吧。"
            )
        if result.status == "refused":
            return (
                f"{result.target_name} 拒绝了 {result.chopper_name} 的凿，"
                f"并且给了 {result.chopper_name} 一杵子。"
            )
        action = (
            f"凿了 {result.times_executed} 次"
            if result.times_executed > 1
            else "凿了一下"
        )
        lines = [f"【凿】{result.chopper_name}{action}{result.target_name}"]
        if result.note:
            lines[0] += f"（{result.note}）"
        if result.g_spot_hits > 0:
            lines.append(f"🎯 凿中G点 {result.g_spot_hits} 次！")
        lines.append(
            f"{result.chopper_name} 共被扣除 {result.coins_deducted} 摸鱼币。"
        )
        if result.coins > 0:
            lines.append(
                f"{result.target_name} 发情值 +{result.heat_gain}"
                f"（当前 {result.heat_now}/{result.threshold}），"
                f"获得 {result.coins} 摸鱼币。"
            )
        else:
            lines.append(
                f"{result.target_name} 发情值 +{result.heat_gain}"
                f"（当前 {result.heat_now}/{result.threshold}），一无所获。"
            )
        if result.climax_triggered:
            lines.append(f"🔥 {result.target_name} 发情值爆表！")
            if result.climax_text:
                lines.append(result.climax_text)
            climax_note = (
                f"（连凿爆表 {result.climax_count} 次，"
                if result.times_executed > 1
                else "（"
            )
            lines.append(
                f"{climax_note}今日第 {result.today_climaxes} 次 / "
                f"总第 {result.total_climaxes} 次）"
            )
        if result.stopped_reason == "target_limit":
            lines.append(
                f"（连续凿提前停止：{result.target_name} 今日被凿次数已达上限）"
            )
        return "\n".join(lines)

    def _set_estrus_opt_out(self, message, received_at, group_chat_id, opted_out):
        if group_chat_id is None:
            return "请在已启用的群聊中设置。"
        display_name = self._repository.set_estrus_opt_out(
            message.sender_platform_id, group_chat_id, opted_out
        )
        if display_name is None:
            return "请先用 /入职 名字 加入摸鱼公司。"
        if opted_out:
            return f"{display_name} 已开启拒绝被凿：今后被 /凿 时对方会吃一杵子。"
        return f"{display_name} 已开启允许被凿：欢迎来凿。"

    def _my_estrus(self, message, received_at, group_chat_id):
        if group_chat_id is None:
            return "请在已启用的群聊中查询。"
        info = self._repository.get_my_estrus(
            message.sender_platform_id, group_chat_id, received_at
        )
        if info is None:
            return "请先用 /入职 名字 加入摸鱼公司。"
        return (
            "【我的凿】\n"
            f"名字：{info['display_name']}\n"
            f"发情值：{info['heat']}/{info['threshold']}\n"
            f"被凿：今日 {info['today_chopped']} 次 / 累计 {info['chopped_count']} 次 ｜ "
            f"高潮：今日 {info['today_climaxes']} 次 / 总 {info['total_climaxes']} 次\n"
            f"凿人：今日 {info['today_chops_given']} 次 / 累计 {info['total_chops_given']} 次\n"
            f"状态：{'拒绝被凿' if info['opted_out'] else '允许被凿'}"
        )

    def _estrus_popularity(self, message, received_at, group_chat_id):
        if group_chat_id is None:
            return "请在已启用的群聊中查询。"
        entries = self._repository.estrus_popularity_rankings(
            group_chat_id, received_at
        )
        if not entries:
            return "今天还没人被凿，快用 /凿 开张吧。"
        lines = ["【每日人气榜】"]
        lines.extend(
            f"{entry['display_name']}：今日被凿{entry['today_chopped']}次"
            f"（总计：{entry['total_chopped']}次）"
            for entry in entries
        )
        return "\n".join(lines)

    def _set_gender(self, message, content, received_at):
        tokens = content.strip().split()
        if len(tokens) < 2:
            return "用法：/设置性别 男 或 /设置性别 女。"
        raw = tokens[1]
        gender = {
            "男": "male", "男性": "male", "male": "male", "m": "male",
            "女": "female", "女性": "female", "female": "female", "f": "female",
        }.get(raw.strip().lower() if raw.isascii() else raw)
        if gender is None:
            return "性别只能填 男 或 女。"
        try:
            updated = self._repository.set_user_gender(
                message.sender_platform_id, gender
            )
        except ValueError as error:
            return str(error)
        if not updated:
            return "请先用 /入职 名字 加入摸鱼公司。"
        return f"已将你的性别设置为{'男' if gender == 'male' else '女'}。"

    def _truth_trade_leave(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /退出。"
        result = self._repository.leave_truth_trade(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "no_game":
            return "当前没有真心换真心对局。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "not_participant":
            return "你没有参与当前真心换真心局。"
        return result.public_message or "你已退出本局真心换真心。"

    def _truth_trade_end(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /结束游戏。"
        result = self._repository.end_truth_trade(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "no_game":
            return "当前没有可结束的真心换真心局。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "not_participant":
            return "只有本局参与者可以结束游戏。"
        return result.public_message or "【真心换真心】本局已结束。"

    def _truth_trade_continue(self, message, received_at, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /继续。"
        result = self._repository.continue_truth_trade(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "no_game":
            return "当前没有真心换真心对局。"
        if result.status == "not_joined":
            return "请先用 /入职 名字 加入摸鱼公司。"
        if result.status == "not_participant":
            return "只有当前玩家可以继续下一轮。"
        if result.status == "wrong_state":
            return "本轮还在进行中，等本轮结算后再 /继续。"
        if result.status == "not_enough_players":
            return f"活跃玩家不足 {result.min_players} 人，无法继续；可 /结束游戏 收尾。"
        return result.public_message or "当前不能继续真心换真心。"

    def _truth_trade_statistics(self, message, group_chat_id):
        if message.source_type != "group" or group_chat_id is None:
            return "请在已启用的群聊中发送 /真心换真心数据。"
        statistics = self._repository.truth_trade_statistics(group_chat_id)
        if statistics.games == 0:
            return "本群还没有真心换真心对局记录。"

        def line(label, leaders) -> str:
            if not leaders:
                return f"{label}：暂无"
            return f"{label}：" + "、".join(
                f"{name}（{count} 次）" for name, count in leaders
            )

        return "\n".join((
            "【真心换真心数据】",
            f"对局：{statistics.games} 局 · 提问：{statistics.questions} 个 · "
            f"回答：{statistics.answers} 条",
            line("提问最多", statistics.ask_leaders),
            line("回答最多", statistics.answer_leaders),
        ))

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

    def _check_in(self, platform_id: str, received_at, group_chat_id=None) -> str:
        profile = self._repository.get_user_profile(platform_id)
        if profile is None:
            return self._reply("/打卡", "not_joined", received_at)
        employee = profile.user
        reward = profile.rank.checkin_reward
        birthday = self._repository.birthday_settings_for(employee.id, received_at)
        if birthday is not None and birthday.checkin_multiplier > 1:
            reward = reward * birthday.checkin_multiplier
        if not self._repository.check_in(
            employee, received_at, reward, group_chat_id=group_chat_id
        ):
            return self._reply(
                "/打卡", "already_checked_in", received_at, {"{昵称}": employee.display_name}
            )
        weekly_reward = self._repository.weekly_attendance_reward_for_user(
            employee.id, received_at
        )
        current_employee = self._repository.find_user(platform_id)
        if current_employee is None:
            raise RuntimeError("employee disappeared")
        reply = self._reply(
            "/打卡",
            "checked_in",
            received_at,
            {
                "{昵称}": employee.display_name,
                "{余额}": current_employee.balance,
                "{打卡奖励}": reward,
            },
        )
        if weekly_reward is not None:
            reply += (
                f"\n已连续打卡 7 天，获得本周全勤奖，职位是{profile.rank.name}，"
                f"获得 {weekly_reward} {self._repository.get_game_settings().currency_name}。"
            )
        return reply

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

    def _grant_bonus(
        self, message: InboundMessage, content: str, received_at
    ) -> str:
        payload = content[len("/发奖金"):].strip()
        parts = payload.rsplit(maxsplit=1)
        if len(parts) == 1 and message.reference is not None:
            target_user = self._repository.find_user(
                message.reference.sender_platform_id
            )
            if target_user is None:
                return self._reply("/发奖金", "target_not_found", received_at)
            target = target_user.display_name
            amount_text = parts[0]
        elif len(parts) == 2:
            target, amount_text = parts
            target = target.strip()
        else:
            return self._reply("/发奖金", "usage", received_at)
        if not target:
            return self._reply("/发奖金", "usage", received_at)
        if not amount_text.isascii() or not amount_text.isdigit():
            return self._reply("/发奖金", "invalid_amount", received_at)

        result = self._repository.grant_board_bonus(
            message.sender_platform_id, target, int(amount_text), received_at
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
        title = self._repository.get_equipped_honor(platform_id, received_at)
        display_name = employee.display_name + (f"【荣誉称号：{title}】" if title else "")
        activity = self._repository.personal_activity(platform_id, received_at)
        if activity is None:
            raise RuntimeError("employee disappeared")
        currency = self._repository.get_game_settings().currency_name
        birthday_view = self._repository.get_employee_birthday(
            platform_id, received_at
        )
        if birthday_view is not None:
            days_left = (
                birthday_view.next_occurrence - received_at.date()
            ).days
            countdown = "就是今天！" if days_left == 0 else f"还有 {days_left} 天"
            birthday_line = (
                f"生日：{self._format_birthday(birthday_view)}（{countdown}）"
            )
        else:
            birthday_line = None
        if employee.gender == "male":
            gender_line = "性别：男"
        elif employee.gender == "female":
            gender_line = "性别：女"
        else:
            gender_line = None
        lines = [
            display_name,
            f"工号：{format_employee_number(employee.employee_number)}",
        ]
        if gender_line is not None:
            lines.append(gender_line)
        if birthday_line is not None:
            lines.append(birthday_line)
        lines.extend(
            [
                f"职位：{profile.rank.name}（{profile.rank.level_label}）",
                f"部门：{profile.department.name}",
                f"当前余额：{employee.balance} {currency}。",
                f"今日活跃度：LV{activity.level}。",
                f"今日收益：{self._repository.today_income(employee.id, received_at)} {currency}。",
            ]
        )
        allowance = self._repository.department_allowance_summary(
            platform_id, received_at
        )
        if allowance is not None:
            cap = self._repository.get_department_allowance_settings().daily_cap
            lines.append(f"今日部门津贴：{allowance}/{cap}")
        lines.append(
            f"连续打卡：{self._repository.consecutive_checkin_days(employee.id, received_at)} 天。"
        )
        return "\n".join(lines)

    def _honors(self, message, command, content, now):
        platform_id = message.sender_platform_id
        personal = self._repository.my_honors(platform_id, now)
        if personal is None:
            return "请先用 /入职 名字 加入摸鱼公司。"
        if command == "/佩戴称号":
            parts = content.split()
            if len(parts) != 2 or not re.fullmatch(r"[0-9]+", parts[1]) or len(parts[1]) > 3:
                return "用法：/佩戴称号 序号（/装备称号、/编辑称号 也可）；发送 /我的称号 查看，序号 0 取消佩戴。"
            try:
                name = self._repository.wear_honor(platform_id, int(parts[1]), now)
            except (LookupError, ValueError) as error:
                return str(error)
            return f"已佩戴荣誉称号：{name}。" if name else "已取消佩戴荣誉称号。"
        if command == "/荣誉榜":
            board = self._repository.honor_board(now)
            lines = ["【荣誉榜】"]
            lines.extend(honor_award_lines(board["items"], public_scores=True, include_empty=True))
            return "\n".join(lines) if board["items"] else "本期荣誉尚未结算，暂无获奖名单。"
        if command == "/荣誉历史":
            user = self._repository.get_user_profile(platform_id).user
            history = self._repository.honor_history(now, user_id=user.id)
            lines = ["【荣誉历史】（最近 20 项）"]
            lines.extend(f"{item['week_start']}｜{item['name']}" for item in history["items"])
            return "\n".join(lines) if history["items"] else "你还没有获得过荣誉称号。"
        lines = ["【我的称号】", f"当前佩戴：{personal['equipped'] or '未佩戴'}"]
        for item in personal["items"]:
            lines.append(f"{item['number']}. {item['name']}｜历史获得 {item['total_wins']} 次｜有效至 {item['expires_at'][:10]} 00:00")
        if not personal["items"]:
            lines.append("当前没有可佩戴称号。")
        if personal["history_counts"]:
            lines.append(f"历史累计获得荣誉 {sum(personal['history_counts'].values())} 次。")
        lines.append("发送 /佩戴称号 序号 切换（/装备称号、/编辑称号 也可），序号 0 取消佩戴。")
        return "\n".join(lines)

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


    def _set_birthday(self, platform_id: str, content: str, received_at) -> str:
        text = content[len("/设置生日") :].strip()
        result = self._repository.set_employee_birthday(
            platform_id,
            text,
            received_at,
            visibility=parse_visibility(text),
        )
        if result.status != "saved":
            values = {}
            if result.view is not None:
                values["{生日}"] = self._format_birthday(result.view)
            return self._reply("/设置生日", result.status, received_at, values)
        view = result.view
        assert view is not None
        return self._reply(
            "/设置生日",
            "saved",
            received_at,
            {
                "{生日}": self._format_birthday(view),
                "{可见性}": "公开" if view.visibility == "public" else "不公开",
                "{下次}": view.next_occurrence.isoformat(),
                "{工龄}": view.tenure,
            },
        )


    def _birthday_tip(self, message, content: str, received_at) -> str:
        parts = content.split()
        recipient_name: str | None = None
        if len(parts) == 2:
            amount_text = parts[1]
            # 回复寿星的消息就等于点名（同 /发奖金 的写法），一天多人过生日时最省事
            if message.reference is not None:
                replied = self._repository.find_user(
                    message.reference.sender_platform_id
                )
                if replied is not None:
                    recipient_name = replied.display_name
        elif len(parts) == 3:
            recipient_name, amount_text = parts[1], parts[2]
        else:
            return self._reply("/随礼", "usage", received_at)
        if not amount_text.isascii() or not amount_text.isdigit():
            return self._reply("/随礼", "invalid_amount", received_at, {"{上限}": "—"})
        result = self._repository.tip_birthday(
            message.sender_platform_id,
            int(amount_text),
            received_at,
            platform_message_id=message.platform_message_id,
            recipient_name=recipient_name,
        )
        values = {
            "{寿星}": result.recipient_name or "",
            "{金额}": str(result.amount),
            "{上限}": str(result.maximum) if result.maximum else "—",
        }
        return self._reply("/随礼", result.status, received_at, values)


    def _my_birthday(self, platform_id: str, received_at) -> str:
        view = self._repository.get_employee_birthday(platform_id, received_at)
        if view is None:
            return self._reply("/我的生日", "missing", received_at)
        return self._reply(
            "/我的生日",
            "shown",
            received_at,
            {
                "{生日}": self._format_birthday(view),
                "{可见性}": "公开" if view.visibility == "public" else "不公开",
                "{下次}": view.next_occurrence.isoformat(),
                "{工龄}": view.tenure,
            },
        )

    def _month_birthdays(self, received_at) -> str:
        listing = self._repository.list_month_birthdays(received_at)
        if not listing.entries:
            return self._reply(
                "/本月生日", "empty", received_at, {"{月份}": str(listing.month)}
            )
        names = "、".join(
            f"{entry.display_name}（{entry.month}-{entry.day}"
            + ("，就是今天" if entry.is_today else "")
            + "）"
            for entry in listing.entries
        )
        return self._reply(
            "/本月生日",
            "shown",
            received_at,
            {
                "{月份}": str(listing.month),
                "{名单}": names,
                "{人数}": str(len(listing.entries)),
            },
        )

    @staticmethod
    def _format_birthday(view) -> str:
        return f"{view.month} 月 {view.day} 日"


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
        title = self._repository.get_equipped_honor(platform_id, received_at)
        if title:
            employee = self._repository.find_user(platform_id)
            text = f"{employee.display_name}【荣誉称号：{title}】\n{text}"
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
        if result.status == "cooldown":
            hours = max(1, result.cooldown_remaining_seconds // 3600)
            return f"刚变更过部门，需 24 小时后才能再次更换（还剩约 {hours} 小时）。"
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
        if result.status == "cooldown":
            hours = max(1, result.cooldown_remaining_seconds // 3600)
            return f"刚变更过部门，需 24 小时后才能再次更换（还剩约 {hours} 小时）。"
        return self._reply("/切换部门", "unknown_department", received_at)

    def _department_allowance_hints(self) -> dict[str, str]:
        """/部门 增益提示：文案随后台津贴设置动态生成。"""
        settings = self._repository.get_department_allowance_settings()
        return {
            "checkin": f"每日打卡额外 +{settings.checkin_amount} 摸鱼币",
            "event": f"参与随机事件/公演并正常完成额外 +{settings.event_amount} 摸鱼币",
            "game": (
                f"开局小游戏 +{settings.game_host_amount}；"
                f"每天参与满 {settings.game_play_step} 局 +{settings.game_play_amount}"
            ),
            "submission": f"随机事件投稿过审额外 +{settings.submission_amount} 摸鱼币",
            "chat": (
                f"水群有 {settings.chat_drop_percent}% 概率掉落 "
                f"{settings.chat_drop_amount} 摸鱼币"
                + (
                    f"（同人冷却 {settings.chat_drop_cooldown_seconds} 秒）"
                    if settings.chat_drop_cooldown_seconds > 0
                    else ""
                )
            ),
            "referral": f"每邀请新人通过链接进群 +{settings.referral_amount} 摸鱼币",
            "discipline": "可执行风纪罚款操作，获得罚款20%的奖励",
        }

    def _departments(self, received_at) -> str:
        hints = self._department_allowance_hints()
        lines = []
        for department in self._repository.list_departments():
            if not department.enabled or department.is_default:
                continue
            hint = hints.get(department.allowance_kind)
            lines.append(
                f"{department.name}：{department.description or '暂无说明'}"
                + (f"（部门增益：{hint}）" if hint else "")
            )
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
            top_ranks = [
                rank for rank in reversed(item.ranks) if rank.members
            ][:3]
            if top_ranks:
                lines.append("职位人员：")
                for index, rank in enumerate(top_ranks, 1):
                    name_counts = Counter(
                        member.display_name for member in rank.members
                    )
                    member_labels = [
                        (
                            f"{member.display_name} "
                            f"{format_employee_number(member.employee_number)}"
                            if name_counts[member.display_name] > 1
                            else member.display_name
                        )
                        for member in rank.members
                    ]
                    lines.append(
                        f"{index}. {rank.rank_name}：{'、'.join(member_labels)}"
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

    def _inventory(self, message: InboundMessage, received_at) -> str:
        if message.source_type != "group":
            return self._reply("/我的物品", "group_only", received_at)
        employee = self._repository.find_user(message.sender_platform_id)
        if employee is None:
            return self._reply("/我的物品", "not_joined", received_at)
        items = self._repository.list_user_shop_items(employee.id)
        return self._reply(
            "/我的物品",
            "shown",
            received_at,
            {
                "{昵称}": employee.display_name,
                "{物品列表}": "暂时空空如也。"
                if not items
                else "\n".join(
                    f"#{item.public_number} {item.name} × {item.quantity}"
                    for item in items
                ),
            },
        )

    def _shop(self, message: InboundMessage, received_at, group_chat_id) -> str:
        if message.source_type != "group":
            return self._reply("/商店", "group_only", received_at)
        items = self._repository.list_shop_items(group_chat_id or PRIMARY_GROUP_CHAT_ID)
        if not items:
            return self._reply("/商店", "empty", received_at)
        currency_name = self._repository.get_game_settings().currency_name
        grouped: dict[str, list] = {}
        for item in items:
            grouped.setdefault(item.category or CATEGORY_OTHER, []).append(item)
        ordered = [category for category in CATEGORY_DISPLAY_ORDER if category in grouped]
        ordered += [
            category
            for category in grouped
            if category not in CATEGORY_DISPLAY_ORDER and category != CATEGORY_OTHER
        ]
        if CATEGORY_OTHER in grouped:
            ordered.append(CATEGORY_OTHER)
        sections = []
        for category in ordered:
            lines = [f"◆ {category}"]
            for item in grouped[category]:
                lines.append(
                    f"#{item.public_number} {item.name}（{item.price} {currency_name}，库存 "
                    f"{'不限' if item.unlimited_stock else item.stock}"
                    f"{'，需 LV' + str(item.minimum_rank_order) if item.minimum_rank_order else ''}）"
                    f"\n说明：{item.description}"
                )
            sections.append("\n".join(lines))
        return self._reply(
            "/商店",
            "items_available",
            received_at,
            {"{商店列表}": "\n\n".join(sections)},
        )

    def _purchase(
        self, message: InboundMessage, content: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group":
            return self._reply("/购买", "group_only", received_at)
        group_chat_id = group_chat_id or PRIMARY_GROUP_CHAT_ID
        parts = content.split()
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
            return self._reply("/购买", "usage", received_at)
        result = self._repository.purchase_shop_item(
            message.platform_message_id,
            message.sender_platform_id,
            int(parts[1]),
            group_chat_id,
            received_at,
        )
        values = {}
        if result.item is not None:
            values.update(
                {
                    "{商品编号}": result.item.public_number,
                    "{商品名称}": result.item.name,
                    "{最低职位}": result.item.minimum_rank_order or 0,
                }
            )
        if result.balance is not None:
            values["{余额}"] = result.balance
        if result.quantity is not None:
            values["{数量}"] = result.quantity
        return self._reply("/购买", result.status, received_at, values)

    def _use_item(
        self, message: InboundMessage, content: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group":
            return self._reply("/使用", "group_only", received_at)
        group_chat_id = group_chat_id or PRIMARY_GROUP_CHAT_ID
        parts = content.split()
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
            return self._reply("/使用", "usage", received_at)
        result = self._repository.use_ordinary_shop_item(
            message.platform_message_id,
            message.sender_platform_id,
            int(parts[1]),
            group_chat_id,
            received_at,
            target_platform_id=(
                None
                if message.reference is None
                else message.reference.sender_platform_id
            ),
        )
        if result.status == "event_ad_slot_required":
            draft = self._repository.start_random_event_ad_slot(
                message.sender_platform_id,
                int(parts[1]),
                group_chat_id,
                received_at,
            )
            if draft.status != "started":
                return self._reply("/使用", f"ad_slot_{draft.status}", received_at)
            return (
                "请选择要锁定优选投稿位的场次：\n"
                + "\n".join(
                    f"{slot.position}. {slot.group_name}｜"
                    f"{slot.scheduled_at.strftime('%H:%M')}"
                    f"｜优选投稿位 {slot.taken}/{slot.limit}"
                    for slot in draft.schedules
                )
                + "\n回复 /选择 场次序号。"
            )
        if result.status == "adult_required":
            result = self._repository.start_adult_shop_item(
                message.platform_message_id,
                message.sender_platform_id,
                int(parts[1]),
                group_chat_id,
                received_at,
                target_platform_id=(
                    None
                    if message.reference is None
                    else message.reference.sender_platform_id
                ),
            )
        values = {}
        if result.item is not None:
            values.update(
                {
                    "{商品编号}": result.item.public_number,
                    "{商品名称}": result.item.name,
                }
            )
        if result.reward is not None:
            values["{奖励}"] = result.reward
        if result.target_display_name is not None:
            values["{目标员工}"] = result.target_display_name
        if result.session_number is not None:
            values["{卡片局编号}"] = result.session_number
        scenario = result.status
        if result.status == "completed" and result.item is not None:
            if result.item.effect_type == "gift":
                scenario = "gift_completed"
            elif result.item.effect_type == "scratch":
                scenario = "scratch_completed"
            else:
                scenario = "quota_completed"
        if result.status == "scene_required":
            return [
                self._reply("/使用", "scene_required", received_at, values),
                CommandReply(
                    f"卡片局 #{result.session_number}：请发送 1–200 字的具体场景要求。",
                    destination_chatroom_id=result.direct_chatroom_id,
                    delivery_kind="direct",
                ),
            ]
        return self._reply("/使用", scenario, received_at, values)

    def _invite_adult_participant(
        self, message: InboundMessage, content: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group":
            return self._reply("/邀请参与", "group_only", received_at)
        parts = content.split()
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
            return self._reply("/邀请参与", "usage", received_at)
        result = self._repository.invite_adult_card_participant(
            message.sender_platform_id,
            None if message.reference is None else message.reference.sender_platform_id,
            int(parts[1]),
            received_at,
            group_chat_id=group_chat_id or PRIMARY_GROUP_CHAT_ID,
        )
        return self._reply(
            "/邀请参与",
            result.status,
            received_at,
            {"{卡片局编号}": result.session_number or int(parts[1])},
        )

    def _cancel_adult_use(
        self, message: InboundMessage, content: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group":
            return self._reply("/取消使用", "group_only", received_at)
        parts = content.split()
        if len(parts) != 2 or not parts[1].isascii() or not parts[1].isdigit():
            return self._reply("/取消使用", "usage", received_at)
        result = self._repository.cancel_adult_card_session(
            message.sender_platform_id,
            int(parts[1]),
            received_at,
            group_chat_id=group_chat_id or PRIMARY_GROUP_CHAT_ID,
        )
        return self._reply(
            "/取消使用",
            result.status,
            received_at,
            {"{卡片局编号}": result.session_number or int(parts[1])},
        )

    def _decide_adult_use(
        self, message: InboundMessage, command: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group":
            return self._reply(command, "group_only", received_at)
        result = self._repository.decide_adult_card_consent(
            message.sender_platform_id,
            None if message.reference is None else message.reference.message_id,
            command == "/同意使用",
            received_at,
            group_chat_id=group_chat_id or PRIMARY_GROUP_CHAT_ID,
        )
        return self._reply(
            command,
            result.status,
            received_at,
            {"{卡片局编号}": result.session_number or ""},
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
            "daily_limit": "daily_limit",
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
            "not_joined", "direct_chat_required", "disabled", "daily_limit",
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
        scenario = {
            "signup_left": "texas_signup_left",
            "acted": "texas_folded",
            "settled": "texas_folded",
        }.get(result.status, "texas_cannot_leave")
        acknowledgement = self._reply("/退出", scenario, received_at)
        if result.public_message:
            return acknowledgement + "\n\n" + result.public_message
        return acknowledgement

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
            if result.public_message:
                return acknowledgement + "\n\n" + result.public_message
            return acknowledgement
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
        if status == "announcement_pending":
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

    def _random_event_vote(
        self, message: InboundMessage, command: str, content: str, received_at
    ) -> str:
        """`/事件投票 序号` 与 `/事件投票情况`：全公司对下一场演什么表决。"""
        if message.source_type != "group":
            return self._reply(command, "group_only", received_at)
        if command == "/事件投票情况":
            view = self._repository.random_event_poll_view(
                message.sender_platform_id
            )
            if view is None or view.status != "open":
                return self._reply("/事件投票情况", "none", received_at)
            return self._reply(
                "/事件投票情况",
                "shown",
                received_at,
                {"{票型}": self._random_event_vote_tally(view)},
            )
        parts = content.split(maxsplit=1)
        if len(parts) != 2 or not parts[1].strip().isdigit():
            return self._reply("/事件投票", "usage", received_at)
        position = int(parts[1].strip())
        result = self._repository.cast_random_event_vote(
            message.sender_platform_id, position, received_at
        )
        if result.status in {
            "no_poll",
            "closed",
            "no_candidate",
            "vacant",
            "not_joined",
            "already_voted",
        }:
            return self._reply(
                "/事件投票", result.status, received_at, {"{序号}": position}
            )
        view = result.view
        candidate = (
            None
            if view is None
            else next(
                (item for item in view.candidates if item.position == position), None
            )
        )
        return self._reply(
            "/事件投票",
            "changed" if result.status == "changed" else "recorded",
            received_at,
            {
                "{序号}": position,
                "{事件}": (
                    "未命名"
                    if candidate is None or not candidate.scene_name
                    else candidate.scene_name
                ),
                "{票数}": 0 if candidate is None else candidate.votes,
            },
        )

    def _random_event_time_table(self, group_chat_id, received_at) -> str:
        schedules = self._repository.list_today_random_event_schedules(received_at)
        if not schedules:
            return "今天没有随机事件场次。"
        groups = {
            group.id: group.name
            for group in self._repository.list_group_chats(include_deleted=True)
        }
        available = {
            slot.schedule_id: slot
            for slot in self._repository.random_event_ad_slot_schedules(
                None, received_at
            )
        }
        status_labels = {
            "pending": "待开始",
            "signup": "报名中",
            "in_progress": "进行中",
            "tipping": "打赏中",
            "ended": "已结束",
            "dissolved": "已解散",
            "skipped": "已跳过",
        }
        return "【随机事件时间表】\n" + "\n".join(
            f"{schedule.scheduled_at.strftime('%H:%M')}｜"
            f"{groups.get(schedule.group_chat_id, '未知群聊')}｜"
            f"{status_labels.get(schedule.status, schedule.status)}"
            + (
                f"｜优选投稿位 {available[schedule.id].taken}/"
                f"{available[schedule.id].limit}"
                if schedule.id in available
                else ""
            )
            for schedule in schedules
        )

    def _random_event_vote_tally(self, view) -> str:
        lines = [
            f"【事件投票】{view.scheduled_at.strftime('%H:%M')} 那场，"
            f"{view.closes_at.strftime('%H:%M')} 截止，已投 {view.total_votes} 票"
        ]
        for candidate in view.candidates:
            if candidate.vacant:
                lines.append(f"{candidate.position}. ✨ 优选投稿位待定")
            else:
                lines.append(
                    f"{candidate.position}. 《{candidate.scene_name}》 "
                    f"by {_short_author_name(candidate.author_name)} "
                    f"{candidate.votes} 票"
                )
        if view.my_position is not None:
            lines.append(f"你投的是 {view.my_position} 号")
        else:
            lines.append("你还没投票，回复 /事件投票 序号")
        return "\n".join(lines)

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

    def _performance_tip(
        self,
        message: InboundMessage,
        content: str,
        received_at,
        group_chat_id,
    ) -> str:
        payload = content[len("/打赏") :].strip()
        recipient_name = None
        reference_message_id = None
        if message.reference is not None:
            if not payload.isascii() or not payload.isdigit() or int(payload) <= 0:
                return "回复参演人员本场消息后，请发送 /打赏 金额。"
            amount = int(payload)
            reference_message_id = message.reference.message_id
        else:
            parts = payload.rsplit(maxsplit=1)
            if (
                len(parts) != 2
                or not parts[0].strip()
                or not parts[1].isascii()
                or not parts[1].isdigit()
                or int(parts[1]) <= 0
            ):
                return "请发送 /打赏 参演人员名称 金额，或回复参演人员本场消息发送 /打赏 金额。"
            recipient_name = parts[0].strip()
            amount = int(parts[1])
        result = self._repository.tip_performance(
            message.sender_platform_id,
            recipient_name,
            amount,
            message.platform_message_id,
            received_at,
            group_chat_id,
            reference_message_id,
        )
        currency = self._repository.get_game_settings().currency_name
        if result.status in {"sent", "duplicate"}:
            return (
                f"{result.sender_display_name} 已打赏 {result.recipient_display_name} "
                f"{result.amount} {currency}。"
            )
        if result.status == "insufficient_balance":
            return f"余额不足，当前仅有 {result.sender_balance or 0} {currency}。"
        return {
            "not_joined": "请先用 /入职 名称 加入摸鱼公司。",
            "not_tipping": "当前不在公演打赏阶段。",
            "expired": "公演打赏时间已结束。",
            "invalid_amount": "打赏金额必须是正整数。",
            "recipient_not_found": "没有找到该参演人员。",
            "recipient_not_participant": "只能打赏本场参演人员。",
            "invalid_reference": "引用消息不是本场参演人员的演出内容。",
            "self_tip": "不能给自己打赏。",
        }.get(result.status, "打赏失败，请稍后重试。")

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
        if content.startswith("/记忆考核 公会赛"):
            if group_chat_id is None:
                return "请在已启用的群聊中发送 /记忆考核 公会赛 场数。"
            planned_series_count = parse_guild_match_start(content)
            if planned_series_count is None:
                return "格式：/记忆考核 公会赛 场数（1–20）。"
            result = self._repository.start_memory_guild_match(
                platform_id,
                planned_series_count,
                received_at,
                group_chat_id,
            )
            if result.public_message is not None:
                return result.public_message
            return {
                "not_joined": "请先用 /入职 名称 加入摸鱼公司。",
                "disabled": "本群未开启记忆考核玩法。",
                "already_active": "本群已有一场记忆考核公会赛。",
                "multiplayer_active": "当前已有多人玩法进行中，暂不能发起公会赛。",
            }.get(result.status, "公会赛创建失败，请稍后重试。")
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
                "daily_limit": "duel_daily_limit",
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
            "multiplayer_active": "single_multiplayer_active",
            "random_event_active": "random_event_active",
        }
        return self._reply("/记忆考核", scenarios[result.status], received_at)

    def _memory_guild_team_config(
        self, message: InboundMessage, content: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group" or group_chat_id is None:
            return "请在公会赛所在群配置队伍。"
        parsed = parse_team_command(content)
        if parsed is None:
            return "格式：/队伍1 队名，或 /队伍1人员 玩家A，玩家B。"
        slot, field, value = parsed
        if field == "name":
            result = self._repository.set_memory_guild_team_name(
                message.sender_platform_id,
                slot,
                value,
                received_at,
                group_chat_id,
            )
        else:
            try:
                names = split_roster_names(value)
            except ValueError as error:
                return str(error)
            result = self._repository.set_memory_guild_roster(
                message.sender_platform_id,
                slot,
                names,
                received_at,
                group_chat_id,
            )
        if result.status in {"team_updated", "roster_updated"}:
            team = result.team1 if slot == 1 else result.team2
            if field == "name":
                return f"✅ 队伍{slot}名称已设为：{team.name}。"
            return (
                f"✅ 队伍{slot}人员已更新："
                + "、".join(member.display_name for member in team.members)
                + "。"
            )
        return {
            "no_match": "当前没有记忆考核公会赛。",
            "host_only": "只有本场主持人可以配置队伍。",
            "configuration_locked": "首场已进入选人，队伍配置已经锁定。",
            "duplicate_team_name": "两个队伍不能使用相同名称。",
            "unknown_member": "队伍人员中存在未入职或名称不正确的员工。",
            "host_cannot_play": "主持人不能加入参赛队伍。",
            "member_in_other_team": "同一名员工不能同时加入两个队伍。",
            "invalid_team": "队伍名称应为 1–64 个字符。",
            "invalid_roster": "队伍人员不能为空或重复。",
        }.get(result.status, "队伍配置失败，请稍后重试。")

    def _memory_guild_series_config(
        self, message: InboundMessage, content: str, received_at, group_chat_id
    ) -> str:
        if message.source_type != "group" or group_chat_id is None:
            return "请在公会赛所在群配置场次。"
        parsed = parse_series_command(content)
        if parsed is None:
            return "格式：/第1场 4/7；胜场必须严格过半。"
        sequence, win_target, maximum_decisive_rounds = parsed
        result = self._repository.create_memory_guild_series(
            message.sender_platform_id,
            sequence,
            win_target,
            maximum_decisive_rounds,
            received_at,
            group_chat_id,
        )
        if result.status == "series_created":
            label = "加时赛" if sequence > result.planned_series_count else "正式场"
            return (
                f"⚔️ 第{sequence}场（{label}）已创建："
                f"{maximum_decisive_rounds}局{win_target}胜。\n"
                "请两队成员分别私聊发送 /上场 玩家名称。"
            )
        return {
            "no_match": "当前没有记忆考核公会赛。",
            "host_only": "只有本场主持人可以配置场次。",
            "invalid_series": "场次赛制无效，胜场必须严格过半。",
            "invalid_sequence": "场次编号必须紧接上一场。",
            "previous_series_active": "上一场尚未结束，不能配置新场次。",
            "insufficient_roster": "两队名称必须完整，且每队人数不得少于预设场数。",
            "tiebreaker_not_needed": "当前大比分无需加时赛。",
        }.get(result.status, "场次配置失败，请稍后重试。")

    def _memory_guild_lineup(
        self, message: InboundMessage, content: str, received_at
    ) -> str | list[CommandReply]:
        if message.source_type != "direct":
            return "请私聊总监事发送 /上场 玩家名称。"
        candidates = self._repository.memory_guild_lineup_candidates(
            message.sender_platform_id
        )
        candidate_lines = "\n".join(
            f"{candidate.index}. {candidate.group_name}" for candidate in candidates
        )
        if not candidates:
            return "你当前没有等待选择选手的公会赛。"
        if len(candidates) > 1:
            parts = content.split(maxsplit=2)
            if len(parts) != 3 or not parts[1].isdigit():
                return (
                    "你在多个群有待选阵容，请发送 /上场 群序号 玩家名称：\n"
                    + candidate_lines
                )
            selected = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate.index == int(parts[1])
                ),
                None,
            )
            if selected is None:
                return "群序号无效，请重新发送：\n" + candidate_lines
            selected_name = parts[2].strip()
        else:
            parts = content.split(maxsplit=1)
            if len(parts) != 2 or not parts[1].strip():
                return "格式：/上场 玩家名称。"
            selected = candidates[0]
            selected_name = parts[1].strip()
        result = self._repository.select_memory_guild_player(
            message.sender_platform_id,
            selected_name,
            received_at,
            selected.group_chat_id,
        )
        if result.status == "lineup_recorded":
            return f"✅ 已锁定本队上场选手：{selected_name}。等待另一队选择。"
        if result.status == "series_ready" and result.public_message is not None:
            return [
                CommandReply(
                    f"✅ 已锁定本队上场选手：{selected_name}。双方阵容已公开。",
                    destination_chatroom_id=message.chatroom_id,
                    delivery_kind="direct",
                ),
                CommandReply(
                    result.public_message,
                    destination_chatroom_id=self._repository.group_chat_destination(
                        selected.group_chat_id
                    ),
                    delivery_kind="group",
                    group_chat_id=selected.group_chat_id,
                ),
            ]
        return {
            "lineup_locked": "本队本场上场选手已经锁定，不能更换。",
            "invalid_player": "只能选择本队名单中的员工。",
            "player_already_used": "该员工已在普通场次出场，不能重复上场。",
            "not_team_member": "只有参赛队伍成员可以为本队选人。",
            "wrong_state": "当前不在选择上场选手阶段。",
            "no_match": "当前没有等待选择选手的公会赛。",
        }.get(result.status, "选择上场选手失败，请稍后重试。")

    def _memory_guild_start_round(
        self, message: InboundMessage, received_at, group_chat_id
    ) -> str | CommandReply:
        if message.source_type != "group" or group_chat_id is None:
            return "请在公会赛所在群发送 /开始对战。"
        result = self._repository.start_memory_guild_round(
            message.sender_platform_id, received_at, group_chat_id
        )
        if result.status == "round_started":
            return CommandReply(
                result.public_message or "",
                recall_after_seconds=result.display_seconds,
                memory_guild_round_id=result.round_id,
            )
        return {
            "no_match": "当前没有记忆考核公会赛。",
            "host_only": "只有本场主持人可以开始对战。",
            "round_not_ready": "当前尚未完成双方选人，或上一小局仍未结束。",
        }.get(result.status, "暂时不能开始新题。")

    def _memory_guild_answer(
        self,
        message: InboundMessage,
        answer: str,
        received_at,
        group_chat_id,
    ) -> str | None:
        result = self._repository.answer_memory_guild_round(
            message.sender_platform_id,
            message.platform_message_id,
            answer,
            received_at,
            group_chat_id,
        )
        if result.public_message is not None:
            return result.public_message
        return {
            "incorrect": "❌ 答案不正确，可继续发送 /答案 内容。",
            "not_current_player": "只有本小局公开的两位选手可以作答。",
            "round_closed": None,
            "duplicate_answer": None,
            "no_match": None,
        }.get(result.status)

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
        if result.status == "timed_out":
            return self._reply("/记忆考核", "timed_out", received_at)
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
        if result.status == "auto_cashed_out":
            return self._reply(
                "/继续",
                "auto_cashed_out",
                received_at,
                {
                    "{昵称}": result.display_name,
                    "{奖励}": result.reward,
                    "{余额}": result.balance,
                    "{超时秒数}": result.display_seconds,
                },
            )
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
            "公演预约": "公演",
            "演出": "公演",
        }.get(topic, topic)

        guides = {
            "基础": (
                "【基础与资产】",
                (
                    ("/入职", "/入职 名字：登记成为员工"),
                    ("/打卡", "/打卡：按当前职位领取每日奖励"),
                    ("/余额", "/余额：查看当前余额"),
                    ("/修改名称", "/修改名称 新名称：修改自己的员工名称"),
                    ("/编辑档案", "/编辑档案 档案内容：更新个人档案"),
                    ("/编辑档案形象", "/编辑档案形象（回复一张图片）：更新档案形象"),
                    ("/我的档案", "/我的档案：查看自己的个人档案"),
                    ("/发奖金", "回复目标发送 /发奖金 金额；也支持 /发奖金 员工名 金额、/发奖金 全部 金额：仅核心董事会发放"),
                    ("/发红包", "/发红包 人数 总金额：发出随机运气红包"),
                    ("/抢红包", "/抢红包：领取当前红包"),
                    ("/我", "/我：查看个人资料、收益与活跃度"),
                    ("/我的称号", "/我的称号：查看本周可佩戴称号、有效期与累计获得次数"),
                    ("/佩戴称号", "/佩戴称号 序号：佩戴一个称号；/装备称号、/编辑称号 等效，序号 0 取消佩戴"),
                    ("/荣誉榜", "/荣誉榜：查看本周荣誉称号获得者"),
                    ("/荣誉历史", "/荣誉历史：查看自己的历史获奖记录"),
                    ("/我的津贴", "/我的津贴：查看今日各项部门津贴明细与合计"),
                    ("/我的物品", "/我的物品：查看持有物品"),
                    ("/商店", "/商店：查看可购买物品"),
                ),
            ),
            "商店": (
                "【商店与卡片】",
                (
                    ("/商店", "/商店：查看本群可购买商品、稳定编号、价格、职位和库存"),
                    ("/购买", "/购买 商品编号：购买一件商品并扣除摸鱼币"),
                    ("/我的物品", "/我的物品：按商品编号查看自己的库存"),
                    ("/使用", "/使用 商品编号：使用刮刮卡或次数卡；回复员工消息使用赠送卡或成人卡"),
                    ("/邀请参与", "/邀请参与 卡片局编号：回复其他员工，为多人成人卡补充参与者"),
                    ("/取消使用", "/取消使用 卡片局编号：场景或选人阶段取消并退回预留卡片"),
                    ("/同意使用", "回复卡片授权通知发送 /同意使用：确认成年并同意该次具体场景"),
                    ("/拒绝使用", "回复卡片授权通知发送 /拒绝使用：整局作废，发起人获商品价格 50% 补偿"),
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
                    ("/随机事件时间表", "/随机事件时间表：查看全公司今天全部场次与状态"),
                    ("/使用", "/使用 优选投稿卡编号：在群内选择场次和已审核投稿，确认后锁定优选投稿位"),
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
                    ("/记忆考核", "/记忆考核 公会赛 场数：由主持人创建双队公会赛"),
                    ("/队伍1", "/队伍1 队名；/队伍2 队名：设置两队名称"),
                    ("/队伍1人员", "/队伍1人员 玩家A，玩家B；队伍2同理"),
                    ("/公会赛场次", "/第1场 4/7：设置本场七局四胜"),
                    ("/上场", "队员私聊 /上场 玩家名称：首个有效选择锁定"),
                    ("/开始对战", "/开始对战：主持人开始当前小局并展示5级题目"),
                    ("/加入", "/加入：加入等待中的对战"),
                    ("/答案", "/答案 内容：提交记忆答案"),
                    ("/继续", "/继续：单人挑战进入下一等级"),
                    ("/收手", "/收手：结算当前单人挑战奖励"),
                    ("/退出", "/退出：立即退出当前记忆考核对战"),
                    ("/结束游戏", "/结束游戏：公会赛仅主持人可结束，董事会可强制结束"),
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
            "我有你没有": (
                "【我有你没有】",
                (
                    ("/我有你没有", "/我有你没有：创建报名局"),
                    ("/加入", "/加入：加入报名；至少 3 人后由发起者发送 /开始"),
                    ("/开始", "/开始：仅发起者开始本局"),
                    ("/发言", "轮到自己时 /发言 内容：说出一项自己有、别人可能没有的经历"),
                    ("/扣", "其余存活玩家 /扣：没有该经历，扣一颗心"),
                    ("/不扣", "其余存活玩家 /不扣：自己也有该经历，保留心数"),
                    ("/退出", "/退出：退出当前对局"),
                    ("/结束游戏", "/结束游戏：仅发起者可结束本局"),
                ),
            ),
            "国王游戏": (
                "【国王游戏】",
                (
                    ("/国王游戏", "/国王游戏：创建报名局"),
                    ("/加入", "/加入：报名；开局后加入者在下一轮生效"),
                    ("/开始", "/开始：至少 3 人后由发起者抽取本轮国王"),
                    ("/公开", "/公开 编号 [编号...]：仅本轮国王公开指定编号"),
                    ("/继续", "/继续：任一参与者进入下一轮"),
                    ("/国王游戏数据", "/国王游戏数据：查看当前局国王、受罚和回旋镖实时统计"),
                    ("/结束游戏", "/结束游戏：任一参与者结束本局并公布统计"),
                ),
            ),
            "大话骰子": (
                "【大话骰子】",
                (
                    ("/大话骰子", "/大话骰子：创建报名局（每人 5 骰 + 每轮随机万能点）"),
                    ("/加入", "/加入：报名；对局中途加入者在下一轮生效"),
                    ("/开始", "/开始：发起者摇骰开局，骰子私聊发放"),
                    ("N个X", "直接发送如“3个5”：当前行动者叫数或加码"),
                    ("/开骰", "/开骰：当前行动者质疑上一手叫数，全场明牌定胜负"),
                    ("/牌局", "/牌局：查看座位、当前叫数与万能点状态"),
                    ("/看骰", "私聊 /看骰：查看自己当前骰子"),
                    ("/继续", "/继续：开牌后任一参与者开启下一轮"),
                    ("/大话骰子数据", "/大话骰子数据：查看开牌、败露、拆穿与受罚统计"),
                    ("/结束游戏", "/结束游戏：任一参与者结束本局并公布统计"),
                ),
            ),
            "真心换真心": (
                "【真心换真心】",
                (
                    ("/真心换真心", "/真心换真心：创建报名局"),
                    ("/加入", "/加入：报名；对局中途加入者从下一个问题起参与"),
                    ("/开始", "/开始：至少 2 人后由发起者开局"),
                    ("/问", "轮到自己时 /问 内容：向其他人提问；/问 跳过：跳过本轮提问（/问题 也可）"),
                    ("/回答", "其余玩家 /回答 内容：回答当前问题；/回答 跳过：记为拒答（/答、/真心 也可）"),
                    ("/继续", "/继续：本轮结算后任一参与者开下一轮"),
                    ("/当前游戏", "/当前游戏：查看当前进度、玩家名单与总人数"),
                    ("/真心换真心数据", "/真心换真心数据：查看本群总战绩"),
                    ("/结束游戏", "/结束游戏：任一参与者结束本局"),
                ),
            ),
            "暗网交易所": (
                "【暗网交易所】",
                (
                    ("/上架暗网", "私聊 /上架暗网：按引导填写并预览虚拟商品"),
                    ("/取消上架", "私聊 /取消上架：取消尚未确认的上架草稿"),
                    ("/确认", "私聊 /确认：正式上架当前完整草稿；上架后不能撤回"),
                    ("/报价", "私聊 /报价 商品编号 金额：匿名报价并冻结相应摸鱼币"),
                    ("/查看暗网", "/查看暗网：完整列表在吸烟室发布；/查看暗网 [商品编号]：私聊返回单件详情；不显示精确结算时间"),
                    ("/确认收货", "私聊 /确认收货 [商品编号]：确认收到拍下的商品"),
                    ("/投诉", "私聊 /投诉 [商品编号]：未收到商品时提交董事会审核"),
                    ("/公开", "私聊 /公开 [商品编号]：只有双方都同意才公开买卖双方身份"),
                    ("/不公开", "私聊 /不公开 [商品编号]：拒绝公开，本次交易双方保持匿名"),
                ),
            ),
            "公演": (
                "【公演场次预约】",
                (
                    ("/预约公演", "/预约公演：在开放公演的群内启动私聊预约向导"),
                    ("/公演日程", "/公演日程：查看本群已审核的未来公演"),
                    ("/我的公演预约", "私聊 /我的公演预约：查看预约与延期审核状态"),
                    ("/取消公演预约", "私聊 /取消公演预约：预告前取消草稿或预约"),
                    ("/延期", "私聊 /延期 30m、/延期 1h 或 /延期 1d：申请推迟开场"),
                    ("/end", "/end：任一参演人员结束演出并开启 180 秒打赏"),
                    ("/打赏", "/打赏 参演人员名称 金额；也可回复参演人员本场消息发送 /打赏 金额"),
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
            "彩票": (
                "【公司双色球】",
                (
                    ("/彩票", "/彩票：查看本期期号、停售与开奖时刻、奖池、调节金与各奖级概率"),
                    ("/购买彩票", "/购买彩票 03 07 09 10 + 05：手选一注，红球 01-10 选 4 个不重复，蓝球 01-06 选 1 个"),
                    ("/购买彩票", "/购买彩票 机选 [注数]：随机一注或多注；也可写「随机」「机」「random」"),
                    ("/购买彩票", "/购买彩票 N 注：进入逐注填写，手选与「机选」可以混用"),
                    ("/确认彩票", "/确认彩票：一次性扣款并提交草稿里的全部号码"),
                    ("/取消彩票", "/取消彩票：放弃草稿，不扣款"),
                    ("/我的彩票", "/我的彩票 [期号]：查看最近一期或指定已开奖期的投注；下方为已开奖期累计统计"),
                    ("/彩票验证", "/彩票验证 期号：查看已开奖期次的号码、盐与承诺哈希"),
                    ("/彩票", "规则：每注 2 摸鱼币，每人每个自然日最多 5 注，同一期同一组号码只能买一次；开奖前 10 分钟停售，22:00 开奖"),
                    ("/彩票", "奖级：一等奖 100、二等奖 50、三等奖 15、四等奖 5、五等奖 1；任意中奖概率 26.59%，每注长期期望返回约 1.19 摸鱼币"),
                    ("/彩票", "奖池上限 200 摸鱼币，超出部分转入调节金；调节金累计到当前员工总数时全员各发 1 摸鱼币"),
                ),
            ),
            "风纪": (
                "【风纪罚款】",
                (
                    ("/罚款", "执法部门成员引用他人消息发送 /罚款 [理由]：对目标处以罚款"),
                    ("/罚款", "或 /罚款 名字 [理由]：按注册名罚款；重名请用 /罚款 #工号 [理由]"),
                    ("/罚款", "罚款即销毁，余额不足扣到 0；执法者获得抽成津贴（计入每日 5 币封顶）"),
                    ("/我的罚款", "私聊 /我的罚款：查看自己被罚款的记录"),
                ),
            ),
            "凿与发情值": (
                "【凿与发情值】",
                (
                    ("/凿", "引用对方消息发送 /凿 [附言]，或 /凿 名字 [附言]：凿一下对方"),
                    ("/凿", "被凿者发情值随机 +0~2、获得随机摸鱼币；发情值攒满 100 触发高潮"),
                    ("/拒绝被凿", "/拒绝被凿：不再接受被凿，凿你的人会吃一杵子"),
                    ("/允许被凿", "/允许被凿：重新接受被凿"),
                    ("/我的凿", "/我的凿：查看自己的发情值、被凿/凿人与高潮次数"),
                    ("/人气榜", "/人气榜：查看今日被凿人气前 5（按今日被凿次数，每日随收益榜推送）"),
                    ("/设置性别", "/设置性别 男|女：设置自己的性别（/修改性别 等效），影响高潮文风"),
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
                        "我有你没有",
                        "真心换真心",
                        "暗网交易所",
                        "公演",
                    )
                )
            return any(command in commands for command, _ in guides[category][1])

        if not topic:
            categories = (
                ("基础", "/帮助 基础：入职与资产"),
                ("商店", "/帮助 商店：购买、使用、赠送与授权"),
                (
                    "游戏",
                    "/帮助 游戏：玩法总览；/帮助 摸鱼躲藏、/帮助 记忆考核、/帮助 谁是卧底、/帮助 甩锅游戏、/帮助 蹦蹦数字炸弹、/帮助 德州扑克、/帮助 我有你没有、/帮助 真心换真心、/帮助 暗网交易所、/帮助 公演预约",
                ),
                ("随机事件", "/帮助 随机事件：报名与退出"),
                ("彩票", "/帮助 彩票：公司双色球的玩法、奖级与开奖规则"),
                ("风纪", "/帮助 风纪：风纪罚款"),
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
                    "我有你没有",
                    "真心换真心",
                    "暗网交易所",
                    "公演",
                )
                if any(command in commands for command, _ in guides[name][1])
            ]
            guide = "【游戏玩法】\n" + "\n".join(
                f"/帮助 {'公演预约' if name == '公演' else name}：查看{name}玩法"
                for name in game_topics
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

    # ------------------------------------------------------------- 公司双色球

    _LOTTERY_TIER_LABELS = {
        PrizeTier.HEAD: "一等奖",
        PrizeTier.SECOND: "二等奖",
        PrizeTier.THIRD: "三等奖",
        PrizeTier.FOURTH: "四等奖",
        PrizeTier.FIFTH: "五等奖",
    }

    _LOTTERY_DRAFT_SCENARIOS = {
        "started": "draft_started",
        "appended": "draft_appended",
        "ready": "draft_ready",
        "expired": "draft_expired",
        "duplicate": "draft_duplicate",
        "no_draft": "draft_missing",
        "limit": "draft_limit",
        "not_joined": "not_joined",
        "closed": "closed",
        "not_on_sale": "not_on_sale",
        "disabled": "disabled",
    }

    _LOTTERY_PURCHASE_SCENARIOS = {
        "bought": "bought",
        "disabled": "disabled",
        "closed": "closed",
        "not_on_sale": "not_on_sale",
        "not_joined": "not_joined",
        "daily_limit": "daily_limit",
        "round_full": "round_full",
        "duplicate": "duplicate",
        "duplicate_request": "bought",
        "insufficient_balance": "insufficient_balance",
    }

    def _company_lottery_draft_step(
        self, message: InboundMessage, content: str
    ) -> str | None:
        """非指令消息：正在逐注填写草稿时，把它当成号码或「机选」。

        不是草稿续填就返回 None，让这条消息照常走闲聊；号码格式对得上但草稿刚好
        超时的话，给一次明确提示而不是静默丢弃。
        """
        if (
            message.source_type != "group"
            or message.chatroom_id is None
            or self._repository.resolve_enabled_group_chat(message.chatroom_id) is None
        ):
            return None
        received_at = message.received_at.astimezone(_BEIJING)
        quick = is_quick_pick(content)
        ticket = None if quick else self._company_lottery_parse_single(content)
        if not quick and ticket is None:
            return None

        status = self._repository.company_lottery_draft_status(
            message.sender_platform_id, received_at
        )
        if status == "expired":
            return self._reply("/购买彩票", "draft_expired", received_at)
        if status != "active":
            return None

        if quick:
            result = self._repository.append_quick_pick_to_draft(
                message.sender_platform_id, received_at
            )
        else:
            result = self._repository.append_company_lottery_draft(
                message.sender_platform_id, ticket, received_at
            )
        return self._company_lottery_draft_reply(result, received_at)

    def _company_lottery_parse_single(self, content: str):
        view = self._repository.current_company_lottery_round()
        settings = (
            self._repository.get_company_lottery_settings()
            if view is None
            else view.rules
        )
        try:
            return parse_single(
                content,
                red_pool=settings.red_pool,
                red_count=settings.red_count,
                blue_pool=settings.blue_pool,
            )
        except TicketParseError:
            return None

    def _company_lottery(
        self, message: InboundMessage, command: str, content: str,
        received_at, group_chat_id,
    ) -> str | list[str] | None:
        if message.source_type != "group" or group_chat_id is None:
            return self._reply(command, "group_only", received_at)

        if command == "/彩票":
            view = self._repository.current_company_lottery_round(
                message.sender_platform_id
            )
            if view is None:
                return self._reply("/彩票", "not_open", received_at)
            return self._reply(
                "/彩票", "menu", received_at, self._company_lottery_menu_values(view)
            )

        if command == "/我的彩票":
            parts = content.split()
            if len(parts) > 2 or (
                len(parts) == 2 and not parts[1].lstrip("#").isdigit()
            ):
                return self._reply("/我的彩票", "usage", received_at)
            round_number = (
                None if len(parts) == 1 else int(parts[1].lstrip("#"))
            )
            if round_number is not None:
                view = self._repository.company_lottery_round_by_number(round_number)
                if view is None:
                    return self._reply(
                        "/我的彩票", "not_found", received_at,
                        {"{期号}": round_number},
                    )
                if view.state != "drawn":
                    return self._reply(
                        "/我的彩票", "not_drawn", received_at,
                        {"{期号}": round_number},
                    )
            history = self._repository.own_company_lottery_bets(
                message.sender_platform_id,
                drawn_only=True,
                round_number=round_number,
            )
            if not history.bets:
                if round_number is not None:
                    return self._reply(
                        "/我的彩票", "not_bought", received_at,
                        {"{期号}": round_number},
                    )
                return self._reply(
                    "/我的彩票",
                    "empty"
                    if not self._repository.own_company_lottery_bets(
                        message.sender_platform_id
                    ).bets
                    else "no_drawn",
                    received_at,
                )
            return self._reply(
                "/我的彩票",
                "shown",
                received_at,
                self._company_lottery_history_values(history),
            )

        if command == "/彩票验证":
            parts = content.split()
            if len(parts) != 2 or not parts[1].lstrip("#").isdigit():
                return self._reply("/彩票验证", "usage", received_at)
            view = self._repository.company_lottery_round_by_number(
                int(parts[1].lstrip("#"))
            )
            if view is None or view.state != "drawn" or view.answer is None:
                return self._reply("/彩票验证", "not_found", received_at)
            return self._reply(
                "/彩票验证",
                "shown",
                received_at,
                {
                    "{期号}": f"{view.round_number:04d}",
                    "{号码}": view.answer.display(),
                    "{盐}": view.salt or "",
                    "{哈希}": view.commit_hash,
                },
            )

        if command == "/取消彩票":
            cancelled = self._repository.cancel_company_lottery_draft(
                message.sender_platform_id
            )
            return self._reply(
                "/取消彩票", "cancelled" if cancelled else "no_draft", received_at
            )

        if command == "/确认彩票":
            result = self._repository.confirm_company_lottery_draft(
                message.platform_message_id,
                message.sender_platform_id,
                received_at,
            )
            if result.status in {"no_draft", "empty_draft"}:
                return self._reply("/确认彩票", result.status, received_at)
            purchase = result.purchase
            return self._reply(
                "/购买彩票",
                self._LOTTERY_PURCHASE_SCENARIOS.get(purchase.status, "closed"),
                received_at,
                self._company_lottery_purchase_values(purchase),
            )

        view = self._repository.current_company_lottery_round()
        settings = (
            self._repository.get_company_lottery_settings()
            if view is None
            else view.rules
        )
        try:
            order = parse_order(
                content,
                red_pool=settings.red_pool,
                red_count=settings.red_count,
                blue_pool=settings.blue_pool,
                max_quantity=settings.max_tickets_per_day,
            )
        except TicketParseError as error:
            scenario = (
                "invalid_format"
                if error.scenario in {"format", "empty"}
                else "invalid_number"
            )
            return self._reply(
                "/购买彩票",
                scenario,
                received_at,
                {
                    "{错误}": error.detail,
                    "{红球池}": settings.red_pool,
                    "{红球数}": settings.red_count,
                    "{蓝球池}": settings.blue_pool,
                },
            )

        if order.kind is OrderKind.GUIDED:
            draft = self._repository.start_company_lottery_draft(
                message.sender_platform_id, order.quantity, received_at
            )
            return self._company_lottery_draft_reply(draft, received_at)

        if order.kind is OrderKind.QUICK:
            purchase = self._repository.buy_quick_picks(
                message.platform_message_id,
                message.sender_platform_id,
                order.quantity,
                received_at,
            )
        else:
            purchase = self._repository.buy_company_lottery_tickets(
                message.platform_message_id,
                message.sender_platform_id,
                [order.ticket],
                received_at,
            )
        return self._reply(
            "/购买彩票",
            self._LOTTERY_PURCHASE_SCENARIOS.get(purchase.status, "closed"),
            received_at,
            self._company_lottery_purchase_values(purchase),
        )

    def _company_lottery_draft_reply(self, result, received_at) -> str:
        scenario = self._LOTTERY_DRAFT_SCENARIOS.get(result.status, "draft_missing")
        return self._reply(
            "/购买彩票",
            scenario,
            received_at,
            {
                "{目标注数}": result.target,
                "{已填注数}": result.collected,
                "{剩余注数}": max(result.target - result.collected, 0),
                "{当前注}": "" if result.latest is None else result.latest.display(),
            },
        )

    def _company_lottery_purchase_values(self, purchase) -> dict:
        if purchase.is_quick_pick:
            lines = ["　🎲 机选号码"] + [
                f"　{ticket.display()}" for ticket in purchase.tickets
            ]
        else:
            lines = [f"　{ticket.display()}" for ticket in purchase.tickets]
        return {
            "{注数}": len(purchase.tickets),
            "{花费}": purchase.cost,
            "{余额}": purchase.balance or 0,
            "{剩余注数}": purchase.remaining or 0,
            "{差额}": purchase.needed or 0,
            "{号码列表}": "\n".join(lines),
            "{截止时刻}": (
                purchase.close_at.strftime("%H:%M")
                if purchase.close_at is not None
                else "刚刚"
            ),
        }

    def _company_lottery_menu_values(self, view) -> dict:
        settings = view.rules
        counts = tier_counts(
            red_pool=settings.red_pool,
            red_count=settings.red_count,
            blue_pool=settings.blue_pool,
        )
        total = total_combinations(
            red_pool=settings.red_pool,
            red_count=settings.red_count,
            blue_pool=settings.blue_pool,
        )
        lines = [
            f"{self._LOTTERY_TIER_LABELS[tier]} 1/{total / counts[tier]:.4g} → "
            f"{settings.prizes[tier]}"
            for tier in ALL_TIERS
        ]
        win_rate = winning_combinations(
            red_pool=settings.red_pool,
            red_count=settings.red_count,
            blue_pool=settings.blue_pool,
        ) / total
        return {
            "{期数}": view.round_number,
            "{票价}": settings.ticket_price,
            "{已售}": view.tickets_sold,
            "{我的注数}": view.my_tickets,
            "{截止时刻}": view.close_at.strftime("%H:%M"),
            "{开奖时刻}": view.draw_at.strftime("%H:%M"),
            "{奖池}": view.pool_balance,
            "{调节金}": view.adjustment_balance,
            "{哈希}": view.commit_hash[:16],
            "{红球池}": settings.red_pool,
            "{红球数}": settings.red_count,
            "{蓝球池}": settings.blue_pool,
            "{奖级表}": "\n".join(lines),
            "{中奖率}": f"{win_rate:.2%}",
        }

    def _company_lottery_history_values(self, history) -> dict:
        lines = []
        for bet in history.bets[:8]:
            mark = "✗" if bet.prize_tier is None else f"+{bet.prize_amount}"
            quick = "（机选）" if bet.is_quick_pick else ""
            lines.append(f"第 {bet.round_number} 期 {bet.ticket.display()}{quick} {mark}")
        return {
            "{记录}": "\n".join(lines),
            "{累计投入}": history.total_cost,
            "{累计中奖}": history.total_prize,
            "{净收益}": history.total_prize - history.total_cost,
        }

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
