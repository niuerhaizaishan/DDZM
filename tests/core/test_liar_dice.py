from datetime import datetime, timedelta
from random import Random
import re
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.liar_dice import (
    count_point,
    is_legal_raise,
    judge_open,
    parse_call,
)
from dzmm_bot.runtime.contracts import InboundMessage


BEIJING = ZoneInfo("Asia/Shanghai")


class _ReverseOrderRandom(Random):
    def __init__(self, seed):
        super().__init__(seed)
        self.shuffle_count = 0

    def shuffle(self, values):
        self.shuffle_count += 1
        values.reverse()


def _service(*, liar_dice_random=None):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base
    from dzmm_bot.core.service import CoreService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory, liar_dice_random=liar_dice_random)
    return CoreService(repository, GroupCommandHandler(repository)), repository, factory


def _receive(service, message_id, sender, content, received_at, **kwargs):
    kwargs.setdefault("chatroom_id", "group-main")
    message = InboundMessage(message_id, sender, content, received_at, **kwargs)
    return service.receive_inbound(message)


def _latest_reply(factory):
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        latest = session.scalar(
            select(OutboundRecord).order_by(OutboundRecord.created_at.desc())
        )
        if latest is None:
            return ""
        if latest.inbound_message_id is None:
            return latest.text
        return "\n".join(
            session.scalars(
                select(OutboundRecord.text)
                .where(OutboundRecord.inbound_message_id == latest.inbound_message_id)
                .order_by(OutboundRecord.reply_index)
            )
        )


def _join_employees(service, now):
    for index, name in enumerate(("甲", "乙", "丙")):
        _receive(service, f"join-{index}", f"user-{index}", f"/入职 {name}", now)


def _seed_direct_chats(factory, now, drop_platform_id=None):
    from dzmm_bot.core.schema import DirectChatRecord

    with factory.begin() as session:
        for index in range(3):
            platform_id = f"user-{index}"
            if platform_id == drop_platform_id:
                continue
            session.add(
                DirectChatRecord(
                    platform_user_id=platform_id,
                    chatroom_id=f"dm-{platform_id}",
                    discovered_at=now,
                )
            )


def _flush_all_outbound(repository, now):
    """模拟 worker 把当前所有待发消息都发成功（含私聊发骰回执）。"""
    for _ in range(32):
        record = repository.claim_outbound("worker-1", now, 30)
        if record is None:
            return
        assert repository.confirm_sent(
            record.id, "worker-1", record.lease_token, f"psn-{record.id}", now
        )
    raise AssertionError("outbound 队列迟迟不清空")


def _seat_map(factory):
    from dzmm_bot.core.schema import (
        LiarDiceGameRecord,
        LiarDicePlayerRecord,
        UserRecord,
    )

    with factory() as session:
        rows = session.execute(
            select(LiarDicePlayerRecord, UserRecord)
            .join(UserRecord, UserRecord.id == LiarDicePlayerRecord.user_id)
            .join(
                LiarDiceGameRecord,
                LiarDiceGameRecord.id == LiarDicePlayerRecord.game_id,
            )
            .where(
                LiarDiceGameRecord.active_key == "global",
                LiarDicePlayerRecord.state == "active",
            )
        ).all()
        return {player.seat_number: user.platform_id for player, user in rows}


def _dice_game(repository):
    from dzmm_bot.core.schema import LiarDiceGameRecord

    with repository._session() as session:
        return session.scalar(
            select(LiarDiceGameRecord).where(
                LiarDiceGameRecord.active_key == "global"
            )
        )


def _hand_texts(factory, since_round=None):
    from dzmm_bot.core.schema import LiarDicePlayerRecord, OutboundRecord

    with factory() as session:
        rows = session.execute(
            select(OutboundRecord, LiarDicePlayerRecord)
            .join(
                LiarDicePlayerRecord,
                LiarDicePlayerRecord.hand_outbound_id == OutboundRecord.id,
            )
            .order_by(OutboundRecord.created_at)
        ).all()
        return [
            outbound.text
            for outbound, _ in rows
            if since_round is None or f"第 {since_round} 轮" in outbound.text
        ]


def _calling_game(player_count=3):
    service, repository, factory = _service(liar_dice_random=Random(7))
    now = datetime(2026, 10, 14, 12, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=group-main", now)
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    _receive(service, "start", "user-0", "/大话骰子", now)
    for index in range(1, player_count):
        _receive(service, f"signup-{index}", f"user-{index}", "/加入", now)
    _receive(service, "begin", "user-0", "/开始", now)
    _flush_all_outbound(repository, now)
    return service, repository, factory, now


def test_parse_call_and_raise_rules():
    assert parse_call("3个3") == (3, 3)
    assert parse_call("/5个6") == (5, 6)
    assert parse_call("12 个 2") == (12, 2)
    assert parse_call("3个7") is None
    assert parse_call("个3") is None
    assert is_legal_raise(None, (3, 2), 3)
    assert not is_legal_raise(None, (2, 2), 3)
    assert is_legal_raise((3, 2), (4, 1), 3)
    assert is_legal_raise((3, 2), (3, 5), 3)
    assert not is_legal_raise((3, 2), (3, 2), 3)
    assert not is_legal_raise((4, 1), (3, 6), 3)


def test_count_point_with_wild():
    dice = {"a": [1, 2, 3, 4, 5], "b": [2, 2, 3, 3, 3]}
    assert count_point(dice, 3, 6, False) == 4
    assert count_point(dice, 2, 2, False) == 3
    assert count_point(dice, 2, 2, True) == 3
    assert count_point(dice, 6, 3, False) == 4
    assert count_point(dice, 6, 3, True) == 0
    assert judge_open(dice, (4, 3), 6, False)
    assert not judge_open(dice, (5, 3), 6, False)


@pytest.mark.parametrize("secondary_group", [False, True])
def test_liar_dice_global_switch_and_minimum_apply_to_all_groups(secondary_group):
    service, repository, factory = _service()
    now = datetime(2026, 10, 6, 12, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=group-main", now)
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    group = repository.create_group_chat("第二群", "https://www.aikda.com/chat?c=group-rest", True, True, False, False, now) if secondary_group else repository.list_group_chats()[0]
    repository.set_liar_dice_settings(turn_seconds=90, enabled=False, min_players=3)
    _receive(service, "disabled", "user-0", "/大话骰子", now, chatroom_id=group.chatroom_id)
    assert "当前未开放" in _latest_reply(factory)
    assert repository.current_gameplay_admin_summary(now, group.id).game_type is None
    repository.set_liar_dice_settings(turn_seconds=90, enabled=True, min_players=3)
    _receive(service, "start", "user-0", "/大话骰子", now, chatroom_id=group.chatroom_id)
    assert "至少 3 人" in _latest_reply(factory)
    _receive(service, "join-second", "user-1", "/加入", now, chatroom_id=group.chatroom_id)
    _receive(service, "too-few", "user-0", "/开始", now, chatroom_id=group.chatroom_id)
    assert "至少 3 人" in _latest_reply(factory)
    repository.set_liar_dice_settings(turn_seconds=90, enabled=False, min_players=3)
    _receive(service, "join-third", "user-2", "/加入", now, chatroom_id=group.chatroom_id)
    _receive(service, "begin", "user-0", "/开始", now, chatroom_id=group.chatroom_id)
    assert "摇骰中（3 人）" in _latest_reply(factory)
    _flush_all_outbound(repository, now)
    summary = repository.current_gameplay_admin_summary(now, group.id)
    assert summary.game_type == "liar_dice"
    assert summary.round_number == 1
    assert summary.action_deadline == now + timedelta(seconds=90)
    assert [player.number for player in summary.participants] == [1, 2, 3]
    assert summary.current_seat == 1
    assert repository.force_end_gameplay("liar_dice", summary.game_id, now, group.id)
    assert not repository.force_end_gameplay("liar_dice", summary.game_id, now, group.id)
    assert repository.current_gameplay_admin_summary(now, group.id).game_type is None
    assert repository.start_liar_dice("user-0", now, group.id).status == "disabled"


def test_liar_dice_full_flow():
    random = _ReverseOrderRandom(7)
    service, repository, factory = _service(liar_dice_random=random)
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)

    _receive(service, "m1", "user-0", "/大话骰子", now)
    assert "报名已开启" in _latest_reply(factory)
    _receive(service, "m2", "user-1", "/加入", now)
    assert "当前 2 人" in _latest_reply(factory)
    _receive(service, "m3", "user-2", "/加入", now)
    assert "当前 3 人" in _latest_reply(factory)
    _receive(service, "m4", "user-0", "/加入", now)
    assert "已经在当前大话骰子局" in _latest_reply(factory)

    game = _dice_game(repository)
    assert game is not None and game.state == "signup"

    _receive(service, "m5", "user-0", "/开始", now)
    assert "摇骰中" in _latest_reply(factory)
    _flush_all_outbound(repository, now)
    game = _dice_game(repository)
    assert game.state == "calling"
    assert game.round_number == 1
    assert game.current_seat == 1

    hands = _hand_texts(factory)
    assert len(hands) == 3
    assert all("你的骰子" in text for text in hands)
    first_wild = repository.liar_dice_private_hands("user-0", now).private_message
    wild_face = re.search(r"本轮万能点 🎲([1-6])", first_wild).group(1)
    assert all(f"本轮万能点：🎲{wild_face}" in text for text in hands)
    assert all("叫过该点后失效" in text for text in hands)

    seats = _seat_map(factory)
    seat1, seat2, seat3 = seats[1], seats[2], seats[3]

    # 第 1 轮：1号叫数；3号退出（排队，本轮仍打）；2号开牌
    _receive(service, "m6", seat1, "3个3", now)
    assert "叫 3个3" in _latest_reply(factory)
    _receive(service, "m7", seat3, "/退出", now)
    assert "本轮结束后生效" in _latest_reply(factory)
    _receive(service, "m8", seat2, "/开骰", now)
    assert "全场骰子" in _latest_reply(factory)
    assert "获得发令权" in _latest_reply(factory)
    assert _dice_game(repository).state == "round_end"
    from dzmm_bot.core.schema import DepartmentGamePlayRecord

    with factory() as session:
        assert sorted(session.scalars(select(DepartmentGamePlayRecord.count))) == [1, 1, 1]
    _receive(service, "m8-repeat", seat2, "/开骰", now)
    with factory() as session:
        assert sorted(session.scalars(select(DepartmentGamePlayRecord.count))) == [1, 1, 1]

    _receive(service, "m9", "user-0", "/大话骰子数据", now)
    reply = _latest_reply(factory)
    assert "大话骰子数据" in reply
    assert "本局：" in reply and "总战绩：" in reply

    _receive(service, "m10", "user-0", "/继续", now)
    assert "第 2 轮" in _latest_reply(factory)
    assert "重新随机排列" in _latest_reply(factory)
    _flush_all_outbound(repository, now)
    assert _dice_game(repository).state == "calling"
    assert _dice_game(repository).current_seat == 1
    assert len(_hand_texts(factory, since_round=2)) == 2
    second_seats = _seat_map(factory)
    assert second_seats == {1: seat2, 2: seat1}
    assert random.shuffle_count == 2
    second_wild = repository.liar_dice_private_hands(second_seats[1], now).private_message
    wild_face = re.search(r"本轮万能点 🎲([1-6])", second_wild).group(1)
    assert all(f"本轮万能点：🎲{wild_face}" in text for text in _hand_texts(factory, since_round=2))
    announcement = _latest_reply(factory)
    for seat, platform_id in second_seats.items():
        assert f"{seat}号 {repository.find_user(platform_id).display_name}" in announcement

    _receive(service, "m11", second_seats[1], "2个1", now)
    assert "叫 2个1" in _latest_reply(factory)
    _receive(service, "m12", second_seats[2], "/开骰", now)
    assert _dice_game(repository).state == "round_end"

    _receive(service, "m13", seat3, "/加入", now)
    assert "下一轮开骰时参战" in _latest_reply(factory)
    _receive(service, "m14", "user-0", "/继续", now)
    assert "第 3 轮" in _latest_reply(factory)
    _flush_all_outbound(repository, now)
    game = _dice_game(repository)
    assert game.state == "calling"
    assert game.current_seat == 1
    assert len(_hand_texts(factory, since_round=3)) == 3
    third_seats = _seat_map(factory)
    assert third_seats == {1: seat3, 2: seat1, 3: seat2}
    assert random.shuffle_count == 3

    _receive(service, "m15", seat3, "3个1", now)
    assert "叫 3个1" in _latest_reply(factory)
    _receive(service, "m16", seat1, "/开骰", now)
    assert _dice_game(repository).state == "round_end"

    # 只剩 1 人时退出 → 直接散局
    _receive(service, "m17", seat1, "/退出", now)
    assert "你已退出本局大话骰子" in _latest_reply(factory)
    _receive(service, "m18", seat2, "/退出", now)
    assert "不足 2 人" in _latest_reply(factory)
    from dzmm_bot.core.schema import LiarDiceGameRecord

    with repository._session() as session:
        finished = session.scalar(
            select(LiarDiceGameRecord).order_by(
                LiarDiceGameRecord.created_at.desc()
            )
        )
    assert finished.state == "completed"
    from dzmm_bot.core.schema import GameParticipationRecord, LiarDiceRoundRecord

    with factory() as session:
        assert sorted(session.scalars(select(DepartmentGamePlayRecord.count))) == [2, 3, 3]
        assert len(session.scalars(select(GameParticipationRecord)).all()) == 3
        snapshots = session.scalars(select(LiarDiceRoundRecord.dice_snapshot)).all()
        assert all(set(snapshot) <= {str(repository.find_user(f"user-{index}").id)
                                    for index in range(3)} for snapshot in snapshots)


def test_liar_dice_career_statistics_accumulate_across_games():
    service, repository, factory = _service(liar_dice_random=Random(7))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)

    def career_opens_total(reply):
        career = reply.split("总战绩：", 1)[1]
        opens = career.split("开牌次数最多：", 1)[1].splitlines()[0]
        return sum(int(count) for count in re.findall(r"（(\d+) 次）", opens))

    def play_one_round(message_id):
        _receive(service, f"{message_id}a", "user-0", "/大话骰子", now)
        _receive(service, f"{message_id}b", "user-1", "/加入", now)
        _receive(service, f"{message_id}c", "user-2", "/加入", now)
        _receive(service, f"{message_id}d", "user-0", "/开始", now)
        _flush_all_outbound(repository, now)
        seats = _seat_map(factory)
        _receive(service, f"{message_id}e", seats[1], "3个2", now)
        assert "叫 3个2" in _latest_reply(factory)
        _receive(service, f"{message_id}f", seats[2], "/开骰", now)
        assert "全场骰子" in _latest_reply(factory)
        assert _dice_game(repository).state == "round_end"

    # 第 1 局打完一轮回合后收局：对局结束后没有本局块，总战绩保留
    play_one_round("g1")
    _receive(service, "end1", "user-0", "/结束游戏", now)
    assert "本局结束" in _latest_reply(factory)
    _receive(service, "stat1", "user-0", "/大话骰子数据", now)
    reply = _latest_reply(factory)
    assert "总战绩：" in reply
    assert "本局：" not in reply
    assert career_opens_total(reply) == 1

    # 第 2 局再打一轮：总战绩跨局累计为 2 次
    play_one_round("g2")
    _receive(service, "stat2", "user-0", "/大话骰子数据", now)
    reply = _latest_reply(factory)
    assert "本局：" in reply
    assert career_opens_total(reply) == 2


def test_liar_dice_requires_direct_chats():
    service, repository, factory = _service(liar_dice_random=Random(3))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now, drop_platform_id="user-2")

    _receive(service, "m1", "user-0", "/大话骰子", now)
    _receive(service, "m2", "user-1", "/加入", now)
    _receive(service, "m3", "user-2", "/加入", now)
    _receive(service, "m4", "user-0", "/开始", now)
    assert "私聊" in _latest_reply(factory) and "丙" in _latest_reply(factory)
    assert _dice_game(repository).state == "signup"


def test_liar_dice_timeout_skip_and_void():
    service, repository, factory = _service(liar_dice_random=Random(11))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    _receive(service, "m1", "user-0", "/大话骰子", now)
    _receive(service, "m2", "user-1", "/加入", now)
    _receive(service, "m3", "user-2", "/加入", now)
    _receive(service, "m4", "user-0", "/开始", now)
    _flush_all_outbound(repository, now)
    assert _dice_game(repository).state == "calling"
    group_chat_id = _dice_game(repository).group_chat_id

    later = now + timedelta(minutes=10)
    first_skip = repository.run_liar_dice_jobs(later, group_chat_id)
    assert len(first_skip) == 1
    assert "超时" in first_skip[0]
    assert _dice_game(repository).state == "calling"

    repository.run_liar_dice_jobs(later + timedelta(minutes=5), group_chat_id)
    repository.run_liar_dice_jobs(later + timedelta(minutes=10), group_chat_id)
    game = _dice_game(repository)
    assert game.state == "round_end"

    _receive(service, "continue-voided-round", "user-0", "/继续", later + timedelta(minutes=10))
    _flush_all_outbound(repository, later + timedelta(minutes=10))
    game = _dice_game(repository)
    assert game.state == "calling" and game.round_number == 2
    assert game.timeout_streak == 0 and game.current_seat == 1
    assert set(_seat_map(factory)) == {1, 2, 3}


def test_liar_dice_dealing_timeout_starts_round_and_keeps_hands_available():
    service, repository, factory = _service(liar_dice_random=Random(13))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    _receive(service, "m1", "user-0", "/大话骰子", now)
    _receive(service, "m2", "user-1", "/加入", now)
    _receive(service, "m3", "user-2", "/加入", now)
    _receive(service, "m4", "user-0", "/开始", now)

    game = _dice_game(repository)
    assert game.state == "dealing"
    assert game.dealing_deadline == now + timedelta(seconds=15)

    # 已经处于发骰阶段的旧对局没有截止时间，也必须能够自动补齐并恢复。
    with factory.begin() as session:
        session.get(type(game), game.id).dealing_deadline = None
    repository.run_liar_dice_jobs(now + timedelta(seconds=14), game.group_chat_id)
    assert _dice_game(repository).state == "dealing"

    repository.run_liar_dice_jobs(now + timedelta(seconds=15), game.group_chat_id)
    game = _dice_game(repository)
    assert game.state == "calling"
    assert game.dealing_deadline is None
    assert game.turn_deadline is not None

    from dzmm_bot.core.schema import LiarDicePlayerRecord, OutboundRecord

    with factory() as session:
        players = list(
            session.scalars(
                select(LiarDicePlayerRecord).where(
                    LiarDicePlayerRecord.game_id == game.id,
                    LiarDicePlayerRecord.state == "active",
                )
            )
        )
        assert {player.hand_delivery_state for player in players} == {"failed"}
        hand_ids = {player.hand_outbound_id for player in players}
        assert set(
            session.scalars(
                select(OutboundRecord.status).where(OutboundRecord.id.in_(hand_ids))
            )
        ) == {"failed"}
        announcements = list(
            session.scalars(
                select(OutboundRecord.text).where(
                    OutboundRecord.delivery_kind == "group",
                    OutboundRecord.inbound_message_id.is_(None),
                )
            )
        )
        assert any("私聊发送超时" in text and "/看骰" in text for text in announcements)

    shown = repository.liar_dice_private_hands("user-0", now)
    assert shown.status == "shown"
    assert "你的骰子" in shown.private_message


def test_liar_dice_look_dice_is_direct_only():
    service, repository, factory = _service(liar_dice_random=Random(5))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    _receive(service, "m1", "user-0", "/大话骰子", now)
    _receive(service, "m2", "user-1", "/加入", now)
    _receive(service, "m3", "user-2", "/加入", now)
    _receive(service, "m4", "user-0", "/开始", now)
    _flush_all_outbound(repository, now)

    _receive(service, "m5", "user-0", "/看骰", now)
    assert "私聊" in _latest_reply(factory)
    _receive(
        service,
        "m6",
        "user-0",
        "/看骰",
        now,
        source_type="direct",
        chatroom_id="dm-user-0",
    )
    assert "你的骰子" in _latest_reply(factory)
    assert "本轮万能点" in _latest_reply(factory)


@pytest.mark.parametrize("quantity,face,success", [(4, 1, True), (3, 1, False), (4, 6, True), (3, 6, False)])
def test_liar_dice_jump_open_outcomes_and_statistics(quantity, face, success):
    from dzmm_bot.core.schema import LiarDicePlayerRecord, LiarDiceRoundRecord

    service, repository, factory, now = _calling_game()
    seats = _seat_map(factory)
    caller = repository.find_user(seats[1])
    next_caller = repository.find_user(seats[2])
    challenger = repository.find_user(seats[3])
    with factory.begin() as session:
        round_record = session.scalar(select(LiarDiceRoundRecord))
        round_record.wild_face = 6
        for player in session.scalars(select(LiarDicePlayerRecord)):
            player.dice = [6, 2, 2, 2, 2]
    _receive(service, "call", seats[1], f"{quantity}个{face}", now)
    _receive(service, "jump", seats[3], "/跳开", now)
    reply = _latest_reply(factory)
    assert "全场骰子" in reply and "实际 3 个" in reply
    if success:
        assert f"{challenger.display_name} 跳开成功" in reply
        assert f"{challenger.display_name} 获得发令权" in reply
        assert f"给 {caller.display_name} 布置一个惩罚任务" in reply
        assert "双重惩罚" not in reply
    else:
        assert f"{challenger.display_name} 跳开失败" in reply
        assert "双重惩罚" in reply
        assert f"叫骰者 {caller.display_name} 和原本下一个叫骰者 {next_caller.display_name}" in reply
        assert f"各给 {challenger.display_name} 布置一个惩罚任务" in reply
    with factory() as session:
        round_record = session.scalar(select(LiarDiceRoundRecord))
        assert round_record.state == "resolved"
        assert round_record.opener_user_id == challenger.id
        assert round_record.winner_user_id == (challenger.id if success else caller.id)
        assert round_record.loser_user_id == (caller.id if success else challenger.id)
        assert round_record.wild_invalidated == (face == 6)
        assert len(round_record.dice_snapshot) == 3
    game = _dice_game(repository)
    assert game.state == "round_end" and game.turn_deadline is None
    statistics = repository.liar_dice_statistics(game.group_chat_id).current
    assert statistics.opens_leaders == ((challenger.display_name, 1),)
    assert statistics.penalty_leaders == (((caller if success else challenger).display_name, 1),)
    assert statistics.catch_leaders == (((challenger.display_name, 1),) if success else ())
    _receive(service, "jump", seats[3], "/跳开", now)
    _receive(service, "jump-again", seats[3], "/跳开", now)
    assert "不在叫牌阶段" in _latest_reply(factory)
    assert repository.liar_dice_statistics(game.group_chat_id).current == statistics
    _receive(service, "continue", seats[3], "/继续", now)
    _flush_all_outbound(repository, now)
    assert _dice_game(repository).state == "calling"
    assert _dice_game(repository).round_number == 2
    assert len(_hand_texts(factory, since_round=2)) == 3


def test_liar_dice_jump_open_permissions_and_command_switch():
    service, repository, factory, now = _calling_game()
    seats = _seat_map(factory)
    _receive(service, "without-call", seats[3], "/跳开", now)
    assert "还没有人叫数" in _latest_reply(factory)
    _receive(service, "call", seats[1], "16个1", now)
    _receive(service, "self-open", seats[1], "/跳开", now)
    assert "不能开自己" in _latest_reply(factory)
    _receive(service, "current-open", seats[2], "/跳开", now)
    assert "请使用 /开骰" in _latest_reply(factory)
    _receive(service, "out-of-turn", seats[3], "/开骰", now)
    assert "还没轮到你" in _latest_reply(factory)
    _receive(service, "private-jump", seats[3], "/跳开", now, source_type="direct", chatroom_id=f"dm-{seats[3]}")
    assert "请在大话骰子所在群发送 /跳开" in _latest_reply(factory)
    repository.ensure_command_definitions()
    assert repository.set_command_enabled("/跳开", False)
    _receive(service, "disabled-jump", seats[3], "/跳开", now)
    assert _dice_game(repository).state == "calling"
    assert repository.set_command_enabled("/跳开", True)
    _receive(service, "enabled-jump", seats[3], "/跳开", now)
    assert "跳开成功" in _latest_reply(factory)


def test_liar_dice_jump_open_rejects_outsiders_and_next_round_joiners():
    service, repository, factory, now = _calling_game(2)
    seats = _seat_map(factory)
    game = _dice_game(repository)
    _receive(service, "call", seats[1], "16个1", now)
    _receive(service, "outsider-jump", "user-2", "/跳开", now)
    assert "只有本轮参与者" in _latest_reply(factory)
    _receive(service, "join-later", "user-2", "/加入", now)
    _receive(service, "joiner-jump", "user-2", "/跳开", now)
    assert "下一轮加入者请等待" in _latest_reply(factory)
    _receive(service, "two-player-jump", seats[2], "/跳开", now)
    assert "请使用 /开骰" in _latest_reply(factory)
    assert _dice_game(repository).state == "calling"
    _receive(service, "open", seats[2], "/开骰", now)
    _receive(service, "continue", "user-2", "/继续", now)
    _flush_all_outbound(repository, now)
    new_seats = _seat_map(factory)
    assert set(new_seats) == {1, 2, 3}
    assert set(new_seats.values()) == {"user-0", "user-1", "user-2"}
    assert _dice_game(repository).id == game.id
    assert _dice_game(repository).current_seat == 1


def test_liar_dice_jump_open_uses_current_actor_after_timeout():
    service, repository, factory, now = _calling_game()
    seats = _seat_map(factory)
    _receive(service, "call", seats[1], "3个1", now)
    game = _dice_game(repository)
    repository.run_liar_dice_jobs(game.turn_deadline, game.group_chat_id)
    assert _dice_game(repository).current_seat == 3
    _receive(service, "jump", seats[2], "/跳开", now + timedelta(minutes=3))
    reply = _latest_reply(factory)
    caller = repository.find_user(seats[1])
    next_caller = repository.find_user(seats[3])
    assert "跳开失败" in reply
    assert f"叫骰者 {caller.display_name} 和原本下一个叫骰者 {next_caller.display_name}" in reply


def test_liar_dice_jump_open_rejects_missing_next_actor():
    from dzmm_bot.core.schema import LiarDiceGameRecord

    service, repository, factory, now = _calling_game()
    seats = _seat_map(factory)
    _receive(service, "call", seats[1], "3个1", now)
    game = _dice_game(repository)
    with factory.begin() as session:
        session.get(LiarDiceGameRecord, game.id).current_seat = 99
    _receive(service, "jump", seats[2], "/跳开", now)
    assert "没有可跳过的下一位" in _latest_reply(factory)
    assert _dice_game(repository).state == "calling"


def test_liar_dice_jump_open_is_scoped_to_group():
    service, repository, factory, now = _calling_game()
    seats = _seat_map(factory)
    repository.create_group_chat("第二群", "https://www.aikda.com/chat?c=group-other", True, True, False, False, now)
    _receive(service, "call", seats[1], "16个1", now)
    _receive(service, "wrong-group", seats[3], "/跳开", now, chatroom_id="group-other")
    assert "当前没有大话骰子对局" in _latest_reply(factory)
    assert _dice_game(repository).state == "calling"
    _receive(service, "right-group", seats[3], "/跳开", now)
    assert "跳开成功" in _latest_reply(factory)


@pytest.mark.parametrize("state", ["signup", "dealing"])
def test_liar_dice_jump_open_rejects_before_calling(state):
    from dzmm_bot.core.schema import LiarDiceGameRecord, LiarDiceRoundRecord

    service, repository, factory, now = _calling_game()
    seats = _seat_map(factory)
    game = _dice_game(repository)
    with factory.begin() as session:
        session.get(LiarDiceGameRecord, game.id).state = state
    _receive(service, "early-jump", seats[3], "/跳开", now)
    assert "不在叫牌阶段" in _latest_reply(factory)
    assert _dice_game(repository).state == state
    with factory() as session:
        assert session.scalar(select(LiarDiceRoundRecord)).opener_user_id is None


def test_liar_dice_help_lists_jump_open_and_reshuffle():
    service, repository, factory, now = _calling_game()
    _receive(service, "help", "user-0", "/帮助 大话骰子", now)
    reply = _latest_reply(factory)
    assert "/跳开" in reply and "原定下一位各一个惩罚" in reply
    assert "重新随机排列顺序" in reply
