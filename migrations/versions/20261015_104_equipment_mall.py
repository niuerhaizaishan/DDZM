"""Add an independent workstation equipment catalog, ownership and purchases."""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "20261015_104"
down_revision = "20261012_103"
branch_labels = None
depends_on = None


def upgrade():
    catalog = op.create_table(
        "equipment_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("public_number", sa.Integer(), nullable=False, unique=True),
        sa.Column("asset_key", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("daily_income", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_equipment_price"),
        sa.CheckConstraint("daily_income >= 0", name="ck_equipment_income"),
    )
    op.create_table(
        "equipment_ownerships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("equipment_items.id"), nullable=False),
        sa.Column("equipped", sa.Boolean(), nullable=False),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "item_id", name="uq_equipment_owner"),
    )
    op.create_table(
        "equipment_purchases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("inbound_message_id", sa.Uuid(), sa.ForeignKey("inbound_messages.id"), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("equipment_items.id"), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), sa.ForeignKey("group_chats.id"), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price >= 0", name="ck_equipment_purchase_price"),
    )
    seeds = (
        (1, "monitor-main", "主显示器", 36, 2),
        (2, "monitor-left", "左侧竖屏", 28, 1),
        (3, "monitor-right", "右侧竖屏", 28, 1),
        (4, "screen-light", "屏幕挂灯", 18, 1),
        (5, "keyboard", "机械键盘", 22, 1),
        (6, "mouse", "桌面鼠标", 16, 1),
        (7, "desk-lamp", "暖光台灯", 24, 1),
        (8, "handheld", "桌面掌机", 20, 1),
        (9, "pc", "侧透主机", 58, 3),
        (10, "chair", "人体工学椅", 46, 2),
    )
    op.bulk_insert(catalog, [dict(
        id=uuid4(), public_number=number, asset_key=asset_key,
        name=name, price=price, daily_income=income, enabled=True,
    ) for number, asset_key, name, price, income in seeds])


def downgrade():
    op.drop_table("equipment_purchases")
    op.drop_table("equipment_ownerships")
    op.drop_table("equipment_items")
