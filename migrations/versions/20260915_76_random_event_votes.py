"""Add the company-wide random event poll tables and vote settings."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_76"
down_revision: str | None = "20260915_75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VOTE_SETTINGS = (
    sa.Column(
        "vote_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
    ),
    sa.Column(
        "vote_close_offset_minutes",
        sa.Integer(),
        nullable=False,
        server_default="10",
    ),
    sa.Column(
        "vote_broadcast_interval_minutes",
        sa.Integer(),
        nullable=False,
        server_default="30",
    ),
    sa.Column(
        "vote_random_candidates", sa.Integer(), nullable=False, server_default="3"
    ),
    sa.Column("vote_ad_slot_limit", sa.Integer(), nullable=False, server_default="1"),
    sa.Column(
        "vote_fallback_minutes", sa.Integer(), nullable=False, server_default="30"
    ),
    sa.Column(
        "vote_allow_change", sa.Boolean(), nullable=False, server_default=sa.true()
    ),
)


def upgrade() -> None:
    _add_settings_columns()
    _create_polls()
    _create_candidates()
    _create_votes()


def downgrade() -> None:
    op.drop_table("random_event_poll_votes")
    op.drop_table("random_event_poll_candidates")
    op.drop_index("ix_random_event_polls_status_close", table_name="random_event_polls")
    op.drop_table("random_event_polls")
    # 与 upgrade 一样要有守卫：迁移基线用例里可能根本没有这张表
    if not sa.inspect(op.get_bind()).has_table("random_event_settings"):
        return
    for column in reversed(VOTE_SETTINGS):
        op.drop_column("random_event_settings", column.name)


def _add_settings_columns() -> None:
    if not sa.inspect(op.get_bind()).has_table("random_event_settings"):
        return
    for column in VOTE_SETTINGS:
        op.add_column("random_event_settings", column)


def _create_polls() -> None:
    op.create_table(
        "random_event_polls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_schedule_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("winner_candidate_id", sa.Uuid(), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_tally_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fallback_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_schedule_id"], ["random_event_schedules.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("target_schedule_id"),
    )
    op.create_index(
        "ix_random_event_polls_status_close",
        "random_event_polls",
        ["status", "closes_at"],
    )


def _create_candidates() -> None:
    op.create_table(
        "random_event_poll_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("scene_id", sa.Uuid(), nullable=True),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("scene_name", sa.String(length=64), nullable=True),
        sa.Column("event_name", sa.String(length=64), nullable=True),
        sa.Column("seat_summary", sa.String(length=255), nullable=True),
        sa.Column("author_name", sa.String(length=64), nullable=True),
        sa.Column("reward", sa.Integer(), nullable=True),
        sa.Column("target_rounds", sa.Integer(), nullable=True),
        sa.Column(
            "vacant", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["random_event_polls.id"]),
        sa.ForeignKeyConstraint(["scene_id"], ["random_event_scenes.id"]),
        sa.ForeignKeyConstraint(
            ["template_id"], ["random_event_scene_openings.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "position"),
        sa.UniqueConstraint("poll_id", "scene_id"),
    )


def _create_votes() -> None:
    op.create_table(
        "random_event_poll_votes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("poll_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["random_event_polls.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["random_event_poll_candidates.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "user_id"),
    )
