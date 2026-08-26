"""Add random-event previews and deferred dark-market notices."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_56"
down_revision: str | None = "20260825_55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("random_event_schedules"):
        with op.batch_alter_table("random_event_schedules") as batch:
            batch.add_column(
                sa.Column("pre_notice_sent_at", sa.DateTime(timezone=True))
            )
    if not inspector.has_table("dark_market_deferred_notices"):
        op.create_table(
            "dark_market_deferred_notices",
            sa.Column("listing_id", sa.Uuid(), nullable=False),
            sa.Column("group_chat_id", sa.Uuid(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["listing_id"], ["dark_market_listings.id"]
            ),
            sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
            sa.PrimaryKeyConstraint("listing_id"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("dark_market_deferred_notices"):
        op.drop_table("dark_market_deferred_notices")
    if inspector.has_table("random_event_schedules"):
        with op.batch_alter_table("random_event_schedules") as batch:
            batch.drop_column("pre_notice_sent_at")
