from sqlalchemy import func, select

from tests.core.test_equipment import context, receive, rank, NOW
from dzmm_bot.core.schema import (
    BalanceTransactionRecord, WorkstationAccessoryPurchaseRecord,
    WorkstationAccessoryRecord,
)


def test_environment_upgrade_grants_accessories_without_purchase(context):
    _, repo, factory = context
    rank(context, 10)
    user = repo.find_user("user-1")
    repo.record_balance_change(user.id, 40000 - user.balance, "board_bonus", NOW)
    for number in range(6, 10):
        receive(context, f"upgrade-{number}", f"/升级装备 {number}")
    before = repo.find_user("user-1").balance
    assert "实付 460" in receive(context, "advance", "/升级工位")
    assert repo.find_user("user-1").balance == before - 460
    progression = repo.get_workstation(user.id)["progression"]
    assert {item["number"] for item in progression["accessories"]} == {101, 102, 201, 202, 203, 204}
    assert all(item["equipped"] for item in progression["accessories"])
    assert receive(context, "shop", "/装备商城") == ""
    assert "购买成功" not in receive(context, "disabled", "/购买装备 201")
    assert repo.find_user("user-1").balance == before - 460
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkstationAccessoryPurchaseRecord)) == 0
        assert session.scalar(select(func.count()).select_from(BalanceTransactionRecord).where(
            BalanceTransactionRecord.user_id == user.id,
            BalanceTransactionRecord.source == "equipment_purchase",
        )) == 0
        assert session.scalar(select(func.count()).select_from(WorkstationAccessoryRecord)) == 6
