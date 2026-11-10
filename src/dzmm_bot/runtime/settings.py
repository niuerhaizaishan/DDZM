import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    core_token: str
    admin_token: str | None
    browser_profile: Path
    login_url: str | None
    core_api_port: int
    browser_cdp_port: int
    admin_web_port: int
    novnc_port: int
    outbound_concurrency: int = 4
    chat_url: str | None = None
    bot_api_token: str | None = None
    long_message_bot_id: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    integration_api_key: str | None = None
    chess_game_id: str | None = None
    chess_token_audience: str | None = None
    chess_allow_uid: bool = False
    chess_game_url: str | None = None
    chess_public_api_url: str | None = None
    chess_test_chatroom_id: str | None = None
    doudizhu_game_id: str | None = None
    doudizhu_game_url: str | None = None
    doudizhu_public_api_url: str | None = None
    doudizhu_chatroom_id: str | None = None
    mistrealm_enabled: bool = False
    drawguess_game_id: str | None = None
    drawguess_game_url: str | None = None
    drawguess_public_api_url: str | None = None
    drawguess_chatroom_id: str | None = None
    club_game_id: str | None = None
    club_game_url: str | None = None
    club_public_api_url: str | None = None
    club_chatroom_id: str | None = None
    workstation_public_url: str | None = None
    gamefy_game_id: str | None = None
    workstation_game_url: str | None = None

    @classmethod
    def from_environment(cls) -> "Settings":
        from dzmm_bot.core.workstation import normalize_workstation_game_url, normalize_workstation_public_url

        database_url = _required("DZMM_DATABASE_URL")
        core_token = _required("DZMM_CORE_TOKEN")
        admin_token = _optional("DZMM_ADMIN_TOKEN")
        browser_profile = Path(os.environ.get("DZMM_BROWSER_PROFILE", "/var/lib/dzmm/browser"))
        if not browser_profile.is_absolute():
            raise ValueError("DZMM_BROWSER_PROFILE must be an absolute path")

        return cls(
            database_url=database_url,
            core_token=core_token,
            admin_token=admin_token,
            browser_profile=browser_profile,
            login_url=_optional("DZMM_LOGIN_URL", empty_as_none=True),
            core_api_port=_port("DZMM_CORE_API_PORT", 18120),
            browser_cdp_port=_port("DZMM_BROWSER_CDP_PORT", 19222),
            admin_web_port=_port("DZMM_ADMIN_WEB_PORT", 18090),
            novnc_port=_port("DZMM_NOVNC_PORT", 16080),
            outbound_concurrency=_bounded_int(
                "DZMM_OUTBOUND_CONCURRENCY", 4, minimum=1, maximum=16
            ),
            chat_url=_optional("DZMM_CHAT_URL", empty_as_none=True),
            bot_api_token=_optional("DZMM_BOT_API_TOKEN", empty_as_none=True),
            long_message_bot_id=_optional("DZMM_BOT_ID", empty_as_none=True),
            deepseek_api_key=_optional("DP_API_KEY", empty_as_none=True),
            deepseek_model=os.environ.get(
                "DZMM_DEEPSEEK_MODEL", "deepseek-v4-flash"
            ),
            deepseek_base_url=os.environ.get(
                "DZMM_DEEPSEEK_BASE_URL", "https://api.deepseek.com"
            ),
            integration_api_key=_optional("DZMM_INTEGRATION_API_KEY"),
            chess_game_id=_optional("DZMM_CHESS_GAME_ID", empty_as_none=True),
            chess_token_audience=_optional("DZMM_CHESS_TOKEN_AUDIENCE", empty_as_none=True),
            chess_allow_uid=os.environ.get("DZMM_CHESS_ALLOW_UID", "false").lower() == "true",
            chess_game_url=_optional("DZMM_CHESS_GAME_URL", empty_as_none=True),
            chess_public_api_url=_optional("DZMM_CHESS_PUBLIC_API_URL", empty_as_none=True),
            chess_test_chatroom_id=_optional("DZMM_CHESS_TEST_CHATROOM_ID", empty_as_none=True),
            doudizhu_game_id=_optional("DZMM_DOUDIZHU_GAME_ID", empty_as_none=True),
            doudizhu_game_url=_optional("DZMM_DOUDIZHU_GAME_URL", empty_as_none=True),
            doudizhu_public_api_url=_optional("DZMM_DOUDIZHU_PUBLIC_API_URL", empty_as_none=True),
            doudizhu_chatroom_id=_optional("DZMM_DOUDIZHU_CHATROOM_ID", empty_as_none=True),
            mistrealm_enabled=os.environ.get("DZMM_MISTREALM_ENABLED", "false").lower() == "true",
            drawguess_game_id=_optional("DZMM_DRAWGUESS_GAME_ID", empty_as_none=True),
            drawguess_game_url=_optional("DZMM_DRAWGUESS_GAME_URL", empty_as_none=True),
            drawguess_public_api_url=_optional("DZMM_DRAWGUESS_PUBLIC_API_URL", empty_as_none=True),
            drawguess_chatroom_id=_optional("DZMM_DRAWGUESS_CHATROOM_ID", empty_as_none=True),
            club_game_id=_optional("DZMM_CLUB_GAME_ID", empty_as_none=True),
            club_game_url=_optional("DZMM_CLUB_GAME_URL", empty_as_none=True),
            club_public_api_url=_optional("DZMM_CLUB_PUBLIC_API_URL", empty_as_none=True),
            club_chatroom_id=_optional("DZMM_CLUB_CHATROOM_ID", empty_as_none=True),
            workstation_public_url=normalize_workstation_public_url(
                _optional("DZMM_WORKSTATION_PUBLIC_URL", empty_as_none=True)
            ),
            gamefy_game_id=_optional("DZMM_GAMEFY_GAME_ID", empty_as_none=True),
            workstation_game_url=normalize_workstation_game_url(
                _optional("DZMM_WORKSTATION_GAME_URL", empty_as_none=True)
            ),
        )


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"{name} must be set and nonempty")
    return value


def _optional(name: str, *, empty_as_none: bool = False) -> str | None:
    value = os.environ.get(name)
    if value == "":
        if empty_as_none:
            return None
        raise ValueError(f"{name} must be nonempty when set")
    return value


def _port(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError as error:
        raise ValueError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value
