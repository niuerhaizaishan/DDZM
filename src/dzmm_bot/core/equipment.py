from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .workstation_progression import WorkstationProgressionMixin
from .workstation_actions import WorkstationActionsMixin
from .workstation_income import WorkstationIncomeMixin
from .workstation_admin import WorkstationAdminMixin

from .schema import (
    EquipmentItemRecord,
    EquipmentOwnershipRecord,
    EquipmentPurchaseRecord,
    GroupChatRecord,
    InboundRecord,
    UserRecord,
    WorkstationComponentRecord,
    WorkstationAccessoryRecord,
)
from .workstation_catalog import component_daily_income


EQUIPMENT_COMMAND_DEFINITIONS = (
    ("/工位背包", "/工位背包", "查看已拥有的环境和设备"),
    ("/升级工位", "/升级工位", "本环境四件设备全部升至升级款后，付费迁入下一环境，配齐基础布置和基础款设备"),
    ("/精修工位", "/精修工位", "兼容旧指令：基础布置随环境，不单独精修"),
    ("/切换工位", "/切换工位 环境编号", "免费切换已拥有环境"),
    ("/工位收益表", "/工位收益表", "查看环境和设备各等级的日收益与升级费用"),
    ("/购买装备", "/购买装备 装备编号", "配件不再单独购买；设备提升请用 /升级装备，环境更换请用 /升级工位"),
    ("/升级装备", "/升级 设备名称", "2至5号设备在当前环境内从基础档升到升级档，不能跨环境升级"),
    ("/装备", "/装备 设备名称 等级；/装备 环境 编号", "设备需填当前环境已拥有的等级；自动获得的配件只填编号；基础布置随环境配套"),
    ("/卸下", "/卸下 装备编号", "卸下设备或自动获得的配件，保留所有权；基础布置不能单独卸下"),
    ("/我的工位", "/我的工位", "查看当前环境、设备与预计日收益"),
    ("/工位游戏", "/工位游戏", "直接发送工位小游戏入口"),
)
EQUIPMENT_COMMANDS = frozenset(item[0] for item in EQUIPMENT_COMMAND_DEFINITIONS)
DEFAULT_EQUIPMENT = (
    (1, "monitor-main", "主显示器", 36, 2),
    (2, "monitor-left", "左侧竖屏", 28, 1),
    (3, "monitor-right", "右侧竖屏", 28, 1),
    (4, "screen-light", "屏幕挂灯", 18, 1),
    (5, "keyboard", "机械键盘", 22, 1),
    (6, "mouse", "桌面鼠标", 16, 1),
    (7, "desk-lamp", "暖光台灯", 24, 1),
    (8, "handheld", "桌面掌机", 20, 1),
    (9, "pc", "侧透主机", 58, 3),
    (10, "chair", "人体工学椅", 46, 2),
)


@dataclass(frozen=True)
class EquipmentView:
    number: int
    asset_key: str
    name: str
    price: int
    daily_income: int
    enabled: bool
    owned: bool
    equipped: bool


@dataclass(frozen=True)
class EquipmentActionResult:
    status: str
    name: str = ""
    price: int = 0
    balance: int | None = None


class EquipmentMixin(WorkstationAdminMixin, WorkstationIncomeMixin, WorkstationActionsMixin, WorkstationProgressionMixin):
    def list_workstations(self, query="", page=1, page_size=24):
        from .repository import format_employee_number

        query = query.strip()
        if not 1 <= page <= 1000000 or not 1 <= page_size <= 48 or len(query) > 64:
            raise ValueError("invalid workstation directory query")
        filters = []
        if query:
            number = query.removeprefix("#")
            matches = [UserRecord.display_name.icontains(query, autoescape=True)]
            if number.isascii() and number.isdecimal() and len(number) <= 9:
                matches.append(UserRecord.employee_number == int(number))
            filters.append(or_(*matches))
        with self._session() as session:
            total = session.scalar(select(func.count()).select_from(UserRecord).where(*filters))
            users = session.scalars(select(UserRecord).where(*filters)
                                    .order_by(UserRecord.employee_number).offset((page - 1) * page_size)
                                    .limit(page_size)).all()
            rules = self.workstation_rules(session)
            equipment = {user.id: [] for user in users}
            totals = {user.id: [9, sum(component_daily_income(n, 1, rules=rules) for n in range(1, 10))] for user in users}
            if users:
                for component in session.scalars(select(WorkstationComponentRecord).where(
                    WorkstationComponentRecord.user_id.in_(totals)
                )):
                    if not component.equipped:
                        totals[component.user_id][0] -= 1
                    totals[component.user_id][1] += (component_daily_income(component.category_number, component.active_level, component.equipped, rules=rules)
                        - component_daily_income(component.category_number, 1, rules=rules))
                rows = session.execute(select(EquipmentOwnershipRecord.user_id, EquipmentItemRecord)
                                       .join(EquipmentItemRecord, EquipmentItemRecord.id == EquipmentOwnershipRecord.item_id)
                                       .where(EquipmentOwnershipRecord.user_id.in_(equipment),
                                              EquipmentOwnershipRecord.equipped.is_(True))
                                       .order_by(EquipmentItemRecord.public_number))
                for user_id, item in rows:
                    equipment[user_id].append(item)
                for user_id, count in session.execute(
                    select(WorkstationAccessoryRecord.user_id, func.count())
                    .where(WorkstationAccessoryRecord.user_id.in_(totals),
                           WorkstationAccessoryRecord.equipped.is_(True))
                    .group_by(WorkstationAccessoryRecord.user_id)
                ):
                    totals[user_id][0] += count
            return {
                "items": [{"number": user.employee_number,
                           "employee_number": format_employee_number(user.employee_number),
                           "display_name": user.display_name,
                           "asset_keys": [item.asset_key for item in equipment[user.id]],
                           "equipped_count": totals[user.id][0],
                           "daily_income": totals[user.id][1]}
                          for user in users],
                "total": total, "page": page, "page_size": page_size,
            }

    def get_workstation_by_number(self, employee_number):
        with self._session() as session:
            user_id = session.scalar(select(UserRecord.id).where(UserRecord.employee_number == employee_number))
        return self.get_workstation(user_id) if user_id is not None else None

    def get_workstation(self, user_id):
        from .repository import format_employee_number

        with self._session() as session:
            user = session.get(UserRecord, user_id)
            if user is None:
                return None
            items = session.scalars(
                select(EquipmentItemRecord)
                .join(EquipmentOwnershipRecord, EquipmentOwnershipRecord.item_id == EquipmentItemRecord.id)
                .where(EquipmentOwnershipRecord.user_id == user.id, EquipmentOwnershipRecord.equipped.is_(True))
                .order_by(EquipmentItemRecord.public_number)
            ).all()
            progression = self._workstation_progression(session, user)
            return {
                "display_name": user.display_name,
                "employee_number": format_employee_number(user.employee_number),
                "equipped": [
                    {"number": item.public_number, "asset_key": item.asset_key,
                     "name": item.name, "daily_income": item.daily_income}
                    for item in items
                ],
                "daily_income": progression["daily_income"],
                "income_settlement_enabled": self.workstation_income_enabled(),
                "progression": progression,
            }

    def _ensure_equipment_catalog(self, session):
        dialect = session.get_bind().dialect.name
        if dialect not in {"postgresql", "sqlite"}:
            raise ValueError(f"unsupported database dialect: {dialect}")
        insert = postgresql_insert if dialect == "postgresql" else sqlite_insert
        existing = set(session.scalars(select(EquipmentItemRecord.asset_key)))
        for number, asset_key, name, price, daily_income in DEFAULT_EQUIPMENT:
            if asset_key in existing:
                continue
            session.execute(
                insert(EquipmentItemRecord).values(
                    id=uuid4(), public_number=number, asset_key=asset_key,
                    name=name, price=price, daily_income=daily_income, enabled=True,
                ).on_conflict_do_nothing()
            )

    def list_equipment(self, platform_id):
        with self.transaction():
            with self._session() as session:
                self._ensure_equipment_catalog(session)
                user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id))
                holdings = {} if user is None else {
                    row.item_id: row for row in session.scalars(
                        select(EquipmentOwnershipRecord).where(EquipmentOwnershipRecord.user_id == user.id)
                    )
                }
                return [
                    EquipmentView(
                        number=item.public_number, asset_key=item.asset_key,
                        name=item.name, price=item.price, daily_income=item.daily_income,
                        enabled=item.enabled, owned=item.id in holdings,
                        equipped=item.id in holdings and holdings[item.id].equipped,
                    )
                    for item in session.scalars(
                        select(EquipmentItemRecord).order_by(EquipmentItemRecord.public_number)
                    ) if item.enabled or item.id in holdings
                ]

    def purchase_equipment(self, message_id, platform_id, number, group_chat_id, now):
        with self.transaction():
            with self._session() as session:
                group = session.get(GroupChatRecord, group_chat_id)
                if group is None or group.deleted_at is not None or not group.listening_enabled:
                    return EquipmentActionResult("wrong_group")
                user = session.scalar(
                    select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update()
                )
                if user is None:
                    return EquipmentActionResult("not_joined")
                inbound = session.scalar(select(InboundRecord).where(
                    InboundRecord.platform_message_id == message_id,
                    InboundRecord.sender_platform_id == platform_id,
                    InboundRecord.group_chat_id == group_chat_id,
                    InboundRecord.source_type == "group",
                ))
                if inbound is None:
                    raise ValueError("装备购买入站消息不存在")
                existing = session.scalar(select(EquipmentPurchaseRecord).where(
                    EquipmentPurchaseRecord.inbound_message_id == inbound.id
                ))
                if existing is not None:
                    if existing.result["number"] != number:
                        return EquipmentActionResult("request_conflict")
                    return EquipmentActionResult(**{
                        key: value for key, value in existing.result.items() if key != "number"
                    })
                self._ensure_equipment_catalog(session)
                item = session.scalar(select(EquipmentItemRecord).where(
                    EquipmentItemRecord.public_number == number
                ).with_for_update())
                if item is None:
                    return EquipmentActionResult("not_found")
                holding = session.scalar(select(EquipmentOwnershipRecord).where(
                    EquipmentOwnershipRecord.user_id == user.id,
                    EquipmentOwnershipRecord.item_id == item.id,
                ))
                if holding is not None:
                    return EquipmentActionResult("already_owned", item.name, balance=user.balance)
                if not item.enabled:
                    return EquipmentActionResult("disabled", item.name)
                if user.balance < item.price:
                    return EquipmentActionResult("insufficient_balance", item.name, item.price, user.balance)
                self._apply_balance_change(
                    user, -item.price, "equipment_purchase", now,
                    memo=f"装备 #{item.public_number} {item.name}",
                )
                session.add(EquipmentOwnershipRecord(
                    user_id=user.id, item_id=item.id, equipped=False, purchased_at=now,
                ))
                result = dict(status="purchased", name=item.name, price=item.price, balance=user.balance)
                session.add(EquipmentPurchaseRecord(
                    inbound_message_id=inbound.id, user_id=user.id, item_id=item.id,
                    group_chat_id=group_chat_id, price=item.price,
                    result={"number": number, **result}, created_at=now,
                ))
                session.flush()
                return EquipmentActionResult(**result)

    def set_equipment_equipped(self, platform_id, number, equipped):
        with self.transaction():
            with self._session() as session:
                user = session.scalar(
                    select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update()
                )
                if user is None:
                    return EquipmentActionResult("not_joined")
                item = session.scalar(select(EquipmentItemRecord).where(
                    EquipmentItemRecord.public_number == number
                ))
                if item is None:
                    return EquipmentActionResult("not_found")
                holding = session.scalar(select(EquipmentOwnershipRecord).where(
                    EquipmentOwnershipRecord.user_id == user.id,
                    EquipmentOwnershipRecord.item_id == item.id,
                ))
                if holding is None:
                    return EquipmentActionResult("not_owned", item.name)
                if holding.equipped == equipped:
                    return EquipmentActionResult("already_equipped" if equipped else "already_removed", item.name)
                holding.equipped = equipped
                return EquipmentActionResult("equipped" if equipped else "removed", item.name)
