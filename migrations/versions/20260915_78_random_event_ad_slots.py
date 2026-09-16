"""Add the event ad slot tables (事件广告卡)."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_78"
down_revision: str | None = "20260915_77"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    _create_slots()
    _create_drafts()


def downgrade() -> None:
    op.drop_table("random_event_ad_slot_drafts")
    op.drop_index("ix_random_event_ad_slots_poll", table_name="random_event_ad_slots")
    op.drop_table("random_event_ad_slots")


def _create_slots() -> None:
    op.create_table(
        "random_event_ad_slots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="consumed",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["random_event_scenes.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["poll_id"], ["random_event_polls.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["random_event_poll_candidates.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "user_id"),
    )
    op.create_index(
        "ix_random_event_ad_slots_poll", "random_event_ad_slots", ["poll_id"]
    )


def _create_drafts() -> None:
    op.create_table(
        "random_event_ad_slot_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_id", sa.Uuid(), nullable=False),
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["poll_id"], ["random_event_polls.id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["random_event_scenes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
