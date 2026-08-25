import tomllib
from pathlib import Path


def test_admin_web_assets_are_declared_as_package_data():
    project = tomllib.loads(Path("pyproject.toml").read_text())

    assert project["tool"]["setuptools"]["package-data"]["dzmm_bot"] == [
        "admin/static/*.css",
        "admin/static/*.js",
        "admin/templates/*.html",
    ]


def test_packaged_admin_assets_include_red_packet_settings_surface():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'id="red-packet-settings-card"' in page
    assert 'id="red-packet-settings-modal"' in page
    assert 'id="save-red-packet-settings"' in page
    assert 'requestGame("/api/game/red-packet/settings")' in script
    assert 'method: "PATCH"' in script


def test_packaged_admin_assets_include_multi_group_surface():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()

    assert 'id="group-chats-view"' in page
    assert 'id="group-chat-modal"' in page
    assert 'id="employee-group-message-filter"' in page


def test_admin_bundle_contains_dark_market_controls():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'data-view="dark-market"' in page
    assert 'id="dark-market-settings-card"' in page
    assert 'id="dark-market-listings"' in page
    assert 'id="dark-market-settings-modal"' in page
    assert "/api/game/dark-market/listings" in script
    assert "force-delist-dark-market" in script


def test_admin_bundle_contains_shop_card_controls():
    root = Path(__file__).resolve().parents[2]
    page = (root / "src/dzmm_bot/admin/templates/index.html").read_text()
    script = (root / "src/dzmm_bot/admin/static/admin.js").read_text()

    assert 'id="group-chat-adult-shop-enabled"' in page
    assert 'id="shop-purchase-log"' in page
    assert 'id="shop-scene-job-list"' in page
    assert 'id="shop-common-state-list"' in page
    assert "/api/game/shop/activity" in script
    assert "data-retry-shop-scene" in script
    assert "data-end-shop-state" in script
