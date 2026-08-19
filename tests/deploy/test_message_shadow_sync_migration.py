from pathlib import Path
from datetime import datetime
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, DateTime, MetaData, String, Table, Uuid, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_message_shadow_sync_migration_round_trips_runtime_columns(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'message-shadow-sync.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    runtime = Table(
        "group_chat_runtime_states",
        metadata,
        Column("group_chat_id", Uuid, primary_key=True),
        Column("connection_state", String(16), nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            runtime.insert().values(
                group_chat_id=uuid4(),
                connection_state="connected",
                updated_at=datetime(2026, 8, 19, 12),
            )
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260819_49")

    command.upgrade(config, "head")

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("group_chat_runtime_states")
    }
    assert {
        "shadow_sync_state",
        "shadow_cursor_at",
        "shadow_cursor_message_id",
        "shadow_last_attempt_at",
        "shadow_last_success_at",
        "shadow_next_retry_at",
        "shadow_failure_count",
        "shadow_error_summary",
    } <= columns.keys()
    assert columns["shadow_sync_state"]["nullable"] is False
    assert columns["shadow_failure_count"]["nullable"] is False

    command.downgrade(config, "20260819_49")

    remaining = {
        column["name"]
        for column in inspect(engine).get_columns("group_chat_runtime_states")
    }
    assert "shadow_sync_state" not in remaining
    assert "shadow_cursor_at" not in remaining
