from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Boolean, Column, MetaData, String, Table, Text, create_engine, inspect, select


ROOT = Path(__file__).resolve().parents[2]


def test_ai_trigger_prefixes_migration_defaults_existing_settings(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'ai-trigger-prefixes.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    settings = Table(
        "ai_assistant_settings",
        metadata,
        Column("id", String, primary_key=True),
        Column("enabled", Boolean, nullable=False),
        Column("persona", Text, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            settings.insert().values(id="1", enabled=True, persona="总监事")
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260819_49")

    command.upgrade(config, "head")

    reflected = Table("ai_assistant_settings", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        prefixes = connection.scalar(select(reflected.c.trigger_prefixes))
    assert prefixes == ["@总监事"]
    assert {
        column["name"]: column
        for column in inspect(engine).get_columns("ai_assistant_settings")
    }["trigger_prefixes"]["nullable"] is False

    command.downgrade(config, "20260819_49")
    assert "trigger_prefixes" not in {
        column["name"]
        for column in inspect(engine).get_columns("ai_assistant_settings")
    }
