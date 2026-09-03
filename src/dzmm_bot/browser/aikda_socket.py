from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
import logging
from threading import Event, Lock, RLock, get_ident
from typing import Any
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo
from socketio.exceptions import TimeoutError as SocketTimeoutError

from dzmm_bot.runtime.contracts import (
    GroupChatTarget,
    InboundMessage,
    MessageReference,
)


_LOGGER = logging.getLogger(__name__)
_SEND_ACK_TIMEOUT_SECONDS = 3
_DIRECT_JOIN_ACK_TIMEOUT_SECONDS = 2


class AikdaMessageRejectedError(RuntimeError):
    pass


class AikdaAuthenticationError(RuntimeError):
    pass


class AikdaTransportError(RuntimeError):
    pass


class AikdaSocketGateway:

    def __init__(
        self,
        chat_url: str,
        *,
        token_provider: Callable[[], str],
        request: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        upload: Callable[[Path, str, str], dict[str, Any]] | None = None,
        cookie_provider: Callable[[], str] | None = None,
        socket_factory: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(ZoneInfo("Asia/Shanghai")),
    ) -> None:
        parsed = urlsplit(chat_url)
        chatroom_id = parse_qs(parsed.query).get("c", [None])[0]
        if not parsed.scheme or not parsed.netloc or not chatroom_id:
            raise ValueError("chat_url must contain an absolute URL with c query parameter")
        self.chatroom_id = chatroom_id
        self._implicit_group_chatroom_id = chatroom_id
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._token_provider = token_provider
        self._request = request
        self._upload = upload
        self._cookie_provider = cookie_provider
        self._socket_factory = socket_factory or _socket_client
        self._clock = clock
        self._owner_thread_id = get_ident()
        self._socket = None
        self._bot_id: str | None = None
        self._account_display_name: str | None = None
        self._authenticated = False
        self._joined = Event()
        self._pending: deque[InboundMessage] = deque()
        self._seen_ids: set[tuple[str, str]] = set()
        self._pending_lock = Lock()
        self._state_lock = RLock()
        self._emit_lock = Lock()
        self._send_locks_guard = Lock()
        self._send_locks = {}
        self._message_handler: Callable[[InboundMessage], None] | None = None
        self._group_targets: dict[str, GroupChatTarget] = {
            chatroom_id: GroupChatTarget(UUID(int=0), chatroom_id, chat_url)
        }
        self._group_chatroom_ids: set[str] = {chatroom_id}
        self._joined_group_chatroom_ids: set[str] = {chatroom_id}
        self._group_join_errors: dict[str, str] = {}
        self._direct_chatroom_ids: set[str] = set()
        self._joined_direct_chatroom_ids: set[str] = set()
        self._next_direct_room_join_index = 0

    def configure_group_rooms(
        self, targets: tuple[GroupChatTarget, ...]
    ) -> None:
        configured: dict[str, GroupChatTarget] = {}
        for target in targets:
            parsed = urlsplit(target.chat_url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin != self._origin:
                raise ValueError("all group chats must use the gateway origin")
            if target.chatroom_id in configured:
                raise ValueError("duplicate group chatroom ID")
            configured[target.chatroom_id] = target
        next_ids = set(configured)
        if next_ids == self._group_chatroom_ids:
            self._group_targets = configured
            return
        self._group_targets = configured
        self._group_chatroom_ids = next_ids
        self._joined_group_chatroom_ids.intersection_update(next_ids)
        self._group_join_errors = {
            room_id: error
            for room_id, error in self._group_join_errors.items()
            if room_id in next_ids
        }
        if next_ids:
            self.chatroom_id = sorted(next_ids)[0]
        if self._socket is not None and self._socket.connected:
            self._join_configured_group_rooms()

    def set_message_handler(
        self, handler: Callable[[InboundMessage], None]
    ) -> None:
        self._message_handler = handler

    def read_new(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> list[InboundMessage]:
        self._ensure_connected()
        self._set_direct_targets(direct_chatroom_ids)
        return self._drain_pending()

    def maintain_recovery(
        self, direct_chatroom_ids: tuple[str, ...] = ()
    ) -> None:
        self._ensure_connected()
        self._set_direct_targets(direct_chatroom_ids)

    def _set_direct_targets(self, direct_chatroom_ids: tuple[str, ...]) -> None:
        targets = set(direct_chatroom_ids)
        if targets != self._direct_chatroom_ids:
            self._direct_chatroom_ids = targets
            self._next_direct_room_join_index = 0
        for offset in range(len(direct_chatroom_ids)):
            index = (self._next_direct_room_join_index + offset) % len(
                direct_chatroom_ids
            )
            chatroom_id = direct_chatroom_ids[index]
            if chatroom_id in self._joined_direct_chatroom_ids:
                continue
            self._next_direct_room_join_index = (index + 1) % len(
                direct_chatroom_ids
            )
            try:
                self._join_direct_room(
                    chatroom_id, timeout=_DIRECT_JOIN_ACK_TIMEOUT_SECONDS
                )
            except (SocketTimeoutError, RuntimeError) as exc:
                _LOGGER.warning(
                    "direct message room join deferred chatroom=%s error=%s",
                    chatroom_id,
                    exc or type(exc).__name__,
                )
            return

    def _drain_pending(self) -> list[InboundMessage]:
        with self._pending_lock:
            messages, self._pending = self._pending, deque()
        return sorted(messages, key=lambda message: message.received_at)

    def _join_direct_room(self, chatroom_id: str, *, timeout: float = 10) -> None:
        with self._state_lock:
            if chatroom_id in self._joined_direct_chatroom_ids:
                return
            joined = self._call(
                "message:join-room", {"chatroomId": chatroom_id}, timeout=timeout
            )
            if not joined or joined.get("success") is not True:
                error = joined.get("error", "message room join failed") if joined else "message room join failed"
                raise RuntimeError(error)
            self._joined_direct_chatroom_ids.add(chatroom_id)

    def _join_group_room(self, chatroom_id: str, *, timeout: float = 10) -> None:
        with self._state_lock:
            if chatroom_id in self._joined_group_chatroom_ids:
                return
            joined = self._call(
                "message:join-room", {"chatroomId": chatroom_id}, timeout=timeout
            )
            if not joined or joined.get("success") is not True:
                error = (
                    joined.get("error", "group room join failed")
                    if joined
                    else "group room join failed"
                )
                raise RuntimeError(error)
            self._joined_group_chatroom_ids.add(chatroom_id)
            self._group_join_errors.pop(chatroom_id, None)

    def _join_configured_group_rooms(self) -> None:
        for chatroom_id in sorted(self._group_chatroom_ids):
            if chatroom_id in self._joined_group_chatroom_ids:
                continue
            try:
                self._join_group_room(chatroom_id)
            except (SocketTimeoutError, RuntimeError) as error:
                self._group_join_errors[chatroom_id] = str(error)[:512]
                _LOGGER.warning(
                    "group message room join failed chatroom=%s error=%s",
                    chatroom_id,
                    error or type(error).__name__,
                )

    def group_room_states(self) -> dict[str, tuple[str, str | None]]:
        return {
            chatroom_id: (
                ("connected", None)
                if chatroom_id in self._joined_group_chatroom_ids
                else (
                    "failed",
                    self._group_join_errors[chatroom_id],
                )
                if chatroom_id in self._group_join_errors
                else ("pending", None)
            )
            for chatroom_id in self._group_chatroom_ids
        }

    def send(
        self, text: str, *, message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str:
        return self.send_to(
            self.chatroom_id, text, message_id=message_id, reference=reference
        )

    def send_to(
        self, chatroom_id: str, text: str, *, message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str:
        if not text.strip():
            raise ValueError("text must be nonempty")
        content = {"type": "text", "text": text}
        if reference is not None:
            content["reference"] = _reference_payload(reference)
        return self._send_content(chatroom_id, content, message_id=message_id)

    def send_image(
        self, image_url: str, *, alt: str = "image", message_id: str | None = None,
        reference: MessageReference | None = None,
    ) -> str:
        return self.send_image_to(
            self.chatroom_id, image_url, alt=alt, message_id=message_id,
            reference=reference,
        )

    def send_image_to(
        self, chatroom_id: str, image_url: str, *, alt: str = "image",
        message_id: str | None = None, reference: MessageReference | None = None,
    ) -> str:
        if not image_url.strip():
            raise ValueError("image_url must be nonempty")
        content = {"type": "image", "url": image_url, "alt": alt or "image"}
        if reference is not None:
            content["reference"] = _reference_payload(reference)
        return self._send_content(chatroom_id, content, message_id=message_id)

    def upload_image(self, path: Path, mime_type: str) -> dict:
        if self._upload is None:
            raise NotImplementedError("image uploader unavailable")
        self._ensure_connected()
        return self._upload(path, mime_type, self.chatroom_id)

    def _send_content(
        self, chatroom_id: str, content: dict[str, Any], *, message_id: str | None
    ) -> str:
        if not chatroom_id:
            raise ValueError("chatroom_id must be nonempty")
        with self._send_lock(chatroom_id):
            self._ensure_connected()
            message_id = message_id or str(uuid4())
            message = {
                "message_id": message_id,
                "sent_by": self._bot_id,
                "chatroom_id": chatroom_id,
                "sent_at": _utc_iso(self._clock()),
                "content": content,
            }
            if chatroom_id in self._group_chatroom_ids:
                self._join_group_room(chatroom_id)
            else:
                self._join_direct_room(chatroom_id)
            acknowledgement = self._call(
                "message:send",
                {"chatroomId": chatroom_id, "message": message},
                timeout=_SEND_ACK_TIMEOUT_SECONDS,
            )
            if not acknowledgement or acknowledgement.get("success") is not True:
                error = acknowledgement.get("error", "message acknowledgement failed") if acknowledgement else "message acknowledgement failed"
                code = acknowledgement.get("code") if acknowledgement else None
                _LOGGER.warning(
                    "aikda message:send rejected destination=%s chars=%s lines=%s code=%s error=%s",
                    chatroom_id,
                    len(content.get("text", "")),
                    content.get("text", "").count("\n") + 1,
                    code or "-",
                    error,
                )
                raise AikdaMessageRejectedError(error)
        return message_id

    def _send_lock(self, chatroom_id: str):
        with self._send_locks_guard:
            return self._send_locks.setdefault(chatroom_id, Lock())

    def add_bot_to_chatroom(self, chatroom_id: str, bot_id: str) -> None:
        self._request(
            "chatroom.addBot",
            {"chatroomId": chatroom_id, "botId": bot_id},
        )

    def retract(self, message_id: str, *, chatroom_id: str | None = None) -> None:
        self._ensure_connected()
        acknowledgement = self._call(
            "message:recall",
            {
                "chatroomId": chatroom_id or self.chatroom_id,
                "messageId": message_id,
            },
            timeout=10,
        )
        if not acknowledgement or acknowledgement.get("success") is not True:
            error = acknowledgement.get("error", "message retraction acknowledgement failed") if acknowledgement else "message retraction acknowledgement failed"
            raise RuntimeError(error)

    def is_authenticated(self) -> bool:
        if self._socket is not None and self._socket.connected and self._joined.is_set():
            self._authenticated = True
            return True
        try:
            self._ensure_connected()
        except AikdaAuthenticationError:
            self._authenticated = False
            return False
        return self._authenticated

    @property
    def account_display_name(self) -> str | None:
        return self._account_display_name

    def close(self) -> None:
        with self._state_lock:
            socket = self._socket
            self._socket = None
            self._authenticated = False
            self._joined.clear()
            self._joined_group_chatroom_ids.clear()
            self._joined_direct_chatroom_ids.clear()
        if socket is not None:
            socket.disconnect()

    def _call(self, event: str, payload: dict[str, Any], *, timeout: float):
        if not hasattr(self._socket, "emit"):
            return self._socket.call(event, payload, timeout=timeout)
        callback_event = self._socket.eio.create_event()
        callback_args: list[Any] = []

        def event_callback(*args):
            callback_args.extend(args)
            callback_event.set()

        with self._emit_lock:
            self._socket.emit(event, data=payload, callback=event_callback)
        if not callback_event.wait(timeout=timeout):
            raise SocketTimeoutError()
        if len(callback_args) > 1:
            return tuple(callback_args)
        if callback_args:
            return callback_args[0]
        return None

    def _ensure_connected(self) -> None:
        try:
            with self._state_lock:
                self._ensure_connected_locked()
        except AikdaTransportError:
            try:
                self.close()
            except Exception:
                _LOGGER.exception("socket cleanup after connection failure failed")
            raise

    def _ensure_connected_locked(self) -> None:
        if self._socket is not None and self._socket.connected and self._joined.is_set():
            self._join_configured_group_rooms()
            self._authenticated = True
            return
        if get_ident() != self._owner_thread_id:
            raise SocketTimeoutError()
        try:
            profile = self._request("user.getMe")
        except (AikdaAuthenticationError, AikdaTransportError):
            raise
        except Exception as error:
            raise AikdaTransportError(str(error) or type(error).__name__) from error
        bot_id = profile.get("id")
        if not bot_id:
            raise AikdaAuthenticationError("bot identity unavailable")
        self._account_display_name = _profile_display_name(profile)
        try:
            token = self._token_provider()
        except (AikdaAuthenticationError, AikdaTransportError):
            raise
        except Exception as error:
            raise AikdaTransportError(str(error) or type(error).__name__) from error
        if not token:
            raise AikdaAuthenticationError("socket token unavailable")
        self._bot_id = bot_id
        if self._socket is None:
            self._socket = self._socket_factory()
            self._socket.on("message:new", self._on_message)
            self._socket.on("message:joined", self._on_joined)
            self._socket.on("disconnect", self._on_disconnect)
        self._joined.clear()
        cookie = self._cookie_provider() if self._cookie_provider is not None else ""
        connect_options: dict[str, Any] = {
            "socketio_path": "ws/matching",
            "auth": {"token": token},
            "transports": ["websocket", "polling"],
        }
        if cookie:
            connect_options["headers"] = {"Cookie": cookie}
        try:
            self._socket.connect(
                self._origin,
                **connect_options,
            )
        except Exception as error:
            raise AikdaTransportError(str(error) or type(error).__name__) from error
        if not self._joined.wait(timeout=10):
            raise AikdaTransportError("socket join timed out")
        if self._implicit_group_chatroom_id in self._group_chatroom_ids:
            self._joined_group_chatroom_ids.add(self._implicit_group_chatroom_id)
        self._join_configured_group_rooms()
        self._authenticated = True

    def _on_message(self, payload: dict[str, Any]) -> None:
        message = payload.get("message")
        if isinstance(message, dict):
            self._accept_message(payload.get("chatroomId"), message)

    def _on_joined(self, _payload: dict[str, Any] | None = None) -> None:
        self._joined.set()

    def _on_disconnect(self) -> None:
        with self._state_lock:
            self._authenticated = False
            self._joined.clear()
            self._joined_group_chatroom_ids.clear()
            self._joined_direct_chatroom_ids.clear()

    def _accept_message(self, chatroom_id: str | None, message: dict[str, Any]) -> None:
        if message.get("sent_by") == self._bot_id:
            return
        content = message.get("content")
        message_id = message.get("message_id")
        sent_by = message.get("sent_by")
        sent_at = message.get("sent_at")
        if (
            not isinstance(content, dict)
            or not isinstance(message_id, str)
            or not isinstance(sent_by, str)
            or not isinstance(sent_at, str)
        ):
            return
        content_type = content.get("type")
        if content_type == "text":
            text_content = content.get("text")
            if not isinstance(text_content, str):
                return
            image_url = image_alt = None
            image_width = image_height = None
        elif content_type == "image":
            image_url = content.get("url")
            parsed_url = urlsplit(image_url) if isinstance(image_url, str) else None
            if (
                parsed_url is None
                or parsed_url.scheme != "https"
                or not parsed_url.netloc
            ):
                return
            image_alt = content.get("alt")
            if image_alt is not None and not isinstance(image_alt, str):
                return
            image_width = content.get("width")
            image_height = content.get("height")
            if any(
                value is not None
                and (isinstance(value, bool) or not isinstance(value, int) or value < 1)
                for value in (image_width, image_height)
            ):
                return
            text_content = "[图片]"
        else:
            return
        if chatroom_id is None:
            return
        if chatroom_id in self._group_chatroom_ids:
            source_type = "group"
        else:
            source_type = "direct"
        inbound = InboundMessage(
            message_id,
            sent_by,
            text_content,
            _shanghai_time(sent_at),
            source_type=source_type,
            chatroom_id=chatroom_id,
            reference=_message_reference(content.get("reference")),
            content_type=content_type,
            image_url=image_url,
            image_alt=image_alt,
            image_width=image_width,
            image_height=image_height,
        )
        with self._pending_lock:
            seen_key = (chatroom_id, message_id)
            if seen_key in self._seen_ids:
                return
            self._seen_ids.add(seen_key)
            handler = self._message_handler
            if handler is None:
                self._pending.append(inbound)
        if handler is not None:
            handler(inbound)


def _message_reference(value: Any) -> MessageReference | None:
    if not isinstance(value, dict):
        return None
    message_id = value.get("id")
    sender_platform_id = value.get("sentBy")
    content = value.get("content")
    if (
        not isinstance(message_id, str)
        or not message_id
        or not isinstance(sender_platform_id, str)
        or not sender_platform_id
        or not isinstance(content, dict)
    ):
        return None
    content_type = content.get("type")
    if not isinstance(content_type, str) or not content_type:
        return None
    image_url = content.get("url")
    if image_url is not None and not isinstance(image_url, str):
        return None
    optional_strings = {
        key: content.get(key)
        for key in ("alt", "blurhash")
    }
    if any(value is not None and not isinstance(value, str) for value in optional_strings.values()):
        return None
    optional_dimensions = {
        key: content.get(key)
        for key in ("width", "height")
    }
    if any(
        value is not None
        and (isinstance(value, bool) or not isinstance(value, int) or value < 1)
        for value in optional_dimensions.values()
    ):
        return None
    return MessageReference(
        message_id=message_id,
        sender_platform_id=sender_platform_id,
        content_type=content_type,
        image_url=image_url,
        alt=optional_strings["alt"],
        width=optional_dimensions["width"],
        height=optional_dimensions["height"],
        blurhash=optional_strings["blurhash"],
        text=content.get("text") if isinstance(content.get("text"), str) else None,
    )


def _reference_payload(reference: MessageReference) -> dict[str, Any]:
    content: dict[str, Any] = {"type": reference.content_type}
    if reference.content_type == "text":
        content["text"] = reference.text or ""
    else:
        if reference.image_url is not None:
            content["url"] = reference.image_url
        for key, value in (
            ("alt", reference.alt),
            ("width", reference.width),
            ("height", reference.height),
            ("blurhash", reference.blurhash),
        ):
            if value is not None:
                content[key] = value
    return {
        "id": reference.message_id,
        "sentBy": reference.sender_platform_id,
        "content": content,
    }


def _socket_client():
    import socketio

    return socketio.Client(reconnection=False)


def _shanghai_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        ZoneInfo("Asia/Shanghai")
    )


def _utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _profile_display_name(profile: dict[str, Any]) -> str | None:
    display_name = profile.get("fullName")
    if not isinstance(display_name, str) or not display_name.strip():
        return None
    return display_name.strip()
