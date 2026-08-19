from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Any
from uuid import UUID

import httpx

from dzmm_bot.runtime.contracts import InboundMessage

from .aikda_socket import _message_reference, _shanghai_time


@dataclass(frozen=True)
class ShadowSyncCursor:
    group_chat_id: UUID
    chatroom_id: str
    at: datetime | None = None
    message_id: str | None = None


@dataclass(frozen=True)
class ShadowSyncRequest:
    origin: str
    cookie: str
    access_token: str
    cursors: tuple[ShadowSyncCursor, ...]


@dataclass(frozen=True)
class ShadowSyncResult:
    status: str
    messages: tuple[InboundMessage, ...]
    cursors: tuple[ShadowSyncCursor, ...]
    error_summary: str | None = None


class ShadowSyncRunner:
    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=5)
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="dzmm-shadow-sync"
        )
        self._future: Future[ShadowSyncResult] | None = None
        self._lock = Lock()

    def submit(self, request: ShadowSyncRequest) -> bool:
        with self._lock:
            if self._future is not None:
                return False
            self._future = self._executor.submit(self._run, request)
        return True

    def take_result(self) -> ShadowSyncResult | None:
        with self._lock:
            future = self._future
            if future is None or not future.done():
                return None
            self._future = None
        return future.result()

    def close(self) -> None:
        self._executor.shutdown(wait=True)
        self._client.close()

    def _run(self, request: ShadowSyncRequest) -> ShadowSyncResult:
        cursors = request.cursors[:50]
        try:
            response = self._client.get(
                f"{request.origin.rstrip('/')}/api/trpc/chatroom.syncChatroomMessages",
                params={
                    "input": _request_input(cursors),
                },
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {request.access_token}",
                    "Cookie": request.cookie,
                    "Referer": f"{request.origin.rstrip('/')}/chat",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as error:
            return ShadowSyncResult(
                "retrying", (), cursors, _error_summary(error)
            )
        if response.status_code in {401, 403}:
            return ShadowSyncResult("auth_required", (), cursors, "authentication_required")
        if response.status_code == 418:
            error = _response_error(response)
            status = "captcha_required" if error == "captcha_required" else "retrying"
            return ShadowSyncResult(status, (), cursors, error or "http_418")
        if response.status_code >= 500:
            return ShadowSyncResult(
                "retrying", (), cursors, f"http_{response.status_code}"
            )
        if response.status_code != 200:
            return ShadowSyncResult(
                "retrying", (), cursors, f"http_{response.status_code}"
            )
        try:
            chatrooms = _response_chatrooms(response.json())
            messages, next_cursors = _parse_chatrooms(chatrooms, cursors)
        except (TypeError, ValueError, KeyError) as error:
            return ShadowSyncResult(
                "retrying", (), cursors, _error_summary(error)
            )
        return ShadowSyncResult("healthy", messages, next_cursors)


def _request_input(cursors: Sequence[ShadowSyncCursor]) -> str:
    import json

    return json.dumps(
        {
            "json": {
                "chatrooms": [
                    {
                        "chatroomId": cursor.chatroom_id,
                        "cursorAt": None
                        if cursor.at is None
                        else cursor.at.isoformat(),
                        "cursorMessageId": cursor.message_id,
                    }
                    for cursor in cursors
                ]
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _response_chatrooms(body: Any) -> list[dict[str, Any]]:
    value = body
    if isinstance(value, dict) and "result" in value:
        value = value.get("result")
    if isinstance(value, dict) and "data" in value:
        value = value.get("data")
    if isinstance(value, dict) and "json" in value:
        value = value.get("json")
    if not isinstance(value, dict) or not isinstance(value.get("chatrooms"), list):
        raise ValueError("invalid shadow sync response")
    if not all(isinstance(item, dict) for item in value["chatrooms"]):
        raise ValueError("invalid shadow sync chatroom")
    return value["chatrooms"]


def _parse_chatrooms(
    chatrooms: list[dict[str, Any]],
    cursors: tuple[ShadowSyncCursor, ...],
) -> tuple[tuple[InboundMessage, ...], tuple[ShadowSyncCursor, ...]]:
    previous = {cursor.chatroom_id: cursor for cursor in cursors}
    next_cursors = dict(previous)
    messages: list[InboundMessage] = []
    for item in chatrooms:
        chatroom_id = item.get("chatroomId")
        if not isinstance(chatroom_id, str) or chatroom_id not in previous:
            raise ValueError("unknown shadow sync chatroom")
        raw_messages = item.get("messages")
        if not isinstance(raw_messages, list):
            raise ValueError("invalid shadow sync messages")
        for raw in raw_messages:
            parsed = _parse_message(chatroom_id, raw)
            if parsed is not None:
                messages.append(parsed)
        cursor = item.get("cursor")
        if cursor is not None:
            if not isinstance(cursor, dict):
                raise ValueError("invalid shadow sync cursor")
            cursor_at = cursor.get("at")
            cursor_message_id = cursor.get("messageId")
            if cursor_at is not None and not isinstance(cursor_at, str):
                raise ValueError("invalid shadow sync cursor timestamp")
            if cursor_message_id is not None and not isinstance(
                cursor_message_id, str
            ):
                raise ValueError("invalid shadow sync cursor message ID")
            old = previous[chatroom_id]
            next_cursors[chatroom_id] = ShadowSyncCursor(
                old.group_chat_id,
                chatroom_id,
                None if cursor_at is None else datetime.fromisoformat(
                    cursor_at.replace("Z", "+00:00")
                ),
                cursor_message_id,
            )
    messages.sort(key=lambda message: message.received_at)
    ordered_cursors = tuple(
        next_cursors[cursor.chatroom_id] for cursor in cursors
    )
    return tuple(messages), ordered_cursors


def _parse_message(
    chatroom_id: str, value: Any
) -> InboundMessage | None:
    if not isinstance(value, dict):
        return None
    content = value.get("content")
    message_id = value.get("message_id")
    sent_by = value.get("sent_by")
    sent_at = value.get("sent_at")
    if (
        not isinstance(content, dict)
        or content.get("type") != "text"
        or not isinstance(content.get("text"), str)
        or not isinstance(message_id, str)
        or not message_id
        or not isinstance(sent_by, str)
        or not sent_by
        or not isinstance(sent_at, str)
    ):
        return None
    return InboundMessage(
        message_id,
        sent_by,
        content["text"],
        _shanghai_time(sent_at),
        source_type="group",
        chatroom_id=chatroom_id,
        reference=_message_reference(content.get("reference")),
    )


def _response_error(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    error = body.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str):
            return message
    return None


def _error_summary(error: Exception) -> str:
    return (str(error).strip() or type(error).__name__)[:512]
