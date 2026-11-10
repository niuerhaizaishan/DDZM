import hashlib
import hmac
import re
from urllib.parse import urlsplit
from uuid import UUID


WORKSTATION_LAYERS = {
    "monitor-main": 20,
    "monitor-left": 10,
    "monitor-right": 10,
    "screen-light": 30,
    "keyboard": 40,
    "mouse": 40,
    "desk-lamp": 40,
    "handheld": 40,
    "pc": 40,
    "chair": 60,
}


def normalize_workstation_public_url(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("DZMM_WORKSTATION_PUBLIC_URL is not a valid HTTP(S) URL") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(character.isspace() or character in "\\<>\"" for character in value)
        or (port is not None and port == 0)
        or any(segment in {".", ".."} for segment in parsed.path.split("/"))
    ):
        raise ValueError("DZMM_WORKSTATION_PUBLIC_URL must be an HTTP(S) base URL without credentials, query or fragment")
    return value


def normalize_workstation_game_url(value: str | None) -> str | None:
    try:
        value = normalize_workstation_public_url(value)
    except ValueError as error:
        raise ValueError(str(error).replace("DZMM_WORKSTATION_PUBLIC_URL", "DZMM_WORKSTATION_GAME_URL")) from error
    if value is not None and urlsplit(value).scheme != "https":
        raise ValueError("DZMM_WORKSTATION_GAME_URL must use HTTPS")
    return value


class WorkstationLinks:
    def __init__(self, secret: str, public_url: str | None = None, *, game_url: str | None = None):
        if not secret:
            raise ValueError("workstation signing secret must be nonempty")
        self._secret = secret.encode("utf-8")
        self.public_url = normalize_workstation_public_url(public_url)
        self.game_url = normalize_workstation_game_url(game_url)
        game = urlsplit(self.game_url) if self.game_url else None
        card = re.fullmatch(r"/character/([1-9][0-9]*)", game.path) if game else None
        self.game_card_id = (
            card.group(1)
            if card and game.hostname in {"dzmm.ai", "www.dzmm.ai"} and game.port in {None, 443}
            else None
        )

    def token_for(self, user_id: UUID) -> str:
        identifier = user_id.hex
        signature = hmac.new(
            self._secret, f"workstation-view:v1:{identifier}".encode("ascii"), hashlib.sha256
        ).hexdigest()
        return f"{identifier}.{signature}"

    def user_id_for(self, token: str) -> UUID | None:
        if not re.fullmatch(r"[0-9a-f]{32}\.[0-9a-f]{64}", token):
            return None
        user_id = UUID(hex=token[:32])
        return user_id if hmac.compare_digest(token, self.token_for(user_id)) else None

    def url_for(self, user_id: UUID) -> str | None:
        if self.public_url is None:
            return None
        return f"{self.public_url}/workstation/{self.token_for(user_id)}"
