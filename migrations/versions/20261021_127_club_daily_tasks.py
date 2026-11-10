"""make Club activity rewards daily except employment

Revision ID: 20261021_127
Revises: 20261021_126
"""

from alembic import op
import sqlalchemy as sa


revision = "20261021_127"
down_revision = "20261021_126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("club_task_claims", sa.Column("claim_date", sa.Date(), nullable=True))
    op.execute(sa.text(
        "UPDATE club_task_claims SET claim_date = "
        "(claimed_at AT TIME ZONE 'Asia/Shanghai')::date "
        "WHERE task_key <> 'employment'"
    ))
    op.drop_constraint(
        "club_task_claims_user_id_task_key_key",
        "club_task_claims",
        type_="unique",
    )
    op.create_check_constraint(
        "ck_club_task_claim_cycle",
        "club_task_claims",
        "(task_key = 'employment' AND claim_date IS NULL) OR "
        "(task_key <> 'employment' AND claim_date IS NOT NULL)",
    )
    op.create_index(
        "ux_club_task_claim_once",
        "club_task_claims",
        ["user_id", "task_key"],
        unique=True,
        postgresql_where=sa.text("task_key = 'employment'"),
    )
    op.create_index(
        "ux_club_task_claim_daily",
        "club_task_claims",
        ["user_id", "task_key", "claim_date"],
        unique=True,
        postgresql_where=sa.text("task_key <> 'employment'"),
    )


def downgrade() -> None:
    op.drop_index("ux_club_task_claim_daily", table_name="club_task_claims")
    op.drop_index("ux_club_task_claim_once", table_name="club_task_claims")
    op.drop_constraint("ck_club_task_claim_cycle", "club_task_claims", type_="check")
    op.execute(sa.text(
        "DELETE FROM club_task_claims older USING club_task_claims newer "
        "WHERE older.user_id = newer.user_id AND older.task_key = newer.task_key "
        "AND older.claimed_at < newer.claimed_at"
    ))
    op.create_unique_constraint(
        "club_task_claims_user_id_task_key_key",
        "club_task_claims",
        ["user_id", "task_key"],
    )
    op.drop_column("club_task_claims", "claim_date")
