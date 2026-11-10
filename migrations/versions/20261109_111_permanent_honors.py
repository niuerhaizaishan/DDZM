"""Add season and manually granted permanent honors."""

from alembic import op
import sqlalchemy as sa

revision = "20261109_111_permanent_honors"
down_revision = "20261105_110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "honor_seasons",
        sa.Column("code", sa.String(8), primary_key=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by", sa.String(128), nullable=False),
        sa.Column("preview_digest", sa.String(64), nullable=False),
        sa.Column("issued_count", sa.Integer(), nullable=False),
    )
    with op.batch_alter_table("honor_awards") as batch:
        batch.alter_column("period_id", existing_type=sa.Uuid(), nullable=True)
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=True)
        batch.add_column(sa.Column("source", sa.String(12), server_default="weekly", nullable=False))
        batch.add_column(sa.Column("season_code", sa.String(8)))
        batch.add_column(sa.Column("source_details", sa.JSON()))
        batch.add_column(sa.Column("revoked_at", sa.DateTime(timezone=True)))
        batch.create_foreign_key("fk_honor_awards_season", "honor_seasons", ["season_code"], ["code"])
        batch.create_unique_constraint("uq_honor_awards_season_user", ["season_code", "user_id"])
        batch.create_check_constraint(
            "ck_honor_award_source",
            "(source = 'weekly' AND period_id IS NOT NULL AND expires_at IS NOT NULL "
            "AND season_code IS NULL AND revoked_at IS NULL) OR "
            "(source IN ('season', 'manual') AND period_id IS NULL AND expires_at IS NULL "
            "AND user_id IS NOT NULL AND ((source = 'season' AND season_code IS NOT NULL) "
            "OR (source = 'manual' AND season_code IS NULL)))",
        )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT 1 FROM honor_awards WHERE source <> 'weekly' LIMIT 1")):
        raise RuntimeError("Permanent honor history exists and cannot be removed by this downgrade")
    with op.batch_alter_table("honor_awards") as batch:
        batch.drop_constraint("ck_honor_award_source", type_="check")
        batch.drop_constraint("uq_honor_awards_season_user", type_="unique")
        batch.drop_constraint("fk_honor_awards_season", type_="foreignkey")
        batch.drop_column("revoked_at")
        batch.drop_column("source_details")
        batch.drop_column("season_code")
        batch.drop_column("source")
        batch.alter_column("expires_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.alter_column("period_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_table("honor_seasons")
