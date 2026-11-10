"""A room bundles its background; four devices have exactly two local tiers."""
import pytest
from uuid import uuid4

from tests.core.test_equipment import context, receive, rank, NOW
from dzmm_bot.core.workstation_actions import WorkstationActionError
from dzmm_bot.core.workstation_catalog import UPGRADE_COSTS
from dzmm_bot.core.schema import WorkstationComponentRecord, WorkstationActionRecord, BalanceTransactionRecord
from tests.core.test_equipment import count


@pytest.mark.parametrize('number', range(1, 6))
def test_background_cannot_be_upgraded_equipped_or_removed_independently(context, number):
    _, repo, _ = context
    rank(context, 10)
    receive(context, 'entry', '/我的工位')
    for action in ({'kind': 'upgrade', 'number': number},
                   {'kind': 'equip', 'number': number, 'level': 1},
                   {'kind': 'remove', 'number': number}):
        with pytest.raises(WorkstationActionError, match='环境'):
            repo.quote_workstation_action('user-1', action, NOW)
    for i, text in enumerate((('/升级装备 1', '/装备 1 1', '/卸下 1') if number == 1 else ())):
        assert '随环境整体' in receive(context, f'background-{i}', text)
    assert repo.find_user('user-1').balance == 128


def test_all_five_rooms_enforce_two_tiers_and_same_quote_payment(context):
    _, repo, _ = context
    rank(context, 10)
    user = repo.find_user('user-1')
    repo.record_balance_change(user.id, 40000-user.balance, 'board_bonus', NOW)
    receive(context, 'entry', '/我的工位')
    for room in range(1, 6):
        shop = repo.get_workstation_shop('user-1')
        assert shop['growth']['active_environment'] == room
        overview = receive(context, f'base-overview-{room}', '/我的工位')
        for category in ('电脑', '显示器', '键盘', '鼠标'):
            assert f'{category}：{room}-1 ' in overview
        for number in range(6, 10):
            assert '升级成功' in receive(context, f'up-{room}-{number}', f'/升级装备 {number}')
            before = repo.find_user('user-1').balance
            assert '当前环境的升级档' in receive(context, f'blocked-{room}-{number}', f'/升级装备 {number}')
            with pytest.raises(WorkstationActionError, match='当前环境的升级档'):
                repo.quote_workstation_action('user-1', {'kind': 'upgrade', 'number': number}, NOW)
            assert repo.find_user('user-1').balance == before
            item = next(c for c in repo.get_workstation_shop('user-1')['items'] if c['number'] == number)
            assert item['selectable_levels'] == [room*2-1, room*2]
            assert item['price'] is None and item['next_level'] is None
            if room > 1:
                assert '只能选择当前环境' in receive(context, f'old-tier-{room}-{number}', f'/装备 {number} 1')
        overview = receive(context, f'upgraded-overview-{room}', '/我的工位')
        for category in ('电脑', '显示器', '键盘', '鼠标'):
            assert f'{category}：{room}-2 ' in overview
        assert '不再单独精修' in receive(context, f'polish-{room}', '/精修工位')
        if room < 5:
            quote = repo.quote_workstation_action('user-1', {'kind': 'advance'}, NOW)
            before = repo.find_user('user-1').balance
            assert f"实付 {quote['price']}" in receive(context, f'advance-{room}', '/升级工位')
            assert repo.find_user('user-1').balance == before-quote['price']
            after = repo.get_workstation(user.id)['progression']
            assert after['growth'] == quote['after']['progression']['growth']
            assert {c['active_level'] for c in after['components']} == {room*2+1}
    assert repo.find_user('user-1').balance == 40000 - (5*sum(UPGRADE_COSTS[:8])+4*sum(UPGRADE_COSTS))
    assert repo.get_workstation(user.id)['daily_income'] == 180


def test_legacy_owned_higher_levels_are_retained_but_current_room_is_bounded(context):
    _, repo, _ = context
    rank(context, 10)
    user = repo.find_user('user-1')
    repo.record_balance_change(user.id, 40000-user.balance, 'board_bonus', NOW)
    for number in range(6, 10):
        receive(context, f'previous-room-up-{number}', f'/升级装备 {number}')
    receive(context, 'advance', '/升级工位')
    receive(context, 'upgrade', '/升级装备 6')
    receive(context, 'old-room', '/切换工位 1')
    item = next(c for c in repo.get_workstation_shop('user-1')['items'] if c['number'] == 6)
    assert item['highest_level'] == 4 and item['selectable_levels'] == [1, 2]
    balance = repo.find_user('user-1').balance
    assert '只能选择当前环境' in receive(context, 'cross-room', '/装备 6 4')
    receive(context, 'back', '/切换工位 2')
    assert next(c for c in repo.get_workstation_shop('user-1')['items'] if c['number'] == 6)['highest_level'] == 4
    assert repo.find_user('user-1').balance == balance


@pytest.mark.parametrize('room', range(1, 5))
def test_advancing_requires_all_four_owned_upgrades_in_previous_highest_room(context, room):
    _, repo, factory = context
    rank(context, 10)
    user = repo.find_user('user-1')
    repo.record_balance_change(user.id, 40000-user.balance, 'board_bonus', NOW)
    with factory.begin() as session:
        for number in range(1, 10):
            session.add(WorkstationComponentRecord(user_id=user.id, category_number=number,
                highest_level=room*2-1, active_level=room*2-1, equipped=True))
    receive(context, 'entry', '/我的工位')
    for upgraded in range(4):
        before = repo.get_workstation(user.id)
        balance = repo.find_user('user-1').balance
        ledger_count, receipt_count = count(factory, BalanceTransactionRecord), count(factory, WorkstationActionRecord)
        offer = repo.get_workstation_shop('user-1')['growth_offers']['advance']
        assert offer['status'] == 'devices_required' and len(offer['missing_devices']) == 4-upgraded
        assert not repo.workstation_management('user-1', NOW)['actions']['advance']
        assert f'环境{room}' in receive(context, f'blocked-{upgraded}', '/升级工位')
        for attempt in ('quote', 'direct-apply'):
            with pytest.raises(WorkstationActionError, match='四件设备升至升级款'):
                if attempt == 'quote':
                    repo.quote_workstation_action('user-1', {'kind': 'advance'}, NOW)
                else:
                    repo.apply_workstation_action('user-1', {'kind': 'advance'}, uuid4(), None, NOW)
        assert repo.get_workstation(user.id) == before
        assert repo.find_user('user-1').balance == balance
        assert count(factory, BalanceTransactionRecord) == ledger_count
        assert count(factory, WorkstationActionRecord) == receipt_count
        assert '升级成功' in receive(context, f'up-{upgraded}', f'/升级装备 {6+upgraded}')
    # Ownership qualifies even when an upgraded device is removed or shows its basic appearance.
    receive(context, 'base-appearance', f'/装备 6 {room*2-1}')
    receive(context, 'remove', '/卸下 7')
    assert repo.get_workstation_shop('user-1')['growth_offers']['advance']['status'] == 'available'
    assert repo.workstation_management('user-1', NOW)['actions']['advance']
    quote = repo.quote_workstation_action('user-1', {'kind': 'advance'}, NOW)
    balance = repo.find_user('user-1').balance
    request_id = uuid4()
    result = repo.apply_workstation_action('user-1', {'kind': 'advance'}, request_id, quote['revision'], NOW)
    replay = repo.apply_workstation_action('user-1', {'kind': 'advance'}, request_id, quote['revision'], NOW)
    assert replay['replayed'] and result['price'] == quote['price']
    assert repo.find_user('user-1').balance == balance-quote['price']
    assert repo.get_workstation(user.id)['progression']['growth']['highest_environment'] == room+1

@pytest.mark.parametrize('room', [2, 3, 4, 5])
def test_device_upgrade_uses_owned_room_while_old_room_is_displayed(context, room):
    _, repo, factory = context
    rank(context, 10)
    user = repo.find_user('user-1')
    repo.record_balance_change(user.id, 40000-user.balance, 'board_bonus', NOW)
    with factory.begin() as session:
        for number in range(1, 10):
            session.add(WorkstationComponentRecord(user_id=user.id, category_number=number,
                highest_level=room*2-1, active_level=1, equipped=number != 6))
    receive(context, 'entry', '/我的工位')
    shop = repo.get_workstation_shop('user-1')
    item = next(i for i in shop['items'] if i['number'] == 6)
    assert item['status'] == 'available'
    assert item['next_level'] == room*2
    assert item['environment'] == room and item['equipped_environment'] == 1
    assert item['selectable_levels'] == [1, 2]
    action = {'kind': 'upgrade', 'number': 6}
    quote = repo.quote_workstation_action('user-1', action, NOW)
    result = repo.apply_workstation_action('user-1', action, uuid4(), quote['revision'], NOW)
    actual = repo.get_workstation(user.id)
    component = next(c for c in actual['progression']['components'] if c['number'] == 6)
    assert component['highest_level'] == component['active_level'] == room*2
    assert component['equipped']
    assert actual['progression'] == quote['after']['progression']
    assert repo.find_user('user-1').balance == 40000 - quote['price']
    assert result['price'] == quote['price']
