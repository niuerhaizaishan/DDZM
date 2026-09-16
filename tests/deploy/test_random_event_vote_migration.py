from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Column,
    Integer,
    JSON,
    MetaData,
    Table,
    Uuid,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "random_event_polls",
    "random_event_poll_candidates",
    "random_event_poll_votes",
}

SETTINGS_COLUMNS = {
    "vote_enabled",
    "vote_close_offset_minutes",
    "vote_broadcast_interval_minutes",
    "vote_random_candidates",
    "vote_ad_slot_limit",
    "vote_fallback_minutes",
    "vote_allow_change",
}

POLL_ID = "a" * 32
SCHEDULE_ID = "1" * 32
USER_ID = "b" * 32
CANDIDATE_ID = "c" * 32

VOTE_INSERT = text(
    "INSERT INTO random_event_poll_votes "
    "(id, poll_id, user_id, candidate_id, created_at, updated_at) "
    "VALUES (:id, :poll, :user, :candidate, :created, :updated)"
)


def migrated_engine(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'random-event-vote.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("random_event_scenes", metadata, Column("id", Uuid, primary_key=True))
    Table(
        "random_event_scene_openings", metadata, Column("id", Uuid, primary_key=True)
    )
    Table("random_event_schedules", metadata, Column("id", Uuid, primary_key=True))
    Table(
        "random_event_settings",
        metadata,
        Column("id", Integer, primary_key=True),
        # 后续的放行清单迁移会读写这两列，桩表必须带上（这里只为读，允许为空）
        Column("signup_allowed_commands", JSON),
        Column("in_progress_allowed_commands", JSON),
    )
    metadata.create_all(engine)

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260915_75")
    command.upgrade(config, "head")
    return engine


def _seed_poll(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO random_event_schedules (id) VALUES (:id)"),
            {"id": SCHEDULE_ID},
        )
        connection.execute(
            text("INSERT INTO users (id) VALUES (:id)"),
            {"id": USER_ID},
        )
        connection.execute(
            text(
                "INSERT INTO random_event_polls "
                "(id, target_schedule_id, status, opened_at, closes_at, created_at) "
                "VALUES (:id, :schedule, 'open', :opened, :closes, :opened)"
            ),
            {
                "id": POLL_ID,
                "schedule": SCHEDULE_ID,
                "opened": "2026-09-15 16:20:00",
                "closes": "2026-09-15 19:50:00",
            },
        )
        connection.execute(
            text(
                "INSERT INTO random_event_poll_candidates "
                "(id, poll_id, position, source, vacant, created_at) "
                "VALUES (:id, :poll, 4, 'ad_slot', 0, :opened)"
            ),
            {
                "id": CANDIDATE_ID,
                "poll": POLL_ID,
                "opened": "2026-09-15 16:20:00",
            },
        )


def test_random_event_vote_migration_creates_tables(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_random_event_vote_migration_adds_settings_columns(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)
    inspector = inspect(engine)

    assert SETTINGS_COLUMNS <= {
        column["name"] for column in inspector.get_columns("random_event_settings")
    }

    with engine.begin() as connection:
        connection.execute(text("INSERT INTO random_event_settings (id) VALUES (1)"))
    settings = Table("random_event_settings", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        row = connection.execute(select(settings)).mappings().one()

    assert row["vote_enabled"] is True
    assert row["vote_close_offset_minutes"] == 10
    assert row["vote_broadcast_interval_minutes"] == 30
    assert row["vote_random_candidates"] == 3
    assert row["vote_ad_slot_limit"] == 1
    assert row["vote_fallback_minutes"] == 30
    assert row["vote_allow_change"] is True


def test_random_event_vote_migration_is_global(tmp_path, monkeypatch):
    """全公司一份投票：三张表都不带 group_chat_id，群信息走目标场次。"""
    engine = migrated_engine(tmp_path, monkeypatch)
    inspector = inspect(engine)

    for table in EXPECTED_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "group_chat_id" not in columns, table


def test_random_event_vote_migration_allows_only_one_vote_per_employee(
    tmp_path, monkeypatch
):
    engine = migrated_engine(tmp_path, monkeypatch)
    _seed_poll(engine)
    values = {
        "id": "d" * 32,
        "poll": POLL_ID,
        "user": USER_ID,
        "candidate": CANDIDATE_ID,
        "created": "2026-09-15 17:00:00",
        "updated": "2026-09-15 17:00:00",
    }

    with engine.begin() as connection:
        connection.execute(VOTE_INSERT, values)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(VOTE_INSERT, {**values, "id": "e" * 32})


def test_random_event_vote_migration_keeps_one_poll_per_schedule(
    tmp_path, monkeypatch
):
    """一个目标场次只能有一份投票。"""
    engine = migrated_engine(tmp_path, monkeypatch)
    _seed_poll(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO random_event_polls "
                    "(id, target_schedule_id, status, opened_at, closes_at, created_at) "
                    "VALUES (:id, :schedule, 'open', :opened, :closes, :opened)"
                ),
                {
                    "id": "f" * 32,
                    "schedule": SCHEDULE_ID,
                    "opened": "2026-09-15 16:20:00",
                    "closes": "2026-09-15 19:50:00",
                },
            )


def test_random_event_vote_migration_downgrades_cleanly(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)
    config = Config(str(ROOT / "alembic.ini"))

    command.downgrade(config, "20260915_75")

    inspector = inspect(engine)
    remaining = set(inspector.get_table_names())
    assert not (EXPECTED_TABLES & remaining)
    assert not (
        SETTINGS_COLUMNS
        & {column["name"] for column in inspector.get_columns("random_event_settings")}
    )
