from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]


def test_liar_dice_timeout_migration_defaults_and_preserves_rows(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'liar_dice_timeouts.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE liar_dice_settings (id INTEGER PRIMARY KEY, "
                "turn_seconds INTEGER NOT NULL, enabled BOOLEAN NOT NULL, "
                "min_players INTEGER NOT NULL)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE liar_dice_games (id INTEGER PRIMARY KEY, "
                "state VARCHAR(20) NOT NULL, round_number INTEGER NOT NULL)"
            )
        )
        connection.execute(sa.text("INSERT INTO liar_dice_settings VALUES (1, 240, 1, 4)"))
        connection.execute(sa.text("INSERT INTO liar_dice_games VALUES (1, 'round_end', 3)"))
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20261010_102")
    command.upgrade(config, "20261011_103")
    with engine.connect() as connection:
        settings = (
            connection.execute(sa.text("SELECT * FROM liar_dice_settings")).mappings().one()
        )
        game = (
            connection.execute(sa.text("SELECT * FROM liar_dice_games")).mappings().one()
        )
        # 历史设置保留，新列取服务端默认值（报名 5 / 等待继续 5 / 发牌 180）
        assert dict(settings) == {
            "id": 1,
            "turn_seconds": 240,
            "enabled": 1,
            "min_players": 4,
            "signup_timeout_minutes": 5,
            "continue_timeout_minutes": 5,
            "deal_timeout_seconds": 180,
        }
        # 历史对局不被误杀：deadline 留空，交给巡检首次补写
        assert dict(game) == {
            "id": 1,
            "state": "round_end",
            "round_number": 3,
            "round_end_deadline": None,
            "dealing_deadline": None,
        }
    command.downgrade(config, "20261010_102")
    with engine.connect() as connection:
        assert (
            connection.execute(
                sa.text("SELECT turn_seconds FROM liar_dice_settings")
            ).scalar_one()
            == 240
        )
    assert {
        "signup_timeout_minutes",
        "continue_timeout_minutes",
        "deal_timeout_seconds",
    }.isdisjoint({column["name"] for column in sa.inspect(engine).get_columns("liar_dice_settings")})
    assert {"round_end_deadline", "dealing_deadline"}.isdisjoint(
        {column["name"] for column in sa.inspect(engine).get_columns("liar_dice_games")}
    )
    command.upgrade(config, "20261011_103")
    engine.dispose()


def test_liar_dice_timeout_migration_generates_postgresql_sql(monkeypatch):
    monkeypatch.setenv(
        "DZMM_DATABASE_URL", "postgresql+psycopg://localhost/liar_dice_timeouts_test"
    )
    output = StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    command.upgrade(config, "20261010_102:20261011_103", sql=True)
    sql = output.getvalue()
    assert (
        "ALTER TABLE liar_dice_settings ADD COLUMN signup_timeout_minutes INTEGER DEFAULT '5' NOT NULL"
        in sql
    )
    assert (
        "ALTER TABLE liar_dice_settings ADD COLUMN continue_timeout_minutes INTEGER DEFAULT '5' NOT NULL"
        in sql
    )
    assert (
        "ALTER TABLE liar_dice_settings ADD COLUMN deal_timeout_seconds INTEGER DEFAULT '180' NOT NULL"
        in sql
    )
    assert (
        "ALTER TABLE liar_dice_games ADD COLUMN round_end_deadline TIMESTAMP WITH TIME ZONE"
        in sql
    )
    assert (
        "ALTER TABLE liar_dice_games ADD COLUMN dealing_deadline TIMESTAMP WITH TIME ZONE"
        in sql
    )
