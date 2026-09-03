import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dzmm_bot.runtime.settings import Settings


def test_settings_requires_nonempty_database_url_and_core_token(monkeypatch):
    monkeypatch.delenv("DZMM_DATABASE_URL", raising=False)
    monkeypatch.delenv("DZMM_CORE_TOKEN", raising=False)

    with pytest.raises(ValueError, match="DZMM_DATABASE_URL"):
        Settings.from_environment()


def test_settings_uses_isolated_default_browser_port(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm:x@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-token")

    assert Settings.from_environment().browser_cdp_port == 19222


def test_settings_defaults_outbound_concurrency_to_four(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm:x@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-token")
    monkeypatch.delenv("DZMM_OUTBOUND_CONCURRENCY", raising=False)

    assert Settings.from_environment().outbound_concurrency == 4


@pytest.mark.parametrize("value", ["0", "17", "invalid"])
def test_settings_rejects_invalid_outbound_concurrency(monkeypatch, value):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm:x@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-token")
    monkeypatch.setenv("DZMM_OUTBOUND_CONCURRENCY", value)

    with pytest.raises(ValueError, match="DZMM_OUTBOUND_CONCURRENCY"):
        Settings.from_environment()


def test_settings_rejects_empty_secret_and_relative_browser_profile(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm:x@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "")

    with pytest.raises(ValueError, match="DZMM_CORE_TOKEN"):
        Settings.from_environment()

    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-token")
    monkeypatch.setenv("DZMM_BROWSER_PROFILE", "relative-profile")

    with pytest.raises(ValueError, match="DZMM_BROWSER_PROFILE"):
        Settings.from_environment()


def test_settings_treats_an_empty_login_url_as_not_configured(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm:x@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-token")
    monkeypatch.setenv("DZMM_LOGIN_URL", "")

    assert Settings.from_environment().login_url is None


def test_settings_reads_configured_group_chat_url(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-secret")
    monkeypatch.setenv("DZMM_CHAT_URL", "https://chat.example/chat?c=group-1")

    assert Settings.from_environment().chat_url == "https://chat.example/chat?c=group-1"


def test_settings_reads_optional_bot_api_token(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-secret")
    monkeypatch.setenv("DZMM_BOT_API_TOKEN", "bot-secret")

    assert Settings.from_environment().bot_api_token == "bot-secret"


def test_settings_reads_the_configured_long_message_bot_id(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-secret")
    monkeypatch.setenv("DZMM_BOT_ID", "311a2438-cff6-4986-b1d8-81396f8ca4ef")

    assert (
        Settings.from_environment().long_message_bot_id
        == "311a2438-cff6-4986-b1d8-81396f8ca4ef"
    )


def test_settings_reads_deepseek_runtime_configuration(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-secret")
    monkeypatch.setenv("DP_API_KEY", "deepseek-secret")

    settings = Settings.from_environment()

    assert settings.deepseek_api_key == "deepseek-secret"
    assert settings.deepseek_model == "deepseek-v4-flash"
    assert settings.deepseek_base_url == "https://api.deepseek.com"


def test_settings_does_not_reuse_the_legacy_generic_api_key(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "postgresql+psycopg://dzmm@localhost/dzmm")
    monkeypatch.setenv("DZMM_CORE_TOKEN", "core-secret")
    monkeypatch.delenv("DP_API_KEY", raising=False)
    monkeypatch.setenv("API_KEY", "legacy-secret")

    assert Settings.from_environment().deepseek_api_key is None
