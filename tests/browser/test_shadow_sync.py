from datetime import UTC, datetime
from threading import Event
from time import monotonic, sleep
from uuid import UUID
import json

import httpx

from dzmm_bot.browser.shadow_sync import (
    ShadowSyncCursor,
    ShadowSyncRequest,
    ShadowSyncRunner,
)


NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)
GROUP_ID = UUID("00000000-0000-0000-0000-000000000101")


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        return None


def request() -> ShadowSyncRequest:
    return ShadowSyncRequest(
        origin="https://www.aikda.com",
        cookie="session=cookie-value",
        access_token="access-token",
        cursors=(
            ShadowSyncCursor(
                GROUP_ID,
                "group-a",
                NOW,
                "message-8",
            ),
        ),
    )


def response(status_code, payload=None):
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://www.aikda.com/api/trpc/test"),
    )


def take_result(runner):
    deadline = monotonic() + 2
    while monotonic() < deadline:
        result = runner.take_result()
        if result is not None:
            return result
        sleep(0.01)
    raise AssertionError("shadow sync did not finish")


def test_shadow_sync_encodes_cursors_and_parses_valid_text_messages():
    client = FakeClient(
        response(
            200,
            {
                "result": {
                    "data": {
                        "json": {
                            "chatrooms": [
                                {
                                    "chatroomId": "group-a",
                                    "messages": [
                                        {
                                            "message_id": "message-9",
                                            "sent_by": "user-a",
                                            "sent_at": "2026-08-19T12:00:01Z",
                                            "content": {
                                                "type": "text",
                                                "text": "/余额",
                                            },
                                        },
                                        {
                                            "message_id": "image-1",
                                            "sent_by": "user-a",
                                            "sent_at": "2026-08-19T12:00:02Z",
                                            "content": {"type": "image"},
                                        },
                                    ],
                                    "cursor": {
                                        "at": "2026-08-19T12:00:01Z",
                                        "messageId": "message-9",
                                    },
                                }
                            ]
                        }
                    }
                }
            },
        )
    )
    runner = ShadowSyncRunner(client=client)

    assert runner.submit(request()) is True
    result = take_result(runner)
    runner.close()

    assert result.status == "healthy"
    assert [message.platform_message_id for message in result.messages] == [
        "message-9"
    ]
    assert result.messages[0].chatroom_id == "group-a"
    assert result.cursors[0].message_id == "message-9"
    url, kwargs = client.calls[0]
    assert url == "https://www.aikda.com/api/trpc/chatroom.syncChatroomMessages"
    assert kwargs["headers"]["Cookie"] == "session=cookie-value"
    assert kwargs["headers"]["Authorization"] == "Bearer access-token"
    encoded = json.loads(kwargs["params"]["input"])
    assert encoded["json"]["chatrooms"] == [
        {
            "chatroomId": "group-a",
            "cursorAt": NOW.isoformat(),
            "cursorMessageId": "message-8",
        }
    ]


def test_shadow_sync_classifies_captcha_without_advancing_cursor():
    runner = ShadowSyncRunner(
        client=FakeClient(response(418, {"error": "captcha_required"}))
    )

    assert runner.submit(request()) is True
    result = take_result(runner)
    runner.close()

    assert result.status == "captcha_required"
    assert result.cursors == request().cursors
    assert result.messages == ()


def test_shadow_sync_classifies_auth_timeout_server_and_invalid_responses():
    cases = [
        (FakeClient(response(401)), "auth_required"),
        (FakeClient(response(403)), "auth_required"),
        (FakeClient(response(503)), "retrying"),
        (FakeClient(error=httpx.ReadTimeout("slow")), "retrying"),
        (FakeClient(response(200, {"unexpected": True})), "retrying"),
    ]
    for client, expected in cases:
        runner = ShadowSyncRunner(client=client)
        assert runner.submit(request()) is True
        result = take_result(runner)
        runner.close()
        assert result.status == expected
        assert result.cursors == request().cursors


def test_shadow_sync_allows_only_one_inflight_request():
    entered = Event()
    release = Event()

    class BlockingClient(FakeClient):
        def get(self, url, **kwargs):
            entered.set()
            release.wait(1)
            return response(418, {"error": "captcha_required"})

    runner = ShadowSyncRunner(client=BlockingClient())

    assert runner.submit(request()) is True
    assert entered.wait(1)
    assert runner.submit(request()) is False
    release.set()
    assert take_result(runner).status == "captcha_required"
    runner.close()
