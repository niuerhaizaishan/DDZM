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
    service, repository, factory = _service(liar_dice_random=Random(7))
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

    _receive(service, "m9", "user-0", "/大话骰子数据", now)
    reply = _latest_reply(factory)
    assert "大话骰子数据" in reply
    assert "本局：" in reply and "总战绩：" in reply

    # 第 2 轮：连续轮转——开牌者是 2号，下家本应是 3号，但 3号已退出，回绕到 1号
    _receive(service, "m10", "user-0", "/继续", now)
    assert "第 2 轮" in _latest_reply(factory)
    _flush_all_outbound(repository, now)
    assert _dice_game(repository).state == "calling"
    assert _dice_game(repository).current_seat == 1
    assert len(_hand_texts(factory, since_round=2)) == 2

    _receive(service, "m11", seat1, "2个1", now)
    assert "叫 2个1" in _latest_reply(factory)
    _receive(service, "m12", seat2, "/开骰", now)
    assert _dice_game(repository).state == "round_end"

    # 已退出者重新加入：下一轮排到末尾（座位 3），并成为轮转起点
    _receive(service, "m13", seat3, "/加入", now)
    assert "下一轮开骰时参战" in _latest_reply(factory)
    _receive(service, "m14", "user-0", "/继续", now)
    assert "第 3 轮" in _latest_reply(factory)
    _flush_all_outbound(repository, now)
    game = _dice_game(repository)
    assert game.state == "calling"
    assert game.current_seat == 3
    assert len(_hand_texts(factory, since_round=3)) == 3

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
    from dzmm_bot.core.schema import DepartmentGamePlayRecord, GameParticipationRecord, LiarDiceRoundRecord

    with factory() as session:
        assert sorted(session.scalars(select(DepartmentGamePlayRecord.count))) == [1, 1, 1]
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


def test_liar_dice_signup_deadline_follows_settings():
    """报名时限必须来自设置（历史上硬编码 10 分钟），后台改了要跟着变。"""
    service, repository, factory = _service(liar_dice_random=Random(3))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    repository.set_liar_dice_settings(turn_seconds=120, signup_timeout_minutes=7)
    _receive(service, "m1", "user-0", "/大话骰子", now)
    game = _dice_game(repository)
    assert game is not None
    assert game.signup_deadline == now + timedelta(minutes=7)
    assert repository.get_liar_dice_settings().signup_timeout_minutes == 7


def test_liar_dice_signup_timeout_notice_states_the_deadline():
    service, repository, factory = _service(liar_dice_random=Random(3))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    _receive(service, "m1", "user-0", "/大话骰子", now)
    group_chat_id = _dice_game(repository).group_chat_id
    messages = repository.run_liar_dice_jobs(now + timedelta(minutes=6), group_chat_id)
    assert messages == ["【大话骰子】报名 5 分钟内没人 /开始，本局已自动取消。"]
    assert _dice_game(repository) is None


def test_liar_dice_round_end_expires_with_notice():
    """本轮结束后长时间没人 /继续：必须自动收尾并公告（历史行为是静默挂着）。"""
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
    group_chat_id = _dice_game(repository).group_chat_id
    seat1, seat2 = _seat_map(factory)[1], _seat_map(factory)[2]
    _receive(service, "m5", seat1, "3个3", now)
    _receive(service, "m6", seat2, "/开骰", now)
    game = _dice_game(repository)
    assert game.state == "round_end"
    assert game.round_end_deadline == now + timedelta(minutes=5)

    assert repository.run_liar_dice_jobs(now + timedelta(minutes=4), group_chat_id) == []
    messages = repository.run_liar_dice_jobs(
        now + timedelta(minutes=5), group_chat_id
    )
    assert len(messages) == 1
    assert "本轮结束后 5 分钟没人 /继续，本局已自动结束" in messages[0]
    assert _dice_game(repository) is None
    with factory() as session:
        from dzmm_bot.core.schema import LiarDiceGameRecord

        finished = session.scalar(select(LiarDiceGameRecord))
        assert finished.state == "completed"
        assert finished.finish_reason == "continue_expired"
        assert finished.active_key is None


def test_liar_dice_legacy_round_end_game_is_not_killed_on_first_tick():
    """部署前留下的历史局（无 deadline）：首次巡检只补写 deadline，不得当场结束。"""
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
    group_chat_id = _dice_game(repository).group_chat_id
    seat1, seat2 = _seat_map(factory)[1], _seat_map(factory)[2]
    _receive(service, "m5", seat1, "3个3", now)
    _receive(service, "m6", seat2, "/开骰", now)

    from dzmm_bot.core.schema import LiarDiceGameRecord

    with factory.begin() as session:
        legacy = session.scalar(select(LiarDiceGameRecord))
        legacy.round_end_deadline = None

    far_later = now + timedelta(hours=6)
    assert repository.run_liar_dice_jobs(far_later, group_chat_id) == []
    game = _dice_game(repository)
    assert game is not None and game.round_end_deadline == far_later + timedelta(minutes=5)
    assert repository.run_liar_dice_jobs(
        far_later + timedelta(minutes=4), group_chat_id
    ) == []
    assert len(
        repository.run_liar_dice_jobs(far_later + timedelta(minutes=5), group_chat_id)
    ) == 1
    assert _dice_game(repository) is None


def test_liar_dice_dealing_timeout_cancels_the_game():
    """私聊骰子迟迟未确认送达：不能让局永远卡在 dealing（群里此前一句话都没有）。"""
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
    game = _dice_game(repository)
    assert game.state == "dealing"
    assert game.dealing_deadline == now + timedelta(seconds=180)
    group_chat_id = game.group_chat_id

    assert repository.run_liar_dice_jobs(now + timedelta(seconds=120), group_chat_id) == []
    messages = repository.run_liar_dice_jobs(
        now + timedelta(seconds=180), group_chat_id
    )
    assert messages == [
        "⚠️【大话骰子】骰子私聊没送达，本局已取消，可重新发 /大话骰子 开新局。"
    ]
    assert _dice_game(repository) is None


def _outbound_count(factory) -> int:
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        return len(session.scalars(select(OutboundRecord)).all())


def _to_round_end(service, repository, factory, now):
    _receive(service, "m1", "user-0", "/大话骰子", now)
    _receive(service, "m2", "user-1", "/加入", now)
    _receive(service, "m3", "user-2", "/加入", now)
    _receive(service, "m4", "user-0", "/开始", now)
    _flush_all_outbound(repository, now)
    seats = _seat_map(factory)
    _receive(service, "m5", seats[1], "3个3", now)
    _receive(service, "m6", seats[2], "/开骰", now)
    return seats


def test_liar_dice_participant_call_after_round_end_gets_an_explanation():
    """本轮结束后参与者继续叫数：要告诉他为什么没生效（历史行为是完全静默）。"""
    service, repository, factory = _service(liar_dice_random=Random(11))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    seats = _to_round_end(service, repository, factory, now)
    assert _dice_game(repository).state == "round_end"

    before = _outbound_count(factory)
    _receive(service, "m7", seats[1], "3个4", now)
    assert _outbound_count(factory) == before + 1
    assert "本轮已作废或已结束" in _latest_reply(factory)
    assert "/继续" in _latest_reply(factory)


def test_liar_dice_outsider_call_stays_silent():
    """非本局参与者打「N个X」：保持静默，不把群聊里的普通数字当指令回。"""
    service, repository, factory = _service(liar_dice_random=Random(11))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _receive(service, "join-9", "user-9", "/入职 丁", now)
    _seed_direct_chats(factory, now)
    _to_round_end(service, repository, factory, now)

    before = _outbound_count(factory)
    _receive(service, "m7", "user-9", "3个4", now)
    assert _outbound_count(factory) == before


def test_liar_dice_call_without_any_game_stays_silent():
    service, repository, factory = _service(liar_dice_random=Random(11))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)

    before = _outbound_count(factory)
    _receive(service, "m1", "user-0", "3个4", now)
    assert _outbound_count(factory) == before


def test_liar_dice_admin_force_end_announces_in_the_group():
    """锁定既有行为：管理端强制结束会给群里发公告（函数末尾统一发 /结束游戏 admin_forced 模板）。"""
    service, repository, factory = _service(liar_dice_random=Random(11))
    now = datetime(2026, 10, 2, 16, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    _join_employees(service, now)
    _seed_direct_chats(factory, now)
    _to_round_end(service, repository, factory, now)
    game = _dice_game(repository)
    before = _outbound_count(factory)

    assert repository.force_end_gameplay("liar_dice", game.id, now, game.group_chat_id)
    assert _outbound_count(factory) == before + 1
    assert "管理员已强制结束当前游戏" in _latest_reply(factory)
    assert _dice_game(repository) is None
