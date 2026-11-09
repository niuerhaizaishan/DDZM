"""Loopback-only linked game/chat demo, using an isolated SQLite account.

No environment settings, external chat transport or production database is loaded.
The platform identity shim is served here only, never copied into publish/.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import sys
import tempfile
from uuid import UUID, uuid4

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from dzmm_bot.admin.core_client import CoreClient
from dzmm_bot.admin.workstation import install_workstation_routes
from dzmm_bot.core.app import create_app
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.gamefy import GamefyIdentityVerifier
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import Base, OutboundRecord, RankRecord, UserRecord
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage
from build_gamefy_workstation import build

ACTOR = '00000000-0000-4000-8000-000000000101'
COLLEAGUE = '00000000-0000-4000-8000-000000000102'
GAME_ID = '100001'


class DemoCommand(BaseModel):
    text: str = Field(min_length=1, max_length=200)


@contextmanager
def demo_app(database, port):
    engine = create_engine('sqlite+pysqlite:///' + str(database), connect_args={'check_same_thread': False, 'timeout': 30})
    Base.metadata.create_all(engine)
    repository = CoreRepository(sessionmaker(engine, expire_on_commit=False))
    repository.bootstrap_primary_group('https://www.aikda.com/chat?c=local-workstation-demo', datetime.now(timezone.utc))
    service = CoreService(repository, GroupCommandHandler(repository))

    def send(text, actor=ACTOR):
        result = service.receive_inbound(InboundMessage(str(uuid4()), actor, text, datetime.now(timezone.utc),
            source_type='group', chatroom_id='local-workstation-demo'))
        with repository._session() as session:
            return list(session.scalars(select(OutboundRecord.text).where(
                OutboundRecord.inbound_message_id == result.message_id).order_by(OutboundRecord.reply_index)))

    for actor, name in [(ACTOR, '示例员工'), (COLLEAGUE, '示例同事')]:
        if repository.find_user(actor) is None:
            send('/入职 ' + name, actor)
            user = repository.find_user(actor)
            repository.record_balance_change(user.id, 40000 - user.balance, 'board_bonus', datetime.now(timezone.utc))
            with repository._session() as session:
                session.get(UserRecord, user.id).rank_id = session.scalar(select(RankRecord.id).where(RankRecord.sort_order == 10))
    send('/我的工位')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    original_verify = GamefyIdentityVerifier.verify

    def local_verify(self, token):
        # Local signatures still validate account, issuer, audience and expiry.
        try:
            claims = jwt.decode(token, key.public_key(), algorithms=['RS256'], issuer='dzmm-gamefy', audience=GAME_ID,
                options={'require': ['sub', 'iss', 'aud', 'iat', 'exp'], 'strict_aud': True})
            return str(UUID(claims['sub']))
        except (jwt.PyJWTError, ValueError) as error:
            from fastapi import HTTPException
            raise HTTPException(401, '本地测试身份已失效，请刷新。') from error

    GamefyIdentityVerifier.verify = local_verify
    core_secret = secrets.token_urlsafe(32)
    try:
        build_folder = ROOT / 'output' / 'workstation-build'
        build_folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='demo-', dir=build_folder) as demo_root, TestClient(create_app(repository, core_secret, gamefy_game_id=GAME_ID)) as internal:
            project = build(Path(demo_root), release=True, api_base_url='https://preview.example.test', card_id=int(GAME_ID))
            def forward(request):
                response = internal.request(request.method, str(request.url), headers=request.headers, content=request.content)
                return httpx.Response(response.status_code, headers=response.headers, content=response.content)
            with httpx.Client(base_url='http://local-core', headers={'X-Core-Token': core_secret},
                              transport=httpx.MockTransport(forward), timeout=90) as client:
                app = FastAPI(title='Local isolated workstation demo')
                install_workstation_routes(app, CoreClient('http://local-core', core_secret, client=client))
                publish = project / 'publish'

                @app.post('/demo/command')
                def command(payload: DemoCommand):
                    return {'replies': send(payload.text)}

                @app.get('/demo/package')
                def package():
                    return FileResponse(ROOT / 'output' / 'gamefy-workstation-release.zip', filename='gamefy-workstation-release.zip')

                @app.get('/')
                def page():
                    now = datetime.now(timezone.utc)
                    token = jwt.encode({'sub': ACTOR, 'iss': 'dzmm-gamefy', 'aud': GAME_ID,
                        'iat': now, 'exp': now + timedelta(hours=12)}, key, algorithm='RS256', headers={'kid': 'local-only'})
                    html = (publish / 'index.html').read_text(encoding='utf-8')
                    shim = '<script>window.dzmm={user:{info:async()=>({token:' + json.dumps(token) + '})}};</script>'
                    chat = '''<section style="margin:16px;padding:16px;background:#fff4d9;border:1px solid #bca571;border-radius:12px">
<strong>本地联动试玩 · 独立测试账号</strong><p>初始40,000测试币、升级上限Lv10。只写入本机试玩数据库。<a href="/demo/package">下载小游戏发布候选包</a></p>
<form id="demo-chat" style="display:flex;flex-wrap:wrap;gap:8px"><label for="demo-command">模拟群聊指令</label> <input id="demo-command" value="/帮助 工位" maxlength="200" required style="min-width:0;max-width:100%">
<button>发送到模拟群</button></form><pre id="demo-replies" style="white-space:pre-wrap;overflow-wrap:anywhere"></pre></section>
<script>document.getElementById('demo-chat').addEventListener('submit',async e=>{e.preventDefault();
const button=e.target.querySelector('button');button.disabled=true;
try{const response=await fetch('/demo/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:document.getElementById('demo-command').value})});
const result=await response.json();document.getElementById('demo-replies').textContent=(result.replies||[]).join('\\n');window.dispatchEvent(new Event('focus'));}
catch{document.getElementById('demo-replies').textContent='本地连接失败，请重试。';}finally{button.disabled=false;}});</script>'''
                    return HTMLResponse(html.replace('</head>', shim + '</head>').replace('<main>', '<main>' + chat),
                                        headers={'Cache-Control': 'no-store'})

                @app.get('/{filename}')
                def resource(filename: str):
                    if filename == 'config.js':
                        return Response('window.workstationConfig={apiBaseUrl:' + json.dumps(f'http://127.0.0.1:{port}') + '};', media_type='text/javascript')
                    if filename not in {'game.js', 'art.js', 'workstation.js', 'style.css', 'game.css'}:
                        from fastapi import HTTPException
                        raise HTTPException(404)
                    text = (publish / filename).read_text(encoding='utf-8')
                    if filename == 'game.js':
                        # This adapter exception exists only in the loopback demo response.
                        text = text.replace('endpoint.protocol !== "https:"',
                            '(endpoint.protocol !== "https:" && endpoint.origin !== "http://127.0.0.1:' + str(port) + '")')
                    return Response(text, media_type='text/css' if filename.endswith('.css') else 'text/javascript')
                yield app, repository
    finally:
        GamefyIdentityVerifier.verify = original_verify
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8895)
    args = parser.parse_args()
    folder = ROOT / 'output' / 'workstation-linked-demo'
    folder.mkdir(parents=True, exist_ok=True)
    import uvicorn
    with demo_app(folder / 'local-actions-v1.sqlite3', args.port) as (app, _):
        print(f'Local isolated game: http://127.0.0.1:{args.port}/')
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, log_level='warning')


if __name__ == '__main__':
    main()
