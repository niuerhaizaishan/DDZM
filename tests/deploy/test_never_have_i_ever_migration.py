from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, JSON, MetaData, String, Table, Uuid, create_engine, inspect, select


ROOT = Path(__file__).resolve().parents[2]


def test_never_have_i_ever_migration_upgrades_revision_63(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'never-have-i-ever.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    groups = Table(
        "group_chats",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("enabled_game_types", JSON, nullable=False),
    )
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)
    group_id = UUID("11111111-1111-1111-1111-111111111111")
    with engine.begin() as connection:
        connection.execute(
            groups.insert().values(
                id=group_id,
                enabled_game_types=["number_bomb", "texas_holdem"],
            )
        )
    config = Config(str(ROOT / "alembic.ini"))

    command.stamp(config, "20260831_63")
    command.upgrade(config, "head")

    tables = set(inspect(engine).get_table_names())
    assert {
        "never_have_i_ever_settings",
        "never_have_i_ever_games",
        "never_have_i_ever_players",
        "never_have_i_ever_rounds",
        "never_have_i_ever_responses",
    } <= tables
    with engine.connect() as connection:
        enabled_game_types = connection.scalar(
            select(groups.c.enabled_game_types).where(groups.c.id == group_id)
        )
    assert enabled_game_types == [
        "number_bomb",
        "texas_holdem",
        "never_have_i_ever",
    ]

    command.downgrade(config, "20260831_63")
    tables = set(inspect(engine).get_table_names())
    assert "never_have_i_ever_games" not in tables
