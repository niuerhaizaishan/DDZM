from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dzmm_bot.runtime.contracts import InboundMessage

BEIJING = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 17, 10, 0, tzinfo=BEIJING)
JOINED_AT = datetime(2024, 2, 10, 12, 0, tzinfo=BEIJING)

_counter = {"value": 0}


@pytest.fixture
def harness():
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.list_ranks()
    handler = GroupCommandHandler(repository)
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=birthday", NOW
    )
    repository.create_user("p1", "小明", JOINED_AT, 0)
    repository.create_user("p2", "小红", JOINED_AT, 0)
    repository.create_user("p3", "小刚", JOINED_AT, 0)
    return handler, repository, factory, group


def send(handler, group, platform_id, content, *, now=NOW):
    _counter["value"] += 1
    reply = handler.handle(
        InboundMessage(
            f"m-{_counter['value']}",
            platform_id,
            content,
            now,
            source_type="group",
            chatroom_id=group.chatroom_id,
        )
    )
    if isinstance(reply, list):
        return "\n".join(reply)
    return reply or ""


# ------------------------------------------------------------------ 登记

def test_setting_a_birthday_is_saved_and_echoed(harness):
    handler, repository, _, group = harness

    reply = send(handler, group, "p1", "/设置生日 5-20")

    view = repository.get_employee_birthday("p1", NOW)
    assert view is not None
    assert (view.month, view.day) == (5, 20)
    assert view.visibility == "public"
    assert view.year is None
    assert "5 月 20 日" in reply
    assert "2027-05-20" in reply


def test_every_input_shape_is_accepted(harness):
    handler, repository, _, group = harness

    for text in ("5/20", "05.20", "5月20日", "1995年5月20日"):
        send(handler, group, "p1", f"/设置生日 {text}")
        view = repository.get_employee_birthday("p1", NOW)
        assert view is not None and (view.month, view.day) == (5, 20)


def test_a_birthday_can_be_hidden(harness):
    handler, repository, _, group = harness

    reply = send(handler, group, "p1", "/设置生日 5-20 不公开")

    view = repository.get_employee_birthday("p1", NOW)
    assert view is not None and view.visibility == "private"
    assert "不公开" in reply
    listing = repository.list_month_birthdays(datetime(2026, 5, 1, tzinfo=BEIJING))
    assert listing.entries == ()


def test_an_impossible_date_is_refused(harness):
    handler, repository, _, group = harness

    reply = send(handler, group, "p1", "/设置生日 2-30")

    assert "这个日期不存在" in reply
    assert repository.get_employee_birthday("p1", NOW) is None


def test_a_missing_date_shows_the_usage(harness):
    handler, repository, _, group = harness

    reply = send(handler, group, "p1", "/设置生日")

    assert "请用 /设置生日 5-20" in reply
    assert repository.get_employee_birthday("p1", NOW) is None


def test_a_stranger_cannot_register(harness):
    handler, _, _, group = harness

    reply = send(handler, group, "p9", "/设置生日 5-20")

    assert "请先用 /入职" in reply


# ------------------------------------------------------------ 一年改一次

def test_a_birthday_can_only_be_changed_once_a_year(harness):
    """首次登记不算改；登记之后每个自然年只能改一次。"""
    handler, repository, _, group = harness
    send(handler, group, "p1", "/设置生日 5-20")

    first_change = send(handler, group, "p1", "/设置生日 6-1")
    second_change = send(handler, group, "p1", "/设置生日 7-2")

    view = repository.get_employee_birthday("p1", NOW)
    assert view is not None and (view.month, view.day) == (6, 1)
    assert "一年只能改一次" not in first_change
    assert "一年只能改一次" in second_change


def test_the_quota_resets_next_year(harness):
    handler, repository, _, group = harness
    send(handler, group, "p1", "/设置生日 5-20")
    send(handler, group, "p1", "/设置生日 6-1")

    later = NOW + timedelta(days=365)
    send(handler, group, "p1", "/设置生日 7-1", now=later)

    view = repository.get_employee_birthday("p1", later)
    assert view is not None and (view.month, view.day) == (7, 1)


# ---------------------------------------------------------------- 查询

def test_my_birthday_says_when_it_is_missing_and_when_it_is_known(harness):
    handler, _, _, group = harness

    assert "还没登记" in send(handler, group, "p1", "/我的生日")

    send(handler, group, "p1", "/设置生日 5-20")
    reply = send(handler, group, "p1", "/我的生日")

    assert "5 月 20 日" in reply
    assert "2 年" in reply  # 2024-02-10 入职，2026-09-17 时是 2 年 7 个月


def test_this_month_lists_the_public_birthdays_and_marks_today(harness):
    handler, repository, _, group = harness
    send(handler, group, "p1", "/设置生日 9-17")
    send(handler, group, "p2", "/设置生日 9-20")
    send(handler, group, "p3", "/设置生日 9-21 不公开")

    reply = send(handler, group, "p1", "/本月生日")

    assert "小明（9-17，就是今天）" in reply
    assert "小红（9-20）" in reply
    assert "小刚" not in reply
    assert "共 2 位" in reply


def test_this_month_says_so_when_nobody_registered(harness):
    handler, _, _, group = harness

    reply = send(handler, group, "p1", "/本月生日")

    assert "还没有登记生日的同事" in reply


# ------------------------------------------------------------- 白名单守护

def test_the_new_commands_are_allowed_while_a_random_event_runs():
    from dzmm_bot.core.repository import _RANDOM_EVENT_CONFIGURABLE_COMMANDS

    assert {"/设置生日", "/我的生日", "/本月生日"} <= (
        _RANDOM_EVENT_CONFIGURABLE_COMMANDS
    )


def test_the_admin_checkboxes_cover_the_birthday_commands():
    """复选框数组漏登记，管理员存一次随机事件规则就会把它们静默删掉。"""
    root = Path(__file__).resolve().parents[2]
    source = (root / "src/dzmm_bot/admin/static/admin.js").read_text(
        encoding="utf-8"
    )
    block = source.split("randomEventCommandOptions = [", 1)[1].split("];", 1)[0]

    assert '"/设置生日"' in block
    assert '"/我的生日"' in block
    assert '"/本月生日"' in block
