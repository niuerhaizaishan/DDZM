from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


def _revision_45_dependencies(database_url: str) -> None:
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("inbound_messages", metadata, Column("id", Uuid, primary_key=True))
    Table("outbound_messages", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)


def test_texas_holdem_migration_adds_group_scoped_tables_and_defaults(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'texas-holdem.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    _revision_45_dependencies(database_url)
    command.stamp(config, "20260818_45")

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "texas_holdem_settings",
        "texas_holdem_games",
        "texas_holdem_players",
        "texas_holdem_actions",
        "texas_holdem_pots",
        "texas_holdem_daily_starts",
    } <= set(inspector.get_table_names())
    assert any(
        index["name"] == "ux_texas_holdem_one_active" and index["unique"]
        for index in inspector.get_indexes("texas_holdem_games")
    )
    group_column = next(
        column
        for column in inspector.get_columns("texas_holdem_games")
        if column["name"] == "group_chat_id"
    )
    assert group_column["nullable"] is False
    game_columns = {
        column["name"] for column in inspector.get_columns("texas_holdem_games")
    }
    assert {
        "minimum_players_snapshot",
        "maximum_players_snapshot",
        "daily_start_limit_snapshot",
        "action_timeout_seconds_snapshot",
        "small_blind_percent_snapshot",
        "big_blind_percent_snapshot",
    } <= game_columns
    with engine.connect() as connection:
        settings = connection.execute(
            text(
                "SELECT enabled, minimum_players, maximum_players, "
                "minimum_buy_in, maximum_buy_in, daily_start_limit, "
                "signup_timeout_seconds, action_timeout_seconds, "
                "small_blind_percent, big_blind_percent "
                "FROM texas_holdem_settings WHERE id = 1"
            )
        ).one()
    assert tuple(settings) == (1, 2, 9, 20, 200, 1, 120, 120, 5, 10)

    command.downgrade(config, "20260818_45")

    inspector = inspect(engine)
    assert "texas_holdem_games" not in inspector.get_table_names()
    assert "texas_holdem_settings" not in inspector.get_table_names()
