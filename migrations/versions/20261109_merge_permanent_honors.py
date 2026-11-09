"""Join the deployed permanent-honor revision to the workstation and upstream chain."""

revision = "20261109_merge_permanent_honors"
down_revision = ("20261109_merge_workstation", "20261109_111_permanent_honors")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
