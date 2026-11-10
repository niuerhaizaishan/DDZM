"""Authenticated workstation administration; public game routes remain separate."""

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Query
from dzmm_bot.core.workstation_actions import digest


def install_workstation_management(
    app,
    core,
    repository,
    authorize,
    require_super_admin,
    idempotent_response,
    versioned_response,
    relay,
):
    prefix = "/api/game/workstation"

    def read(resource, params=None):
        return relay(lambda: core.workstation_admin_get(resource, params))

    def write(resource, payload):
        return relay(lambda: core.workstation_admin_write(resource, payload))

    def envelope(identity, key, payload):
        if "actor" in payload or "request_id" in payload:
            raise HTTPException(422, "操作身份与请求编号由服务端生成")
        try:
            request_id = str(UUID(key or ""))
        except ValueError:
            raise HTTPException(422, "Idempotency-Key must be a UUID")
        actor = f'{identity.account_id or "super_admin"}:{identity.username}'
        return {**payload, "actor": actor, "request_id": request_id}

    def mutate(resource, payload, identity, key):
        body = envelope(identity, key, payload)
        return idempotent_response(
            identity,
            key,
            lambda: (200, write(resource, body)),
            scope=f"workstation:{resource}:{digest(body)}",
        )

    @app.get(prefix + "/overview")
    def overview(identity=Depends(authorize)):
        return read("overview")

    @app.get(prefix + "/settings")
    def settings(identity=Depends(authorize)):
        return {**read("settings"), "version": repository.config_version()}

    @app.get(prefix + "/players")
    def players(
        query: str = Query("", max_length=64),
        page: int = Query(1, ge=1, le=100000),
        page_size: int = Query(20, ge=1, le=48),
        identity=Depends(authorize),
    ):
        return read("players", {"query": query, "page": page, "page_size": page_size})

    @app.get(prefix + "/players/{number}")
    def player(number: int, identity=Depends(authorize)):
        return read(f"players/{number}")

    def player_permission(payload, identity):
        if payload.get("kind") == "grant" and identity.role != "super_admin":
            raise HTTPException(403, "仅超级管理员可补授环境与设备")

    @app.post(prefix + "/players/{number}/preview")
    def preview(number: int, payload: dict, identity=Depends(authorize)):
        player_permission(payload, identity)
        return write(f"players/{number}/preview", payload)

    @app.post(prefix + "/players/{number}/actions")
    def action(
        number: int,
        payload: dict,
        identity=Depends(authorize),
        idempotency_key: str | None = Header(None),
    ):
        player_permission(payload, identity)
        return mutate(f"players/{number}/actions", payload, identity, idempotency_key)

    @app.post(prefix + "/settings/preview")
    def rules_preview(payload: dict, identity=Depends(authorize)):
        return write("settings/preview", payload)

    @app.post(prefix + "/settings")
    def rules(
        payload: dict,
        identity=Depends(authorize),
        idempotency_key: str | None = Header(None),
        if_match: str | None = Header(None),
    ):
        body = envelope(identity, idempotency_key, payload)
        return versioned_response(
            identity,
            idempotency_key,
            if_match,
            lambda: write("settings", body),
            scope=f"workstation:rules:{digest(body)}",
        )

    @app.post(prefix + "/income")
    def income(
        payload: dict,
        identity=Depends(require_super_admin),
        idempotency_key: str | None = Header(None),
    ):
        return mutate("income", payload, identity, idempotency_key)

    @app.get(prefix + "/records/{kind}")
    def records(
        kind: str,
        query: str = Query("", max_length=64),
        page: int = Query(1, ge=1, le=100000),
        page_size: int = Query(20, ge=1, le=48),
        identity=Depends(authorize),
    ):
        if kind not in ("settlements", "operations"):
            raise HTTPException(404, "记录不存在")
        return read(
            f"records/{kind}", {"query": query, "page": page, "page_size": page_size}
        )
