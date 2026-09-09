from urllib.parse import parse_qs, urlsplit

import httpx


class DzmmBotSendError(RuntimeError):
    pass


class DzmmBotSender:
    def __init__(self, api_token: str, *, client: httpx.Client | None = None) -> None:
        if not api_token:
            raise ValueError("Bot API token must be nonempty")
        self._client = client or httpx.Client(
            base_url="https://www.ivorune.xyz",
            headers={"X-Bot-Token": api_token},
            timeout=20,
        )
        if client is not None:
            self._client.headers["X-Bot-Token"] = api_token

    def send_to(self, chatroom_id: str, text: str) -> str:
        response = self._client.post(
            "/api/bot/send-message",
            json={"chatroom_id": chatroom_id, "content": text},
        )
        try:
            body = response.json()
        except ValueError as error:
            raise DzmmBotSendError("Bot API returned an invalid response") from error
        if response.status_code != 200 or body.get("ok") is not True:
            raise DzmmBotSendError(
                body.get("error") or f"Bot API request failed ({response.status_code})"
            )
        message_id = body.get("result", {}).get("message_id")
        if not isinstance(message_id, str) or not message_id:
            raise DzmmBotSendError("Bot API did not return a message ID")
        return message_id


def chatroom_id_from_url(chat_url: str) -> str:
    chatroom_id = parse_qs(urlsplit(chat_url).query).get("c", [None])[0]
    if not chatroom_id:
        raise ValueError("DZMM_CHAT_URL must include the group chat c parameter")
    return chatroom_id
