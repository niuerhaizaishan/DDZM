"""Seed dark market commands and editable replies."""

from collections.abc import Sequence
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite


revision: str = "20260824_53"
down_revision: str | None = "20260824_52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


COMMANDS = (
    ("/上架暗网", "/上架暗网", "私聊引导上架暗网商品"),
    ("/取消上架", "/取消上架", "取消尚未确认的暗网上架草稿"),
    ("/确认", "/确认", "确认当前暗网上架草稿"),
    ("/报价", "/报价 商品编号 金额", "私聊匿名竞价暗网商品"),
    ("/公开", "/公开 [商品编号]", "同意公开暗网成交双方身份"),
    ("/不公开", "/不公开 [商品编号]", "拒绝公开暗网成交双方身份"),
    ("/登陆暗网", "/登陆暗网 [商品编号]", "在指定暗网群查询竞价商品"),
)

TEMPLATES = (
    ("/上架暗网", "private_only", "请私聊总监事发送 /上架暗网。"),
    ("/上架暗网", "not_joined", "请先用 /入职 名字 加入摸鱼公司。"),
    ("/上架暗网", "unavailable", "暗网交易所暂未开放。"),
    ("/上架暗网", "name", "请发送商品名称（1–30 字）。"),
    ("/上架暗网", "purpose", "请发送商品用途（1–100 字）。"),
    ("/上架暗网", "details", "请发送商品详细信息（1–500 字）。"),
    ("/上架暗网", "gender", "请选择匿名性别并发送：男、女或保密。"),
    ("/上架暗网", "starting_price", "请发送起拍价（1–99999 的整数）。"),
    ("/上架暗网", "preview", "草稿已填写完成，请发送 /确认 正式上架。"),
    ("/取消上架", "private_only", "请在私聊中发送 /取消上架。"),
    ("/取消上架", "cancelled", "暗网上架草稿已取消。"),
    ("/取消上架", "not_joined", "请先用 /入职 名字 加入摸鱼公司。"),
    ("/取消上架", "no_draft", "当前没有可取消的暗网上架草稿。"),
    ("/确认", "private_only", "请在私聊中发送 /确认。"),
    ("/确认", "listed", "暗网商品 #{商品编号} 上架成功。"),
    ("/确认", "not_joined", "请先用 /入职 名字 加入摸鱼公司。"),
    ("/确认", "unavailable", "暗网交易所暂未开放。"),
    ("/确认", "expired", "暗网上架草稿已超时，请重新发送 /上架暗网。"),
    ("/确认", "daily_limit", "你今天的暗网商品上架次数已用完。"),
    ("/确认", "no_draft", "当前没有可确认的完整暗网上架草稿。"),
    ("/报价", "private_only", "请在私聊中发送 /报价 商品编号 金额。"),
    ("/报价", "usage", "请用 /报价 商品编号 金额，例如 /报价 12 25。"),
    ("/报价", "accepted", "暗网商品 #{商品编号} 报价成功：{金额} {货币}，当前冻结 {冻结金额} {货币}。"),
    ("/报价", "not_joined", "请先用 /入职 名字 加入摸鱼公司。"),
    ("/报价", "not_found", "未找到该暗网商品。"),
    ("/报价", "ended", "该暗网商品已结束竞价。"),
    ("/报价", "invalid_amount", "报价金额必须是 1–99999 的整数。"),
    ("/报价", "insufficient_balance", "余额不足，无法提交该报价。"),
    ("/报价", "too_low", "报价过低，下一次报价至少为 {最低报价} {货币}。"),
    ("/登陆暗网", "group_only", "请在配置的暗网群中发送 /登陆暗网。"),
    ("/登陆暗网", "usage", "请用 /登陆暗网 或 /登陆暗网 商品编号。"),
    ("/登陆暗网", "wrong_group", "本群不是暗网交易所入口。"),
    ("/登陆暗网", "empty", "暗网交易所当前没有竞价中的商品。"),
    ("/登陆暗网", "not_found", "未找到该竞价中的暗网商品。"),
    ("/登陆暗网", "shown", "{商品列表}"),
    *(
        (command, scenario, template)
        for command in ("/公开", "/不公开")
        for scenario, template in (
            ("private_only", f"请在私聊中发送 {command}。"),
            ("usage", f"请用 {command} [商品编号]。"),
            ("choose_listing", "你有多笔待确认交易：{商品编号列表}。请在指令后加商品编号。"),
            ("waiting_other", "你的选择已记录，正在等待另一方确认。"),
            ("revealed", "双方均同意，买卖双方身份已在暗网群公开。"),
            ("anonymous", "本次交易将保持匿名。"),
            ("expired", "公开确认已超时，本次交易保持匿名。"),
            ("no_pending", "当前没有需要你确认公开身份的暗网交易。"),
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
    if not (
        inspector.has_table("command_definitions")
        and inspector.has_table("command_reply_templates")
    ):
        return
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    connection = op.get_bind()
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
    for command, syntax, description in COMMANDS:
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
    for command, scenario, template in TEMPLATES:
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
    if not (
        inspector.has_table("command_definitions")
        and inspector.has_table("command_reply_templates")
    ):
        return
    commands = sa.table(
        "command_definitions", sa.column("command", sa.String())
    )
    templates = sa.table(
        "command_reply_templates",
        sa.column("command", sa.String()),
    )
    command_names = tuple(command for command, _, _ in COMMANDS)
    op.execute(templates.delete().where(templates.c.command.in_(command_names)))
    op.execute(commands.delete().where(commands.c.command.in_(command_names)))
