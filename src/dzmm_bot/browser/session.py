from datetime import datetime
from pathlib import Path
from time import time
from typing import Callable, Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dzmm_bot.runtime.contracts import (
    DirectChatRoom,
    GroupChatTarget,
    InboundMessage,
    LoginState,
    MessageReference,
)
from dzmm_bot.dzmm_source import DzmmMessageSource

from .aikda_socket import AikdaSocketGateway


class ChatGateway(Protocol):
    def configure_group_rooms(
        self, targets: tuple[GroupChatTarget, ...]
    ) -> None: ...

    def group_room_states(self) -> dict[str, tuple[str, str | None]]: ...

    def read_new(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[InboundMessage]: ...

    def reconcile_history(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[InboundMessage]: ...

    def maintain_direct_chats(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[DirectChatRoom]: ...

    def send(
        self, text: str, *, message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str: ...

    def send_to(
        self, chatroom_id: str, text: str, *, message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str: ...

    def send_image(
        self, image_url: str, *, alt: str = "image", message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str: ...

    def send_image_to(
        self, chatroom_id: str, image_url: str, *, alt: str = "image",
        message_id: str | None = None, reference: MessageReference | None = None,
    ) -> str: ...

    def upload_image(self, path: Path, mime_type: str) -> dict: ...

    def discover_direct_chats(self) -> list[DirectChatRoom]: ...

    def retract(self, message_id: str) -> None: ...

    def is_authenticated(self) -> bool: ...

    def close(self) -> None: ...


class BrowserSession:
    def __init__(
        self,
        profile_path: Path,
        login_url: str | None,
        *,
        chat_url: str | None = None,
        cdp_port: int = 19222,
        playwright_factory: Callable | None = None,
        socket_factory: Callable | None = None,
    ) -> None:
        if cdp_port != 19222:
            raise ValueError("browser CDP port must be the isolated port 19222")
        self.profile_path = profile_path
        self.login_url = login_url
        self.chat_url = chat_url
        self.cdp_port = cdp_port
        self._playwright_factory = playwright_factory or _start_playwright
        self._socket_factory = socket_factory
        self._playwright = None
        self._context = None
        self._gateway = None
        self._attached = False
        self._group_targets: tuple[GroupChatTarget, ...] = ()
        self._group_targets_configured = False

    def configure_group_chats(
        self, targets: tuple[GroupChatTarget, ...]
    ) -> None:
        self._group_targets = targets
        self._group_targets_configured = True
        if targets and self.chat_url is None:
            self.chat_url = targets[0].chat_url
        if self._gateway is not None:
            self._gateway.configure_group_rooms(targets)

    def attach_existing(self) -> ChatGateway:
        if self._gateway is not None:
            return self._gateway
        self._playwright = self._playwright_factory()
        browser = self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{self.cdp_port}"
        )
        self._context = browser.contexts[0]
        self._attached = True
        self._gateway = self._new_gateway()
        if self._group_targets_configured:
            self._gateway.configure_group_rooms(self._group_targets)
        self._open_group_chat()
        return self._gateway

    def start_headless(self) -> ChatGateway:
        if self._gateway is not None:
            return self._gateway
        self.profile_path.mkdir(parents=True, exist_ok=True)
        self._playwright = self._playwright_factory()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_path),
            headless=True,
            args=[
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={self.cdp_port}",
                "--restore-last-session",
            ],
        )
        page = next(
            (
                restored
                for restored in self._context.pages
                if restored.url != "about:blank"
            ),
            self._context.pages[0],
        )
        if self.login_url and page.url == "about:blank":
            page.goto(self.login_url)
        self._gateway = self._new_gateway()
        if self._group_targets_configured:
            self._gateway.configure_group_rooms(self._group_targets)
        self._open_group_chat()
        return self._gateway

    def _open_group_chat(self) -> None:
        if self.chat_url is None or self._gateway is None:
            return
        if not self._page_is_authenticated():
            return
        page = self._active_page()
        if page.url != self.chat_url:
            page.goto(self.chat_url)

    def _new_gateway(self) -> ChatGateway:
        if self.chat_url is None:
            return _PlaywrightGateway(self._context, self.login_url)
        return AikdaSocketGateway(
            self.chat_url,
            token_provider=self._token,
            request=self._request,
            upload=self._upload_image,
            cookie_provider=self._cookies,
            socket_factory=self._socket_factory,
        )

    def _token(self) -> str:
        return self._active_page().evaluate(_TOKEN_SCRIPT)

    def _request(self, procedure: str, payload: dict | None = None) -> dict:
        return self._active_page().evaluate(
            _TRPC_SCRIPT,
            {"procedure": procedure, "payload": payload},
        )

    def _upload_image(
        self, path: Path, mime_type: str, chatroom_id: str
    ) -> dict:
        response = self._context.request.post(
            f"{_origin(self.chat_url)}/api/trpc/chatroom.uploadImage",
            multipart={
                "file": {
                    "name": path.name,
                    "mimeType": mime_type,
                    "buffer": path.read_bytes(),
                },
                "chatroomId": chatroom_id,
            },
        )
        if not response.ok:
            raise RuntimeError("Aikda image upload failed")
        body = response.json()
        return body.get("result", {}).get("data", {}).get("json", body)

    def _cookies(self) -> str:
        origin = _origin(self.chat_url)
        cookies = self._context.cookies([origin])
        return "; ".join(
            f"{cookie['name']}={cookie['value']}"
            for cookie in cookies
            if cookie.get("name") and cookie.get("value")
        )

    def _active_page(self):
        return next(
            (page for page in self._context.pages if "/chat" in page.url),
            self._context.pages[0],
        )

    def _page_is_authenticated(self) -> bool:
        if not self._context.pages or self.login_url is None:
            return False
        return _location(self._active_page().url) != _location(self.login_url)

    def stop(self) -> None:
        if self._gateway is not None and self.chat_url is not None:
            self._gateway.close()
        if self._context is not None and not self._attached:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._gateway = None
        self._context = None
        self._attached = False
        self._playwright = None

    def login_state(self) -> LoginState:
        if self._gateway is None:
            return LoginState.AUTH_REQUIRED
        return (
            LoginState.READY
            if self._gateway.is_authenticated()
            else LoginState.AUTH_REQUIRED
        )


class _PlaywrightGateway:
    def __init__(self, context, login_url: str | None) -> None:
        self._context = context
        self._login_url = login_url

    def configure_group_rooms(
        self, targets: tuple[GroupChatTarget, ...]
    ) -> None:
        if len(targets) > 1:
            raise NotImplementedError("multiple groups require the Aikda socket gateway")

    def group_room_states(self) -> dict[str, tuple[str, str | None]]:
        return {}

    def read_new(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[InboundMessage]:
        page = self._active_page()
        return [
            InboundMessage(
                message.message_id,
                message.sender,
                message.text,
                datetime.now(ZoneInfo("Asia/Shanghai")),
            )
            for message in DzmmMessageSource(page).read_new()
        ]

    def reconcile_history(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[InboundMessage]:
        return self.read_new(direct_chatroom_ids)

    def maintain_direct_chats(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[DirectChatRoom]:
        raise NotImplementedError("direct messages require the Aikda socket gateway")

    def send(
        self, text: str, *, message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str:
        page = self._active_page()
        editor = page.locator("textarea, [contenteditable='true']").last
        editor.fill(text)
        editor.press("Enter")
        return f"dzmm:{int(time() * 1000)}"

    def send_to(
        self, chatroom_id: str, text: str, *, message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str:
        raise NotImplementedError("direct messages require the Aikda socket gateway")

    def send_image(
        self, image_url: str, *, alt: str = "image", message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str:
        raise NotImplementedError("images require the Aikda socket gateway")

    def send_image_to(
        self, chatroom_id: str, image_url: str, *, alt: str = "image",
        message_id: str | None = None, reference: MessageReference | None = None,
    ) -> str:
        raise NotImplementedError("images require the Aikda socket gateway")

    def upload_image(self, path: Path, mime_type: str) -> dict:
        raise NotImplementedError("image upload requires the Aikda socket gateway")

    def discover_direct_chats(self) -> list[DirectChatRoom]:
        raise NotImplementedError("direct messages require the Aikda socket gateway")

    def retract(self, message_id: str) -> None:
        raise NotImplementedError("message retraction requires the Aikda socket gateway")

    def _active_page(self):
        return next((page for page in self._context.pages if "/chat" in page.url), self._context.pages[0])

    def is_authenticated(self) -> bool:
        if not self._context.pages:
            return False
        if self._login_url is None:
            return False
        return _location(self._context.pages[0].url) != _location(self._login_url)

    def close(self) -> None:
        self._context.close()


def _location(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.netloc, parsed.path.rstrip("/")


def _origin(url: str | None) -> str:
    if url is None:
        raise ValueError("chat URL is required for socket authentication")
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _start_playwright():
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


_TOKEN_SCRIPT = """async () => {
  const response = await fetch('/api/auth/token');
  const body = await response.json();
  if (!response.ok || !body.access_token) {
    throw new Error('Aikda access token unavailable');
  }
  return body.access_token;
}"""


_TRPC_SCRIPT = """async ({ procedure, payload }) => {
  const input = { json: payload ?? null };
  const response = await fetch(
    `/api/trpc/${procedure}?input=${encodeURIComponent(JSON.stringify(input))}`
  );
  const body = await response.json();
  if (!response.ok) {
    throw new Error(`Aikda ${procedure} request failed`);
  }
  return body?.result?.data?.json ?? body?.json ?? body?.[0]?.result?.data?.json;
}"""
