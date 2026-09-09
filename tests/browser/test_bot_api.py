import json

import httpx
import pytest


def test_bot_sender_posts_a_group_message_with_bot_token():
    from dzmm_bot.browser.bot_api import DzmmBotSender

    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": "platform-message-1"}},
        )

    sender = DzmmBotSender(
        "bot-token",
        client=httpx.Client(
            base_url="https://www.ivorune.xyz",
            transport=httpx.MockTransport(handle),
        ),
    )

    assert sender.send_to("group-1", "第一行\n第二行") == "platform-message-1"
    assert requests[0].url.path == "/api/bot/send-message"
    assert requests[0].headers["X-Bot-Token"] == "bot-token"
    assert json.loads(requests[0].content) == {
        "chatroom_id": "group-1",
        "content": "第一行\n第二行",
    }


def test_bot_sender_surfaces_the_platform_error():
    from dzmm_bot.browser.bot_api import DzmmBotSendError, DzmmBotSender

    sender = DzmmBotSender(
        "bot-token",
        client=httpx.Client(
            base_url="https://www.ivorune.xyz",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    403, json={"ok": False, "error": "bot is not installed"}
                )
            ),
        ),
    )

    with pytest.raises(DzmmBotSendError, match="bot is not installed"):
        sender.send_to("group-1", "测试")


def test_chatroom_id_is_read_from_the_configured_chat_url():
    from dzmm_bot.browser.bot_api import chatroom_id_from_url

    assert chatroom_id_from_url("https://www.ivorune.xyz/chat?c=group-1") == "group-1"


def test_chatroom_url_requires_the_group_query_parameter():
    from dzmm_bot.browser.bot_api import chatroom_id_from_url

    with pytest.raises(ValueError, match="c parameter"):
        chatroom_id_from_url("https://www.ivorune.xyz/chat")
