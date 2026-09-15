from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Column,
    MetaData,
    Table,
    Uuid,
    create_engine,
    inspect,
    select,
    text,
)


ROOT = Path(__file__).resolve().parents[2]

EXPECTED_TABLES = {
    "company_lottery_settings",
    "company_lottery_rounds",
    "company_lottery_bets",
    "company_lottery_drafts",
    "company_lottery_pool_ledger",
    "company_lottery_welfare",
    "company_lottery_welfare_payouts",
}


def migrated_engine(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'company-lottery.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("inbound_messages", metadata, Column("id", Uuid, primary_key=True))
    metadata.create_all(engine)

    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260909_73")
    command.upgrade(config, "head")
    return engine


def test_company_lottery_migration_creates_tables(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_company_lottery_migration_adds_round_rule_snapshots(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("company_lottery_rounds")
    }

    assert "rules_snapshot" in columns


def test_company_lottery_migration_seeds_pool_and_settings(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)

    settings = Table("company_lottery_settings", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        row = connection.execute(select(settings)).mappings().one()

    assert row["enabled"] is True
    assert row["red_pool"] == 10
    assert row["red_count"] == 4
    assert row["blue_pool"] == 6
    assert row["ticket_price"] == 2
    assert row["head_prize"] == 100
    assert row["pool_ceiling"] == 200
    assert row["pool_seed"] == 100
    assert row["per_person_cap"] == 100
    assert row["max_tickets_per_day"] == 5
    assert row["welfare_per_person"] == 1

    ledger = Table("company_lottery_pool_ledger", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        entries = connection.execute(select(ledger)).mappings().all()

    assert len(entries) == 1
    entry = entries[0]
    assert entry["account"] == "pool"
    assert entry["kind"] == "deposit"
    assert entry["amount"] == 100
    assert entry["balance_after"] == 100


def test_company_lottery_migration_creates_indexes(tmp_path, monkeypatch):
    """SQLite 的 get_indexes() 不返回部分索引，直接查 sqlite_master。"""
    engine = migrated_engine(tmp_path, monkeypatch)
    with engine.connect() as connection:
        names = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index'")
            )
        }

    assert {
        "ux_company_lottery_one_open",
        "ix_company_lottery_rounds_state_draw",
        "ix_company_lottery_bets_round_user",
        "ix_company_lottery_bets_created_at",
        "ix_company_lottery_ledger_account",
        "ix_company_lottery_welfare_created",
        "ix_company_lottery_welfare_payouts_user",
    } <= names


def test_company_lottery_migration_keeps_the_economy_global(tmp_path, monkeypatch):
    """期次、账本与福利都不带 group_chat_id：三个群共用一套经济。"""
    engine = migrated_engine(tmp_path, monkeypatch)
    inspector = inspect(engine)

    for table in (
        "company_lottery_rounds",
        "company_lottery_drafts",
        "company_lottery_pool_ledger",
        "company_lottery_welfare",
    ):
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert "group_chat_id" not in columns, table


def test_company_lottery_migration_downgrades_cleanly(tmp_path, monkeypatch):
    engine = migrated_engine(tmp_path, monkeypatch)
    config = Config(str(ROOT / "alembic.ini"))

    command.downgrade(config, "20260909_73")

    remaining = set(inspect(engine).get_table_names())
    assert not (EXPECTED_TABLES & remaining)
