"""add unified Club card-table rooms

Revision ID: 20261021_129
Revises: 20261021_128
"""

from alembic import op
import sqlalchemy as sa


revision = "20261021_129"
down_revision = "20261021_128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "club_card_rooms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game", sa.String(length=16), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("create_request_id", sa.Uuid(), nullable=False),
        sa.Column("seats", sa.JSON(), nullable=False),
        sa.Column("ready", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("room_type", sa.String(length=16), nullable=False),
        sa.Column("stake", sa.Integer(), server_default="0", nullable=False),
        sa.Column("state", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("escrowed", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("hand_settled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=False),
        sa.Column("hand_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["creator_id"], ["club_players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("creator_id", "create_request_id", name="uq_club_card_room_create"),
    )
    op.create_index("ix_club_card_rooms_game", "club_card_rooms", ["game"])
    op.create_index("ix_club_card_rooms_phase", "club_card_rooms", ["phase"])
    op.create_index("ix_club_card_rooms_updated_at", "club_card_rooms", ["updated_at"])
    op.create_table(
        "club_card_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["club_card_rooms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["club_players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "user_id", "request_id"),
    )
    op.create_table(
        "club_card_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.String(length=300), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["club_card_rooms.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["club_players.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "user_id", "request_id"),
    )
    op.create_table(
        "club_card_hands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("game", sa.String(length=16), nullable=False),
        sa.Column("hand_number", sa.Integer(), nullable=False),
        sa.Column("players", sa.JSON(), nullable=False),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("payouts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["club_card_rooms.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "hand_number"),
    )
    op.create_index("ix_club_card_hands_game", "club_card_hands", ["game"])


def downgrade() -> None:
    op.drop_index("ix_club_card_hands_game", table_name="club_card_hands")
    op.drop_table("club_card_hands")
    op.drop_table("club_card_messages")
    op.drop_table("club_card_requests")
    op.drop_index("ix_club_card_rooms_updated_at", table_name="club_card_rooms")
    op.drop_index("ix_club_card_rooms_phase", table_name="club_card_rooms")
    op.drop_index("ix_club_card_rooms_game", table_name="club_card_rooms")
    op.drop_table("club_card_rooms")
