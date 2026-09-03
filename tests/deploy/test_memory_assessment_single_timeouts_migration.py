from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_memory_assessment_single_timeouts_migration_upgrades_revision_64(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'memory-timeouts.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "memory_assessment_settings",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))

    command.stamp(config, "20260831_64")
    command.upgrade(config, "head")

    columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("memory_assessment_settings")
    }
    assert columns["single_answer_timeout_seconds"]["nullable"] is False
    assert columns["single_decision_timeout_seconds"]["nullable"] is False
