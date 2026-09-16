from datetime import datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.runtime.contracts import InboundMessage

BEIJING = __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 15, 16, 20, tzinfo=BEIJING)
TARGET_AT = NOW + timedelta(hours=3)
JOINED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BEIJING)


def _service():
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base, RankRecord
    from dzmm_bot.core.service import CoreService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.list_ranks()
    with factory.begin() as session:
        session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 1)
        ).multiplayer_game_limit = 999
    return CoreService(repository, GroupCommandHandler(repository)), repository, factory


def _purge(factory):
    from dzmm_bot.core.schema import OutboundRecord

    with factory.begin() as session:
        session.query(OutboundRecord).delete()


def _reply(factory):
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        texts = list(
            session.scalars(
                select(OutboundRecord.text).order_by(
                    OutboundRecord.reply_index, OutboundRecord.created_at
                )
            )
        )
    if not texts:
        return None
    return "\n".join(texts)


def _seed_scenes(session, names=("甲", "乙", "丙")):
    from dzmm_bot.core.schema import (
        RandomEventSceneOpeningRecord,
        RandomEventSceneRecord,
        RandomEventSceneSeatRecord,
    )

    for name in names:
        scene = RandomEventSceneRecord(
            name=name,
            signup_text=f"{name} 报名",
            reward=6,
            target_rounds=3,
            enabled=True,
            created_at=JOINED_AT,
        )
        session.add(scene)
        session.flush()
        session.add(
            RandomEventSceneOpeningRecord(
                scene_id=scene.id, position=1, name=f"{name} 事件", content="开场"
            )
        )
        session.add(
            RandomEventSceneSeatRecord(scene_id=scene.id, role="主持", capacity=1)
        )


def _open_poll(repository, factory, *, running=False):
    """建群、建员工、造场景与目标场次，然后开一期投票。"""
    from dzmm_bot.core.schema import (
        RandomEventRecord,
        RandomEventScheduleRecord,
    )

    with factory.begin() as session:
        _seed_scenes(session)
        schedule = RandomEventScheduleRecord(
            group_chat_id=repository.list_group_chats()[0].id,
            event_date=TARGET_AT.date(),
            scheduled_at=TARGET_AT,
            status="pending",
        )
        session.add(schedule)
        session.flush()
        if running:
            active_schedule = RandomEventScheduleRecord(
                group_chat_id=schedule.group_chat_id,
                event_date=NOW.date(),
                scheduled_at=NOW - timedelta(hours=1),
                status="in_progress",
                scene_name="占用中",
            )
            session.add(active_schedule)
            session.flush()
            session.add(
                RandomEventRecord(
                    group_chat_id=schedule.group_chat_id,
                    schedule_id=active_schedule.id,
                    group_key="default",
                    state="in_progress",
                    scene_name="占用中",
                    event_name="占用中 事件",
                    signup_text="报名",
                    formal_opening_text="开场",
                    reward=6,
                    target_rounds=3,
                    signup_deadline=NOW - timedelta(minutes=30),
                    started_at=NOW - timedelta(hours=1),
                )
            )
    return repository.create_random_event_poll(NOW)


def _setup(*, running=False):
    service, repository, factory = _service()
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=event-vote", NOW
    )
    repository.create_user("p1", "小明", NOW, 100)
    repository.create_user("p2", "小红", NOW, 100)
    view = _open_poll(repository, factory, running=running)
    return service, repository, factory, group, view


def _send(service, group, message_id, sender, content, now=NOW):
    _purge(service._repository._session_factory)
    service.receive_inbound(
        InboundMessage(
            message_id,
            sender,
            content,
            now,
            source_type="group",
            chatroom_id=group.chatroom_id,
        )
    )


# ------------------------------------------------------------------ 投票

def test_vote_command_records_the_vote():
    service, repository, factory, group, view = _setup()
    scene_name = view.candidates[0].scene_name

    _send(service, group, "m1", "p1", "/事件投票 1")

    text = _reply(factory)
    assert "已投" in text
    assert scene_name in text
    assert "1 票" in text


def test_vote_command_reports_a_change():
    service, repository, factory, group, view = _setup()
    _send(service, group, "m1", "p1", "/事件投票 1")

    _send(service, group, "m2", "p1", "/事件投票 2")

    assert "改投" in _reply(factory)
    assert repository.random_event_poll_view("p1").my_position == 2


def test_vote_command_rejects_a_bad_position():
    service, repository, factory, group, view = _setup()

    _send(service, group, "m1", "p1", "/事件投票 9")
    assert "9 号候选" in _reply(factory)

    _send(service, group, "m2", "p1", "/事件投票 abc")
    assert "/事件投票" in _reply(factory)

    _send(service, group, "m3", "p1", "/事件投票")
    assert "/事件投票" in _reply(factory)


def test_vote_command_rejects_the_vacant_slot():
    service, repository, factory, group, view = _setup()

    _send(service, group, "m1", "p1", "/事件投票 4")

    assert "招商中" in _reply(factory)
    assert repository.random_event_poll_view("p1").my_position is None


def test_vote_command_without_a_poll():
    service, repository, factory = _service()
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=event-vote-none", NOW
    )
    repository.create_user("p1", "小明", NOW, 100)

    _send(service, group, "m1", "p1", "/事件投票 1")

    assert "没有正在进行的投票" in _reply(factory)


def test_vote_command_rejects_an_outsider():
    service, repository, factory, group, view = _setup()

    _send(service, group, "m1", "outsider", "/事件投票 1")

    assert "入职" in _reply(factory)


def test_vote_command_lists_the_tally():
    service, repository, factory, group, view = _setup()
    _send(service, group, "m1", "p1", "/事件投票 1")
    _send(service, group, "m2", "p2", "/事件投票 1")
    _send(service, group, "m3", "p2", "/事件投票 2")

    _send(service, group, "m4", "p1", "/事件投票情况")

    text = _reply(factory)
    assert "2 票" in text
    assert "1 票" in text
    assert "招商中" in text
    assert "你投的是 1 号" in text


# ------------------------------------------------------------------ 门禁

def test_vote_command_works_while_a_random_event_is_running():
    """随机事件进行中也要能投票，否则上一场还在演时全公司都投不了票。"""
    service, repository, factory, group, view = _setup(running=True)

    _send(service, group, "m1", "p1", "/事件投票 1")

    text = _reply(factory)
    assert text is not None
    assert "监事不会处理" not in text
    assert "已投" in text


def test_vote_command_is_registered_in_every_whitelist():
    """少登记一处就是静默失效：指令没反应、或活动期间永远无法放行。"""
    from dzmm_bot.core import repository as repository_module
    from dzmm_bot.core.commands import _COMMANDS
    from dzmm_bot.core.reply_templates import TEMPLATE_DEFINITIONS

    definitions = {item[0] for item in repository_module._COMMAND_DEFINITIONS}
    templates = {item.command for item in TEMPLATE_DEFINITIONS}

    for command in ("/事件投票", "/事件投票情况"):
        assert command in _COMMANDS, command
        assert command in definitions, command
        assert command in templates, command
        assert command in repository_module._RANDOM_EVENT_CONFIGURABLE_COMMANDS, command


def test_admin_command_checkboxes_cover_the_vote_commands():
    """后台"可执行指令"复选框是硬编码数组：漏了这两条，管理员存一次随机事件
    规则就会把投票指令从放行清单里静默删掉（迁移 77 只保护升级那一刻）。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    source = (root / "src/dzmm_bot/admin/static/admin.js").read_text(
        encoding="utf-8"
    )
    block = source.split("randomEventCommandOptions = [", 1)[1].split("];", 1)[0]

    assert '"/事件投票"' in block
    assert '"/事件投票情况"' in block
