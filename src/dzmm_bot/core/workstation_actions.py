"""Shared account actions. Web requests never create synthetic group messages."""
from .workstation_labels import level_label
import copy
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from .schema import (GroupChatRecord, InboundRecord, UserRecord, WorkstationActionRecord,
                     WorkstationUpgradeRecord, WorkstationAccessoryPurchaseRecord)
from .workstation_accessories import ACCESSORIES, BY_NUMBER
from .workstation_growth import batch_growth_plan, growth_state, current_environment
from .workstation_art import component_scene
from .workstation_catalog import CATEGORIES, component_daily_income, upgrade_cost, component_name, environment_name
from .workstation_share import available_share_groups
from .workstation_stage5 import accessory_scene


class WorkstationActionError(ValueError):
    def __init__(self, message, code=409):
        super().__init__(message)
        self.code = code


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


ACTION_COMMANDS = {
    "upgrade": "/升级装备", "purchase": "/购买装备", "equip": "/装备", "remove": "/卸下",
    "advance": "/升级工位", "polish": "/精修工位", "view": "/切换工位",
}


class WorkstationActionsMixin:
    def _action_permission(self, platform_id, action, now, *, web):
        if action['kind'] == 'polish':
            raise WorkstationActionError('五项基础布置已随环境整体升级，不再单独精修；请使用 /升级工位。')
        command = ACTION_COMMANDS.get(action['kind'])
        if not command or not self.is_command_enabled(command):
            raise WorkstationActionError("管理员暂未开放这项工位操作。", 403)
        if action['kind'] in {'advance', 'polish'} and not self.is_command_enabled('/升级装备'):
            raise WorkstationActionError("管理员暂未开放装备升级。", 403)
        if action['kind'] == 'view' and not self.is_command_enabled('/装备'):
            raise WorkstationActionError("管理员暂未开放装备切换。", 403)
        if web and (not self.is_command_enabled('/我的工位') or not available_share_groups(self, platform_id, now)):
            raise WorkstationActionError("请先在已启用的群里发送 /我的工位，再刷新游戏；操作入口24小时内有效。", 403)

    def workstation_management(self, platform_id, now):
        self.ensure_command_definitions()
        shop = self.get_workstation_shop(platform_id)
        allowed = {}
        for kind in ACTION_COMMANDS:
            try:
                self._action_permission(platform_id, {'kind': kind}, now, web=True)
                allowed[kind] = True
            except WorkstationActionError:
                allowed[kind] = False
        allowed['advance'] = allowed['advance'] and shop['growth_offers']['advance']['status'] == 'available'
        return {**shop, 'revision': digest(shop), 'actions': allowed,
                'management_note': '网页和群聊共用账号余额与装备。请先在群里发送 /我的工位 开通24小时操作入口。'}

    def _action_plan(self, session, user, action):
        rules = self.workstation_rules(session)
        shop = self.get_workstation_shop(user.platform_id)
        components = {item['number']: item for item in shop['items']}
        kind, number, level = action['kind'], action.get('number'), action.get('level')
        targets, cost, item = {}, 0, None
        stage = min((c['highest_level'] + 1) // 2 for n, c in components.items() if n <= 5)
        title = ''
        if kind == 'upgrade':
            item = components.get(number)
            if item is None:
                raise WorkstationActionError('部件编号不存在。')
            if item['status'] == 'environment_bundle':
                raise WorkstationActionError('位置、地板、桌子、椅子、绿植随环境整体升级，请使用 /升级工位。')
            if item['status'] == 'environment_max':
                raise WorkstationActionError('已拥有当前环境的升级档；请使用 /升级工位 迁入下一环境，再提升设备。')
            if item['status'] == 'legacy_mixed':
                raise WorkstationActionError('旧搭配的装备尚未补齐，请使用 /升级工位 整套迁入下一环境。')
            targets[number] = item['highest_level'] + 1
            title = f"升级{item['category']}至 {level_label(targets[number])}"
        elif kind in {'advance', 'polish'}:
            batch = batch_growth_plan(list(components.values()), kind, rules=rules)
            if batch['status'] == 'max':
                raise WorkstationActionError('已到最高环境5；四件设备仍可在本环境升至升级档，配件已随环境自动获得。')
            if batch['status'] == 'devices_required':
                rank_note = (f"当前职级最高可升级至{level_label(shop['level_cap'])}，请先晋升。"
                             if shop['level_cap'] < stage * 2 else '')
                raise WorkstationActionError(f"需先将环境{stage}的四件设备升至升级款；未完成：{'、'.join(batch['missing_devices'])}。" + rank_note)
            targets = batch['targets']
            if not targets:
                raise WorkstationActionError('当前环境已配齐，无需重复升级。')
            title = f'升级至环境{stage + 1}' if kind == 'advance' else f'精修环境{stage}'
        elif kind == 'purchase':
            raise WorkstationActionError('配件随环境升级自动获得，无需购买；请使用 /升级工位。')
        elif kind in {'equip', 'remove'}:
            if number in components:
                item = components[number]
                if number <= 5:
                    raise WorkstationActionError('五项基础布置随环境整体更换，不支持单独装卸或切换等级。')
                if kind == 'equip':
                    room = current_environment(list(components.values()))
                    if level not in (room * 2 - 1, room * 2):
                        raise WorkstationActionError('只能选择当前环境的基础档或升级档；切换环境请使用 /切换工位。')
                    if level is None or not 1 <= level <= item['highest_level']:
                        raise WorkstationActionError(f"该等级尚未拥有，当前最高 {level_label(item['highest_level'])}。")
            else:
                item = next((a for a in shop['accessories'] if a['number'] == number and a['owned']), None)
                if item is None:
                    raise WorkstationActionError('该配件尚未随环境升级获得。')
            title = ('装备' if kind == 'equip' else '卸下') + item.get('category', item['name'])
            if number in BY_NUMBER and kind == 'equip' and item['environment'] != shop['growth']['active_environment']:
                title += f"，切换至环境{item['environment']}后显示"
        elif kind == 'view':
            if level is None or not 1 <= level <= stage:
                raise WorkstationActionError(f'环境尚未解锁，当前最高环境{stage}。')
            baseline = level * 2 - 1
            if any(c['highest_level'] < baseline for c in components.values()):
                raise WorkstationActionError('该环境尚未整套配齐，请使用 /升级工位 解锁完整环境。')
            title = f'切换至环境{level}（免费，保留已购装备）'
        else:
            raise WorkstationActionError('操作类型不存在。')
        for n, target in targets.items():
            if target > shop['level_cap']:
                raise WorkstationActionError(f"职级不足，当前升级上限 {level_label(shop['level_cap'])}。")
            cost += upgrade_cost(components[n]['highest_level'], target, rules=rules)
        if cost > user.balance:
            raise WorkstationActionError(f"余额不足，还差 {cost - user.balance} {shop['currency_name']}。")
        return {'title': title, 'price': cost, 'targets': targets, 'revision': digest(shop),
                'balance_after': user.balance - cost, 'currency_name': shop['currency_name'],
                'environment': stage + 1 if kind == 'advance' else stage}

    def _project_action(self, workstation, action, plan):
        rules = self.workstation_rules()
        after = copy.deepcopy(workstation)
        progression = after['progression']
        components = progression['components']
        prior_scene = accessory_scene(components, progression['accessories'])
        for c in components:
            number = c['number']
            if number in plan['targets']:
                c['highest_level'] = c['active_level'] = plan['targets'][number]
                c['equipped'] = True
            if action['kind'] == 'view':
                c['active_level'] = min(c['highest_level'], action['level'] * 2)
                c['equipped'] = True
            if action.get('number') == number and action['kind'] in {'equip', 'remove'}:
                c['equipped'] = action['kind'] == 'equip'
                if c['equipped']:
                    c['active_level'] = action['level']
            category = CATEGORIES[number - 1]
            c['name'] = component_name(category, c['active_level'], rules=rules)
            c['description'] = category['descriptions'][c['active_level'] - 1]

            c['daily_income'] = component_daily_income(c['number'], c['active_level'], c['equipped'], rules=rules)
        room = None
        if action['kind'] == 'advance':
            room = plan['environment']
        elif action['kind'] == 'polish':
            candidate = plan['environment']
            if prior_scene and prior_scene['environment'] != candidate and all(c['highest_level'] >= candidate * 2 - 1 for c in components):
                room = candidate
        elif action['kind'] == 'upgrade':
            candidate = (plan['targets'][action['number']] + 1) // 2
            if prior_scene and prior_scene['environment'] != candidate and all(c['highest_level'] >= candidate * 2 - 1 for c in components):
                room = candidate
        if room is not None:
            for c in components:
                c['active_level'] = min(c['highest_level'], room * 2)
                if action['kind'] == 'advance':
                    c['equipped'] = True
                category = CATEGORIES[c['number'] - 1]
                c['name'] = component_name(category, c['active_level'], rules=rules)
                c['description'] = category['descriptions'][c['active_level'] - 1]

                c['daily_income'] = component_daily_income(c['number'], c['active_level'], c['equipped'], rules=rules)
        accessories = progression['accessories']
        if action['kind'] == 'advance':
            room = plan['environment']
            owned = {a['number'] for a in accessories}
            accessories.extend({**item, 'equipped': True} for item in ACCESSORIES
                               if item['environment'] <= room and item['number'] not in owned)
        for a in accessories:
            if a['number'] == action.get('number') and action['kind'] in {'equip', 'remove'}:
                a['equipped'] = action['kind'] == 'equip'
        progression['daily_income'] = after['daily_income'] = sum(c['daily_income'] for c in components)
        progression['equipped_count'] = sum(c['equipped'] for c in components) + sum(a['equipped'] for a in accessories)
        progression['scene'] = component_scene(components)
        progression.pop('accessory_scene', None)
        expanded = accessory_scene(components, accessories)
        if expanded:
            progression['accessory_scene'] = expanded
            progression['environment_name'] = environment_name(expanded['environment'], rules=rules)
        progression['growth'] = growth_state(components, accessories, expanded)
        return after

    def quote_workstation_action(self, platform_id, action, now):
        self.ensure_command_definitions()
        with self.transaction(), self._session() as session:
            self.lock_workstation_rules(session)
            rules = self.workstation_rules(session)
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update())
            self._action_permission(platform_id, action, now, web=True)
            plan = self._action_plan(session, user, action)
            before = self.get_workstation(user.id)
            return {**plan, 'before': before, 'after': self._project_action(before, action, plan)}

    def apply_workstation_action(self, platform_id, action, request_id, revision, now, *, inbound=None):
        self.ensure_command_definitions()
        with self.transaction(), self._session() as session:
            self.lock_workstation_rules(session)
            rules = self.workstation_rules(session)
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update())
            self._action_permission(platform_id, action, now, web=inbound is None)
            inbound_id = None
            if inbound is not None:
                message_id, group_id = inbound
                group = session.get(GroupChatRecord, group_id, with_for_update=True)
                record = session.scalar(select(InboundRecord).where(
                    InboundRecord.platform_message_id == message_id, InboundRecord.sender_platform_id == platform_id,
                    InboundRecord.group_chat_id == group_id, InboundRecord.source_type == 'group'))
                if not record or not group or group.deleted_at or not group.listening_enabled:
                    raise WorkstationActionError('请在已启用的群聊中操作。', 403)
                request_id = uuid5(NAMESPACE_URL, f'ddzm:workstation-action:{record.id}')
                inbound_id = record.id
                if any(session.scalar(select(table.id).where(table.inbound_message_id == record.id))
                       for table in (WorkstationUpgradeRecord, WorkstationAccessoryPurchaseRecord)):
                    raise WorkstationActionError('这条消息已经用于其他购买或升级，请重新发送。')
            fingerprint = digest({'action': action, 'revision': revision})
            receipt = session.get(WorkstationActionRecord, (user.id, request_id))
            if receipt:
                if receipt.fingerprint != fingerprint:
                    raise WorkstationActionError('这次操作已用于其他请求，请刷新后重试。')
                return self._action_response_state(user, {**receipt.result, 'replayed': True}, now, inbound)
            plan = self._action_plan(session, user, action)
            if revision is not None and revision != plan['revision']:
                raise WorkstationActionError('余额或装备已变化，请刷新并重新确认；本次未扣币。')
            for number, target in plan['targets'].items():
                while True:
                    item = next(i for i in self.get_workstation_shop(platform_id)['items'] if i['number'] == number)
                    if item['highest_level'] >= target:
                        break
                    # The environment package owns these steps; individual
                    # shop restrictions must not zero its existing prices.
                    level = item['highest_level']
                    category = CATEGORIES[number - 1]

                    item = {**item, 'price': upgrade_cost(level, rules=rules),
                            'cash_required': upgrade_cost(level, rules=rules), 'credit_used': 0,
                            'next_name': component_name(category, level + 1, rules=rules), 'next_daily_income': component_daily_income(number, level + 1, rules=rules)}
                    self._upgrade_component(session, user, item, now)
            kind, number = action['kind'], action.get('number')
            if kind == 'purchase':
                raise WorkstationActionError('配件随环境升级自动获得，无需购买；请使用 /升级工位。')
            elif kind in {'equip', 'remove'}:
                if number <= 9:
                    self.set_workstation_component(platform_id, number, action.get('level'), equipped=kind == 'equip')
                else:
                    self.set_workstation_accessory(platform_id, number, equipped=kind == 'equip')
            elif kind == 'view':
                self._activate_environment(session, user.id, action['level'])
            elif kind == 'advance':
                self._activate_environment(session, user.id, plan['environment'])
                self._grant_environment_accessories(session, user.id, plan['environment'])
            result = {'status': 'applied', 'title': plan['title'], 'price': plan['price'],
                      'balance': user.balance, 'currency_name': plan['currency_name'], 'replayed': False}
            session.add(WorkstationActionRecord(user_id=user.id, request_id=request_id, fingerprint=fingerprint,
                                              inbound_message_id=inbound_id, result=result, created_at=now))
            session.flush()
            return self._action_response_state(user, result, now, inbound)

    def _action_response_state(self, user, result, now, inbound):
        # Keep receipts small and immutable. Retries return the current account
        # state while retaining the original payment receipt and request id.
        if inbound is not None:
            return result
        return {**result, 'workstation': self.get_workstation(user.id),
                'management': self.workstation_management(user.platform_id, now)}
