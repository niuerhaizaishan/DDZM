"""Snapshot lottery rules when a round opens."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_75"
down_revision: str | None = "20260914_74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "company_lottery_rounds",
        sa.Column("rules_snapshot", sa.JSON(), nullable=True),
    )
    bind = op.get_bind()
    settings = sa.table(
        "company_lottery_settings",
        sa.column("red_pool"),
        sa.column("red_count"),
        sa.column("blue_pool"),
        sa.column("ticket_price"),
        sa.column("head_prize"),
        sa.column("second_prize"),
        sa.column("third_prize"),
        sa.column("fourth_prize"),
        sa.column("fifth_prize"),
        sa.column("pool_ceiling"),
        sa.column("per_person_cap"),
        sa.column("max_tickets_per_day"),
        sa.column("max_tickets_per_round"),
    )
    bind.execute(settings.update().values(red_count=4))
    row = bind.execute(sa.select(settings)).mappings().first()
    if row is None:
        return
    snapshot = {
        "red_pool": row["red_pool"],
        "red_count": row["red_count"],
        "blue_pool": row["blue_pool"],
        "ticket_price": row["ticket_price"],
        "head_prize": row["head_prize"],
        "second_prize": row["second_prize"],
        "third_prize": row["third_prize"],
        "fourth_prize": row["fourth_prize"],
        "fifth_prize": row["fifth_prize"],
        "pool_ceiling": row["pool_ceiling"],
        "per_person_cap": row["per_person_cap"],
        "max_tickets_per_day": row["max_tickets_per_day"],
        "max_tickets_per_round": row["max_tickets_per_round"],
    }
    rounds = sa.table(
        "company_lottery_rounds",
        sa.column("rules_snapshot", sa.JSON()),
    )
    bind.execute(
        rounds.update().where(rounds.c.rules_snapshot.is_(None)).values(
            rules_snapshot=snapshot
        )
    )


def downgrade() -> None:
    op.drop_column("company_lottery_rounds", "rules_snapshot")
