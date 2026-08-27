"""Configure dark market identity disclosure duration."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_61"
down_revision: str | None = "20260827_60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("dark_market_settings"):
        return
    existing = {
        column["name"] for column in inspector.get_columns("dark_market_settings")
    }
    with op.batch_alter_table("dark_market_settings") as batch:
        if "disclosure_duration_value" not in existing:
            batch.add_column(
                sa.Column(
                    "disclosure_duration_value",
                    sa.Integer(),
                    nullable=False,
                    server_default="10",
                )
            )
        if "disclosure_duration_unit" not in existing:
            batch.add_column(
                sa.Column(
                    "disclosure_duration_unit",
                    sa.String(length=16),
                    nullable=False,
                    server_default="minute",
                )
            )
        batch.create_check_constraint(
            "ck_dark_market_disclosure_duration_unit",
            "disclosure_duration_unit IN ('minute', 'hour', 'day')",
        )
        batch.create_check_constraint(
            "ck_dark_market_disclosure_duration_range",
            "(disclosure_duration_unit = 'minute' AND "
            "disclosure_duration_value BETWEEN 1 AND 43200) OR "
            "(disclosure_duration_unit = 'hour' AND "
            "disclosure_duration_value BETWEEN 1 AND 720) OR "
            "(disclosure_duration_unit = 'day' AND "
            "disclosure_duration_value BETWEEN 1 AND 30)",
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("dark_market_settings"):
        return
    existing = {
        column["name"] for column in inspector.get_columns("dark_market_settings")
    }
    with op.batch_alter_table("dark_market_settings") as batch:
        batch.drop_constraint(
            "ck_dark_market_disclosure_duration_range", type_="check"
        )
        batch.drop_constraint(
            "ck_dark_market_disclosure_duration_unit", type_="check"
        )
        if "disclosure_duration_unit" in existing:
            batch.drop_column("disclosure_duration_unit")
        if "disclosure_duration_value" in existing:
            batch.drop_column("disclosure_duration_value")
