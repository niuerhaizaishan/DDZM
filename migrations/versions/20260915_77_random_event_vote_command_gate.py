"""Let the random event vote command through the running-event gate.

新指令要能放行，否则随机事件报名中/进行中时全公司都投不了票。放行清单存在
`random_event_settings` 里，所以只改代码默认值对已部署的库无效——这里把新指令
追加进已有清单（幂等，且不动管理员自己加过的其它指令）。
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260915_77"
down_revision: str | None = "20260915_76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


VOTE_COMMANDS = ("/事件投票", "/事件投票情况")
ALLOW_LIST_COLUMNS = ("signup_allowed_commands", "in_progress_allowed_commands")


def _settings_table() -> sa.TableClause:
    return sa.table(
        "random_event_settings",
        sa.column("id", sa.Integer()),
        sa.column("signup_allowed_commands", sa.JSON()),
        sa.column("in_progress_allowed_commands", sa.JSON()),
    )


def _rewrite(add: bool) -> None:
    if not sa.inspect(op.get_bind()).has_table("random_event_settings"):
        return
    settings = _settings_table()
    bind = op.get_bind()
    for row in bind.execute(sa.select(settings)).mappings():
        for column in ALLOW_LIST_COLUMNS:
            values = list(row[column] or [])
            if add:
                changed = False
                for command in VOTE_COMMANDS:
                    if command not in values:
                        values.append(command)
                        changed = True
            else:
                kept = [value for value in values if value not in VOTE_COMMANDS]
                changed = len(kept) != len(values)
                values = kept
            if changed:
                bind.execute(
                    sa.update(settings)
                    .where(settings.c.id == row["id"])
                    .values({column: values})
                )


def upgrade() -> None:
    _rewrite(add=True)


def downgrade() -> None:
    _rewrite(add=False)
