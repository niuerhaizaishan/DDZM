from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Column,
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
    "employee_birthdays",
    "birthday_greetings",
    "birthday_previews",
    "birthday_tips",
    "birthday_settings",
}

BASE_REVISION = "20260915_75"
NOW = datetime(2026, 9, 17, 9, 0, tzinfo=timezone.utc)


def migrated_engine(tmp_path, monkeypatch, *, existing_group_id=None):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'birthday.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("inbound_messages", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)
    if existing_group_id is not None:
        groups = Table("group_chats", MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(groups.insert().values(id=existing_group_id))

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, BASE_REVISION)
    command.upgrade(config, "head")
    return engine, config


def uid() -> str:
    """自动加载出来的列是 SQLite 的 CHAR(32)，塞字符串最省事。"""
    return str(uuid4())


def table(engine, name):
    return Table(name, MetaData(), autoload_with=engine)


def test_birthday_migration_creates_every_table(tmp_path, monkeypatch):
    engine, _ = migrated_engine(tmp_path, monkeypatch)

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_birthday_migration_adds_the_group_switch_for_existing_rows(
    tmp_path, monkeypatch
):
    """已有群必须被补成「开启」，否则升级后三个群一个都收不到祝福。"""
    group_id = "00000000-0000-0000-0000-0000000000aa"
    engine, _ = migrated_engine(tmp_path, monkeypatch, existing_group_id=group_id)

    groups = table(engine, "group_chats")
    with engine.connect() as connection:
        row = connection.execute(select(groups)).mappings().one()

    assert row["birthdays_enabled"] in (True, 1)


def test_birthday_migration_adds_the_unique_anchors(tmp_path, monkeypatch):
    """唯一锚点是幂等的命根子：同一个员工同一年只能被祝福一次。"""
    engine, _ = migrated_engine(tmp_path, monkeypatch)
    birthdays = table(engine, "employee_birthdays")
    greetings = table(engine, "birthday_greetings")
    previews = table(engine, "birthday_previews")
    tips = table(engine, "birthday_tips")

    user_id, other_id, greeting_id = uid(), uid(), uid()
    with engine.begin() as connection:
        connection.execute(
            birthdays.insert().values(
                id=uid(),
                user_id=user_id,
                month=5,
                day=20,
                visibility="public",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        connection.execute(
            greetings.insert().values(
                id=greeting_id,
                user_id=user_id,
                greet_year=2026,
                greeted_at=NOW,
                gift_amount=20,
                lottery_tickets=0,
                tips_count=0,
                tips_total=0,
                status="greeted",
            )
        )
        connection.execute(
            previews.insert().values(
                id=uid(),
                user_id=user_id,
                preview_year=2026,
                previewed_at=NOW,
            )
        )
        connection.execute(
            tips.insert().values(
                id=uid(),
                greeting_id=greeting_id,
                from_user_id=other_id,
                amount=10,
                inbound_message_id=uid(),
                created_at=NOW,
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                birthdays.insert().values(
                    id=uid(),
                    user_id=user_id,
                    month=6,
                    day=1,
                    visibility="public",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                greetings.insert().values(
                    id=uid(),
                    user_id=user_id,
                    greet_year=2026,
                    greeted_at=NOW,
                    gift_amount=20,
                    lottery_tickets=0,
                    tips_count=0,
                    tips_total=0,
                    status="greeted",
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                previews.insert().values(
                    id=uid(),
                    user_id=user_id,
                    preview_year=2026,
                    previewed_at=NOW,
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                tips.insert().values(
                    id=uid(),
                    greeting_id=greeting_id,
                    from_user_id=other_id,
                    amount=5,
                    inbound_message_id=uid(),
                    created_at=NOW,
                )
            )


def test_birthday_migration_lays_out_the_settings_columns(tmp_path, monkeypatch):
    engine, _ = migrated_engine(tmp_path, monkeypatch)

    columns = {
        column["name"] for column in inspect(engine).get_columns("birthday_settings")
    }

    assert {
        "id",
        "enabled",
        "greet_time",
        "preview_enabled",
        "preview_time",
        "gift_amount",
        "same_day_backfill",
        "edit_limit_per_year",
        "checkin_multiplier",
        "shop_discount_percent",
        "lottery_free_tickets",
        "event_reward_bonus_percent",
        "tips_enabled",
        "tip_max_amount",
        "tip_window_minutes",
        "anniversary_enabled",
        "greet_template",
        "preview_template",
        "tips_summary_template",
    } == columns


def test_birthday_migration_downgrades_cleanly(tmp_path, monkeypatch):
    engine, config = migrated_engine(tmp_path, monkeypatch)

    command.downgrade(config, BASE_REVISION)

    tables = set(inspect(engine).get_table_names())
    assert EXPECTED_TABLES & tables == set()
    group_columns = {
        column["name"] for column in inspect(engine).get_columns("group_chats")
    }
    assert "birthdays_enabled" not in group_columns


def test_birthday_migration_round_trips_after_downgrade(tmp_path, monkeypatch):
    engine, config = migrated_engine(tmp_path, monkeypatch)

    command.downgrade(config, BASE_REVISION)
    command.upgrade(config, "head")

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM birthday_settings")) == 0


def test_birthday_migration_tracks_the_yearly_edit_quota(tmp_path, monkeypatch):
    """「一年只能改几次」需要一个计数器，否则配额设成 0 或 2 都落不了地。"""
    engine, _ = migrated_engine(tmp_path, monkeypatch)

    columns = {
        column["name"] for column in inspect(engine).get_columns("employee_birthdays")
    }

    assert {"edit_count", "edit_count_year"} <= columns
