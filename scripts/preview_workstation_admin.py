"""Loopback-only backoffice demo, with a temporary database and no chat delivery."""

import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
import tempfile
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from dzmm_bot.admin.app import create_app
from dzmm_bot.admin.core_client import CoreClient
from dzmm_bot.admin.repository import AdminRepository
from dzmm_bot.core.app import create_app as create_core_app
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, beijing_now
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage


@contextmanager
def demo_app():
    with tempfile.TemporaryDirectory(prefix="dzmm-admin-demo-") as directory:
        engine = create_engine(
            "sqlite+pysqlite:///" + str(Path(directory) / "demo.db"),
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        factory = sessionmaker(engine, expire_on_commit=False)
        repo = CoreRepository(factory)
        now = beijing_now()
        repo.bootstrap_primary_group(
            "https://www.aikda.com/chat?c=local-admin-demo", now
        )
        service = CoreService(repo, GroupCommandHandler(repo))
        for index, name in enumerate(("示例员工", "示例同事", "待修正工位"), start=1):
            platform_id = f"local-admin-demo-{index}"
            service.receive_inbound(
                InboundMessage(
                    str(uuid4()),
                    platform_id,
                    "/入职 " + name,
                    now,
                    chatroom_id="local-admin-demo",
                )
            )
            number = repo.find_user(platform_id).employee_number
            level = index * 2
            repo.workstation_admin_player_apply(
                number,
                {
                    "kind": "grant",
                    "environment": index,
                    "devices": {
                        str(n): {"level": level, "equipped": True} for n in range(6, 10)
                    },
                    "actor": "local-demo",
                    "request_id": str(uuid4()),
                    "reason": "隔离演示数据",
                    "revision": repo.workstation_admin_player(number)["revision"],
                },
                now,
            )
        internal = TestClient(
            create_core_app(repo, "local-core-demo"),
            headers={"X-Core-Token": "local-core-demo"},
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

        with (
            internal,
            httpx.Client(
                transport=httpx.MockTransport(transport),
                base_url="http://testserver",
                headers={"X-Core-Token": "local-core-demo"},
            ) as client,
        ):
            admin = AdminRepository(factory)
            admin.create_account("operator", "local-demo-password")
            yield create_app(
                "local-workstation-admin",
                CoreClient("http://testserver", "local-core-demo", client=client),
                repository=admin,
            )
        engine.dispose()


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8896)
    args = parser.parse_args()
    print(
        f"Local demo: http://127.0.0.1:{args.port}/ ; super-admin token: local-workstation-admin"
    )
    print(
        "Normal admin: operator / local-demo-password. Demo credentials only; no production data."
    )
    with demo_app() as app:
        uvicorn.run(app, host="127.0.0.1", port=args.port)
