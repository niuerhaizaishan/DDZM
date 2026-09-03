"""Gate random event signup on delivered public notice."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_63"
down_revision: str | None = "20260830_62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("random_events"):
        return
    existing = {column["name"] for column in inspector.get_columns("random_events")}
    has_outbound_messages = inspector.has_table("outbound_messages")
    with op.batch_alter_table("random_events") as batch:
        if "signup_notice_outbound_id" not in existing:
            batch.add_column(sa.Column("signup_notice_outbound_id", sa.Uuid()))
            if has_outbound_messages:
                batch.create_foreign_key(
                    "fk_random_events_signup_notice_outbound_id",
                    "outbound_messages",
                    ["signup_notice_outbound_id"],
                    ["id"],
                )
            batch.create_index(
                "ix_random_events_signup_notice_outbound_id",
                ["signup_notice_outbound_id"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("random_events"):
        return
    existing = {column["name"] for column in inspector.get_columns("random_events")}
    if "signup_notice_outbound_id" not in existing:
        return
    foreign_keys = {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys("random_events")
    }
    with op.batch_alter_table("random_events") as batch:
        batch.drop_index("ix_random_events_signup_notice_outbound_id")
        if "fk_random_events_signup_notice_outbound_id" in foreign_keys:
            batch.drop_constraint(
                "fk_random_events_signup_notice_outbound_id", type_="foreignkey"
            )
        batch.drop_column("signup_notice_outbound_id")
