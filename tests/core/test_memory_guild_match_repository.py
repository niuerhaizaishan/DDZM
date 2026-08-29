from datetime import UTC, datetime, timedelta
from random import Random

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    Base,
    MemoryGuildMatchRecord,
    MemoryGuildAnswerRecord,
    MemoryGuildRoundRecord,
    MemoryGuildSeriesRecord,
    MemoryGuildTeamRecord,
    PRIMARY_GROUP_CHAT_ID,
    RankRecord,
)


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def repository(session_factory, now) -> CoreRepository:
    repository = CoreRepository(session_factory, number_bomb_random=Random(1))
    repository.list_ranks()
    with session_factory.begin() as session:
        session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 1)
        ).multiplayer_game_limit = 999
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=memory-guild", now
    )
    for platform_id, name in (
        ("host", "主持人"),
        ("red-1", "G"),
        ("red-2", "彻"),
        ("red-3", "苏白"),
        ("blue-1", "玩家A"),
        ("blue-2", "玩家B"),
        ("blue-3", "玩家C"),
    ):
        repository.create_user(platform_id, name, now, 0)
    repository.upsert_direct_chats(
        [
            (platform_id, f"direct-{platform_id}")
            for platform_id in (
                "host",
                "red-1",
                "red-2",
                "red-3",
                "blue-1",
                "blue-2",
                "blue-3",
            )
        ],
        now,
    )
    return repository


def test_hired_employee_creates_match_without_consuming_daily_limit(repository, now):
    created = repository.start_memory_guild_match(
        "host", 3, now, PRIMARY_GROUP_CHAT_ID
    )

    assert created.status == "created"
    assert created.match_id is not None
    assert created.host_name == "主持人"
    assert created.planned_series_count == 3
    assert "🏆 记忆考核 · 公会赛" in created.public_message


def test_non_employee_and_invalid_series_count_cannot_create(repository, now):
    assert repository.start_memory_guild_match(
        "missing", 3, now, PRIMARY_GROUP_CHAT_ID
    ).status == "not_joined"
    assert repository.start_memory_guild_match(
        "host", 0, now, PRIMARY_GROUP_CHAT_ID
    ).status == "invalid_series_count"
    assert repository.start_memory_guild_match(
        "host", 21, now, PRIMARY_GROUP_CHAT_ID
    ).status == "invalid_series_count"


def test_host_configures_and_overwrites_team_names_and_rosters(repository, now):
    repository.start_memory_guild_match("host", 3, now, PRIMARY_GROUP_CHAT_ID)

    assert repository.set_memory_guild_team_name(
        "host", 1, "女仆公馆队", now, PRIMARY_GROUP_CHAT_ID
    ).status == "team_updated"
    renamed = repository.set_memory_guild_team_name(
        "host", 1, "新女仆公馆队", now, PRIMARY_GROUP_CHAT_ID
    )
    assert renamed.status == "team_updated"
    assert renamed.team1.name == "新女仆公馆队"
    roster = repository.set_memory_guild_roster(
        "host", 1, ("G", "彻", "苏白"), now, PRIMARY_GROUP_CHAT_ID
    )
    assert roster.status == "roster_updated"
    assert tuple(member.display_name for member in roster.team1.members) == (
        "G",
        "彻",
        "苏白",
    )
    overwritten = repository.set_memory_guild_roster(
        "host", 1, ("彻", "G"), now, PRIMARY_GROUP_CHAT_ID
    )
    assert tuple(member.display_name for member in overwritten.team1.members) == (
        "彻",
        "G",
    )


def test_team_configuration_rejects_unauthorized_and_invalid_members(repository, now):
    repository.start_memory_guild_match("host", 3, now, PRIMARY_GROUP_CHAT_ID)
    repository.set_memory_guild_team_name(
        "host", 1, "女仆公馆队", now, PRIMARY_GROUP_CHAT_ID
    )
    repository.set_memory_guild_team_name(
        "host", 2, "摸鱼事务所队", now, PRIMARY_GROUP_CHAT_ID
    )

    assert repository.set_memory_guild_team_name(
        "red-1", 1, "越权改名", now, PRIMARY_GROUP_CHAT_ID
    ).status == "host_only"
    assert repository.set_memory_guild_team_name(
        "host", 2, "女仆公馆队", now, PRIMARY_GROUP_CHAT_ID
    ).status == "duplicate_team_name"
    assert repository.set_memory_guild_roster(
        "host", 1, ("主持人",), now, PRIMARY_GROUP_CHAT_ID
    ).status == "host_cannot_play"
    assert repository.set_memory_guild_roster(
        "host", 1, ("不存在",), now, PRIMARY_GROUP_CHAT_ID
    ).status == "unknown_member"

    repository.set_memory_guild_roster(
        "host", 1, ("G", "彻"), now, PRIMARY_GROUP_CHAT_ID
    )
    assert repository.set_memory_guild_roster(
        "host", 2, ("G", "玩家A"), now, PRIMARY_GROUP_CHAT_ID
    ).status == "member_in_other_team"


def test_active_match_blocks_second_match_in_same_group(repository, now):
    assert repository.start_memory_guild_match(
        "host", 1, now, PRIMARY_GROUP_CHAT_ID
    ).status == "created"
    assert repository.start_memory_guild_match(
        "red-1", 1, now, PRIMARY_GROUP_CHAT_ID
    ).status == "already_active"


def test_existing_multiplayer_game_blocks_guild_match(repository, now):
    assert repository.start_number_bomb_game("host", now).status == "signup_started"

    result = repository.start_memory_guild_match(
        "red-1", 1, now, PRIMARY_GROUP_CHAT_ID
    )

    assert result.status == "multiplayer_active"


def test_active_summary_identifies_host_and_team_members(repository, now):
    repository.start_memory_guild_match("host", 1, now, PRIMARY_GROUP_CHAT_ID)
    repository.set_memory_guild_team_name(
        "host", 1, "女仆公馆队", now, PRIMARY_GROUP_CHAT_ID
    )
    repository.set_memory_guild_roster(
        "host", 1, ("G",), now, PRIMARY_GROUP_CHAT_ID
    )

    host = repository.active_gameplay_summary("host", now, PRIMARY_GROUP_CHAT_ID)
    member = repository.active_gameplay_summary("red-1", now, PRIMARY_GROUP_CHAT_ID)

    assert host.game_type == "memory_guild"
    assert host.actor_role == "host"
    assert "/队伍1 队名" in host.available_commands
    assert "/结束游戏" in host.available_commands
    assert member.game_type == "memory_guild"
    assert member.actor_role == "participant"


def test_only_host_can_end_match_and_admin_force_end_is_supported(repository, now):
    created = repository.start_memory_guild_match(
        "host", 1, now, PRIMARY_GROUP_CHAT_ID
    )

    assert repository.end_memory_guild_match(
        "red-1", now, PRIMARY_GROUP_CHAT_ID
    ).status == "host_only"
    assert repository.end_memory_guild_match(
        "host", now, PRIMARY_GROUP_CHAT_ID
    ).status == "forced_ended"
    assert repository.memory_guild_match_view(PRIMARY_GROUP_CHAT_ID) is None

    second = repository.start_memory_guild_match(
        "host", 1, now, PRIMARY_GROUP_CHAT_ID
    )
    assert second.status == "created"
    assert repository.force_end_gameplay(
        "memory_guild", second.match_id, now, PRIMARY_GROUP_CHAT_ID
    ) is True
    assert repository.memory_guild_match_view(PRIMARY_GROUP_CHAT_ID) is None


def _configure_match(
    repository,
    now,
    planned_series_count=2,
    group_chat_id=PRIMARY_GROUP_CHAT_ID,
):
    repository.start_memory_guild_match(
        "host", planned_series_count, now, group_chat_id
    )
    repository.set_memory_guild_team_name(
        "host", 1, "女仆公馆队", now, group_chat_id
    )
    repository.set_memory_guild_team_name(
        "host", 2, "摸鱼事务所队", now, group_chat_id
    )
    repository.set_memory_guild_roster(
        "host", 1, ("G", "彻", "苏白"), now, group_chat_id
    )
    repository.set_memory_guild_roster(
        "host", 2, ("玩家A", "玩家B", "玩家C"), now, group_chat_id
    )


def test_first_series_requires_complete_rosters(repository, now):
    repository.start_memory_guild_match("host", 2, now, PRIMARY_GROUP_CHAT_ID)
    repository.set_memory_guild_team_name(
        "host", 1, "女仆公馆队", now, PRIMARY_GROUP_CHAT_ID
    )
    repository.set_memory_guild_team_name(
        "host", 2, "摸鱼事务所队", now, PRIMARY_GROUP_CHAT_ID
    )
    repository.set_memory_guild_roster(
        "host", 1, ("G",), now, PRIMARY_GROUP_CHAT_ID
    )
    repository.set_memory_guild_roster(
        "host", 2, ("玩家A", "玩家B"), now, PRIMARY_GROUP_CHAT_ID
    )

    result = repository.create_memory_guild_series(
        "host", 1, 2, 3, now, PRIMARY_GROUP_CHAT_ID
    )

    assert result.status == "insufficient_roster"


def test_series_numbers_are_sequential_and_previous_must_be_settled(repository, now):
    _configure_match(repository, now)

    assert repository.create_memory_guild_series(
        "host", 2, 2, 3, now, PRIMARY_GROUP_CHAT_ID
    ).status == "invalid_sequence"
    assert repository.create_memory_guild_series(
        "host", 1, 2, 3, now, PRIMARY_GROUP_CHAT_ID
    ).status == "series_created"
    assert repository.create_memory_guild_series(
        "host", 2, 2, 3, now, PRIMARY_GROUP_CHAT_ID
    ).status == "previous_series_active"


def test_private_lineup_first_selection_locks_until_both_teams_ready(repository, now):
    _configure_match(repository, now)
    repository.create_memory_guild_series(
        "host", 1, 2, 3, now, PRIMARY_GROUP_CHAT_ID
    )

    candidates = repository.memory_guild_lineup_candidates("red-1")
    assert len(candidates) == 1
    assert candidates[0].group_chat_id == PRIMARY_GROUP_CHAT_ID

    first = repository.select_memory_guild_player(
        "red-1", "G", now, PRIMARY_GROUP_CHAT_ID
    )
    assert first.status == "lineup_recorded"
    assert first.public_message is None
    assert repository.select_memory_guild_player(
        "red-2", "彻", now, PRIMARY_GROUP_CHAT_ID
    ).status == "lineup_locked"

    second = repository.select_memory_guild_player(
        "blue-2", "玩家A", now, PRIMARY_GROUP_CHAT_ID
    )
    assert second.status == "series_ready"
    assert "G" in second.public_message
    assert "玩家A" in second.public_message
    assert "请主持人发送 /开始对战" in second.public_message


def test_lineup_must_select_a_member_of_the_actors_team(repository, now):
    _configure_match(repository, now)
    repository.create_memory_guild_series(
        "host", 1, 2, 3, now, PRIMARY_GROUP_CHAT_ID
    )

    assert repository.select_memory_guild_player(
        "red-1", "玩家A", now, PRIMARY_GROUP_CHAT_ID
    ).status == "invalid_player"
    assert repository.select_memory_guild_player(
        "host", "G", now, PRIMARY_GROUP_CHAT_ID
    ).status == "not_team_member"


def test_regular_series_rejects_a_player_used_in_an_earlier_series(
    repository, session_factory, now
):
    _configure_match(repository, now, planned_series_count=2)
    repository.create_memory_guild_series(
        "host", 1, 1, 1, now, PRIMARY_GROUP_CHAT_ID
    )
    repository.select_memory_guild_player("red-1", "G", now, PRIMARY_GROUP_CHAT_ID)
    repository.select_memory_guild_player(
        "blue-1", "玩家A", now, PRIMARY_GROUP_CHAT_ID
    )
    with session_factory.begin() as session:
        match = session.scalar(select(MemoryGuildMatchRecord))
        series = session.scalar(select(MemoryGuildSeriesRecord))
        teams = list(
            session.scalars(
                select(MemoryGuildTeamRecord).order_by(MemoryGuildTeamRecord.slot)
            )
        )
        series.state = "finished"
        series.winner_team_id = teams[0].id
        series.finished_at = now
        teams[0].series_wins = 1
        match.state = "waiting_series"

    assert repository.create_memory_guild_series(
        "host", 2, 1, 1, now, PRIMARY_GROUP_CHAT_ID
    ).status == "series_created"
    assert repository.select_memory_guild_player(
        "red-2", "G", now, PRIMARY_GROUP_CHAT_ID
    ).status == "player_already_used"


def test_private_lineup_candidates_disambiguate_multiple_groups(repository, now):
    second_group = repository.create_group_chat(
        "第二群",
        "https://www.aikda.com/chat?c=memory-guild-second",
        True,
        True,
        False,
        False,
        now,
        enabled_game_types=("memory_assessment",),
    )
    for group_chat_id in (PRIMARY_GROUP_CHAT_ID, second_group.id):
        _configure_match(repository, now, group_chat_id=group_chat_id)
        repository.create_memory_guild_series(
            "host", 1, 2, 3, now, group_chat_id
        )

    candidates = repository.memory_guild_lineup_candidates("red-1")

    assert len(candidates) == 2
    assert {candidate.group_chat_id for candidate in candidates} == {
        PRIMARY_GROUP_CHAT_ID,
        second_group.id,
    }
    assert repository.select_memory_guild_player(
        "red-1", "G", now
    ).status == "ambiguous_group"


def test_regular_series_rejects_used_player_but_overtime_allows_reuse(
    repository, session_factory, now
):
    _configure_match(repository, now, planned_series_count=1)
    repository.create_memory_guild_series(
        "host", 1, 1, 1, now, PRIMARY_GROUP_CHAT_ID
    )
    repository.select_memory_guild_player("red-1", "G", now, PRIMARY_GROUP_CHAT_ID)
    repository.select_memory_guild_player(
        "blue-1", "玩家A", now, PRIMARY_GROUP_CHAT_ID
    )
    with session_factory.begin() as session:
        match = session.scalar(select(MemoryGuildMatchRecord))
        series = session.scalar(select(MemoryGuildSeriesRecord))
        teams = list(
            session.scalars(
                select(MemoryGuildTeamRecord).order_by(MemoryGuildTeamRecord.slot)
            )
        )
        series.state = "finished"
        series.winner_team_id = teams[0].id
        series.finished_at = now
        teams[0].series_wins = 1
        teams[1].series_wins = 1
        match.state = "waiting_series"

    assert repository.create_memory_guild_series(
        "host", 2, 1, 1, now, PRIMARY_GROUP_CHAT_ID
    ).status == "series_created"
    assert repository.select_memory_guild_player(
        "red-2", "G", now, PRIMARY_GROUP_CHAT_ID
    ).status == "lineup_recorded"
    assert repository.select_memory_guild_player(
        "blue-2", "玩家A", now, PRIMARY_GROUP_CHAT_ID
    ).status == "series_ready"


def _ready_series(repository, now, planned_series_count=1, win_target=2, rounds=3):
    _configure_match(repository, now, planned_series_count=planned_series_count)
    repository.create_memory_guild_series(
        "host", 1, win_target, rounds, now, PRIMARY_GROUP_CHAT_ID
    )
    repository.select_memory_guild_player("red-1", "G", now, PRIMARY_GROUP_CHAT_ID)
    repository.select_memory_guild_player(
        "blue-1", "玩家A", now, PRIMARY_GROUP_CHAT_ID
    )


def _recall_guild_round(repository, started, now):
    outbound = repository.enqueue_system_outbound(
        started.public_message,
        recall_after_seconds=started.display_seconds,
        memory_guild_round_id=started.round_id,
        group_chat_id=PRIMARY_GROUP_CHAT_ID,
        destination_chatroom_id="memory-guild",
    )
    leased = repository.claim_outbound("worker-a", now, 30)
    assert repository.confirm_sent(
        outbound.id, "worker-a", leased.lease_token, "platform-question", now
    )
    recalled_at = now + timedelta(seconds=started.display_seconds)
    recall = repository.claim_outbound_recall("worker-a", recalled_at, 30)
    assert repository.confirm_outbound_recalled(
        outbound.id,
        "worker-a",
        recall.recall_lease_token,
        recalled_at,
    )
    return recalled_at


def test_only_host_starts_level_five_round_and_recall_opens_answering(
    repository, session_factory, now
):
    _ready_series(repository, now)

    assert repository.start_memory_guild_round(
        "red-1", now, PRIMARY_GROUP_CHAT_ID
    ).status == "host_only"
    started = repository.start_memory_guild_round(
        "host", now, PRIMARY_GROUP_CHAT_ID
    )
    assert started.status == "round_started"
    assert started.level == 5
    assert started.display_seconds == repository.get_memory_assessment_settings().duel_recall_seconds
    assert started.answer == started.public_message

    recalled_at = _recall_guild_round(repository, started, now)
    with session_factory() as session:
        round_record = session.get(MemoryGuildRoundRecord, started.round_id)
        assert round_record.state == "answering"
        assert round_record.answer_deadline == recalled_at + timedelta(
            minutes=repository.get_memory_assessment_settings().duel_answer_timeout_minutes
        )


def test_wrong_answers_can_retry_and_first_correct_answer_wins(
    repository, session_factory, now
):
    _ready_series(repository, now, win_target=2, rounds=3)
    started = repository.start_memory_guild_round(
        "host", now, PRIMARY_GROUP_CHAT_ID
    )
    recalled_at = _recall_guild_round(repository, started, now)

    assert repository.answer_memory_guild_round(
        "red-2", "outsider", started.answer, recalled_at, PRIMARY_GROUP_CHAT_ID
    ).status == "not_current_player"
    assert repository.answer_memory_guild_round(
        "red-1", "wrong", "错误", recalled_at, PRIMARY_GROUP_CHAT_ID
    ).status == "incorrect"
    won = repository.answer_memory_guild_round(
        "red-1", "correct", started.answer, recalled_at, PRIMARY_GROUP_CHAT_ID
    )
    assert won.status == "round_won"
    assert "G 赢得本局" in won.public_message
    assert repository.answer_memory_guild_round(
        "blue-1", "late", started.answer, recalled_at, PRIMARY_GROUP_CHAT_ID
    ).status == "round_closed"
    with session_factory() as session:
        answers = list(session.scalars(select(MemoryGuildAnswerRecord)))
        assert [(answer.answer, answer.correct) for answer in answers] == [
            ("错误", False),
            (started.answer, True),
        ]


def test_answer_timeout_records_draw_without_incrementing_score(repository, now):
    _ready_series(repository, now)
    started = repository.start_memory_guild_round(
        "host", now, PRIMARY_GROUP_CHAT_ID
    )
    recalled_at = _recall_guild_round(repository, started, now)
    deadline = recalled_at + timedelta(
        minutes=repository.get_memory_assessment_settings().duel_answer_timeout_minutes
    )

    results = repository.run_memory_guild_jobs(deadline)

    assert len(results) == 1
    assert results[0].status == "round_drawn"
    assert "本局平局" in results[0].public_message
    assert repository.start_memory_guild_round(
        "host", deadline, PRIMARY_GROUP_CHAT_ID
    ).status == "round_started"


def test_winning_series_finishes_match_after_all_planned_series(repository, now):
    _ready_series(repository, now, planned_series_count=1, win_target=1, rounds=1)
    started = repository.start_memory_guild_round(
        "host", now, PRIMARY_GROUP_CHAT_ID
    )
    recalled_at = _recall_guild_round(repository, started, now)

    finished = repository.answer_memory_guild_round(
        "red-1", "winner", started.answer, recalled_at, PRIMARY_GROUP_CHAT_ID
    )

    assert finished.status == "match_finished"
    assert "🏆 公会赛结束" in finished.public_message
    assert "女仆公馆队" in finished.public_message
    assert repository.memory_guild_match_view(PRIMARY_GROUP_CHAT_ID) is None

    items, total = repository.list_memory_guild_history(1, 20)
    detail = repository.memory_guild_history_detail(finished.match_id)
    assert total == 1
    assert items[0]["teams"][0]["name"] == "女仆公馆队"
    assert detail["series"][0]["rounds"][0]["result"] == "won"
    assert detail["series"][0]["rounds"][0]["answers"][0]["correct"] is True
