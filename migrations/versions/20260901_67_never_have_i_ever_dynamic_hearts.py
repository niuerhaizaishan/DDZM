"""Allow Never Have I Ever hearts to scale with player count."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_67"
down_revision: str | None = "20260831_66"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("never_have_i_ever_players"):
        return
    with op.batch_alter_table("never_have_i_ever_players") as batch:
        batch.drop_constraint("ck_never_have_i_ever_hearts", type_="check")
        batch.create_check_constraint("ck_never_have_i_ever_hearts", "hearts >= 0")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("never_have_i_ever_players"):
        return
    with op.batch_alter_table("never_have_i_ever_players") as batch:
        batch.drop_constraint("ck_never_have_i_ever_hearts", type_="check")
        batch.create_check_constraint(
            "ck_never_have_i_ever_hearts", "hearts BETWEEN 0 AND 5"
        )
