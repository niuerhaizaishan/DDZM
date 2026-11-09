from uuid import uuid4

import pytest
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from dzmm_bot.admin.app import create_app
from dzmm_bot.admin.core_client import CoreClient
from dzmm_bot.admin.repository import AdminRepository
from dzmm_bot.core.app import create_app as core_app
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, WorkstationAdminOperationRecord, beijing_now
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage


@pytest.fixture
def management():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = CoreRepository(factory)
    now = beijing_now()
    repo.bootstrap_primary_group("https://www.aikda.com/chat?c=test", now)
    CoreService(repo, GroupCommandHandler(repo)).receive_inbound(
        InboundMessage("join", "player", "/入职 测试员工", now, chatroom_id="test")
    )
    internal = TestClient(
        core_app(repo, "core-test", clock=lambda: now),
        headers={"X-Core-Token": "core-test"},
    )

    def transport(request):
        response = internal.request(
            request.method,
            str(request.url),
            content=request.content,
            headers=dict(request.headers),
        )
        return httpx.Response(
            response.status_code,
            content=response.content,
            headers=response.headers,
            request=request,
        )

    gateway = httpx.Client(
        transport=httpx.MockTransport(transport),
        base_url="http://testserver",
        headers={"X-Core-Token": "core-test"},
    )
    core = CoreClient("http://testserver", "core-test", client=gateway)
    admin = AdminRepository(factory)
    account = admin.create_account("operator", "test-password")
    session = admin.create_session(account.id, now)
    client = TestClient(create_app("test-admin", core, repository=admin))
    yield client, repo, internal, factory, {"X-Admin-Session": session}
    client.close()
    gateway.close()
    internal.close()
    engine.dispose()


def super_headers(**extras):
    return {"X-Admin-Token": "test-admin", "Idempotency-Key": str(uuid4()), **extras}


def test_normal_admin_can_edit_names_and_income_without_settlement_permission(management):
    client, repo, internal, factory, operator = management
    settings = client.get('/api/game/workstation/settings', headers=operator).json()
    rules = settings['rules']
    rules['environment_names'][0] = '新人办公区'
    rules['environment_income'][0] = 3
    rules['device_names']['computer'][0] = '入门办公电脑'
    rules['tool_income'][0] = 4
    preview = client.post('/api/game/workstation/settings/preview', headers=operator, json=rules)
    assert preview.status_code == 200, preview.text
    assert preview.json()['after']['daily_income'] == 19
    body = {'kind': 'rules', 'revision': settings['revision'], 'data': rules, 'reason': '管理员修改名称与收益'}
    headers = {**operator, 'Idempotency-Key': str(uuid4()), 'If-Match': str(settings['version'])}
    saved = client.post('/api/game/workstation/settings', headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()['rules'] == rules
    user = repo.find_user('player')
    station = repo.get_workstation(user.id)
    assert station['progression']['environment_name'] == '新人办公区'
    assert station['daily_income'] == 19
    computer = next(c for c in station['progression']['components'] if c['number'] == 6)
    assert computer['name'] == '入门办公电脑' and computer['daily_income'] == 4
    assert client.post('/api/game/workstation/settings', json=body).status_code == 401
    assert client.post('/api/game/workstation/income', headers=headers, json={}).status_code == 403
    script = client.get('/static/workstation-admin.js').text
    assert '编辑名称、收益和价格' in script
    assert '<details open><summary>${label}各档名称' in script
    assert 'if (!workstationSuper()) { content.querySelector("#edit-workstation-rules-settings").remove()' not in script


def player_body():
    return {
        "kind": "grant",
        "environment": 2,
        "devices": {str(n): {"level": 4, "equipped": True} for n in range(6, 10)},
    }


def test_management_auth_permissions_forgery_and_static_page(management):
    client, repo, internal, factory, operator = management
    number = repo.find_user("player").employee_number
    assert client.get("/api/game/workstation/overview").status_code == 401
    assert (
        internal.get(
            "/internal/game/workstation/settings", headers={"X-Core-Token": "bad"}
        ).status_code
        == 401
    )
    assert (
        client.get("/api/game/workstation/players", headers=operator).json()["total"]
        == 1
    )
    assert (
        client.post(
            f"/api/game/workstation/players/{number}/preview",
            headers=operator,
            json=player_body(),
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/game/workstation/settings/preview", headers=operator, json={}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/game/workstation/income", headers=operator, json={}
        ).status_code
        == 403
    )
    payload = {
        **player_body(),
        "actor": "forged",
        "request_id": str(uuid4()),
        "reason": "x",
        "revision": "0" * 64,
    }
    assert (
        client.post(
            f"/api/game/workstation/players/{number}/actions",
            headers=super_headers(),
            json=payload,
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/game/workstation/players/{number}/actions",
            headers=super_headers(**{"Idempotency-Key": "bad"}),
            json={},
        ).status_code
        == 422
    )
    page = client.get("/").text
    assert (
        "nav-workstation" in page
        and "workstation-admin.js" in page
        and "workstation-admin-panel" in page
    )
    assert client.get("/static/workstation-admin.js").status_code == 200


def test_management_preview_apply_conflicts_and_normal_admin_equip(management):
    client, repo, internal, factory, operator = management
    number = repo.find_user("player").employee_number
    path = f"/api/game/workstation/players/{number}"
    headers = super_headers()
    preview = client.post(path + "/preview", headers=headers, json=player_body())
    assert preview.status_code == 200, preview.text
    body = {
        **player_body(),
        "reason": "补授测试",
        "revision": preview.json()["revision"],
    }
    saved = client.post(path + "/actions", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["workstation"] == preview.json()["after"]
    assert (
        client.post(path + "/actions", headers=headers, json=body).json()
        == saved.json()
    )
    assert (
        client.post(
            path + "/actions", headers=headers, json={**body, "reason": "改变请求"}
        ).status_code
        == 409
    )
    equip = {
        **player_body(),
        "kind": "equip",
        "environment": 1,
        "devices": {str(n): {"level": 1, "equipped": True} for n in range(6, 10)},
    }
    next_preview = client.post(path + "/preview", headers=operator, json=equip)
    response = client.post(
        path + "/actions",
        headers={**operator, "Idempotency-Key": str(uuid4())},
        json={
            **equip,
            "reason": "切换旧环境",
            "revision": next_preview.json()["revision"],
        },
    )
    assert response.status_code == 200, response.text
    assert (
        response.json()["workstation"]["progression"]["growth"]["highest_environment"]
        == 2
    )
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(WorkstationAdminOperationRecord)
            )
            == 2
        )
    assert (
        client.get("/api/game/workstation/players?query=测试", headers=operator).json()[
            "total"
        ]
        == 1
    )
    assert (
        client.get(
            "/api/game/workstation/players?query=不存在", headers=operator
        ).json()["total"]
        == 0
    )
    assert (
        client.get(
            "/api/game/workstation/players?page_size=100", headers=operator
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/game/workstation/records/operations?query=补授", headers=operator
        ).json()["total"]
        == 1
    )


def test_management_rules_version_and_income_switch(management):
    client, repo, internal, factory, operator = management
    settings = client.get(
        "/api/game/workstation/settings", headers=super_headers()
    ).json()
    rules = settings["rules"]
    rules["tool_income"][0] = 3
    headers = super_headers(**{"If-Match": str(settings["version"])})
    body = {
        "kind": "rules",
        "revision": settings["revision"],
        "data": rules,
        "reason": "测试调整",
    }
    assert (
        client.post(
            "/api/game/workstation/settings", headers=headers, json=body
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/game/workstation/settings", headers=headers, json=body
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/game/workstation/settings",
            headers=super_headers(**{"If-Match": "0"}),
            json=body,
        ).status_code
        == 409
    )
    directory = client.get("/api/game/workstation/players", headers=operator).json()
    assert (
        directory["items"][0]["daily_income"] == 12
    )  # includes default components without DB rows
    overview = client.get("/api/game/workstation/overview", headers=operator).json()
    assert overview["daily_income"] == 12
    state = client.get("/api/game/workstation/settings", headers=operator).json()
    enabled = client.post(
        "/api/game/workstation/income",
        headers=super_headers(),
        json={
            "kind": "income",
            "enabled": True,
            "reason": "启用",
            "revision": state["settlement_revision"],
        },
    )
    assert enabled.status_code == 200, enabled.text
    settled = client.post(
        "/api/game/workstation/income",
        headers=super_headers(),
        json={
            "kind": "settle",
            "reason": "补跑今日",
            "revision": enabled.json()["revision"],
        },
    )
    assert settled.status_code == 200 and settled.json()["result"]["amount"] == 12
    records = client.get(
        "/api/game/workstation/records/settlements", headers=operator
    ).json()
    assert records["total"] == 1 and len(records["items"][0]["components"]) == 9
