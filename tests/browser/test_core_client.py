from datetime import UTC, datetime
import json

import httpx

from dzmm_bot.runtime.contracts import (
    DirectChatRoom,
    GroupChatRuntimeUpdate,
    InboundMessage,
    LoginState,
    MessageReference,
)


def test_core_client_syncs_group_targets_and_runtime():
    from dzmm_bot.browser.core_client import CoreClient
    from uuid import UUID

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path, request.content))
        if request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "group_chat_id": "00000000-0000-0000-0000-000000000101",
                        "chatroom_id": "group-a",
                        "chat_url": "https://www.aikda.com/chat?c=group-a",
                    }
                ],
            )
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test", transport=httpx.MockTransport(handler)
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    [target] = client.group_chat_targets()
    accepted = client.sync_group_chat_runtime(
        "worker-a",
        (
            GroupChatRuntimeUpdate(
                target.group_chat_id, "connected", last_connected_at=now
            ),
        ),
        now,
    )
    assert target.chatroom_id == "group-a"
    assert accepted is True
    runtime_payload = json.loads(requests[1][2])
    assert runtime_payload["statuses"][0] == {
        "group_chat_id": str(UUID("00000000-0000-0000-0000-000000000101")),
        "connection_state": "connected",
        "last_connected_at": now.isoformat(),
        "last_inbound_at": None,
        "last_outbound_at": None,
        "last_error_summary": None,
    }


def test_core_client_heartbeat_reports_actual_and_returns_desired_listener_state():
    from dzmm_bot.browser.core_client import CoreClient

    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "worker_id": "worker-a",
                "login_state": "ready",
                "recorded_at": "2026-08-05T20:00:00+08:00",
                "listening": True,
                "listening_desired": False,
            },
        )

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    desired = client.heartbeat(
        "worker-a",
        LoginState.READY,
        True,
        now,
        "饭饭（小狗青巫）.",
        "captcha_required",
        "captcha_required",
    )

    assert observed == {
        "path": "/internal/heartbeat",
        "payload": {
            "worker_id": "worker-a",
            "login_state": "ready",
            "listening": True,
            "account_display_name": "饭饭（小狗青巫）.",
            "bot_delivery_state": "captcha_required",
            "bot_delivery_error": "captcha_required",
            "recorded_at": now.isoformat(),
        },
    }
    assert desired is False


def test_core_client_runs_daily_jobs():
    from dzmm_bot.browser.core_client import CoreClient

    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["method"] = request.method
        observed["path"] = request.url.path
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    client.run_daily_jobs(now)

    assert observed == {
        "method": "POST",
        "path": "/internal/daily-jobs/run",
        "payload": {"now": now.isoformat()},
    }


def test_core_client_syncs_discovered_direct_chatrooms():
    from dzmm_bot.browser.core_client import CoreClient

    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    client.sync_direct_chats([DirectChatRoom("employee-1", "direct-1")], now)

    assert observed == {
        "path": "/internal/direct-chats/sync",
        "payload": {
            "rooms": [{"platform_user_id": "employee-1", "chatroom_id": "direct-1"}],
            "now": now.isoformat(),
        },
    }


def test_core_client_releases_a_timed_out_outbound_with_a_retry_delay():
    from dzmm_bot.browser.core_client import CoreClient
    from uuid import UUID

    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["path"] = request.url.path
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    message_id = UUID("00000000-0000-0000-0000-000000000001")
    lease_token = UUID("00000000-0000-0000-0000-000000000002")
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    client.release_outbound(message_id, "worker-a", lease_token, now)

    assert observed == {
        "path": f"/internal/outbound/{message_id}/retry",
        "payload": {
            "worker_id": "worker-a",
            "lease_token": str(lease_token),
            "now": now.isoformat(),
            "retry_delay_seconds": 5,
        },
    }


def test_core_client_serializes_provenance_and_fetches_direct_inbound_rooms():
    from dzmm_bot.browser.core_client import CoreClient

    observed = []

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.method == "GET":
            return httpx.Response(200, json={"chatroom_ids": ["direct-1"]})
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    rooms = client.direct_inbound_chatroom_ids()
    client.submit_inbound(
        InboundMessage(
            "direct-message-1", "employee-1", "/报数 29", now,
            source_type="direct", chatroom_id="direct-1",
        )
    )

    assert rooms == ("direct-1",)
    assert observed == [
        ("GET", "/internal/direct-inbound/rooms", None),
        (
            "POST",
            "/internal/inbound",
            {
                "platform_message_id": "direct-message-1",
                "sender_platform_id": "employee-1",
                "content": "/报数 29",
                "received_at": now.isoformat(),
                "source_type": "direct",
                "chatroom_id": "direct-1",
            },
        ),
    ]


def test_core_client_serializes_referenced_image():
    """Fails if the Worker-to-core HTTP request omits image reply metadata."""
    from dzmm_bot.browser.core_client import CoreClient

    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    client.submit_inbound(
        InboundMessage(
            "reply-1",
            "employee-1",
            "/编辑档案形象",
            now,
            reference=MessageReference(
                message_id="image-1",
                sender_platform_id="employee-2",
                content_type="image",
                image_url="https://cdn.example.test/profile.png",
                alt="profile.png",
                width=1254,
                height=1254,
                blurhash="UsK-k9",
            ),
        )
    )

    assert observed["reference"] == {
        "message_id": "image-1",
        "sender_platform_id": "employee-2",
        "content_type": "image",
        "image_url": "https://cdn.example.test/profile.png",
        "alt": "profile.png",
        "width": 1254,
        "height": 1254,
        "blurhash": "UsK-k9",
    }


def test_core_client_serializes_direct_image_inbound():
    from dzmm_bot.browser.core_client import CoreClient

    observed = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed.update(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test",
        "token",
        client=httpx.Client(
            base_url="http://core.test",
            transport=httpx.MockTransport(handler),
        ),
    )
    now = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)

    client.submit_inbound(
        InboundMessage(
            "cover-1",
            "employee-1",
            "[图片]",
            now,
            source_type="direct",
            chatroom_id="direct-1",
            content_type="image",
            image_url="https://cdn.example/cover.webp",
            image_alt="公演封面",
            image_width=1200,
            image_height=800,
        )
    )

    assert observed == {
        "platform_message_id": "cover-1",
        "sender_platform_id": "employee-1",
        "content": "[图片]",
        "received_at": now.isoformat(),
        "source_type": "direct",
        "chatroom_id": "direct-1",
        "content_type": "image",
        "image_url": "https://cdn.example/cover.webp",
        "image_alt": "公演封面",
        "image_width": 1200,
        "image_height": 800,
    }


def test_core_client_deserializes_image_outbound_claim():
    from dzmm_bot.browser.core_client import CoreClient

    message_id = "00000000-0000-0000-0000-000000000001"
    lease_token = "00000000-0000-0000-0000-000000000002"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "id": message_id, "inbound_message_id": None, "text": "",
            "content_type": "image", "image_url": "https://cdn.example.com/profile.png",
            "image_alt": "档案形象", "lease_token": lease_token,
            "lease_expires_at": "2026-08-13T12:00:30Z", "attempt_count": 1,
            "destination_chatroom_id": None, "delivery_kind": "group",
            "recall_after_seconds": None,
        })

    client = CoreClient(
        "http://core.test", "token",
        client=httpx.Client(base_url="http://core.test", transport=httpx.MockTransport(handler)),
    )
    claim = client.claim_outbound("worker-a", datetime(2026, 8, 13, tzinfo=UTC), 30)

    assert claim.content_type == "image"
    assert claim.image_url == "https://cdn.example.com/profile.png"
    assert claim.image_alt == "档案形象"


def test_core_client_claims_and_completes_profile_image_upload():
    from dzmm_bot.browser.core_client import CoreClient

    observed = []
    task_id = "00000000-0000-0000-0000-000000000003"
    lease_token = "00000000-0000-0000-0000-000000000004"

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={
                "id": task_id, "temp_path": "/tmp/profile.png",
                "original_filename": "profile.png", "mime_type": "image/png",
                "expected_profile_version": 2, "lease_token": lease_token,
                "attempt_count": 1,
            })
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test", "token",
        client=httpx.Client(base_url="http://core.test", transport=httpx.MockTransport(handler)),
    )
    now = datetime(2026, 8, 13, tzinfo=UTC)

    claim = client.claim_profile_image_upload("worker-a", now, 30)
    accepted = client.complete_profile_image_upload(
        claim.id, "worker-a", claim.lease_token,
        "https://cdn.example.com/profile.png", now,
    )

    assert claim.temp_path == "/tmp/profile.png"
    assert accepted is True
    assert observed[1] == (
        f"/internal/profile-image-uploads/{task_id}/completed",
        {
            "worker_id": "worker-a", "lease_token": lease_token,
            "result_url": "https://cdn.example.com/profile.png",
            "now": now.isoformat(),
        },
    )


def test_core_client_claims_and_completes_profile_image_cleanup():
    from dzmm_bot.browser.core_client import CoreClient

    observed = []
    task_id = "00000000-0000-0000-0000-000000000005"
    lease_token = "00000000-0000-0000-0000-000000000006"

    def handler(request: httpx.Request) -> httpx.Response:
        observed.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={
                "id": task_id, "temp_path": "/tmp/superseded.png",
                "lease_token": lease_token,
            })
        return httpx.Response(200, json={"accepted": True})

    client = CoreClient(
        "http://core.test", "token",
        client=httpx.Client(base_url="http://core.test", transport=httpx.MockTransport(handler)),
    )
    now = datetime(2026, 8, 13, tzinfo=UTC)

    claim = client.claim_profile_image_cleanup("worker-a", now, 30)
    client.complete_profile_image_cleanup(
        claim.id, "worker-a", claim.lease_token, now
    )

    assert claim.temp_path == "/tmp/superseded.png"
    assert observed[1] == (
        f"/internal/profile-image-cleanups/{task_id}/completed",
        {
            "worker_id": "worker-a", "lease_token": lease_token,
            "now": now.isoformat(),
        },
    )
