from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_platform_nickname_migration_adds_and_removes_cached_profile_fields(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'platform-nickname.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "users",
        metadata,
        Column("platform_id", String(255), primary_key=True),
        Column("display_name", String(64), nullable=False),
    )
    metadata.create_all(engine)
    command.stamp(config, "20260907_70")

    command.upgrade(config, "20260907_71")

    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert {
        "platform_nickname",
        "platform_nickname_synced_at",
        "platform_nickname_attempted_at",
    } <= columns

    command.downgrade(config, "20260907_70")

    columns = {column["name"] for column in inspect(engine).get_columns("users")}
    assert "platform_nickname" not in columns
