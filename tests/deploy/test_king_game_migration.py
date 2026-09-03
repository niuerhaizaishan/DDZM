from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, JSON, MetaData, Table, Uuid, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_king_game_migration_creates_persistent_game_tables(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'king-game.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "group_chats",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("enabled_game_types", JSON, nullable=False),
    )
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))

    command.stamp(config, "20260901_67")
    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert {
        "king_game_settings",
        "king_games",
        "king_game_players",
        "king_game_rounds",
    } <= set(inspector.get_table_names())
