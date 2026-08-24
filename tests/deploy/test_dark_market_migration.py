from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import Column, Integer, MetaData, Table, Uuid, create_engine, inspect, text


ROOT = Path(__file__).resolve().parents[2]


def _revision_51_dependencies(database_url: str) -> None:
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    Table("users", metadata, Column("id", Uuid, primary_key=True))
    Table("inbound_messages", metadata, Column("id", Uuid, primary_key=True))
    Table(
        "ranks",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("sort_order", Integer, nullable=False, unique=True),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            metadata.tables["ranks"].insert(),
            [{"id": uuid4(), "sort_order": sort_order} for sort_order in range(1, 12)],
        )


def test_dark_market_migration_creates_defaults_and_rank_limits(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dark-market.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    _revision_51_dependencies(database_url)
    command.stamp(config, "20260820_51")

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "dark_market_settings",
        "dark_market_rank_limits",
        "dark_market_drafts",
        "dark_market_listings",
        "dark_market_bids",
        "dark_market_disclosures",
        "dark_market_daily_listings",
        "dark_market_number_counters",
    } <= set(inspector.get_table_names())
    assert any(
        index["name"] == "ux_dark_market_one_current_bid" and index["unique"]
        for index in inspector.get_indexes("dark_market_bids")
    )
    assert any(
        constraint["name"] == "uq_dark_market_listings_public_number"
        for constraint in inspector.get_unique_constraints("dark_market_listings")
    )
    assert any(
        constraint["name"] == "uq_dark_market_drafts_user_id"
        for constraint in inspector.get_unique_constraints("dark_market_drafts")
    )
    with engine.connect() as connection:
        settings = connection.execute(
            text(
                "SELECT enabled, announcement_group_id, duration_hours, "
                "fee_percent, version FROM dark_market_settings WHERE id = 1"
            )
        ).one()
        limits = connection.execute(
            text(
                "SELECT r.sort_order, l.daily_limit "
                "FROM dark_market_rank_limits AS l "
                "JOIN ranks AS r ON r.id = l.rank_id "
                "ORDER BY r.sort_order"
            )
        ).all()
        counter = connection.execute(
            text("SELECT next_number FROM dark_market_number_counters WHERE id = 1")
        ).scalar_one()
    assert tuple(settings) == (1, None, 3, 5, 0)
    assert [limit for _, limit in limits] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, -1]
    assert counter == 1

    command.downgrade(config, "20260820_51")

    inspector = inspect(engine)
    assert not {
        "dark_market_settings",
        "dark_market_rank_limits",
        "dark_market_drafts",
        "dark_market_listings",
        "dark_market_bids",
        "dark_market_disclosures",
        "dark_market_daily_listings",
        "dark_market_number_counters",
    } & set(inspector.get_table_names())
