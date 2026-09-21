"""Add the birthday blessing tables and the per-group switch."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260917_76"
down_revision: str | None = "20260915_75"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group_chats",
        sa.Column(
            "birthdays_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "employee_birthdays",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("day", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer()),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("last_edited_at", sa.DateTime(timezone=True)),
        sa.Column("edit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edit_count_year", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_table(
        "birthday_greetings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("greet_year", sa.Integer(), nullable=False),
        sa.Column("greeted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gift_amount", sa.Integer(), nullable=False),
        sa.Column("lottery_tickets", sa.Integer(), nullable=False),
        sa.Column("tips_count", sa.Integer(), nullable=False),
        sa.Column("tips_total", sa.Integer(), nullable=False),
        sa.Column("tips_closed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "greet_year"),
    )
    op.create_index(
        "ix_birthday_greetings_pending_tips",
        "birthday_greetings",
        ["tips_closed_at", "greeted_at"],
    )
    op.create_table(
        "birthday_previews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("preview_year", sa.Integer(), nullable=False),
        sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "preview_year"),
    )
    op.create_table(
        "birthday_tips",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("greeting_id", sa.Uuid(), nullable=False),
        sa.Column("from_user_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("inbound_message_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["greeting_id"], ["birthday_greetings.id"]),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["inbound_message_id"], ["inbound_messages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("greeting_id", "from_user_id"),
    )
    op.create_index(
        "ix_birthday_tips_inbound",
        "birthday_tips",
        ["inbound_message_id"],
    )
    op.create_table(
        "birthday_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("greet_time", sa.String(length=5), nullable=False),
        sa.Column(
            "preview_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("preview_time", sa.String(length=5), nullable=False),
        sa.Column("gift_amount", sa.Integer(), nullable=False),
        sa.Column(
            "same_day_backfill",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("edit_limit_per_year", sa.Integer(), nullable=False),
        sa.Column("checkin_multiplier", sa.Integer(), nullable=False),
        sa.Column("shop_discount_percent", sa.Integer(), nullable=False),
        sa.Column("lottery_free_tickets", sa.Integer(), nullable=False),
        sa.Column("event_reward_bonus_percent", sa.Integer(), nullable=False),
        sa.Column(
            "tips_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("tip_max_amount", sa.Integer(), nullable=False),
        sa.Column("tip_window_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "anniversary_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("greet_template", sa.Text(), nullable=False),
        sa.Column("preview_template", sa.Text(), nullable=False),
        sa.Column("tips_summary_template", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in (
        "birthday_tips",
        "birthday_previews",
        "birthday_greetings",
        "employee_birthdays",
        "birthday_settings",
    ):
        if inspector.has_table(table):
            op.drop_table(table)
    if inspector.has_table("group_chats"):
        columns = {column["name"] for column in inspector.get_columns("group_chats")}
        if "birthdays_enabled" in columns:
            op.drop_column("group_chats", "birthdays_enabled")
