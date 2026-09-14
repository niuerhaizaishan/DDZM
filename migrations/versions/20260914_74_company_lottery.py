"""Add the company double color ball lottery."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "20260914_74"
down_revision: str | None = "20260909_73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


POOL_SEED = 100
PRIMARY_GROUP_CHAT_ID = "00000000-0000-0000-0000-000000000001"
LOTTERY_KNOWLEDGE_CARD_ID = UUID("1f4b0c62-5a17-4a6e-8f2d-6c9e3ab5d704")


def _create_settings() -> None:
    op.create_table(
        "company_lottery_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("red_pool", sa.Integer(), nullable=False),
        sa.Column("red_count", sa.Integer(), nullable=False),
        sa.Column("blue_pool", sa.Integer(), nullable=False),
        sa.Column("ticket_price", sa.Integer(), nullable=False),
        sa.Column("head_prize", sa.Integer(), nullable=False),
        sa.Column("second_prize", sa.Integer(), nullable=False),
        sa.Column("third_prize", sa.Integer(), nullable=False),
        sa.Column("fourth_prize", sa.Integer(), nullable=False),
        sa.Column("fifth_prize", sa.Integer(), nullable=False),
        sa.Column("pool_ceiling", sa.Integer(), nullable=False),
        sa.Column("pool_seed", sa.Integer(), nullable=False),
        sa.Column("per_person_cap", sa.Integer(), nullable=False),
        sa.Column("max_tickets_per_day", sa.Integer(), nullable=False),
        sa.Column("max_tickets_per_round", sa.Integer(), nullable=False),
        sa.Column("draw_hour", sa.Integer(), nullable=False),
        sa.Column("draw_minute", sa.Integer(), nullable=False),
        sa.Column("close_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("notify_offset_minutes", sa.Integer(), nullable=False),
        sa.Column("draft_timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("welfare_enabled", sa.Boolean(), nullable=False),
        sa.Column("welfare_per_person", sa.Integer(), nullable=False),
        sa.Column("welfare_min_tenure_hours", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def _create_rounds() -> None:
    op.create_table(
        "company_lottery_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("open_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draw_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True)),
        sa.Column("commit_hash", sa.String(length=64), nullable=False),
        sa.Column("red_1", sa.Integer()),
        sa.Column("red_2", sa.Integer()),
        sa.Column("red_3", sa.Integer()),
        sa.Column("red_4", sa.Integer()),
        sa.Column("blue", sa.Integer()),
        sa.Column("salt", sa.String(length=64)),
        sa.Column("tickets_sold", sa.Integer(), nullable=False),
        sa.Column("gross_amount", sa.Integer(), nullable=False),
        sa.Column("pool_opening", sa.Integer(), nullable=False),
        sa.Column("pool_overflow", sa.Integer(), nullable=False),
        sa.Column("pool_available", sa.Integer(), nullable=False),
        sa.Column("pool_closing", sa.Integer(), nullable=False),
        sa.Column("payable", sa.Integer(), nullable=False),
        sa.Column("paid_total", sa.Integer(), nullable=False),
        sa.Column("haircut_ratio", sa.Numeric(precision=5, scale=4)),
        sa.Column("capped_count", sa.Integer(), nullable=False),
        sa.Column("winner_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("drawn_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('open', 'closed', 'drawn', 'cancelled')",
            name="ck_company_lottery_round_state",
        ),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("group_chat_id", "round_number"),
    )
    op.create_index(
        "ux_company_lottery_one_open",
        "company_lottery_rounds",
        ["group_chat_id"],
        unique=True,
        sqlite_where=sa.text("state = 'open'"),
        postgresql_where=sa.text("state = 'open'"),
    )
    op.create_index(
        "ix_company_lottery_rounds_state_draw",
        "company_lottery_rounds",
        ["state", "draw_at"],
    )


def _create_bets() -> None:
    op.create_table(
        "company_lottery_bets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("red_1", sa.Integer(), nullable=False),
        sa.Column("red_2", sa.Integer(), nullable=False),
        sa.Column("red_3", sa.Integer(), nullable=False),
        sa.Column("red_4", sa.Integer(), nullable=False),
        sa.Column("blue", sa.Integer(), nullable=False),
        sa.Column("ticket_key", sa.String(length=24), nullable=False),
        sa.Column("cost", sa.Integer(), nullable=False),
        sa.Column("is_quick_pick", sa.Boolean(), nullable=False),
        sa.Column("prize_tier", sa.String(length=12)),
        sa.Column("prize_amount", sa.Integer(), nullable=False),
        sa.Column("merited_amount", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.ForeignKeyConstraint(["round_id"], ["company_lottery_rounds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "user_id", "ticket_key"),
    )
    op.create_index(
        "ix_company_lottery_bets_round_user",
        "company_lottery_bets",
        ["round_id", "user_id"],
    )
    op.create_index(
        "ix_company_lottery_bets_created_at", "company_lottery_bets", ["created_at"]
    )
    op.create_index(
        "ix_company_lottery_bets_inbound",
        "company_lottery_bets",
        ["inbound_message_id"],
    )


def _create_drafts() -> None:
    op.create_table(
        "company_lottery_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid(), nullable=False),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("tickets", sa.JSON(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["round_id"], ["company_lottery_rounds.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )


def _create_pool_ledger() -> None:
    op.create_table(
        "company_lottery_pool_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid()),
        sa.Column("account", sa.String(length=16), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "account IN ('pool', 'adjustment')",
            name="ck_company_lottery_ledger_account",
        ),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["round_id"], ["company_lottery_rounds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_lottery_ledger_account",
        "company_lottery_pool_ledger",
        ["group_chat_id", "account", "created_at"],
    )


def _create_welfare() -> None:
    op.create_table(
        "company_lottery_welfare",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("round_id", sa.Uuid()),
        sa.Column("employee_count", sa.Integer(), nullable=False),
        sa.Column("per_person", sa.Integer(), nullable=False),
        sa.Column("paid_total", sa.Integer(), nullable=False),
        sa.Column("fund_before", sa.Integer(), nullable=False),
        sa.Column("fund_after", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["round_id"], ["company_lottery_rounds.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_lottery_welfare_group",
        "company_lottery_welfare",
        ["group_chat_id", "created_at"],
    )
    op.create_table(
        "company_lottery_welfare_payouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("welfare_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["welfare_id"], ["company_lottery_welfare.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("welfare_id", "user_id"),
    )
    op.create_index(
        "ix_company_lottery_welfare_payouts_user",
        "company_lottery_welfare_payouts",
        ["user_id", "created_at"],
    )


def _seed_settings() -> None:
    settings = sa.table(
        "company_lottery_settings",
        sa.column("id", sa.Integer()),
        sa.column("enabled", sa.Boolean()),
        sa.column("red_pool", sa.Integer()),
        sa.column("red_count", sa.Integer()),
        sa.column("blue_pool", sa.Integer()),
        sa.column("ticket_price", sa.Integer()),
        sa.column("head_prize", sa.Integer()),
        sa.column("second_prize", sa.Integer()),
        sa.column("third_prize", sa.Integer()),
        sa.column("fourth_prize", sa.Integer()),
        sa.column("fifth_prize", sa.Integer()),
        sa.column("pool_ceiling", sa.Integer()),
        sa.column("pool_seed", sa.Integer()),
        sa.column("per_person_cap", sa.Integer()),
        sa.column("max_tickets_per_day", sa.Integer()),
        sa.column("max_tickets_per_round", sa.Integer()),
        sa.column("draw_hour", sa.Integer()),
        sa.column("draw_minute", sa.Integer()),
        sa.column("close_offset_minutes", sa.Integer()),
        sa.column("notify_offset_minutes", sa.Integer()),
        sa.column("draft_timeout_minutes", sa.Integer()),
        sa.column("welfare_enabled", sa.Boolean()),
        sa.column("welfare_per_person", sa.Integer()),
        sa.column("welfare_min_tenure_hours", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now().astimezone()
    op.get_bind().execute(
        settings.insert().values(
            id=1,
            enabled=True,
            red_pool=10,
            red_count=4,
            blue_pool=6,
            ticket_price=2,
            head_prize=100,
            second_prize=50,
            third_prize=15,
            fourth_prize=5,
            fifth_prize=1,
            pool_ceiling=200,
            pool_seed=POOL_SEED,
            per_person_cap=100,
            max_tickets_per_day=5,
            max_tickets_per_round=2000,
            draw_hour=22,
            draw_minute=0,
            close_offset_minutes=10,
            notify_offset_minutes=5,
            draft_timeout_minutes=15,
            welfare_enabled=True,
            welfare_per_person=1,
            welfare_min_tenure_hours=0,
            created_at=now,
            updated_at=now,
        )
    )


def _seed_pool() -> None:
    """首期由系统注入启动奖池，之后不再额外注入。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    group_ids = {UUID(PRIMARY_GROUP_CHAT_ID)}
    if inspector.has_table("group_chats"):
        groups = sa.table("group_chats", sa.column("id", sa.Uuid()))
        existing = [row[0] for row in bind.execute(sa.select(groups.c.id))]
        group_ids |= set(existing)

    ledger = sa.table(
        "company_lottery_pool_ledger",
        sa.column("id", sa.Uuid()),
        sa.column("group_chat_id", sa.Uuid()),
        sa.column("round_id", sa.Uuid()),
        sa.column("account", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("amount", sa.Integer()),
        sa.column("balance_after", sa.Integer()),
        sa.column("note", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now().astimezone()
    for group_id in group_ids:
        bind.execute(
            ledger.insert().values(
                id=uuid4(),
                group_chat_id=group_id,
                round_id=None,
                account="pool",
                kind="deposit",
                amount=POOL_SEED,
                balance_after=POOL_SEED,
                note="上线启动奖池",
                created_at=now,
            )
        )


def _seed_knowledge_card() -> None:
    """知识卡：规则说明须如实写明长期期望返回约 1.19 摸鱼币。"""
    if not sa.inspect(op.get_bind()).has_table("ai_knowledge_cards"):
        return
    cards = sa.table(
        "ai_knowledge_cards",
        sa.column("id", sa.Uuid()),
        sa.column("topic", sa.String()),
        sa.column("title", sa.String()),
        sa.column("keywords", sa.JSON()),
        sa.column("content", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("priority", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now().astimezone()
    op.bulk_insert(
        cards,
        [
            {
                "id": LOTTERY_KNOWLEDGE_CARD_ID,
                "topic": "company_lottery",
                "title": "公司双色球",
                "keywords": ["公司双色球", "彩票", "购买彩票", "机选", "开奖", "奖池"],
                "content": (
                    "公司双色球每期红球从 01-10 选 4 个不重复号码、蓝球从 01-06 选 1 个，"
                    "共 1,260 种组合。发送 /购买彩票 03 07 09 10 + 05 手选一注，"
                    "/购买彩票 机选 [注数] 随机买，/购买彩票 N 注 可逐注填写后再 /确认彩票；"
                    "/彩票 看本期规则与概率，/我的彩票 看自己的投注与收益，/彩票验证 期号 可核对已开奖号码与哈希。"
                    "每注 2 摸鱼币，每人每个自然日最多 5 注；开奖前 10 分钟停售，每晚 22:00 开奖。"
                    "奖级固定：一等奖 100、二等奖 50、三等奖 15、四等奖 5、五等奖 1，"
                    "任意中奖概率 26.59%，每注长期期望返回约 1.19 摸鱼币，整体是回收货币而不是发钱。"
                    "奖池上限 200 摸鱼币，超出部分转入调节金；调节金累计到当前员工总数时全员各发 1 摸鱼币。"
                ),
                "enabled": True,
                "priority": 100,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def upgrade() -> None:
    _create_settings()
    _create_rounds()
    _create_bets()
    _create_drafts()
    _create_pool_ledger()
    _create_welfare()
    _seed_settings()
    _seed_pool()
    _seed_knowledge_card()


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_knowledge_cards"):
        cards = sa.table("ai_knowledge_cards", sa.column("id", sa.Uuid()))
        op.get_bind().execute(
            cards.delete().where(cards.c.id == LOTTERY_KNOWLEDGE_CARD_ID)
        )
    op.drop_index(
        "ix_company_lottery_welfare_payouts_user",
        table_name="company_lottery_welfare_payouts",
    )
    op.drop_table("company_lottery_welfare_payouts")
    op.drop_index(
        "ix_company_lottery_welfare_group", table_name="company_lottery_welfare"
    )
    op.drop_table("company_lottery_welfare")
    op.drop_index(
        "ix_company_lottery_ledger_account",
        table_name="company_lottery_pool_ledger",
    )
    op.drop_table("company_lottery_pool_ledger")
    op.drop_table("company_lottery_drafts")
    op.drop_index(
        "ix_company_lottery_bets_created_at", table_name="company_lottery_bets"
    )
    op.drop_index(
        "ix_company_lottery_bets_round_user", table_name="company_lottery_bets"
    )
    op.drop_table("company_lottery_bets")
    op.drop_index(
        "ix_company_lottery_rounds_state_draw", table_name="company_lottery_rounds"
    )
    op.drop_index(
        "ux_company_lottery_one_open", table_name="company_lottery_rounds"
    )
    op.drop_table("company_lottery_rounds")
    op.drop_table("company_lottery_settings")
