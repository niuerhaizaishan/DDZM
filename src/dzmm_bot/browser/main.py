import os
from random import uniform
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
from time import sleep

from dzmm_bot.auth_desktop import AuthDesktopController
from dzmm_bot.runtime.settings import Settings

from .bot_api import DzmmBotSender
from .core_client import CoreClient
from .session import BrowserSession
from .shadow_sync import ShadowSyncRunner
from .worker import BrowserWorker


def main() -> None:
    settings = Settings.from_environment()
    worker = create_worker(settings)
    while True:
        worker.run_once()
        sleep(1)


def create_worker(settings: Settings) -> BrowserWorker:
    session = BrowserSession(
        settings.browser_profile,
        settings.login_url,
        chat_url=settings.chat_url,
        cdp_port=settings.browser_cdp_port,
    )
    worker: BrowserWorker
    desktop = AuthDesktopController(
        runtime_dir=Path("/var/lib/dzmm-browser/runtime"),
        profile_dir=settings.browser_profile,
        login_url=settings.login_url,
        login_state=lambda: worker.login_state.value,
        browser_stopped=lambda: worker.browser_stopped,
        browser_executable=_playwright_chromium_executable(),
        novnc_port=settings.novnc_port,
    )
    bot_sender = DzmmBotSender(settings.bot_api_token) if settings.bot_api_token else None
    worker = BrowserWorker(
        worker_id=os.environ.get("DZMM_WORKER_ID", "browser-worker-1"),
        core=CoreClient(
            f"http://127.0.0.1:{settings.core_api_port}", settings.core_token
        ),
        session=session,
        desktop=desktop,
        clock=lambda: datetime.now(ZoneInfo("Asia/Shanghai")),
        bot_sender=bot_sender,
        outbound_concurrency=settings.outbound_concurrency,
        shadow_runner=ShadowSyncRunner(),
        shadow_jitter=lambda: uniform(-5, 5),
    )
    return worker


def _playwright_chromium_executable() -> str:
    executables = sorted(
        Path.home().glob(
            ".cache/ms-playwright/chromium-*/chrome-linux64/chrome"
        )
    )
    if not executables:
        raise RuntimeError("Playwright Chromium is not installed")
    return str(executables[-1])


if __name__ == "__main__":
    main()
