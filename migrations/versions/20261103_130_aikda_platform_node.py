"""Move persisted platform links back to the Aikda node."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20261103_130"
down_revision: str | None = "20261022_mr_expedition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_ORIGINS = (
    "https://www.ivorune.xyz",
    "https://ivorune.xyz",
    "https://www.lumivale.xyz",
    "https://lumivale.xyz",
    "https://www.dzmm.ai",
    "https://dzmm.ai",
)
_NEW_ORIGIN = "https://www.aikda.com"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    for table_name, column_name in (
        ("group_chats", "chat_url"),
        ("game_settings", "company_story_novel_url"),
    ):
        if table_name not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table_name)}
        if column_name not in columns:
            continue
        for old_origin in _OLD_ORIGINS:
            connection.execute(
                sa.text(
                    f"UPDATE {table_name} "
                    f"SET {column_name} = replace({column_name}, :old_origin, :new_origin) "
                    f"WHERE {column_name} LIKE :prefix"
                ),
                {
                    "old_origin": old_origin,
                    "new_origin": _NEW_ORIGIN,
                    "prefix": f"{old_origin}/%",
                },
            )


def downgrade() -> None:
    pass
