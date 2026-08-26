from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


def test_migration_57_adds_performance_defaults(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'performance.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("inbound_messages", metadata, Column("id", Uuid, primary_key=True))
    Table(
        "outbound_messages",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("status", String(32), nullable=False),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260826_56")

    command.upgrade(config, "20260826_57")

    inspector = inspect(engine)
    assert {
        "performance_settings",
        "performance_reservations",
        "performance_participants",
        "performance_drafts",
        "performance_extension_requests",
        "performance_messages",
        "performance_tips",
    } <= set(inspector.get_table_names())
    assert "performances_enabled" in {
        column["name"] for column in inspector.get_columns("group_chats")
    }
    assert {"deferred_by_performance_id", "performance_defer_key"} <= {
        column["name"] for column in inspector.get_columns("outbound_messages")
    }
    with engine.connect() as connection:
        maximum_duration = connection.execute(
            text(
                "SELECT maximum_duration_minutes FROM performance_settings WHERE id = 1"
            )
        ).scalar_one()
    assert maximum_duration == 360

    command.downgrade(config, "20260826_56")
    inspector = inspect(engine)
    assert "performance_settings" not in inspector.get_table_names()
    assert "performances_enabled" not in {
        column["name"] for column in inspector.get_columns("group_chats")
    }


def test_migration_57_skips_incomplete_legacy_test_schema(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'legacy-partial.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("unrelated_legacy_table", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260826_56")

    command.upgrade(config, "20260826_57")

    inspector = inspect(engine)
    assert "performance_settings" not in inspector.get_table_names()

    command.downgrade(config, "20260826_56")
