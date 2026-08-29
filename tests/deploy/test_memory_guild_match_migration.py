from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, String, Table, Uuid, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_memory_guild_match_migration_upgrades_existing_revision_61(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'memory-guild.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table(
        "outbound_messages",
        metadata,
        Column("id", Uuid, primary_key=True),
    )
    metadata.create_all(engine)

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260827_61")
    command.upgrade(config, "head")

    inspector = inspect(engine)
    expected_tables = {
        "memory_guild_matches",
        "memory_guild_teams",
        "memory_guild_members",
        "memory_guild_series",
        "memory_guild_rounds",
        "memory_guild_answers",
    }
    assert expected_tables <= set(inspector.get_table_names())
    assert "ux_memory_guild_one_active_per_group" in {
        index["name"]
        for index in inspector.get_indexes("memory_guild_matches")
    }
    assert {
        "group_chat_id",
        "host_user_id",
        "planned_series_count",
        "champion_team_id",
        "forced_by_user_id",
    } <= {
        column["name"]
        for column in inspector.get_columns("memory_guild_matches")
    }
    assert "ux_memory_guild_member_match_user" in {
        index["name"]
        for index in inspector.get_indexes("memory_guild_members")
    }
    assert "ux_memory_guild_answer_platform_message" in {
        index["name"]
        for index in inspector.get_indexes("memory_guild_answers")
    }

    command.downgrade(config, "20260827_61")

    inspector = inspect(engine)
    assert expected_tables.isdisjoint(inspector.get_table_names())
