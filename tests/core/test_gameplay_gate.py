"""两道互斥闸门的覆盖面一致性测试。

仓库里有两道互斥闸门：

- ``_has_active_game``：手写查询清单，被 /记忆考核（单人/对战/公会赛）、蹦蹦数字炸弹、
  德州扑克、随机事件等调用；
- ``_group_has_active_gameplay``：遍历 ``GROUP_GAME_TYPES`` + 随机事件 + 公演预约，
  被 /大话骰子、国王游戏、真心换真心、我有你没有、群停用校验等调用。

历史上两道门覆盖不一致：大话骰子在进行中时 ``_has_active_game`` 查不到它，
于是 /记忆考核 能照开，同群两局并存 → ``/继续`` 与 ``/当前游戏`` 都回
「检测到多个活动游戏，请联系管理员处理」，只能人工介入。

本文件用参数化用例覆盖 ``GROUP_GAME_TYPES`` 全集：任何一道门漏掉一种玩法都会变红。
新增玩法时请同时补 ``_seed_active``（否则会直接报「未覆盖的玩法类型」）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.group_games import GROUP_GAME_TYPES
from dzmm_bot.core.schema import (
    BlameGameRecord,
    GroupChatRecord,
    HideAndSeekGameRecord,
    KingGameRecord,
    LiarDiceGameRecord,
    LiarDicePlayerRecord,
    MemoryAssessmentGameRecord,
    MemoryGuildMatchRecord,
    NeverHaveIEverGameRecord,
    NumberBombGameRecord,
    PerformanceReservationRecord,
    RedPacketRecord,
    TexasHoldemGameRecord,
    TruthTradeGameRecord,
    UndercoverSessionRecord,
    UserRecord,
)

BEIJING = ZoneInfo("Asia/Shanghai")
GROUP_ID = UUID("00000000-0000-0000-0000-0000000000aa")
HOST_PLATFORM_ID = "gate-host"


def _build():
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    now = datetime(2026, 10, 11, 20, 0, tzinfo=BEIJING)
    with factory.begin() as session:
        session.add(
            GroupChatRecord(
                id=GROUP_ID,
                name="玩法闸门测试群",
                chatroom_id="group-main",
                listening_enabled=True,
                games_enabled=True,
                random_events_enabled=True,
                announcements_enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            UserRecord(
                platform_id=HOST_PLATFORM_ID,
                display_name="闸门测试员",
                employee_number=1,
                joined_at=now,
            )
        )
    return repository, factory, now


def _seed_active(session, game_type: str, now: datetime) -> None:
    """把 ``game_type`` 造成「本群活跃」的最小状态（字段照 _group_has_active_game_type 的判定条件）。"""
    user_id = uuid4()
    if game_type == "red_packet":
        session.add(
            RedPacketRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                issuer_user_id=user_id,
                target_count=3,
                total_amount=30,
                state="open",
                has_empty=False,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
    elif game_type == "hide_and_seek":
        session.add(
            HideAndSeekGameRecord(
                group_chat_id=GROUP_ID,
                user_id=user_id,
                play_date=now.date(),
                state="selecting",
                candidates=[],
                entry_fee=1,
                win_reward=3,
                choice_deadline=now + timedelta(minutes=5),
            )
        )
    elif game_type == "memory_assessment":
        session.add(
            MemoryAssessmentGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                mode="single",
                state="answering",
                play_date=now.date(),
            )
        )
    elif game_type == "undercover":
        session.add(
            UndercoverSessionRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                state="signup",
                target_player_count=5,
            )
        )
    elif game_type == "blame_bomb":
        session.add(
            BlameGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                state="signup",
                creator_user_id=user_id,
                target_player_count=4,
                signup_deadline=now + timedelta(minutes=5),
            )
        )
    elif game_type == "number_bomb":
        session.add(
            NumberBombGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                state="signup",
                target_player_count=4,
                last_activity_at=now,
            )
        )
    elif game_type == "texas_holdem":
        session.add(
            TexasHoldemGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                creator_user_id=user_id,
                state="signup",
                buy_in=10,
                signup_deadline=now + timedelta(minutes=5),
                created_at=now,
            )
        )
    elif game_type == "never_have_i_ever":
        session.add(
            NeverHaveIEverGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                host_user_id=user_id,
                state="signup",
            )
        )
    elif game_type == "king_game":
        session.add(
            KingGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                host_user_id=user_id,
                state="signup",
            )
        )
    elif game_type == "liar_dice":
        session.add(
            LiarDiceGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                host_user_id=user_id,
                state="signup",
            )
        )
    elif game_type == "truth_trade":
        session.add(
            TruthTradeGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                host_user_id=user_id,
                state="signup",
            )
        )
    else:  # pragma: no cover - 新增玩法时这里会提醒补 seeder
        raise AssertionError(f"未覆盖的玩法类型: {game_type}，请补 _seed_active")


def _seed_memory_guild(session, now: datetime) -> None:
    session.add(
        MemoryGuildMatchRecord(
            group_chat_id=GROUP_ID,
            active_key="global",
            host_user_id=uuid4(),
            state="signup",
            planned_series_count=1,
        )
    )


def _seed_performance(session, now: datetime) -> None:
    session.add(
        PerformanceReservationRecord(
            owner_user_id=uuid4(),
            group_chat_id=GROUP_ID,
            title="闸门测试公演",
            introduction="仅用于互斥闸门测试",
            scheduled_at=now + timedelta(hours=1),
            event_date=now.date(),
            state="waiting",
            submitted_at=now,
        )
    )


@pytest.mark.parametrize("game_type", GROUP_GAME_TYPES)
def test_has_active_game_sees_every_group_game_type(game_type):
    repository, factory, now = _build()
    with factory.begin() as session:
        _seed_active(session, game_type, now)
    with repository._session() as session:
        assert repository._has_active_game(session, GROUP_ID) is True


@pytest.mark.parametrize("game_type", GROUP_GAME_TYPES)
def test_group_has_active_gameplay_sees_every_group_game_type(game_type):
    repository, factory, now = _build()
    with factory.begin() as session:
        _seed_active(session, game_type, now)
    with repository._session() as session:
        assert repository._group_has_active_gameplay(session, GROUP_ID) is True


def test_group_has_active_gameplay_counts_memory_guild_and_performance():
    repository, factory, now = _build()
    with factory.begin() as session:
        _seed_memory_guild(session, now)
    with repository._session() as session:
        assert repository._group_has_active_gameplay(session, GROUP_ID) is True

    repository, factory, now = _build()
    with factory.begin() as session:
        _seed_performance(session, now)
    with repository._session() as session:
        assert repository._group_has_active_gameplay(session, GROUP_ID) is True


def test_both_gates_ignore_finished_games():
    """已结束对局（active_key 已清 / state 已终态）不得再占位，防止过度拦截。"""
    repository, factory, now = _build()
    with factory.begin() as session:
        session.add(
            LiarDiceGameRecord(
                group_chat_id=GROUP_ID,
                active_key=None,
                host_user_id=uuid4(),
                state="completed",
            )
        )
        session.add(
            TruthTradeGameRecord(
                group_chat_id=GROUP_ID,
                active_key=None,
                host_user_id=uuid4(),
                state="finished",
            )
        )
        session.add(
            RedPacketRecord(
                group_chat_id=GROUP_ID,
                active_key=None,
                issuer_user_id=uuid4(),
                target_count=3,
                total_amount=30,
                state="finished",
                has_empty=False,
                created_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
    with repository._session() as session:
        assert repository._has_active_game(session, GROUP_ID) is False
        assert repository._group_has_active_gameplay(session, GROUP_ID) is False


def test_both_gates_see_nothing_in_an_idle_group():
    repository, factory, now = _build()
    del now
    with repository._session() as session:
        assert repository._has_active_game(session, GROUP_ID) is False
        assert repository._group_has_active_gameplay(session, GROUP_ID) is False


def test_liar_dice_blocks_memory_assessment_single():
    """大话骰子进行中不得开记忆考核（历史 bug：两局并存 → /继续 卡死在 conflict）。"""
    repository, factory, now = _build()
    with factory.begin() as session:
        session.add(
            LiarDiceGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                host_user_id=uuid4(),
                state="calling",
            )
        )
    result = repository.start_memory_assessment_single(HOST_PLATFORM_ID, now, GROUP_ID)
    assert result.status == "multiplayer_active"
    with factory() as session:
        assert session.query(MemoryAssessmentGameRecord).count() == 0


def test_memory_assessment_blocks_liar_dice():
    """反方向：记忆考核进行中不得开大话骰子（闸门对称性）。"""
    repository, factory, now = _build()
    with factory.begin() as session:
        session.add(
            MemoryAssessmentGameRecord(
                group_chat_id=GROUP_ID,
                active_key="global",
                mode="single",
                state="answering",
                play_date=now.date(),
            )
        )
    result = repository.start_liar_dice(HOST_PLATFORM_ID, now, GROUP_ID)
    assert result.status == "multiplayer_active"
    with factory() as session:
        assert session.query(LiarDiceGameRecord).count() == 0


def _service(repository):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.service import CoreService

    return CoreService(repository, GroupCommandHandler(repository))


def _say(service, factory, message_id, platform_id, content, now, **kwargs) -> str:
    from dzmm_bot.core.schema import OutboundRecord
    from dzmm_bot.runtime.contracts import InboundMessage

    kwargs.setdefault("chatroom_id", "group-main")
    service.receive_inbound(
        InboundMessage(message_id, platform_id, content, now, **kwargs)
    )
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


def _seed_conflict(session, now: datetime) -> None:
    """造出历史 bug 的现场：大话骰子（本人在局）+ 记忆考核 同时活跃。"""
    host_id = session.scalar(
        select(UserRecord.id).where(UserRecord.platform_id == HOST_PLATFORM_ID)
    )
    dice = LiarDiceGameRecord(
        group_chat_id=GROUP_ID,
        active_key="global",
        host_user_id=host_id,
        state="calling",
        round_number=1,
        current_seat=1,
    )
    session.add(dice)
    session.flush()
    session.add(
        LiarDicePlayerRecord(
            game_id=dice.id,
            user_id=host_id,
            state="active",
            seat_number=1,
            joined_at=now,
        )
    )
    session.add(
        MemoryAssessmentGameRecord(
            group_chat_id=GROUP_ID,
            active_key="global",
            mode="single",
            state="answering",
            play_date=now.date(),
        )
    )


def test_conflict_reply_lists_each_running_game_and_how_to_end_it():
    """冲突不再只回「请联系管理员」：要列出各局 + 各自收尾指令，用户能自己解开。"""
    repository, factory, now = _build()
    service = _service(repository)
    with factory.begin() as session:
        _seed_conflict(session, now)

    reply = _say(service, factory, "m-current-game", HOST_PLATFORM_ID, "/当前游戏", now)
    assert "检测到 2 局同时进行" in reply
    assert "大话骰子" in reply
    assert "记忆考核" in reply
    assert "第 1 轮" in reply
    assert "/结束游戏" in reply
    assert "请先给其中一局收尾，另一局会继续。" in reply

    continued = _say(
        service,
        factory,
        "m-continue",
        HOST_PLATFORM_ID,
        "/继续",
        now + timedelta(seconds=1),
    )
    assert "检测到 2 局同时进行" in continued

    left = _say(
        service,
        factory,
        "m-leave",
        HOST_PLATFORM_ID,
        "/退出",
        now + timedelta(seconds=2),
    )
    assert "检测到 2 局同时进行" in left
