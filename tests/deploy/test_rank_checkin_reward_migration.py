from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, String, Table, Uuid, create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


def test_rank_checkin_reward_migration_backfills_current_global_reward(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'rank-checkin-rewards.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    engine = create_engine(database_url)
    metadata = MetaData()
    ranks = Table(
        "ranks",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("name", String(64), nullable=False),
    )
    settings = Table(
        "game_settings",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("checkin_reward", Integer, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(settings.insert(), {"id": 1, "checkin_reward": 5})
        connection.execute(ranks.insert(), [{"id": uuid4(), "name": "实习生"}, {"id": uuid4(), "name": "总监"}])
    command.stamp(config, "20260903_69")

    command.upgrade(config, "20260907_70")

    assert "checkin_reward" in {
        column["name"] for column in inspect(engine).get_columns("ranks")
    }
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT checkin_reward FROM ranks ORDER BY name")
        ).scalars().all() == [5, 5]

    command.downgrade(config, "20260903_69")

    assert "checkin_reward" not in {
        column["name"] for column in inspect(engine).get_columns("ranks")
    }
