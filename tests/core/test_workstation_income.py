from datetime import datetime, date, timezone
from zoneinfo import ZoneInfo
import pytest
from sqlalchemy import select, func
from .test_equipment import context, receive, rank, NOW
from dzmm_bot.core.schema import (WorkstationIncomeSettingsRecord, WorkstationIncomeRecord,
                                 BalanceTransactionRecord, WorkstationComponentRecord)

DAY = date(2026, 11, 5)
MIDNIGHT = datetime(2026, 11, 5, tzinfo=ZoneInfo('Asia/Shanghai'))


def enable(context, first=DAY):
    with context[2].begin() as s:
        s.add(WorkstationIncomeSettingsRecord(id=1, enabled=True, first_settlement_date=first))


def receipts(context):
    with context[2]() as s:
        return s.scalar(select(func.count()).select_from(WorkstationIncomeRecord))


def test_activation_date_timezone_idempotency_and_account_ledger(context):
    _, repo, factory = context
    rank(context, 10)
    receive(context, 'upgrade', '/升级 电脑')
    before = repo.find_user('user-1').balance
    assert not repo.workstation_income_enabled()
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 0
    enable(context)
    assert repo.get_workstation_shop('user-1')['income_settlement_enabled']
    assert repo.run_workstation_income_jobs(datetime(2026, 11, 4, 15, 59, 59, tzinfo=timezone.utc))['amount'] == 0
    assert receipts(context) == 0
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 2
    assert repo.find_user('user-1').balance == before + 2
    assert repo.run_workstation_income_jobs(MIDNIGHT)['accounts'] == 0
    # An independent repository/worker cannot credit again after restart.
    from dzmm_bot.core.repository import CoreRepository
    assert CoreRepository(factory).run_workstation_income_jobs(MIDNIGHT)['accounts'] == 0
    assert receipts(context) == 1
    with factory() as s:
        ledger = list(s.scalars(select(BalanceTransactionRecord).where(BalanceTransactionRecord.source == 'workstation_income')))
        assert len(ledger) == 1 and ledger[0].amount == 2
        r = s.get(WorkstationIncomeRecord, (repo.find_user('user-1').id, DAY))
        assert sum(c['daily_income'] for c in r.components) == r.amount


def test_snapshot_equipped_only_zero_receipt_and_no_historical_backpay(context):
    _, repo, _ = context
    rank(context, 10)
    receive(context, 'upgrade', '/升级 鼠标')
    receive(context, 'remove', '/卸下 鼠标')
    enable(context)
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 0
    assert receipts(context) == 1
    receive(context, 'equip', '/装备 鼠标 1-2')
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 0
    late = MIDNIGHT.replace(day=9)
    assert repo.run_workstation_income_jobs(late)['amount'] == 2
    assert receipts(context) == 2  # no invented historical snapshots on missed days


def test_failed_batch_rolls_back_receipts_credits_and_cursor(context, monkeypatch):
    _, repo, factory = context
    rank(context, 10)
    receive(context, 'upgrade', '/升级 鼠标')
    enable(context)
    before = repo.find_user('user-1').balance
    original = repo._apply_balance_change
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('injected credit failure')
    monkeypatch.setattr(repo, '_apply_balance_change', fail)
    with pytest.raises(RuntimeError, match='injected'):
        repo.run_workstation_income_jobs(MIDNIGHT)
    assert receipts(context) == 0
    assert repo.find_user('user-1').balance == before
    with factory() as s:
        assert s.get(WorkstationIncomeSettingsRecord, 1).last_settled_on is None
    monkeypatch.setattr(repo, '_apply_balance_change', original)
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 2


def test_max_environment_and_four_devices_total_180_without_accessory_income(context):
    _, repo, factory = context
    user = repo.find_user('user-1')
    with factory.begin() as s:
        for n in range(1, 10):
            level = 9 if n <= 5 else 10
            s.add(WorkstationComponentRecord(user_id=user.id, category_number=n,
                  highest_level=level, active_level=level, equipped=True))
    enable(context)
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 180


def test_disabled_and_new_joiners_wait_for_next_daily_snapshot(context):
    _, repo, factory = context
    enable(context)
    with factory.begin() as s:
        s.get(WorkstationIncomeSettingsRecord, 1).enabled = False
    assert repo.run_workstation_income_jobs(MIDNIGHT)['accounts'] == 0
    with factory.begin() as s:
        s.get(WorkstationIncomeSettingsRecord, 1).enabled = True
    repo.run_workstation_income_jobs(MIDNIGHT)
    receive(context, 'new', '/入职 新同事', sender='new-user')
    assert repo.run_workstation_income_jobs(MIDNIGHT)['accounts'] == 0
    assert receipts(context) == 1
    assert repo.run_workstation_income_jobs(MIDNIGHT.replace(day=6))['accounts'] == 2

@pytest.mark.parametrize('room,total', [(1,0),(2,2),(3,5),(4,10),(5,20)])
@pytest.mark.parametrize('tier', [1,2])
def test_whole_environment_income_matches_views_and_settlement(context, room, total, tier):
    _, repo, factory = context
    user = repo.find_user('user-1')
    with factory.begin() as s:
        for n in range(1, 10):
            level = room*2-2+tier if n<=5 else 1
            s.add(WorkstationComponentRecord(user_id=user.id,category_number=n,
                highest_level=level,active_level=level,equipped=True))
    workstation = repo.get_workstation(user.id)
    assert workstation['daily_income'] == total
    assert repo.get_workstation_shop('user-1')['daily_income'] == total
    assert next(i for i in repo.list_workstations()['items'] if i['number']==user.employee_number)['daily_income'] == total
    assert all(type(c['daily_income']) is int for c in workstation['progression']['components'])
    before = repo.find_user('user-1').balance
    enable(context)
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == total
    assert repo.find_user('user-1').balance == before + total
    assert repo.run_workstation_income_jobs(MIDNIGHT)['amount'] == 0
