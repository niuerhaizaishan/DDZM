"""Add audited company-season reset receipts."""

from alembic import op
import sqlalchemy as sa


revision = "20261111_112_company_seasons"
down_revision = "20261109_merge_permanent_honors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_seasons",
        sa.Column("code", sa.String(16), primary_key=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_by", sa.String(128), nullable=False),
        sa.Column("carryover_numerator", sa.Integer(), nullable=False),
        sa.Column("carryover_denominator", sa.Integer(), nullable=False),
        sa.Column("preview_digest", sa.String(64), nullable=False),
        sa.Column("rules_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "carryover_numerator >= 0 AND "
            "carryover_denominator > 0 AND "
            "carryover_numerator <= carryover_denominator",
            name="ck_company_season_carryover_ratio",
        ),
    )
    op.create_table(
        "company_season_settlements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "season_code",
            sa.String(16),
            sa.ForeignKey("company_seasons.code"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("old_rank_id", sa.Uuid(), sa.ForeignKey("ranks.id")),
        sa.Column("new_rank_id", sa.Uuid(), sa.ForeignKey("ranks.id"), nullable=False),
        sa.Column("old_balance", sa.Integer(), nullable=False),
        sa.Column("gross_value", sa.Integer(), nullable=False),
        sa.Column("new_balance", sa.Integer(), nullable=False),
        sa.Column("balance_delta", sa.Integer(), nullable=False),
        sa.Column("breakdown", sa.JSON(), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "season_code", "user_id", name="uq_company_season_settlement_user"
        ),
    )
    op.create_index(
        "ix_company_season_settlements_user",
        "company_season_settlements",
        ["user_id", "season_code"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT 1 FROM company_season_settlements LIMIT 1")
    ):
        raise RuntimeError(
            "Company season settlement history exists and cannot be removed"
        )
    op.drop_index(
        "ix_company_season_settlements_user",
        table_name="company_season_settlements",
    )
    op.drop_table("company_season_settlements")
    op.drop_table("company_seasons")
