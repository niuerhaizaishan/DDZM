"""Environment rules must agree across admin, chat, quotes and wallet ledger."""
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from .test_equipment import context, receive, rank, NOW
from .test_workstation_admin import change, rules_change
from dzmm_bot.core.schema import (
    BalanceTransactionRecord, WorkstationRulesRecord, WorkstationComponentRecord,
    WorkstationActionRecord,
)
from dzmm_bot.core.workstation_actions import WorkstationActionError
from dzmm_bot.core.workstation_admin import default_rules, validate_rules


def prepare(context, room=1):
    repo = context[1]
    rank(context, 10)
    receive(context, "open", "/我的工位")
    number, payload = change(repo, room=room, level=room * 2)
    repo.workstation_admin_player_apply(number, payload, NOW)
    repo.record_balance_change(repo.find_user("user-1").id, 10000, "test", NOW)
    return repo


@pytest.mark.parametrize("room,price", [(1, 137), (2, 501), (3, 0), (4, 12345)])
def test_saved_environment_price_matches_offer_quote_chat_charge_and_replay(context, room, price):
    repo = prepare(context, room)
    user = repo.find_user("user-1")
    if price > user.balance:
        repo.record_balance_change(user.id, price, "test", NOW)
    old = repo.quote_workstation_action("user-1", {"kind": "advance"}, NOW)
    rules = default_rules()
    rules["environment_upgrade_costs"][room - 1] = price
    rules["environment_income"][room] = 33
    rules["tool_income"][room * 2] = 11
    # Changing device upgrade prices must not add surcharges to the bundle.
    rules["upgrade_costs"][room * 2 - 1] = 999
    repo.workstation_admin_rules_preview(rules)
    repo.workstation_admin_rules_apply(rules_change(repo, rules), NOW)
    with pytest.raises(WorkstationActionError):
        repo.apply_workstation_action("user-1", {"kind": "advance"}, uuid4(), old["revision"], NOW)
    offer = repo.get_workstation_shop("user-1")["growth_offers"]["advance"]
    quote = repo.quote_workstation_action("user-1", {"kind": "advance"}, NOW)
    assert quote["price"] == offer["price"] == price
    assert quote["after"]["daily_income"] == 33 + 4 * 11
    table = receive(context, "table", "/工位收益表")
    assert f"Lv{room} 收益{rules['environment_income'][room - 1]}｜升级费用 {price}" in table
    before = repo.find_user("user-1").balance
    key = uuid4()
    result = repo.apply_workstation_action("user-1", {"kind": "advance"}, key, quote["revision"], NOW)
    assert result["price"] == price and result["balance"] == before - price
    assert result["workstation"] == quote["after"]
    assert repo.apply_workstation_action("user-1", {"kind": "advance"}, key, quote["revision"], NOW)["replayed"]
    assert repo.find_user("user-1").balance == before - price
    with context[2]() as session:
        charges = list(session.scalars(select(BalanceTransactionRecord).where(
            BalanceTransactionRecord.source == "workstation_upgrade")))
        assert sum(row.amount for row in charges) == -price
        assert len(charges) == (1 if price else 0)


def test_group_environment_upgrade_uses_saved_price(context):
    repo = prepare(context)
    rules = default_rules()
    rules["environment_upgrade_costs"][0] = 173
    repo.workstation_admin_rules_apply(rules_change(repo, rules), NOW)
    before = repo.find_user("user-1").balance
    text = receive(context, "advance", "/升级工位")
    assert "实付 173" in text
    assert repo.find_user("user-1").balance == before - 173
    assert receive(context, "advance", "/升级工位") == text
    assert repo.find_user("user-1").balance == before - 173


def test_old_saved_rules_derive_prices_from_their_custom_steps(context):
    repo = context[1]
    rules = default_rules()
    rules.pop("environment_upgrade_costs")
    rules["upgrade_costs"][0:2] = [30, 50]
    with context[2].begin() as session:
        session.add(WorkstationRulesRecord(id=1, version=7, data=rules))
    settings = repo.workstation_admin_settings()
    assert settings["rules"]["environment_upgrade_costs"] == [600, 1430, 3700, 7400]
    assert settings["revision"] == 7
    assert "Lv1 收益0｜升级费用 600" in receive(context, "table", "/工位收益表")
    # Merely reading or locking old rules does not overwrite saved configuration.
    with context[2]() as session:
        assert "environment_upgrade_costs" not in session.get(WorkstationRulesRecord, 1).data


def test_legacy_partial_ownership_retains_paid_progress_discount(context):
    repo = prepare(context)
    rules = default_rules()
    rules["environment_upgrade_costs"][0] = 920
    repo.workstation_admin_rules_apply(rules_change(repo, rules), NOW)
    with context[2].begin() as session:
        row = session.get(WorkstationComponentRecord, (repo.find_user("user-1").id, 1))
        row.highest_level = 2  # One legacy layout step already bought (20 of 460).
    quote = repo.quote_workstation_action("user-1", {"kind": "advance"}, NOW)
    assert quote["price"] == 880  # 920 * (460 - 20) / 460
    before = repo.find_user("user-1").balance
    result = repo.apply_workstation_action("user-1", {"kind": "advance"}, uuid4(), quote["revision"], NOW)
    assert result["balance"] == before - 880


def test_changed_price_checks_balance_and_failures_roll_back_bundle(context, monkeypatch):
    repo = prepare(context)
    before = repo.find_user("user-1").balance
    rules = default_rules()
    rules["environment_upgrade_costs"][0] = before + 1
    repo.workstation_admin_rules_apply(rules_change(repo, rules), NOW)
    assert repo.get_workstation_shop("user-1")["growth_offers"]["advance"]["status"] == "insufficient_balance"
    with pytest.raises(WorkstationActionError, match="余额不足"):
        repo.apply_workstation_action("user-1", {"kind": "advance"}, uuid4(), None, NOW)
    rules["environment_upgrade_costs"][0] = 99
    repo.workstation_admin_rules_apply(rules_change(repo, rules), NOW)
    station = repo.get_workstation(repo.find_user("user-1").id)
    def fail(*args, **kwargs):
        raise RuntimeError("injected failure after bundle charge")
    monkeypatch.setattr(repo, "_grant_environment_accessories", fail)
    with pytest.raises(RuntimeError, match="injected"):
        repo.apply_workstation_action("user-1", {"kind": "advance"}, uuid4(), None, NOW)
    assert repo.find_user("user-1").balance == before
    assert repo.get_workstation(repo.find_user("user-1").id) == station
    with context[2]() as session:
        assert session.scalar(select(func.count()).select_from(WorkstationActionRecord)) == 0
        assert session.scalar(select(func.count()).select_from(BalanceTransactionRecord).where(
            BalanceTransactionRecord.source == "workstation_upgrade")) == 0


@pytest.mark.parametrize("value", [[1, 2, 3], [1, 2, 3, -1], [1, 2, True, 4], [1, 2, 3, 20000001], [1, 2, 3, 1.5]])
def test_environment_price_validation(value):
    rules = default_rules()
    rules["environment_upgrade_costs"] = value
    with pytest.raises(ValueError, match="environment_upgrade_costs"):
        validate_rules(rules)
