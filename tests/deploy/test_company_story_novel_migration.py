from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_company_story_novel_migration_adds_nullable_setting_column(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'company-story-novel.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("game_settings", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260907_71")

    command.upgrade(config, "head")

    column = next(
        item
        for item in inspect(engine).get_columns("game_settings")
        if item["name"] == "company_story_novel_url"
    )
    assert column["nullable"] is True

    command.downgrade(config, "20260907_71")
    assert "company_story_novel_url" not in {
        item["name"] for item in inspect(engine).get_columns("game_settings")
    }
