from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, String, Table, Uuid, create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


def test_number_bomb_points_tournament_migration_preserves_existing_games(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'number-bomb-points.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    games = Table(
        "number_bomb_games",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("state", String(32), nullable=False),
    )
    members = Table(
        "number_bomb_members",
        metadata,
        Column("id", Uuid, primary_key=True),
    )
    round_players = Table(
        "number_bomb_round_players",
        metadata,
        Column("id", Uuid, primary_key=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            games.insert(),
            {"id": UUID("00000000-0000-0000-0000-000000000101"), "state": "signup"},
        )
        connection.execute(
            members.insert(),
            {"id": UUID("00000000-0000-0000-0000-000000000102")},
        )
        connection.execute(
            round_players.insert(),
            {"id": UUID("00000000-0000-0000-0000-000000000103")},
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260818_46")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert {"mode", "maximum_rounds"} <= {
        column["name"] for column in inspector.get_columns("number_bomb_games")
    }
    assert {"total_points", "retired_at_round"} <= {
        column["name"] for column in inspector.get_columns("number_bomb_members")
    }
    assert {"competition_rank", "round_points", "result_reason"} <= {
        column["name"]
        for column in inspector.get_columns("number_bomb_round_players")
    }
    with engine.connect() as connection:
        game = connection.execute(
            text("SELECT mode, maximum_rounds FROM number_bomb_games")
        ).one()
        member = connection.execute(
            text("SELECT total_points, retired_at_round FROM number_bomb_members")
        ).one()
        round_player = connection.execute(
            text(
                "SELECT competition_rank, round_points, result_reason "
                "FROM number_bomb_round_players"
            )
        ).one()
    assert tuple(game) == ("standard", 0)
    assert tuple(member) == (0, None)
    assert tuple(round_player) == (None, 0, None)

    command.downgrade(config, "20260818_46")

    inspector = inspect(engine)
    assert "mode" not in {
        column["name"] for column in inspector.get_columns("number_bomb_games")
    }
