"""Add the typed shop card catalog and durable use workflows."""

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_54"
down_revision: str | None = "20260824_53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SYSTEM_ITEMS = (
    ("gift_basic", "初级赠送卡", 3, "gift", "赠送目标员工 2 摸鱼币", 2),
    ("gift_intermediate", "中级赠送卡", 5, "gift", "赠送目标员工 4 摸鱼币", 4),
    ("gift_advanced", "高级赠送卡", 10, "gift", "赠送目标员工 8 摸鱼币", 6),
    ("gift_platinum", "白金赠送卡", 20, "gift", "赠送目标员工 15 摸鱼币", 9),
    ("ai_quota", "总监事对话卡", 2, "ai_quota", "当天总监事对话次数 +1", None),
    ("scratch_a", "刮刮卡 A", 5, "scratch", "随机获得 1–10 摸鱼币", None),
    ("scratch_b", "刮刮卡 B", 10, "scratch", "随机获得 5–15 摸鱼币", None),
    ("scratch_c", "刮刮卡 C", 20, "scratch", "随机获得 10–30 摸鱼币", 6),
    (
        "multiplayer_quota",
        "小游戏次数卡",
        3,
        "multiplayer_quota",
        "当天多人游戏发起次数 +1",
        None,
    ),
    ("adult_m", "M卡", 10, "adult_m", "发布自愿参与的场景公告", None),
    ("adult_flirt", "发骚卡", 20, "adult_scene", "双人授权场景", None),
    (
        "adult_training_invite",
        "调教邀请卡",
        30,
        "adult_scene",
        "邀请对方接受调教",
        None,
    ),
    (
        "adult_trained_invite",
        "被调教邀请卡",
        30,
        "adult_scene",
        "邀请对方进行调教",
        None,
    ),
    ("adult_love", "爱爱卡", 50, "adult_scene", "双人授权场景", None),
    ("adult_three", "3P卡", 80, "adult_scene", "三人授权场景", None),
    ("adult_four", "四人淫趴卡", 100, "adult_scene", "四人授权场景", None),
    ("adult_six", "六人淫趴卡", 150, "adult_scene", "六人授权场景", None),
    ("adult_sleep", "昏睡卡", 20, "adult_scene", "单目标授权场景", None),
    ("adult_gender_change", "性转卡", 50, "adult_scene", "单目标授权场景", None),
    (
        "adult_common_1h",
        "常识改变卡·1小时",
        50,
        "adult_common",
        "来源群临时设定 1 小时",
        None,
    ),
    (
        "adult_common_6h",
        "常识改变卡·6小时",
        80,
        "adult_common",
        "来源群临时设定 6 小时",
        None,
    ),
    (
        "adult_common_24h",
        "常识改变卡·24小时",
        100,
        "adult_common",
        "来源群临时设定 24 小时",
        None,
    ),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not (inspector.has_table("items") and inspector.has_table("group_chats")):
        return
    connection = op.get_bind()
    legacy_names = {
        row[0] for row in connection.execute(sa.text("SELECT name FROM items")).all()
    }
    collisions = sorted(name for _, name, *_ in SYSTEM_ITEMS if name in legacy_names)
    if collisions:
        raise RuntimeError(
            "系统商品同名冲突，请先处理历史自建商品：" + "、".join(collisions)
        )
    with op.batch_alter_table("group_chats") as batch:
        batch.add_column(
            sa.Column(
                "adult_shop_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    if inspector.has_table("texas_holdem_games"):
        with op.batch_alter_table("texas_holdem_games") as batch:
            batch.add_column(sa.Column("start_quota_source", sa.String(length=16)))
    with op.batch_alter_table("items") as batch:
        batch.add_column(sa.Column("public_number", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "unlimited_stock",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("system_key", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("effect_type", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("minimum_rank_order", sa.Integer(), nullable=True))

    if inspector.has_table("command_definitions"):
        connection.execute(
            sa.text(
                "UPDATE command_definitions SET syntax = :syntax, description = :description "
                "WHERE command = '/发奖金'"
            ),
            {
                "syntax": "回复发送 /发奖金 金额；/发奖金 员工名 金额；/发奖金 全部 金额",
                "description": "核心董事会向单个或全部员工发放系统奖金",
            },
        )
    existing = connection.execute(
        sa.text("SELECT id FROM items ORDER BY created_at, id")
    ).all()
    for public_number, (item_id,) in enumerate(existing, start=1):
        connection.execute(
            sa.text("UPDATE items SET public_number = :number WHERE id = :id"),
            {"number": public_number, "id": item_id},
        )
    next_number = len(existing) + 1
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    items = sa.table(
        "items",
        sa.column("id", sa.Uuid()),
        sa.column("public_number", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("price", sa.Integer()),
        sa.column("stock", sa.Integer()),
        sa.column("unlimited_stock", sa.Boolean()),
        sa.column("system_key", sa.String()),
        sa.column("effect_type", sa.String()),
        sa.column("minimum_rank_order", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    for key, name, price, effect_type, description, minimum_rank_order in SYSTEM_ITEMS:
        connection.execute(
            items.insert().values(
                id=uuid4(),
                public_number=next_number,
                name=name,
                description=description,
                price=price,
                stock=0,
                unlimited_stock=True,
                system_key=key,
                effect_type=effect_type,
                minimum_rank_order=minimum_rank_order,
                enabled=True,
                created_at=now,
            )
        )
        next_number += 1
    with op.batch_alter_table("items") as batch:
        batch.alter_column("public_number", nullable=False)
        batch.create_unique_constraint("uq_items_public_number", ["public_number"])
        batch.create_unique_constraint("uq_items_system_key", ["system_key"])

    op.create_table(
        "shop_purchases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_message_id", name="uq_shop_purchase_inbound"),
    )
    op.create_table(
        "shop_purchase_daily_usage",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "usage_date", "category", name="uq_shop_purchase_daily"
        ),
    )
    op.create_table(
        "shop_daily_bonuses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("ai_total", sa.Integer(), nullable=False),
        sa.Column("ai_used", sa.Integer(), nullable=False),
        sa.Column("multiplayer_total", sa.Integer(), nullable=False),
        sa.Column("multiplayer_used", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_shop_daily_bonus"),
    )
    op.create_table(
        "shop_multiplayer_daily_starts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("play_date", sa.Date(), nullable=False),
        sa.Column("game_type", sa.String(length=32), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "play_date", "game_type", name="uq_shop_multiplayer_daily_start"
        ),
    )
    op.create_table(
        "shop_item_uses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_message_id", name="uq_shop_item_use_inbound"),
    )
    op.create_table(
        "adult_card_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_number", sa.Integer(), nullable=False),
        sa.Column("item_use_id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("source_inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("scene", sa.String(length=200), nullable=True),
        sa.Column("desired_participant_count", sa.Integer(), nullable=True),
        sa.Column("expected_recipient_count", sa.Integer(), nullable=False),
        sa.Column("stage_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["item_use_id"], ["shop_item_uses.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_inbound_message_id"], ["inbound_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_use_id", name="uq_adult_session_item_use"),
        sa.UniqueConstraint("public_number", name="uq_adult_session_public_number"),
    )
    op.create_index(
        "ix_adult_card_sessions_due",
        "adult_card_sessions",
        ["state", "stage_deadline", "consent_deadline"],
    )
    op.create_table(
        "adult_card_participants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_order", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("authorization_outbound_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["authorization_outbound_id"], ["outbound_messages.id"]
        ),
        sa.ForeignKeyConstraint(["session_id"], ["adult_card_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_id", "user_id", name="uq_adult_participant_session_user"
        ),
    )
    op.create_table(
        "shop_scene_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("lease_worker_id", sa.String(length=255), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("failure_summary", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["adult_card_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_shop_scene_job_session"),
    )
    op.create_index(
        "ix_shop_scene_jobs_claim",
        "shop_scene_jobs",
        ["status", "lease_expires_at", "created_at"],
    )
    op.create_table(
        "shop_common_sense_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["adult_card_sessions.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_shop_common_session"),
    )
    op.create_index(
        "ix_shop_common_state_due", "shop_common_sense_states", ["state", "ends_at"]
    )
    op.create_index(
        "ux_shop_common_active_target",
        "shop_common_sense_states",
        ["target_user_id"],
        unique=True,
        postgresql_where=sa.text("state = 'active'"),
        sqlite_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "shop_session_number_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.bulk_insert(
        sa.table(
            "shop_session_number_counters",
            sa.column("id", sa.Integer()),
            sa.column("next_number", sa.Integer()),
        ),
        [{"id": 1, "next_number": 1}],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("shop_session_number_counters"):
        return
    if inspector.has_table("command_definitions"):
        op.execute(
            sa.text(
                "UPDATE command_definitions SET syntax = '/发奖金 员工名 金额；/发奖金 全部 金额' "
                "WHERE command = '/发奖金'"
            )
        )
    op.drop_table("shop_session_number_counters")
    op.drop_index("ux_shop_common_active_target", table_name="shop_common_sense_states")
    op.drop_index("ix_shop_common_state_due", table_name="shop_common_sense_states")
    op.drop_table("shop_common_sense_states")
    op.drop_index("ix_shop_scene_jobs_claim", table_name="shop_scene_jobs")
    op.drop_table("shop_scene_jobs")
    op.drop_table("adult_card_participants")
    op.drop_index("ix_adult_card_sessions_due", table_name="adult_card_sessions")
    op.drop_table("adult_card_sessions")
    op.drop_table("shop_item_uses")
    op.drop_table("shop_multiplayer_daily_starts")
    op.drop_table("shop_daily_bonuses")
    op.drop_table("shop_purchase_daily_usage")
    op.drop_table("shop_purchases")
    connection = op.get_bind()
    if inspector.has_table("user_items"):
        connection.execute(
            sa.text(
                "DELETE FROM user_items WHERE item_id IN "
                "(SELECT id FROM items WHERE system_key IS NOT NULL)"
            )
        )
    connection.execute(sa.text("DELETE FROM items WHERE system_key IS NOT NULL"))
    with op.batch_alter_table("items") as batch:
        batch.drop_constraint("uq_items_system_key", type_="unique")
        batch.drop_constraint("uq_items_public_number", type_="unique")
        batch.drop_column("minimum_rank_order")
        batch.drop_column("effect_type")
        batch.drop_column("system_key")
        batch.drop_column("unlimited_stock")
        batch.drop_column("public_number")
    with op.batch_alter_table("group_chats") as batch:
        batch.drop_column("adult_shop_enabled")
    if inspector.has_table("texas_holdem_games"):
        with op.batch_alter_table("texas_holdem_games") as batch:
            batch.drop_column("start_quota_source")
