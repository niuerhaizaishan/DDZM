import json
from pathlib import Path
import subprocess

import pytest

from dzmm_bot.browser.aikda_socket import (
    AikdaAuthenticationError,
    AikdaTransportError,
)
from dzmm_bot.browser.session import BrowserSession
from dzmm_bot.browser import session as session_module
from dzmm_bot.runtime.contracts import LoginState


class FakePage:
    def __init__(self, url, rows=None):
        self.url = url
        self.rows = rows or []
        self.filled = []
        self.pressed = []

    def goto(self, url):
        self.url = url

    def evaluate(self, _script, _selectors):
        return self.rows

    def locator(self, _selector):
        return self

    @property
    def last(self):
        return self

    def fill(self, text):
        self.filled.append(text)

    def press(self, key):
        self.pressed.append(key)


class NodePage(FakePage):
    def evaluate(self, script, argument):
        program = f"""
const request = eval({json.dumps(f"({script})")});
const keepAlive = setInterval(() => {{}}, 1000);
global.fetch = (_url, options) => new Promise((_resolve, reject) => {{
  options?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
}});
request({json.dumps(argument)})
  .then(() => {{ clearInterval(keepAlive); process.exit(0); }})
  .catch((error) => {{
    clearInterval(keepAlive);
    console.error(error.message);
    process.exit(2);
  }});
"""
        result = subprocess.run(
            ["node", "-e", program],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip())
        return None


class FakeSocket:
    def __init__(self):
        self.handlers = {}
        self.connected = False
        self.connect_calls = []
        self.calls = []

    def on(self, event, handler):
        self.handlers[event] = handler

    def connect(self, origin, **kwargs):
        self.connect_calls.append((origin, kwargs))
        self.connected = True
        self.handlers["message:joined"]({"syncMode": "http"})

    def call(self, event, payload, timeout):
        self.calls.append((event, payload, timeout))
        return {"success": True}

    def disconnect(self):
        self.connected = False


class FakeContext:
    def __init__(self, url, cookies=None):
        self.pages = [FakePage(url)]
        self._cookies = cookies or []
        self.closed = False

    def cookies(self, _urls=None):
        return self._cookies

    def close(self):
        self.closed = True


class FakeUploadResponse:
    ok = True

    def json(self):
        return {"result": {"data": {"json": {"url": "https://cdn.example/upload.png"}}}}


class FakeRequestContext:
    def __init__(self):
        self.calls = []

    def post(self, url, *, multipart):
        self.calls.append((url, multipart))
        return FakeUploadResponse()


class FakeChromium:
    def __init__(self, context):
        self.context = context
        self.calls = []

    def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs)
        return self.context

    def connect_over_cdp(self, url):
        self.calls.append({"cdp_url": url})
        return type("Browser", (), {"contexts": [self.context]})()


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_headless_session_uses_owned_profile_and_loopback_cdp(tmp_path):
    context = FakeContext("https://chat.example/room")
    chromium = FakeChromium(context)
    playwright = FakePlaywright(chromium)
    profile = tmp_path / "profile"
    session = BrowserSession(
        profile_path=profile,
        login_url="https://chat.example/login",
        cdp_port=19222,
        playwright_factory=lambda: playwright,
    )

    session.start_headless()

    assert profile.is_dir()
    assert chromium.calls == [
        {
            "user_data_dir": str(profile),
            "headless": True,
            "args": [
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=19222",
                "--restore-last-session",
            ],
        }
    ]


def test_session_rejects_nonstandard_cdp_port(tmp_path):
    with pytest.raises(ValueError, match="19222"):
        BrowserSession(tmp_path / "profile", None, cdp_port=9222)


def test_session_attaches_to_the_existing_desktop_browser(tmp_path):
    context = FakeContext("https://chat.example/room")
    chromium = FakeChromium(context)
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        playwright_factory=lambda: FakePlaywright(chromium),
    )

    assert session.attach_existing().is_authenticated()
    assert chromium.calls == [{"cdp_url": "http://127.0.0.1:19222"}]


def test_attached_desktop_opens_configured_group_chat(tmp_path):
    context = FakeContext("https://chat.example/chat")
    chromium = FakeChromium(context)
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
        playwright_factory=lambda: FakePlaywright(chromium),
    )

    session.attach_existing()

    assert context.pages[0].url == "https://chat.example/chat?c=group-1"


def test_headless_session_prefers_a_restored_page_over_a_blank_page(tmp_path):
    context = FakeContext("about:blank")
    context.pages.append(FakePage("https://chat.example/room"))
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        playwright_factory=lambda: FakePlaywright(FakeChromium(context)),
    )

    session.start_headless()

    assert session.login_state() is LoginState.READY


def test_login_state_uses_navigation_without_platform_selectors(tmp_path):
    context = FakeContext("https://chat.example/login")
    chromium = FakeChromium(context)
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        playwright_factory=lambda: FakePlaywright(chromium),
    )
    session.start_headless()

    assert session.login_state() is LoginState.AUTH_REQUIRED
    context.pages[0].url = "https://chat.example/room"
    assert session.login_state() is LoginState.READY


def test_missing_login_url_requires_authentication(tmp_path):
    session = BrowserSession(
        tmp_path / "profile",
        None,
        playwright_factory=lambda: FakePlaywright(
            FakeChromium(FakeContext("about:blank"))
        ),
    )

    session.start_headless()

    assert session.login_state() is LoginState.AUTH_REQUIRED


def test_stop_releases_browser_and_playwright(tmp_path):
    context = FakeContext("https://chat.example/room")
    playwright = FakePlaywright(FakeChromium(context))
    session = BrowserSession(
        tmp_path / "profile", None, playwright_factory=lambda: playwright
    )
    session.start_headless()

    session.stop()

    assert context.closed is True
    assert playwright.stopped is True


def test_configured_session_uses_socket_gateway_instead_of_dom_chat_controls(tmp_path):
    page = FakePage("https://chat.example/chat")
    socket = FakeSocket()
    page.evaluate = lambda script, arg=None: (
        "short-lived-token"
        if "api/auth/token" in script
        else {"id": "bot-1"}
        if arg["procedure"] == "user.getMe"
        else {"messages": []}
    )
    context = FakeContext(page.url)
    context.pages = [page]
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
        playwright_factory=lambda: FakePlaywright(FakeChromium(context)),
        socket_factory=lambda: socket,
    )
    gateway = session.start_headless()

    assert gateway.is_authenticated()
    platform_id = gateway.send("hello")

    assert page.url == "https://chat.example/chat?c=group-1"
    assert socket.connect_calls[0][1]["auth"] == {"token": "short-lived-token"}
    assert socket.calls[0][0] == "message:send"
    assert platform_id == socket.calls[0][1]["message"]["message_id"]
    assert page.filled == []


def test_trpc_request_aborts_a_hung_platform_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(
        session_module, "_TRPC_REQUEST_TIMEOUT_MS", 10, raising=False
    )
    context = FakeContext("https://chat.example/chat?c=group-1")
    context.pages = [NodePage(context.pages[0].url)]
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
    )
    session._context = context

    with pytest.raises(AikdaTransportError, match="aborted"):
        session._request("chatroom.getMessages", {"chatroomId": "group-1"})


def test_trpc_unauthorized_response_is_classified_as_authentication_loss(tmp_path):
    context = FakeContext("https://chat.example/chat?c=group-1")

    def unauthorized(_script, _argument):
        raise RuntimeError("Aikda user.getMe request failed status=401")

    context.pages[0].evaluate = unauthorized
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
    )
    session._context = context

    with pytest.raises(AikdaAuthenticationError, match="status=401"):
        session._request("user.getMe")


def test_configured_session_uploads_image_as_multipart_without_hex_encoding(tmp_path):
    page = FakePage("https://chat.example/chat?c=group-1")
    socket = FakeSocket()
    page.evaluate = lambda script, arg=None: (
        "short-lived-token"
        if "api/auth/token" in script
        else {"id": "bot-1"}
        if arg["procedure"] == "user.getMe"
        else {"messages": []}
    )
    context = FakeContext(page.url)
    context.request = FakeRequestContext()
    context.pages = [page]
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
        playwright_factory=lambda: FakePlaywright(FakeChromium(context)),
        socket_factory=lambda: socket,
    )
    image_path = tmp_path / "profile.png"
    image_path.write_bytes(b"raw-image")

    gateway = session.start_headless()
    result = gateway.upload_image(image_path, "image/png")

    assert result == {"url": "https://cdn.example/upload.png"}
    assert context.request.calls == [(
        "https://chat.example/api/trpc/chatroom.uploadImage",
        {
            "file": {
                "name": "profile.png",
                "mimeType": "image/png",
                "buffer": b"raw-image",
            },
            "chatroomId": "group-1",
        },
    )]


def test_configured_session_forwards_browser_cookies_to_socket_handshake(tmp_path):
    """Fails if the server Socket.IO client omits the authenticated browser session."""
    page = FakePage("https://chat.example/chat?c=group-1")
    page.evaluate = lambda script, arg=None: (
        "short-lived-token"
        if "api/auth/token" in script
        else {"id": "bot-1"}
        if arg["procedure"] == "user.getMe"
        else {"messages": []}
    )
    context = FakeContext(
        page.url,
        cookies=[
            {"name": "sb-rls-auth-token", "value": "browser-session"},
            {"name": "theme", "value": "dark"},
        ],
    )
    context.pages = [page]
    socket = FakeSocket()
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
        playwright_factory=lambda: FakePlaywright(FakeChromium(context)),
        socket_factory=lambda: socket,
    )

    assert session.start_headless().is_authenticated()

    assert socket.connect_calls[0][1]["headers"] == {
        "Cookie": "sb-rls-auth-token=browser-session; theme=dark"
    }


def test_stop_disconnects_the_configured_socket_gateway(tmp_path):
    page = FakePage("https://chat.example/chat")
    socket = FakeSocket()
    page.evaluate = lambda script, arg=None: (
        "short-lived-token"
        if "api/auth/token" in script
        else {"id": "bot-1"}
        if arg["procedure"] == "user.getMe"
        else {"messages": []}
    )
    context = FakeContext(page.url)
    context.pages = [page]
    session = BrowserSession(
        tmp_path / "profile",
        "https://chat.example/login",
        chat_url="https://chat.example/chat?c=group-1",
        playwright_factory=lambda: FakePlaywright(FakeChromium(context)),
        socket_factory=lambda: socket,
    )

    assert session.start_headless().is_authenticated()
    session.stop()

    assert socket.connected is False
