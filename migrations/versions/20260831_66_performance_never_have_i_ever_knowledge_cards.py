"""Add knowledge cards for performances and Never Have I Ever."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_66"
down_revision: str | None = "20260831_65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERFORMANCE_CARD_ID = UUID("7e2d2105-80a4-4cd3-ac90-6e93f336eac8")
NEVER_HAVE_I_EVER_CARD_ID = UUID("c7b5e021-5c31-47ba-96b0-e99cfe611d42")


def upgrade() -> None:
    cards = _cards_table()
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    op.bulk_insert(
        cards,
        [
            {
                "id": PERFORMANCE_CARD_ID,
                "topic": "performance",
                "title": "公演场次预约",
                "keywords": ["公演", "公演预约", "预约公演", "公演日程", "延期"],
                "content": (
                    "在开放公演的群内发送 /预约公演，随后按私聊向导填写标题、简介、"
                    "封面、开场时间和参演人员并等待审核。/公演日程 查看本群已审核场次；"
                    "预约人可私聊 /我的公演预约、/取消公演预约，或 /延期 30m、/延期 1h、/延期 1d 申请延期。"
                    "开场前5分钟会群内预告；演出中只有参演人员可 /end，之后进入打赏环节。"
                ),
                "enabled": True,
                "priority": 100,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": NEVER_HAVE_I_EVER_CARD_ID,
                "topic": "never_have_i_ever",
                "title": "我有你没有",
                "keywords": ["我有你没有", "扣心", "不扣", "发言"],
                "content": (
                    "发送 /我有你没有 创建报名局，其他员工 /加入；至少3人后由发起者 /开始。"
                    "轮到的玩家发送 /发言 内容，说出自己的经历；其他存活玩家用 /扣 表示没有该经历并扣一颗心，"
                    "用 /不扣 表示也有该经历并保留心数。心数归零的玩家出局；达到自由惩罚条件后按群内提示进行。"
                ),
                "enabled": True,
                "priority": 100,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    cards = _cards_table()
    op.get_bind().execute(
        cards.delete().where(
            cards.c.id.in_((PERFORMANCE_CARD_ID, NEVER_HAVE_I_EVER_CARD_ID))
        )
    )


def _cards_table():
    return sa.table(
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
