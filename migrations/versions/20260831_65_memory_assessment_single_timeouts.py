"""Configure single-player memory assessment timeouts."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_65"
down_revision: str | None = "20260831_64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    op.add_column(
        "memory_assessment_settings",
        sa.Column(
            "single_answer_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
    )
    op.add_column(
        "memory_assessment_settings",
        sa.Column(
            "single_decision_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="15",
        ),
    )
    if dialect_name != "sqlite":
        op.alter_column(
            "memory_assessment_settings",
            "single_answer_timeout_seconds",
            server_default=None,
        )
        op.alter_column(
            "memory_assessment_settings",
            "single_decision_timeout_seconds",
            server_default=None,
        )


def downgrade() -> None:
    op.drop_column("memory_assessment_settings", "single_decision_timeout_seconds")
    op.drop_column("memory_assessment_settings", "single_answer_timeout_seconds")
