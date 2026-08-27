"""Persist inbound image metadata for performance history."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260827_60"
down_revision: str | None = "20260826_59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("inbound_messages"):
        return
    existing = {column["name"] for column in inspector.get_columns("inbound_messages")}
    with op.batch_alter_table("inbound_messages") as batch:
        if "content_type" not in existing:
            batch.add_column(
                sa.Column(
                    "content_type",
                    sa.String(length=16),
                    nullable=False,
                    server_default="text",
                )
            )
        if "image_url" not in existing:
            batch.add_column(sa.Column("image_url", sa.Text()))
        if "image_alt" not in existing:
            batch.add_column(sa.Column("image_alt", sa.String(length=512)))
        if "image_width" not in existing:
            batch.add_column(sa.Column("image_width", sa.Integer()))
        if "image_height" not in existing:
            batch.add_column(sa.Column("image_height", sa.Integer()))
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("performance_messages"):
        indexes = {
            index["name"] for index in inspector.get_indexes("performance_messages")
        }
        if "ix_performance_messages_reservation_created" not in indexes:
            op.create_index(
                "ix_performance_messages_reservation_created",
                "performance_messages",
                ["reservation_id", "created_at", "id"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("inbound_messages"):
        return
    if inspector.has_table("performance_messages"):
        indexes = {
            index["name"] for index in inspector.get_indexes("performance_messages")
        }
        if "ix_performance_messages_reservation_created" in indexes:
            op.drop_index(
                "ix_performance_messages_reservation_created",
                table_name="performance_messages",
            )
    existing = {column["name"] for column in inspector.get_columns("inbound_messages")}
    with op.batch_alter_table("inbound_messages") as batch:
        for column_name in (
            "image_height",
            "image_width",
            "image_alt",
            "image_url",
            "content_type",
        ):
            if column_name in existing:
                batch.drop_column(column_name)
