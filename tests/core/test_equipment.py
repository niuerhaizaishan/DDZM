from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.equipment import EQUIPMENT_COMMANDS
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    BalanceTransactionRecord, Base, EquipmentItemRecord, EquipmentOwnershipRecord,
    EquipmentPurchaseRecord, OutboundRecord, PRIMARY_GROUP_CHAT_ID, UserItemRecord,
    UserRecord, RankRecord, WorkstationComponentRecord, WorkstationUpgradeRecord,
)
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage

NOW = datetime(2026, 10, 21, 12, tzinfo=ZoneInfo("Asia/Shanghai"))

@pytest.fixture
def context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, connection_record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=group-main", NOW)
    context = CoreService(repository, GroupCommandHandler(repository)), repository, factory
    receive(context, "join", "/入职 糯糯")
    user = repository.find_user("user-1")
    repository.record_balance_change(user.id, 128 - user.balance, "board_bonus", NOW)
    yield context
    engine.dispose()

def receive(context, message_id, content, sender="user-1", **options):
    service, _, factory = context
    options.setdefault("chatroom_id", "group-main")
    result = service.receive_inbound(InboundMessage(message_id, sender, content, NOW, **options))
    with factory() as session:
        return "\n".join(session.scalars(select(OutboundRecord.text).where(
            OutboundRecord.inbound_message_id == result.message_id).order_by(OutboundRecord.reply_index)))

def count(factory, model):
    with factory() as session:
        return session.scalar(select(func.count()).select_from(model))

def rank(context, order):
    with context[2].begin() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.platform_id == "user-1"))
        user.rank_id = session.scalar(select(RankRecord.id).where(RankRecord.sort_order == order))

def inbound(context, identifier, number=6, level=1):
    context[1].accept_inbound(InboundMessage(identifier, "user-1", f"/升级装备 {number} {level}", NOW,
        chatroom_id="group-main"), PRIMARY_GROUP_CHAT_ID)

def test_free_baseline_and_rank_filtered_shop(context):
    _, repo, factory = context
    before = repo.find_user("user-1").balance
    shop = repo.get_workstation_shop("user-1")
    assert len(shop["items"]) == 9
    assert {r["highest_level"] for r in shop["items"]} == {1}
    assert {r["status"] for r in shop["items"]} == {"environment_bundle", "rank_locked"}
    assert shop["daily_income"] == 0 and shop["level_cap"] == 1
    assert "职级不足" in receive(context, "rank-locked", "/升级 电脑")
    assert "无需购买" in receive(context, "buy", "/购买装备 6")
    assert repo.find_user("user-1").balance == before
    assert count(factory, EquipmentPurchaseRecord) == 0
    rank(context, 2)
    computer = next(r for r in repo.get_workstation_shop("user-1")["items"] if r["number"] == 6)
    assert computer["status"] == "available" and computer["price"] == 20
    assert computer["upgrade_command"] == "/升级装备 6"
    assert "电脑" in receive(context, "inventory", "/工位背包")
    assert len(repo.list_shop_items(PRIMARY_GROUP_CHAT_ID)) > 0


def test_workstation_income_table_uses_workbook_levels_and_prices(context):
    text = receive(context, "income-table", "/工位收益表")
    lines = text.splitlines()
    assert lines[:2] == ["【工位收益表】", "环境类"]
    assert "Lv1 收益0｜升级费用 300" in lines
    assert "Lv2 收益2｜升级费用 950" in lines
    assert "Lv5 收益20｜已满级" in lines
    assert lines[7] == "设备类"
    assert "Lv1-1 收益0｜升级费用 20" in lines
    assert "Lv2-1 收益5｜升级费用 70" in lines
    assert "Lv5-2 收益40｜已满级" in lines
    assert len(lines) == 18

def test_upgrade_replay_stale_rank_cap_and_cross_group_appearance(context):
    _, repo, factory = context
    assert "职级不足" in receive(context, "locked", "/升级装备 6 1")
    rank(context, 3)
    first = receive(context, "upgrade", "/升级装备 6 1")
    assert "升级成功" in first and "实付 20" in first
    assert receive(context, "upgrade", "/升级装备 6 1") == first
    replay = repo.upgrade_workstation_component("upgrade", "user-1", 6, 1, PRIMARY_GROUP_CHAT_ID, NOW)
    assert replay["status"] == "upgraded" and replay["balance"] == 108
    assert repo.upgrade_workstation_component("upgrade", "user-1", 3, 1, PRIMARY_GROUP_CHAT_ID, NOW)["status"] == "request_conflict"
    assert "等级已变化" in receive(context, "duplicate-new-id", "/升级装备 6 1")
    assert "当前已解锁 1-2" in receive(context, "skip", "/升级装备 6 3")
    assert count(factory, WorkstationUpgradeRecord) == 1
    assert repo.find_user("user-1").balance == 108
    assert '当前环境的升级档' in receive(context, 'upgrade3', '/升级装备 6 2')
    rank(context, 1)
    repo.create_group_chat('第二群', 'https://www.aikda.com/chat?c=group-other', True, True, False, False, NOW)
    assert '已装备 电脑' in receive(context, 'old-look', '/装备 6 2', chatroom_id='group-other')
    assert '预计工位日收入：2 摸鱼币。' in receive(context, 'overview', '/我的工位')
    assert '已卸下' in receive(context, 'remove', '/卸下 6')
    assert repo.get_workstation_shop('user-1')['daily_income'] == 0
    assert '已装备' in receive(context, 'restore', '/装备 6 2')
    assert '当前环境' in receive(context, 'unowned', '/装备 6 3')
    assert repo.find_user('user-1').balance == 108


def test_single_number_upgrades_one_level_and_replay_never_charges_again(context):
    _, repo, factory = context
    assert "职级不足" in receive(context, "auto-locked", "/升级装备 6")
    rank(context, 3)
    first = receive(context, "auto-first", "/升级装备 6")
    assert "基础黑色台式电脑 1-2" in first and "实付 20" in first
    assert receive(context, "auto-first", "/升级装备 6") == first
    # Wearing an older appearance must not determine which level gets unlocked next.
    assert "已装备" in receive(context, "auto-old-look", "/装备 6 1")
    assert '当前环境的升级档' in receive(context, 'auto-second', '/升级装备 6')
    assert repo.find_user('user-1').balance == 108
    replay = repo.upgrade_workstation_component('auto-first', 'user-1', 6, None, PRIMARY_GROUP_CHAT_ID, NOW)
    assert replay['level'] == 2 and replay['balance'] == 108
    assert repo.upgrade_workstation_component('auto-first', 'user-1', 3, None, PRIMARY_GROUP_CHAT_ID, NOW)['status'] == 'request_conflict'
    assert '不存在' in receive(context, 'auto-unknown', '/升级装备 99')
    assert count(factory, WorkstationUpgradeRecord) == 1
    with factory() as session:
        row = session.get(WorkstationComponentRecord, (repo.find_user('user-1').id, 6))
        assert row.highest_level == 2 and row.active_level == 1 and row.equipped


def test_shortage_is_exact_and_no_receipt_or_deduction_on_failure(context):
    _, repo, factory = context
    rank(context, 2)
    user = repo.find_user("user-1")
    repo.record_balance_change(user.id, 7-user.balance, "board_bonus", NOW)
    assert "还差 13" in receive(context, "short", "/升级装备 6")
    computer = next(r for r in repo.get_workstation_shop("user-1")["items"] if r["number"] == 6)
    assert computer["status"] == "insufficient_balance" and computer["shortage"] == 13
    assert repo.find_user("user-1").balance == 7
    assert count(factory, WorkstationUpgradeRecord) == count(factory, WorkstationComponentRecord) == 0

def test_legacy_purchases_never_discount_upgrades(context):
    _, repo, factory = context
    repo.list_equipment("user-1")
    with factory.begin() as session:
        item = session.scalar(select(EquipmentItemRecord).where(EquipmentItemRecord.public_number == 1))
        item.price = 27
    repo.accept_inbound(InboundMessage("legacy", "user-1", "legacy purchase", NOW, chatroom_id="group-main"), PRIMARY_GROUP_CHAT_ID)
    assert repo.purchase_equipment("legacy", "user-1", 1, PRIMARY_GROUP_CHAT_ID, NOW).price == 27
    with factory.begin() as session:
        session.scalar(select(EquipmentItemRecord).where(EquipmentItemRecord.public_number == 1)).price = 999
    rank(context, 3)
    shop = repo.get_workstation_shop("user-1")
    assert shop["upgrade_credit"] == 0
    assert all(r["credit_used"] == 0 and r["cash_required"] == (r["price"] or 0) for r in shop["items"])
    assert "实付 20" in receive(context, "credit-first", "/升级装备 6 1")
    assert "实付 20" in receive(context, "credit-second", "/升级装备 7 1")
    assert repo.get_workstation_shop("user-1")["upgrade_credit"] == 0
    assert repo.find_user("user-1").balance == 61
    receive(context, "credit-first", "/升级装备 6 1")
    assert repo.find_user("user-1").balance == 61
    assert count(factory, EquipmentPurchaseRecord) == count(factory, EquipmentOwnershipRecord) == 1
    assert count(factory, WorkstationUpgradeRecord) == 2
    assert "无需购买" in receive(context, "no-legacy-loophole", "/购买装备 1")
    with factory() as session:
        assert session.scalars(select(BalanceTransactionRecord.amount).where(BalanceTransactionRecord.source == "workstation_upgrade")).all() == [-20, -20]
        assert all(r.credit_used == 0 and r.cash_paid == r.price for r in session.scalars(select(WorkstationUpgradeRecord)))
    user = repo.find_user("user-1")
    repo.record_balance_change(user.id, 7 - user.balance, "board_bonus", NOW)
    item = next(r for r in repo.get_workstation_shop("user-1")["items"] if r["number"] == 8)
    assert item["status"] == "insufficient_balance" and item["shortage"] == 13
    assert "还差 13" in receive(context, "legacy-no-discount", "/升级装备 8 1")
    assert repo.find_user("user-1").balance == 7
    assert count(factory, WorkstationUpgradeRecord) == 2

def test_upgrade_rolls_back_cash_and_slot_on_storage_failure(context, monkeypatch):
    _, repo, factory = context
    rank(context, 2)
    inbound(context, "fail")
    original = repo._apply_balance_change
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("storage failure")
    monkeypatch.setattr(repo, "_apply_balance_change", fail)
    with pytest.raises(RuntimeError, match="storage failure"):
        repo.upgrade_workstation_component("fail", "user-1", 6, None, PRIMARY_GROUP_CHAT_ID, NOW)
    assert repo.find_user("user-1").balance == 128
    assert count(factory, WorkstationUpgradeRecord) == count(factory, WorkstationComponentRecord) == 0
    assert repo.get_workstation_shop("user-1")["upgrade_credit"] == 0

def test_excel_costs_and_income_all_slots_board_cap_and_max(context):
    _, repo, factory = context
    rank(context, 11)
    user = repo.find_user("user-1")
    repo.record_balance_change(user.id, 30000-user.balance, "board_bonus", NOW)
    assert repo.get_workstation_shop("user-1")["level_cap"] == 10
    for room in range(1, 6):
        for number in range(6, 10):
            assert '升级成功' in receive(context, f'room-{room}-{number}', f'/升级装备 {number}')
        if room < 5:
            assert '完成' in receive(context, f'advance-{room}', '/升级工位')
    assert repo.find_user('user-1').balance == 30000-18950
    shop = repo.get_workstation_shop('user-1')
    assert shop['daily_income'] == 180
    assert {r['status'] for r in shop['items']} == {'environment_bundle', 'environment_max'}
    assert all(r['price'] is None for r in shop['items'])
    assert '当前环境的升级档' in receive(context, 'max', '/升级装备 6')
    assert count(factory, WorkstationUpgradeRecord) == 20

@pytest.mark.parametrize("content", ["/升级装备", "/升级装备 6 1 2", "/升级装备 0", "/升级装备 ６", "/升级装备 -1", "/升级装备 9999999999", "/升级装备 6 0", "/升级装备 ６ 1", "/升级装备 -1 1", "/升级装备 1 9999999999", "/装备 1", "/卸下 1 2", "/装备 鼠标 2-3", "/装备 电脑 1-1 2"])
def test_invalid_arguments_never_charge(context, content):
    assert "用法" in receive(context,"invalid",content)
    assert context[1].find_user("user-1").balance == 128
    assert count(context[2], WorkstationUpgradeRecord) == 0

@pytest.mark.parametrize("command", sorted(EQUIPMENT_COMMANDS))
def test_direct_messages_cannot_operate(context, command):
    assert "群聊" in receive(context,"direct",command,source_type="direct",chatroom_id="dm")

def test_disabled_group_unknown_user_and_command_switch(context):
    _, repo, factory = context
    for command in ("/工位背包", "/升级装备 6", "/装备 6 1"):
        assert "先使用 /入职" in receive(context,command,command,sender="stranger")
    assert receive(context,"unknown-group","/升级装备 6 1",chatroom_id="missing") == ""
    assert repo.upgrade_workstation_component("x","user-1",6,1,None,NOW)["status"] == "wrong_group"
    with pytest.raises(ValueError,match="入站消息不存在"):
        repo.upgrade_workstation_component("missing","user-1",6,1,PRIMARY_GROUP_CHAT_ID,NOW)
    repo.set_command_enabled("/升级装备", False)
    assert receive(context,"disabled","/升级装备 6 1") == ""
    assert repo.find_user("user-1").balance == 128

    repo.set_command_enabled("/工位背包", False)
    assert receive(context, "disabled-inventory", "/工位背包") == ""
    assert "/工位背包" not in receive(context, "help-after-disable", "/帮助 工位")

def test_help_and_normal_shop_remain_separate(context):
    _, repo, factory = context
    text = receive(context,"help","/帮助 工位")
    assert all(command in text for command in ("/我的工位", "/工位背包", "/工位收益表", "/升级 电脑", "/装备 环境"))
    assert "/装备商城" not in text and "抵扣" not in text
    ordinary = next(item for item in repo.list_shop_items(PRIMARY_GROUP_CHAT_ID) if item.system_key == "ai_quota")
    assert ordinary.name in receive(context,"ordinary",f"/购买 {ordinary.public_number}")
    assert repo.find_user("user-1").balance == 128 - ordinary.price
    assert count(factory, UserItemRecord) == 1
    assert count(factory, WorkstationUpgradeRecord) == 0
