from datetime import UTC, datetime, timedelta
from random import Random
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, PRIMARY_GROUP_CHAT_ID


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


@pytest.fixture
def repository() -> CoreRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return CoreRepository(sessionmaker(engine, expire_on_commit=False), number_bomb_random=Random(1))


def _configure_market(repository: CoreRepository, now: datetime) -> None:
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=dark-market-room", now
    )
    settings = repository.get_dark_market_settings()
    repository.set_dark_market_settings(
        enabled=True,
        announcement_group_id=PRIMARY_GROUP_CHAT_ID,
        duration_hours=3,
        fee_percent=5,
        rank_limits={limit.rank_id: limit.daily_limit for limit in settings.rank_limits},
        expected_version=settings.version,
    )


def _complete_draft(
    repository: CoreRepository, platform_id: str, now: datetime
) -> None:
    assert repository.start_dark_market_draft(platform_id, now).status == "started"
    assert repository.advance_dark_market_draft(platform_id, "旧钥匙", now).step == "purpose"
    assert repository.advance_dark_market_draft(platform_id, "打开未知房门", now).step == "details"
    assert repository.advance_dark_market_draft(platform_id, "来历不明", now).step == "gender"
    assert repository.advance_dark_market_draft(platform_id, "保密", now).step == "starting_price"
    preview = repository.advance_dark_market_draft(platform_id, "10", now)
    assert preview.status == "preview"
    assert preview.step == "preview"
    assert "旧钥匙" in preview.preview_text


def test_dark_market_settings_seed_all_rank_limits(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)

    settings = repository.get_dark_market_settings()

    assert settings.enabled is True
    assert settings.announcement_group_id is None
    assert settings.duration_hours == 3
    assert settings.fee_percent == 5
    assert [limit.daily_limit for limit in settings.rank_limits] == [
        1, 1, 2, 2, 3, 3, 4, 4, 5, 5, -1
    ]


def test_dark_market_settings_require_an_enabled_listening_group(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    settings = repository.get_dark_market_settings()

    with pytest.raises(ValueError, match="暗网群聊不可用"):
        repository.set_dark_market_settings(
            enabled=True,
            announcement_group_id=uuid4(),
            duration_hours=3,
            fee_percent=5,
            rank_limits={limit.rank_id: limit.daily_limit for limit in settings.rank_limits},
            expected_version=settings.version,
        )


def test_dark_market_draft_resumes_and_rejects_invalid_field(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    _configure_market(repository, now)

    started = repository.start_dark_market_draft("seller", now)
    invalid = repository.advance_dark_market_draft("seller", "名" * 31, now)
    resumed = repository.start_dark_market_draft("seller", now + timedelta(minutes=1))

    assert started.status == "started"
    assert invalid.status == "invalid"
    assert invalid.step == "name"
    assert resumed.status == "resumed"
    assert resumed.step == "name"


def test_dark_market_draft_can_be_cancelled_and_expires(repository, now) -> None:
    repository.create_user("seller", "卖家", now, 100)
    _configure_market(repository, now)
    repository.start_dark_market_draft("seller", now)

    assert repository.cancel_dark_market_draft("seller", now).status == "cancelled"
    assert repository.cancel_dark_market_draft("seller", now).status == "no_draft"

    repository.start_dark_market_draft("seller", now)
    restarted = repository.start_dark_market_draft(
        "seller", now + timedelta(minutes=31)
    )
    assert restarted.status == "started"
    assert restarted.step == "name"


def test_confirm_listing_consumes_quota_and_enqueues_anonymous_announcement(
    repository, now
) -> None:
    repository.create_user("seller", "真实卖家", now, 100)
    _configure_market(repository, now)
    _complete_draft(repository, "seller", now)

    result = repository.confirm_dark_market_listing("seller", uuid4(), now)

    assert result.status == "listed"
    assert result.listing is not None
    assert result.listing.public_number == 1
    assert result.listing.ends_at == now + timedelta(hours=3)
    assert result.listing.fee_percent_snapshot == 5
    outbound = repository.claim_outbound(
        "worker", now, 30, required_delivery_key="dark-market-room"
    )
    assert outbound is not None
    assert "暗网新商品 #1" in outbound.text
    assert "旧钥匙" in outbound.text
    assert "真实卖家" not in outbound.text
    assert "截止" not in outbound.text

    _complete_draft(repository, "seller", now)
    limited = repository.confirm_dark_market_listing("seller", uuid4(), now)
    assert limited.status == "daily_limit"


def test_listing_numbers_are_never_reused(repository, now) -> None:
    repository.create_user("seller-a", "卖家甲", now, 100)
    repository.create_user("seller-b", "卖家乙", now, 100)
    _configure_market(repository, now)
    _complete_draft(repository, "seller-a", now)
    _complete_draft(repository, "seller-b", now)

    first = repository.confirm_dark_market_listing("seller-a", uuid4(), now)
    second = repository.confirm_dark_market_listing("seller-b", uuid4(), now)

    assert first.listing is not None
    assert second.listing is not None
    assert (first.listing.public_number, second.listing.public_number) == (1, 2)
