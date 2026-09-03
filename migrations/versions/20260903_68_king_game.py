"""Add the persistent King game."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "20260903_68"
down_revision: str | None = "20260901_67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


KING_GAME_CARD_ID = UUID("8019a5d5-8f91-430e-b0b6-bb6b9200af1e")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("group_chats"):
        groups = sa.table(
            "group_chats",
            sa.column("id", sa.Uuid()),
            sa.column("enabled_game_types", sa.JSON()),
        )
        for group_id, enabled_game_types in bind.execute(
            sa.select(groups.c.id, groups.c.enabled_game_types)
        ):
            game_types = list(enabled_game_types or [])
            if "king_game" not in game_types:
                bind.execute(
                    groups.update()
                    .where(groups.c.id == group_id)
                    .values(enabled_game_types=[*game_types, "king_game"])
                )
    op.create_table(
        "king_game_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("king_phase_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "king_games",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_chat_id", sa.Uuid(), nullable=False),
        sa.Column("host_user_id", sa.Uuid(), nullable=False),
        sa.Column("active_key", sa.String(length=32)),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("current_king_user_id", sa.Uuid()),
        sa.Column("signup_deadline", sa.DateTime(timezone=True)),
        sa.Column("king_phase_deadline", sa.DateTime(timezone=True)),
        sa.Column("end_after_round", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("finish_reason", sa.String(length=64)),
        sa.CheckConstraint(
            "state IN ('signup', 'awaiting_reveal', 'revealed', 'completed', "
            "'cancelled', 'expired', 'forced_ended')",
            name="ck_king_game_state",
        ),
        sa.ForeignKeyConstraint(["group_chat_id"], ["group_chats.id"]),
        sa.ForeignKeyConstraint(["host_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["current_king_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_king_game_one_active",
        "king_games",
        ["group_chat_id"],
        unique=True,
        sqlite_where=sa.text("active_key IS NOT NULL"),
        postgresql_where=sa.text("active_key IS NOT NULL"),
    )
    op.create_table(
        "king_game_players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("roster_order", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('signup', 'active', 'withdrawn')",
            name="ck_king_game_player_state",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["king_games.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "roster_order"),
        sa.UniqueConstraint("game_id", "user_id"),
    )
    op.create_table(
        "king_game_rounds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("king_user_id", sa.Uuid(), nullable=False),
        sa.Column("number_map", sa.JSON(), nullable=False),
        sa.Column("revealed_numbers", sa.JSON()),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revealed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "state IN ('awaiting_reveal', 'revealed', 'timed_out')",
            name="ck_king_game_round_state",
        ),
        sa.ForeignKeyConstraint(["game_id"], ["king_games.id"]),
        sa.ForeignKeyConstraint(["king_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "sequence"),
    )
    if inspector.has_table("ai_knowledge_cards"):
        cards = sa.table(
            "ai_knowledge_cards",
            sa.column("id", sa.Uuid()),
            sa.column("topic", sa.String()),
            sa.column("title", sa.String()),
            sa.column("keywords", sa.JSON()),
            sa.column("content", sa.Text()),
            sa.column("enabled", sa.Boolean()),
            sa.column("priority", sa.Integer()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        )
        now = datetime.now().astimezone()
        bind.execute(
            cards.insert().values(
                id=KING_GAME_CARD_ID,
                topic="king_game",
                title="国王游戏",
                keywords=["国王游戏", "国王", "公开", "编号"],
                content=(
                    "发送 /国王游戏 创建报名局，其他员工 /加入；至少3人后发起者 /开始。"
                    "每轮系统公布国王；国王先自由发布命令，再发送 /公开 编号（如 /公开 2 5）"
                    "公开本轮号码与对应玩家。任一参与者 /继续 进入下一轮；参与者可 /退出 或 /结束游戏。"
                    "系统只负责抽号、公开和轮次，不判断国王命令内容。"
                ),
                enabled=True,
                priority=100,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("ai_knowledge_cards"):
        cards = sa.table("ai_knowledge_cards", sa.column("id", sa.Uuid()))
        op.get_bind().execute(cards.delete().where(cards.c.id == KING_GAME_CARD_ID))
    op.drop_table("king_game_rounds")
    op.drop_table("king_game_players")
    op.drop_index("ux_king_game_one_active", table_name="king_games")
    op.drop_table("king_games")
    op.drop_table("king_game_settings")
