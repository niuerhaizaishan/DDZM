"""Shared versioned workstation rules and transactional administrative operations."""

import copy
from collections import defaultdict
from datetime import date
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .schema import (
    UserRecord,
    WorkstationRulesRecord,
    WorkstationAdminOperationRecord,
    WorkstationComponentRecord,
    WorkstationIncomeSettingsRecord,
    WorkstationIncomeRecord,
    BEIJING,
    beijing_now,
)
from .workstation_catalog import (
    CATEGORIES,
    UPGRADE_COSTS,
    TOOL_INCOME,
    component_daily_income,
    environment_upgrade_cost,
)
from .workstation_labels import ENVIRONMENT_NAMES
from .workstation_actions import WorkstationActionError, digest
from .workstation_art import component_scene
from .workstation_stage5 import accessory_scene
from .workstation_growth import growth_state


def default_rules():
    return {
        "upgrade_costs": list(UPGRADE_COSTS),
        "environment_upgrade_costs": [environment_upgrade_cost(n) for n in range(1, 5)],
        "environment_income": [0, 2, 5, 10, 20],
        "tool_income": list(TOOL_INCOME),
        "environment_names": list(ENVIRONMENT_NAMES),
        "device_names": {
            c["key"]: list(c["names"]) for c in CATEGORIES if c["number"] >= 6
        },
    }


def validate_rules(data):
    if not isinstance(data, dict) or set(data) != set(default_rules()):
        raise ValueError("规则字段不完整或包含未知字段")
    for key, length, minimum, maximum in [
        ("upgrade_costs", 9, 1, 1000000),
        ("environment_upgrade_costs", 4, 0, 20000000),
        ("environment_income", 5, 0, 1000000),
        ("tool_income", 10, 0, 1000000),
    ]:
        values = data[key]
        if (
            not isinstance(values, list)
            or len(values) != length
            or any(type(v) is not int or not minimum <= v <= maximum for v in values)
        ):
            raise ValueError(f"{key}需要{length}个有效整数")

    def names(values, length):
        return (
            isinstance(values, list)
            and len(values) == length
            and all(
                isinstance(v, str)
                and 1 <= len(v.strip()) <= 80
                and not any(ord(c) < 32 for c in v)
                for v in values
            )
        )

    if not names(data["environment_names"], 5):
        raise ValueError("需要5个有效环境名称")
    if not isinstance(data["device_names"], dict) or set(data["device_names"]) != {
        "computer",
        "monitor",
        "keyboard",
        "mouse",
    }:
        raise ValueError("设备名称需要电脑、显示器、键盘、鼠标四类")
    if any(not names(values, 10) for values in data["device_names"].values()):
        raise ValueError("每类设备需要10个有效名称")
    return copy.deepcopy(data)


def income_settings(row):
    return {
        "enabled": bool(row and row.enabled),
        "first_date": row.first_settlement_date.isoformat() if row else None,
        "last_settled_on": (
            row.last_settled_on.isoformat() if row and row.last_settled_on else None
        ),
    }


class WorkstationAdminMixin:
    def workstation_rules(self, session=None):
        if session is None:
            with self._session() as s:
                return self.workstation_rules(s)
        row = session.get(WorkstationRulesRecord, 1)
        data = copy.deepcopy(row.data if row else default_rules())
        # Old instances may have custom component prices. Derive their current
        # bundle totals until the administrator explicitly saves the new field.
        if "environment_upgrade_costs" not in data:
            data["environment_upgrade_costs"] = [
                environment_upgrade_cost(n, rules=data) for n in range(1, 5)
            ]
        return {
            **data,
            "revision": row.version if row else 0,
        }

    def lock_workstation_rules(self, session, *, exclusive=False):
        insert = (
            pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        )
        session.execute(
            insert(WorkstationRulesRecord)
            .values(id=1, version=0, data=default_rules())
            .on_conflict_do_nothing()
        )
        row = session.scalar(
            select(WorkstationRulesRecord)
            .where(WorkstationRulesRecord.id == 1)
            .with_for_update(read=not exclusive)
            .execution_options(populate_existing=True)
        )
        return row

    def _workstation_projection(self, session, rules):
        users = list(session.scalars(select(UserRecord.id)))
        states = defaultdict(dict)
        for row in session.scalars(select(WorkstationComponentRecord)):
            states[row.user_id][row.category_number] = row
        total = 0
        environments = {i: 0 for i in range(1, 6)}
        for uid in users:
            entries = states[uid]
            stage = min(
                (entries[n].highest_level + 1) // 2 if n in entries else 1
                for n in range(1, 6)
            )
            environments[stage] += 1
            total += sum(
                component_daily_income(
                    n,
                    entries[n].active_level if n in entries else 1,
                    entries[n].equipped if n in entries else True,
                    rules=rules,
                )
                for n in range(1, 10)
            )
        return {
            "accounts": len(users),
            "daily_income": total,
            "environments": environments,
        }

    def workstation_admin_overview(self, now):
        today = now.astimezone(BEIJING).date()
        with self._session() as session:
            result = self._workstation_projection(
                session, self.workstation_rules(session)
            )
            result["settlement"] = income_settings(
                session.get(WorkstationIncomeSettingsRecord, 1)
            )
            count, amount = session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(WorkstationIncomeRecord.amount), 0),
                ).where(WorkstationIncomeRecord.settlement_date == today)
            ).one()
            result.update(
                today=today.isoformat(), settled_accounts=count, settled_amount=amount
            )
            return result

    def workstation_admin_settings(self):
        with self._session() as session:
            rules = self.workstation_rules(session)
            return {
                "rules": {k: v for k, v in rules.items() if k != "revision"},
                "revision": rules["revision"],
                "projection": self._workstation_projection(session, rules),
            }

    def workstation_admin_players(self, query="", page=1, page_size=20):
        result = self.list_workstations(query, page, page_size)
        result["pages"] = (result["total"] + page_size - 1) // page_size
        with self._session() as session:
            for item in result["items"]:
                user = session.scalar(
                    select(UserRecord).where(
                        UserRecord.employee_number == item["number"]
                    )
                )
                components = self._component_views(session, user.id)
                item["highest_environment"] = min(
                    (c["highest_level"] + 1) // 2
                    for c in components
                    if c["number"] <= 5
                )
                item["active_environment"] = min(
                    (c["active_level"] + 1) // 2 for c in components if c["number"] <= 5
                )
            return result

    def workstation_admin_player(self, number):
        with self._session() as session:
            user = session.scalar(
                select(UserRecord).where(UserRecord.employee_number == number)
            )
            if user is None:
                raise WorkstationActionError("员工不存在", 404)
            workstation = self.get_workstation(user.id)
            return {
                "workstation": workstation,
                "shop": self.get_workstation_shop(user.platform_id),
                "revision": digest(
                    {
                        "workstation": workstation,
                        "rules": self.workstation_rules(session)["revision"],
                    }
                ),
            }

    def _admin_player_projection(self, before, payload, rules):
        after = copy.deepcopy(before)
        p = after["progression"]
        cs = p["components"]
        room = payload["environment"]
        owned = min((c["highest_level"] + 1) // 2 for c in cs if c["number"] <= 5)
        if payload["kind"] == "equip" and room > owned:
            raise WorkstationActionError("环境尚未拥有")
        for c in cs:
            n = c["number"]
            target = room * 2 - 1 if n <= 5 else payload["devices"][str(n)]["level"]
            if n >= 6 and target not in (room * 2 - 1, room * 2):
                raise ValueError("设备档位必须属于选定环境")
            if payload["kind"] == "grant":
                c["highest_level"] = max(c["highest_level"], target)
            if target > c["highest_level"]:
                raise WorkstationActionError("设备档位尚未拥有")
            c["active_level"] = target
            c["equipped"] = True if n <= 5 else payload["devices"][str(n)]["equipped"]
            from .workstation_catalog import component_name

            c["name"] = component_name(CATEGORIES[n - 1], target, rules=rules)
            c["description"] = CATEGORIES[n - 1]["descriptions"][target - 1]
            c["daily_income"] = component_daily_income(
                n, target, c["equipped"], rules=rules
            )
        from .workstation_accessories import ACCESSORIES

        highest = min((c["highest_level"] + 1) // 2 for c in cs if c["number"] <= 5)
        if payload["kind"] == "grant":
            existing = {a["number"] for a in p["accessories"]}
            p["accessories"] += [
                {**a, "equipped": True}
                for a in ACCESSORIES
                if a["environment"] <= highest and a["number"] not in existing
            ]
        p["daily_income"] = after["daily_income"] = sum(c["daily_income"] for c in cs)
        p["equipped_count"] = sum(c["equipped"] for c in cs) + sum(
            a["equipped"] for a in p["accessories"]
        )
        p["scene"] = component_scene(cs)
        p.pop("accessory_scene", None)
        scene = accessory_scene(cs, p["accessories"])
        if scene:
            p["accessory_scene"] = scene
        p["growth"] = growth_state(cs, p["accessories"], scene)
        from .workstation_catalog import environment_name

        p["environment_name"] = environment_name(room, rules=rules)
        return after

    def workstation_admin_player_preview(self, number, payload):
        detail = self.workstation_admin_player(number)
        if payload["kind"] == "backfill":
            after = copy.deepcopy(detail["workstation"])
            from .workstation_accessories import ACCESSORIES

            p = after["progression"]
            owned = p["growth"]["highest_environment"]
            existing = {a["number"] for a in p["accessories"]}
            p["accessories"] += [
                {**a, "equipped": True}
                for a in ACCESSORIES
                if a["environment"] <= owned and a["number"] not in existing
            ]
            scene = accessory_scene(p["components"], p["accessories"])
            p["equipped_count"] = sum(c["equipped"] for c in p["components"]) + sum(
                a["equipped"] for a in p["accessories"]
            )
            if scene:
                p["accessory_scene"] = scene
            p["growth"] = growth_state(p["components"], p["accessories"], scene)
        else:
            after = self._admin_player_projection(
                detail["workstation"], payload, self.workstation_rules()
            )
        return {
            "before": detail["workstation"],
            "after": after,
            "revision": detail["revision"],
        }

    def _workstation_admin_operation(
        self, payload, now, operation, *, number=None, exclusive=False, settlement=False
    ):
        with self.transaction(), self._session() as session:
            self.lock_workstation_rules(session, exclusive=exclusive)
            user = None
            if number is not None:
                user = session.scalar(
                    select(UserRecord)
                    .where(UserRecord.employee_number == number)
                    .with_for_update()
                )
                if user is None:
                    raise WorkstationActionError("员工不存在", 404)
            if settlement:
                session.scalar(
                    select(WorkstationIncomeSettingsRecord)
                    .where(WorkstationIncomeSettingsRecord.id == 1)
                    .with_for_update()
                )
            fingerprint = digest({"number": number, **payload})
            receipt = session.scalar(
                select(WorkstationAdminOperationRecord).where(
                    WorkstationAdminOperationRecord.actor == payload["actor"],
                    WorkstationAdminOperationRecord.request_id
                    == UUID(payload["request_id"]),
                )
            )
            if receipt:
                if receipt.fingerprint != fingerprint:
                    raise WorkstationActionError("请求编号已用于其他操作")
                return {**receipt.result, "replayed": True}
            before, after, result = operation(session, user)
            session.add(
                WorkstationAdminOperationRecord(
                    actor=payload["actor"],
                    request_id=UUID(payload["request_id"]),
                    fingerprint=fingerprint,
                    kind=payload["kind"],
                    user_id=user.id if user else None,
                    reason=(payload.get("reason") or "").strip() or {
                        "rules": "修改工位规则", "income": "调整结算设置", "settle": "执行今日结算",
                        "grant": "补授环境与设备", "equip": "调整已拥有的装备", "backfill": "补齐自动配件",
                    }[payload["kind"]],
                    before=before,
                    after=after,
                    result=result,
                    created_at=now,
                )
            )
            session.flush()
            return {**result, "replayed": False}

    def workstation_admin_player_apply(self, number, payload, now):
        def apply(session, user):
            detail = self.workstation_admin_player(number)
            if detail["revision"] != payload["revision"]:
                raise WorkstationActionError("工位已变化，请重新预览")
            before = detail["workstation"]
            balance = user.balance
            if payload["kind"] == "backfill":
                self._grant_environment_accessories(
                    session,
                    user.id,
                    before["progression"]["growth"]["highest_environment"],
                )
            else:
                after = self._admin_player_projection(
                    before, payload, self.workstation_rules(session)
                )
                for c in after["progression"]["components"]:
                    row = session.get(
                        WorkstationComponentRecord, (user.id, c["number"])
                    )
                    if row is None:
                        row = WorkstationComponentRecord(
                            user_id=user.id, category_number=c["number"]
                        )
                        session.add(row)
                    row.highest_level = c["highest_level"]
                    row.active_level = c["active_level"]
                    row.equipped = c["equipped"]
                if payload["kind"] == "grant":
                    self._grant_environment_accessories(
                        session,
                        user.id,
                        after["progression"]["growth"]["highest_environment"],
                    )
            session.flush()
            assert user.balance == balance
            result = self.workstation_admin_player(number)
            return before, result["workstation"], result

        return self._workstation_admin_operation(
            payload, now, apply, number=number, exclusive=True
        )

    def workstation_admin_rules_preview(self, data):
        data = validate_rules(data)
        with self._session() as session:
            current = self.workstation_rules(session)
            return {
                "revision": current["revision"],
                "before": self._workstation_projection(session, current),
                "after": self._workstation_projection(session, data),
            }

    def workstation_admin_rules_apply(self, payload, now):
        data = validate_rules(payload["data"])

        def apply(session, user):
            row = session.get(WorkstationRulesRecord, 1)
            if row.version != payload["revision"]:
                raise WorkstationActionError("规则已变化，请刷新后重新保存")
            before = copy.deepcopy(row.data)
            row.data = data
            row.version += 1
            session.flush()
            return before, data, self.workstation_admin_settings()

        return self._workstation_admin_operation(payload, now, apply, exclusive=True)

    def workstation_admin_income_apply(self, payload, now):
        def apply(session, user):
            row = session.get(WorkstationIncomeSettingsRecord, 1)
            before = income_settings(row)
            if payload.get("revision") != digest(before):
                raise WorkstationActionError("结算状态已变化，请刷新后重新操作")
            if payload["kind"] == "settle":
                result = self.run_workstation_income_jobs(now)
            else:
                if row is None:
                    row = WorkstationIncomeSettingsRecord(
                        id=1,
                        enabled=payload["enabled"],
                        first_settlement_date=now.astimezone(BEIJING).date(),
                    )
                    session.add(row)
                else:
                    row.enabled = payload["enabled"]
                session.flush()
                result = income_settings(row)
            after = income_settings(row)
            return (
                before,
                after,
                {"settlement": after, "revision": digest(after), "result": result},
            )

        return self._workstation_admin_operation(
            payload, now, apply, settlement=True, exclusive=True
        )

    def workstation_admin_records(self, kind, page=1, page_size=20, query=""):
        with self._session() as session:
            if kind == "settlements":
                statement = (
                    select(WorkstationIncomeRecord, UserRecord)
                    .join(UserRecord)
                    .order_by(
                        WorkstationIncomeRecord.settlement_date.desc(),
                        UserRecord.employee_number,
                    )
                )
                count = (
                    select(func.count())
                    .select_from(WorkstationIncomeRecord)
                    .join(UserRecord)
                )
                if query:
                    condition = UserRecord.display_name.icontains(query) | (
                        UserRecord.employee_number == int(query)
                        if query.isascii() and query.isdecimal()
                        else False
                    )
                    statement = statement.where(condition)
                    count = count.where(condition)
                rows = session.execute(
                    statement.offset((page - 1) * page_size).limit(page_size)
                ).all()
                items = [
                    {
                        "employee_number": u.employee_number,
                        "display_name": u.display_name,
                        "date": r.settlement_date.isoformat(),
                        "amount": r.amount,
                        "components": r.components,
                        "created_at": r.settled_at.isoformat(),
                    }
                    for r, u in rows
                ]
            else:
                statement = select(WorkstationAdminOperationRecord).order_by(
                    WorkstationAdminOperationRecord.created_at.desc()
                )
                count = select(func.count()).select_from(
                    WorkstationAdminOperationRecord
                )
                if query:
                    condition = WorkstationAdminOperationRecord.actor.icontains(
                        query
                    ) | WorkstationAdminOperationRecord.reason.icontains(query)
                    statement = statement.where(condition)
                    count = count.where(condition)
                rows = session.scalars(
                    statement.offset((page - 1) * page_size).limit(page_size)
                ).all()
                items = [
                    {
                        "id": str(r.id),
                        "actor": r.actor,
                        "kind": r.kind,
                        "reason": r.reason,
                        "user_id": str(r.user_id) if r.user_id else None,
                        "before": r.before,
                        "after": r.after,
                        "created_at": r.created_at.isoformat(),
                    }
                    for r in rows
                ]
            return {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": session.scalar(count),
                "pages": (session.scalar(count) + page_size - 1) // page_size,
            }


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class DeviceState(StrictBody):
    level: int = Field(ge=1, le=10)
    equipped: bool = True


class PlayerChange(StrictBody):
    kind: str = Field(pattern="^(grant|equip|backfill)$")
    environment: int = Field(ge=1, le=5)
    devices: dict[str, DeviceState]


class AdminPlayerChange(PlayerChange):
    actor: str = Field(min_length=1, max_length=200)
    request_id: str
    reason: str = Field(default="", max_length=500)
    revision: str = Field(pattern="^[0-9a-f]{64}$")


class AdminChange(StrictBody):
    actor: str = Field(min_length=1, max_length=200)
    request_id: str
    reason: str = Field(default="", max_length=500)
    kind: str = Field(pattern="^(rules|income|settle)$")
    revision: int | str
    data: dict | None = None
    enabled: bool | None = None


def install_workstation_admin_routes(app, repository, authorize, clock=beijing_now):
    def response(call):
        try:
            return call()
        except WorkstationActionError as error:
            raise HTTPException(error.code, str(error)) from error
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(422, str(error)) from error

    prefix = "/internal/game/workstation"

    @app.get(prefix + "/overview", dependencies=[Depends(authorize)])
    def overview():
        return repository.workstation_admin_overview(clock())

    @app.get(prefix + "/settings", dependencies=[Depends(authorize)])
    def settings():
        result = repository.workstation_admin_settings()
        with repository._session() as session:
            state = income_settings(session.get(WorkstationIncomeSettingsRecord, 1))
        return {**result, "settlement": state, "settlement_revision": digest(state)}

    @app.get(prefix + "/players", dependencies=[Depends(authorize)])
    def players(
        query: str = Query("", max_length=64),
        page: int = Query(1, ge=1, le=100000),
        page_size: int = Query(20, ge=1, le=48),
    ):
        return repository.workstation_admin_players(query, page, page_size)

    @app.get(prefix + "/players/{number}", dependencies=[Depends(authorize)])
    def player(number: int):
        return response(lambda: repository.workstation_admin_player(number))

    @app.post(prefix + "/players/{number}/preview", dependencies=[Depends(authorize)])
    def player_preview(number: int, payload: PlayerChange):
        if set(payload.devices) != {"6", "7", "8", "9"}:
            raise HTTPException(422, "需要四件设备状态")
        return response(
            lambda: repository.workstation_admin_player_preview(
                number, payload.model_dump()
            )
        )

    @app.post(prefix + "/players/{number}/actions", dependencies=[Depends(authorize)])
    def player_apply(number: int, payload: AdminPlayerChange):
        if set(payload.devices) != {"6", "7", "8", "9"}:
            raise HTTPException(422, "需要四件设备状态")
        return response(
            lambda: repository.workstation_admin_player_apply(
                number, payload.model_dump(), clock()
            )
        )

    @app.post(prefix + "/settings/preview", dependencies=[Depends(authorize)])
    def settings_preview(payload: dict):
        return response(lambda: repository.workstation_admin_rules_preview(payload))

    @app.post(prefix + "/settings", dependencies=[Depends(authorize)])
    def save_settings(payload: AdminChange):
        if (
            payload.kind != "rules"
            or type(payload.revision) is not int
        ):
            raise HTTPException(422, "规则保存参数无效")
        return response(
            lambda: repository.workstation_admin_rules_apply(
                payload.model_dump(), clock()
            )
        )

    @app.post(prefix + "/income", dependencies=[Depends(authorize)])
    def save_income(payload: AdminChange):
        if (
            payload.kind not in ("income", "settle")
            or (payload.kind == "income" and payload.enabled is None)
        ):
            raise HTTPException(422, "结算参数无效")
        return response(
            lambda: repository.workstation_admin_income_apply(
                payload.model_dump(), clock()
            )
        )

    @app.get(prefix + "/records/{kind}", dependencies=[Depends(authorize)])
    def records(
        kind: str,
        page: int = Query(1, ge=1, le=100000),
        page_size: int = Query(20, ge=1, le=48),
        query: str = Query("", max_length=64),
    ):
        if kind not in ("settlements", "operations"):
            raise HTTPException(404, "记录不存在")
        return repository.workstation_admin_records(kind, page, page_size, query)
