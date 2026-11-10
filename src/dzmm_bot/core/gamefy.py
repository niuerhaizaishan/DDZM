from typing import Annotated, Literal
from uuid import UUID
import logging

import jwt
from fastapi import Depends, Header, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import beijing_now
from .workstation_share import available_share_groups, enqueue_workstation_share, share_status
from .workstation_actions import WorkstationActionError


JWKS_URL = "https://www.dzmm.ai/api/gamefy/.well-known/jwks.json"
logger = logging.getLogger(__name__)


class WorkstationShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: UUID
    request_id: UUID


class WorkstationAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal['upgrade', 'purchase', 'equip', 'remove', 'advance', 'polish', 'view']
    number: int | None = Field(default=None, ge=1, le=999)
    level: int | None = Field(default=None, ge=1, le=10)

    @model_validator(mode='after')
    def valid_shape(self):
        needs_number = self.kind in {'upgrade', 'purchase', 'equip', 'remove'}
        needs_level = self.kind == 'view' or self.kind == 'equip' and self.number is not None and self.number <= 9
        if needs_number != (self.number is not None) or needs_level != (self.level is not None):
            raise ValueError('操作参数与类型不符')
        if self.kind == 'view' and self.level > 5:
            raise ValueError('环境范围为1至5')
        return self


class WorkstationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: WorkstationAction
    revision: str = Field(pattern=r'^[0-9a-f]{64}$')


class WorkstationActionRequest(WorkstationPreviewRequest):
    request_id: UUID


class GamefyIdentityVerifier:
    def __init__(self, game_id: str):
        numeric_id = game_id.isascii() and game_id.isdecimal() and int(game_id) > 0
        try:
            uuid_id = str(UUID(game_id)) == game_id
        except (ValueError, TypeError, AttributeError):
            uuid_id = False
        if not numeric_id and not uuid_id:
            raise ValueError("DZMM_GAMEFY_GAME_ID must be a canonical UUID or positive numeric game ID")
        self.game_id = game_id
        self.keys = jwt.PyJWKClient(
            JWKS_URL, lifespan=3600, timeout=5,
            headers={"User-Agent": "DDZM-Workstation/1.0", "Accept": "application/json"},
        )

    def verify(self, token: str) -> str:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or not header["kid"]:
                raise jwt.InvalidTokenError()
            key = self.keys.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token, key, algorithms=["RS256"], issuer="dzmm-gamefy",
                audience=self.game_id,
                options={"require": ["exp", "iat", "sub", "iss", "aud"], "strict_aud": True},
            )
            return str(UUID(claims["sub"]))
        except jwt.PyJWKClientConnectionError as error:
            raise HTTPException(503, "平台身份验证暂不可用，请稍后刷新重试。") from error
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as error:
            logger.warning(
                "Gamefy identity rejected: %s (%s)", type(error).__name__,
                str(error) if isinstance(error, jwt.InvalidAudienceError) else "invalid credentials",
            )
            raise HTTPException(401, "玩家身份无效或已过期，请刷新游戏重新登录。") from error


def install_gamefy_routes(app, repository, authorize, game_id):
    verifier = GamefyIdentityVerifier(game_id) if game_id else None

    def authenticated_employee(
        _: Annotated[None, Depends(authorize)],
        authorization: Annotated[str | None, Header()] = None,
    ):
        if verifier is None:
            raise HTTPException(503, "平台工位尚未开放，请管理员配置游戏 ID。")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "请先登录 DZMM，再打开工位游戏。")
        token = authorization[7:]
        if not token or len(token) > 8192:
            raise HTTPException(401, "玩家身份无效，请刷新游戏重新登录。")
        platform_id = verifier.verify(token)
        user = repository.find_user(platform_id)
        if user is None:
            raise HTTPException(404, "尚未找到你的员工档案，请先在群里发送 /入职 名字。")
        return user

    @app.get("/internal/gamefy/workstation")
    def gamefy_workstation(user=Depends(authenticated_employee)):
        workstation = repository.get_workstation(user.id)
        return JSONResponse(
            {**workstation, "currency_name": repository.get_game_settings().currency_name,
             "share_groups": available_share_groups(repository, user.platform_id, beijing_now())},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/internal/gamefy/workstation/shop")
    def workstation_shop(user=Depends(authenticated_employee)):
        return JSONResponse(repository.workstation_management(user.platform_id, beijing_now()), headers={"Cache-Control": "no-store"})

    def action_response(operation):
        try:
            return JSONResponse(operation(), headers={"Cache-Control": "no-store"})
        except WorkstationActionError as error:
            raise HTTPException(error.code, str(error)) from error

    @app.post('/internal/gamefy/workstation/quote')
    def quote_action(action: WorkstationAction, user=Depends(authenticated_employee)):
        return action_response(lambda: repository.quote_workstation_action(
            user.platform_id, action.model_dump(exclude_none=True), beijing_now()))

    @app.post('/internal/gamefy/workstation/actions')
    def apply_action(payload: WorkstationActionRequest, user=Depends(authenticated_employee)):
        return action_response(lambda: repository.apply_workstation_action(user.platform_id,
            payload.action.model_dump(exclude_none=True), payload.request_id, payload.revision, beijing_now()))

    @app.post("/internal/gamefy/workstation/share")
    def share_workstation(payload: WorkstationShareRequest, user=Depends(authenticated_employee)):
        return enqueue_workstation_share(repository, user.id, payload.group_id, payload.request_id, beijing_now())

    @app.get("/internal/gamefy/workstation/lobby")
    def workstation_lobby(
        query: str = Query("", max_length=64), page: int = Query(1, ge=1, le=1000000),
        user=Depends(authenticated_employee),
    ):
        return JSONResponse(
            {**repository.list_workstations(query, page), "my_number": user.employee_number},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/internal/gamefy/workstation/employees/{employee_number}")
    def employee_workstation(employee_number: int = Path(ge=1, le=2147483647), user=Depends(authenticated_employee)):
        workstation = repository.get_workstation_by_number(employee_number)
        if workstation is None:
            raise HTTPException(404, "未找到该员工的工位，请返回大厅刷新。")
        is_owner = employee_number == user.employee_number
        return JSONResponse(
            {**workstation, "is_owner": is_owner,
             "currency_name": repository.get_game_settings().currency_name,
             "share_groups": available_share_groups(repository, user.platform_id, beijing_now()) if is_owner else []},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/internal/gamefy/workstation/shares/{request_id}")
    def workstation_share_status(request_id: UUID, user=Depends(authenticated_employee)):
        return share_status(repository, user.id, request_id)
