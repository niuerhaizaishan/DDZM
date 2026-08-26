"""Add public performance reservations."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260826_57"
down_revision: str | None = "20260826_56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LIVE = (
    "state IN ('pending_review', 'approved', 'previewed', 'waiting', "
    "'performing', 'tipping')"
)


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ai_activity_events"):
        with op.batch_alter_table("ai_activity_events") as batch:
            batch.alter_column(
                "detail",
                existing_type=sa.String(length=32),
                type_=sa.String(length=64),
                existing_nullable=True,
            )
    with op.batch_alter_table("group_chats") as batch:
        batch.add_column(
            sa.Column(
                "performances_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    op.create_table(
        "performance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("maximum_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "performance_settings",
            sa.column("id", sa.Integer()),
            sa.column("maximum_duration_minutes", sa.Integer()),
            sa.column("version", sa.Integer()),
        ),
        [{"id": 1, "maximum_duration_minutes": 360, "version": 0}],
    )
    op.create_table(
        "performance_reservations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=50), nullable=False),
        sa.Column("introduction", sa.String(length=500), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("cover_url", sa.Text()),
        sa.Column("cover_alt", sa.String(length=255)),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("pre_notice_sent_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("tipping_started_at", sa.DateTime(timezone=True)),
        sa.Column("tipping_deadline", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("maximum_duration_minutes_snapshot", sa.Integer()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(length=255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("rejection_reason", sa.String(length=500)),
        sa.Column("cancellation_reason", sa.String(length=500)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
    )
    op.create_index(
        "ux_performance_reservations_live_date",
        "performance_reservations",
        ["event_date"],
        unique=True,
        sqlite_where=sa.text(_LIVE),
        postgresql_where=sa.text(_LIVE),
    )
    op.create_index(
        "ux_performance_reservations_live_owner",
        "performance_reservations",
        ["owner_user_id"],
        unique=True,
        sqlite_where=sa.text(_LIVE),
        postgresql_where=sa.text(_LIVE),
    )
    op.create_index(
        "ux_performance_reservations_stage_group",
        "performance_reservations",
        ["group_chat_id"],
        unique=True,
        sqlite_where=sa.text("state IN ('performing', 'tipping')"),
        postgresql_where=sa.text("state IN ('performing', 'tipping')"),
    )
    op.create_index(
        "ix_performance_reservations_state_scheduled",
        "performance_reservations",
        ["state", "scheduled_at"],
    )
    op.create_table(
        "performance_participants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["performance_reservations.id"]
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("reservation_id", "user_id"),
        sa.UniqueConstraint("reservation_id", "display_order"),
    )
    op.create_table(
        "performance_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("current_step", sa.String(length=32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
    )
    op.create_table(
        "performance_extension_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("original_scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("reviewer", sa.String(length=255)),
        sa.Column("rejection_reason", sa.String(length=500)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["performance_reservations.id"]
        ),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
    )
    op.create_index(
        "ux_performance_extension_requests_pending",
        "performance_extension_requests",
        ["reservation_id"],
        unique=True,
        sqlite_where=sa.text("state = 'pending'"),
        postgresql_where=sa.text("state = 'pending'"),
    )
    op.create_table(
        "performance_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["performance_reservations.id"]
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
    )
    op.create_table(
        "performance_tips",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reservation_id", sa.Uuid(), nullable=False),
        sa.Column("sender_user_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["reservation_id"], ["performance_reservations.id"]
        ),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
    )
    op.create_index(
        "ix_performance_tips_reservation", "performance_tips", ["reservation_id"]
    )

    with op.batch_alter_table("outbound_messages") as batch:
        batch.add_column(sa.Column("deferred_by_performance_id", sa.Uuid()))
        batch.add_column(sa.Column("performance_defer_key", sa.String(length=255)))
        batch.create_foreign_key(
            "fk_outbound_messages_deferred_performance",
            "performance_reservations",
            ["deferred_by_performance_id"],
            ["id"],
        )
    op.create_index(
        "ux_outbound_messages_held_performance_key",
        "outbound_messages",
        ["deferred_by_performance_id", "performance_defer_key"],
        unique=True,
        sqlite_where=sa.text(
            "status = 'held_performance' AND performance_defer_key IS NOT NULL"
        ),
        postgresql_where=sa.text(
            "status = 'held_performance' AND performance_defer_key IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ux_outbound_messages_held_performance_key", table_name="outbound_messages"
    )
    with op.batch_alter_table("outbound_messages") as batch:
        batch.drop_constraint(
            "fk_outbound_messages_deferred_performance", type_="foreignkey"
        )
        batch.drop_column("performance_defer_key")
        batch.drop_column("deferred_by_performance_id")
    op.drop_index("ix_performance_tips_reservation", table_name="performance_tips")
    op.drop_table("performance_tips")
    op.drop_table("performance_messages")
    op.drop_index(
        "ux_performance_extension_requests_pending",
        table_name="performance_extension_requests",
    )
    op.drop_table("performance_extension_requests")
    op.drop_table("performance_drafts")
    op.drop_table("performance_participants")
    op.drop_index(
        "ix_performance_reservations_state_scheduled",
        table_name="performance_reservations",
    )
    op.drop_index(
        "ux_performance_reservations_stage_group",
        table_name="performance_reservations",
    )
    op.drop_index(
        "ux_performance_reservations_live_owner",
        table_name="performance_reservations",
    )
    op.drop_index(
        "ux_performance_reservations_live_date",
        table_name="performance_reservations",
    )
    op.drop_table("performance_reservations")
    op.drop_table("performance_settings")
    if sa.inspect(op.get_bind()).has_table("ai_activity_events"):
        with op.batch_alter_table("ai_activity_events") as batch:
            batch.alter_column(
                "detail",
                existing_type=sa.String(length=64),
                type_=sa.String(length=32),
                existing_nullable=True,
            )
    with op.batch_alter_table("group_chats") as batch:
        batch.drop_column("performances_enabled")
