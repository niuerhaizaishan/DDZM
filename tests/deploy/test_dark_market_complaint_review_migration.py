from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    inspect,
    select,
)


ROOT = Path(__file__).resolve().parents[2]


def test_dark_market_complaint_review_migration_adds_review_state_and_audit_fields(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dark-market-review.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    listings = Table(
        "dark_market_listings",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("state", String(32), nullable=False),
        CheckConstraint(
            "state IN ('active', 'awaiting_receipt', 'sold', 'complained', "
            "'unsold', 'force_delisted')",
            name="ck_dark_market_listing_state",
        ),
    )
    transactions = Table(
        "balance_transactions",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
    )
    replies = Table(
        "command_reply_templates",
        metadata,
        Column("command", String(32), primary_key=True),
        Column("scenario", String(64), primary_key=True),
        Column("template", String(2000), nullable=False),
    )
    metadata.create_all(engine)
    listing_id = UUID(int=1)
    transaction_id = UUID(int=2)
    with engine.begin() as connection:
        connection.execute(
            listings.insert().values(id=listing_id, state="awaiting_receipt")
        )
        connection.execute(
            transactions.insert().values(
                id=transaction_id,
                occurred_at=datetime(2026, 8, 26, tzinfo=UTC),
            )
        )
        connection.execute(
            replies.insert().values(
                command="/投诉",
                scenario="complained",
                template="旧投诉回复",
            )
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260826_57")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    columns = {
        column["name"] for column in inspector.get_columns("dark_market_listings")
    }
    checks = {
        check["name"]: check["sqltext"]
        for check in inspector.get_check_constraints("dark_market_listings")
    }
    assert {
        "complaint_requested_at",
        "complaint_reviewed_at",
        "complaint_reviewed_by",
        "complaint_decision",
    } <= columns
    assert "complaint_pending" in checks["ck_dark_market_listing_state"]
    assert "approved" in checks["ck_dark_market_listing_complaint_decision"]
    assert "rejected" in checks["ck_dark_market_listing_complaint_decision"]
    balance_columns = {
        column["name"] for column in inspector.get_columns("balance_transactions")
    }
    assert "dark_market_listing_id" in balance_columns
    reflected = MetaData()
    upgraded_listings = Table(
        "dark_market_listings", reflected, autoload_with=engine
    )
    upgraded_transactions = Table(
        "balance_transactions", reflected, autoload_with=engine
    )
    upgraded_replies = Table(
        "command_reply_templates", reflected, autoload_with=engine
    )
    with engine.begin() as connection:
        stored_transaction_id = connection.scalar(
            select(upgraded_transactions.c.id).where(
                upgraded_transactions.c.id == transaction_id
            )
        )
        assert str(stored_transaction_id).replace("-", "") == transaction_id.hex
        reply = connection.execute(
            select(upgraded_replies.c.scenario, upgraded_replies.c.template).where(
                upgraded_replies.c.command == "/投诉"
            )
        ).one()
        assert reply.scenario == "complaint_pending"
        assert "等待董事会审核" in reply.template
        connection.execute(
            upgraded_listings.update()
            .where(upgraded_listings.c.id == listing_id)
            .values(state="complaint_pending")
        )

    command.downgrade(config, "20260826_57")

    inspector = inspect(engine)
    columns = {
        column["name"] for column in inspector.get_columns("dark_market_listings")
    }
    assert "complaint_requested_at" not in columns
    balance_columns = {
        column["name"] for column in inspector.get_columns("balance_transactions")
    }
    assert "dark_market_listing_id" not in balance_columns
    reflected = MetaData()
    downgraded_listings = Table(
        "dark_market_listings", reflected, autoload_with=engine
    )
    downgraded_transactions = Table(
        "balance_transactions", reflected, autoload_with=engine
    )
    downgraded_replies = Table(
        "command_reply_templates", reflected, autoload_with=engine
    )
    with engine.connect() as connection:
        assert connection.scalar(
            select(downgraded_listings.c.state).where(
                downgraded_listings.c.id == listing_id
            )
        ) == "awaiting_receipt"
        stored_transaction_id = connection.scalar(
            select(downgraded_transactions.c.id).where(
                downgraded_transactions.c.id == transaction_id
            )
        )
        assert str(stored_transaction_id).replace("-", "") == transaction_id.hex
        reply = connection.execute(
            select(downgraded_replies.c.scenario, downgraded_replies.c.template).where(
                downgraded_replies.c.command == "/投诉"
            )
        ).one()
        assert reply.scenario == "complained"
        assert "卖家已被处罚" in reply.template


def test_dark_market_balance_audit_migration_upgrades_existing_revision_58(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dark-market-balance-audit.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
        "dark_market_listings",
        metadata,
        Column("id", Uuid, primary_key=True),
    )
    Table(
        "balance_transactions",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("occurred_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260826_58")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert "dark_market_listing_id" in {
        column["name"] for column in inspector.get_columns("balance_transactions")
    }

    command.downgrade(config, "20260826_58")

    inspector = inspect(engine)
    assert "dark_market_listing_id" not in {
        column["name"] for column in inspector.get_columns("balance_transactions")
    }
