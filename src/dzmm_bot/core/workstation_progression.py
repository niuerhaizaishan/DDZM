from sqlalchemy import select

from .schema import (
    GroupChatRecord, InboundRecord, RankRecord, UserRecord,
    WorkstationComponentRecord, WorkstationUpgradeRecord,
    WorkstationAccessoryRecord, WorkstationAccessoryPurchaseRecord,
    WorkstationActionRecord,
)
from .workstation_catalog import ART_NOTICE, CATEGORIES, component_daily_income, upgrade_cost, component_name, environment_name
from .workstation_art import component_scene
from .workstation_stage5 import accessory_scene
from .workstation_accessories import ACCESSORIES, BY_NUMBER
from .workstation_growth import growth_state, growth_offers, current_environment


class WorkstationProgressionMixin:
    @staticmethod
    def _grant_environment_accessories(session, user_id, environment):
        """Grant all accessories through a reached environment without charging."""
        owned = {row.accessory_number for row in session.scalars(select(WorkstationAccessoryRecord).where(
            WorkstationAccessoryRecord.user_id == user_id
        ))}
        granted = []
        for item in ACCESSORIES:
            if item['environment'] <= environment and item['number'] not in owned:
                session.add(WorkstationAccessoryRecord(user_id=user_id, accessory_number=item['number'], equipped=True))
                granted.append(item['number'])
        if granted:
            session.flush()
        return granted

    def _component_views(self, session, user_id):
        rules = self.workstation_rules(session)
        holdings = {r.category_number: r for r in session.scalars(select(WorkstationComponentRecord).where(
            WorkstationComponentRecord.user_id == user_id
        ))}
        result = []
        for category in CATEGORIES:
            row = holdings.get(category["number"])
            highest = row.highest_level if row else 1
            active = row.active_level if row else 1
            equipped = row.equipped if row else True
            result.append({
                "number": category["number"], "key": category["key"], "category": category["name"],
                "highest_level": highest, "active_level": active, "equipped": equipped,
                "name": component_name(category, active, rules=rules), "description": category["descriptions"][active - 1],
                "daily_income": component_daily_income(category["number"], active, equipped, rules=rules),
            })
        return result

    def _workstation_progression(self, session, user):
        components = self._component_views(session, user.id)
        accessories = self._accessory_views(session, user.id)
        result = {"components": components, "daily_income": sum(c["daily_income"] for c in components),
                "equipped_count": sum(c["equipped"] for c in components) + sum(a["equipped"] for a in accessories), "art_notice": ART_NOTICE,
                "scene": component_scene(components)}
        result['accessories'] = accessories
        expanded = accessory_scene(components, accessories)
        if expanded is not None:
            result["accessory_scene"] = expanded
        result['growth'] = growth_state(components, accessories, expanded)
        if expanded: result['environment_name'] = environment_name(expanded['environment'], rules=self.workstation_rules(session))
        return result

    def get_workstation_shop(self, platform_id):
        with self._session() as session:
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id))
            if user is None:
                return None
            rank = session.get(RankRecord, user.rank_id) if user.rank_id else None
            cap = 10 if rank and rank.is_board else min(10, max(1, rank.sort_order if rank else 1))
            rules = self.workstation_rules(session)
            components = self._component_views(session, user.id)
            active_environment = current_environment(components)
            # Purchase progression is independent of the room currently on display.
            environment = min((c['highest_level'] + 1) // 2 for c in components if c['number'] <= 5)
            base, ceiling = environment * 2 - 1, environment * 2
            rows = []
            for current, category in zip(components, CATEGORIES):
                level = current["highest_level"]
                bundled = category['group'] == 'environment'
                next_level = level + 1 if not bundled and base <= level < ceiling else None
                price = upgrade_cost(level, rules=rules) if next_level else None
                cash = price if price is not None else 0
                state = ('environment_bundle' if bundled else 'environment_max' if level >= ceiling
                         else 'legacy_mixed' if level < base else "rank_locked" if level >= cap
                         else "insufficient_balance" if user.balance < cash else "available")
                required = session.scalar(select(RankRecord).where(RankRecord.sort_order == level + 1)) if state == "rank_locked" else None
                rows.append({**current, "status": state, "next_level": next_level,
                             'bundled': bundled, 'environment': environment, 'equipped_environment': active_environment,
                             'selectable_levels': [] if bundled else [n for n in (active_environment * 2 - 1, active_environment * 2) if n <= level],
                             "next_name": component_name(category, level + 1, rules=rules) if next_level else None,
                             "next_description": category["descriptions"][level] if next_level else None,
                             "price": price, "credit_used": 0,
                             "cash_required": cash, "shortage": max(0, cash - user.balance),
                             "required_rank": required.name if required else f"职级 Lv{level + 1}",
                             "next_daily_income": component_daily_income(category["number"], level + 1, rules=rules) if next_level else None,
                             "income_delta": component_daily_income(category["number"], level + 1, rules=rules) - current["daily_income"] if next_level else 0,
                             "upgrade_command": f"/升级装备 {category['number']}" if state == "available" else None})
            rows.sort(key=lambda r: ({"available": 0, "insufficient_balance": 1, "rank_locked": 2,
                'environment_max': 3, 'environment_bundle': 4, 'legacy_mixed': 5}[r["status"]], r["number"]))
            owned = {item['number']:item for item in self._accessory_views(session,user.id)}
            accessory_rows = []
            for item in ACCESSORIES:
                holding = owned.get(item['number'])
                state = 'owned' if holding else 'auto_grant' if item['environment'] <= environment else 'locked'
                accessory_rows.append({**item,'owned':holding is not None,'equipped':bool(holding and holding['equipped']),
                    'status':state,'price':None,'shortage':0,
                    'unlock_description': f"升级到环境{item['environment']}后自动获得",
                    'purchase_command':None})
            # Keep zero-valued credit fields compatible with previously published clients.
            return {"rules_revision": rules["revision"], "rank_name": rank.name if rank else "未分配职级", "level_cap": cap, "balance": user.balance, "upgrade_credit": 0,
                    "currency_name": self.get_game_settings().currency_name, "items": rows,
                    "daily_income": sum(c["daily_income"] for c in components),
                    "income_settlement_enabled": self.workstation_income_enabled(), "art_notice": ART_NOTICE, 'accessories':accessory_rows,
                    'growth': growth_state(components, list(owned.values()), accessory_scene(components, list(owned.values()))),
                    'growth_offers': growth_offers(components, cap, user.balance, rules=rules)}

    @staticmethod
    def _accessory_views(session,user_id):
        return [{**BY_NUMBER[row.accessory_number],'equipped':row.equipped} for row in session.scalars(
            select(WorkstationAccessoryRecord).where(WorkstationAccessoryRecord.user_id==user_id)
            .order_by(WorkstationAccessoryRecord.accessory_number)) if row.accessory_number in BY_NUMBER]

    def purchase_workstation_accessory(self,message_id,platform_id,number,group_chat_id,now):
        item = BY_NUMBER.get(number)
        if item is None:
            return {'status': 'not_found'}
        return {'status': 'purchase_disabled', 'number': number, 'name': item['name'],
                'message': '配件随环境升级自动获得，无需单独购买。'}

    def _purchase_accessory(self, session, user, item, now):
        self._apply_balance_change(user, -item['price'], 'equipment_purchase', now,
            memo=f"工位配件 #{item['number']} {item['name']}")
        session.add(WorkstationAccessoryRecord(user_id=user.id, accessory_number=item['number'], equipped=True))
        session.flush()
        return {'status': 'purchased', 'number': item['number'], 'name': item['name'],
                'price': item['price'], 'balance': user.balance}

    def _upgrade_component(self, session, user, item, now):
        number, level = item['number'], item['highest_level']
        prior_scene = accessory_scene(self._component_views(session, user.id))
        row = session.get(WorkstationComponentRecord, (user.id, number))
        if row is None:
            row = WorkstationComponentRecord(user_id=user.id, category_number=number)
            session.add(row)
        self._apply_balance_change(user, -item['cash_required'], 'workstation_upgrade', now,
            memo=f"工位 #{number} Lv{level}→Lv{level + 1}")
        row.highest_level = row.active_level = level + 1
        row.equipped = True
        session.flush()
        # Upgrading while viewing an older room returns to the owned room for
        # this level. Otherwise a single upgraded slot breaks the native scene.
        room = (level + 2) // 2
        components = self._component_views(session, user.id)
        if prior_scene and prior_scene['environment'] != room and all(c['highest_level'] >= room * 2 - 1 for c in components):
            for c in components:
                holding = session.get(WorkstationComponentRecord, (user.id, c['number']))
                if holding is not None:
                    holding.active_level = min(c['highest_level'], room * 2)
            session.flush()
        return {'status': 'upgraded', 'number': number, 'name': item['next_name'],
                'level': level + 1, 'price': item['price'], 'cash_paid': item['cash_required'],
                'credit_used': 0, 'balance': user.balance, 'daily_income': item['next_daily_income']}

    def set_workstation_accessory(self,platform_id,number,*,equipped=True):
        with self.transaction(), self._session() as session:
            user=session.scalar(select(UserRecord).where(UserRecord.platform_id==platform_id).with_for_update())
            if user is None:return {'status':'not_joined'}
            item=BY_NUMBER.get(number)
            if item is None:return {'status':'not_found'}
            row=session.get(WorkstationAccessoryRecord,(user.id,number))
            if row is None:return {'status':'accessory_not_owned'}
            row.equipped=equipped
            return {'status':'equipped' if equipped else 'removed','name':item['name'],
                    'daily_income':sum(c['daily_income'] for c in self._component_views(session,user.id))}

    def upgrade_workstation_component(self, message_id, platform_id, number, expected_level, group_chat_id, now):
        with self.transaction(), self._session() as session:
            self.lock_workstation_rules(session)
            group = session.get(GroupChatRecord, group_chat_id) if group_chat_id else None
            if group is None or group.deleted_at is not None or not group.listening_enabled:
                return {"status": "wrong_group"}
            # All balance and slot mutations take the same user lock across groups.
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update())
            if user is None:
                return {"status": "not_joined"}
            inbound = session.scalar(select(InboundRecord).where(
                InboundRecord.platform_message_id == message_id, InboundRecord.sender_platform_id == platform_id,
                InboundRecord.group_chat_id == group_chat_id, InboundRecord.source_type == "group",
            ))
            if inbound is None:
                raise ValueError("装备升级入站消息不存在")
            if session.scalar(select(WorkstationActionRecord.request_id).where(WorkstationActionRecord.inbound_message_id == inbound.id)):
                return {'status': 'request_conflict'}
            if session.scalar(select(WorkstationAccessoryPurchaseRecord.id).where(
                    WorkstationAccessoryPurchaseRecord.inbound_message_id==inbound.id)):
                return {'status':'request_conflict'}
            receipt = session.scalar(select(WorkstationUpgradeRecord).where(WorkstationUpgradeRecord.inbound_message_id == inbound.id))
            if receipt:
                matches = receipt.category_number == number and (expected_level is None or receipt.from_level == expected_level)
                return dict(receipt.result) if matches else {"status": "request_conflict"}
            shop = self.get_workstation_shop(platform_id)
            item = next((r for r in shop["items"] if r["number"] == number), None)
            if item is None:
                return {"status": "not_found"}
            if expected_level is not None and item["highest_level"] != expected_level:
                return {"status": "stale_level", "level": item["highest_level"]}
            # Resolve the next level under the user lock, after receipt replay detection.
            expected_level = item["highest_level"]
            if item["status"] != "available":
                return item
            result = self._upgrade_component(session, user, item, now)
            session.add(WorkstationUpgradeRecord(
                inbound_message_id=inbound.id, user_id=user.id, group_chat_id=group_chat_id,
                category_number=number, from_level=expected_level, to_level=expected_level + 1,
                price=item["price"], credit_used=item["credit_used"], cash_paid=item["cash_required"],
                result=result, created_at=now,
            ))
            session.flush()
            return result

    def set_workstation_component(self, platform_id, number, level=None, *, equipped=True):
        with self.transaction(), self._session() as session:
            self.lock_workstation_rules(session)
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update())
            if user is None:
                return {"status": "not_joined"}
            if not 1 <= number <= 9:
                return {"status": "not_found"}
            if number <= 5:
                return {'status': 'environment_bundle'}
            room = current_environment(self._component_views(session, user.id))
            if equipped and level is not None and level not in (room * 2 - 1, room * 2):
                return {'status': 'environment_locked'}
            row = session.get(WorkstationComponentRecord, (user.id, number))
            highest = row.highest_level if row else 1
            if level is not None and not 1 <= level <= highest:
                return {"status": "not_owned", "level": highest}
            if row is None:
                row = WorkstationComponentRecord(user_id=user.id, category_number=number, highest_level=1, active_level=1)
                session.add(row)
            if level is not None:
                row.active_level = level
            row.equipped = equipped
            session.flush()
            return {"status": "equipped" if equipped else "removed", "name": CATEGORIES[number - 1]["name"],
                    "daily_income": self._workstation_progression(session, user)["daily_income"]}

    def _activate_environment(self, session, user_id, environment):
        for c in self._component_views(session, user_id):
            row = session.get(WorkstationComponentRecord, (user_id, c['number']))
            if row is None:
                row = WorkstationComponentRecord(user_id=user_id, category_number=c['number'], highest_level=1)
                session.add(row)
            row.active_level = min(c['highest_level'], environment * 2)
            row.equipped = True
        session.flush()
