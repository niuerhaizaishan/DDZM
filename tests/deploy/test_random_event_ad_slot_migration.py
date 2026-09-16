from pathlib import Path

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
)


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "random_event_ad_slots",
    "random_event_ad_slot_drafts",
}


def migrated_engine(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'event-ad-slot.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    # 前置表：广告卡两张表的外键指向它们
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("items", metadata, Column("id", Uuid, primary_key=True))
    Table("random_event_scenes", metadata, Column("id", Uuid, primary_key=True))
    Table("random_event_settings", metadata, Column("id", Integer, primary_key=True),
          Column("signup_allowed_commands", JSON),
          Column("in_progress_allowed_commands", JSON))
    metadata.create_all(engine)

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260915_77")
    command.upgrade(config, "head")
    return engine


def test_ad_slot_migration_creates_tables(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_ad_slot_migration_links_author_work_and_poll(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)
    inspector = inspect(engine)

    columns = {
        column["name"] for column in inspector.get_columns("random_event_ad_slots")
    }
    assert {
        "user_id",
        "scene_id",
        "item_id",
        "poll_id",
        "candidate_id",
        "status",
        "created_at",
    } <= columns

    draft_columns = {
        column["name"]
        for column in inspector.get_columns("random_event_ad_slot_drafts")
    }
    assert {
        "user_id",
        "item_id",
        "poll_id",
        "current_step",
        "scene_id",
        "expires_at",
    } <= draft_columns


def test_ad_slot_migration_keeps_one_draft_per_author(tmp_path, monkeypatch):
    """一人一份向导草稿：靠 user_id 唯一约束保证（SQLite 反射拿不到自动索引，直接试插）。"""
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    import pytest

    engine = migrated_engine(tmp_path, monkeypatch)
    statement = text(
        "INSERT INTO random_event_ad_slot_drafts "
        "(id, user_id, item_id, poll_id, current_step, created_at, updated_at, "
        "last_activity_at, expires_at) "
        "VALUES (:id, :user, :item, :poll, 'pick_event', :at, :at, :at, :at)"
    )
    values = {
        "id": "a" * 32,
        "user": "b" * 32,
        "item": "c" * 32,
        "poll": "d" * 32,
        "at": "2026-09-15 16:20:00",
    }

    with engine.begin() as connection:
        connection.execute(statement, values)

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(statement, {**values, "id": "e" * 32})


def test_ad_slot_migration_downgrades_cleanly(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)
    config = Config(str(ROOT / "alembic.ini"))

    command.downgrade(config, "20260915_77")

    remaining = set(inspect(engine).get_table_names())
    assert not (EXPECTED_TABLES & remaining)


def test_event_ad_slot_item_is_defined():
    """商品目录由 `_ensure_shop_catalog` 自动补种，这里只钉住定义本身。"""
    from dzmm_bot.core.shop_cards import item_by_key

    item = item_by_key("event_ad_slot")

    assert item.name == "事件广告卡"
    assert item.effect_type == "event_ad_slot"
    assert item.price > 0
    assert item.minimum_rank_order is None
