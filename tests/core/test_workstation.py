from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dzmm_bot.admin.app import create_app as create_admin_app
from dzmm_bot.admin.core_client import CoreClient
from dzmm_bot.admin.repository import AdminRepository
from dzmm_bot.core.app import create_app
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    Base, EquipmentItemRecord, EquipmentOwnershipRecord, EquipmentPurchaseRecord,
    OutboundRecord,
    RankRecord, UserRecord,
)
from dzmm_bot.core.service import CoreService
from dzmm_bot.core.workstation import WORKSTATION_LAYERS, WorkstationLinks
from dzmm_bot.runtime.contracts import InboundMessage
from dzmm_bot.runtime.settings import Settings


NOW = datetime(2026, 10, 15, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
SECRET = "workstation-test-core-secret"
PUBLIC_URL = "https://workstation.example.test"
GAME_URL = "https://www.dzmm.ai/character/3772306"


@pytest.fixture
def workstation_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=workstation-group", NOW)
    links = WorkstationLinks(SECRET, PUBLIC_URL)
    service = CoreService(repository, GroupCommandHandler(repository, workstation_links=links))

    def send(identifier, content, sender="owner"):
        result = service.receive_inbound(InboundMessage(
            identifier, sender, content, NOW, source_type="group", chatroom_id="workstation-group",
        ))
        with factory() as session:
            return "\n".join(session.scalars(select(OutboundRecord.text).where(
                OutboundRecord.inbound_message_id == result.message_id,
            )))

    send("join-owner", "/入职 糯糯")
    send("join-visitor", "/入职 小小糯", "visitor")
    owner = repository.find_user("owner")
    repository.record_balance_change(owner.id, 128 - owner.balance, "board_bonus", NOW)
    with TestClient(create_app(repository, SECRET, workstation_public_url=PUBLIC_URL)) as internal:
        def forward(request):
            response = internal.request(request.method, str(request.url), headers=request.headers, content=request.content)
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)
        with httpx.Client(
            base_url="http://core.test", headers={"X-Core-Token": SECRET},
            transport=httpx.MockTransport(forward),
        ) as http_client:
            core = CoreClient("http://core.test", SECRET, client=http_client)
            with TestClient(create_admin_app(
                "admin-test-secret", core, repository=AdminRepository(factory),
            )) as public:
                yield repository, factory, links, send, internal, public
    engine.dispose()


def test_group_command_sends_personal_link_and_nonmembers_cannot_get_one(workstation_context):
    repository, factory, links, send, _, _ = workstation_context
    owner = repository.find_user("owner")
    overview = send("my-workstation", "/我的工位")
    assert "糯糯的工位" in overview
    assert overview.endswith("预计工位日收入：0 摸鱼币。")
    assert "下一条消息" not in overview and "http" not in overview
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord).where(
            OutboundRecord.reference_message_id == "my-workstation")) == 1
    reply = send("workstation-game", "/工位游戏")
    assert f"{PUBLIC_URL}/workstation/{links.token_for(owner.id)}" in reply
    assert reply == links.url_for(owner.id)
    with factory() as session:
        records = session.scalars(select(OutboundRecord).where(OutboundRecord.text == links.url_for(owner.id))).all()
        assert len(records) == 1
        assert records[0].reply_index == 0
        assert records[0].reference_message_id is None
        assert records[0].reference_sender_platform_id is None
        assert records[0].reference_content_type is None
        assert records[0].reference_text is None
        assert records[0].destination_chatroom_id == "workstation-group"
        assert records[0].group_chat_id == repository.resolve_enabled_group_chat("workstation-group").id
        entry = list(session.scalars(select(OutboundRecord).where(
            OutboundRecord.inbound_message_id == records[0].inbound_message_id,
        )))
        assert len(entry) == 1
    send("workstation-game", "/工位游戏")
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(OutboundRecord).where(
            OutboundRecord.text == links.url_for(owner.id)
        )) == 1
    assert "owner" not in reply
    assert SECRET not in reply
    assert "请先使用 /入职" in send("unregistered", "/我的工位", "stranger")
    assert "请先使用 /入职" in send("unregistered-game", "/工位游戏", "stranger")
    assert links.token_for(repository.find_user("visitor").id) not in reply


def test_unconfigured_url_reports_unavailable_instead_of_localhost(workstation_context):
    repository, _, _, _, _, _ = workstation_context
    handler = GroupCommandHandler(repository)
    reply = handler.handle(InboundMessage(
        "unconfigured", "owner", "/工位游戏", NOW, source_type="group", chatroom_id="workstation-group",
    ))
    assert "请管理员配置公开访问地址" in reply
    assert "http" not in reply


def test_workstation_entry_commands_have_separate_switches_and_validate_usage(workstation_context):
    repository, factory, _, send, _, _ = workstation_context
    assert "用法：/工位游戏" in send("bad-game-args", "/工位游戏 2")
    handler = GroupCommandHandler(repository)
    direct = handler.handle(InboundMessage("direct-game", "owner", "/工位游戏", NOW, source_type="direct"))
    assert "群聊" in direct
    help_text = send("workstation-help", "/帮助 工位")
    assert "/我的工位：查看当前环境、设备与预计日收益" in help_text
    assert "/工位游戏：直接打开工位小游戏" in help_text
    repository.set_command_enabled("/我的工位", False)
    assert "http" in send("entry-with-overview-off", "/工位游戏")
    repository.set_command_enabled("/工位游戏", False)
    assert send("entry-disabled", "/工位游戏") == ""
    repository.set_command_enabled("/我的工位", True)
    overview = send("overview-with-game-off", "/我的工位")
    assert "糯糯的工位" in overview and "http" not in overview


def test_core_inbound_factory_uses_configured_link(workstation_context):
    repository, factory, links, _, internal, _ = workstation_context
    response = internal.post("/internal/inbound", headers={"X-Core-Token": SECRET}, json={
        "platform_message_id": "factory-command", "sender_platform_id": "owner",
        "content": "/工位游戏", "received_at": NOW.isoformat(),
        "source_type": "group", "chatroom_id": "workstation-group",
    })
    assert response.status_code == 200
    with factory() as session:
        replies = session.scalars(select(OutboundRecord.text)).all()
        assert any(links.url_for(repository.find_user("owner").id) in reply for reply in replies)


def test_game_entry_uses_platform_identity_without_changing_existing_personal_links(workstation_context):
    repository, factory, links, _, _, public = workstation_context
    owner = repository.find_user("owner")
    original_balance = owner.balance
    with TestClient(create_app(
        repository, SECRET, workstation_public_url=PUBLIC_URL, workstation_game_url=GAME_URL,
    )) as internal:
        for sender in ["owner", "visitor"]:
            message_id = f"platform-entry-{sender}"
            response = internal.post("/internal/inbound", headers={"X-Core-Token": SECRET}, json={
                "platform_message_id": message_id, "sender_platform_id": sender,
                "content": "/工位游戏", "received_at": NOW.isoformat(),
                "source_type": "group", "chatroom_id": "workstation-group",
            })
            assert response.status_code == 200
            repeated = internal.post("/internal/inbound", headers={"X-Core-Token": SECRET}, json={
                "platform_message_id": message_id, "sender_platform_id": sender,
                "content": "/工位游戏", "received_at": NOW.isoformat(),
                "source_type": "group", "chatroom_id": "workstation-group",
            })
            assert repeated.status_code == 200
            overview = internal.post("/internal/inbound", headers={"X-Core-Token": SECRET}, json={
                "platform_message_id": f"overview-{sender}", "sender_platform_id": sender,
                "content": "/我的工位", "received_at": NOW.isoformat(),
                "source_type": "group", "chatroom_id": "workstation-group",
            })
            assert overview.status_code == 200
        with factory() as session:
            replies = list(session.scalars(select(OutboundRecord.text)))
        for sender in ["owner", "visitor"]:
            employee = repository.find_user(sender)
            reply = next(text for text in replies if f"【{employee.display_name}的工位】" in text)
            assert GAME_URL not in reply
            assert reply.startswith(f"【{employee.display_name}的工位】\n环境：1级 临时办公角落【日收益：0】\n【设备】\n")
            assert reply.endswith("\n预计工位日收入：0 摸鱼币。")
            assert "下一条消息" not in reply
            assert "电脑：1-1 入门台式电脑【日收益：0】\n显示器：1-1 老旧显示器【日收益：0】\n键盘：1-1 老旧键盘【日收益：0】\n鼠标：1-1 老旧鼠标【日收益：0】\n" in reply
            assert "配件：" not in reply
            assert "当前 DZMM 登录账号" not in reply and "24小时" not in reply and "余额：" not in reply
            assert "/workstation/" not in reply
            assert links.token_for(employee.id) not in reply
        assert GAME_URL not in replies
        with factory() as session:
            link_records = session.scalars(select(OutboundRecord).where(OutboundRecord.content_type == "character")).all()
            assert len(link_records) == 2
            assert all(link.text == "3772306" and link.reply_index == 0 for link in link_records)
            for link in link_records:
                assert session.scalar(select(func.count()).select_from(OutboundRecord).where(
                    OutboundRecord.inbound_message_id == link.inbound_message_id)) == 1
            assert all(link.reference_message_id is None and link.reference_text is None for link in link_records)
            assert all(link.delivery_kind == "group" and link.destination_chatroom_id == "workstation-group" for link in link_records)
        claimed_cards = []
        for _ in range(20):
            claim = internal.post("/internal/outbound/claim", headers={"X-Core-Token": SECRET}, json={
                "worker_id": "share-card-regression", "now": NOW.isoformat(), "lease_seconds": 60,
            })
            assert claim.status_code == 200
            outbound = claim.json()
            if outbound is None:
                break
            if outbound["content_type"] == "character":
                claimed_cards.append(outbound)
                assert outbound["text"] == "3772306"
                assert outbound["destination_chatroom_id"] == "workstation-group"
                assert outbound["reference_message_id"] is None
            sent = internal.post(f"/internal/outbound/{outbound['id']}/sent", headers={"X-Core-Token": SECRET}, json={
                "worker_id": "share-card-regression", "lease_token": outbound["lease_token"],
                "platform_sent_id": "test-" + outbound["id"], "now": NOW.isoformat(),
            })
            assert sent.status_code == 200 and sent.json()["accepted"] is True
        assert len(claimed_cards) == 2
    assert repository.find_user("owner").balance == original_balance
    assert public.get(f"/api/workstations/{links.token_for(owner.id)}").status_code == 200


@pytest.mark.parametrize(("url", "card_id"), [
    (GAME_URL, "3772306"),
    ("https://dzmm.ai/character/3772306/", "3772306"),
    ("https://www.dzmm.ai/character/0", None),
    ("https://www.dzmm.ai/character/3772306/extra", None),
    ("https://www.dzmm.ai/character/8c0c9601-1a72-42f7-b379-120adf63886d", None),
    ("https://example.test/character/3772306", None),
    ("https://www.dzmm.ai:8443/character/3772306", None),
    (None, None),
])
def test_game_card_id_is_only_derived_from_platform_card_url(url, card_id):
    assert WorkstationLinks(SECRET, PUBLIC_URL, game_url=url).game_card_id == card_id


def test_custom_game_entry_still_sends_standalone_text_link(workstation_context):
    repository, _, _, _, _, _ = workstation_context
    url = "https://games.example.test/workstation"
    handler = GroupCommandHandler(repository, workstation_links=WorkstationLinks(SECRET, game_url=url))
    reply = handler.handle(InboundMessage(
        "custom-game-entry", "owner", "/工位游戏", NOW,
        source_type="group", chatroom_id="workstation-group",
    ))
    assert reply.text == url
    assert reply.content_type == "text"
    assert reply.reference_inbound is False


def test_public_view_reads_actual_equipment_and_refreshes_without_charging(workstation_context):
    repository, factory, links, send, _, public = workstation_context
    token = links.token_for(repository.find_user("owner").id)
    path = f"/api/workstations/{token}"
    assert public.get(path).json()["equipped"] == []
    initial_scene = public.get(path).json()["progression"]["scene"]
    assert len(initial_scene["layers"]) == 9
    assert all(item["level"] == 1 for item in initial_scene["layers"])
    with factory.begin() as session:
        session.get(UserRecord, repository.find_user("owner").id).rank_id = session.scalar(
            select(RankRecord.id).where(RankRecord.sort_order == 2))
    assert "升级成功" in send("buy", "/升级装备 6")
    response = public.get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["daily_income"] == 2
    assert response.json()["equipped"] == []  # retained legacy ownership is separate
    upgraded_scene = response.json()["progression"]["scene"]
    assert next(item for item in upgraded_scene["layers"] if item["key"] == "computer")["level"] == 2
    assert initial_scene != upgraded_scene
    assert response.json()["progression"]["components"][5]["active_level"] == 2
    assert "balance" not in response.json() and "upgrade_credit" not in response.json()
    visitor_token = links.token_for(repository.find_user("visitor").id)
    assert public.get(f"/api/workstations/{visitor_token}").json()["equipped"] == []
    assert public.get(path).json()["daily_income"] == 2
    assert "我的养成" in public.get(f"/workstation/{token}").text
    send("remove", "/卸下 6")
    assert public.get(path).json()["daily_income"] == 0
    assert "computer" not in {item["key"] for item in public.get(path).json()["progression"]["scene"]["layers"]}
    assert repository.find_user("owner").balance == 108
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(EquipmentOwnershipRecord)) == 0
        assert session.scalar(select(func.count()).select_from(EquipmentPurchaseRecord)) == 0


def test_public_view_cannot_mutate_or_authorize_admin_endpoints(workstation_context):
    repository, _, links, _, internal, public = workstation_context
    token = links.token_for(repository.find_user("owner").id)
    assert internal.get(f"/internal/workstations/{token}").status_code == 401
    assert public.post(f"/api/workstations/{token}", json={"equipped": [1]}).status_code == 405
    assert public.get("/api/status", headers={"X-Admin-Token": token}).status_code == 401
    assert public.get("/api/integration/users/owner/balance", headers={"X-Api-Key": token}).status_code in {401, 503}


@pytest.mark.parametrize("invalid", ["invalid", "0" * 32 + "." + "0" * 64, "signed-unknown", "tampered"])
def test_invalid_or_unknown_workstation_returns_friendly_404(workstation_context, invalid):
    repository, _, links, _, _, public = workstation_context
    if invalid == "signed-unknown":
        invalid = links.token_for(uuid4())
    elif invalid == "tampered":
        invalid = links.token_for(repository.find_user("owner").id)
        invalid = invalid[:-1] + ("0" if invalid[-1] != "0" else "1")
    for prefix in ("/workstation/", "/api/workstations/"):
        response = public.get(prefix + invalid)
        assert response.status_code == 404
        assert "重新发送 /工位游戏" in response.text


def test_assets_are_packaged_and_public_page_does_not_use_demo_state(workstation_context):
    repository, _, links, _, _, public = workstation_context
    token = links.token_for(repository.find_user("owner").id)
    response = public.get(f"/workstation/{token}")
    assert response.status_code == 200
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "img-src 'self' data:" in response.headers["content-security-policy"]
    assert "default-src 'self';" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert SECRET not in response.text
    script = public.get("/static/workstation.js")
    assert script.status_code == 200
    assert "localStorage" not in script.text
    assert "innerHTML" not in script.text
    assert "credentials: \"omit\"" in script.text
    assert public.get("/static/workstation.css").status_code == 200
    for name in ["core-base.png", *(f"{key}-layer.png" for key in WORKSTATION_LAYERS)]:
        asset = public.get(f"/static/workstation/{name}")
        assert asset.status_code == 200
        assert asset.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert public.get("/static/workstation/manifest.json").status_code == 404
    from dzmm_bot.core.workstation_art import ART_FILENAMES
    assert len(ART_FILENAMES) == 90
    for name in ART_FILENAMES:
        asset = public.get(f"/static/workstation/{name}")
        assert asset.status_code == 200
        assert "immutable" in asset.headers["cache-control"]
        assert asset.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert public.get('/static/workstation/growth-invalid-desk-lv99.png').status_code == 404


@pytest.mark.parametrize("failure", ["unavailable", "upstream-error"])
def test_public_view_sanitizes_core_failures(workstation_context, failure):
    repository, factory, links, _, _, _ = workstation_context
    token = links.token_for(repository.find_user("owner").id)

    class UnavailableCore:
        def get_workstation(self, token):
            request = httpx.Request("GET", "http://core.test/internal/workstations/test")
            if failure == "unavailable":
                raise httpx.ConnectError("private connection details", request=request)
            response = httpx.Response(500, text="private database details", request=request)
            response.raise_for_status()

    with TestClient(create_admin_app("admin-test-secret", UnavailableCore(), repository=AdminRepository(factory))) as client:
        for prefix in ("/workstation/", "/api/workstations/"):
            response = client.get(prefix + token)
            assert response.status_code == 503
            assert "稍后重试" in response.text
            assert "private" not in response.text


def test_public_read_does_not_seed_missing_catalog(workstation_context):
    repository, factory, links, _, _, public = workstation_context
    with factory.begin() as session:
        session.query(EquipmentItemRecord).delete()
    token = links.token_for(repository.find_user("owner").id)
    assert public.get(f"/api/workstations/{token}").status_code == 200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(EquipmentItemRecord)) == 0


def test_changing_signing_key_invalidates_old_links():
    identifier = UUID("00000000-0000-0000-0000-000000000001")
    old = WorkstationLinks("old-test-key", PUBLIC_URL)
    new = WorkstationLinks("new-test-key", PUBLIC_URL)
    token = old.token_for(identifier)
    assert old.user_id_for(token) == identifier
    assert new.user_id_for(token) is None
    assert old.user_id_for(str(identifier)) is None
    assert old.url_for(identifier) == old.url_for(identifier)


@pytest.mark.parametrize("value", [
    "javascript:alert(1)", "https://user:password@example.test", "https://example.test?a=b",
    "https://example.test#token", "https://example.test/../admin", "https://example.test:bad",
    "https://example.test:0", "https://example.test/with space", "https://example.test\\evil", "https://[invalid",
])
def test_settings_rejects_unsafe_public_url(monkeypatch, value):
    monkeypatch.setenv("DZMM_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("DZMM_CORE_TOKEN", SECRET)
    monkeypatch.setenv("DZMM_BROWSER_PROFILE", str(Path.cwd() / "output" / "test-browser"))
    monkeypatch.setenv("DZMM_WORKSTATION_PUBLIC_URL", value)
    with pytest.raises(ValueError, match="DZMM_WORKSTATION_PUBLIC_URL"):
        Settings.from_environment()


def test_settings_supports_optional_url_and_proxy_prefix(monkeypatch):
    monkeypatch.setenv("DZMM_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("DZMM_CORE_TOKEN", SECRET)
    monkeypatch.setenv("DZMM_BROWSER_PROFILE", str(Path.cwd() / "output" / "test-browser"))
    monkeypatch.delenv("DZMM_WORKSTATION_PUBLIC_URL", raising=False)
    monkeypatch.delenv("DZMM_WORKSTATION_GAME_URL", raising=False)
    assert Settings.from_environment().workstation_public_url is None
    assert Settings.from_environment().workstation_game_url is None
    monkeypatch.setenv("DZMM_WORKSTATION_PUBLIC_URL", PUBLIC_URL + "/games/")
    assert Settings.from_environment().workstation_public_url == PUBLIC_URL + "/games"
    monkeypatch.setenv("DZMM_WORKSTATION_GAME_URL", GAME_URL + "/")
    assert Settings.from_environment().workstation_game_url == GAME_URL


@pytest.mark.parametrize("value", ["http://www.dzmm.ai/character/3772306", "https://user:password@example.test", "https://example.test?token=private"])
def test_settings_rejects_unsafe_game_entry_url(monkeypatch, value):
    monkeypatch.setenv("DZMM_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("DZMM_CORE_TOKEN", SECRET)
    monkeypatch.setenv("DZMM_BROWSER_PROFILE", str(Path.cwd() / "output" / "test-browser"))
    monkeypatch.setenv("DZMM_WORKSTATION_GAME_URL", value)
    with pytest.raises(ValueError, match="DZMM_WORKSTATION_GAME_URL"):
        Settings.from_environment()


def test_stage5_reads_saved_upgrades_name_and_unequip_without_extra_charges(workstation_context):
    from io import BytesIO
    from PIL import Image
    from dzmm_bot.browser.workstation_image import render_workstation_image
    from dzmm_bot.core.schema import WorkstationComponentRecord, WorkstationUpgradeRecord
    from dzmm_bot.core.workstation_stage5 import STAGE5_FILENAMES

    repository, factory, links, send, _, public = workstation_context
    owner = repository.find_user('owner')
    repository.record_balance_change(owner.id, 2000-owner.balance, 'board_bonus', NOW)
    with factory.begin() as session:
        session.get(UserRecord, owner.id).rank_id = session.scalar(select(RankRecord.id).where(RankRecord.is_board.is_(True)))
        for number in range(1,10):
            session.add(WorkstationComponentRecord(user_id=owner.id, category_number=number,
                highest_level=9 if number==6 else 10, active_level=9, equipped=True))
    path = f'/api/workstations/{links.token_for(owner.id)}'
    before = public.get(path).json()
    assert 'accessory_scene' in before['progression']
    assert len(before['progression']['accessory_scene']['layers']) == 5
    reply = send('stage5-upgrade', '/升级装备 6')
    assert '升级成功' in reply and '800' in reply
    upgraded = public.get(path).json()
    keys = {item['key'] for item in upgraded['progression']['accessory_scene']['layers']}
    assert not {'headphones','microphone','handheld'} & keys
    assert not {'console','pen-display','desk-mat','speakers'} & keys
    assert upgraded['progression']['components'][5]['active_level'] == 10
    assert repository.find_user('owner').balance == 1200
    send('stage5-upgrade', '/升级装备 6')  # Replayed inbound must not buy twice.
    assert repository.find_user('owner').balance == 1200
    send('stage5-rename', '/修改名称 糯糯的新工位')
    named = public.get(path).json()
    assert named['display_name'] == '糯糯的新工位'
    visitor=public.get(f'/api/workstations/{links.token_for(repository.find_user("visitor").id)}').json()['progression']
    assert visitor['accessories']==[] and visitor['accessory_scene']['environment']==1
    output=BytesIO(); render_workstation_image(named,output)
    image=Image.open(output); assert image.size==(1536,1024) and image.mode=='RGBA'
    send('stage5-remove', '/卸下 6')
    removed = public.get(path).json()
    assert not {'computer-basic','computer-upgraded','headphones','microphone','handheld','computer-underlay'} & {
        item['key'] for item in removed['progression']['accessory_scene']['layers']}
    # The captured image still contains the former saved loadout after later mutations.
    captured=BytesIO(); render_workstation_image(named,captured); assert captured.getvalue()==output.getvalue()
    send('stage5-keyboard', '/装备 8 10')
    assert not {'console','pen-display'} & {item['key'] for item in public.get(path).json()['progression']['accessory_scene']['layers']}
    send('stage5-hide-chair', '/卸下 4')
    assert public.get(path).json()['progression']['accessory_scene']['environment'] == 5
    send('stage5-show-chair', '/装备 4 9')
    send('stage5-downgrade', '/装备 8 8')
    assert public.get(path).json()['progression']['accessory_scene']['environment'] == 5
    assert repository.find_user('owner').balance == 1200
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(WorkstationUpgradeRecord)) == 1
    for filename in STAGE5_FILENAMES:
        response=public.get('/static/workstation/'+filename)
        assert response.status_code==200 and 'immutable' in response.headers['cache-control']
    assert public.get('/static/workstation/stage5-invalid-base.png').status_code==404
