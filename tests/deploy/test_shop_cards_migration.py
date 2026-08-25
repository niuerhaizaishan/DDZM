from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    Uuid,
    create_engine,
    inspect,
    text,
)

ROOT = Path(__file__).resolve().parents[2]


def test_shop_card_migration_refuses_to_overwrite_same_named_legacy_item(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'shop-name-collision.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    items = Table(
        "items",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("name", String(64), nullable=False, unique=True),
        Column("description", Text, nullable=False),
        Column("price", Integer, nullable=False),
        Column("stock", Integer, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            items.insert().values(
                id=uuid4(),
                name="初级赠送卡",
                description="历史自建商品，不得覆盖",
                price=99,
                stock=7,
                enabled=False,
                created_at=datetime(
                    2026, 8, 24, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai")
                ),
            )
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260824_53")

    with pytest.raises(RuntimeError, match="系统商品同名"):
        command.upgrade(config, "head")

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT name, description, price, stock, enabled FROM items "
                "WHERE name = '初级赠送卡'"
            )
        ).one()
    assert row == ("初级赠送卡", "历史自建商品，不得覆盖", 99, 7, 0)


def test_shop_card_migration_numbers_legacy_items_and_seeds_catalog(
    tmp_path, monkeypatch
) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'shop.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    engine = create_engine(database_url)
    metadata = MetaData()
    Table("group_chats", metadata, Column("id", Uuid, primary_key=True))
    commands = Table(
        "command_definitions",
        metadata,
        Column("command", String(64), primary_key=True),
        Column("syntax", Text, nullable=False),
        Column("description", Text, nullable=False),
    )
    items = Table(
        "items",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("name", String(64), nullable=False, unique=True),
        Column("description", Text, nullable=False),
        Column("price", Integer, nullable=False),
        Column("stock", Integer, nullable=False),
        Column("enabled", Boolean, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    )
    metadata.create_all(engine)
    now = datetime(2026, 8, 24, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    legacy_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            items.insert().values(
                id=legacy_id,
                name="纪念徽章",
                description="旧商品",
                price=7,
                stock=3,
                enabled=True,
                created_at=now,
            )
        )
        connection.execute(
            commands.insert().values(
                command="/发奖金",
                syntax="/发奖金 员工名 金额；/发奖金 全部 金额",
                description="旧说明",
            )
        )
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260824_53")

    command.upgrade(config, "head")

    inspector = inspect(engine)
    assert {
        "shop_purchases",
        "shop_purchase_daily_usage",
        "shop_daily_bonuses",
        "shop_multiplayer_daily_starts",
        "shop_item_uses",
        "adult_card_sessions",
        "adult_card_participants",
        "shop_scene_jobs",
        "shop_common_sense_states",
    } <= set(inspector.get_table_names())
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT public_number, name, price, system_key, effect_type, "
                "unlimited_stock FROM items ORDER BY public_number"
            )
        ).all()
        adult_switch = connection.execute(
            text("SELECT adult_shop_enabled FROM group_chats LIMIT 1")
        ).first()
        bonus_syntax = connection.execute(
            text("SELECT syntax FROM command_definitions WHERE command = '/发奖金'")
        ).scalar_one()
    assert rows[0] == (1, "纪念徽章", 7, None, None, 0)
    assert rows[1][1:5] == ("初级赠送卡", 3, "gift_basic", "gift")
    assert rows[-1][1:5] == (
        "常识改变卡·24小时",
        100,
        "adult_common_24h",
        "adult_common",
    )
    assert len(rows) == 23
    assert adult_switch is None
    assert bonus_syntax.startswith("回复发送 /发奖金 金额")
    assert "desired_participant_count" in {
        column["name"] for column in inspector.get_columns("adult_card_sessions")
    }

    command.downgrade(config, "20260824_53")
    inspector = inspect(engine)
    assert "shop_purchases" not in inspector.get_table_names()
    assert "public_number" not in {
        column["name"] for column in inspector.get_columns("items")
    }
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT syntax FROM command_definitions WHERE command = '/发奖金'")
            ).scalar_one()
            == "/发奖金 员工名 金额；/发奖金 全部 金额"
        )
        assert connection.execute(text("SELECT name FROM items")).all() == [
            ("纪念徽章",)
        ]
