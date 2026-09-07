import asyncio
from pathlib import Path
import tempfile
from secrets import compare_digest, token_urlsafe
from typing import Annotated, Callable
from uuid import UUID

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    WebSocket,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from httpx import HTTPStatusError
from sqlalchemy.exc import IntegrityError

from dzmm_bot.core.database import create_session_factory
from dzmm_bot.core.group_games import GROUP_GAME_TYPES
from dzmm_bot.core.schema import beijing_now
from dzmm_bot.runtime.settings import Settings

from .core_client import (
    AdminCorePort,
    CoreClient,
    NoVNCClient,
    NoVNCWebSocketConnector,
)
from .repository import (
    AdminIdentity,
    AdminRepository,
    ConfigVersionConflictError,
    IdempotencyInProgressError,
)


_ROOT = Path(__file__).parent
_SAFE_STATUS_FIELDS = (
    "state",
    "last_heartbeat",
    "listening",
    "listening_desired",
    "bot_delivery_state",
    "bot_delivery_error",
    "queue_counts",
)
_WORKER_COMMANDS = {
    "start": "resume_listening",
    "stop": "pause_listening",
    "restart": "restart_browser",
}
_CONSOLE_PATH = "login-console/websockify"
_CONSOLE_URL = "/login-console/?path=login-console%2Fwebsockify"


def _with_default_ai_memory_settings(settings: dict) -> dict:
    return {
        **settings,
        "memory_enabled": settings.get("memory_enabled", True),
        "extraction_prompt": settings.get(
            "extraction_prompt",
            "仅整理玩家稳定的称呼偏好、回复风格、长期兴趣和互动禁忌。",
        ),
        "history_limit": settings.get("history_limit", 500),
        "max_memory_chars": settings.get("max_memory_chars", 1200),
        "batch_message_threshold": settings.get("batch_message_threshold", 20),
        "max_entries_per_category": settings.get("max_entries_per_category", 3),
        "candidate_expiry_days": settings.get("candidate_expiry_days", 30),
    }


def create_app_from_environment() -> FastAPI:
    settings = Settings.from_environment()
    if settings.admin_token is None:
        raise ValueError("DZMM_ADMIN_TOKEN must be set and nonempty")
    return create_app(
        settings.admin_token,
        CoreClient(
            f"http://127.0.0.1:{settings.core_api_port}", settings.core_token
        ),
        repository=AdminRepository(create_session_factory(settings.database_url)),
        console_client=NoVNCClient(settings.novnc_port),
        websocket_connector=NoVNCWebSocketConnector(settings.novnc_port),
    )


def create_app(
    admin_token: str,
    core: AdminCorePort,
    *,
    repository: AdminRepository,
    console_client: NoVNCClient | None = None,
    websocket_connector: Callable | None = None,
    profile_upload_dir: Path | None = None,
) -> FastAPI:
    if not admin_token:
        raise ValueError("admin_token must be nonempty")
    app = FastAPI()
    console = console_client or NoVNCClient()
    connect_websocket = websocket_connector or NoVNCWebSocketConnector()
    upload_dir = profile_upload_dir or Path(tempfile.gettempdir()) / "dzmm-profile-images"
    upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    upload_dir.chmod(0o700)
    console_session: tuple[str, str] | None = None

    def authorize(
        x_admin_token: Annotated[str | None, Header()] = None,
        x_admin_session: Annotated[str | None, Header()] = None,
    ) -> AdminIdentity:
        if x_admin_token is not None and x_admin_session is not None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")
        if x_admin_token is not None and compare_digest(x_admin_token, admin_token):
            return AdminIdentity(None, "超级管理员", "super_admin")
        if x_admin_session is not None:
            identity = repository.resolve_session(x_admin_session, beijing_now())
            if identity is not None:
                return identity
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")

    def require_super_admin(
        identity: Annotated[AdminIdentity, Depends(authorize)],
    ) -> AdminIdentity:
        if identity.role != "super_admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "super admin required")
        return identity

    def idempotent_response(
        identity: AdminIdentity,
        idempotency_key: str | None,
        operation: Callable[[], tuple[int, dict]],
        *,
        scope: str,
    ) -> JSONResponse:
        if not idempotency_key:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Idempotency-Key is required")
        actor = "super_admin" if identity.account_id is None else str(identity.account_id)
        actor_key = f"{actor}:{scope}"
        try:
            replay = repository.reserve_idempotency_key(
                actor_key, idempotency_key, beijing_now()
            )
        except IdempotencyInProgressError as error:
            raise HTTPException(status.HTTP_409_CONFLICT, str(error))
        if replay is not None:
            status_code, body = replay
            return JSONResponse(body, status_code=status_code)
        try:
            status_code, body = operation()
        except Exception:
            repository.release_idempotency_key(actor_key, idempotency_key)
            raise
        repository.complete_idempotency_key(
            actor_key, idempotency_key, status_code, body, beijing_now()
        )
        return JSONResponse(body, status_code=status_code)

    def versioned_configuration_response(
        identity: AdminIdentity,
        idempotency_key: str | None,
        if_match: str | None,
        operation: Callable[[], dict],
        *,
        scope: str,
        status_code: int = 200,
    ) -> JSONResponse:
        try:
            expected_version = int(if_match) if if_match is not None else None
        except ValueError:
            expected_version = None
        if expected_version is None or expected_version < 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "If-Match version is required")

        def versioned_operation() -> tuple[int, dict]:
            try:
                body, version = repository.update_configuration(
                    expected_version, operation
                )
            except ConfigVersionConflictError as error:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    {"message": str(error), "version": error.current_version},
                )
            return status_code, {**body, "version": version}

        return idempotent_response(
            identity, idempotency_key, versioned_operation, scope=scope
        )

    @app.get("/", response_class=HTMLResponse)
    def index() -> FileResponse:
        return FileResponse(
            _ROOT / "templates" / "index.html",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/static/admin.js")
    def javascript() -> FileResponse:
        return FileResponse(
            _ROOT / "static" / "admin.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/static/admin_urls.js")
    def javascript_urls() -> FileResponse:
        return FileResponse(
            _ROOT / "static" / "admin_urls.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/static/admin.css")
    def stylesheet() -> FileResponse:
        return FileResponse(
            _ROOT / "static" / "admin.css",
            media_type="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def admin_login(request: dict) -> dict:
        username = request.get("username")
        password = request.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid login")
        account = repository.authenticate(username, password)
        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
        return {
            "session_token": repository.create_session(account.id, beijing_now()),
            "account_id": str(account.id),
            "username": account.username,
            "role": "admin",
        }

    @app.get("/api/auth/me")
    def admin_identity(
        identity: Annotated[AdminIdentity, Depends(authorize)],
    ) -> dict:
        return {
            "account_id": None if identity.account_id is None else str(identity.account_id),
            "username": identity.username,
            "role": identity.role,
        }

    @app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def admin_logout(
        identity: Annotated[AdminIdentity, Depends(authorize)],
        x_admin_session: Annotated[str | None, Header()] = None,
    ) -> Response:
        if identity.account_id is not None and x_admin_session is not None:
            repository.revoke_session(x_admin_session)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/api/admins")
    def admin_accounts(
        _: Annotated[AdminIdentity, Depends(require_super_admin)],
    ) -> list[dict]:
        return [
            {
                "id": str(account.id),
                "username": account.username,
                "active": account.active,
                "created_at": account.created_at,
            }
            for account in repository.list_accounts()
        ]

    @app.post("/api/admins", status_code=status.HTTP_201_CREATED)
    def create_admin_account(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(require_super_admin)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        username = request.get("username")
        password = request.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid administrator")
        username = username.strip()
        if not 1 <= len(username) <= 32 or len(password) < 8:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid administrator")

        def operation() -> tuple[int, dict]:
            try:
                account = repository.create_account(username, password)
            except IntegrityError:
                raise HTTPException(status.HTTP_409_CONFLICT, "administrator already exists")
            return 201, {
                "id": str(account.id),
                "username": account.username,
                "active": account.active,
            }

        return idempotent_response(identity, idempotency_key, operation, scope="admins")

    @app.patch("/api/admins/{account_id}")
    def update_admin_account(
        account_id: UUID,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(require_super_admin)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        if "active" in request:
            if not isinstance(request["active"], bool):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid administrator")
            def operation() -> tuple[int, dict]:
                account = repository.set_account_active(account_id, request["active"])
                if account is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "administrator not found")
                return 200, _account_response(account)
        elif "password" in request and isinstance(request["password"], str):
            if len(request["password"]) < 8:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid administrator")
            def operation() -> tuple[int, dict]:
                account = repository.reset_password(account_id, request["password"])
                if account is None:
                    raise HTTPException(status.HTTP_404_NOT_FOUND, "administrator not found")
                return 200, _account_response(account)
        else:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid administrator")
        return idempotent_response(
            identity, idempotency_key, operation, scope=f"admins:{account_id}:update"
        )

    @app.delete("/api/admins/{account_id}")
    def delete_admin_account(
        account_id: UUID,
        identity: Annotated[AdminIdentity, Depends(require_super_admin)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        def operation() -> tuple[int, dict]:
            if not repository.delete_account(account_id):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "administrator not found")
            return 200, {"deleted": True}

        return idempotent_response(
            identity, idempotency_key, operation, scope=f"admins:{account_id}:delete"
        )

    @app.get("/api/status")
    def operational_status(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        raw = core.status()
        return {key: raw.get(key) for key in _SAFE_STATUS_FIELDS}

    @app.get("/api/group-chats")
    def group_chats(
        _: Annotated[None, Depends(authorize)],
        include_deleted: bool = False,
    ) -> dict:
        return {
            "items": _relay_core(
                lambda: core.list_group_chats(include_deleted)
            ),
            "version": repository.config_version(),
        }

    @app.post("/api/group-chats")
    def create_group_chat(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "name",
            "chat_url",
            "listening_enabled",
            "games_enabled",
            "random_events_enabled",
            "announcements_enabled",
        )
        if (
            not isinstance(request.get("name"), str)
            or not isinstance(request.get("chat_url"), str)
            or not all(
                isinstance(request.get(key), bool)
                for key in (
                    "listening_enabled",
                    "games_enabled",
                    "random_events_enabled",
                    "announcements_enabled",
                )
            )
            or (
                "adult_shop_enabled" in request
                and not isinstance(request["adult_shop_enabled"], bool)
            )
            or (
                "performances_enabled" in request
                and not isinstance(request["performances_enabled"], bool)
            )
            or (
                "enabled_game_types" in request
                and (
                    not isinstance(request["enabled_game_types"], list)
                    or not all(
                        isinstance(value, str)
                        for value in request["enabled_game_types"]
                    )
                )
            )
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid group chat"
            )
        payload = {
            **{key: request[key] for key in required},
            "adult_shop_enabled": request.get("adult_shop_enabled", False),
            "performances_enabled": request.get("performances_enabled", False),
            "enabled_game_types": request.get(
                "enabled_game_types", list(GROUP_GAME_TYPES)
            ),
            "now": beijing_now().isoformat(),
        }
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.create_group_chat(payload)),
            scope="group-chats:create",
            status_code=status.HTTP_201_CREATED,
        )

    @app.patch("/api/group-chats/{group_id}")
    def update_group_chat(
        group_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        allowed = {
            "name",
            "chat_url",
            "listening_enabled",
            "games_enabled",
            "enabled_game_types",
            "random_events_enabled",
            "announcements_enabled",
            "adult_shop_enabled",
            "performances_enabled",
        }
        if not request or set(request) - allowed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid group chat"
            )
        if any(
            key in request and not isinstance(request[key], str)
            for key in ("name", "chat_url")
        ) or any(
            key in request and not isinstance(request[key], bool)
            for key in allowed - {"name", "chat_url", "enabled_game_types"}
        ) or (
            "enabled_game_types" in request
            and (
                not isinstance(request["enabled_game_types"], list)
                or not all(
                    isinstance(value, str)
                    for value in request["enabled_game_types"]
                )
            )
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid group chat"
            )
        payload = {**request, "now": beijing_now().isoformat()}
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.update_group_chat(group_id, payload)
            ),
            scope=f"group-chats:{group_id}:update",
        )

    @app.delete("/api/group-chats/{group_id}")
    def delete_group_chat(
        group_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.delete_group_chat(
                    group_id, beijing_now().isoformat()
                )
            ),
            scope=f"group-chats:{group_id}:delete",
        )

    @app.post("/api/group-chats/{group_id}/add-bot", status_code=status.HTTP_202_ACCEPTED)
    def add_bot_to_group_chat(
        group_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (202, _relay_core(lambda: core.add_bot_to_group(group_id))),
            scope=f"group-chats:{group_id}:add-bot",
        )

    @app.get("/api/game/commands")
    def game_commands(_: Annotated[None, Depends(authorize)]) -> list[dict]:
        version = repository.config_version()
        return [{**command, "version": version} for command in core.list_game_commands()]

    @app.patch("/api/game/commands")
    def set_game_command_enabled(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        command = request.get("command")
        enabled = request.get("enabled")
        if not isinstance(command, str) or not isinstance(enabled, bool):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid command")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: core.set_game_command_enabled(command, enabled),
            scope=f"game-command:{command}",
        )

    @app.patch("/api/game/command-templates")
    def set_game_command_template(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        command = request.get("command")
        scenario = request.get("scenario")
        template = request.get("template")
        if not all(isinstance(value, str) for value in (command, scenario, template)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid template")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.set_game_command_template(command, scenario, template)),
            scope=f"game-template:{command}:{scenario}",
        )

    @app.get("/api/game/users")
    def game_users(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return core.list_game_users(page, page_size)

    @app.get("/api/game/users/{platform_id}/balance-transactions")
    def balance_transactions(
        platform_id: str,
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return _relay_core(
            lambda: core.list_balance_transactions(platform_id, page, page_size)
        )

    @app.get("/api/game/users/{platform_id}/group-messages")
    def employee_group_messages(
        platform_id: str,
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        group_chat_id: str | None = Query(None),
    ) -> dict:
        return _relay_core(
            lambda: core.list_employee_group_messages(
                platform_id, page, page_size, group_chat_id
            )
        )

    @app.get("/api/game/ranks")
    def game_ranks(_: Annotated[None, Depends(authorize)]) -> list[dict]:
        return _relay_core(core.list_ranks)

    @app.patch("/api/game/ranks/{rank_id}")
    def update_game_rank(
        rank_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "name",
            "promotion_price",
            "checkin_reward",
            "vote_weight",
            "multiplayer_game_limit",
            "has_group_management",
            "enabled",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid rank")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.update_rank(
                    rank_id, {key: request[key] for key in required}
                )
            ),
            scope=f"rank:{rank_id}",
        )

    @app.get("/api/game/departments")
    def game_departments(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return {
            **_relay_core(lambda: core.list_departments(page, page_size)),
            "version": repository.config_version(),
        }

    @app.post("/api/game/departments", status_code=status.HTTP_201_CREATED)
    def create_game_department(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        if not isinstance(request.get("name"), str) or not isinstance(
            request.get("description", ""), str
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid department")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.create_department(
                    {"name": request["name"], "description": request.get("description", "")}
                )
            ),
            scope="departments",
            status_code=status.HTTP_201_CREATED,
        )

    @app.put("/api/game/departments/{department_id}")
    def update_game_department(
        department_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = ("name", "description", "enabled")
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid department")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.update_department(
                    department_id, {key: request[key] for key in required}
                )
            ),
            scope=f"department:{department_id}",
        )

    @app.delete("/api/game/departments/{department_id}")
    def delete_game_department(
        department_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.delete_department(department_id)),
            scope=f"department:{department_id}",
        )

    @app.get("/api/game/promotions")
    def game_promotions(
        _: Annotated[None, Depends(authorize)],
        state: str | None = Query(None),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return {
            **_relay_core(lambda: core.list_promotions(state, page, page_size)),
            "version": repository.config_version(),
        }

    @app.get("/api/game/department-requests")
    def game_department_requests(
        _: Annotated[None, Depends(authorize)],
        state: str | None = Query(None),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return {
            **_relay_core(
                lambda: core.list_department_requests(state, page, page_size)
            ),
            "version": repository.config_version(),
        }

    @app.post("/api/game/users/{platform_id}/board-membership")
    def set_board_membership(
        platform_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(require_super_admin)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        if not isinstance(request.get("member"), bool):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid board membership")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                {
                    **_relay_core(
                        lambda: core.set_board_membership(platform_id, request["member"])
                    ),
                    "board_member": request["member"],
                },
            ),
            scope=f"board-membership:{platform_id}",
        )

    @app.get("/api/game/items")
    def game_items(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return core.list_game_items(page, page_size)

    @app.post("/api/game/items", status_code=status.HTTP_201_CREATED)
    async def create_game_item(
        request: Request,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        try:
            item = await request.json()
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid item")
        required = ("name", "description", "price", "stock")
        if not isinstance(item, dict) or not all(key in item for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid item")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (201, core.create_game_item({key: item[key] for key in required})),
            scope="game-items",
        )

    @app.patch("/api/game/items/{public_number}")
    def update_game_item(
        public_number: int,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        required = {
            "description",
            "enabled",
            "minimum_rank_order",
            "unlimited_stock",
            "stock",
        }
        if set(request) != required:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid item")
        if (
            not isinstance(request["description"], str)
            or not 1 <= len(request["description"].strip()) <= 200
            or not isinstance(request["enabled"], bool)
            or not isinstance(request["unlimited_stock"], bool)
            or not isinstance(request["stock"], int)
            or request["stock"] < 0
            or (
                request["minimum_rank_order"] is not None
                and (
                    not isinstance(request["minimum_rank_order"], int)
                    or request["minimum_rank_order"] < 1
                )
            )
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid item")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (200, core.update_game_item(public_number, request)),
            scope=f"game-items:{public_number}",
        )

    @app.get("/api/game/shop/activity")
    def shop_activity(
        _: Annotated[None, Depends(authorize)],
        limit: int = Query(100, ge=1, le=500),
    ) -> dict:
        return core.get_shop_activity(limit)

    @app.post("/api/game/shop/scene-jobs/{job_id}/retry")
    def retry_shop_scene_job(
        job_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (200, core.retry_shop_scene_job(job_id)),
            scope=f"shop-scene-retry:{job_id}",
        )

    @app.post("/api/game/shop/common-states/{state_id}/end")
    def end_shop_common_state(
        state_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (200, core.end_shop_common_state(state_id)),
            scope=f"shop-common-end:{state_id}",
        )

    @app.get("/api/game/settings")
    def game_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {**core.get_game_settings(), "version": repository.config_version()}

    @app.patch("/api/game/settings")
    def set_game_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "currency_name",
            "onboarding_bonus",
            "checkin_reward",
            "weekly_attendance_reward",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        optional = (
            "submission_enabled",
            "submission_draft_timeout_minutes",
            "submission_max_participants",
            "submission_default_target_rounds",
            "submission_default_event_reward",
            "submission_approval_reward",
        )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.set_game_settings({key: request[key] for key in required})),
            scope="game-settings",
        )

    @app.get("/api/game/profile-settings")
    def profile_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return _relay_core(core.get_profile_settings)

    @app.patch("/api/game/profile-settings")
    def set_profile_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        if set(request) != {"edit_cost", "shared_labor", "version"}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid profile settings"
            )
        if any(
            isinstance(request[key], bool) or not isinstance(request[key], int)
            for key in request
        ) or not (
            0 <= request["edit_cost"] <= 99999
            and 0 <= request["shared_labor"] <= 99999
            and request["version"] >= 0
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid profile settings"
            )
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (200, _relay_core(lambda: core.set_profile_settings(request))),
            scope="profile-settings",
        )

    @app.get("/api/game/users/{platform_id}/profile")
    def personal_profile(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> dict:
        return _relay_core(lambda: core.get_personal_profile(platform_id))

    @app.put("/api/game/users/{platform_id}/profile")
    def set_personal_profile(
        platform_id: str,
        request: dict,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        if (
            set(request) != {"profile_text"}
            or not isinstance(request["profile_text"], str)
            or len(request["profile_text"].strip()) > 800
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid personal profile"
            )
        return _relay_core(
            lambda: core.set_personal_profile(
                platform_id, request["profile_text"]
            )
        )

    @app.post(
        "/api/game/users/{platform_id}/profile-image",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def upload_personal_profile_image(
        platform_id: str,
        _: Annotated[None, Depends(authorize)],
        file: Annotated[UploadFile, File()],
    ) -> dict:
        allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
        if file.content_type not in allowed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid image type")
        destination = upload_dir / f"{token_urlsafe(24)}{allowed[file.content_type]}"
        size = 0
        try:
            with destination.open("xb") as output:
                destination.chmod(0o600)
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 10 * 1024 * 1024:
                        raise HTTPException(
                            status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "image exceeds 10 MB",
                        )
                    output.write(chunk)
            header = destination.read_bytes()[:12]
            valid_signature = (
                file.content_type == "image/png"
                and header.startswith(b"\x89PNG\r\n\x1a\n")
                or file.content_type == "image/jpeg"
                and header.startswith(b"\xff\xd8\xff")
                or file.content_type == "image/webp"
                and header.startswith(b"RIFF")
                and header[8:12] == b"WEBP"
            )
            if not valid_signature:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "invalid image content",
                )
            upload = {
                "temp_path": str(destination),
                "original_filename": file.filename or "profile-image",
                "mime_type": file.content_type,
                "now": beijing_now().isoformat(),
            }
            return _relay_core(
                lambda: core.create_profile_image_upload(platform_id, upload)
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.get("/api/game/profile-image-uploads/{task_id}")
    def personal_profile_image_upload_status(
        task_id: str, _: Annotated[None, Depends(authorize)]
    ) -> dict:
        return _relay_core(lambda: core.get_profile_image_upload(task_id))

    @app.delete("/api/game/users/{platform_id}/profile-image")
    def clear_personal_profile_image(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> dict:
        return _relay_core(lambda: core.clear_profile_image(platform_id))

    @app.get("/api/game/number-bomb/settings")
    def number_bomb_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_number_bomb_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/number-bomb/settings")
    def set_number_bomb_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = {
            "enabled",
            "signup_timeout_minutes",
            "reminder_interval_seconds",
        }
        if set(request) != required:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_number_bomb_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="number-bomb-settings",
        )

    @app.get("/api/game/never-have-i-ever/settings")
    def never_have_i_ever_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_never_have_i_ever_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/never-have-i-ever/settings")
    def set_never_have_i_ever_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = {
            "enabled",
            "signup_timeout_minutes",
            "statement_timeout_seconds",
            "response_timeout_seconds",
        }
        if set(request) != required:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_never_have_i_ever_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="never-have-i-ever-settings",
        )

    @app.get("/api/game/king-game/settings")
    def king_game_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_king_game_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/king-game/settings")
    def set_king_game_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = {"enabled", "king_phase_timeout_seconds"}
        if set(request) != required:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_king_game_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="king-game-settings",
        )

    @app.get("/api/game/never-have-i-ever/history")
    def never_have_i_ever_history(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        return _relay_core(
            lambda: core.list_never_have_i_ever_history(page, page_size)
        )

    @app.get("/api/game/red-packet/settings")
    def red_packet_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_red_packet_settings),
            "version": repository.config_version(),
        }

    @app.get("/api/game/texas-holdem/settings")
    def texas_holdem_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_texas_holdem_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/texas-holdem/settings")
    def set_texas_holdem_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = {
            "enabled",
            "minimum_players",
            "maximum_players",
            "minimum_buy_in",
            "maximum_buy_in",
            "daily_start_limit",
            "signup_timeout_seconds",
            "action_timeout_seconds",
            "small_blind_percent",
            "big_blind_percent",
        }
        if set(request) != required:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        integer_fields = required - {"enabled"}
        if not isinstance(request["enabled"], bool) or any(
            not isinstance(request[key], int) or isinstance(request[key], bool)
            for key in integer_fields
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        if not (
            2 <= request["minimum_players"] <= request["maximum_players"] <= 9
            and 1
            <= request["minimum_buy_in"]
            <= request["maximum_buy_in"]
            <= 99999
            and 1 <= request["daily_start_limit"] <= 100
            and 10 <= request["signup_timeout_seconds"] <= 3600
            and 10 <= request["action_timeout_seconds"] <= 3600
            and 1
            <= request["small_blind_percent"]
            < request["big_blind_percent"]
            <= 100
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_texas_holdem_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="texas-holdem-settings",
        )

    @app.get("/api/game/dark-market/settings")
    def dark_market_settings(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        settings = _relay_core(core.get_dark_market_settings)
        return {
            **settings,
            "settings_version": settings["version"],
            "version": repository.config_version(),
        }

    @app.patch("/api/game/dark-market/settings")
    def set_dark_market_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = {
            "enabled",
            "announcement_group_id",
            "duration_hours",
            "fee_percent",
            "disclosure_duration_value",
            "disclosure_duration_unit",
            "rank_limits",
        }
        if set(request) != required:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        rank_limits = request["rank_limits"]
        valid_rank_limits = (
            isinstance(rank_limits, list)
            and bool(rank_limits)
            and all(
                isinstance(item, dict)
                and set(item) == {"rank_id", "daily_limit"}
                and isinstance(item["rank_id"], str)
                and bool(item["rank_id"])
                and isinstance(item["daily_limit"], int)
                and not isinstance(item["daily_limit"], bool)
                and item["daily_limit"] >= -1
                for item in rank_limits
            )
            and len({item["rank_id"] for item in rank_limits})
            == len(rank_limits)
        )
        group_id = request["announcement_group_id"]
        disclosure_unit_minutes = {
            "minute": 1,
            "hour": 60,
            "day": 24 * 60,
        }
        disclosure_value = request["disclosure_duration_value"]
        disclosure_unit = request["disclosure_duration_unit"]
        if (
            not isinstance(request["enabled"], bool)
            or (
                group_id is not None
                and (not isinstance(group_id, str) or not group_id)
            )
            or (request["enabled"] and group_id is None)
            or not isinstance(request["duration_hours"], int)
            or isinstance(request["duration_hours"], bool)
            or not 1 <= request["duration_hours"] <= 24
            or not isinstance(request["fee_percent"], int)
            or isinstance(request["fee_percent"], bool)
            or not 1 <= request["fee_percent"] <= 100
            or not isinstance(disclosure_value, int)
            or isinstance(disclosure_value, bool)
            or disclosure_value < 1
            or disclosure_unit not in disclosure_unit_minutes
            or disclosure_value * disclosure_unit_minutes.get(disclosure_unit, 0)
            > 30 * 24 * 60
            or not valid_rank_limits
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )

        def update_settings() -> dict:
            current = _relay_core(core.get_dark_market_settings)
            return _relay_core(
                lambda: core.set_dark_market_settings(
                    {
                        **request,
                        "expected_version": current["version"],
                    }
                )
            )

        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            update_settings,
            scope="dark-market-settings",
        )

    @app.get("/api/game/dark-market/listings")
    def dark_market_listings(
        _: Annotated[None, Depends(authorize)],
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> dict:
        if status_filter not in {
            None,
            "active",
            "awaiting_receipt",
            "complaint_pending",
            "sold",
            "complained",
            "unsold",
            "force_delisted",
        }:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid status"
            )
        return _relay_core(
            lambda: core.list_dark_market_listings(
                status_filter, page, page_size
            )
        )

    @app.get("/api/game/dark-market/listings/{listing_id}")
    def dark_market_listing(
        listing_id: str,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return _relay_core(lambda: core.get_dark_market_listing(listing_id))

    @app.post("/api/game/dark-market/listings/{listing_id}/force-delist")
    def force_delist_dark_market_listing(
        listing_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.force_delist_dark_market_listing(listing_id)
            ),
            scope="dark-market-force-delist",
        )

    @app.post(
        "/api/game/dark-market/listings/{listing_id}/complaint/{decision}"
    )
    def review_dark_market_complaint(
        listing_id: str,
        decision: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        if decision not in {"approve", "reject"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown decision")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.review_dark_market_complaint(
                        listing_id,
                        decision == "approve",
                        identity.username,
                        beijing_now().isoformat(),
                    )
                ),
            ),
            scope=f"dark-market-complaint:{listing_id}:{decision}",
        )

    @app.patch("/api/game/red-packet/settings")
    def set_red_packet_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = {"expiry_minutes", "empty_probability_percent"}
        if set(request) != required:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        expiry_minutes = request["expiry_minutes"]
        empty_probability_percent = request["empty_probability_percent"]
        if (
            isinstance(expiry_minutes, bool)
            or not isinstance(expiry_minutes, int)
            or not 1 <= expiry_minutes <= 60
            or isinstance(empty_probability_percent, bool)
            or not isinstance(empty_probability_percent, int)
            or not 0 <= empty_probability_percent <= 30
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_red_packet_settings(
                    {
                        "expiry_minutes": expiry_minutes,
                        "empty_probability_percent": empty_probability_percent,
                    }
                )
            ),
            scope="red-packet-settings",
        )

    @app.get("/api/gameplay/current")
    def current_gameplay(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_current_gameplay),
            "version": repository.config_version(),
        }

    @app.get("/api/game/memory-assessment/guild/current")
    def memory_guild_current(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_memory_guild_current),
            "version": repository.config_version(),
        }

    @app.get("/api/game/memory-assessment/guild/history")
    def memory_guild_history(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        return _relay_core(
            lambda: core.list_memory_guild_history(page, page_size)
        )

    @app.get("/api/game/memory-assessment/guild/history/{match_id}")
    def memory_guild_detail(
        match_id: str,
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return _relay_core(lambda: core.get_memory_guild_detail(match_id))

    @app.post("/api/gameplay/{group_chat_id}/{game_type}/{game_id}/force-end")
    def force_end_gameplay(
        group_chat_id: str,
        game_type: str,
        game_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.force_end_gameplay(
                    group_chat_id, game_type, game_id
                )
            ),
            scope="force-end-gameplay",
        )

    @app.get("/api/ai-assistant/settings")
    def ai_assistant_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **_with_default_ai_memory_settings(_relay_core(core.get_ai_assistant_settings)),
            "version": repository.config_version(),
        }

    @app.patch("/api/ai-assistant/settings")
    def set_ai_assistant_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "enabled",
            "trigger_prefixes",
            "persona",
            "system_prompt",
            "over_limit_reply",
            "failure_reply",
            "max_response_chars",
            "timeout_seconds",
            "quotas",
            "memory_enabled",
            "extraction_prompt",
            "history_limit",
            "max_memory_chars",
            "batch_message_threshold",
            "max_entries_per_category",
            "candidate_expiry_days",
        )
        if (
            not all(key in request for key in required)
            or not isinstance(request["trigger_prefixes"], list)
            or not isinstance(request["quotas"], list)
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        settings = {key: request[key] for key in required}
        settings["quotas"] = [
            {"rank_id": quota["rank_id"], "daily_limit": quota["daily_limit"]}
            for quota in request["quotas"]
        ]
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.set_ai_assistant_settings(settings)),
            scope="ai-assistant-settings",
        )

    @app.get("/api/game/users/{platform_id}/ai-memory")
    def ai_player_memory(
        platform_id: str, _: Annotated[None, Depends(authorize)]
    ) -> dict:
        return _relay_core(lambda: core.get_ai_player_memory(platform_id))

    @app.get("/api/ai-knowledge-cards")
    def ai_knowledge_cards(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return {
            "items": _relay_core(core.list_ai_knowledge_cards),
            "version": repository.config_version(),
        }

    @app.post("/api/ai-knowledge-cards")
    def create_ai_knowledge_card(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity, idempotency_key, if_match,
            lambda: _relay_core(lambda: core.create_ai_knowledge_card(request)),
            scope="ai-knowledge-card:create",
        )

    @app.put("/api/ai-knowledge-cards/{card_id}")
    def update_ai_knowledge_card(
        card_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity, idempotency_key, if_match,
            lambda: _relay_core(lambda: core.update_ai_knowledge_card(card_id, request)),
            scope=f"ai-knowledge-card:{card_id}",
        )

    @app.delete("/api/ai-knowledge-cards/{card_id}")
    def delete_ai_knowledge_card(
        card_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity, idempotency_key, if_match,
            lambda: _relay_core(lambda: core.delete_ai_knowledge_card(card_id)),
            scope=f"ai-knowledge-card:{card_id}",
        )

    @app.post("/api/game/users/{platform_id}/ai-impressions")
    def create_ai_player_impression(
        platform_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        category = request.get("category")
        content = request.get("content")
        if not isinstance(category, str) or not isinstance(content, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid impression")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.create_ai_player_impression(
                platform_id, {"category": category, "content": content}
            )),
            scope=f"ai-player-impression:{platform_id}:new",
            status_code=201,
        )

    @app.put("/api/game/users/{platform_id}/ai-impressions/{entry_id}")
    def update_ai_player_impression(
        platform_id: str,
        entry_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        if (
            not isinstance(request.get("category"), str)
            or not isinstance(request.get("content"), str)
            or not isinstance(request.get("pinned"), bool)
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid impression")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.update_ai_player_impression(
                platform_id,
                entry_id,
                {
                    "category": request["category"],
                    "content": request["content"],
                    "pinned": request["pinned"],
                },
            )),
            scope=f"ai-player-impression:{platform_id}:{entry_id}",
        )

    @app.delete("/api/game/users/{platform_id}/ai-impressions/{entry_id}")
    def delete_ai_player_impression(
        platform_id: str,
        entry_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.delete_ai_player_impression(platform_id, entry_id)
            ),
            scope=f"ai-player-impression:{platform_id}:{entry_id}",
        )

    @app.delete("/api/game/users/{platform_id}/ai-memory")
    def clear_ai_player_memory(
        platform_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.clear_ai_player_memory(platform_id)),
            scope=f"ai-player-memory:{platform_id}",
        )

    @app.get("/api/game/activity-settings")
    def activity_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {**core.get_activity_settings(), "version": repository.config_version()}

    @app.patch("/api/game/activity-settings")
    def set_activity_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        if not isinstance(request.get("rules"), list) or not isinstance(
            request.get("report_times"), list
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.set_activity_settings({"rules": request["rules"], "report_times": request["report_times"]})),
            scope="activity-settings",
        )

    @app.get("/api/game/random-events/settings")
    def random_event_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **core.get_random_event_settings(),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/random-events/settings")
    def set_random_event_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "schedule_times",
            "signup_notice_template",
            "signup_timeout_minutes",
            "reminder_interval_minutes",
            "signup_allowed_commands",
            "in_progress_allowed_commands",
            "blocked_message",
        )
        optional = (
            "submission_enabled",
            "submission_draft_timeout_minutes",
            "submission_max_participants",
            "submission_default_target_rounds",
            "submission_default_event_reward",
            "submission_approval_reward",
            "tipping_duration_seconds",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_random_event_settings(
                    {
                        **{key: request[key] for key in required},
                        **{key: request[key] for key in optional if key in request},
                    }
                )
            ),
            scope="random-event-settings",
        )

    @app.get("/api/game/hide-and-seek/settings")
    def hide_and_seek_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **_relay_core(core.get_hide_and_seek_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/hide-and-seek/settings")
    def set_hide_and_seek_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "enabled",
            "entry_fee",
            "win_reward",
            "daily_limit",
            "selection_timeout_minutes",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_hide_and_seek_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="hide-and-seek-settings",
        )

    @app.get("/api/game/memory-assessment/settings")
    def memory_assessment_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **_relay_core(core.get_memory_assessment_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/memory-assessment/settings")
    def set_memory_assessment_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "enabled",
            "single_daily_limit",
            "single_recall_seconds",
            "single_answer_timeout_seconds",
            "single_decision_timeout_seconds",
            "duel_recall_seconds",
            "duel_difficulty_level",
            "duel_base_pool",
            "duel_wrong_freeze",
            "duel_wrong_limit",
            "duel_signup_timeout_minutes",
            "duel_answer_timeout_minutes",
            "character_set",
            "levels",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_memory_assessment_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="memory-assessment-settings",
        )

    @app.get("/api/game/undercover/settings")
    def undercover_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **_relay_core(core.get_undercover_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/undercover/settings")
    def set_undercover_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "enabled",
            "vote_seconds",
            "whiteboard_win_remaining",
            "signup_timeout_minutes",
            "roles",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_undercover_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="undercover-settings",
        )

    @app.get("/api/game/undercover/session")
    def undercover_session(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **_relay_core(core.get_undercover_session),
            "version": repository.config_version(),
        }

    @app.get("/api/game/blame-bomb/settings")
    def blame_bomb_settings(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            **_relay_core(core.get_blame_bomb_settings),
            "version": repository.config_version(),
        }

    @app.patch("/api/game/blame-bomb/settings")
    def set_blame_bomb_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "enabled",
            "signup_timeout_seconds",
            "turn_timeout_seconds",
            "durations",
        )
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid settings")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_blame_bomb_settings(
                    {key: request[key] for key in required}
                )
            ),
            scope="blame-bomb-settings",
        )

    @app.get("/api/game/blame-bomb/incidents")
    def blame_incidents(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return {
            **_relay_core(lambda: core.list_blame_incidents(page, page_size)),
            "version": repository.config_version(),
        }

    @app.post(
        "/api/game/blame-bomb/incidents",
        status_code=status.HTTP_201_CREATED,
    )
    def create_blame_incident(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = ("name", "description", "keywords")
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid incident")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.create_blame_incident(
                    {key: request[key] for key in required}
                )
            ),
            scope="blame-bomb-incidents",
            status_code=status.HTTP_201_CREATED,
        )

    @app.put("/api/game/blame-bomb/incidents/{incident_id}")
    def update_blame_incident(
        incident_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = ("name", "description", "keywords", "enabled")
        if not all(key in request for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid incident")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.update_blame_incident(
                    incident_id, {key: request[key] for key in required}
                )
            ),
            scope=f"blame-bomb-incident:{incident_id}",
        )

    @app.delete("/api/game/blame-bomb/incidents/{incident_id}")
    def delete_blame_incident(
        incident_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.delete_blame_incident(incident_id)),
            scope=f"blame-bomb-incident:{incident_id}",
        )

    @app.get("/api/game/blame-bomb/session")
    def blame_bomb_session(_: Annotated[None, Depends(authorize)]) -> dict:
        return _relay_core(core.get_blame_bomb_session)

    @app.post("/api/game/blame-bomb/end")
    def end_blame_bomb_session(
        _: Annotated[None, Depends(authorize)],
    ) -> dict:
        return _relay_core(core.end_blame_bomb_session)

    @app.get("/api/game/hide-and-seek/scenes")
    def hide_and_seek_scenes(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return {
            **_relay_core(lambda: core.list_hide_and_seek_scenes(page, page_size)),
            "version": repository.config_version(),
        }

    @app.post("/api/game/hide-and-seek/scenes", status_code=status.HTTP_201_CREATED)
    def create_hide_and_seek_scene(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        if not isinstance(request.get("name"), str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid scene")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.create_hide_and_seek_scene({"name": request["name"]})
            ),
            scope="hide-and-seek-scenes",
            status_code=status.HTTP_201_CREATED,
        )

    @app.put("/api/game/hide-and-seek/scenes/{scene_id}")
    def update_hide_and_seek_scene(
        scene_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        if not isinstance(request.get("name"), str) or not isinstance(
            request.get("enabled"), bool
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid scene")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.update_hide_and_seek_scene(
                    scene_id, {"name": request["name"], "enabled": request["enabled"]}
                )
            ),
            scope=f"hide-and-seek-scene:{scene_id}",
        )

    @app.delete("/api/game/hide-and-seek/scenes/{scene_id}")
    def delete_hide_and_seek_scene(
        scene_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.delete_hide_and_seek_scene(scene_id)),
            scope=f"hide-and-seek-scene:{scene_id}",
        )

    @app.get("/api/game/performances")
    def performances(
        _: Annotated[AdminIdentity, Depends(authorize)],
        state_filter: str | None = Query(default=None, alias="state"),
    ) -> dict:
        return {
            "items": _relay_core(
                lambda: core.list_performances(state_filter)
            ),
            "version": repository.config_version(),
        }

    @app.get("/api/game/performances/settings")
    def performance_settings(
        _: Annotated[AdminIdentity, Depends(authorize)],
    ) -> dict:
        return {
            **_relay_core(core.get_performance_settings),
            "version": repository.config_version(),
        }

    @app.get("/api/game/performances/{performance_id}/messages")
    def performance_messages(
        performance_id: str,
        _: Annotated[AdminIdentity, Depends(authorize)],
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        return _relay_core(
            lambda: core.list_performance_messages(
                performance_id, page, page_size
            )
        )

    @app.patch("/api/game/performances/settings")
    def update_performance_settings(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        value = request.get("maximum_duration_minutes")
        if isinstance(value, bool) or not isinstance(value, int):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid performance settings"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.set_performance_settings(
                    {"maximum_duration_minutes": value}
                )
            ),
            scope="performance-settings",
        )

    @app.post("/api/game/performances/{performance_id}/approve")
    def approve_performance(
        performance_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.approve_performance(
                        performance_id,
                        identity.username,
                        beijing_now().isoformat(),
                    )
                ),
            ),
            scope=f"performance:{performance_id}:approve",
        )

    @app.post("/api/game/performances/{performance_id}/reject")
    def reject_performance(
        performance_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "拒绝原因不能为空")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.reject_performance(
                        performance_id,
                        identity.username,
                        reason.strip(),
                        beijing_now().isoformat(),
                    )
                ),
            ),
            scope=f"performance:{performance_id}:reject",
        )

    @app.post("/api/game/performances/{performance_id}/cancel")
    def cancel_performance(
        performance_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "取消原因不能为空")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.cancel_performance(
                        performance_id,
                        identity.username,
                        reason.strip(),
                        beijing_now().isoformat(),
                        force=identity.role == "super_admin",
                    )
                ),
            ),
            scope=f"performance:{performance_id}:cancel",
        )

    @app.post("/api/game/performance-extensions/{request_id}/{decision}")
    def review_performance_extension(
        request_id: str,
        decision: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[
            str | None, Header(alias="Idempotency-Key")
        ] = None,
    ) -> JSONResponse:
        if decision not in {"approve", "reject"}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown decision")
        reason = request.get("reason")
        if decision == "reject" and (
            not isinstance(reason, str) or not reason.strip()
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "拒绝原因不能为空")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.review_performance_extension(
                        request_id,
                        decision == "approve",
                        identity.username,
                        reason.strip() if isinstance(reason, str) else None,
                        beijing_now().isoformat(),
                        identity.role == "super_admin",
                    )
                ),
            ),
            scope=f"performance-extension:{request_id}:{decision}",
        )

    @app.get("/api/game/random-events/submissions")
    def random_event_submissions(
        _: Annotated[AdminIdentity, Depends(authorize)],
        status_filter: str | None = Query(None, alias="status"),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return _relay_core(
            lambda: core.list_random_event_submissions(
                status_filter, page, page_size
            )
        )

    @app.get("/api/game/random-events/submissions/{submission_id}")
    def random_event_submission(
        submission_id: str,
        _: Annotated[AdminIdentity, Depends(authorize)],
    ) -> dict:
        return _relay_core(lambda: core.random_event_submission(submission_id))

    @app.patch("/api/game/random-events/submissions/{submission_id}")
    def update_random_event_submission(
        submission_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        content = request.get("content")
        if not isinstance(content, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "投稿内容无效")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.update_random_event_submission(
                        submission_id, content, beijing_now().isoformat()
                    )
                ),
            ),
            scope=f"random-event-submission:{submission_id}:edit",
        )

    @app.post("/api/game/random-events/submissions/{submission_id}/approve")
    def approve_random_event_submission(
        submission_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.approve_random_event_submission(
                        submission_id, identity.username, beijing_now().isoformat()
                    )
                ),
            ),
            scope=f"random-event-submission:{submission_id}:approve",
        )

    @app.post("/api/game/random-events/submissions/{submission_id}/reject")
    def reject_random_event_submission(
        submission_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        reason = request.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "拒绝原因不能为空")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (
                200,
                _relay_core(
                    lambda: core.reject_random_event_submission(
                        submission_id,
                        identity.username,
                        reason,
                        beijing_now().isoformat(),
                    )
                ),
            ),
            scope=f"random-event-submission:{submission_id}:reject",
        )

    @app.get("/api/game/random-events/scenes")
    def random_event_scenes(
        _: Annotated[None, Depends(authorize)],
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        return {
            **core.list_random_event_scenes(page, page_size),
            "version": repository.config_version(),
        }

    @app.post("/api/game/random-events/scenes", status_code=status.HTTP_201_CREATED)
    async def create_random_event_scene(
        request: Request,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        try:
            scene = await request.json()
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid scene")
        if not isinstance(scene, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "场景数据格式无效")
        required = ("name", "signup_text", "reward", "target_rounds", "seats")
        missing = [key for key in required if key not in scene]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"缺少场景字段：{'、'.join(missing)}",
            )
        if not isinstance(scene.get("events", scene.get("openings")), list):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "事件模板必须是列表"
            )
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.create_random_event_scene(
                    {key: scene[key] for key in required}
                    | {"events": scene["events"]}
                    if "events" in scene
                    else {key: scene[key] for key in (*required, "openings")}
                )
            ),
            scope="random-event-scenes",
            status_code=status.HTTP_201_CREATED,
        )

    @app.put("/api/game/random-events/scenes/{scene_id}")
    def update_random_event_scene(
        scene_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = (
            "name",
            "signup_text",
            "reward",
            "target_rounds",
            "seats",
            "enabled",
        )
        if (
            not all(key in request for key in required)
            or not isinstance(request.get("events", request.get("openings")), list)
        ):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid scene")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.update_random_event_scene(
                    scene_id,
                    {key: request[key] for key in required}
                    | {"events": request["events"]}
                    if "events" in request
                    else {key: request[key] for key in (*required, "openings")},
                )
            ),
            scope=f"random-event-scene:{scene_id}",
        )

    @app.delete("/api/game/random-events/scenes/{scene_id}")
    def delete_random_event_scene(
        scene_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.delete_random_event_scene(scene_id)),
            scope=f"random-event-scene:{scene_id}",
        )

    @app.get("/api/game/random-events/today")
    def today_random_events(_: Annotated[None, Depends(authorize)]) -> dict:
        return {
            "items": core.list_today_random_events(),
            "version": repository.config_version(),
        }

    @app.get("/api/game/random-events/history")
    def random_event_history(
        _: Annotated[None, Depends(authorize)],
        status_filter: Annotated[str | None, Query(alias="status")] = None,
        group_chat_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
    ) -> dict:
        if status_filter not in {
            None,
            "ended",
            "dissolved",
            "skipped",
            "cancelled",
        }:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid status"
            )
        return _relay_core(
            lambda: core.list_random_event_history(
                status_filter,
                group_chat_id,
                start_date,
                end_date,
                page,
                page_size,
            )
        )

    @app.patch("/api/game/random-events/today/{schedule_id}")
    def reschedule_random_event(
        schedule_id: str,
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        scheduled_at = request.get("scheduled_at")
        if not isinstance(scheduled_at, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid schedule")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.reschedule_random_event(schedule_id, scheduled_at)
            ),
            scope=f"random-event-schedule:{schedule_id}",
        )

    @app.post("/api/game/random-events/today")
    def create_today_random_event(
        request: dict,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        required = ("scene_id", "event_name", "scheduled_at")
        if not all(isinstance(request.get(key), str) and request[key] for key in required):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid schedule")
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(
                lambda: core.create_today_random_event(
                    {key: request[key] for key in required}
                )
            ),
            scope="random-event-schedules",
        )

    @app.delete("/api/game/random-events/today/{schedule_id}")
    def delete_today_random_event(
        schedule_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.delete_today_random_event(schedule_id)),
            scope=f"random-event-schedule:{schedule_id}",
        )

    @app.post("/api/game/random-events/today/{schedule_id}/trigger")
    def trigger_random_event(
        schedule_id: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    ) -> JSONResponse:
        return versioned_configuration_response(
            identity,
            idempotency_key,
            if_match,
            lambda: _relay_core(lambda: core.trigger_random_event(schedule_id)),
            scope=f"random-event-schedule:{schedule_id}:trigger",
        )

    @app.get("/api/game/random-events/today/{schedule_id}/details")
    def random_event_details(
        schedule_id: str, _: Annotated[None, Depends(authorize)]
    ) -> dict:
        return _relay_core(lambda: core.random_event_details(schedule_id))

    @app.post("/api/session", status_code=status.HTTP_204_NO_CONTENT)
    def create_console_session(
        response: Response, identity: Annotated[AdminIdentity, Depends(authorize)]
    ) -> None:
        nonlocal console_session
        lease = core.get_manual_login_lease()
        if lease is None or lease["operator_id"] != _actor_id(identity):
            raise HTTPException(status.HTTP_409_CONFLICT, "manual login is not owned by actor")
        console_session = (token_urlsafe(32), _actor_id(identity))
        response.set_cookie(
            "dzmm_admin_session",
            console_session[0],
            httponly=True,
            max_age=900,
            path="/login-console",
            samesite="strict",
        )

    @app.post("/api/worker/{action}", status_code=status.HTTP_202_ACCEPTED)
    def worker_action(
        action: str,
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        command = _WORKER_COMMANDS.get(action)
        if command is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown action")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (202, core.enqueue_command(command)),
            scope=f"worker:{action}",
        )

    @app.get("/api/login/lease")
    def login_lease(
        _: Annotated[AdminIdentity, Depends(authorize)],
    ) -> dict | None:
        return core.get_manual_login_lease()

    @app.post("/api/login/start", status_code=status.HTTP_202_ACCEPTED)
    def login_start(
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        _require_verification(core)
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (202, _relay_core(lambda: core.start_manual_login(_actor_id(identity), identity.username))),
            scope="manual-login:start",
        )

    @app.post("/api/login/finish", status_code=status.HTTP_202_ACCEPTED)
    def login_finish(
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        _require_login_state(core, "auth_in_progress")
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (202, _relay_core(lambda: core.finish_manual_login(_actor_id(identity), identity.username))),
            scope="manual-login:finish",
        )

    @app.post("/api/login/cancel", status_code=status.HTTP_202_ACCEPTED)
    def login_cancel(
        identity: Annotated[AdminIdentity, Depends(authorize)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JSONResponse:
        return idempotent_response(
            identity,
            idempotency_key,
            lambda: (202, _relay_core(core.cancel_manual_login)),
            scope="manual-login:cancel",
        )

    @app.get("/login-console")
    def login_console(
        dzmm_admin_session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        _authorize_console(core, console_session, dzmm_admin_session)
        _require_login_state(core, "auth_in_progress")
        return RedirectResponse(_CONSOLE_URL, status_code=307)

    @app.get("/login-console/")
    def login_console_index(
        request: Request,
        dzmm_admin_session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        _authorize_console(core, console_session, dzmm_admin_session)
        _require_login_state(core, "auth_in_progress")
        if request.query_params.getlist("path") != [_CONSOLE_PATH]:
            return RedirectResponse(_CONSOLE_URL, status_code=307)
        return _proxy_console_asset(console, "/vnc.html")

    @app.get("/login-console/{asset_path:path}")
    def login_console_asset(
        asset_path: str,
        dzmm_admin_session: Annotated[str | None, Cookie()] = None,
    ) -> Response:
        _authorize_console(core, console_session, dzmm_admin_session)
        _require_login_state(core, "auth_in_progress")
        if not asset_path or ".." in asset_path.split("/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "asset not found")
        return _proxy_console_asset(console, f"/{asset_path}")

    @app.websocket("/login-console/websockify")
    async def login_console_websocket(websocket: WebSocket) -> None:
        if not _console_session_is_active(
            core, console_session, websocket.cookies.get("dzmm_admin_session")
        ):
            await websocket.close(code=4401)
            return
        if core.login_state() != "auth_in_progress":
            await websocket.close(code=4409)
            return
        offered_protocols = [
            protocol.strip()
            for protocol in websocket.headers.get(
                "sec-websocket-protocol", ""
            ).split(",")
            if protocol.strip()
        ]
        async with connect_websocket(
            "/websockify", subprotocols=offered_protocols or None
        ) as upstream:
            await websocket.accept(
                subprotocol=getattr(upstream, "subprotocol", None)
            )
            downstream = asyncio.create_task(
                _relay_to_upstream(websocket, upstream)
            )
            upstream_task = asyncio.create_task(
                _relay_to_browser(upstream, websocket)
            )
            done, pending = await asyncio.wait(
                (downstream, upstream_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)

    return app


def _require_login_state(core: AdminCorePort, expected: str) -> None:
    if core.login_state() != expected:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"login state must be {expected}",
        )


def _require_verification(core: AdminCorePort) -> None:
    if core.login_state() == "auth_required":
        return
    status_payload = core.status()
    if status_payload.get("bot_delivery_state") != "captcha_required":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "platform verification is not required",
        )


def _actor_id(identity: AdminIdentity) -> str:
    return "super_admin" if identity.account_id is None else str(identity.account_id)


def _relay_core(operation: Callable[[], dict]) -> dict:
    try:
        return operation()
    except HTTPStatusError as error:
        raise HTTPException(error.response.status_code, error.response.text)


def _account_response(account) -> dict:
    return {"id": str(account.id), "username": account.username, "active": account.active}


def _authorize_console(
    core: AdminCorePort,
    active_session: tuple[str, str] | None,
    supplied_session: str | None,
) -> None:
    if not _console_session_is_active(core, active_session, supplied_session):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unauthorized")


def _console_session_is_active(
    core: AdminCorePort,
    active_session: tuple[str, str] | None,
    supplied_session: str | None,
) -> bool:
    if active_session is None or supplied_session is None:
        return False
    token, operator_id = active_session
    lease = core.get_manual_login_lease()
    return (
        lease is not None
        and lease["operator_id"] == operator_id
        and compare_digest(token, supplied_session)
    )


def _proxy_console_asset(console: NoVNCClient, path: str) -> Response:
    upstream = console.get(path)
    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        status_code=upstream.status_code,
    )


async def _relay_to_upstream(websocket: WebSocket, upstream) -> None:
    while True:
        event = await websocket.receive()
        if event["type"] == "websocket.disconnect":
            return
        data = event.get("bytes")
        if data is None:
            data = event.get("text")
        if data is not None:
            await upstream.send(data)


async def _relay_to_browser(upstream, websocket: WebSocket) -> None:
    async for data in upstream:
        if isinstance(data, bytes):
            await websocket.send_bytes(data)
        else:
            await websocket.send_text(data)
