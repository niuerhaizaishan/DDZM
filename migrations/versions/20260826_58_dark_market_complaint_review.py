"""Add dark market complaint review state."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_58"
down_revision: str | None = "20260826_57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_STATE_CHECK = (
    "state IN ('active', 'awaiting_receipt', 'complaint_pending', 'sold', "
    "'complained', 'unsold', 'force_delisted')"
)
_OLD_STATE_CHECK = (
    "state IN ('active', 'awaiting_receipt', 'sold', 'complained', "
    "'unsold', 'force_delisted')"
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("dark_market_listings"):
        return
    with op.batch_alter_table("dark_market_listings") as batch:
        batch.drop_constraint("ck_dark_market_listing_state", type_="check")
        batch.add_column(
            sa.Column("complaint_requested_at", sa.DateTime(timezone=True))
        )
        batch.add_column(
            sa.Column("complaint_reviewed_at", sa.DateTime(timezone=True))
        )
        batch.add_column(sa.Column("complaint_reviewed_by", sa.String(length=100)))
        batch.add_column(sa.Column("complaint_decision", sa.String(length=16)))
        batch.create_check_constraint(
            "ck_dark_market_listing_state", _NEW_STATE_CHECK
        )
        batch.create_check_constraint(
            "ck_dark_market_listing_complaint_decision",
            "complaint_decision IS NULL OR complaint_decision IN ('approved', 'rejected')",
        )
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("command_reply_templates"):
        op.execute(
            "UPDATE command_reply_templates "
            "SET scenario = 'complaint_pending', "
            "template = '暗网商品 #{商品编号} 已进入投诉审核，资金继续冻结，等待董事会审核。' "
            "WHERE command = '/投诉' AND scenario = 'complained'"
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("dark_market_listings"):
        return
    if inspector.has_table("command_reply_templates"):
        op.execute(
            "UPDATE command_reply_templates "
            "SET scenario = 'complained', "
            "template = '暗网商品 #{商品编号} 投诉已处理，成交款已退还，卖家已被处罚。' "
            "WHERE command = '/投诉' AND scenario = 'complaint_pending'"
        )
    op.execute(
        "UPDATE dark_market_listings SET state = 'awaiting_receipt' "
        "WHERE state = 'complaint_pending'"
    )
    with op.batch_alter_table("dark_market_listings") as batch:
        batch.drop_constraint(
            "ck_dark_market_listing_complaint_decision", type_="check"
        )
        batch.drop_constraint("ck_dark_market_listing_state", type_="check")
        batch.drop_column("complaint_decision")
        batch.drop_column("complaint_reviewed_by")
        batch.drop_column("complaint_reviewed_at")
        batch.drop_column("complaint_requested_at")
        batch.create_check_constraint(
            "ck_dark_market_listing_state", _OLD_STATE_CHECK
        )
