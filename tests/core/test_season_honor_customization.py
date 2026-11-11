from uuid import uuid4
from datetime import timedelta

import pytest
from sqlalchemy import select, func

from .test_honors import context, INITIAL
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.honors import HonorConflict, HonorSeasonMember, HonorGrantInput, SeasonHonorSettingsInput
from dzmm_bot.core.schema import (
    HonorAwardRecord, HonorSeasonRecord, HonorWearRecord, RankRecord, UserRecord,
    AuditEventRecord, PRIMARY_GROUP_CHAT_ID, OutboundRecord,
)
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage


def seed(context, closing_rank="部门副总监", *, current=1):
    repo, factory = context
    user = repo.find_user("male-1")
    with factory.begin() as s:
        s.get(UserRecord, user.id).rank_id = s.scalar(select(RankRecord.id).where(RankRecord.sort_order == current))
        s.add(HonorSeasonRecord(code="S1", issued_at=INITIAL, issued_by="admin", preview_digest="a" * 64, issued_count=1))
        s.flush()
        award = HonorAwardRecord(title_key="season:S1", title_name=f"S1赛季 · 技术部 · {closing_rank}",
            user_id=user.id, winner_name=user.display_name, valid_from=INITIAL, sort_order=1000,
            public_score=False, source="season", season_code="S1",
            source_details={"rank": closing_rank, "department": "技术部", "actor": "admin"})
        s.add(award)
        s.flush()
        return award.id


def chat(repo, content, identifier=None, source="group"):
    return GroupCommandHandler(repo).handle(InboundMessage(
        identifier or str(uuid4()), "male-1", content, INITIAL,
        source_type=source, chatroom_id="group-main" if source == "group" else "dm"))


def test_closing_rank_default_visible_permanent_wear_and_custom_name_once(context):
    repo, factory = context
    award_id = seed(context)
    text = chat(repo, "/赛季称号")
    assert "S1赛季 · 部门副总监（永久）" in text and "自定义一次" in text
    assert "S1赛季 · 部门副总监" in chat(repo, "/我的称号")
    assert repo.wear_honor("male-1", 1, INITIAL) == "S1赛季 · 部门副总监"
    assert "已修改为：S1赛季 · 快乐摸鱼人（永久）" in chat(repo, "/修改赛季称号 快乐摸鱼人", "rename")
    assert "只能修改一次" in chat(repo, "/修改赛季称号 再改一次")
    assert "只能修改一次" in chat(repo, "/修改赛季称号 快乐摸鱼人")
    assert "修改机会已使用" in chat(repo, "/赛季称号")
    assert "S1赛季 · 快乐摸鱼人" in chat(repo, "/我的称号")
    assert repo.get_equipped_honor("male-1", INITIAL + timedelta(days=10000)) == "S1赛季 · 快乐摸鱼人"
    personal = repo.my_honors("male-1", INITIAL)
    assert personal["items"][0]["expires_at"] is None
    assert personal["history_counts"] == {"season:S1": 1}
    history = repo.honor_history(INITIAL, user_id=repo.find_user("male-1").id)["items"][0]
    assert history["name"] == "S1赛季 · 快乐摸鱼人" and history["source_details"]["rank"] == "部门副总监"
    assert history["season_info"]["customized"]
    assert history["season_info"]["original_name"] == "S1赛季 · 技术部 · 部门副总监"
    assert history["season_info"]["customized_at"] == INITIAL.isoformat()
    with factory() as s:
        award = s.get(HonorAwardRecord, award_id)
        assert award.source_details["original_title"] == "S1赛季 · 技术部 · 部门副总监"
        assert award.source_details["rank_order"] == 8
        assert s.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.event_type == "honor_season_customize")) == 1
    # Retrying exactly the same inbound message is safe.
    assert "已修改为" in chat(repo, "/修改赛季称号 快乐摸鱼人", "rename")


def test_configurable_threshold_preserves_customization_and_weekly_settings(context):
    repo, factory = context
    seed(context)
    assert repo.season_honor_settings(INITIAL)["minimum_rank_order"] == 8
    weekly = repo.get_honor_config(INITIAL)
    assert "season_minimum_rank_order" not in weekly["configuration"]
    chat(repo, "/修改赛季称号 开心摸鱼")
    repo.wear_honor("male-1", 1, INITIAL)
    def threshold(value):
        settings = repo.season_honor_settings(INITIAL)
        return repo.update_season_honor_settings(SeasonHonorSettingsInput(
            minimum_rank_order=value, expected_version=settings["version"]), "admin", INITIAL)
    changed = threshold(9)
    assert changed["minimum_rank_order"] == 9
    assert repo.get_equipped_honor("male-1", INITIAL) is None
    assert repo.season_honor("male-1", INITIAL)["status"] == "not_qualified"
    assert "部门总监" in chat(repo, "/赛季称号")
    assert repo.my_honors("male-1", INITIAL)["items"] == []
    assert repo.get_honor_config(INITIAL)["current"] == weekly["current"]
    threshold(8)
    assert repo.season_honor("male-1", INITIAL)["customized"]
    assert "只能修改一次" in chat(repo, "/修改赛季称号 重新取名")
    # A scheduled weekly edit must not reset the immediately active threshold.
    threshold(9)
    config = repo.get_honor_config(INITIAL)
    weekly_payload = {key: value for key, value in config["configuration"].items() if key != "activity_rules"}
    repo.update_honor_config({**weekly_payload, "expected_version": config["version"]}, "admin", INITIAL)
    assert repo.season_honor_settings(INITIAL)["minimum_rank_order"] == 9
    assert repo.season_honor("male-1", INITIAL)["status"] == "not_qualified"
    # Changing the immediate setting keeps pending weekly rules pending.
    pending = repo.get_honor_config(INITIAL)
    threshold(8)
    assert repo.get_honor_config(INITIAL)["effective_week"] == pending["effective_week"]
    assert repo.get_honor_config(INITIAL)["current"] == pending["current"]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(HonorAwardRecord)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEventRecord).where(
            AuditEventRecord.event_type == "honor_season_settings")) == 4


def test_lower_threshold_uses_closing_snapshot_and_unknown_remains_denied(context):
    repo, _ = context
    seed(context, closing_rank="实习生", current=11)
    settings = repo.season_honor_settings(INITIAL)
    repo.update_season_honor_settings(SeasonHonorSettingsInput(
        minimum_rank_order=1, expected_version=settings["version"]), "admin", INITIAL)
    assert repo.season_honor("male-1", INITIAL)["status"] == "available"
    assert repo.season_honor("male-2", INITIAL)["status"] == "not_qualified"


@pytest.mark.parametrize("closing,current,eligible", [("部门经理", 11, False), ("部门副总监", 1, True), ("部门总监", 1, True), ("公司负责人", 1, True), ("核心董事会", 1, True), ("未知职级", 11, False)])
def test_current_rank_never_grants_or_removes_season_eligibility(context, closing, current, eligible):
    repo, factory = context
    award_id = seed(context, closing, current=current)
    if eligible:
        assert repo.season_honor("male-1", INITIAL)["status"] == "available"
    else:
        assert "再接再厉" in chat(repo, "/赛季称号")
        assert "再接再厉" in chat(repo, "/修改赛季称号 不应成功")
        assert repo.my_honors("male-1", INITIAL)["items"] == []
        history = repo.honor_history(INITIAL, user_id=repo.find_user("male-1").id)["items"][0]
        assert history["season_info"]["status"] == "not_qualified" and not history["active"]
        with factory.begin() as s:
            s.add(HonorWearRecord(user_id=repo.find_user("male-1").id, award_id=award_id))
        assert repo.get_equipped_honor("male-1", INITIAL) is None


@pytest.mark.parametrize("name", ["", "x" * 58, "无效\n名字", "【冒充】", "名称\x01", "名字\u007f"])
def test_invalid_names_do_not_use_modification_chance(context, name):
    repo, _ = context
    seed(context)
    with pytest.raises(ValueError):
        repo.customize_season_honor("male-1", name, INITIAL)
    assert not repo.season_honor("male-1", INITIAL)["customized"]


def test_missing_season_and_nonmember_and_usage_feedback(context):
    repo, _ = context
    assert "尚未发放" in chat(repo, "/赛季称号")
    assert "用法" in chat(repo, "/赛季称号 2")
    assert "用法" in chat(repo, "/修改赛季称号")
    assert repo.season_honor("stranger", INITIAL) is None
    seed(context)
    assert repo.season_honor("male-2", INITIAL)["status"] == "not_qualified"


def test_revoke_prevents_customization_without_restoring_chance(context):
    repo, _ = context
    award_id = seed(context)
    repo.customize_season_honor("male-1", "永久自定义", INITIAL)
    repo.revoke_permanent_honor(award_id, "撤回测试", "admin", INITIAL)
    assert "已被撤回" in chat(repo, "/赛季称号")
    assert "已被撤回" in chat(repo, "/修改赛季称号 不应修改")
    assert repo.my_honors("male-1", INITIAL)["items"] == []


def test_new_batch_defaults_to_closing_rank_and_filters_lower_ranks(context):
    repo, _ = context
    roster = [HonorSeasonMember(employee_number=repo.find_user(p).employee_number, department="", rank=r)
              for p, r in [("male-1", "部门副总监"), ("male-2", "部门经理")]]
    preview = repo.preview_s1_honors(roster, INITIAL)
    assert len(preview["rows"]) == 1 and preview["rows"][0]["title"] == "S1赛季 · 部门副总监"
    assert len(preview["skipped"]) == 1
    repo.issue_s1_honors(roster, preview["preview_digest"], "admin", INITIAL)
    assert repo.season_honor("male-1", INITIAL)["default_rank"] == "部门副总监"
    assert repo.season_honor("male-2", INITIAL)["status"] == "not_qualified"


def test_request_replay_creates_one_reply_and_other_permanent_honors_still_work(context):
    repo, factory = context
    seed(context)
    service = CoreService(repo, GroupCommandHandler(repo))
    message = InboundMessage("single-custom", "male-1", "/修改赛季称号 测试称号", INITIAL,
                             source_type="group", chatroom_id="group-main")
    first = service.receive_inbound(message)
    service.receive_inbound(message)
    with factory() as s:
        assert s.scalar(select(func.count()).select_from(OutboundRecord).where(
            OutboundRecord.inbound_message_id == first.message_id)) == 1
    other = repo.find_user("male-2")
    repo.grant_permanent_honor(HonorGrantInput(employee_number=other.employee_number, name="热心同事", reason="测试"), "admin", INITIAL)
    assert repo.my_honors("male-2", INITIAL)["items"][0]["name"] == "热心同事"


@pytest.mark.parametrize("content", ["/赛季称号", "/修改赛季称号 演出之星"])
def test_season_commands_work_in_direct_messages_and_during_performances(context, content):
    from .test_honors import performance
    repo, factory = context
    seed(context)
    performance(factory, repo.find_user("male-1"), INITIAL, state="performing")
    service = CoreService(repo, GroupCommandHandler(repo))
    first = service.receive_inbound(InboundMessage("during-show", "male-1", content, INITIAL,
                                                 source_type="group", chatroom_id="group-main"))
    second = service.receive_inbound(InboundMessage("direct-season", "male-1", "/赛季称号", INITIAL,
                                                  source_type="direct", chatroom_id="dm"))
    with factory() as s:
        for inbound in [first, second]:
            text = s.scalar(select(OutboundRecord.text).where(OutboundRecord.inbound_message_id == inbound.message_id))
            assert "S1赛季" in text


def test_two_requests_share_single_chance_and_failed_audit_rolls_back(context, monkeypatch):
    repo, _ = context
    seed(context)
    original = repo._honor_audit
    def fail(*args, **kwargs):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(repo, "_honor_audit", fail)
    with pytest.raises(RuntimeError, match="injected"):
        repo.customize_season_honor("male-1", "不应保存", INITIAL)
    assert not repo.season_honor("male-1", INITIAL)["customized"]
    monkeypatch.setattr(repo, "_honor_audit", original)
    repo.customize_season_honor("male-1", "只改一次", INITIAL)
    with pytest.raises(HonorConflict, match="只能修改一次"):
        repo.customize_season_honor("male-1", "不同请求", INITIAL)


def test_concurrent_requests_only_one_can_customize(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from dzmm_bot.core.schema import Base
    from dzmm_bot.core.repository import CoreRepository
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'season-custom.db'}",
                           connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repo = CoreRepository(factory)
    repo.bootstrap_primary_group("https://www.aikda.com/chat?c=group-main", INITIAL)
    repo.create_user("male-1", "测试员工", INITIAL, 0)
    repo.get_honor_config(INITIAL)
    seed((repo, factory))
    def customize(name):
        try:
            return CoreRepository(factory).customize_season_honor("male-1", name, INITIAL)["name"]
        except HonorConflict:
            return "rejected"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(customize, ["第一个请求", "第二个请求"]))
        assert results.count("rejected") == 1
        assert repo.season_honor("male-1", INITIAL)["name"] in results
        with factory() as s:
            assert s.scalar(select(func.count()).select_from(AuditEventRecord).where(
                AuditEventRecord.event_type == "honor_season_customize")) == 1
    finally:
        engine.dispose()


def test_new_snapshot_rank_order_survives_renamed_rank_configuration(context):
    repo, factory = context
    user = repo.find_user("male-1")
    with factory.begin() as s:
        row = s.scalar(select(RankRecord).where(RankRecord.sort_order == 8))
        row.name = "自定义领导岗位"
        s.get(UserRecord, user.id).rank_id = row.id
    roster = [HonorSeasonMember(employee_number=user.employee_number, department="", rank="自定义领导岗位")]
    preview = repo.preview_s1_honors(roster, INITIAL)
    assert preview["rows"][0]["rank_order"] == 8
    repo.issue_s1_honors(roster, preview["preview_digest"], "admin", INITIAL)
    with factory.begin() as s:
        s.scalar(select(RankRecord).where(RankRecord.sort_order == 8)).name = "再次更名"
        s.get(UserRecord, user.id).rank_id = s.scalar(select(RankRecord.id).where(RankRecord.sort_order == 1))
    assert repo.season_honor("male-1", INITIAL)["default_rank"] == "自定义领导岗位"
    assert "已修改为" in chat(repo, "/修改赛季称号 历史荣誉")
