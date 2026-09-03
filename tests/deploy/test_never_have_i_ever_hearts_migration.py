from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Column, Integer, MetaData, Table, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_never_have_i_ever_hearts_migration_removes_fixed_upper_bound(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'never-have-i-ever-hearts.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "never_have_i_ever_players",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("hearts", Integer, nullable=False),
        CheckConstraint(
            "hearts BETWEEN 0 AND 5", name="ck_never_have_i_ever_hearts"
        ),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))

    command.stamp(config, "20260831_66")
    command.upgrade(config, "head")

    constraints = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspect(engine).get_check_constraints(
            "never_have_i_ever_players"
        )
    }
    assert constraints["ck_never_have_i_ever_hearts"] == "hearts >= 0"
