"""Link dark market balance transactions to listings."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_59"
down_revision: str | None = "20260826_58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("balance_transactions"):
        return
    with op.batch_alter_table("balance_transactions") as batch:
        batch.add_column(sa.Column("dark_market_listing_id", sa.Uuid()))
        batch.create_foreign_key(
            "fk_balance_transactions_dark_market_listing_id",
            "dark_market_listings",
            ["dark_market_listing_id"],
            ["id"],
        )
        batch.create_index(
            "ix_balance_transactions_dark_market_listing_occurred",
            ["dark_market_listing_id", "occurred_at"],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("balance_transactions"):
        return
    with op.batch_alter_table("balance_transactions") as batch:
        batch.drop_index("ix_balance_transactions_dark_market_listing_occurred")
        batch.drop_constraint(
            "fk_balance_transactions_dark_market_listing_id", type_="foreignkey"
        )
        batch.drop_column("dark_market_listing_id")
