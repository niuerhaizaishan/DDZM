"""Enable birthday blessings for existing global and group settings."""

from alembic import op
import sqlalchemy as sa


revision = "20261107_111"
down_revision = "20261105_110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, column_name in (
        ("birthday_settings", "enabled"),
        ("group_chats", "birthdays_enabled"),
    ):
        if not inspector.has_table(table_name):
            continue
        if not any(column["name"] == column_name for column in inspector.get_columns(table_name)):
            continue
        flag = sa.column(column_name, sa.Boolean())
        table = sa.table(table_name, flag)
        op.execute(table.update().where(flag.is_(False)).values({column_name: True}))


def downgrade() -> None:
    # The original values cannot be inferred after administrators edit settings.
    pass
