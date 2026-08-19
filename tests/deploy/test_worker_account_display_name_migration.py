from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_worker_account_display_name_migration_round_trips(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'worker-account-name.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "worker_instances",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("worker_id", String(255), nullable=False),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260818_47")

    command.upgrade(config, "head")

    assert "account_display_name" in {
        column["name"]
        for column in inspect(engine).get_columns("worker_instances")
    }

    command.downgrade(config, "20260818_47")

    assert "account_display_name" not in {
        column["name"]
        for column in inspect(engine).get_columns("worker_instances")
    }
