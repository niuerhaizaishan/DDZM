"""liar dice timeouts: signup / continue / deal deadlines

Revision ID: 20261011_103
Revises: 20261010_102
Create Date: 2026-10-11
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20261011_103"
down_revision: str | None = "20261010_102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "liar_dice_settings",
        sa.Column(
            "signup_timeout_minutes", sa.Integer(), nullable=False, server_default="5"
        ),
    )
    op.add_column(
        "liar_dice_settings",
        sa.Column(
            "continue_timeout_minutes", sa.Integer(), nullable=False, server_default="5"
        ),
    )
    op.add_column(
        "liar_dice_settings",
        sa.Column(
            "deal_timeout_seconds", sa.Integer(), nullable=False, server_default="180"
        ),
    )
    op.add_column(
        "liar_dice_games", sa.Column("round_end_deadline", sa.DateTime(timezone=True))
    )
    op.add_column(
        "liar_dice_games", sa.Column("dealing_deadline", sa.DateTime(timezone=True))
    )


def downgrade() -> None:
    op.drop_column("liar_dice_games", "dealing_deadline")
    op.drop_column("liar_dice_games", "round_end_deadline")
    op.drop_column("liar_dice_settings", "deal_timeout_seconds")
    op.drop_column("liar_dice_settings", "continue_timeout_minutes")
    op.drop_column("liar_dice_settings", "signup_timeout_minutes")
