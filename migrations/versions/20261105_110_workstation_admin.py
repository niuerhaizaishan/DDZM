"""Versioned workstation rules and audited administrative adjustments."""

from alembic import op
import sqlalchemy as sa

revision = "20261105_110"
down_revision = "20261104_109"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workstation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_workstation_rules_singleton"),
    )
    op.create_table(
        "workstation_admin_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor", sa.String(200), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor", "request_id", name="uq_workstation_admin_request"),
    )
    if sa.inspect(op.get_bind()).has_table("birthday_settings"):
        with op.batch_alter_table("birthday_settings") as batch:
            batch.alter_column(
                "enabled",
                existing_type=sa.Boolean(),
                server_default=sa.true(),
                existing_nullable=False,
            )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("birthday_settings"):
        with op.batch_alter_table("birthday_settings") as batch:
            batch.alter_column(
                "enabled",
                existing_type=sa.Boolean(),
                server_default=sa.false(),
                existing_nullable=False,
            )
    op.drop_table("workstation_admin_operations")
    op.drop_table("workstation_rules")
