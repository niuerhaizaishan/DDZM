from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from secrets import choice
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .bot_accounts import BOT_PLATFORM_IDS
from .game_statistics import sync_game_participations
from .schema import (
    ActivityLevelRuleRecord, AIRequestRecord, AuditEventRecord, BEIJING,
    DailyCheckinRecord, DarkMarketListingRecord, EstrusChopRecord, GroupChatRecord,
    HonorAwardRecord, HonorConfigRecord, HonorPeriodRecord, HonorStateRecord,
    HonorWearRecord, InboundRecord, PerformanceParticipantRecord,
    PerformanceReservationRecord, PerformanceTipRecord, PRIMARY_GROUP_CHAT_ID,
    RandomEventParticipantRecord, RandomEventRecord,
    RandomEventSubmissionRecord, RandomEventTipRecord, UserRecord,
    GameParticipationRecord, KingGameRecord, KingGameRoundRecord,
    NumberBombGameRecord, NumberBombRoundRecord, NumberBombRoundPlayerRecord,
    TexasHoldemGameRecord, TexasHoldemPlayerRecord,
)


TITLE_SPECS = (
    ("checkin_king", "牛马之王", "weekly_checkin", None, 1, 7),
    ("chatter", "超级话痨", "chatter", None, 1, 10),
    ("actor_m", "周最佳男主角", "tip_received", "male", 1, 1),
    ("actor_f", "周最佳女主角", "tip_received", "female", 1, 1),
    ("performer_m", "周最骚帅哥", "performance", "male", 1, 1),
    ("performer_f", "周最骚妹子", "performance", "female", 1, 1),
    ("tip_first_m", "榜一大哥", "tip_given", "male", 1, 1),
    ("tip_first_f", "榜一大姐", "tip_given", "female", 1, 1),
    ("tip_second_m", "榜二大哥", "tip_given", "male", 2, 1),
    ("tip_second_f", "榜二大姐", "tip_given", "female", 2, 1),
    ("submission", "色色大师", "submission", None, 1, 1),
    ("game_king", "超级游戏王", "game_count", None, 1, 1),
    ("boomerang", "我杀我自己", "boomerang", None, 1, 1),
    ("punished", "极品抖 M", "punished", None, 1, 1),
    ("lucky", "摸鱼幸运星", "lucky", None, 1, 1),
    ("slacker", "超级咸鱼", "slacker", None, 1, 3),
    ("charm_m", "公司最靓的仔", "chopped", "male", 1, 1),
    ("charm_f", "公司最正的妞", "chopped", "female", 1, 1),
    ("buyer_m", "金主爸爸", "market_spend", "male", 1, 1),
    ("buyer_f", "金主妈妈", "market_spend", "female", 1, 1),
    ("seller_m", "极品男奸商", "market_sales", "male", 1, 1),
    ("seller_f", "极品女奸商", "market_sales", "female", 1, 1),
    ("market_star", "地下人气王", "market_income", None, 1, 1),
    ("poker_profit", "赌圣", "poker_profit", None, 1, 1),
    ("poker_count", "赌鬼", "poker_count", None, 1, 1),
    ("poker_loss", "扫把星", "poker_loss", None, 1, 1),
    ("bot_friend", "总监事之友", "bot_mention", None, 1, 1),
    ("checkin_god", "牛马之神", "streak", None, 1, 30),
    ("checkin_immortal", "牛马之仙", "streak", None, 1, 100),
)
CHECKIN_TITLES = {"checkin_king", "checkin_god", "checkin_immortal"}
TITLE_VALID_DAYS = {"checkin_god": 30, "checkin_immortal": 100}
SUPPORTED_METRICS = {
    "streak", "weekly_checkin", "chatter", "slacker", "tip_received", "tip_given", "performance",
    "submission", "chopped", "market_spend", "market_sales", "market_income",
    "game_count", "boomerang", "punished", "lucky", "poker_profit", "poker_count",
    "poker_loss", "bot_mention",
}
METRIC_LABELS = {
    "weekly_checkin": "本统计周截至周日连续打卡天数，最多七天；默认七天全勤，所有达标者均获得",
    "streak": "截至统计周周日的跨周连续打卡天数，所有达到门槛的员工均获得",
    "chatter": "七天每天达到门槛活跃等级，再按周活跃字数排名",
    "slacker": "七天打卡且每天不高于门槛等级，按周活跃字数从少到多排名",
    "tip_received": "随机事件与公演收到的有效打赏总金额",
    "tip_given": "随机事件与公演支出的有效打赏总金额",
    "performance": "已结束的随机事件、公演中的有效参演次数",
    "submission": "本周审核通过的投稿次数（按审核时间）",
    "chopped": "本周成功被凿次数（所有群合并统计）",
    "market_spend": "最终结算的暗网消费金额（按结算时间）",
    "market_sales": "最终结算的暗网卖出次数（按结算时间）",
    "market_income": "最终结算的暗网净收益（扣除手续费）",
    "game_count": "本周结束的有效整局参与次数，每人每局一次；强制结束需已完成一轮",
    "boomerang": "国王游戏已揭晓轮次中，国王选中自己号码的次数",
    "punished": "国王游戏已揭晓轮次被选中次数，加蹦蹦数字炸弹有效结算轮次受罚次数（含积分赛；跳过、退赛不计）",
    "lucky": "国王游戏已揭晓有效轮次当选国王次数，加蹦蹦数字炸弹有效结算轮次胜出次数（含积分赛；并列各计一次）",
    "poker_profit": "本周已结算德州扑克累计净盈利（最终筹码减买入，先合计再排名）",
    "poker_count": "本周已完成结算的德州扑克整局参与次数",
    "poker_loss": "本周已结算德州扑克累计净亏损（先合计再排名）",
    "bot_mention": "所选群内成功完成且有回复内容的 AI 互动次数，同一请求重试只计一次",
}


def week_of(value):
    day = value.astimezone(BEIJING).date() if isinstance(value, datetime) else value
    return day - timedelta(days=day.weekday())


def midnight(day):
    return datetime.combine(day, time(), BEIJING)


def default_honor_config():
    return {
        "enabled": False,
        "group_ids": [str(PRIMARY_GROUP_CHAT_ID)],
        "announcement_group_id": str(PRIMARY_GROUP_CHAT_ID),
        "announce": True,
        "announcement_time": "09:00",
        "rules": [
            {"key": key, "name": name, "enabled": metric in SUPPORTED_METRICS,
             "description": METRIC_LABELS[metric],
             "minimum": minimum, "sort_order": position, "public_score": True}
            for position, (key, name, metric, gender, rank, minimum) in enumerate(TITLE_SPECS, 1)
        ],
    }


def honor_configuration(snapshot):
    values = deepcopy(snapshot)
    values.setdefault("announcement_time", "09:00")
    keys = {rule["key"] for rule in values["rules"]}
    if not keys.intersection({"checkin_god", "checkin_immortal"}):
        for rule in values["rules"]:
            if rule["key"] == "checkin_king":
                rule.update(minimum=7, description=METRIC_LABELS["weekly_checkin"])
    values["rules"].extend(rule for rule in default_honor_config()["rules"] if rule["key"] not in keys)
    return values


def honor_award_lines(awards, public_scores=False, include_empty=False):
    grouped = defaultdict(list)
    for award in awards:
        grouped[award["key"]].append(award)
    lines = []
    for records in grouped.values():
        winners = [record for record in records if record["user_id"]]
        title = records[0]["name"]
        if records[0]["key"] in CHECKIN_TITLES and winners:
            names = "、".join(record["winner_name"] for record in winners[:10])
            suffix = "等" if len(winners) > 10 else ""
            lines.append(f"{title}：{names}{suffix}（达标 {len(winners)} 人）")
        elif winners:
            record = winners[0]
            score = f"（成绩：{record['score']}）" if public_scores and record["score"] is not None else ""
            lines.append(f"{title}：{record['winner_name']}{score}")
        elif include_empty:
            lines.append(f"{title}：暂无获得者")
    return lines


class HonorRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    key: str
    name: str = Field(min_length=1, max_length=64)
    enabled: StrictBool
    description: str = Field(max_length=300)
    minimum: int = Field(ge=0, le=100000000)
    sort_order: int = Field(ge=1, le=999)
    public_score: StrictBool


class HonorConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: StrictBool
    group_ids: list[str] = Field(min_length=1, max_length=100)
    announcement_group_id: str | None
    announce: StrictBool
    announcement_time: str = Field(default="09:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    rules: list[HonorRuleInput] = Field(min_length=len(TITLE_SPECS), max_length=len(TITLE_SPECS))
    expected_version: int = Field(ge=0)


class HonorSettleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date
    preview_digest: str = Field(min_length=64, max_length=64)


class HonorCorrectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    winner_id: UUID | None
    reason: str = Field(min_length=1, max_length=300)
    expected_revision: int = Field(ge=1)


class HonorConflict(ValueError):
    pass


class HonorConfigRequest(HonorConfigInput):
    actor: str = Field(min_length=1, max_length=128)


class HonorSettleRequest(HonorSettleInput):
    actor: str = Field(min_length=1, max_length=128)


class HonorBackfillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, max_length=128)


class HonorCorrectionRequest(HonorCorrectionInput):
    actor: str = Field(min_length=1, max_length=128)


class HonorsMixin:
    def _honor_lock(self, session, now):
        self._lock_gameplay_gate(session)
        dialect = session.get_bind().dialect.name
        insert = postgres_insert if dialect == "postgresql" else sqlite_insert
        session.execute(insert(HonorStateRecord).values(
            id=1, version=0, next_week=week_of(now),
        ).on_conflict_do_nothing(index_elements=["id"]))
        state = session.scalar(select(HonorStateRecord).where(
            HonorStateRecord.id == 1,
        ).with_for_update().execution_options(populate_existing=True))
        if session.get(HonorConfigRecord, self._honor_initial_id()) is None:
            self.ensure_activity_settings()
            config = default_honor_config()
            config["activity_rules"] = [(row.level, row.character_threshold) for row in session.scalars(select(ActivityLevelRuleRecord))]
            session.add(HonorConfigRecord(
                id=self._honor_initial_id(), version=0, effective_week=state.next_week,
                snapshot=config, created_at=now,
            ))
            session.flush()
        return state

    @staticmethod
    def _honor_initial_id():
        return UUID("00000000-0000-0000-0000-000000000096")

    @staticmethod
    def _honor_config_for(session, week):
        return session.scalar(select(HonorConfigRecord).where(
            HonorConfigRecord.effective_week <= week,
        ).order_by(HonorConfigRecord.effective_week.desc(), HonorConfigRecord.version.desc()).limit(1))

    def get_honor_config(self, now):
        with self.transaction(), self._session() as session:
            state = self._honor_lock(session, now)
            current = self._honor_config_for(session, week_of(now))
            latest = session.scalar(select(HonorConfigRecord).order_by(HonorConfigRecord.version.desc()).limit(1))
            first_week = session.get(HonorConfigRecord, self._honor_initial_id()).effective_week
            definitions = [{"key": spec[0], "metric": spec[2], "gender": spec[3],
                            "place": spec[4], "supported": spec[2] in SUPPORTED_METRICS,
                            "all_qualified": spec[0] in CHECKIN_TITLES,
                            "valid_days": TITLE_VALID_DAYS.get(spec[0], 7),
                            "metric_description": METRIC_LABELS[spec[2]]}
                           for spec in TITLE_SPECS]
            current_values = honor_configuration(current.snapshot)
            latest_values = honor_configuration(latest.snapshot)
            return {"version": state.version, "effective_week": latest.effective_week.isoformat(),
                    "current": current_values, "configuration": latest_values,
                    "definitions": definitions, "next_week": state.next_week.isoformat(),
                    "first_week": first_week.isoformat()}

    def update_honor_config(self, payload, actor, now):
        request = HonorConfigInput.model_validate(payload)
        values = request.model_dump(exclude={"expected_version"})
        specs = {spec[0]: spec for spec in TITLE_SPECS}
        if {rule.key for rule in request.rules} != set(specs):
            raise ValueError("称号清单不完整或有重复，请刷新页面")
        names = []
        for rule in values["rules"]:
            rule["name"] = rule["name"].strip()
            if not rule["name"] or any(char in rule["name"] for char in "\r\n【】"):
                raise ValueError("称号名称不能为空，也不能包含换行或【】")
            names.append(rule["name"])
            metric = specs[rule["key"]][2]
            if rule["enabled"] and metric not in SUPPORTED_METRICS:
                raise ValueError("该称号的统计口径尚未实现，不能启用")
            if metric in {"chatter", "slacker"} and not 1 <= rule["minimum"] <= 10:
                raise ValueError("活跃度门槛应为 LV1–LV10")
            if metric == "weekly_checkin" and not 1 <= rule["minimum"] <= 7:
                raise ValueError("周打卡门槛应为 1–7 天")
            if metric != "slacker" and rule["minimum"] < 1:
                raise ValueError("资格门槛至少为 1，避免零成绩获奖")
        if len(set(names)) != len(names):
            raise ValueError("称号名称不能重复")
        try:
            groups = sorted({str(UUID(value)) for value in values["group_ids"]})
            announcement = str(UUID(values["announcement_group_id"])) if values["announcement_group_id"] else None
        except ValueError as error:
            raise ValueError("群聊 ID 无效") from error
        if values["announce"] and not announcement:
            raise ValueError("开启公告时必须选择公告群")
        values["group_ids"] = groups
        values["announcement_group_id"] = announcement
        with self.transaction(), self._session() as session:
            state = self._honor_lock(session, now)
            if state.version != request.expected_version:
                raise HonorConflict("配置已被修改，请刷新后重试")
            for group_id in set(groups + ([announcement] if announcement else [])):
                group = session.get(GroupChatRecord, UUID(group_id))
                if group is None or group.deleted_at is not None:
                    raise ValueError("所选群聊不存在或已删除")
            before = self.get_honor_config(now)["configuration"]
            self.ensure_activity_settings()
            values["activity_rules"] = [(row.level, row.character_threshold) for row in session.scalars(select(ActivityLevelRuleRecord))]
            state.version += 1
            effective = week_of(now) + timedelta(days=7)
            session.add(HonorConfigRecord(version=state.version, effective_week=effective,
                                          snapshot=values, created_at=now))
            self._honor_audit(session, "honor_config", actor,
                              {"before": before, "after": values, "effective_week": effective.isoformat()}, now)
            session.flush()
            return self.get_honor_config(now)

    @staticmethod
    def _honor_audit(session, kind, actor, payload, now):
        session.add(AuditEventRecord(event_type=kind, actor=actor, payload=payload, created_at=now))

    def _honor_metrics(self, session, config, week):
        start, end = midnight(week), midnight(week + timedelta(days=7))
        groups = [UUID(value) for value in config["group_ids"]]
        users = {user.id: user for user in session.scalars(select(UserRecord).where(
            UserRecord.joined_at < end,
            UserRecord.platform_id.not_in(BOT_PLATFORM_IDS),
        ))}
        scores = {metric: defaultdict(int) for metric in SUPPORTED_METRICS}

        sync_game_participations(session, start, end, groups)
        for user_id, count in session.execute(select(GameParticipationRecord.user_id, func.count()).where(
            GameParticipationRecord.completed_at >= start, GameParticipationRecord.completed_at < end,
            GameParticipationRecord.group_chat_id.in_(groups),
        ).group_by(GameParticipationRecord.user_id)):
            scores["game_count"][user_id] = count

        for round_record in session.scalars(select(KingGameRoundRecord).join(
            KingGameRecord, KingGameRoundRecord.game_id == KingGameRecord.id,
        ).where(KingGameRoundRecord.state == "revealed", KingGameRoundRecord.revealed_at >= start,
                KingGameRoundRecord.revealed_at < end, KingGameRecord.group_chat_id.in_(groups))):
            scores["lucky"][round_record.king_user_id] += 1
            selected = set(round_record.revealed_numbers or [])
            for user_id, number in (round_record.number_map or {}).items():
                if number in selected:
                    target = UUID(user_id)
                    scores["punished"][target] += 1
                    if target == round_record.king_user_id:
                        scores["boomerang"][target] += 1

        for user_id, result, count in session.execute(select(
            NumberBombRoundPlayerRecord.user_id, NumberBombRoundPlayerRecord.result, func.count(),
        ).join(NumberBombRoundRecord, NumberBombRoundPlayerRecord.round_id == NumberBombRoundRecord.id).join(
            NumberBombGameRecord, NumberBombRoundRecord.game_id == NumberBombGameRecord.id,
        ).where(NumberBombRoundRecord.state == "settled", NumberBombRoundRecord.finished_at >= start,
                NumberBombRoundRecord.finished_at < end, NumberBombGameRecord.group_chat_id.in_(groups),
                NumberBombRoundPlayerRecord.result.in_(("winner", "punished")),
                NumberBombRoundPlayerRecord.submitted_number.is_not(None),
                NumberBombRoundPlayerRecord.skipped_at.is_(None),
                (NumberBombRoundPlayerRecord.result_reason.is_(None)
                 | (NumberBombRoundPlayerRecord.result_reason == "reported")),
        ).group_by(NumberBombRoundPlayerRecord.user_id, NumberBombRoundPlayerRecord.result)):
            scores["lucky" if result == "winner" else "punished"][user_id] += count

        for user_id, count, net in session.execute(select(
            TexasHoldemPlayerRecord.user_id, func.count(),
            func.sum(TexasHoldemPlayerRecord.stack - TexasHoldemPlayerRecord.original_buy_in),
        ).join(TexasHoldemGameRecord, TexasHoldemPlayerRecord.game_id == TexasHoldemGameRecord.id).where(
            TexasHoldemGameRecord.state == "settled", TexasHoldemGameRecord.settlement_complete.is_(True),
            TexasHoldemGameRecord.finished_at >= start, TexasHoldemGameRecord.finished_at < end,
            TexasHoldemGameRecord.group_chat_id.in_(groups), TexasHoldemPlayerRecord.seat_number.is_not(None),
        ).group_by(TexasHoldemPlayerRecord.user_id)):
            scores["poker_count"][user_id] = count
            scores["poker_profit"][user_id] = max(net, 0)
            scores["poker_loss"][user_id] = max(-net, 0)

        for request in session.scalars(select(AIRequestRecord).join(
            InboundRecord, AIRequestRecord.inbound_message_id == InboundRecord.id,
        ).where(AIRequestRecord.status == "completed", AIRequestRecord.completed_at >= start,
                AIRequestRecord.completed_at < end, InboundRecord.source_type == "group",
                InboundRecord.group_chat_id.in_(groups))):
            if (request.result_text or "").strip():
                scores["bot_mention"][request.user_id] += 1

        for tip_type, event_type, event_id in (
            (RandomEventTipRecord, RandomEventRecord, RandomEventTipRecord.event_id),
            (PerformanceTipRecord, PerformanceReservationRecord, PerformanceTipRecord.reservation_id),
        ):
            for tip in session.scalars(select(tip_type).join(event_type, event_id == event_type.id).where(
                tip_type.created_at >= start, tip_type.created_at < end, event_type.group_chat_id.in_(groups),
            )):
                scores["tip_given"][tip.sender_user_id] += tip.amount
                scores["tip_received"][tip.recipient_user_id] += tip.amount

        for participant, event, event_id in (
            (RandomEventParticipantRecord, RandomEventRecord, RandomEventParticipantRecord.event_id),
            (PerformanceParticipantRecord, PerformanceReservationRecord, PerformanceParticipantRecord.reservation_id),
        ):
            filters = [event.ended_at >= start, event.ended_at < end,
                       event.group_chat_id.in_(groups),
                       event.state == ("ended" if event is RandomEventRecord else "completed")]
            if participant is RandomEventParticipantRecord:
                filters.append(participant.rounds > 0)
            for user_id, count in session.execute(select(participant.user_id, func.count()).join(
                event, event_id == event.id,
            ).where(*filters).group_by(participant.user_id)):
                scores["performance"][user_id] += count

        for user_id, count in session.execute(select(RandomEventSubmissionRecord.user_id, func.count()).where(
            RandomEventSubmissionRecord.status == "approved",
            RandomEventSubmissionRecord.reviewed_at >= start, RandomEventSubmissionRecord.reviewed_at < end,
        ).group_by(RandomEventSubmissionRecord.user_id)):
            scores["submission"][user_id] = count
        for user_id, count in session.execute(select(EstrusChopRecord.target_user_id, func.count()).where(
            EstrusChopRecord.created_at >= start, EstrusChopRecord.created_at < end,
        ).group_by(EstrusChopRecord.target_user_id)):
            scores["chopped"][user_id] = count
        for listing in session.scalars(select(DarkMarketListingRecord).where(
            DarkMarketListingRecord.state == "sold", DarkMarketListingRecord.finished_at >= start,
            DarkMarketListingRecord.finished_at < end, DarkMarketListingRecord.announcement_group_id.in_(groups),
        )):
            if listing.buyer_user_id is None or listing.final_amount is None:
                continue
            scores["market_spend"][listing.buyer_user_id] += listing.final_amount
            scores["market_sales"][listing.seller_user_id] += 1
            scores["market_income"][listing.seller_user_id] += listing.final_amount - (listing.fee_amount or 0)

        checkins = defaultdict(set)
        for user_id, day in session.execute(select(DailyCheckinRecord.user_id, DailyCheckinRecord.checkin_date).where(
            DailyCheckinRecord.checkin_date < week + timedelta(days=7),
        )):
            checkins[user_id].add(day)
        activity = defaultdict(lambda: defaultdict(int))
        for user_id, content, occurred in session.execute(select(
            UserRecord.id, InboundRecord.content, InboundRecord.received_at,
        ).join(UserRecord, UserRecord.platform_id == InboundRecord.sender_platform_id).where(
            InboundRecord.received_at >= start, InboundRecord.received_at < end,
            InboundRecord.source_type == "group", InboundRecord.group_chat_id.in_(groups),
            InboundRecord.content_type != "system",
            InboundRecord.received_at >= UserRecord.joined_at,
        )):
            if not content.lstrip().startswith("/"):
                activity[user_id][occurred.date()] += len("".join(content.split()))
        levels = config["activity_rules"]
        qualifying = {"chatter": {}, "slacker": {}}
        for user_id in users:
            day = week + timedelta(days=6)
            streak = 0
            while day in checkins[user_id]:
                streak += 1
                day -= timedelta(days=1)
            scores["streak"][user_id] = streak
            scores["weekly_checkin"][user_id] = min(streak, 7)
            daily_levels = [max((level for level, threshold in levels if activity[user_id][week + timedelta(days=offset)] >= threshold), default=0)
                            for offset in range(7)]
            total = sum(activity[user_id].values())
            qualifying["chatter"][user_id] = min(daily_levels)
            qualifying["slacker"][user_id] = max(daily_levels) if all(
                week + timedelta(days=offset) in checkins[user_id] for offset in range(7)
            ) else None
            scores["chatter"][user_id] = total
            scores["slacker"][user_id] = total
        return users, scores, qualifying

    def _honor_report(self, session, week, now):
        if week.weekday() != 0:
            raise ValueError("统计周期必须从周一开始")
        if week > week_of(now):
            raise ValueError("不能预览未来周期")
        revision = self._honor_config_for(session, week)
        if revision is None:
            raise ValueError("该周期早于称号系统启用时间，不能补算")
        config = honor_configuration(revision.snapshot)
        if config["enabled"]:
            users, scores, qualifying = self._honor_metrics(session, config, week)
        else:
            users, scores, qualifying = {}, {metric: {} for metric in SUPPORTED_METRICS}, {}
        rules = {rule["key"]: rule for rule in config["rules"]}
        entries = []
        for key, name, metric, gender, place, minimum in TITLE_SPECS:
            rule = rules[key]
            candidates = []
            if config["enabled"] and rule["enabled"] and metric in SUPPORTED_METRICS:
                for user_id, score in scores[metric].items():
                    user = users.get(user_id)
                    if user is None or (gender and user.gender != gender):
                        continue
                    if metric == "chatter":
                        eligible = qualifying[metric][user_id] >= rule["minimum"]
                    elif metric == "slacker":
                        level = qualifying[metric][user_id]
                        eligible = level is not None and level <= rule["minimum"]
                    else:
                        eligible = score >= rule["minimum"]
                    candidates.append({"user_id": str(user_id), "name": user.display_name,
                                       "score": score, "eligible": eligible})
                candidates.sort(key=lambda entry: (entry["score"] if metric == "slacker" else -entry["score"], entry["user_id"]))
            entries.append({**rule, "metric": metric, "gender": gender, "place": place,
                            "all_qualified": key in CHECKIN_TITLES, "valid_days": TITLE_VALID_DAYS.get(key, 7),
                            "supported": metric in SUPPORTED_METRICS, "candidates": candidates})
        tip_rankings = {gender: sorted([
            {"user_id": str(user_id), "name": users[user_id].display_name, "score": score}
            for user_id, score in scores["tip_given"].items()
            if user_id in users and users[user_id].gender == gender and score > 0
        ], key=lambda candidate: (-candidate["score"], candidate["user_id"])) for gender in ("male", "female")}
        report = {"week_start": week.isoformat(), "config_version": revision.version,
                  "configuration": deepcopy(config), "entries": entries, "tip_rankings": tip_rankings}
        report["preview_digest"] = sha256(json.dumps(report, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return report

    def preview_honors(self, week, now):
        with self.transaction(), self._session() as session:
            self._honor_lock(session, now)
            existing = session.scalar(select(HonorPeriodRecord).where(HonorPeriodRecord.week_start == week))
            report = deepcopy(existing.snapshot) if existing else self._honor_report(session, week, now)
            return {**report, "settled": existing is not None,
                    "can_settle": existing is None and week < week_of(now)}

    def settle_honors(self, week, actor, now, preview_digest=None):
        with self.transaction(), self._session() as session:
            self._honor_lock(session, now)
            existing = session.scalar(select(HonorPeriodRecord).where(HonorPeriodRecord.week_start == week))
            if existing:
                self._honor_announce(session, existing, now)
                return self._honor_period_view(session, existing)
            if week >= week_of(now):
                raise ValueError("统计周尚未结束，不能结算")
            report = self._honor_report(session, week, now)
            if preview_digest is not None and preview_digest != report["preview_digest"]:
                raise HonorConflict("统计数据或规则已变动，请重新预览再确认")
            period = HonorPeriodRecord(week_start=week, config_version=report["config_version"],
                                       snapshot=report, settled_at=now, revision=1)
            session.add(period)
            session.flush()
            rankings = {}
            for gender in ("male", "female"):
                candidates = report["tip_rankings"][gender]
                ranking = []
                for score in dict.fromkeys(candidate["score"] for candidate in candidates):
                    tied = [candidate for candidate in candidates if candidate["score"] == score]
                    while tied:
                        selected = choice(tied)
                        ranking.append(selected)
                        tied.remove(selected)
                rankings[("tip_given", gender)] = ranking
            for entry in report["entries"]:
                candidates = [candidate for candidate in entry["candidates"] if candidate["eligible"]]
                if entry["all_qualified"]:
                    self._honor_add_awards(session, period, entry, candidates, week)
                    continue
                ranking_key = (entry["metric"], entry["gender"])
                if ranking_key not in rankings:
                    ranking = []
                    for score in dict.fromkeys(candidate["score"] for candidate in candidates):
                        tied = [candidate for candidate in candidates if candidate["score"] == score]
                        while tied:
                            selected = choice(tied)
                            ranking.append(selected)
                            tied.remove(selected)
                    rankings[ranking_key] = ranking
                ranking = rankings[ranking_key]
                winner = ranking[entry["place"] - 1] if len(ranking) >= entry["place"] else None
                if winner and winner["user_id"] not in {candidate["user_id"] for candidate in candidates}:
                    winner = None
                self._honor_add_awards(session, period, entry, [winner] if winner else [], week)
            self._honor_audit(session, "honor_settlement", actor,
                              {"period_id": str(period.id), "week_start": week.isoformat(), "config_version": period.config_version}, now)
            session.flush()
            self._honor_announce(session, period, now)
            return self._honor_period_view(session, period)

    def backfill_missing_honor_periods(self, actor, now):
        """结算游标至当前周之间真正缺失的已结束周期；已结算周期保持原快照。"""
        settled_weeks = []
        with self.transaction(), self._session() as session:
            state = self._honor_lock(session, now)
            current_week = week_of(now)
            while state.next_week < current_week:
                week = state.next_week
                existing = session.scalar(
                    select(HonorPeriodRecord).where(
                        HonorPeriodRecord.week_start == week
                    )
                )
                if existing is None:
                    self.settle_honors(week, actor, now)
                    settled_weeks.append(week.isoformat())
                state.next_week += timedelta(days=7)
            return {
                "count": len(settled_weeks),
                "settled_weeks": settled_weeks,
                "next_week": state.next_week.isoformat(),
            }

    @staticmethod
    def _honor_add_awards(session, period, entry, winners, week):
        valid_from = midnight(week + timedelta(days=7))
        for winner in winners or [None]:
            session.add(HonorAwardRecord(
                period_id=period.id, title_key=entry["key"], title_name=entry["name"],
                user_id=UUID(winner["user_id"]) if winner else None,
                winner_name=winner["name"] if winner else None, score=winner["score"] if winner else None,
                valid_from=valid_from, expires_at=valid_from + timedelta(days=entry["valid_days"]),
                sort_order=entry["sort_order"], public_score=entry["public_score"],
            ))

    @staticmethod
    def _honor_award_view(award, administrative=False):
        return {"id": str(award.id), "key": award.title_key, "name": award.title_name,
                "user_id": str(award.user_id) if award.user_id else None, "winner_name": award.winner_name,
                "score": award.score if administrative or award.public_score else None,
                "valid_from": award.valid_from.isoformat(), "expires_at": award.expires_at.isoformat()}

    def _honor_period_view(self, session, period):
        awards = session.scalars(select(HonorAwardRecord).where(HonorAwardRecord.period_id == period.id).order_by(
            HonorAwardRecord.sort_order, HonorAwardRecord.title_key,
        )).all()
        return {"id": str(period.id), "week_start": period.week_start.isoformat(),
                "config_version": period.config_version, "revision": period.revision,
                "settled_at": period.settled_at.isoformat(), "announced_at": period.announced_at.isoformat() if period.announced_at else None,
                "scheduled_announced_at": period.scheduled_announced_at.isoformat() if period.scheduled_announced_at else None,
                "awards": [self._honor_award_view(award, True) for award in awards]}

    def _honor_announce(self, session, period, now, scheduled=False):
        config = period.snapshot["configuration"]
        announced = period.scheduled_announced_at if scheduled else period.announced_at
        if announced or not config["announce"] or not config["enabled"]:
            return
        if week_of(now) != period.week_start + timedelta(days=7):
            return
        if scheduled:
            announcement_time = time.fromisoformat(config.get("announcement_time", "09:00"))
            due = datetime.combine(period.week_start + timedelta(days=7), announcement_time, BEIJING)
            if now < due:
                return
        group = session.get(GroupChatRecord, UUID(config["announcement_group_id"]))
        if group is None or group.deleted_at or not group.listening_enabled or not group.announcements_enabled or not group.chatroom_id:
            return
        awards = self._honor_period_view(session, period)["awards"]
        lines = [f"【每周荣誉榜】{period.week_start:%Y-%m-%d} — {period.week_start + timedelta(days=6):%Y-%m-%d}"]
        if scheduled:
            lines[0] += "（周一定时公告）"
        lines.extend(honor_award_lines(awards))
        if len(lines) == 1:
            lines.append("本期暂无合格获奖者。")
        lines.append("发送 /我的称号 查看，/佩戴称号 序号 选择佩戴。")
        self.enqueue_system_outbound("\n".join(lines), group_chat_id=group.id, destination_chatroom_id=group.chatroom_id)
        if scheduled:
            period.scheduled_announced_at = now
        else:
            period.announced_at = now

    def run_honor_jobs(self, now):
        with self.transaction(), self._session() as session:
            state = self._honor_lock(session, now)
            self._honor_clear_invalid_wear(session, now, notify=True)
            for offset in range(4):
                if state.next_week >= week_of(now):
                    break
                self.settle_honors(state.next_week, "scheduler", now)
                state.next_week += timedelta(days=7)
            current = session.scalar(select(HonorPeriodRecord).where(
                HonorPeriodRecord.week_start == week_of(now) - timedelta(days=7),
            ))
            if current:
                self._honor_announce(session, current, now)
                self._honor_announce(session, current, now, scheduled=True)

    def _honor_clear_invalid_wear(self, session, now, notify=False):
        for wear, award, user in session.execute(select(HonorWearRecord, HonorAwardRecord, UserRecord).join(
            HonorAwardRecord, HonorAwardRecord.id == HonorWearRecord.award_id,
        ).join(UserRecord, UserRecord.id == HonorWearRecord.user_id)):
            if award.user_id == wear.user_id and award.valid_from <= now < award.expires_at:
                continue
            if notify:
                room = self.direct_chat_destination(user.platform_id)
                if room:
                    self.enqueue_system_outbound(f"你的荣誉称号「{award.title_name}」已失效，已取消佩戴。发送 /我的称号 查看可用称号。",
                                                 destination_chatroom_id=room, delivery_kind="direct")
            session.delete(wear)
        session.flush()

    def get_equipped_honor(self, platform_id, now):
        with self._session() as session:
            return session.scalar(select(HonorAwardRecord.title_name).join(
                HonorWearRecord, HonorWearRecord.award_id == HonorAwardRecord.id,
            ).join(UserRecord, UserRecord.id == HonorWearRecord.user_id).where(
                UserRecord.platform_id == platform_id, HonorAwardRecord.user_id == UserRecord.id,
                HonorAwardRecord.valid_from <= now, HonorAwardRecord.expires_at > now,
            ))

    def my_honors(self, platform_id, now):
        with self._session() as session:
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id))
            if user is None:
                return None
            available = session.scalars(select(HonorAwardRecord).where(
                HonorAwardRecord.user_id == user.id, HonorAwardRecord.valid_from <= now,
                HonorAwardRecord.expires_at > now,
            ).order_by(HonorAwardRecord.sort_order, HonorAwardRecord.title_key,
                       HonorAwardRecord.valid_from.desc(), HonorAwardRecord.id)).all()
            latest = {}
            for award in available:
                latest.setdefault(award.title_key, award)
            awards = list(latest.values())
            counts = dict(session.execute(select(HonorAwardRecord.title_key, func.count()).where(
                HonorAwardRecord.user_id == user.id,
            ).group_by(HonorAwardRecord.title_key)).all())
            return {"user_id": str(user.id), "name": user.display_name, "equipped": self.get_equipped_honor(platform_id, now),
                    "items": [{**self._honor_award_view(award), "number": number,
                               "total_wins": counts[award.title_key]} for number, award in enumerate(awards, 1)],
                    "history_counts": counts}

    def wear_honor(self, platform_id, number, now):
        with self.transaction(), self._session() as session:
            self._honor_lock(session, now)
            personal = self.my_honors(platform_id, now)
            if personal is None:
                raise LookupError("请先用 /入职 名字 加入摸鱼公司。")
            user = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id))
            if type(number) is not int or not 0 <= number <= len(personal["items"]):
                raise ValueError("称号序号无效或称号已过期，请先发送 /我的称号 查看。")
            wear = session.get(HonorWearRecord, user.id)
            before = personal["equipped"]
            if number == 0:
                if wear:
                    session.delete(wear)
                name = None
            else:
                award = personal["items"][number - 1]
                if wear:
                    wear.award_id = UUID(award["id"])
                else:
                    session.add(HonorWearRecord(user_id=user.id, award_id=UUID(award["id"])))
                name = award["name"]
            self._honor_audit(session, "honor_wear", platform_id, {"before": before, "after": name}, now)
            return name

    def honor_board(self, now):
        with self._session() as session:
            period = session.scalar(select(HonorPeriodRecord).where(
                HonorPeriodRecord.week_start == week_of(now) - timedelta(days=7),
            ))
            if period is None or not period.snapshot["configuration"]["enabled"]:
                return {"week_start": None, "items": []}
            supported = {entry["key"] for entry in period.snapshot["entries"] if entry["enabled"] and entry["supported"]}
            return {"week_start": period.week_start.isoformat(), "items": [self._honor_award_view(award) for award in session.scalars(
                select(HonorAwardRecord).where(HonorAwardRecord.period_id == period.id).order_by(
                    HonorAwardRecord.sort_order, HonorAwardRecord.title_key,
                )) if award.title_key in supported]}

    def honor_history(self, now, user_id=None, title_key=None, week=None, page=1, page_size=20):
        if not 1 <= page or not 1 <= page_size <= 100:
            raise ValueError("分页参数无效")
        with self._session() as session:
            filters = [HonorAwardRecord.user_id.is_not(None)]
            if user_id:
                filters.append(HonorAwardRecord.user_id == user_id)
            if title_key:
                filters.append(HonorAwardRecord.title_key == title_key)
            if week:
                filters.append(HonorPeriodRecord.week_start == week)
            query = select(HonorAwardRecord, HonorPeriodRecord.week_start).join(HonorPeriodRecord).where(*filters)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            items = [{**self._honor_award_view(award, True), "week_start": period_week.isoformat(),
                      "active": award.valid_from <= now < award.expires_at}
                     for award, period_week in session.execute(query.order_by(
                         HonorPeriodRecord.week_start.desc(), HonorAwardRecord.sort_order, HonorAwardRecord.title_key,
                     ).offset((page - 1) * page_size).limit(page_size))]
            return {"items": items, "total": total, "page": page, "page_size": page_size,
                    "pages": (total + page_size - 1) // page_size}

    def honor_periods(self, page=1, page_size=20):
        if not 1 <= page or not 1 <= page_size <= 100:
            raise ValueError("分页参数无效")
        with self._session() as session:
            total = session.scalar(select(func.count()).select_from(HonorPeriodRecord))
            records = session.scalars(select(HonorPeriodRecord).order_by(HonorPeriodRecord.week_start.desc()).offset(
                (page - 1) * page_size,
            ).limit(page_size))
            return {"items": [self._honor_period_view(session, period) for period in records],
                    "total": total, "page": page, "page_size": page_size,
                    "pages": (total + page_size - 1) // page_size}

    def correct_honor(self, award_id, winner_id, reason, expected_revision, actor, now):
        if not reason.strip():
            raise ValueError("纠错必须填写原因")
        with self.transaction(), self._session() as session:
            self._honor_lock(session, now)
            award = session.get(HonorAwardRecord, award_id)
            if award is None:
                raise LookupError("获奖记录不存在")
            period = session.get(HonorPeriodRecord, award.period_id)
            if period.revision != expected_revision:
                raise HonorConflict("结算结果已被修改，请刷新后重试")
            entry = next(entry for entry in period.snapshot["entries"] if entry["key"] == award.title_key)
            candidate = next((candidate for candidate in entry["candidates"]
                              if candidate["eligible"] and candidate["user_id"] == str(winner_id)), None)
            if winner_id is not None and candidate is None:
                raise ValueError("只能选该周期满足资格的候选人，或置为空缺")
            if winner_id is not None and session.scalar(select(HonorAwardRecord.id).where(
                HonorAwardRecord.period_id == period.id, HonorAwardRecord.title_key == award.title_key,
                HonorAwardRecord.user_id == winner_id, HonorAwardRecord.id != award.id,
            ).limit(1)):
                raise ValueError("该员工已获得本周期此称号，不能重复授予")
            if winner_id is not None and entry["metric"] == "tip_given":
                other = session.scalar(select(HonorAwardRecord).where(
                    HonorAwardRecord.period_id == period.id, HonorAwardRecord.id != award.id,
                    HonorAwardRecord.title_key.in_([spec[0] for spec in TITLE_SPECS if spec[2:4] == ("tip_given", entry["gender"])]),
                    HonorAwardRecord.user_id == winner_id,
                ))
                if other:
                    raise ValueError("榜一和榜二不能授予同一人，请先将冲突称号置为空缺")
            before = self._honor_award_view(award, True)
            award.user_id = winner_id
            award.winner_name = candidate["name"] if candidate else None
            award.score = candidate["score"] if candidate else None
            period.revision += 1
            self._honor_audit(session, "honor_correction", actor,
                              {"reason": reason.strip(), "before": before, "after": self._honor_award_view(award, True)}, now)
            session.flush()
            self._honor_clear_invalid_wear(session, now, notify=True)
            return self._honor_period_view(session, period)
