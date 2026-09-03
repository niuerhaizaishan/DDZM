from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, select


ROOT = Path(__file__).resolve().parents[2]


def test_random_event_global_completion_reward_migration_defaults_existing_settings(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'random-event-reward.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    settings = Table(
        "random_event_settings",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(settings.insert().values(id=1))
    config = Config(str(ROOT / "alembic.ini"))

    command.stamp(config, "20260903_68")
    command.upgrade(config, "head")

    assert "global_completion_reward" in {
        column["name"] for column in inspect(engine).get_columns("random_event_settings")
    }
    upgraded_settings = Table("random_event_settings", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        assert connection.scalar(
            select(upgraded_settings.c.global_completion_reward)
        ) == 6
