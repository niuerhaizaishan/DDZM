import httpx
import pytest

from dzmm_bot.core import performance


HTTPS_URL = "https://cdn.example/cover"


def _validator(body: bytes, status_code: int = 200):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)

    return performance.HttpCoverImageValidator(
        httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    )


@pytest.mark.parametrize(
    ("body", "mime_type"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"x" * 8, "image/png"),
        (b"\xff\xd8\xff" + b"x" * 8, "image/jpeg"),
        (b"RIFF\x0c\x00\x00\x00WEBP" + b"x" * 4, "image/webp"),
    ],
)
def test_cover_validator_accepts_supported_magic(body, mime_type) -> None:
    result = _validator(body).validate(HTTPS_URL)

    assert result.mime_type == mime_type
    assert result.byte_size == len(body)


def test_cover_validator_rejects_unsupported_magic() -> None:
    with pytest.raises(ValueError, match="JPEG、PNG、WebP"):
        _validator(b"not-an-image").validate(HTTPS_URL)


def test_cover_validator_stops_after_ten_mib() -> None:
    body = b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)

    with pytest.raises(ValueError, match="10MB"):
        _validator(body).validate(HTTPS_URL)


def test_cover_validator_rejects_redirects() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        _validator(b"", status_code=302).validate(HTTPS_URL)


def test_cover_validator_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _validator(b"anything").validate("http://cdn.example/cover")
