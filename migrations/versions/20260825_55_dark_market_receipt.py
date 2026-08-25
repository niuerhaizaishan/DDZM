"""Add dark market receipt confirmation state."""

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite


revision: str = "20260825_55"
down_revision: str | None = "20260824_54"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NEW_STATE_CHECK = (
    "state IN ('active', 'awaiting_receipt', 'sold', 'complained', "
    "'unsold', 'force_delisted')"
)
_OLD_STATE_CHECK = "state IN ('active', 'sold', 'unsold', 'force_delisted')"

_COMMANDS = (
    ("/查看暗网", "/查看暗网 [商品编号]", "在指定暗网群查询竞价商品"),
    ("/确认收货", "/确认收货 [商品编号]", "私聊确认暗网商品收货"),
    ("/投诉", "/投诉 [商品编号]", "私聊投诉暗网商品未交付"),
)

_TEMPLATES = (
    ("/查看暗网", "group_only", "请在配置的暗网群中发送 /查看暗网。"),
    ("/查看暗网", "usage", "请用 /查看暗网 或 /查看暗网 商品编号。"),
    ("/查看暗网", "wrong_group", "本群不是暗网交易所入口。"),
    ("/查看暗网", "empty", "暗网交易所当前没有竞价中的商品。"),
    ("/查看暗网", "not_found", "未找到该竞价中的暗网商品。"),
    ("/查看暗网", "shown", "{商品列表}"),
    *(
        (command, scenario, template)
        for command, success_scenario, success_template in (
            ("/确认收货", "confirmed", "暗网商品 #{商品编号} 确认收货成功。"),
            ("/投诉", "complained", "暗网商品 #{商品编号} 投诉已处理，成交款已退还，卖家已被处罚。"),
        )
        for scenario, template in (
            ("private_only", f"请在私聊中发送 {command} [商品编号]。"),
            ("usage", f"请用 {command} [商品编号]。"),
            ("choose_listing", "你有多笔待收货交易：{商品编号列表}。请在指令后加商品编号。"),
            (success_scenario, success_template),
            ("auto_confirmed", "暗网商品 #{商品编号} 已到期自动确认收货。"),
            ("no_pending", "当前没有需要你处理的暗网待收货交易。"),
            ("not_found", "未找到该暗网商品。"),
            ("not_buyer", "你不是该暗网商品的买家，无法处理收货。"),
            ("already_resolved", "该暗网订单已经处理完成。"),
            ("not_joined", "请先用 /入职 名字 加入摸鱼公司。"),
        )
    ),
)


def _insert_if_missing(connection, table, values, index_elements) -> None:
    if connection.dialect.name == "postgresql":
        statement = postgresql.insert(table).values(**values)
    elif connection.dialect.name == "sqlite":
        statement = sqlite.insert(table).values(**values)
    else:
        raise ValueError(f"unsupported database dialect: {connection.dialect.name}")
    connection.execute(statement.on_conflict_do_nothing(index_elements=index_elements))


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("dark_market_listings"):
        with op.batch_alter_table("dark_market_listings") as batch:
            batch.drop_constraint("ck_dark_market_listing_state", type_="check")
            batch.add_column(
                sa.Column("receipt_started_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(
                sa.Column("receipt_deadline", sa.DateTime(timezone=True), nullable=True)
            )
            batch.add_column(
                sa.Column("receipt_resolved_at", sa.DateTime(timezone=True), nullable=True)
            )
            batch.create_check_constraint(
                "ck_dark_market_listing_state", _NEW_STATE_CHECK
            )
            batch.create_index(
                "ix_dark_market_listings_receipt_due",
                ["state", "receipt_deadline"],
                unique=False,
            )
    if not (
        inspector.has_table("command_definitions")
        and inspector.has_table("command_reply_templates")
    ):
        return
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE command_definitions SET command = '/查看暗网', "
            "syntax = replace(syntax, '/登陆暗网', '/查看暗网') "
            "WHERE command = '/登陆暗网' AND NOT EXISTS "
            "(SELECT 1 FROM command_definitions WHERE command = '/查看暗网')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE command_reply_templates SET command = '/查看暗网', "
            "template = replace(template, '/登陆暗网', '/查看暗网') "
            "WHERE command = '/登陆暗网' AND NOT EXISTS "
            "(SELECT 1 FROM command_reply_templates existing "
            "WHERE existing.command = '/查看暗网' "
            "AND existing.scenario = command_reply_templates.scenario)"
        )
    )
    commands = sa.table(
        "command_definitions",
        sa.column("command", sa.String()),
        sa.column("syntax", sa.Text()),
        sa.column("description", sa.Text()),
        sa.column("enabled", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    templates = sa.table(
        "command_reply_templates",
        sa.column("id", sa.Uuid()),
        sa.column("command", sa.String()),
        sa.column("scenario", sa.String()),
        sa.column("template", sa.Text()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    for command, syntax, description in _COMMANDS:
        _insert_if_missing(
            connection,
            commands,
            {
                "command": command,
                "syntax": syntax,
                "description": description,
                "enabled": True,
                "created_at": now,
            },
            [commands.c.command],
        )
    for command, scenario, template in _TEMPLATES:
        _insert_if_missing(
            connection,
            templates,
            {
                "id": uuid4(),
                "command": command,
                "scenario": scenario,
                "template": template,
                "created_at": now,
                "updated_at": now,
            },
            [templates.c.command, templates.c.scenario],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("command_definitions"):
        commands = sa.table(
            "command_definitions", sa.column("command", sa.String())
        )
        op.execute(
            commands.delete().where(
                commands.c.command.in_(("/确认收货", "/投诉"))
            )
        )
        connection = op.get_bind()
        connection.execute(
            sa.text(
                "UPDATE command_definitions SET command = '/登陆暗网', "
                "syntax = replace(syntax, '/查看暗网', '/登陆暗网') "
                "WHERE command = '/查看暗网' AND NOT EXISTS "
                "(SELECT 1 FROM command_definitions WHERE command = '/登陆暗网')"
            )
        )
    if inspector.has_table("command_reply_templates"):
        templates = sa.table(
            "command_reply_templates", sa.column("command", sa.String())
        )
        op.execute(
            templates.delete().where(
                templates.c.command.in_(("/确认收货", "/投诉"))
            )
        )
        connection = op.get_bind()
        connection.execute(
            sa.text(
                "UPDATE command_reply_templates SET command = '/登陆暗网', "
                "template = replace(template, '/查看暗网', '/登陆暗网') "
                "WHERE command = '/查看暗网' AND NOT EXISTS "
                "(SELECT 1 FROM command_reply_templates existing "
                "WHERE existing.command = '/登陆暗网' "
                "AND existing.scenario = command_reply_templates.scenario)"
            )
        )
    if inspector.has_table("dark_market_listings"):
        with op.batch_alter_table("dark_market_listings") as batch:
            batch.drop_index("ix_dark_market_listings_receipt_due")
            batch.drop_constraint("ck_dark_market_listing_state", type_="check")
            batch.drop_column("receipt_resolved_at")
            batch.drop_column("receipt_deadline")
            batch.drop_column("receipt_started_at")
            batch.create_check_constraint(
                "ck_dark_market_listing_state", _OLD_STATE_CHECK
            )
