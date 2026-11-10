"""Chat, account API, previews and paid actions share the same persisted state."""
from sqlalchemy import select

from tests.core.test_equipment import context, receive, rank, NOW
from dzmm_bot.core.schema import WorkstationComponentRecord


def test_batch_offer_matches_quote_payment_and_persisted_environment(context):
    _, repo, _ = context
    rank(context, 10)
    user = repo.find_user('user-1')
    repo.record_balance_change(user.id, 40000 - user.balance, 'board_bonus', NOW)
    receive(context, 'entry', '/我的工位')
    for number in range(6, 10):
        receive(context, f'up-{number}', f'/升级装备 {number}')
    shop = repo.get_workstation_shop('user-1')
    assert shop['growth']['active_environment'] == 1
    assert shop['growth_offers']['advance']['price'] == 460
    assert shop['growth_offers']['polish']['price'] == 0
    quote = repo.quote_workstation_action('user-1', {'kind': 'advance'}, NOW)
    assert quote['price'] == shop['growth_offers']['advance']['price']
    assert receive(context, 'shop', '/装备商城') == ''
    assert '实付 460' in receive(context, 'advance', '/升级工位')
    after = repo.get_workstation(user.id)['progression']
    assert after['growth'] == quote['after']['progression']['growth']
    assert after['growth'] == repo.get_workstation_shop('user-1')['growth']
    assert after['growth']['active_environment'] == after['growth']['highest_environment'] == 2
    assert {a['number'] for a in after['accessories']} == {101,102,201,202,203,204}
    assert repo.find_user('user-1').balance == 39460
    # Read-only views cannot create receipts or change the balance.
    for text in ('/我的工位', '/我的装备', '/装备商城 全部'):
        receive(context, 'read-' + text, text)
    assert repo.find_user('user-1').balance == 39460


def test_owned_accessories_survive_old_room_and_low_balance(context):
    _,repo,_=context
    rank(context,10);user=repo.find_user('user-1')
    repo.record_balance_change(user.id,40000-user.balance,'board_bonus',NOW)
    for number in range(6,10):receive(context,f'up-{number}',f'/升级装备 {number}')
    receive(context,'advance','/升级工位')
    receive(context,'old-room','/切换工位 1')
    growth=repo.get_workstation_shop('user-1')['growth']
    assert growth==repo.get_workstation(user.id)['progression']['growth']
    assert growth['active_environment']==1 and growth['highest_environment']==2
    assert growth['accessories_owned']==growth['accessories_equipped']==6
    overview=receive(context,'overview','/我的工位')
    assert '环境：1级 临时办公角落【日收益：0】' in overview
    assert '电脑：1-2 基础黑色台式电脑【日收益：2】' in overview
    assert '配件：' not in overview
    assert receive(context,'inventory','/我的装备')==''
    receive(context,'remove','/卸下 201')
    assert repo.get_workstation_shop('user-1')['growth']['accessories_equipped']==5
    receive(context,'new-room','/切换工位 2')
    balance=repo.find_user('user-1').balance
    repo.record_balance_change(user.id,-balance,'board_bonus',NOW)
    shop=repo.get_workstation_shop('user-1')
    assert next(i for i in shop['items'] if i['number']==6)['status']=='insufficient_balance'
    assert next(a for a in shop['accessories'] if a['number']==202)['owned']
    assert receive(context,'poor-shop','/装备商城')==''


def test_environment_progress_does_not_promise_unowned_complete_room(context):
    _, repo, factory = context
    rank(context, 10)
    user = repo.find_user('user-1')
    with factory.begin() as session:
        for number in range(1, 6):
            session.add(WorkstationComponentRecord(user_id=user.id, category_number=number,
                highest_level=3, active_level=3, equipped=True))
    before = repo.get_workstation_shop('user-1')
    assert before['growth']['active_environment'] is None
    assert before['growth']['highest_environment'] == 2
    assert before['growth']['switchable_environment'] == 1
    assert '环境：混合搭配' in receive(context, 'mixed', '/我的工位')
    assert '该环境尚未整套配齐，请使用 /升级工位' in receive(context, 'unowned-room', '/切换工位 2')
    with factory.begin() as session:
        row = session.scalar(select(WorkstationComponentRecord).where(
            WorkstationComponentRecord.user_id == user.id, WorkstationComponentRecord.category_number == 3))
        row.equipped = False
    assert repo.get_workstation(user.id)['progression']['growth']['core_equipped_count'] == 8


def test_future_accessory_explains_automatic_environment_grant(context):
    _,repo,_=context
    item=next(a for a in repo.get_workstation_shop('user-1')['accessories'] if a['number']==504)
    assert item['status']=='locked' and item['price'] is None
    assert item['unlock_description']=='升级到环境5后自动获得'
    before=repo.find_user('user-1').balance
    assert '自动获得' in receive(context,'purchase-disabled','/购买装备 504')
    assert receive(context,'retired-shop','/装备商城 全部')==''
    assert repo.find_user('user-1').balance==before
