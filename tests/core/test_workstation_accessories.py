"""Environment-granted accessories preserve ownership, art and payment safety."""
from io import BytesIO
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from PIL import Image, ImageChops
from tests.core.test_equipment import context, receive, rank, NOW
from dzmm_bot.core.schema import WorkstationComponentRecord, WorkstationAccessoryPurchaseRecord
from dzmm_bot.core.workstation_accessories import ACCESSORIES
from dzmm_bot.core.workstation_stage5 import accessory_scene
from dzmm_bot.core.workstation_actions import WorkstationActionError
from dzmm_bot.browser.workstation_image import render_workstation_image


def seed_room(context, room):
    _, repo, factory = context
    user = repo.find_user('user-1')
    with factory.begin() as session:
        for number in range(1, 10):
            session.add(WorkstationComponentRecord(user_id=user.id,category_number=number,
                highest_level=room*2,active_level=room*2,equipped=True))
        repo._grant_environment_accessories(session,user.id,room)
    return user


@pytest.mark.parametrize('item', ACCESSORIES, ids=lambda a: str(a['number']))
def test_granted_accessory_rejects_paid_purchase_and_can_be_removed_restored(context, item):
    _,repo,factory=context
    rank(context,10)
    user=seed_room(context,item['environment'])
    receive(context,'entry','/我的工位')
    before=repo.find_user('user-1').balance
    holding=next(a for a in repo.get_workstation(user.id)['progression']['accessories'] if a['number']==item['number'])
    assert holding['equipped']
    assert '不再单独购买' in receive(context,'buy',f'/购买装备 {item["number"]}')
    for operation in ('quote','apply'):
        with pytest.raises(WorkstationActionError,match='无需购买'):
            action={'kind':'purchase','number':item['number']}
            if operation=='quote':repo.quote_workstation_action('user-1',action,NOW)
            else:repo.apply_workstation_action('user-1',action,uuid4(),None,NOW)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkstationAccessoryPurchaseRecord))==0
    assert repo.find_user('user-1').balance==before
    full,removed=BytesIO(),BytesIO()
    render_workstation_image(repo.get_workstation(user.id),full)
    repo.set_workstation_accessory('user-1',item['number'],equipped=False)
    render_workstation_image(repo.get_workstation(user.id),removed)
    assert ImageChops.difference(Image.open(full).convert('RGB'),Image.open(removed).convert('RGB')).getbbox()
    assert next(a for a in repo.get_workstation(user.id)['progression']['accessories'] if a['number']==item['number'])['equipped'] is False
    repo.set_workstation_accessory('user-1',item['number'],equipped=True)
    restored=BytesIO();render_workstation_image(repo.get_workstation(user.id),restored)
    assert full.getvalue()==restored.getvalue()
    assert repo.find_user('user-1').balance==before


@pytest.mark.parametrize('room',[2,3,4,5])
def test_higher_room_accessories_remain_owned_when_old_room_is_shown(context,room):
    _,repo,_=context
    user=seed_room(context,room)
    before=repo.get_workstation(user.id)['progression']['accessories']
    with repo.transaction(),repo._session() as session:repo._activate_environment(session,user.id,1)
    old=repo.get_workstation(user.id)['progression']
    assert old['accessories']==before
    assert old['accessory_scene']['environment']==1
    current_keys={a['key'] for a in ACCESSORIES if a['environment']==1}
    assert {l['key'] for l in old['accessory_scene']['layers']} & {a['key'] for a in ACCESSORIES} == current_keys
    overview=receive(context,'overview','/我的工位')
    assert '配件：' not in overview
    assert receive(context,'retired-inventory','/我的装备')==''


@pytest.mark.parametrize('item',[a for a in ACCESSORIES if a['environment']>1],ids=lambda a:str(a['number']))
def test_future_accessory_cannot_be_equipped_before_environment_is_owned(context,item):
    _,repo,_=context
    rank(context,10);receive(context,'entry','/我的工位')
    before=repo.find_user('user-1').balance
    with pytest.raises(WorkstationActionError,match='尚未随环境升级获得'):
        repo.quote_workstation_action('user-1',{'kind':'equip','number':item['number']},NOW)
    assert repo.find_user('user-1').balance==before


@pytest.mark.parametrize('monitor_level,equipped,expected',[(9,True,'lightbar-basic'),(10,True,'lightbar'),(9,False,None),(10,False,None)])
def test_mounted_lamp_follows_monitor_and_never_floats(monitor_level,equipped,expected):
    from dzmm_bot.core.workstation_art import ART_ORDER
    components=[{'key':key,'active_level':10,'equipped':True} for key in ART_ORDER]
    next(row for row in components if row['key']=='monitor').update(active_level=monitor_level,equipped=equipped)
    ownership=[{'number':508,'equipped':True}]
    keys={layer['key'] for layer in accessory_scene(components,ownership)['layers']}
    assert keys & {'lightbar','lightbar-basic'}==({expected} if expected else set())
    assert ownership==[{'number':508,'equipped':True}]
