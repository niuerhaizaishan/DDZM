from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    inspect,
    text,
)


ROOT = Path(__file__).resolve().parents[2]


def test_dark_market_receipt_migration_preserves_history_and_command_customization(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dark-market-receipt.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    listings = Table(
        "dark_market_listings",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("state", String(32), nullable=False),
        Column("ends_at", DateTime(timezone=True), nullable=False),
        CheckConstraint(
            "state IN ('active', 'sold', 'unsold', 'force_delisted')",
            name="ck_dark_market_listing_state",
        ),
    )
    Index("ix_dark_market_listings_due", listings.c.state, listings.c.ends_at)
    commands = Table(
        "command_definitions",
        metadata,
        Column("command", String(32), primary_key=True),
        Column("syntax", Text, nullable=False),
        Column("description", Text, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    templates = Table(
        "command_reply_templates",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("command", String(32), nullable=False),
        Column("scenario", String(64), nullable=False),
        Column("template", Text, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("command", "scenario"),
    )
    metadata.create_all(engine)
    now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    sold_id = uuid4()
    active_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            listings.insert(),
            [
                {"id": sold_id, "state": "sold", "ends_at": now},
                {"id": active_id, "state": "active", "ends_at": now},
            ],
        )
        connection.execute(
            commands.insert(),
            {
                "command": "/登陆暗网",
                "syntax": "自定义 /登陆暗网 [编号]",
                "description": "管理员自定义说明",
                "enabled": False,
                "created_at": now,
            },
        )
        connection.execute(
            templates.insert(),
            {
                "id": uuid4(),
                "command": "/登陆暗网",
                "scenario": "usage",
                "template": "管理员自定义 /登陆暗网 提示",
                "created_at": now,
                "updated_at": now,
            },
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260824_54")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("dark_market_listings")}
    checks = {check["name"]: check["sqltext"] for check in inspector.get_check_constraints("dark_market_listings")}
    with engine.connect() as connection:
        states = dict(
            connection.execute(
                text("SELECT CAST(id AS TEXT), state FROM dark_market_listings")
            ).all()
        )
        command_rows = dict(
            connection.execute(
                text("SELECT command, enabled FROM command_definitions")
            ).all()
        )
        custom_template = connection.execute(
            text(
                "SELECT template FROM command_reply_templates "
                "WHERE command = '/查看暗网' AND scenario = 'usage'"
            )
        ).scalar_one()
    assert {
        "receipt_started_at",
        "receipt_deadline",
        "receipt_resolved_at",
    } <= columns
    assert "awaiting_receipt" in checks["ck_dark_market_listing_state"]
    assert "complained" in checks["ck_dark_market_listing_state"]
    assert states[str(sold_id).replace("-", "")] == "sold"
    assert states[str(active_id).replace("-", "")] == "active"
    assert command_rows["/查看暗网"] == 0
    assert command_rows["/确认收货"] == 1
    assert command_rows["/投诉"] == 1
    assert "/登陆暗网" not in command_rows
    assert custom_template == "管理员自定义 /查看暗网 提示"

    command.downgrade(config, "20260824_54")

    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("dark_market_listings")}
    with engine.connect() as connection:
        command_rows = set(
            connection.execute(text("SELECT command FROM command_definitions")).scalars()
        )
    assert "receipt_deadline" not in columns
    assert "/登陆暗网" in command_rows
    assert "/查看暗网" not in command_rows
    assert "/确认收货" not in command_rows
    assert "/投诉" not in command_rows
