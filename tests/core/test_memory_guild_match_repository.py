from datetime import UTC, datetime
from random import Random

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, PRIMARY_GROUP_CHAT_ID, RankRecord


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
    assert host.available_commands == ("/结束游戏",)
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
