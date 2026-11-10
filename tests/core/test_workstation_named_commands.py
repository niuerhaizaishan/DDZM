import pytest
from .test_equipment import context, receive, rank, NOW
from dzmm_bot.core.workstation_labels import parse_device_level


@pytest.mark.parametrize('command', ['/工位帮助', '/工位商店', '/装备商店', '/装备商城', '/我的装备'])
def test_retired_commands_do_not_reply(context, command):
    assert receive(context, command, command) == ''


def test_named_upgrade_equip_backpack_and_help(context):
    _, repo, _ = context
    rank(context, 10)
    user = repo.find_user('user-1')
    repo.record_balance_change(user.id, 40000 - user.balance, 'board_bonus', NOW)
    first = receive(context, 'mouse', '/升级 鼠标')
    assert '基础鼠标 1-2' in first
    balance = repo.find_user('user-1').balance
    assert receive(context, 'mouse', '/升级 鼠标') == first
    assert repo.find_user('user-1').balance == balance
    assert '1-2' in receive(context, 'bag', '/工位背包')
    assert '已装备' in receive(context, 'equip', '/装备 鼠标 1-1')
    assert '已装备' in receive(context, 'equip-int', '/装备 鼠标 2')
    assert '当前环境' in receive(context, 'cross', '/装备 鼠标 3')
    assert '未完成' in receive(context, 'blocked', '/升级 环境')
    for name in ('电脑', '显示器', '键盘'):
        assert '升级成功' in receive(context, name, '/升级 ' + name)
    assert '完成' in receive(context, 'advance', '/升级 环境')
    assert '已装备' in receive(context, 'equip-3', '/装备 鼠标 3')
    text = receive(context, 'overview', '/我的工位')
    assert '环境：2级 普通办公环境【日收益：2】' in text
    assert '鼠标：2-1 标准鼠标【日收益：5】' in text
    assert '配件' not in receive(context, 'bag2', '/工位背包')
    assert '完成' in receive(context, 'switch', '/装备 环境 1')
    assert '完成' in receive(context, 'switch-alias', '/切换工位环境 2')
    help_text = receive(context, 'help', '/帮助 工位')
    assert '/升级 电脑' in help_text and '/工位背包' in help_text
    assert all(c not in help_text for c in ('/工位帮助', '/装备商城', '/我的装备'))


@pytest.mark.parametrize('value', ['0', '11', '2-3', '0-1', '６', '-1', '2-1-1'])
def test_bad_device_level_is_rejected_without_mutation(context, value):
    assert parse_device_level(value) is None
    before = context[1].find_user('user-1').balance
    assert '用法' in receive(context, 'invalid', '/装备 鼠标 ' + value)
    assert context[1].find_user('user-1').balance == before


def test_named_commands_preserve_rank_ownership_and_switches(context):
    _, repo, _ = context
    before = repo.find_user('user-1').balance
    assert '职级不足' in receive(context, 'rank', '/升级 鼠标')
    assert '尚未解锁' in receive(context, 'unowned', '/装备 鼠标 1-2')
    assert '请先晋升' in receive(context, 'rank-env', '/升级 环境')
    assert repo.find_user('user-1').balance == before
    repo.set_command_enabled('/升级装备', False)
    assert receive(context, 'off', '/升级 鼠标') == ''
    repo.set_command_enabled('/装备', False)
    assert receive(context, 'equip-off', '/装备 环境 1') == ''


def test_game_popup_matches_group_workstation_help(context):
    from pathlib import Path
    from html import unescape
    import re
    root = Path(__file__).resolve().parents[2]
    reply = receive(context, 'shared-help', '/帮助 工位')
    for file in ('gamefy-workstation/publish/index.html', 'src/dzmm_bot/admin/templates/workstation.html'):
        text = (root / file).read_text(encoding='utf-8')
        popup = re.search(r'<pre id="help-text">(.*?)</pre>', text, re.S)
        assert popup and unescape(popup[1]) == reply
