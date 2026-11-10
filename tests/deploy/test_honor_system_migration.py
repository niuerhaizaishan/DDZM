from pathlib import Path
from io import StringIO
from uuid import uuid4
from datetime import date, datetime

import pytest

from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from dzmm_bot.core.schema import Base


ROOT = Path(__file__).resolve().parents[2]
HONOR_TABLES = {"honor_state", "honor_configs", "honor_periods", "honor_awards", "honor_wear"}
NEW_TABLES = HONOR_TABLES | {"game_participations"}
PERMANENT_HONOR_PREVIOUS = "20261105_110"
PERMANENT_HONOR_REVISION = "20261109_111_permanent_honors"


def test_honor_migration_preserves_users_and_matches_models(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'honors.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Uuid(), primary_key=True),
                     sa.Column("name", sa.String(64)))
    metadata.create_all(engine)
    original_id = uuid4()
    with engine.begin() as connection:
        connection.execute(users.insert().values(id=original_id, name="原员工"))
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.stamp(config, "20261005_95")
    command.upgrade(config, "20261005_99")
    # This fixture only creates the tables needed for the honor migrations.
    command.stamp(config, PERMANENT_HONOR_PREVIOUS)
    command.upgrade(config, PERMANENT_HONOR_REVISION)
    inspector = sa.inspect(engine)
    current_tables = NEW_TABLES | {"honor_seasons"}
    assert current_tables <= set(inspector.get_table_names())
    for name in current_tables:
        columns = inspector.get_columns(name)
        expected = Base.metadata.tables[name].columns
        assert {column["name"] for column in columns} == set(expected.keys())
        for column in columns:
            assert column["nullable"] == expected[column["name"]].nullable
        assert {tuple(index["column_names"]) for index in inspector.get_indexes(name)} == {
            tuple(column.name for column in index.columns) for index in Base.metadata.tables[name].indexes}
    with engine.connect() as connection:
        assert connection.execute(sa.select(users)).one().name == "原员工"
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM honor_configs")) == 0
        assert connection.scalar(sa.text("SELECT COUNT(*) FROM game_participations")) == 0
    assert {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(
        "game_participations")} == {("game_type", "game_id", "user_id")}
    command.downgrade(config, PERMANENT_HONOR_PREVIOUS)
    assert "honor_seasons" not in sa.inspect(engine).get_table_names()
    command.stamp(config, "20261005_99")
    command.downgrade(config, "20261005_95")
    assert not NEW_TABLES.intersection(sa.inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(sa.select(users.c.id)) == original_id
    command.upgrade(config, "20261005_99")
    assert NEW_TABLES <= set(sa.inspect(engine).get_table_names())
    engine.dispose()


def test_permanent_honor_migration_preserves_weekly_award_and_wear(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'permanent-honors.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.String(32), primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.stamp(config, "20261005_95")
    command.upgrade(config, "20261005_99")
    command.stamp(config, PERMANENT_HONOR_PREVIOUS)
    periods, awards, wear = (sa.Table(name, metadata, autoload_with=engine)
                             for name in ("honor_periods", "honor_awards", "honor_wear"))
    period_id, user_id, award_id = [uuid4().hex for _ in range(3)]
    granted_at, expiry = datetime(2026, 10, 5), datetime(2026, 10, 12)
    with engine.begin() as connection:
        connection.execute(users.insert().values(id=user_id))
        connection.execute(periods.insert().values(id=period_id, week_start=date(2026, 9, 28),
                           config_version=0, snapshot={}, settled_at=granted_at, revision=1))
        connection.execute(awards.insert().values(id=award_id, period_id=period_id, title_key="checkin_king",
                           title_name="牛马之王", user_id=user_id, winner_name="糯糯", score=7,
                           valid_from=granted_at, expires_at=expiry, sort_order=1, public_score=True))
        connection.execute(wear.insert().values(user_id=user_id, award_id=award_id))
    command.upgrade(config, PERMANENT_HONOR_REVISION)
    awards = sa.Table("honor_awards", sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        weekly = connection.execute(sa.select(awards).where(awards.c.id == award_id)).one()
        assert weekly.source == "weekly" and weekly.expires_at == expiry and weekly.period_id == period_id
        assert connection.scalar(sa.select(wear.c.award_id)) == award_id
        permanent_id = uuid4().hex
        connection.execute(awards.insert().values(id=permanent_id, source="manual", user_id=user_id,
                           title_key="manual:example", title_name="永久称号", winner_name="糯糯",
                           valid_from=granted_at, sort_order=1000, public_score=False))
    with pytest.raises(RuntimeError, match="Permanent honor history exists"):
        command.downgrade(config, PERMANENT_HONOR_PREVIOUS)
    # The unrelated workstation and upstream migrations are omitted by this fixture.
    command.stamp(config, [PERMANENT_HONOR_REVISION, "20261109_merge_workstation"], purge=True)
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == "20261109_merge_permanent_honors"
        assert connection.scalar(sa.select(awards.c.title_name).where(awards.c.id == permanent_id)) == "永久称号"
        assert connection.scalar(sa.select(wear.c.award_id)) == award_id
    engine.dispose()


def test_honor_migration_generates_postgresql_sql_without_connecting(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://localhost/honor_test")
    output = StringIO()
    config = Config(str(ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "20261005_95:20261005_99", sql=True)
    sql = output.getvalue()
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "UNIQUE (period_id, title_key)" in sql
    assert "FOREIGN KEY(award_id) REFERENCES honor_awards (id)" in sql
    assert "UNIQUE (game_type, game_id, user_id)" in sql
    assert "ADD COLUMN scheduled_announced_at TIMESTAMP WITH TIME ZONE" in sql
    assert "UNIQUE (period_id, title_key, user_id)" in sql
    for name in NEW_TABLES:
        assert f"CREATE TABLE {name}" in sql

    output.seek(0)
    output.truncate()
    command.upgrade(config, f"{PERMANENT_HONOR_PREVIOUS}:{PERMANENT_HONOR_REVISION}", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE honor_seasons" in sql
    assert "ALTER COLUMN expires_at DROP NOT NULL" in sql
    assert "UNIQUE (season_code, user_id)" in sql


def test_scheduled_announcement_migration_preserves_existing_announcement(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'existing-honors.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Uuid(), primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.stamp(config, "20261005_95")
    command.upgrade(config, "20261005_97")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO honor_periods (id, week_start, config_version, snapshot, settled_at, announced_at, revision) "
            "VALUES (:id, '2026-09-28', 0, '{}', '2026-10-05 00:00:00', '2026-10-05 00:01:00', 1)"), {"id": uuid4().hex})
    command.upgrade(config, "20261005_98")
    with engine.connect() as connection:
        row = connection.execute(sa.text("SELECT announced_at, scheduled_announced_at FROM honor_periods")).one()
        assert row.announced_at == "2026-10-05 00:01:00"
        assert row.scheduled_announced_at is None
    command.downgrade(config, "20261005_97")
    with engine.connect() as connection:
        assert connection.scalar(sa.text("SELECT announced_at FROM honor_periods")) == "2026-10-05 00:01:00"
    engine.dispose()


def test_multi_winner_migration_keeps_awards_wear_and_historical_snapshot(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'existing-awards.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = sa.create_engine(database_url)
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.String(32), primary_key=True))
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.stamp(config, "20261005_95")
    command.upgrade(config, "20261005_98")
    periods = sa.Table("honor_periods", metadata, autoload_with=engine)
    awards = sa.Table("honor_awards", metadata, autoload_with=engine)
    wear = sa.Table("honor_wear", metadata, autoload_with=engine)
    period_id, first_user, second_user, award_id = [uuid4().hex for _ in range(4)]
    original_snapshot = {"configuration": {"rules": [{"key": "checkin_king", "minimum": 30}]}}
    original_expiry = datetime(2026, 10, 12)
    original_award = dict(id=award_id, period_id=period_id, title_key="checkin_king", title_name="牛马之王",
        user_id=first_user, winner_name="原员工", score=30, valid_from=datetime(2026, 10, 5),
        expires_at=original_expiry, sort_order=1, public_score=True)
    with engine.begin() as connection:
        connection.execute(users.insert(), [{"id": first_user}, {"id": second_user}])
        connection.execute(periods.insert().values(id=period_id, week_start=datetime(2026, 9, 28).date(),
            config_version=0, snapshot=original_snapshot, settled_at=datetime(2026, 10, 5), revision=1))
        connection.execute(awards.insert().values(**original_award))
        connection.execute(wear.insert().values(user_id=first_user, award_id=award_id))
    command.upgrade(config, "20261005_99")
    with engine.connect() as connection:
        assert connection.scalar(sa.select(periods.c.snapshot)) == original_snapshot
        assert connection.scalar(sa.select(awards.c.expires_at)) == original_expiry
        assert connection.scalar(sa.select(wear.c.award_id)) == award_id
    with engine.begin() as connection:
        connection.execute(awards.insert().values(**{**original_award, "id": uuid4().hex, "user_id": second_user}))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as connection:
        connection.execute(awards.insert().values(**{**original_award, "id": uuid4().hex}))
    with pytest.raises(RuntimeError, match="multi-winner"):
        command.downgrade(config, "20261005_98")
    engine.dispose()
