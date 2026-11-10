from pathlib import Path
import logging
import pytest

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, Uuid, create_engine, inspect, text


@pytest.fixture(autouse=True)
def restore_logger_enabled_state():
    # Alembic fileConfig disables existing application loggers; do not leak that
    # process-global state into the browser worker tests that follow this module.
    previous = {name: logger.disabled for name, logger in logging.Logger.manager.loggerDict.items()
                if isinstance(logger, logging.Logger)}
    yield
    for name, logger in logging.Logger.manager.loggerDict.items():
        if isinstance(logger, logging.Logger):
            logger.disabled = previous.get(name, False)


def test_equipment_migration_roundtrip_preserves_existing_shop(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'equipment.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    for name in ("users", "group_chats", "inbound_messages"):
        Table(name, metadata, Column("id", Uuid, primary_key=True))
    Table("items", metadata, Column("public_number", Integer, primary_key=True), Column("price", Integer))
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO items (public_number, price) VALUES (1, 99)"))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.stamp(config, "20261012_103")
    command.upgrade(config, "20261107_111")
    expected = {"equipment_items", "equipment_ownerships", "equipment_purchases", "workstation_components", "workstation_upgrades",
                'workstation_accessories','workstation_accessory_purchases', 'workstation_actions',
                'workstation_income_settings', 'workstation_income_settlements', 'workstation_rules', 'workstation_admin_operations'}
    assert expected <= set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM equipment_items")) == 10
        assert connection.scalar(text("SELECT price FROM items WHERE public_number = 1")) == 99
        assert connection.scalar(text("SELECT daily_income FROM equipment_items WHERE public_number = 1")) == 2
    command.downgrade(config, "20261012_103")
    assert not expected & set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT price FROM items WHERE public_number = 1")) == 99
    command.upgrade(config, "20261107_111")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM equipment_items")) == 10
    engine.dispose()


def test_workstation_admin_migration_changes_only_birthday_default(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'admin.db'}"
    monkeypatch.setenv('DZMM_DATABASE_URL', database_url)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id CHAR(32) PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE birthday_settings (id INTEGER PRIMARY KEY, enabled BOOLEAN NOT NULL DEFAULT 0)'))
        connection.execute(text('INSERT INTO birthday_settings (id, enabled) VALUES (1, 0), (2, 1)'))
    config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
    command.stamp(config, '20261104_109')
    command.upgrade(config, '20261105_110')
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO birthday_settings (id) VALUES (3)'))
        assert connection.execute(text('SELECT enabled FROM birthday_settings ORDER BY id')).scalars().all() == [0, 1, 1]
    command.downgrade(config, '20261104_109')
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO birthday_settings (id) VALUES (4)'))
        assert connection.execute(text('SELECT enabled FROM birthday_settings ORDER BY id')).scalars().all() == [0, 1, 1, 0]
    engine.dispose()


def test_upgrade_enables_saved_birthday_switches_and_preserves_other_settings(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'birthday-switches.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE birthday_settings (id INTEGER PRIMARY KEY, enabled BOOLEAN NOT NULL, gift_amount INTEGER)"
        ))
        connection.execute(text(
            "CREATE TABLE group_chats (id INTEGER PRIMARY KEY, birthdays_enabled BOOLEAN NOT NULL, announcements_enabled BOOLEAN)"
        ))
        connection.execute(text("INSERT INTO birthday_settings VALUES (1, 0, 37)"))
        connection.execute(text("INSERT INTO group_chats VALUES (1, 0, 0), (2, 1, 1)"))
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.stamp(config, "20261105_110")
    command.upgrade(config, "20261107_111")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT enabled, gift_amount FROM birthday_settings")).one() == (1, 37)
        assert connection.execute(text(
            "SELECT birthdays_enabled, announcements_enabled FROM group_chats ORDER BY id"
        )).all() == [(1, 0), (1, 1)]
    engine.dispose()


def test_upstream_head_can_upgrade_to_workstation_and_permanent_honors(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'upstream.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    for name in ("users", "group_chats", "inbound_messages"):
        Table(name, metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.stamp(config, "20261005_95")
    command.upgrade(config, "20261005_99")
    command.stamp(config, "20261103_130")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "20261109_merge_permanent_honors"
        ]
        assert connection.scalar(text("SELECT count(*) FROM equipment_items")) == 10
        assert connection.scalar(text("SELECT count(*) FROM workstation_admin_operations")) == 0
        assert connection.scalar(text("SELECT count(*) FROM honor_seasons")) == 0
    engine.dispose()
