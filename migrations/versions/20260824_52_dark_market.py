"""Add the persistent dark market exchange."""

from collections.abc import Sequence
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20260824_52"
down_revision: str | None = "20260820_51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dark_market_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("announcement_group_id", sa.Uuid(), nullable=True),
        sa.Column("duration_hours", sa.Integer(), nullable=False),
        sa.Column("fee_percent", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "duration_hours BETWEEN 1 AND 24", name="ck_dark_market_duration_hours"
        ),
        sa.CheckConstraint(
            "fee_percent BETWEEN 1 AND 100", name="ck_dark_market_fee_percent"
        ),
        sa.ForeignKeyConstraint(["announcement_group_id"], ["group_chats.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    settings = sa.table(
        "dark_market_settings",
        *(sa.column(name) for name in (
            "id", "enabled", "announcement_group_id", "duration_hours",
            "fee_percent", "version",
        )),
    )
    op.bulk_insert(settings, [{
        "id": 1,
        "enabled": True,
        "announcement_group_id": None,
        "duration_hours": 3,
        "fee_percent": 5,
        "version": 0,
    }])

    op.create_table(
        "dark_market_rank_limits",
        sa.Column("rank_id", sa.Uuid(), nullable=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False),
        sa.CheckConstraint("daily_limit >= -1", name="ck_dark_market_rank_daily_limit"),
        sa.ForeignKeyConstraint(["rank_id"], ["ranks.id"]),
        sa.PrimaryKeyConstraint("rank_id"),
    )
    connection = op.get_bind()
    ranks = connection.execute(
        sa.text("SELECT id, sort_order FROM ranks ORDER BY sort_order")
    ).all()
    rank_limits = sa.table(
        "dark_market_rank_limits",
        sa.column("rank_id", sa.Uuid()),
        sa.column("daily_limit", sa.Integer()),
    )
    defaults = (1, 1, 2, 2, 3, 3, 4, 4, 5, 5, -1)
    if ranks:
        op.bulk_insert(
            rank_limits,
            [
                {
                    "rank_id": rank_id if isinstance(rank_id, UUID) else UUID(str(rank_id)),
                    "daily_limit": defaults[min(sort_order, len(defaults)) - 1],
                }
                for rank_id, sort_order in ranks
            ],
        )

    op.create_table(
        "dark_market_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("step", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=True),
        sa.Column("purpose", sa.String(length=100), nullable=True),
        sa.Column("details", sa.String(length=500), nullable=True),
        sa.Column("gender", sa.String(length=16), nullable=True),
        sa.Column("starting_price", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "step IN ('name', 'purpose', 'details', 'gender', 'starting_price', 'preview')",
            name="ck_dark_market_draft_step",
        ),
        sa.CheckConstraint(
            "gender IS NULL OR gender IN ('male', 'female', 'private')",
            name="ck_dark_market_draft_gender",
        ),
        sa.CheckConstraint(
            "starting_price IS NULL OR starting_price BETWEEN 1 AND 99999",
            name="ck_dark_market_draft_starting_price",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_dark_market_drafts_user_id"),
    )

    op.create_table(
        "dark_market_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("public_number", sa.Integer(), nullable=False),
        sa.Column("seller_user_id", sa.Uuid(), nullable=False),
        sa.Column("announcement_group_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("details", sa.String(length=500), nullable=False),
        sa.Column("gender", sa.String(length=16), nullable=False),
        sa.Column("starting_price", sa.Integer(), nullable=False),
        sa.Column("duration_hours_snapshot", sa.Integer(), nullable=False),
        sa.Column("fee_percent_snapshot", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("buyer_user_id", sa.Uuid(), nullable=True),
        sa.Column("final_amount", sa.Integer(), nullable=True),
        sa.Column("fee_amount", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('active', 'sold', 'unsold', 'force_delisted')",
            name="ck_dark_market_listing_state",
        ),
        sa.CheckConstraint(
            "gender IN ('male', 'female', 'private')",
            name="ck_dark_market_listing_gender",
        ),
        sa.CheckConstraint(
            "starting_price BETWEEN 1 AND 99999",
            name="ck_dark_market_listing_starting_price",
        ),
        sa.ForeignKeyConstraint(["announcement_group_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["buyer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["seller_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "public_number", name="uq_dark_market_listings_public_number"
        ),
    )
    op.create_index(
        "ix_dark_market_listings_due",
        "dark_market_listings",
        ["state", "ends_at"],
        unique=False,
    )

    op.create_table(
        "dark_market_bids",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("bidder_user_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "amount BETWEEN 1 AND 99999", name="ck_dark_market_bid_amount"
        ),
        sa.CheckConstraint(
            "state IN ('current', 'refunded', 'settled')",
            name="ck_dark_market_bid_state",
        ),
        sa.ForeignKeyConstraint(["bidder_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.ForeignKeyConstraint(["listing_id"], ["dark_market_listings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inbound_message_id", name="uq_dark_market_bid_inbound"),
    )
    op.create_index(
        "ix_dark_market_bids_listing_created",
        "dark_market_bids",
        ["listing_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ux_dark_market_one_current_bid",
        "dark_market_bids",
        ["listing_id"],
        unique=True,
        postgresql_where=sa.text("state = 'current'"),
        sqlite_where=sa.text("state = 'current'"),
    )

    op.create_table(
        "dark_market_disclosures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("listing_id", sa.Uuid(), nullable=False),
        sa.Column("seller_user_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_user_id", sa.Uuid(), nullable=False),
        sa.Column("seller_choice", sa.Boolean(), nullable=True),
        sa.Column("buyer_choice", sa.Boolean(), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('pending', 'revealed', 'anonymous')",
            name="ck_dark_market_disclosure_state",
        ),
        sa.ForeignKeyConstraint(["buyer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["listing_id"], ["dark_market_listings.id"]),
        sa.ForeignKeyConstraint(["seller_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", name="uq_dark_market_disclosure_listing"),
    )

    op.create_table(
        "dark_market_daily_listings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.CheckConstraint("count >= 0", name="ck_dark_market_daily_listing_count"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "usage_date", name="uq_dark_market_daily_listing_user_date"
        ),
    )

    op.create_table(
        "dark_market_number_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("next_number", sa.Integer(), nullable=False),
        sa.CheckConstraint("next_number > 0", name="ck_dark_market_next_number"),
        sa.PrimaryKeyConstraint("id"),
    )
    counters = sa.table(
        "dark_market_number_counters",
        sa.column("id", sa.Integer()),
        sa.column("next_number", sa.Integer()),
    )
    op.bulk_insert(counters, [{"id": 1, "next_number": 1}])


def downgrade() -> None:
    op.drop_table("dark_market_number_counters")
    op.drop_table("dark_market_daily_listings")
    op.drop_table("dark_market_disclosures")
    op.drop_index("ux_dark_market_one_current_bid", table_name="dark_market_bids")
    op.drop_index("ix_dark_market_bids_listing_created", table_name="dark_market_bids")
    op.drop_table("dark_market_bids")
    op.drop_index("ix_dark_market_listings_due", table_name="dark_market_listings")
    op.drop_table("dark_market_listings")
    op.drop_table("dark_market_drafts")
    op.drop_table("dark_market_rank_limits")
    op.drop_table("dark_market_settings")
