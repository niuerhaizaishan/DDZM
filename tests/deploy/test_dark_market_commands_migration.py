from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    create_engine,
    select,
)


ROOT = Path(__file__).resolve().parents[2]


def test_dark_market_command_migration_seeds_without_overwriting_custom_template(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'dark-market-commands.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
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
    from datetime import datetime, UTC
    from uuid import uuid4

    with engine.begin() as connection:
        connection.execute(
            commands.insert(),
            {
                "command": "/报价",
                "syntax": "/报价 自定义",
                "description": "管理员自定义说明",
                "enabled": False,
                "created_at": datetime.now(UTC),
            },
        )
        connection.execute(
            templates.insert(),
            {
                "id": uuid4(),
                "command": "/报价",
                "scenario": "usage",
                "template": "管理员自定义报价提示",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            },
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260824_52")

    command.upgrade(config, "head")

    with engine.connect() as connection:
        command_rows = dict(
            connection.execute(
                select(commands.c.command, commands.c.enabled)
            ).all()
        )
        custom = connection.execute(
            select(templates.c.template).where(
                templates.c.command == "/报价",
                templates.c.scenario == "usage",
            )
        ).scalar_one()
        scenarios = set(
            connection.execute(
                select(templates.c.command, templates.c.scenario)
            ).all()
        )
    assert {
        "/上架暗网",
        "/取消上架",
        "/确认",
        "/报价",
        "/公开",
        "/不公开",
        "/登陆暗网",
    } <= set(command_rows)
    assert command_rows["/报价"] is False
    assert custom == "管理员自定义报价提示"
    assert ("/上架暗网", "private_only") in scenarios
    assert ("/登陆暗网", "wrong_group") in scenarios
