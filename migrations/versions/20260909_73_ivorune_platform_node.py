"""Move persisted platform links to the Ivorune node."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260909_73"
down_revision: str | None = "20260908_72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_ORIGINS = (
    "https://www.aikda.com",
    "https://aikda.com",
    "https://www.dzmm.ai",
    "https://dzmm.ai",
)
_NEW_ORIGIN = "https://www.ivorune.xyz"


def upgrade() -> None:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    targets = (
        ("group_chats", "chat_url"),
        ("game_settings", "company_story_novel_url"),
    )
    for table_name, column_name in targets:
        if table_name not in tables:
            continue
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns(table_name)
        }
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
