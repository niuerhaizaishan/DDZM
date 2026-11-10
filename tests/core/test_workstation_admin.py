from dataclasses import asdict, replace
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from .test_equipment import context, receive, rank, NOW
from dzmm_bot.core.schema import (
    WorkstationAdminOperationRecord,
    WorkstationIncomeRecord,
    WorkstationIncomeSettingsRecord,
)
from dzmm_bot.core.workstation_actions import WorkstationActionError, digest
from dzmm_bot.core.workstation_admin import (
    default_rules,
    income_settings,
    validate_rules,
)


def change(repo, *, kind="grant", room=2, level=4):
    number = repo.find_user("user-1").employee_number
    return number, {
        "kind": kind,
        "environment": room,
        "devices": {str(n): {"level": level, "equipped": True} for n in range(6, 10)},
        "actor": "super_admin:测试",
        "reason": "修复导入数据",
        "request_id": str(uuid4()),
        "revision": repo.workstation_admin_player(number)["revision"],
    }


def rules_change(repo, data):
    return {
        "kind": "rules",
        "data": data,
        "revision": repo.workstation_admin_settings()["revision"],
        "actor": "super_admin:测试",
        "reason": "调整活动数值",
        "request_id": str(uuid4()),
    }


def test_admin_grant_preview_apply_audit_idempotency_and_no_wallet_change(context):
    _, repo, factory = context
    number, payload = change(repo)
    balance = repo.find_user("user-1").balance
    preview = repo.workstation_admin_player_preview(number, payload)
    assert preview["after"]["daily_income"] == 42
    result = repo.workstation_admin_player_apply(number, payload, NOW)
    assert result["workstation"] == preview["after"]
    assert repo.find_user("user-1").balance == balance
    assert repo.workstation_admin_player_apply(number, payload, NOW)["replayed"]
    with pytest.raises(WorkstationActionError, match="请求编号"):
        repo.workstation_admin_player_apply(
            number, {**payload, "reason": "不同操作"}, NOW
        )
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(WorkstationAdminOperationRecord)
            )
            == 1
        )
    records = repo.workstation_admin_records("operations", query="导入")
    assert records["total"] == 1 and records["items"][0]["before"]["daily_income"] == 0


def test_admin_equip_preserves_owned_progress_and_rejects_stale_or_unowned(context):
    repo = context[1]
    number, grant = change(repo)
    repo.workstation_admin_player_apply(number, grant, NOW)
    _, equip = change(repo, kind="equip", room=1, level=1)
    repo.workstation_admin_player_apply(number, equip, NOW)
    detail = repo.workstation_admin_player(number)["workstation"]["progression"]
    assert detail["growth"]["highest_environment"] == 2
    assert detail["growth"]["active_environment"] == 1
    assert all(
        c["highest_level"] == 4 for c in detail["components"] if c["number"] >= 6
    )
    _, invalid = change(repo, kind="equip", room=3, level=5)
    with pytest.raises(WorkstationActionError, match="尚未拥有"):
        repo.workstation_admin_player_apply(number, invalid, NOW)
    with pytest.raises(WorkstationActionError, match="工位已变化"):
        repo.workstation_admin_player_apply(
            number, {**grant, "request_id": str(uuid4())}, NOW
        )


def test_dynamic_rules_shared_by_chat_quote_apply_and_daily_settlement(context):
    _, repo, factory = context
    rank(context, 10)
    receive(context, "open", "/我的工位")
    old = repo.quote_workstation_action("user-1", {"kind": "upgrade", "number": 6}, NOW)
    rules = default_rules()
    rules["upgrade_costs"][0] = 31
    rules["tool_income"][1] = 7
    rules["device_names"]["computer"][1] = "测试电脑"
    rules["environment_names"][0] = "测试环境"
    rules["environment_income"][0] = 3
    preview = repo.workstation_admin_rules_preview(rules)
    assert (
        preview["before"]["daily_income"] == 0 and preview["after"]["daily_income"] == 3
    )
    payload = rules_change(repo, rules)
    repo.workstation_admin_rules_apply(payload, NOW)
    with pytest.raises(WorkstationActionError):
        repo.apply_workstation_action(
            "user-1", {"kind": "upgrade", "number": 6}, uuid4(), old["revision"], NOW
        )
    quote = repo.quote_workstation_action(
        "user-1", {"kind": "upgrade", "number": 6}, NOW
    )
    assert quote["price"] == 31 and quote["after"]["daily_income"] == 10
    before = repo.find_user("user-1").balance
    result = repo.apply_workstation_action(
        "user-1", {"kind": "upgrade", "number": 6}, uuid4(), quote["revision"], NOW
    )
    assert (
        result["balance"] == before - 31 and result["workstation"]["daily_income"] == 10
    )
    text = receive(context, "updated", "/我的工位")
    assert "测试电脑" in text and "测试环境" in text and "日收益：7" in text
    assert "31" in receive(context, "table", "/工位收益表")
    with factory.begin() as session:
        session.add(
            WorkstationIncomeSettingsRecord(
                id=1, enabled=True, first_settlement_date=NOW.date()
            )
        )
    assert repo.run_workstation_income_jobs(NOW)["amount"] == 10
    rules["tool_income"][1] = 100
    repo.workstation_admin_rules_apply(rules_change(repo, rules), NOW)
    assert repo.run_workstation_income_jobs(NOW)["amount"] == 0
    with factory() as session:
        assert session.scalar(select(WorkstationIncomeRecord)).amount == 10
    assert repo.run_workstation_income_jobs(NOW + timedelta(days=1))["amount"] == 103


def test_config_only_name_change_invalidates_quote_and_rules_revisions(context):
    repo = context[1]
    rank(context, 10)
    receive(context, "open", "/我的工位")
    quote = repo.quote_workstation_action(
        "user-1", {"kind": "upgrade", "number": 9}, NOW
    )
    rules = default_rules()
    rules["environment_names"][0] = "新名称"
    payload = rules_change(repo, rules)
    repo.workstation_admin_rules_apply(payload, NOW)
    assert repo.workstation_admin_rules_apply(payload, NOW)["replayed"]
    with pytest.raises(WorkstationActionError, match="规则已变化"):
        repo.workstation_admin_rules_apply({**payload, "request_id": str(uuid4())}, NOW)
    with pytest.raises(WorkstationActionError):
        repo.apply_workstation_action(
            "user-1", {"kind": "upgrade", "number": 9}, uuid4(), quote["revision"], NOW
        )


def test_income_control_manual_settle_and_preserved_cursor(context):
    _, repo, factory = context
    payload = {
        "kind": "income",
        "enabled": True,
        "revision": digest(income_settings(None)),
        "actor": "super_admin:测试",
        "reason": "开始结算",
        "request_id": str(uuid4()),
    }
    enabled = repo.workstation_admin_income_apply(payload, NOW)
    assert enabled["settlement"]["first_date"] == NOW.date().isoformat()
    settled = repo.workstation_admin_income_apply(
        {
            **payload,
            "kind": "settle",
            "revision": enabled["revision"],
            "request_id": str(uuid4()),
        },
        NOW,
    )
    assert settled["result"]["accounts"] == 1
    disabled = repo.workstation_admin_income_apply(
        {
            **payload,
            "enabled": False,
            "revision": settled["revision"],
            "request_id": str(uuid4()),
        },
        NOW,
    )
    assert disabled["settlement"]["last_settled_on"] == NOW.date().isoformat()
    again = repo.workstation_admin_income_apply(
        {**payload, "revision": disabled["revision"], "request_id": str(uuid4())}, NOW
    )
    assert again["settlement"]["last_settled_on"] == NOW.date().isoformat()
    assert repo.run_workstation_income_jobs(NOW)["accounts"] == 0
    assert repo.workstation_admin_records("settlements", query="糯糯")["total"] == 1
    assert repo.workstation_admin_overview(NOW)["settled_accounts"] == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("tool_income", [1]),
        ("upgrade_costs", [True] * 9),
        ("environment_income", [-1] * 5),
        ("environment_names", [""] * 5),
    ],
)
def test_rules_validation(field, value):
    rules = default_rules()
    rules[field] = value
    with pytest.raises(ValueError):
        validate_rules(rules)


def test_birthday_defaults_on_without_overriding_saved_off(context):
    repo = context[1]
    assert repo.get_birthday_settings().enabled
    repo.set_birthday_settings(
        **asdict(replace(repo.get_birthday_settings(), enabled=False))
    )
    assert not repo.get_birthday_settings().enabled


def test_backfill_preview_matches_apply_and_preserves_existing_equipment(context):
    _, repo, factory = context
    number, payload = change(repo, kind="backfill", room=1, level=1)
    preview = repo.workstation_admin_player_preview(number, payload)
    result = repo.workstation_admin_player_apply(number, payload, NOW)
    assert result["workstation"] == preview["after"]
    assert result["workstation"]["progression"]["accessories"]
    _, next_payload = change(repo, kind="backfill", room=1, level=1)
    assert (
        repo.workstation_admin_player_preview(number, next_payload)["before"]
        == repo.workstation_admin_player_preview(number, next_payload)["after"]
    )


def test_failed_adjustment_rolls_back_progress_and_audit(context, monkeypatch):
    _, repo, factory = context
    number, payload = change(repo)
    before = repo.workstation_admin_player(number)

    def fail(*args, **kwargs):
        raise RuntimeError("injected grant failure")

    monkeypatch.setattr(repo, "_grant_environment_accessories", fail)
    with pytest.raises(RuntimeError, match="injected"):
        repo.workstation_admin_player_apply(number, payload, NOW)
    assert repo.workstation_admin_player(number) == before
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(WorkstationAdminOperationRecord)
            )
            == 0
        )


def test_group_rule_lock_precedes_user_activity_write(context, monkeypatch):
    repo = context[1]
    original_lock = repo.lock_workstation_rules
    original_activity = repo.record_activity
    order = []

    def lock(*args, **kwargs):
        order.append("rules")
        return original_lock(*args, **kwargs)

    def activity(*args, **kwargs):
        order.append("activity")
        return original_activity(*args, **kwargs)

    monkeypatch.setattr(repo, "lock_workstation_rules", lock)
    monkeypatch.setattr(repo, "record_activity", activity)
    receive(context, "lock-order", "/升级 鼠标")
    assert order[0] == "rules" and order.index("activity") > 0
