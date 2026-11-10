"""Five-stage progression exercises the real account rules and artwork."""
from uuid import uuid4
from tests.core.test_equipment import context, receive, rank, NOW
from dzmm_bot.core.workstation_accessories import ACCESSORIES
from dzmm_bot.core.workstation_catalog import environment_daily_income, TOOL_INCOME, upgrade_cost


def test_five_stage_journey_preserves_prices_income_ownership_and_art(context):
    _,repo,_=context
    rank(context,10);user=repo.find_user('user-1')
    repo.record_balance_change(user.id,40000-user.balance,'board_bonus',NOW)
    # Existing accounts receive the initial room grant during the accessory backfill.
    with repo.transaction(),repo._session() as session:repo._grant_environment_accessories(session,user.id,1)
    receive(context,'entry','/我的工位')
    spent=0
    for room in range(1,6):
        for number in range(6,10):
            action={'kind':'upgrade','number':number}
            quote=repo.quote_workstation_action('user-1',action,NOW)
            assert quote['price']==upgrade_cost(room*2-1)
            repo.apply_workstation_action('user-1',action,uuid4(),quote['revision'],NOW)
            spent+=quote['price']
            assert repo.get_workstation(user.id)['progression']==quote['after']['progression']
        p=repo.get_workstation(user.id)['progression']
        assert p['daily_income']==environment_daily_income(room)+4*TOOL_INCOME[room*2-1]
        assert len(p['accessories'])==sum(a['environment']<=room for a in ACCESSORIES)
        assert p['accessory_scene']['environment']==room
        if room<5:
            quote=repo.quote_workstation_action('user-1',{'kind':'advance'},NOW)
            repo.apply_workstation_action('user-1',{'kind':'advance'},uuid4(),quote['revision'],NOW)
            spent+=quote['price']
    assert spent==18950 and repo.find_user('user-1').balance==21050
    assert p['daily_income']==180 and len(p['accessories'])==25
