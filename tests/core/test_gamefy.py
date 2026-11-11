import base64
import json
from io import BytesIO
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from PIL import Image

from dzmm_bot.admin.app import create_app as create_admin_app
from dzmm_bot.admin.core_client import CoreClient
from dzmm_bot.admin.repository import AdminRepository
from dzmm_bot.core.app import create_app
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.gamefy import GamefyIdentityVerifier, JWKS_URL
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, EquipmentItemRecord, GroupChatRecord, InboundRecord, OutboundRecord, RankRecord, UserRecord
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage
from dzmm_bot.runtime.settings import Settings


GAME_ID = "3772306"
CORE_SECRET = "gamefy-test-core-only"
OWNER = str(uuid4())
VISITOR = str(uuid4())


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def signed_token(signing_key, **overrides):
    now = datetime.now(timezone.utc)
    claims = {
        "sub": OWNER, "iss": "dzmm-gamefy", "aud": GAME_ID,
        "iat": now, "exp": now + timedelta(minutes=30), **overrides,
    }
    return jwt.encode(claims, signing_key, algorithm="RS256", headers={"kid": "test-key"})


@pytest.fixture
def gamefy_keys(signing_key, monkeypatch):
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
    public.update(kid="test-key", alg="RS256", use="sig")
    calls = []

    def fetch(opener, request, **kwargs):
        assert request.full_url == JWKS_URL
        assert request.get_header("User-agent") == "DDZM-Workstation/1.0"
        assert request.get_header("Accept") == "application/json"
        calls.append(request.full_url)
        return BytesIO(json.dumps({"keys": [public]}).encode())

    monkeypatch.setattr("urllib.request.OpenerDirector.open", fetch)
    return calls


def test_rs256_verification_uses_fixed_jwks_and_caches_public_keys(signing_key, gamefy_keys):
    verifier = GamefyIdentityVerifier(GAME_ID)
    token = signed_token(signing_key)
    assert verifier.verify(token) == OWNER
    assert verifier.verify(token) == OWNER
    assert gamefy_keys == [JWKS_URL]


def test_platform_uuid_game_audience_is_distinct_from_numeric_card_id(signing_key, gamefy_keys):
    game_id = str(uuid4())
    verifier = GamefyIdentityVerifier(game_id)
    assert verifier.verify(signed_token(signing_key, aud=game_id)) == OWNER
    for audience in [GAME_ID, str(uuid4())]:
        with pytest.raises(HTTPException) as error:
            verifier.verify(signed_token(signing_key, aud=audience))
        assert error.value.status_code == 401


@pytest.mark.parametrize("claims", [
    {"aud": "another-game"}, {"aud": [GAME_ID, "another-game"]},
    {"iss": "another-issuer"}, {"sub": "not-a-platform-uuid"}, {"sub": None},
    {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
    {"iat": datetime.now(timezone.utc) + timedelta(hours=1)},
    {"exp": None},
])
def test_rejects_invalid_or_cross_game_claims(signing_key, gamefy_keys, claims):
    with pytest.raises(HTTPException) as error:
        GamefyIdentityVerifier(GAME_ID).verify(signed_token(signing_key, **claims))
    assert error.value.status_code == 401


def test_rejects_wrong_signature_algorithm_and_unknown_key(signing_key, gamefy_keys):
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in [
        signed_token(wrong_key),
        jwt.encode({"sub": OWNER}, "test-symmetric-secret-at-least-thirty-two-bytes", algorithm="HS256", headers={"kid": "test-key"}),
        jwt.encode({"sub": OWNER}, signing_key, algorithm="RS256", headers={"kid": "unknown-key"}),
        "malformed-token",
    ]:
        with pytest.raises(HTTPException) as error:
            GamefyIdentityVerifier(GAME_ID).verify(token)
        assert error.value.status_code == 401


def test_jwks_outage_is_retryable_without_leaking_details(signing_key, monkeypatch):
    verifier = GamefyIdentityVerifier(GAME_ID)

    def unavailable(token):
        raise jwt.PyJWKClientConnectionError("private network diagnostics")

    monkeypatch.setattr(verifier.keys, "get_signing_key_from_jwt", unavailable)
    with pytest.raises(HTTPException) as error:
        verifier.verify(signed_token(signing_key))
    assert error.value.status_code == 503
    assert "private" not in error.value.detail


@pytest.mark.parametrize("identifier", ["", "0", "-1", "other", "３７７２３０６"])
def test_invalid_game_configuration_fails_closed(identifier):
    with pytest.raises(ValueError):
        GamefyIdentityVerifier(identifier)


def test_environment_reads_optional_game_id(monkeypatch, tmp_path):
    monkeypatch.setenv("DZMM_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("DZMM_CORE_TOKEN", CORE_SECRET)
    monkeypatch.setenv("DZMM_BROWSER_PROFILE", str(tmp_path))
    monkeypatch.delenv("DZMM_GAMEFY_GAME_ID", raising=False)
    assert Settings.from_environment().gamefy_game_id is None
    monkeypatch.setenv("DZMM_GAMEFY_GAME_ID", GAME_ID)
    assert Settings.from_environment().gamefy_game_id == GAME_ID


@pytest.fixture
def gamefy_context(gamefy_keys):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    now = datetime.now(timezone.utc)
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=gamefy-test", now)
    service = CoreService(repository, GroupCommandHandler(repository))

    def send(identifier, text, sender=OWNER):
        service.receive_inbound(InboundMessage(
            identifier, sender, text, now, source_type="group", chatroom_id="gamefy-test",
        ))

    send("join-owner", "/入职 糯糯")
    send("join-visitor", "/入职 小小糯", VISITOR)
    owner = repository.find_user(OWNER)
    repository.record_balance_change(owner.id, 300 - owner.balance, "board_bonus", now)
    send("buy", "/购买装备 1")
    # Seed retained legacy art independently of the new progression commands.
    repository.purchase_equipment("buy", OWNER, 1, repository.resolve_enabled_group_chat("gamefy-test").id, now)
    repository.set_equipment_equipped(OWNER, 1, True)
    with TestClient(create_app(repository, CORE_SECRET, gamefy_game_id=GAME_ID)) as internal:
        def forward(request):
            response = internal.request(request.method, str(request.url), headers=request.headers, content=request.content)
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)
        with httpx.Client(base_url="http://core.test", headers={"X-Core-Token": CORE_SECRET}, transport=httpx.MockTransport(forward)) as transport:
            core = CoreClient("http://core.test", CORE_SECRET, client=transport)
            with TestClient(create_admin_app("admin-test-only", core, repository=AdminRepository(factory))) as public:
                yield SimpleNamespace(repository=repository, internal=internal, public=public, send=send)
    engine.dispose()


def test_game_reads_only_authenticated_players_equipped_items(gamefy_context, signing_key):
    context = gamefy_context
    path = "/api/gamefy/workstation"
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}", "Origin": "null"}
    balance = context.repository.find_user(OWNER).balance
    response = context.public.get(path + f"?user_id={VISITOR}", headers=headers)
    assert response.status_code == 200
    assert response.json()["display_name"] == "糯糯"
    assert response.json()["equipped"][0]["asset_key"] == "monitor-main"
    assert response.json()["daily_income"] == 0
    assert len(response.json()["progression"]["components"]) == 9
    assert response.json()["income_settlement_enabled"] is False
    assert response.json()["employee_number"] == "#0001"
    assert set(response.json()) == {"display_name", "employee_number", "share_groups", "equipped", "daily_income", "currency_name", "income_settlement_enabled", "progression"}
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["cache-control"] == "no-store"
    assert "access-control-allow-credentials" not in response.headers
    visitor = {"Authorization": f"Bearer {signed_token(signing_key, sub=VISITOR)}"}
    assert context.public.get(path, headers=visitor).json()["equipped"] == []
    context.repository.set_equipment_equipped(OWNER, 1, False)
    assert context.public.get(path, headers=headers).json()["equipped"] == []
    assert context.repository.find_user(OWNER).balance == balance
    assert CORE_SECRET not in response.text
    assert OWNER not in response.text


def test_sandbox_preflight_is_scoped_to_gamefy(gamefy_context):
    public = gamefy_context.public
    response = public.options("/api/gamefy/workstation", headers={
        "Origin": "null", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-headers"] == "Authorization, Content-Type"
    assert "access-control-allow-origin" not in public.options("/api/status").headers


def test_authentication_and_read_only_access(gamefy_context, signing_key):
    context = gamefy_context
    path = "/api/gamefy/workstation"
    for authorization in [None, "Bearer invalid", f"Bearer {signed_token(signing_key, aud='wrong-game')}", "Bearer " + "a" * 8193]:
        headers = {} if authorization is None else {"Authorization": authorization}
        response = context.public.get(path, headers=headers)
        assert response.status_code == 401
        assert response.headers["access-control-allow-origin"] == "*"
    token = signed_token(signing_key)
    assert context.internal.get("/internal/gamefy/workstation", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert context.public.get(path, headers={"Authorization": f"Bearer {signed_token(signing_key, sub=str(uuid4()))}"}).status_code == 404
    assert context.public.post(path, headers={"Authorization": f"Bearer {token}"}, json={"equipped": [1]}).status_code == 405
    assert context.public.get("/api/status", headers={"X-Admin-Token": token}).status_code == 401


def test_lobby_lists_public_workstations_including_empty_and_searches_literally(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    path = "/api/gamefy/workstation/lobby"
    response = context.public.get(path, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2 and data["my_number"] == 1
    assert data["items"] == [
        {"number": 1, "employee_number": "#0001", "display_name": "糯糯",
         "asset_keys": ["monitor-main"], "equipped_count": 9, "daily_income": 0},
        {"number": 2, "employee_number": "#0002", "display_name": "小小糯",
         "asset_keys": [], "equipped_count": 9, "daily_income": 0},
    ]
    assert response.headers["cache-control"] == "no-store"
    for query in ["#0002", "0002", " 小小糯 "]:
        matches = context.public.get(path, headers=headers, params={"query": query}).json()
        assert [item["number"] for item in matches["items"]] == [2]
    for query in ["%", "_", "不存在", "9" * 64]:
        assert context.public.get(path, headers=headers, params={"query": query}).json()["items"] == []
    for private in [OWNER, VISITOR, CORE_SECRET, "balance", "birthday", "platform_id", "share_groups"]:
        assert private not in response.text
    assert context.public.get(path, headers=headers, params={"page": 2}).json()["items"] == []
    for params in [{"page": 0}, {"page": 1000001}, {"query": "a" * 65}]:
        assert context.public.get(path, headers=headers, params=params).status_code == 422


def test_lobby_pagination_is_stable_and_bounded(gamefy_context, signing_key):
    context = gamefy_context
    for number in range(3, 27):
        context.send(f"join-{number}", f"/入职 员工{number}", str(uuid4()))
    path = "/api/gamefy/workstation/lobby"
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    first = context.public.get(path, headers=headers).json()
    second = context.public.get(path, params={"page": 2}, headers=headers).json()
    assert first["total"] == second["total"] == 26
    assert [item["number"] for item in first["items"]] == list(range(1, 25))
    assert [item["number"] for item in second["items"]] == [25, 26]


def test_employee_view_is_read_only_and_does_not_grant_others_share_access(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    context.send("entry", "/工位游戏")
    own = context.public.get("/api/gamefy/workstation/employees/1", headers=headers).json()
    other = context.public.get("/api/gamefy/workstation/employees/2", headers=headers).json()
    assert own["is_owner"] is True and len(own["share_groups"]) == 1
    assert other["display_name"] == "小小糯" and other["is_owner"] is False
    assert other["equipped"] == [] and other["share_groups"] == []
    visitor_headers = {"Authorization": f"Bearer {signed_token(signing_key, sub=VISITOR)}"}
    visited = context.public.get("/api/gamefy/workstation/employees/1", headers=visitor_headers).json()
    assert visited["equipped"] == own["equipped"]
    assert visited["share_groups"] == [] and visited["is_owner"] is False
    assert context.public.get("/api/gamefy/workstation/employees/99999", headers=headers).status_code == 404
    for suffix in ["/lobby", "/employees/1", "/employees/1/image"]:
        path = "/api/gamefy/workstation" + suffix
        assert context.public.get(path).status_code == 401
        assert context.public.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert context.public.post(path, json={}, headers=headers).status_code == 405
        assert context.public.options(path).headers["access-control-allow-origin"] == "*"
    for suffix in ["/lobby", "/employees/1"]:
        assert context.internal.get("/internal/gamefy/workstation" + suffix, headers=headers).status_code == 401


def test_download_composes_trusted_equipment_without_enqueuing_messages(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    balance = context.repository.find_user(OWNER).balance
    with context.repository._session() as session:
        before = set(session.scalars(select(OutboundRecord.id)))
    prefix = "/api/gamefy/workstation/employees/"
    images = []
    for number in [1, 2]:
        response = context.public.get(prefix + f"{number}/image", headers=headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()) == {"data_url"}
        encoded = response.json()["data_url"].removeprefix("data:image/png;base64,")
        with Image.open(BytesIO(base64.b64decode(encoded))) as image:
            assert image.format == "PNG" and image.size == (1536, 1024)
            images.append(image.tobytes())
    assert images[0] != images[1]  # Identical core art; the status panel identifies each owner.
    assert context.public.get(prefix + "99999/image", headers=headers).status_code == 404
    with context.repository._session() as session:
        assert set(session.scalars(select(OutboundRecord.id))) == before
    assert context.repository.find_user(OWNER).balance == balance


def test_preview_is_small_authenticated_and_keeps_original_download(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    path = "/api/gamefy/workstation/employees/1/image"
    assert context.public.get(path + "?preview=true").status_code == 401
    assert context.public.get(path + "?preview=true", headers={"Authorization": "Bearer invalid"}).status_code == 401
    preview = context.public.get(path + "?preview=true", headers=headers)
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert preview.headers["access-control-allow-origin"] == "*"
    encoded = preview.json()["data_url"]
    assert encoded.startswith("data:image/webp;base64,")
    with Image.open(BytesIO(base64.b64decode(encoded.split(",", 1)[1]))) as image:
        assert image.format == "WEBP" and image.size == (1152, 768)
    original = context.public.get(path, headers=headers).json()["data_url"]
    assert len(encoded) < len(original) / 4
    with Image.open(BytesIO(base64.b64decode(original.split(",", 1)[1]))) as image:
        assert image.format == "PNG" and image.size == (1536, 1024)
    assert context.public.get(path + "?preview=true", headers=headers).json()["data_url"] == encoded


def test_growth_upgrade_refreshes_owner_other_view_and_download_consistently(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    visitor_headers = {"Authorization": f"Bearer {signed_token(signing_key, sub=VISITOR)}"}
    prefix = '/api/gamefy/workstation'
    initial = context.public.get(prefix + '/employees/1/image', headers=headers).json()['data_url']
    with context.repository._session() as session:
        user = session.get(UserRecord, context.repository.find_user(OWNER).id)
        user.rank_id = session.scalar(select(RankRecord.id).where(RankRecord.sort_order == 2))
    balance = context.repository.find_user(OWNER).balance
    context.send('upgrade-computer-art', '/升级装备 6')
    assert context.repository.find_user(OWNER).balance == balance - 20

    own = context.public.get(prefix, headers=headers).json()
    other = context.public.get(prefix + '/employees/1', headers=visitor_headers).json()
    assert own['progression']['scene'] == other['progression']['scene']
    assert next(layer['level'] for layer in own['progression']['scene']['layers'] if layer['key'] == 'computer') == 2
    upgraded = context.public.get(prefix + '/employees/1/image', headers=headers).json()['data_url']
    assert upgraded != initial
    assert context.public.get(prefix + '/employees/1/image', headers=visitor_headers).json()['data_url'] == upgraded
    assert context.public.get(prefix + '/employees/2/image', headers=headers).json()['data_url'] != initial
    with context.repository._session() as session:
        before = set(session.scalars(select(OutboundRecord.id)))
    context.repository.set_workstation_component(OWNER, 6, equipped=False)
    removed = context.public.get(prefix + '/employees/1/image', headers=headers).json()['data_url']
    assert removed not in {upgraded, initial}
    context.repository.set_workstation_component(OWNER, 6, 1, equipped=True)
    assert context.public.get(prefix + '/employees/1/image', headers=headers).json()['data_url'] == initial
    with context.repository._session() as session:
        assert set(session.scalars(select(OutboundRecord.id))) == before
    assert context.repository.find_user(OWNER).balance == balance - 20


def test_stage5_authenticated_image_uses_saved_loadout_and_owner_name(gamefy_context, signing_key):
    from dzmm_bot.core.schema import WorkstationComponentRecord
    context=gamefy_context
    owner=context.repository.find_user(OWNER)
    with context.repository._session() as session:
        for number in range(1,10):
            session.add(WorkstationComponentRecord(user_id=owner.id,category_number=number,
                highest_level=10,active_level=10,equipped=True))
    headers={'Authorization':f'Bearer {signed_token(signing_key)}'}
    visitor={'Authorization':f'Bearer {signed_token(signing_key,sub=VISITOR)}'}
    prefix='/api/gamefy/workstation'
    own=context.public.get(prefix,headers=headers).json()
    other=context.public.get(prefix+'/employees/1',headers=visitor).json()
    assert own['progression']['accessory_scene']==other['progression']['accessory_scene']
    first=context.public.get(prefix+'/employees/1/image',headers=headers)
    assert first.status_code==200
    assert context.public.get(prefix+'/employees/1/image',headers=visitor).json()==first.json()
    assert context.public.get(prefix+'/employees/1/image').status_code==401
    context.send('stage5-name','/修改名称 糯糯与三屏')
    second=context.public.get(prefix+'/employees/1/image',headers=headers).json()['data_url']
    assert second!=first.json()['data_url']
    context.repository.set_workstation_component(OWNER,7,equipped=False)
    scene=context.public.get(prefix,headers=headers).json()['progression']['accessory_scene']
    assert not {'monitor-upgraded','speakers','lightbar'} & {item['key'] for item in scene['layers']}
    assert context.public.get(prefix+'/employees/1/image',headers=headers).json()['data_url']!=second


@pytest.mark.parametrize('stage,number,price,key', [(1,102,20,'headphones'),(2,203,70,'speakers'),(3,304,200,'microphone'),(4,404,400,'microphone'),(5,504,800,'microphone')])
def test_granted_accessory_is_shared_by_authenticated_owner_and_visitor_images(gamefy_context, signing_key, stage, number, price, key):
    from dzmm_bot.core.schema import WorkstationComponentRecord
    context=gamefy_context
    repo=context.repository
    owner=repo.find_user(OWNER)
    repo.record_balance_change(owner.id,10000-owner.balance,'board_bonus',datetime.now(timezone.utc))
    with repo._session() as session:
        for category in range(1,10):
            session.add(WorkstationComponentRecord(user_id=owner.id,category_number=category,
                highest_level=stage*2,active_level=stage*2,equipped=True))
    headers={'Authorization':f'Bearer {signed_token(signing_key)}'}
    visitor={'Authorization':f'Bearer {signed_token(signing_key,sub=VISITOR)}'}
    prefix='/api/gamefy/workstation'
    # Seed the already-earned room grant without simulating a paid purchase.
    with repo.transaction(),repo._session() as session:repo._grant_environment_accessories(session,owner.id,stage)
    context.send('paid-accessory',f'/购买装备 {number}')
    context.send('paid-accessory',f'/购买装备 {number}')
    assert repo.find_user(OWNER).balance==10000
    own=context.public.get(prefix,headers=headers).json()
    other=context.public.get(prefix+'/employees/1',headers=visitor).json()
    assert own['progression']['accessories']==other['progression']['accessories']
    assert next(a for a in own['progression']['accessories'] if a['number']==number)['equipped']
    assert key in {item['key'] for item in own['progression']['accessory_scene']['layers']}
    full=context.public.get(prefix+'/employees/1/image',headers=headers).json()['data_url']
    assert context.public.get(prefix+'/employees/1/image',headers=visitor).json()['data_url']==full
    assert all(a['environment']==1 for a in context.public.get(prefix+'/employees/2',headers=headers).json()['progression']['accessories'])
    context.send('remove-accessory',f'/卸下 {number}')
    removed=context.public.get(prefix+'/employees/1/image',headers=headers).json()['data_url']
    assert removed!=full
    context.send('restore-accessory',f'/装备 {number}')
    assert context.public.get(prefix+'/employees/1/image',headers=headers).json()['data_url']==full
    assert repo.find_user(OWNER).balance==10000


def test_unconfigured_game_does_not_accept_a_valid_platform_token(gamefy_context, signing_key):
    with TestClient(create_app(gamefy_context.repository, CORE_SECRET)) as client:
        response = client.get("/internal/gamefy/workstation", headers={
            "X-Core-Token": CORE_SECRET, "Authorization": f"Bearer {signed_token(signing_key)}",
        })
        assert response.status_code == 503


def test_share_requires_own_identity_recent_group_entry_and_is_idempotent(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}", "Origin": "null"}
    path = "/api/gamefy/workstation"
    assert context.public.get(path, headers=headers).json()["share_groups"] == []
    payload = {"group_id": str(uuid4()), "request_id": str(uuid4())}
    assert context.public.post(path + "/share", headers=headers, json=payload).status_code == 403
    assert context.public.post(path + "/share", json=payload).status_code == 401
    context.send("entry", "/工位游戏")
    groups = context.public.get(path, headers=headers).json()["share_groups"]
    assert len(groups) == 1
    payload["group_id"] = groups[0]["id"]
    for number in range(2, 11):
        context.send(f"buy-{number}", f"/购买装备 {number}")
        context.repository.purchase_equipment(f"buy-{number}", OWNER, number,
            context.repository.resolve_enabled_group_chat("gamefy-test").id, datetime.now(timezone.utc))
        context.repository.set_equipment_equipped(OWNER, number, True)
    with context.repository._session() as session:
        item = session.scalar(select(EquipmentItemRecord).where(EquipmentItemRecord.public_number == 1))
        item.name = "测试装备" * 25
        previous_ids = set(session.scalars(select(OutboundRecord.id)))
    balance = context.repository.find_user(OWNER).balance
    first = context.public.post(path + "/share", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["status"] == "pending"
    assert first.headers["access-control-allow-origin"] == "*"
    assert context.public.post(path + "/share", headers=headers, json=payload).json() == first.json()
    with context.repository._session() as session:
        records = session.scalars(select(OutboundRecord).where(OutboundRecord.content_type == "workstation")).all()
        assert len(records) == 1
        assert len(set(session.scalars(select(OutboundRecord.id))) - previous_ids) == 1
        snapshot = json.loads(records[0].text)
        assert snapshot["display_name"] == "糯糯"
        assert snapshot["employee_number"] == "#0001"
        assert snapshot["equipped"][0]["asset_key"] == "monitor-main"
        assert len(snapshot["equipped"]) == 10
        assert len(records[0].text) > 1000
        assert records[0].destination_chatroom_id == "gamefy-test"
        assert records[0].group_chat_id == UUID(groups[0]["id"])
        records[0].status = "sent"
    status_path = path + "/shares/" + payload["request_id"]
    assert context.public.get(status_path, headers=headers).json()["status"] == "sent"
    visitor = {"Authorization": f"Bearer {signed_token(signing_key, sub=VISITOR)}"}
    assert context.public.get(status_path, headers=visitor).status_code == 404
    assert context.public.post(path + "/share", headers=visitor, json=payload).status_code == 403
    too_fast = context.public.post(path + "/share", headers=headers, json={**payload, "request_id": str(uuid4())})
    assert too_fast.status_code == 429
    assert context.repository.find_user(OWNER).balance == balance


def test_share_rejects_expired_disabled_and_forged_targets(gamefy_context, signing_key):
    context = gamefy_context
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    path = "/api/gamefy/workstation"
    context.send("entry", "/工位游戏")
    group_id = context.public.get(path, headers=headers).json()["share_groups"][0]["id"]
    payload = {"group_id": group_id, "request_id": str(uuid4())}
    for extra in [{"user_id": VISITOR}, {"image_url": "https://untrusted.test/photo.png"}, {"equipped": [1]}]:
        assert context.public.post(path + "/share", headers=headers, json={**payload, **extra}).status_code == 422
    assert context.internal.post("/internal/gamefy/workstation/share", headers=headers, json=payload).status_code == 401
    with context.repository._session() as session:
        entry = session.scalar(select(InboundRecord).where(InboundRecord.platform_message_id == "entry"))
        entry.received_at -= timedelta(hours=25)
    assert context.public.post(path + "/share", headers=headers, json=payload).status_code == 403
    context.send("new-entry", "/工位游戏")
    with context.repository._session() as session:
        group = session.scalar(select(GroupChatRecord).where(GroupChatRecord.chatroom_id == "gamefy-test"))
        group.listening_enabled = False
    assert context.public.get(path, headers=headers).json()["share_groups"] == []
    assert context.public.post(path + "/share", headers=headers, json=payload).status_code == 403


def test_share_preflight_accepts_authorized_json_from_sandbox(gamefy_context):
    response = gamefy_context.public.options("/api/gamefy/workstation/share", headers={
        "Origin": "null", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert "POST" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-origin"] == "*"

def test_shop_authentication_personal_filtering_and_no_financial_leak(gamefy_context, signing_key):
    context = gamefy_context
    path = "/api/gamefy/workstation/shop"
    assert context.public.get(path).status_code == 401
    assert context.public.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
    headers = {"Authorization": f"Bearer {signed_token(signing_key)}"}
    before = context.repository.find_user(OWNER).balance
    response = context.public.get(path + f"?user_id={VISITOR}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["balance"] == before
    assert data["upgrade_credit"] == 0
    assert all(r["credit_used"] == 0 and r["cash_required"] == (r["price"] or 0) for r in data["items"])
    assert data["level_cap"] == 1
    assert data['growth'] == context.repository.get_workstation(context.repository.find_user(OWNER).id)['progression']['growth']
    assert data['growth_offers']['advance']['price'] == 0
    assert data['growth_offers']['advance']['status'] == 'devices_required'
    assert data['growth_offers']['advance']['missing_devices'] == ['电脑', '显示器', '键盘', '鼠标']
    assert all(a['unlock_description'] for a in data['accessories'])
    assert len(data["items"]) == 9
    assert {r["status"] for r in data["items"]} == {"environment_bundle", "rank_locked"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "*"
    other_headers = {"Authorization": f"Bearer {signed_token(signing_key, sub=VISITOR)}"}
    assert context.public.get(path, headers=other_headers).json()["upgrade_credit"] == 0
    public_other = context.public.get("/api/gamefy/workstation/employees/1", headers=other_headers).json()
    assert "balance" not in public_other and "upgrade_credit" not in public_other
    assert "balance" not in json.dumps(public_other["progression"])
    assert context.public.options(path, headers={"Origin": "null", "Access-Control-Request-Method": "GET"}).status_code == 200
    assert context.public.post(path, headers=headers, json={"number":6}).status_code == 405
    assert context.repository.find_user(OWNER).balance == before
    assert context.internal.get("/internal/gamefy/workstation/shop", headers=headers).status_code == 401


def prepare_actions(context, signing_key):
    context.send('open-game', '/工位游戏')
    with context.repository._session() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.platform_id == OWNER))
        user.rank_id = session.scalar(select(RankRecord.id).where(RankRecord.sort_order == 10))
    user = context.repository.find_user(OWNER)
    context.repository.record_balance_change(user.id, 40000 - user.balance, 'board_bonus', datetime.now(timezone.utc))
    return {'Authorization': f'Bearer {signed_token(signing_key)}'}


def game_action(context, headers, action, *, request_id=None):
    path = '/api/gamefy/workstation'
    response = context.public.post(path + '/quote', headers=headers, json=action)
    assert response.status_code == 200, response.text
    quote = response.json()
    payload = {'action': action, 'request_id': str(request_id or uuid4()), 'revision': quote['revision']}
    response = context.public.post(path + '/actions', headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return quote, response.json(), payload


def test_game_chat_upgrade_grant_equip_and_receipts_share_one_account(gamefy_context, signing_key):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    with context.repository.transaction(), context.repository._session() as session:
        context.repository._grant_environment_accessories(session,context.repository.find_user(OWNER).id,1)
    context.send('chat-upgrade', '/升级装备 6 1')
    shop = context.public.get('/api/gamefy/workstation/shop', headers=headers).json()
    assert next(i for i in shop['items'] if i['number'] == 6)['highest_level'] == 2
    assert shop['balance'] == 39980
    quote, result, payload = game_action(context, headers, {'kind': 'equip', 'number': 102})
    assert quote['price'] == 0 and result['balance'] == 39980
    assert all(quote[k].startswith('data:image/webp;base64,') for k in ['before_image','after_image'])
    replay=context.public.post('/api/gamefy/workstation/actions',headers=headers,json=payload)
    assert replay.json()['replayed'] and context.repository.find_user(OWNER).balance == 39980
    context.send('chat-remove', '/卸下 102')
    assert not context.public.get('/api/gamefy/workstation/shop', headers=headers).json()['accessories'][1]['equipped']
    game_action(context, headers, {'kind': 'equip', 'number': 102})
    assert context.repository.get_workstation_shop(OWNER)['accessories'][1]['equipped']
    assert context.repository.find_user(OWNER).balance == 39980
    # An old successful equip cannot undo a later removal when retried.
    _, _, equip_payload = game_action(context, headers, {'kind': 'equip', 'number': 102})
    context.send('chat-remove-again', '/卸下 102')
    context.public.post('/api/gamefy/workstation/actions', headers=headers, json=equip_payload)
    assert not context.repository.get_workstation_shop(OWNER)['accessories'][1]['equipped']


def test_game_stale_quote_conflict_and_owner_is_derived_from_jwt(gamefy_context, signing_key):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    action = {'kind': 'upgrade', 'number': 6}
    quote = context.public.post('/api/gamefy/workstation/quote', headers=headers, json=action).json()
    context.send('concurrent-chat', '/升级装备 7 1')
    payload = {'action': action, 'request_id': str(uuid4()), 'revision': quote['revision']}
    response = context.public.post('/api/gamefy/workstation/actions', headers=headers, json=payload)
    assert response.status_code == 409 and '未扣币' in response.json()['detail']
    assert context.repository.find_user(OWNER).balance == 39980
    _, result, payload = game_action(context, headers, action)
    payload['action'] = {'kind': 'upgrade', 'number': 8}
    assert context.public.post('/api/gamefy/workstation/actions', headers=headers, json=payload).status_code == 409
    payload['user_id'] = VISITOR
    assert context.public.post('/api/gamefy/workstation/actions', headers=headers, json=payload).status_code == 422
    assert context.repository.find_user(OWNER).balance == result['balance']
    visitor = {'Authorization': f'Bearer {signed_token(signing_key, sub=VISITOR)}'}
    assert context.public.post('/api/gamefy/workstation/quote', headers=visitor, json=action).status_code == 403
    assert context.public.post('/api/gamefy/workstation/quote', json=action).status_code == 401
    assert context.public.post('/api/gamefy/workstation/employees/1/actions', headers=visitor, json=payload).status_code == 404


def test_grouped_growth_all_five_rooms_prices_and_permanent_ownership(gamefy_context, signing_key):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    from dzmm_bot.core.workstation_accessories import ACCESSORIES
    for stage in range(1, 6):
        # Test group batch -> game state, then game core/purchase -> repository.
        context.send(f'polish-{stage}', '/精修工位')
        for number in range(6, 10):
            game_action(context, headers, {'kind': 'upgrade', 'number': number})
        if stage < 5:
            game_action(context, headers, {'kind': 'advance'})
    shop = context.repository.get_workstation_shop(OWNER)
    assert {i['highest_level'] for i in shop['items']} == {9, 10}
    assert len([a for a in shop['accessories'] if a['owned']]) == 25
    assert shop['balance'] == 21050 and shop['daily_income'] == 180
    for stage in range(1, 6):
        quote, result, _ = game_action(context, headers, {'kind': 'view', 'level': stage})
        assert quote['price'] == 0 and result['balance'] == 21050
        scene = context.repository.get_workstation(context.repository.find_user(OWNER).id)['progression']['accessory_scene']
        assert scene['environment'] == stage
        assert quote['after']['progression']['accessory_scene'] == scene


def test_action_gates_rank_balance_disabled_group_command_and_strict_payload(gamefy_context, signing_key):
    context = gamefy_context
    headers = {'Authorization': f'Bearer {signed_token(signing_key)}'}
    path = '/api/gamefy/workstation/quote'
    assert context.public.post(path, headers=headers, json={'kind': 'upgrade', 'number': 6}).status_code == 403
    context.send('open-game', '/工位游戏')
    assert context.public.post(path, headers=headers, json={'kind': 'upgrade', 'number': 6}).status_code == 409
    headers = prepare_actions(context, signing_key)
    context.repository.set_command_enabled('/工位游戏', False)
    assert context.public.post(path, headers=headers, json={'kind': 'view', 'level': 1}).status_code == 403
    context.repository.set_command_enabled('/工位游戏', True)
    context.repository.set_command_enabled('/升级装备', False)
    for kind in ['upgrade', 'advance']:
        action = {'kind': kind, **({'number': 6} if kind == 'upgrade' else {})}
        assert context.public.post(path, headers=headers, json=action).status_code == 403
    context.repository.set_command_enabled('/升级装备', True)
    user = context.repository.find_user(OWNER)
    context.repository.record_balance_change(user.id, -user.balance, 'board_bonus', datetime.now(timezone.utc))
    assert context.public.post(path, headers=headers, json={'kind': 'advance'}).status_code == 409
    for action in [
        {'kind': 'equip', 'number': 6}, {'kind': 'upgrade', 'number': True},
        {'kind': 'view', 'level': 6}, {'kind': 'remove', 'number': 6, 'level': 1},
        {'kind': 'upgrade', 'number': 6, 'user_id': VISITOR}, {'kind': 'bad'},
    ]:
        assert context.public.post(path, headers=headers, json=action).status_code == 422
    with context.repository._session() as session:
        group = session.scalar(select(GroupChatRecord).where(GroupChatRecord.chatroom_id == 'gamefy-test'))
        group.listening_enabled = False
    assert context.public.post(path, headers=headers, json={'kind': 'view', 'level': 1}).status_code == 403


def test_grouped_action_rollback_and_chat_receipt_cannot_pay_again(gamefy_context, signing_key, monkeypatch):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    for number in range(6, 10):
        context.send(f'qualify-{number}', f'/升级装备 {number}')
    original = context.repository._upgrade_component
    calls = []
    def fail_second(*args):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('isolated rollback injection')
        return original(*args)
    monkeypatch.setattr(context.repository, '_upgrade_component', fail_second)
    quote = context.public.post('/api/gamefy/workstation/quote', headers=headers, json={'kind': 'advance'}).json()
    with pytest.raises(RuntimeError, match='rollback injection'):
        context.public.post('/api/gamefy/workstation/actions', headers=headers, json={
            'action': {'kind': 'advance'}, 'revision': quote['revision'], 'request_id': str(uuid4())})
    assert context.repository.find_user(OWNER).balance == 39920
    assert {i['highest_level'] for i in context.repository.get_workstation_shop(OWNER)['items']} == {1, 2}
    monkeypatch.setattr(context.repository, '_upgrade_component', original)
    context.send('batch-chat', '/升级工位')
    assert context.repository.find_user(OWNER).balance == 39460
    context.send('batch-chat', '/升级工位')
    assert context.repository.find_user(OWNER).balance == 39460
    group = context.repository.resolve_enabled_group_chat('gamefy-test')
    now = datetime.now(timezone.utc)
    assert context.repository.upgrade_workstation_component('batch-chat', OWNER, 6, None, group.id, now)['status'] == 'request_conflict'
    assert context.repository.purchase_workstation_accessory('batch-chat', OWNER, 102, group.id, now)['status'] == 'purchase_disabled'


def test_old_room_can_upgrade_owned_progress_in_game_and_chat(gamefy_context, signing_key):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    for number in range(6, 10):
        context.send(f'qualify-{number}', f'/升级装备 {number}')
    game_action(context, headers, {'kind': 'advance'})
    game_action(context, headers, {'kind': 'view', 'level': 1})
    before = context.repository.find_user(OWNER).balance
    response = context.public.post('/api/gamefy/workstation/quote', headers=headers,
        json={'kind': 'upgrade', 'number': 6})
    assert response.status_code == 200 and response.json()['price'] == 70
    context.send('old-room-chat-upgrade', '/升级装备 7')
    actual = context.repository.get_workstation(context.repository.find_user(OWNER).id)['progression']
    assert actual['accessory_scene']['environment'] == 2
    assert next(c for c in actual['components'] if c['number'] == 7)['highest_level'] == 4
    assert context.repository.find_user(OWNER).balance == before - 70
    game_action(context, headers, {'kind': 'view', 'level': 1})
    quote, _, _ = game_action(context, headers, {'kind': 'upgrade', 'number': 6})
    actual = context.repository.get_workstation(context.repository.find_user(OWNER).id)['progression']
    assert quote['after']['progression'] == actual
    assert actual['accessory_scene']['environment'] == 2
    assert context.repository.find_user(OWNER).balance == before - 140


def test_light_quote_skips_render_and_apply_returns_immediate_state(gamefy_context, signing_key, monkeypatch):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    path = '/api/gamefy/workstation'
    action = {'kind': 'upgrade', 'number': 6}
    def no_render(*args, **kwargs):
        raise AssertionError('Account requests must not wait for images')
    monkeypatch.setattr('dzmm_bot.admin.workstation.workstation_image_data', no_render)
    quote_response = context.public.post(path + '/quote?include_images=false', headers=headers, json=action)
    assert quote_response.status_code == 200
    quote = quote_response.json()
    assert 'before_image' not in quote and 'after_image' not in quote
    payload = {'action': action, 'revision': quote['revision'], 'request_id': str(uuid4())}
    response = context.public.post(path + '/actions', headers=headers, json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['workstation']['daily_income'] == quote['after']['daily_income']
    assert result['management']['balance'] == result['balance'] == 40000 - quote['price']
    assert next(c for c in result['workstation']['progression']['components'] if c['number'] == 6)['active_level'] == 2
    replay = context.public.post(path + '/actions', headers=headers, json=payload).json()
    assert replay['replayed'] and replay['management'] == result['management']
    # A response lost after commit must replay the receipt without charging again,
    # while returning newer account data if something else has changed since.
    context.repository.record_balance_change(context.repository.find_user(OWNER).id, 7, 'board_bonus', datetime.now(timezone.utc))
    replay = context.public.post(path + '/actions', headers=headers, json=payload).json()
    assert replay['replayed'] and replay['management']['balance'] == result['balance'] + 7
    assert replay['price'] == result['price']


def test_action_preview_is_small_authorized_readonly_and_revision_bound(gamefy_context, signing_key):
    context = gamefy_context
    headers = prepare_actions(context, signing_key)
    path = '/api/gamefy/workstation'
    action = {'kind': 'upgrade', 'number': 9}
    quote = context.public.post(path + '/quote?include_images=false', headers=headers, json=action).json()
    payload = {'action': action, 'revision': quote['revision']}
    assert context.public.options(path + '/action-preview').headers['access-control-allow-origin'] == '*'
    assert context.public.post(path + '/action-preview', json=payload).status_code == 401
    visitor = {'Authorization': f'Bearer {signed_token(signing_key, sub=VISITOR)}'}
    assert context.public.post(path + '/action-preview', headers=visitor, json=payload).status_code == 403
    response = context.public.post(path + '/action-preview', headers=headers, json=payload)
    assert response.status_code == 200
    result = response.json()
    assert result['revision'] == quote['revision']
    assert result['data_url'].startswith('data:image/webp;base64,')
    with Image.open(BytesIO(base64.b64decode(result['data_url'].split(',')[1]))) as preview:
        assert preview.size == (576, 384)
    assert context.repository.find_user(OWNER).balance == 40000
    context.repository.record_balance_change(context.repository.find_user(OWNER).id, 1, 'board_bonus', datetime.now(timezone.utc))
    assert context.public.post(path + '/action-preview', headers=headers, json=payload).status_code == 409
    payload['revision'] = 'invalid'
    assert context.public.post(path + '/action-preview', headers=headers, json=payload).status_code == 422
