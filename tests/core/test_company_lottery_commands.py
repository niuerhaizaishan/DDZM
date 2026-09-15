from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.runtime.contracts import InboundMessage

BEIJING = ZoneInfo("Asia/Shanghai")
DRAW_AT = datetime(2026, 9, 14, 22, 0, tzinfo=BEIJING)


def _service():
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base, RankRecord
    from dzmm_bot.core.service import CoreService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.list_ranks()
    with factory.begin() as session:
        session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 1)
        ).multiplayer_game_limit = 999
    return CoreService(repository, GroupCommandHandler(repository)), repository, factory


def _purge(factory):
    """清空出站记录，让 _reply 只看见本次消息的回复。"""
    from dzmm_bot.core.schema import OutboundRecord

    with factory.begin() as session:
        session.query(OutboundRecord).delete()


def _reply(factory):
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        texts = list(
            session.scalars(
                select(OutboundRecord.text).order_by(
                    OutboundRecord.reply_index, OutboundRecord.created_at
                )
            )
        )
    if not texts:
        return None
    return "\n".join(texts)


def _setup():
    """建群、建员工、开一期。"""
    service, repository, factory = _service()
    now = datetime(2026, 9, 14, 12, 0, tzinfo=BEIJING)
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=lottery-main", now
    )
    repository.create_user("p1", "小明", now, 100)
    repository.create_user("p2", "小红", now, 100)
    repository.ensure_company_lottery_round(now)
    return service, repository, factory, group, now


def _send(service, group, message_id, sender, content, now):
    _purge(service._repository._session_factory)
    service.receive_inbound(
        InboundMessage(
            message_id,
            sender,
            content,
            now,
            source_type="group",
            chatroom_id=group.chatroom_id,
        )
    )


def _answer(repository):
    from dzmm_bot.core.company_lottery import Ticket
    from dzmm_bot.core.schema import CompanyLotteryRoundRecord

    view = repository.current_company_lottery_round()
    with repository._session() as session:
        record = session.get(CompanyLotteryRoundRecord, view.id)
    return Ticket(
        reds=(record.red_1, record.red_2, record.red_3, record.red_4),
        blue=record.blue,
    )


# --------------------------------------------------------------------------- 查询

def test_menu_reports_the_open_round():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/彩票", now)

    text = _reply(factory)
    assert "公司双色球 · 第 1 期" in text
    assert "红球 10 选 4 个不重复，蓝球 6 选 1 个" in text
    assert "一等奖" in text


def test_menu_says_so_when_there_is_no_round():
    service, repository, factory = _service()
    now = datetime(2026, 9, 14, 12, 0, tzinfo=BEIJING)
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=lottery-empty", now
    )
    repository.create_user("p1", "小明", now, 100)

    _send(service, group, "m1", "p1", "/彩票", now)

    assert _reply(factory) == "当前没有开放的彩票期次，稍后再来。"


def test_commands_are_group_only():
    from dzmm_bot.core.commands import GroupCommandHandler

    service, repository, factory, group, now = _setup()

    reply = GroupCommandHandler(repository).handle(
        InboundMessage("d1", "p1", "/彩票", now, source_type="direct")
    )

    assert reply == "请回到群里查看彩票信息。"


def test_group_switch_blocks_the_whole_command_set():
    from dzmm_bot.core.schema import GroupChatRecord

    service, repository, factory, group, now = _setup()
    with repository._session() as session:
        session.get(GroupChatRecord, group.id).lottery_enabled = False

    _send(service, group, "m1", "p1", "/彩票", now)
    assert _reply(factory) == "本群未开放公司双色球，去开放了的群看吧。"
    _send(service, group, "m2", "p1", "/购买彩票 机选", now)
    assert _reply(factory) == "本群未开放公司双色球，去开放了的群玩吧。"
    _send(service, group, "m3", "p1", "/我的彩票", now)
    assert _reply(factory) == "本群未开放公司双色球，去开放了的群看吧。"
    _send(service, group, "m4", "p1", "/彩票验证 1", now)
    assert _reply(factory) == "本群未开放公司双色球，去开放了的群核验吧。"


def test_group_switch_also_blocks_the_draft_step():
    from dzmm_bot.core.schema import GroupChatRecord

    service, repository, factory, group, now = _setup()
    _send(service, group, "m1", "p1", "/购买彩票 2 注", now)
    with repository._session() as session:
        session.get(GroupChatRecord, group.id).lottery_enabled = False

    _send(service, group, "m2", "p1", "03 07 09 10 + 05", now)

    assert _reply(factory) == "本群未开放公司双色球，去开放了的群玩吧。"


def test_help_explains_the_lottery_rules_and_expectation():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/帮助 彩票", now)

    text = _reply(factory)
    assert "【公司双色球】" in text
    assert "/购买彩票 03 07 09 10 + 05" in text
    assert "每注长期期望返回约 1.19 摸鱼币" in text


def test_help_index_lists_the_lottery_category():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/帮助", now)

    assert "/帮助 彩票：公司双色球的玩法、奖级与开奖规则" in _reply(factory)


# --------------------------------------------------------------------------- 购票

def test_manual_purchase_confirms_the_ticket():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 03 07 09 10 + 05", now)

    text = _reply(factory)
    assert text.startswith("✅ 已购 1 注（2 摸鱼币）")
    assert "03  07  09  10" in text
    assert "余额 98 摸鱼币" in text
    assert "本日还可买 4 注" in text


def test_quick_pick_purchase_marks_the_ticket():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 机选 3", now)

    text = _reply(factory)
    assert text.startswith("✅ 已购 3 注（6 摸鱼币）")
    assert "🎲 机选号码" in text
    assert "本日还可买 2 注" in text


def test_buy_lottery_alias_points_at_the_same_command():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/买彩票 机选", now)

    assert _reply(factory).startswith("✅ 已购 1 注（2 摸鱼币）")


def test_out_of_range_number_is_reported():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 12 07 09 10 + 05", now)

    text = _reply(factory)
    assert "红球须在 01-10，你写了 12" in text
    assert "红球 10 选 4 不重复，蓝球 6 选 1" in text


def test_wrong_arity_is_reported_with_the_expected_count():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 03 07 09 + 05", now)

    text = _reply(factory)
    assert "需要 4 个红球，你写了 3 个" in text
    assert "红球 10 选 4 不重复，蓝球 6 选 1" in text


def test_unjoined_employee_cannot_buy():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "stranger", "/购买彩票 机选", now)

    assert _reply(factory) == "请先用 /入职 名字 加入摸鱼公司。"


def test_daily_limit_is_enforced_by_the_command_layer():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 机选 5", now)
    _send(service, group, "m2", "p1", "/购买彩票 机选", now)

    assert _reply(factory) == "今天已经买满 5 注了，明天再来。"


def test_purchase_is_rejected_after_close():
    service, repository, factory, group, now = _setup()

    _send(
        service,
        group,
        "m1",
        "p1",
        "/购买彩票 机选",
        datetime(2026, 9, 14, 21, 55, tzinfo=BEIJING),
    )

    assert "停售" in _reply(factory)


def test_first_round_seeds_the_pool_so_the_head_prize_pays_out():
    service, repository, factory, group, now = _setup()

    pool, adjustment = repository.company_lottery_balances()

    assert pool == 100
    assert adjustment == 0


# --------------------------------------------------------------------------- 逐注填写

def test_guided_purchase_flow():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 2 注", now)
    assert "本次要买 2 注" in _reply(factory)

    _send(service, group, "m2", "p1", "03 07 09 10 + 05", now)
    text = _reply(factory)
    assert "第 1 注已记录" in text
    assert "还剩 1 注" in text

    _send(service, group, "m3", "p1", "机选", now)
    text = _reply(factory)
    assert "已记录 2 注" in text
    assert "确认请发 /确认彩票" in text

    _send(service, group, "m4", "p1", "/确认彩票", now)
    assert _reply(factory).startswith("✅ 已购 2 注（4 摸鱼币）")


def test_guided_purchase_can_be_cancelled():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 3 注", now)
    _send(service, group, "m2", "p1", "03 07 09 10 + 05", now)
    _send(service, group, "m3", "p1", "/取消彩票", now)

    assert _reply(factory) == "已放弃购票草稿，未扣款。"
    _send(service, group, "m4", "p1", "/我的彩票", now)
    assert _reply(factory) == "你还没有买过彩票。"


def test_guided_purchase_can_be_expired():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 3 注", now)
    _send(
        service,
        group,
        "m2",
        "p1",
        "03 07 09 10 + 05",
        datetime(2026, 9, 14, 12, 16, tzinfo=BEIJING),
    )

    assert _reply(factory) == "购票草稿已超时，请重新发起。"


def test_expired_draft_does_not_hijack_plain_chatter():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 3 注", now)
    _send(
        service,
        group,
        "m2",
        "p1",
        "今天天气不错",
        datetime(2026, 9, 14, 12, 16, tzinfo=BEIJING),
    )

    assert _reply(factory) is None


def test_plain_chatter_is_untouched_when_no_draft_is_open():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "今天天气不错", now)

    assert _reply(factory) is None


def test_draft_ignores_text_that_is_not_a_ticket():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 2 注", now)
    _send(service, group, "m2", "p1", "今天天气不错", now)

    assert _reply(factory) is None

    _send(service, group, "m3", "p1", "/确认彩票", now)
    assert _reply(factory) == "草稿里还没有号码，先发一注号码或「机选」。"


def test_confirming_without_a_draft_is_reported():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/确认彩票", now)

    assert _reply(factory) == "你当前没有正在填写的购票草稿。"


# --------------------------------------------------------------------------- 记录与核验

def test_my_tickets_lists_purchases():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/购买彩票 03 07 09 10 + 05", now)
    _send(service, group, "m2", "p1", "/我的彩票", now)

    text = _reply(factory)
    assert text.startswith("🎱 我的彩票")
    assert "第 1 期" in text
    assert "累计投入 2 摸鱼币 ｜ 累计中奖 0 摸鱼币 ｜ 净收益 -2 摸鱼币" in text


def test_my_tickets_is_empty_for_a_new_employee():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p2", "/我的彩票", now)

    assert _reply(factory) == "你还没有买过彩票。"


def test_verify_reveals_the_answer_hash_after_the_draw():
    service, repository, factory, group, now = _setup()
    answer = _answer(repository)
    repository.draw_company_lottery_round(DRAW_AT)

    _send(service, group, "m1", "p1", "/彩票验证 1", DRAW_AT)

    text = _reply(factory)
    assert "第 0001 期" in text
    assert answer.display() in text
    assert "承诺哈希：" in text


def test_verify_needs_a_drawn_round():
    service, repository, factory, group, now = _setup()

    _send(service, group, "m1", "p1", "/彩票验证 1", now)
    assert _reply(factory) == "没有找到该期已开奖记录。"

    _send(service, group, "m2", "p1", "/彩票验证", now)
    assert _reply(factory) == "格式：/彩票验证 期号"


def test_my_tickets_shows_the_prize_after_the_draw():
    service, repository, factory, group, now = _setup()
    answer = _answer(repository)
    _send(
        service,
        group,
        "m1",
        "p1",
        f"/购买彩票 {' '.join(f'{n:02d}' for n in answer.reds)} + {answer.blue:02d}",
        now,
    )
    repository.draw_company_lottery_round(DRAW_AT)

    _send(service, group, "m2", "p1", "/我的彩票", DRAW_AT)

    text = _reply(factory)
    assert "+100" in text
    assert "累计中奖 100 摸鱼币" in text
