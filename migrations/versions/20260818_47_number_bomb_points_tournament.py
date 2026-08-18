"""Add persistent number bomb points tournaments."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260818_47"
down_revision: str | None = "20260818_46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("number_bomb_games") as batch:
        batch.add_column(
            sa.Column(
                "mode",
                sa.String(length=32),
                server_default="standard",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column(
                "maximum_rounds",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.create_check_constraint(
            "ck_number_bomb_game_mode",
            "mode IN ('standard', 'points_tournament')",
        )
        batch.create_check_constraint(
            "ck_number_bomb_game_maximum_rounds",
            "maximum_rounds IN (0, 12)",
        )
    with op.batch_alter_table("number_bomb_members") as batch:
        batch.add_column(
            sa.Column(
                "total_points",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.add_column(sa.Column("retired_at_round", sa.Integer(), nullable=True))
    with op.batch_alter_table("number_bomb_round_players") as batch:
        batch.add_column(
            sa.Column("competition_rank", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "round_points",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch.add_column(
            sa.Column("result_reason", sa.String(length=32), nullable=True)
        )
        batch.create_check_constraint(
            "ck_number_bomb_round_player_result_reason",
            "result_reason IS NULL OR result_reason IN ('reported', 'skipped', 'retired')",
        )


def downgrade() -> None:
    with op.batch_alter_table("number_bomb_round_players") as batch:
        batch.drop_constraint(
            "ck_number_bomb_round_player_result_reason", type_="check"
        )
        batch.drop_column("result_reason")
        batch.drop_column("round_points")
        batch.drop_column("competition_rank")
    with op.batch_alter_table("number_bomb_members") as batch:
        batch.drop_column("retired_at_round")
        batch.drop_column("total_points")
    with op.batch_alter_table("number_bomb_games") as batch:
        batch.drop_constraint(
            "ck_number_bomb_game_maximum_rounds", type_="check"
        )
        batch.drop_constraint("ck_number_bomb_game_mode", type_="check")
        batch.drop_column("maximum_rounds")
        batch.drop_column("mode")
