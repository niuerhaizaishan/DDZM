from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    Column,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    inspect,
    select,
)


ROOT = Path(__file__).resolve().parents[2]


def test_group_game_types_migration_enables_every_game_for_existing_groups(
    tmp_path, monkeypatch
):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'group-game-types.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    groups = Table(
        "group_chats",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("name", String(64), nullable=False),
        Column("games_enabled", Boolean, nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            groups.insert().values(id=uuid4(), name="现有群", games_enabled=True)
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260819_48")

    command.upgrade(config, "head")

    reflected = Table("group_chats", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        enabled = connection.scalar(select(reflected.c.enabled_game_types))
    assert enabled == [
        "red_packet",
        "hide_and_seek",
        "memory_assessment",
        "undercover",
        "blame_bomb",
        "number_bomb",
        "texas_holdem",
    ]
    assert inspect(engine).get_columns("group_chats")[-1]["nullable"] is False

    command.downgrade(config, "20260819_48")

    assert "enabled_game_types" not in {
        column["name"] for column in inspect(engine).get_columns("group_chats")
    }
