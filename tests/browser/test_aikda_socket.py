from collections import deque
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from time import monotonic, sleep
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from socketio.exceptions import TimeoutError as SocketTimeoutError

from dzmm_bot.browser.aikda_socket import AikdaSocketGateway, _socket_client
from dzmm_bot.runtime.contracts import (
    GroupChatTarget,
    InboundMessage,
    MessageReference,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
TARGET_URL = "https://www.aikda.com/chat?c=room-1"


class FakeSocket:
    def __init__(self):
        self.handlers = {}
        self.connected = False
        self.joined = False
        self.connect_calls = []
        self.call_result = {"success": True}
        self.call_results = []
        self.call_errors_by_room = {}
        self.calls = []
        self.message_after_join = None
        self.joined_payload = {"syncMode": "http"}

    def on(self, event, handler):
        self.handlers[event] = handler

    def connect(self, origin, **kwargs):
        self.connect_calls.append((origin, kwargs))
        self.connected = True
        handler = self.handlers.get("message:joined")
        if handler is not None:
            if self.joined_payload is None:
                handler()
            else:
                handler(self.joined_payload)
            self.joined = True
        if self.message_after_join is not None:
            self.handlers["message:new"](self.message_after_join)

    def call(self, event, payload, timeout):
        if not self.joined:
            raise RuntimeError("server join was not completed")
        self.calls.append((event, payload, timeout))
        error = self.call_errors_by_room.get(payload.get("chatroomId"))
        if error is not None:
            raise error
        if self.call_results:
            return self.call_results.pop(0)
        return self.call_result

    def disconnect(self):
        self.connected = False

    def trigger(self, event, payload):
        self.handlers[event](payload)


class FakeRequest:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.messages_by_room = None
        self.rooms = []
        self.calls = []
        self.profile = {"id": "bot-1"}

    def __call__(self, procedure, payload=None):
        self.calls.append((procedure, payload))
        if procedure == "user.getMe":
            return self.profile
        if procedure == "chat.listAll":
            return {"items": self.rooms}
        if procedure == "chatroom.getMessages":
            if self.messages_by_room is not None:
                return {"messages": self.messages_by_room.get(payload["chatroomId"], [])}
            return {"messages": self.messages}
        raise AssertionError(f"unexpected procedure {procedure}")


def message(message_id, sent_by, text, sent_at="2026-08-05T04:00:00Z"):
    return {
        "message_id": message_id,
        "sent_by": sent_by,
        "sent_at": sent_at,
        "content": {"type": "text", "text": text},
    }


class ConcurrentEmitSocket:
    def __init__(self):
        self.connected = True
        self.eio = self
        self._emit_guard = Lock()
        self._active_emits = 0
        self.max_active_emits = 0
        self._pending_acknowledgements = 0
        self.max_pending_acknowledgements = 0

    @staticmethod
    def create_event():
        return Event()

    def emit(self, event, data=None, namespace=None, callback=None):
        with self._emit_guard:
            self._active_emits += 1
            self.max_active_emits = max(self.max_active_emits, self._active_emits)
            self._pending_acknowledgements += 1
            self.max_pending_acknowledgements = max(
                self.max_pending_acknowledgements,
                self._pending_acknowledgements,
            )
        sleep(0.02)
        with self._emit_guard:
            self._active_emits -= 1

        def acknowledge():
            sleep(0.08)
            with self._emit_guard:
                self._pending_acknowledgements -= 1
            callback({"success": True})

        Thread(target=acknowledge).start()


def test_concurrent_socket_sends_serialize_emit_but_overlap_ack_waits():
    socket = ConcurrentEmitSocket()
    gateway = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "token",
        request=FakeRequest(),
        socket_factory=lambda: socket,
        clock=lambda: NOW,
    )
    gateway._socket = socket
    gateway._joined.set()
    gateway._authenticated = True
    gateway._bot_id = "bot-1"
    gateway._joined_direct_chatroom_ids.update({"direct-1", "direct-2"})

    started = monotonic()
    threads = [
        Thread(target=gateway.send_to, args=(room, "hello"))
        for room in ("direct-1", "direct-2")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert socket.max_active_emits == 1
    assert socket.max_pending_acknowledgements == 2
    assert monotonic() - started < 0.18


def test_concurrent_socket_sends_to_the_same_room_wait_for_the_previous_ack():
    """Fails if a direct send can overtake an unacknowledged send in the same room."""
    socket = ConcurrentEmitSocket()
    gateway = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "token",
        request=FakeRequest(),
        socket_factory=lambda: socket,
        clock=lambda: NOW,
    )
    gateway._socket = socket
    gateway._joined.set()
    gateway._authenticated = True
    gateway._bot_id = "bot-1"
    gateway._joined_direct_chatroom_ids.add("direct-1")

    threads = [
        Thread(target=gateway.send_to, args=("direct-1", text))
        for text in ("first", "second")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert socket.max_pending_acknowledgements == 1


def test_background_send_does_not_reconnect_through_owner_thread_dependencies():
    """Fails if a sender thread invokes browser-backed reconnect dependencies."""
    socket = FakeSocket()
    request = FakeRequest()
    gateway = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "token",
        request=request,
        socket_factory=lambda: socket,
        clock=lambda: NOW,
    )
    errors = []

    def send():
        try:
            gateway.send_to("direct-1", "hello")
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=send)
    thread.start()
    thread.join()

    assert len(errors) == 1
    assert isinstance(errors[0], SocketTimeoutError)
    assert request.calls == []


@pytest.fixture
def gateway():
    socket = FakeSocket()
    request = FakeRequest()
    gateway = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "short-lived-token",
        request=request,
        socket_factory=lambda: socket,
        clock=lambda: NOW,
    )
    return gateway, socket, request


def test_live_target_room_text_event_is_read_once(gateway):
    """Fails if the event handler does not retain a target-room text message."""
    adapter, socket, _ = gateway
    assert adapter.read_new() == []


def test_gateway_classifies_nonconfigured_socket_rooms_as_direct(gateway):
    adapter, socket, _ = gateway
    adapter.configure_group_rooms(
        (
            GroupChatTarget(
                UUID("00000000-0000-0000-0000-000000000101"),
                "group-a",
                "https://www.aikda.com/chat?c=group-a",
            ),
            GroupChatTarget(
                UUID("00000000-0000-0000-0000-000000000102"),
                "group-b",
                "https://www.aikda.com/chat?c=group-b",
            ),
        )
    )
    assert adapter.read_new(("direct-1",)) == []

    for room_id, message_id in (
        ("group-a", "same-id"),
        ("group-b", "same-id"),
        ("direct-1", "direct-id"),
        ("unknown-room", "unknown-id"),
    ):
        socket.trigger(
            "message:new",
            {
                "chatroomId": room_id,
                "message": message(message_id, "u-1", room_id),
            },
        )

    assert [
        (item.source_type, item.chatroom_id) for item in adapter.read_new(("direct-1",))
    ] == [
        ("group", "group-a"),
        ("group", "group-b"),
        ("direct", "direct-1"),
        ("direct", "unknown-room"),
    ]


def test_live_replied_image_metadata_is_preserved(gateway):
    """Fails if the Socket adapter keeps reply text but drops its image target."""
    adapter, socket, _ = gateway
    assert adapter.read_new() == []
    payload = message("m-image-reply", "u-1", "/编辑档案形象")
    payload["content"]["reference"] = {
        "id": "image-1",
        "sentBy": "u-2",
        "content": {
            "type": "image",
            "url": "https://cdn.example.test/profile.png",
            "alt": "profile.png",
            "width": 1254,
            "height": 1254,
            "blurhash": "UsK-k9",
        },
    }

    socket.trigger(
        "message:new",
        {"chatroomId": "room-1", "message": payload},
    )

    [received] = adapter.read_new()
    assert received.reference == MessageReference(
        message_id="image-1",
        sender_platform_id="u-2",
        content_type="image",
        image_url="https://cdn.example.test/profile.png",
        alt="profile.png",
        width=1254,
        height=1254,
        blurhash="UsK-k9",
    )


def test_malformed_replied_image_is_ignored_without_dropping_text(gateway):
    """Fails if malformed optional reference data discards a valid text command."""
    adapter, socket, _ = gateway
    assert adapter.read_new() == []
    payload = message("m-bad-reply", "u-1", "/编辑档案形象")
    payload["content"]["reference"] = {
        "id": "image-1",
        "sentBy": "u-2",
        "content": {"type": "image", "url": 123},
    }

    socket.trigger(
        "message:new",
        {"chatroomId": "room-1", "message": payload},
    )

    [received] = adapter.read_new()
    assert received.content == "/编辑档案形象"
    assert received.reference is None

    socket.trigger(
        "message:new",
        {"chatroomId": "room-1", "message": message("m-1", "u-1", "/余额")},
    )

    assert adapter.read_new() == [
        InboundMessage(
            "m-1",
            "u-1",
            "/余额",
            datetime(2026, 8, 5, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
            chatroom_id="room-1",
        )
    ]
    assert adapter.read_new() == []


def test_private_socket_events_are_read_once_even_before_core_selects_the_room(gateway):
    adapter, socket, request = gateway
    request.messages_by_room = {"room-1": [], "direct-1": []}

    assert adapter.read_new(("direct-1",)) == []
    assert socket.calls == [
        ("message:join-room", {"chatroomId": "direct-1"}, 2)
    ]

    socket.trigger(
        "message:new",
        {"chatroomId": "direct-1", "message": message("dm-1", "u-1", "/报数 29")},
    )
    socket.trigger(
        "message:new",
        {"chatroomId": "direct-1", "message": message("dm-text", "u-1", "29")},
    )
    socket.trigger(
        "message:new",
        {"chatroomId": "direct-2", "message": message("dm-other", "u-2", "/报数 30")},
    )

    assert [item.platform_message_id for item in adapter.read_new(("direct-1",))] == [
        "dm-1", "dm-text", "dm-other"
    ]
    assert adapter.read_new(("direct-1",)) == []
    assert socket.calls == [
        ("message:join-room", {"chatroomId": "direct-1"}, 2)
    ]


def test_direct_room_join_timeout_does_not_block_the_next_room(gateway):
    """Fails if one unresponsive private room aborts or monopolizes room syncing."""
    adapter, socket, _ = gateway
    socket.call_errors_by_room["direct-1"] = SocketTimeoutError()

    assert adapter.read_new(("direct-1", "direct-2")) == []
    assert socket.calls == [
        ("message:join-room", {"chatroomId": "direct-1"}, 2)
    ]

    assert adapter.read_new(("direct-1", "direct-2")) == []
    assert socket.calls[-1] == (
        "message:join-room", {"chatroomId": "direct-2"}, 2
    )


def test_unknown_socket_event_is_emitted_for_worker_level_private_filtering(gateway):
    adapter, socket, _ = gateway
    adapter.read_new()

    socket.trigger(
        "message:new",
        {"chatroomId": "new-direct", "message": message("new-dm", "new-user", "你好")},
    )

    [received] = adapter.read_new()
    assert received.platform_message_id == "new-dm"
    assert received.source_type == "direct"


def test_socket_handler_receives_unknown_room_events_for_private_filtering(gateway):
    adapter, socket, _ = gateway
    received = []
    adapter.set_message_handler(received.append)
    adapter.read_new()

    socket.trigger(
        "message:new",
        {"chatroomId": "new-direct", "message": message("new-dm", "new-user", "你好")},
    )

    assert [item.platform_message_id for item in received] == ["new-dm"]
    assert adapter.read_new() == []


def test_read_new_does_not_poll_history_after_socket_is_connected(gateway):
    adapter, _, request = gateway
    now = [NOW]
    adapter._clock = lambda: now[0]
    adapter.read_new()
    request.calls.clear()
    now[0] += timedelta(seconds=5)

    assert adapter.read_new() == []
    assert request.calls == []


def test_recovery_never_uses_http_history_for_group_or_direct_rooms(gateway):
    adapter, _, request = gateway
    request.messages_by_room = {
        "room-1": [],
        "direct-1": [message("dm-1", "employee-1", "/报数 17")],
        "direct-2": [message("dm-2", "employee-2", "/报数 29")],
    }
    adapter.read_new(("direct-1", "direct-2"))
    request.calls.clear()

    recovered = []
    for _ in range(5):
        before = len(request.calls)
        adapter.maintain_recovery(("direct-1", "direct-2"))
        step_calls = [
            call
            for call in request.calls[before:]
            if call[0] == "chatroom.getMessages"
        ]
        assert len(step_calls) <= 1
        recovered.extend(adapter.read_new(("direct-1", "direct-2")))

    history_rooms = [
        payload["chatroomId"]
        for procedure, payload in request.calls
        if procedure == "chatroom.getMessages"
    ]
    assert history_rooms == []
    assert all(procedure != "chat.listAll" for procedure, _ in request.calls)
    assert recovered == []


def test_reconnect_rejoins_socket_without_polling_history():
    socket = FakeSocket()
    request = FakeRequest()
    request.messages_by_room = {"room-1": []}
    adapter = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "short-lived-token",
        request=request,
        socket_factory=lambda: socket,
        clock=lambda: NOW,
    )

    adapter.read_new()
    adapter.maintain_recovery()
    request.calls.clear()
    socket.handlers["disconnect"]()
    adapter.read_new()
    adapter.maintain_recovery()

    assert len(socket.connect_calls) == 2
    assert all(call[0] != "chatroom.getMessages" for call in request.calls)


def test_changing_live_direct_targets_does_not_start_a_history_scan(gateway):
    adapter, _, request = gateway
    adapter.read_new()
    adapter.maintain_recovery()
    request.calls.clear()

    adapter.read_new(("direct-1",))
    adapter.maintain_recovery(("direct-1",))

    assert all(procedure != "chatroom.getMessages" for procedure, _ in request.calls)

def test_self_events_are_ignored_and_unknown_rooms_are_emitted_as_direct(gateway):
    adapter, socket, _ = gateway
    adapter.read_new()

    socket.trigger(
        "message:new",
        {"chatroomId": "room-1", "message": message("m-self", "bot-1", "/余额")},
    )
    socket.trigger(
        "message:new",
        {"chatroomId": "room-2", "message": message("m-other", "u-1", "/余额")},
    )

    received = adapter.read_new()

    assert [item.platform_message_id for item in received] == ["m-other"]
    assert received[0].source_type == "direct"
    assert received[0].chatroom_id == "room-2"


def test_self_message_arriving_during_connection_is_ignored(gateway):
    """Fails if identity is unavailable while the initial socket event arrives."""
    adapter, socket, _ = gateway
    socket.message_after_join = {
        "chatroomId": "room-1",
        "message": message("m-self", "bot-1", "/余额"),
    }

    assert adapter.read_new() == []


def test_send_requires_successful_ack(gateway):
    """Fails if a send is reported before Aikda acknowledges it."""
    adapter, socket, _ = gateway

    platform_message_id = adapter.send("余额：5 摸鱼币")

    send_call = next(call for call in socket.calls if call[0] == "message:send")
    assert platform_message_id == send_call[1]["message"]["message_id"]
    assert socket.calls == [
        (
            "message:send",
            {
                "chatroomId": "room-1",
                "message": {
                    "message_id": platform_message_id,
                    "sent_by": "bot-1",
                    "chatroom_id": "room-1",
                    "sent_at": "2026-08-05T12:00:00Z",
                    "content": {"type": "text", "text": "余额：5 摸鱼币"},
                },
            },
            3,
        )
    ]


def test_send_preserves_caller_message_id_and_uses_short_ack_timeout(gateway):
    adapter, socket, _ = gateway

    platform_message_id = adapter.send("余额：5 摸鱼币", message_id="outbound-1")

    assert platform_message_id == "outbound-1"
    send_call = next(call for call in socket.calls if call[0] == "message:send")
    assert send_call[1]["message"]["message_id"] == "outbound-1"
    assert send_call[2] == 3


def test_send_serializes_reply_reference_into_text_content(gateway):
    adapter, socket, _ = gateway
    reference = MessageReference(
        message_id="trigger-1",
        sender_platform_id="employee-1",
        content_type="text",
        text="/余额",
    )

    adapter.send("余额：5 摸鱼币", reference=reference)

    send_call = next(call for call in socket.calls if call[0] == "message:send")
    assert send_call[1]["message"]["content"] == {
        "type": "text",
        "text": "余额：5 摸鱼币",
        "reference": {
            "id": "trigger-1",
            "sentBy": "employee-1",
            "content": {"type": "text", "text": "/余额"},
        },
    }


def test_send_without_reply_reference_omits_reference_field(gateway):
    adapter, socket, _ = gateway

    adapter.send("系统广播")

    send_call = next(call for call in socket.calls if call[0] == "message:send")
    assert "reference" not in send_call[1]["message"]["content"]


def test_send_image_uses_platform_image_content(gateway):
    adapter, socket, _ = gateway

    platform_message_id = adapter.send_image(
        "https://cdn.example.com/profile.webp",
        alt="档案形象",
        message_id="image-outbound-1",
    )

    assert platform_message_id == "image-outbound-1"
    send_call = next(call for call in socket.calls if call[0] == "message:send")
    assert send_call[1]["message"]["content"] == {
        "type": "image",
        "url": "https://cdn.example.com/profile.webp",
        "alt": "档案形象",
    }


def test_upload_image_delegates_to_authenticated_room_uploader(tmp_path):
    observed = {}
    image_path = tmp_path / "profile.png"
    image_path.write_bytes(b"image")

    def upload(path, mime_type, chatroom_id):
        observed.update(
            path=path, mime_type=mime_type, chatroom_id=chatroom_id
        )
        return {"url": "https://cdn.example.com/uploaded.png"}

    adapter = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "token",
        request=FakeRequest(),
        upload=upload,
        socket_factory=FakeSocket,
    )

    result = adapter.upload_image(image_path, "image/png")

    assert result == {"url": "https://cdn.example.com/uploaded.png"}
    assert observed == {
        "path": image_path,
        "mime_type": "image/png",
        "chatroom_id": "room-1",
    }


def test_send_joins_destination_before_sending_and_preserves_newlines(gateway):
    """Fails until sends explicitly join the target Aikda room first."""
    adapter, socket, _ = gateway

    adapter.send_to("direct-1", "第一行\n第二行")

    assert [call[0] for call in socket.calls] == [
        "message:join-room",
        "message:send",
    ]
    assert socket.calls[0][1] == {"chatroomId": "direct-1"}
    assert socket.calls[1][1]["message"]["content"]["text"] == "第一行\n第二行"


def test_send_reuses_joined_room_until_socket_reconnects(gateway):
    adapter, socket, _ = gateway

    adapter.send_to("direct-1", "第一条")
    adapter.send_to("direct-1", "第二条")

    assert [call[0] for call in socket.calls] == [
        "message:join-room", "message:send", "message:send"
    ]

    socket.connected = False
    adapter._on_disconnect()
    adapter.send_to("direct-1", "第三条")

    assert [call[0] for call in socket.calls] == [
        "message:join-room", "message:send", "message:send",
        "message:join-room", "message:send",
    ]


def test_send_waits_for_server_join_before_emitting(gateway):
    """Fails if the gateway sends before Aikda marks the socket joined."""
    adapter, socket, _ = gateway

    adapter.send("余额：5 摸鱼币")

    assert socket.joined is True


def test_send_to_uses_the_supplied_direct_chatroom(gateway):
    """Fails if direct card messages are accidentally sent into the configured group."""
    adapter, socket, _ = gateway

    platform_message_id = adapter.send_to("direct-1", "你的身份：平民。词语：咖啡")

    assert socket.calls == [
        ("message:join-room", {"chatroomId": "direct-1"}, 10),
        (
            "message:send",
            {
                "chatroomId": "direct-1",
                "message": {
                    "message_id": platform_message_id,
                    "sent_by": "bot-1",
                    "chatroom_id": "direct-1",
                    "sent_at": "2026-08-05T12:00:00Z",
                    "content": {"type": "text", "text": "你的身份：平民。词语：咖啡"},
                },
            },
            3,
        )
    ]


def test_joined_event_without_payload_marks_the_gateway_ready(gateway):
    """Fails for Aikda's real zero-argument message:joined event signature."""
    adapter, socket, _ = gateway
    socket.joined_payload = None

    assert adapter.read_new() == []
    assert adapter.is_authenticated()


def test_authenticated_live_socket_does_not_repeat_the_identity_request(gateway):
    adapter, _, request = gateway
    request.profile = {"id": "bot-1", "fullName": "饭饭（小狗青巫）."}

    assert adapter.is_authenticated() is True
    request.calls.clear()

    assert adapter.is_authenticated() is True
    assert adapter.account_display_name == "饭饭（小狗青巫）."
    assert request.calls == []


def test_authentication_is_lost_when_the_platform_identity_is_unavailable():
    """Fails if a stale socket keeps reporting ready after token expiry."""
    socket = FakeSocket()
    request = FakeRequest()
    adapter = AikdaSocketGateway(
        TARGET_URL,
        token_provider=lambda: "short-lived-token",
        request=request,
        socket_factory=lambda: socket,
        clock=lambda: NOW,
    )

    assert adapter.is_authenticated() is True
    socket.handlers["disconnect"]()
    request.profile = {}

    assert adapter.is_authenticated() is False


def test_send_raises_when_ack_rejects_message(gateway):
    """Fails if an Aikda rejection is incorrectly confirmed as delivered."""
    adapter, socket, _ = gateway
    socket.call_result = {"success": False, "error": "rejected"}

    with pytest.raises(RuntimeError, match="rejected"):
        adapter.send("余额：5 摸鱼币")


def test_send_rejection_logs_shape_without_logging_message_text(gateway, caplog):
    """Fails until a rejected outbound ACK carries safe diagnostic context."""
    adapter, socket, _ = gateway
    socket.call_results = [
        {
            "success": False,
            "error": "请勿发送重复内容",
            "code": "content_rejected",
        },
    ]

    with pytest.raises(RuntimeError, match="请勿发送重复内容"):
        adapter.send("唯一测试甲\n唯一测试乙")

    assert "destination=room-1 chars=11 lines=2" in caplog.text
    assert "code=content_rejected" in caplog.text
    assert "唯一测试甲" not in caplog.text


def test_retracts_an_acknowledged_message_in_the_target_chatroom(gateway):
    """Fails until a sent message can be withdrawn through the live gateway."""
    adapter, socket, _ = gateway

    adapter.retract("outbound-1")

    assert socket.calls == [
        (
            "message:recall",
            {"chatroomId": "room-1", "messageId": "outbound-1"},
            10,
        )
    ]


def test_socket_client_defers_reconnection_until_a_fresh_token_is_available():
    """Fails if the Socket.IO client retries with an expired connection token."""
    assert _socket_client().reconnection is False


def test_reconnect_acquires_a_fresh_token(gateway):
    """Fails if a disconnected session reuses its previous short-lived token."""
    adapter, socket, _ = gateway
    issued_tokens = []
    adapter._token_provider = lambda: issued_tokens.append("fresh-token") or "fresh-token"

    adapter.read_new()
    socket.connected = False
    adapter.read_new()

    assert issued_tokens == ["fresh-token", "fresh-token"]
    assert len(socket.connect_calls) == 2


def test_live_event_arriving_while_pending_messages_are_read_is_retained(gateway):
    """Fails if clearing the read queue discards a concurrently received event."""
    adapter, socket, _ = gateway
    adapter.read_new()

    class RaceQueue(deque):
        def __init__(self):
            super().__init__()
            self.triggered = False

        def __iter__(self):
            yield from tuple(super().__iter__())
            if not self.triggered:
                self.triggered = True
                socket.trigger(
                    "message:new",
                    {"chatroomId": "room-1", "message": message("m-race", "u-1", "/余额")},
                )

    adapter._pending = RaceQueue()

    assert adapter.read_new() == []
    assert [item.platform_message_id for item in adapter.read_new()] == ["m-race"]
