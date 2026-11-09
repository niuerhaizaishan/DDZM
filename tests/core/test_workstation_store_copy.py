import pytest
from tests.core.test_equipment import context, receive


@pytest.mark.parametrize('command',['/工位商店','/装备商店','/装备商城','/装备商城 全部'])
def test_retired_store_has_no_reply_and_does_not_change_balance(context,command):
    _,repo,_=context
    before=repo.find_user('user-1').balance
    assert receive(context,'retired',command)==''
    assert repo.find_user('user-1').balance==before
    help_text=receive(context,'help','/帮助 工位')
    assert '/工位背包' in help_text and '/升级 电脑' in help_text
