from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Column, MetaData, String, Table, Uuid, create_engine, inspect


ROOT = Path(__file__).resolve().parents[2]


def test_dark_market_complaint_review_migration_adds_review_state_and_audit_fields(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dark-market-review.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table(
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
    metadata.create_all(engine)
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

    command.downgrade(config, "20260826_57")

    inspector = inspect(engine)
    columns = {
        column["name"] for column in inspector.get_columns("dark_market_listings")
    }
    assert "complaint_requested_at" not in columns
