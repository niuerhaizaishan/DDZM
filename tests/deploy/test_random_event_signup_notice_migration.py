from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_random_event_signup_notice_migration_upgrades_existing_revision_62(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'random-event-notice.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("outbound_messages", metadata, Column("id", Uuid, primary_key=True))
    Table("random_events", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260830_62")
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "signup_notice_outbound_id" in {
        column["name"] for column in inspector.get_columns("random_events")
    }
    assert "ix_random_events_signup_notice_outbound_id" in {
        index["name"] for index in inspector.get_indexes("random_events")
    }
    assert any(
        foreign_key["referred_table"] == "outbound_messages"
        and foreign_key["constrained_columns"] == ["signup_notice_outbound_id"]
        for foreign_key in inspector.get_foreign_keys("random_events")
    )

    command.downgrade(config, "20260830_62")

    inspector = inspect(engine)
    assert "signup_notice_outbound_id" not in {
        column["name"] for column in inspector.get_columns("random_events")
    }
