"""Independent players and serialized room transactions for Mistrealm."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from secrets import SystemRandom, randbelow
from uuid import UUID, uuid4

from sqlalchemy import delete, select, func
from sqlalchemy.exc import IntegrityError

from . import mistrealm_state as legacy
from . import mistrealm_classic_state as classic
from . import mistrealm_v3_state as v3
from .mistrealm_v3_original import mistrealm_v3_state as v3_original
from .mistrealm_v3_r1 import mistrealm_v3_state as v3_r1
from .mistrealm_v3_cards import validate_deck as validate_v3
from . import mistrealm_story as story
from . import mistrealm_bots as bots
from .mistrealm_balance import record_match
from .mistrealm_classic_cards import validate_deck
from .schema import (
    MistrealmPlayerRecord as Player, MistrealmRoomRecord as Room,
    MistrealmSeatRecord as Seat, MistrealmRequestRecord as Receipt, MistrealmDeckRecord as Deck,
    MistrealmStoryProgressRecord as StoryProgress,
    MistrealmChannelMessageRecord as ChannelMessage,
)


class MistrealmError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def ms(now):
    if now.tzinfo is None:
        raise ValueError("时间必须包含时区")
    return int(now.timestamp()*1000)


def _engine(state):
    if state.get('rules_version')==3 and 'phase' in state and not state.get('balance_revision'):
        return v3_original
    if state.get('rules_version')==3 and state.get('balance_revision')==1:
        return v3_r1
    return {1: legacy, 2: classic, 3: v3}[state.get('rules_version', 1)]


from .mistrealm_profile import MistrealmProfileMixin, settings
from .mistrealm_social import MistrealmSocialMixin
from .mistrealm_ranked import MistrealmRankedMixin, search_radius
from .mistrealm_expedition_repository import MistrealmExpeditionMixin


class MistrealmRepositoryMixin(MistrealmSocialMixin, MistrealmRankedMixin, MistrealmProfileMixin, MistrealmExpeditionMixin):
    @staticmethod
    def _mr_player(session, uid):
        p = session.scalar(select(Player).where(Player.platform_uid == uid).with_for_update())
        if p is None:
            raise MistrealmError("请先登记玩家", 401)
        return p

    def mistrealm_register(self, uid, name, avatar, now):
        with self._session() as session:
            p = session.scalar(select(Player).where(Player.platform_uid == uid).with_for_update())
            if p is None:
                try:
                    with session.begin_nested():
                        p = Player(platform_uid=uid, name=name, avatar=avatar,
                                   created_at=now, updated_at=now, rate_limits={})
                        session.add(p)
                        session.flush()
                except IntegrityError:
                    p = self._mr_player(session, uid)
            p.name, p.avatar, p.updated_at = name, avatar, now
            return {"uid": uid, "name": name, "avatar": avatar}

    @staticmethod
    def _mr_room(session, room_id):
        room = session.scalar(select(Room).where(Room.id == room_id).with_for_update())
        if room is None:
            raise MistrealmError("房间不存在", 404)
        return room

    def _mr_sync(self, session, room, state):
        if state.get('rules_version')==3 and state['phase']=='playing' and state['round']==1:
            state.setdefault('balance_first',state['first'])
        room.state, room.phase = state, state["phase"]
        if state.get('rules_version')==3:record_match(session,room,datetime.fromtimestamp(state['server_time_ms']/1000,timezone.utc))
        deadline = state["deadline_ms"]
        room.deadline = datetime.fromtimestamp(deadline/1000, timezone.utc) if deadline is not None else None
        if state.get('ranked_match'):
            self._rank_settle(session, room, datetime.fromtimestamp(state['server_time_ms']/1000, timezone.utc))
        if state.get('rules_version')==3:
            self._mr_record_history(session, room, datetime.fromtimestamp(state["server_time_ms"]/1000, timezone.utc))
        if room.phase == "closed":
            room.active_code = None
            session.execute(delete(Seat).where(Seat.room_id == room.id))

    @staticmethod
    def _mr_story_progress_record(session, player, now):
        record = session.get(StoryProgress, player.id)
        if record is None:
            record = StoryProgress(player_id=player.id, completed_chapters=[], updated_at=now)
            session.add(record)
            session.flush()
        return record

    def _mr_story_finish(self, session, room, player, now):
        state = room.state
        if state.get("mode") != "story" or state["phase"] != "finished" or state["winner"] != 0:
            return
        progress = self._mr_story_progress_record(session, player, now)
        chapter = state["story"]["chapter"]
        if chapter not in progress.completed_chapters:
            progress.completed_chapters = sorted([*progress.completed_chapters, chapter])
            progress.updated_at = now

    def _mr_story_drive(self, session, room, player, now):
        if room.state.get("mode") not in ("story", "bot"):
            return
        state = story.drive(room.state, ms(now), SystemRandom())
        if state != room.state:
            self._mr_sync(session, room, state)
        self._mr_story_finish(session, room, player, now)

    def _mr_advance(self, session, room, now):
        state = _engine(room.state).advance(room.state, ms(now), SystemRandom())
        if state.get("mode") == "bot":
            state = story.drive(state, ms(now), SystemRandom())
        if state != room.state:
            self._mr_sync(session, room, state)

    def _mr_active(self, session, p, now):
        seat = session.scalar(select(Seat).where(Seat.player_id == p.id))
        if seat:
            room = self._mr_room(session, seat.room_id)
            self._mr_advance(session, room, now)
            return room if room.phase != "closed" else None
        return None

    def _mr_view(self, session, room, p):
        seat = session.scalar(select(Seat).where(Seat.room_id == room.id, Seat.player_id == p.id))
        if seat is None:
            if room.phase != "closed":
                raise MistrealmError("你不在这个房间", 403)
            seat_index = next(
                (
                    index
                    for index, player in enumerate(room.state["players"])
                    if player and player["uid"] == p.platform_uid
                ),
                None,
            )
            if seat_index is None:
                raise MistrealmError("你不在这个房间", 403)
        else:
            seat_index = seat.seat_index
        state = _engine(room.state).project(room.state, seat_index)
        # Seat table is authoritative for active membership.
        for entry in session.scalars(select(Seat).where(Seat.room_id == room.id)):
            profile = session.get(Player, entry.player_id)
            state["players"][entry.seat_index].update(name=profile.name, avatar=profile.avatar)
            honor = self._rank_honor(session, profile)
            if honor and state.get('rules_version') == 3:
                state["players"][entry.seat_index]['honor'] = honor
        if room.state.get("mode") == "story":
            state["mode"] = "story"
            state["story"] = deepcopy(room.state["story"])
            state["players"][1].update(
                name=room.state["story"]["enemy_name"], avatar=None
            )
        if room.state.get("mode") == "bot":
            state["mode"] = "bot"
            state["players"][1].update(**room.state["bot"], is_bot=True)
        if room.state.get('ranked_match'):
            state['mode'] = 'ranked'
            state['ranked'] = self._rank_room_view(session, room)
            for index, player in enumerate(state['players']):
                player['rank_tier'] = state['ranked']['tiers'][index]
                player['rank_rating'] = state['ranked']['ratings'][index]
            state['legal_moves'] = [m for m in state['legal_moves'] if m['action'] != 'rematch']
        return {"room_id": str(room.id), "code": room.active_code,
                "match_id": str(room.match_id) if room.match_id else None, "state": state}

    def mistrealm_me(self, uid, now):
        with self._session() as session:
            p = self._mr_player(session, uid)
            room = self._mr_active(session, p, now)
            has_played = session.scalar(select(select(Receipt.player_id).where(
                Receipt.player_id == p.id,
                Receipt.result["match_id"].as_string().is_not(None),
            ).exists())) or session.scalar(select(select(Room.id).where(
                Room.match_id.is_not(None),
                (Room.state["players"][0]["uid"].as_string() == uid)
                | (Room.state["players"][1]["uid"].as_string() == uid),
            ).exists()))
            return {"uid": uid, "name": p.name, "avatar": p.avatar,
                    "has_played": bool(has_played), "settings": settings(p),
                    "honor": self._rank_honor(session, p),
                    "room_id": str(room.id) if room else None,
                    "matchmaking": self._mr_queue_status(p, now)}

    def _mr_rate(self, uid, kind, limit, now):
        # Separate transaction: rejected attempts still count; shared by all workers.
        with self._session() as session:
            p = self._mr_player(session, uid)
            rates = dict(p.rate_limits)
            stamp = ms(now)
            attempts = [t for t in rates.get(kind, []) if t > stamp-60000]
            if len(attempts) >= limit:
                if kind in ('channel', 'channel_challenge', 'private_message'):
                    wait = (min(attempts) + 60000 - stamp + 999) // 1000
                    raise MistrealmError(f"操作过于频繁，请{wait}秒后重试", 429)
                raise MistrealmError("操作过于频繁，请稍后重试", 429)
            rates[kind] = [*attempts, stamp]
            p.rate_limits = rates

    @staticmethod
    def _mr_digest(value):
        return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    @staticmethod
    def _mr_replay(session, p, request_id, digest):
        old = session.get(Receipt, (p.id, request_id))
        if old:
            if old.digest != digest:
                raise MistrealmError("同一请求编号不能用于不同操作")
            return old.result
        return None

    @staticmethod
    def _mr_save(session, p, request_id, digest, result, room, now):
        session.add(Receipt(player_id=p.id, request_id=request_id, room_id=room.id,
                            digest=digest, result=result, created_at=now))
        return result

    def mistrealm_create(self, uid, request_id, now, deck_id=None, rules_version=2):
        self._mr_rate(uid, "create", 5, now)
        with self._session() as session:
            p = self._mr_player(session, uid)
            digest = self._mr_digest({"action": "create", "deck_id": deck_id, "rules_version": rules_version})
            old = self._mr_replay(session, p, request_id, digest)
            if old is not None:
                return old
            self._mr_clear_queue(p)
            room = self._mr_active(session, p, now)
            if room is None:
                room = self._mr_new_room(session, p, now, self._mr_deck_snapshot(session,p,deck_id,rules_version) if deck_id else None)
            result = self._mr_view(session, room, p)
            return self._mr_save(session, p, request_id, digest, result, room, now)

    def mistrealm_join(self, uid, code, request_id, now, deck_id=None, rules_version=2):
        self._mr_rate(uid, "join", 20, now)
        with self._session() as session:
            p = self._mr_player(session, uid)
            digest = self._mr_digest({"action": "join", "code": code, "deck_id": deck_id, "rules_version": rules_version})
            old = self._mr_replay(session, p, request_id, digest)
            if old is not None:
                return old
            self._mr_clear_queue(p)
            room = self._mr_active(session, p, now)
            if room is None:
                room = session.scalar(select(Room).where(Room.active_code == code).with_for_update())
                if room is None:
                    raise MistrealmError("房间码不存在或已失效", 404)
                self._mr_advance(session, room, now)
                if room.phase == "closed":
                    raise MistrealmError("房间码已失效", 404)
                if session.get(Seat, (room.id, 1)):
                    raise MistrealmError("房间已满")
                if room.state.get('rules_version',1) != (rules_version if deck_id else 1):
                    raise MistrealmError('房间规则版本不同，请使用对应入口')
                payload={'uid':uid}
                if deck_id: payload['deck']=self._mr_deck_snapshot(session,p,deck_id,rules_version)
                state = _engine(room.state).apply_action(room.state, 1, "join", payload, ms(now), SystemRandom())
                self._mr_sync(session, room, state)
                session.add(Seat(room_id=room.id, seat_index=1, player_id=p.id))
                session.flush()
            result = self._mr_view(session, room, p)
            return self._mr_save(session, p, request_id, digest, result, room, now)

    def mistrealm_view(self, room_id, uid, now):
        with self._session() as session:
            p = self._mr_player(session, uid)
            room = self._mr_room(session, room_id)
            # Authorize before advancing or emitting any room data.
            self._mr_view(session, room, p)
            self._mr_advance(session, room, now)
            self._mr_story_drive(session, room, p, now)
            if room.phase == "closed":
                return {"room_id": str(room.id), "code": None,
                        "match_id": str(room.match_id) if room.match_id else None,
                        "state": {"phase": "closed", "version": room.state["version"]}}
            result=self._mr_view(session, room, p)
            if room.state.get('rules_version') in (2,3): result['state']['server_time_ms']=ms(now)
            return result

    def mistrealm_action(self, room_id, uid, match_id, version, request_id, action, payload, now):
        self._mr_rate(uid, "action", 120, now)
        # Persist elapsed deadlines independently of a stale or invalid submitted action.
        with self._session() as session:
            p = self._mr_player(session, uid)
            digest = self._mr_digest(dict(room=room_id, match=match_id, version=version, action=action, payload=payload))
            old = self._mr_replay(session, p, request_id, digest)
            if old is not None:
                return old
            room = self._mr_room(session, room_id)
            self._mr_view(session, room, p)
            self._mr_advance(session, room, now)
        with self._session() as session:
            p = self._mr_player(session, uid)
            digest = self._mr_digest(dict(room=room_id, match=match_id, version=version, action=action, payload=payload))
            old = self._mr_replay(session, p, request_id, digest)
            if old is not None:
                return old
            room = self._mr_room(session, room_id)
            view = self._mr_view(session, room, p)
            self._mr_advance(session, room, now)
            if room.match_id != match_id or room.state["version"] != version:
                raise MistrealmError("房间状态已更新，请刷新")
            if room.state.get('ranked_match') and action == 'rematch':
                raise MistrealmError('排位结算后请返回大厅重新匹配')
            seat = view["state"]["seat"]
            if room.state.get('rules_version') in (2,3) and action=='select_deck':
                payload={'deck':self._mr_deck_snapshot(session,p,UUID(payload['deck_id']),room.state['rules_version'])}
            state = _engine(room.state).apply_action(room.state, seat, action, payload, ms(now), SystemRandom())
            if room.state.get("mode") == "story" and action == "rematch":
                raise MistrealmError("剧情关卡请从章节页重新开始")
            if room.state.get("mode") == "bot" and action == "rematch":
                state = bots.rematch(state, ms(now), SystemRandom())
                room.match_id = uuid4()
            if action == "start" or (room.state.get("rules_version") in (2,3) and room.state["phase"]=="waiting" and state["phase"]!="waiting"):
                room.match_id = uuid4()
            elif state["phase"] == "waiting":
                room.match_id = None
            self._mr_sync(session, room, state)
            self._mr_story_drive(session, room, p, now)
            if action == "leave" and state["phase"] == "waiting":
                session.execute(delete(Seat).where(Seat.room_id == room.id, Seat.player_id == p.id))
            if state["phase"] == "closed" or (action == "leave" and state["phase"] == "waiting"):
                result = {"room_id": str(room.id), "code": None, "match_id": None,
                          "state": {"phase": "closed", "version": state["version"]}}
            else:
                result = self._mr_view(session, room, p)
            return self._mr_save(session, p, request_id, digest, result, room, now)

    def mistrealm_story_progress(self, uid, now):
        with self._session() as session:
            player = self._mr_player(session, uid)
            progress = self._mr_story_progress_record(session, player, now)
            return story.public_chapters(progress.completed_chapters)

    def mistrealm_story_start(self, uid, chapter, deck_id, now, rules_version=2):
        self._mr_rate(uid, "story", 10, now)
        with self._session() as session:
            player = self._mr_player(session, uid)
            progress = self._mr_story_progress_record(session, player, now)
            available = story.public_chapters(progress.completed_chapters)
            if chapter > available["unlocked"]:
                raise MistrealmError("请先完成前一章", 403)
            current = self._mr_active(session, player, now)
            if current is not None:
                if current.state.get("mode") == "story":
                    return self._mr_view(session, current, player)
                raise MistrealmError("请先结束当前玩家对局")
            self._mr_clear_queue(player)
            state = story.new_story_state(
                uid,
                self._mr_deck_snapshot(session, player, deck_id, rules_version),
                chapter,
                ms(now),
                SystemRandom(),
            )
            room = Room(
                host_id=player.id,
                active_code=None,
                phase=state["phase"],
                match_id=uuid4(),
                state=state,
                created_at=now,
                deadline=None,
            )
            session.add(room)
            session.flush()
            session.add(Seat(room_id=room.id, seat_index=0, player_id=player.id))
            self._mr_sync(session, room, state)
            session.flush()
            self._mr_story_finish(session, room, player, now)
            return self._mr_view(session, room, player)

    @staticmethod
    def _mr_channel_item(session, message, now):
        player = session.get(Player, message.player_id)
        item = {
            "id": str(message.id),
            "kind": message.kind,
            "text": message.text,
            "created_at": message.created_at.isoformat(),
            "player": {"uid": player.platform_uid, "name": player.name, "avatar": player.avatar,
                       "online": player.online_seen_at is not None and player.online_seen_at > now-timedelta(seconds=60)},
        }
        if message.kind == "challenge":
            room = session.get(Room, message.room_id)
            waiting = bool(
                room
                and room.phase == "waiting"
                and room.active_code
                and room.state.get("mode") != "story"
                and room.state["players"][1] is None
            )
            item["challenge"] = {
                "room_id": str(message.room_id),
                "status": "waiting" if waiting else "ended",
                "code": room.active_code if waiting else None,
            }
        return item

    def mistrealm_channel_messages(self, uid, limit, now):
        with self._session() as session:
            self._mr_player(session, uid)
            rows = list(
                session.scalars(
                    select(ChannelMessage)
                    .where(ChannelMessage.deleted_at.is_(None))
                    .order_by(ChannelMessage.created_at.desc(), ChannelMessage.id.desc())
                    .limit(limit)
                )
            )
            return {"items": [self._mr_channel_item(session, row, now) for row in reversed(rows)]}

    def _mr_channel_guard(self, player, now):
        if player.channel_muted_until and player.channel_muted_until > now:
            raise MistrealmError(
                "你已被频道禁言至" + player.channel_muted_until.isoformat(), 403
            )

    def mistrealm_channel_post(self, uid, text, now):
        self._mr_rate(uid, "channel", 15, now)
        content = text.strip()
        if not content or len(content) > 200:
            raise MistrealmError("消息需要1至200字", 422)
        with self._session() as session:
            player = self._mr_player(session, uid)
            self._mr_channel_guard(player, now)
            message = ChannelMessage(
                player_id=player.id, kind="text", text=content, created_at=now
            )
            session.add(message)
            session.flush()
            return self._mr_channel_item(session, message, now)

    def mistrealm_channel_challenge(self, uid, room_id, now):
        self._mr_rate(uid, "channel_challenge", 6, now)
        with self._session() as session:
            player = self._mr_player(session, uid)
            self._mr_channel_guard(player, now)
            room = self._mr_room(session, room_id)
            if (
                room.host_id != player.id
                or room.phase != "waiting"
                or room.active_code is None
                or room.state.get("mode") == "story"
                or room.state["players"][1] is not None
            ):
                raise MistrealmError("当前房间不能发布约战")
            old = session.scalar(
                select(ChannelMessage).where(
                    ChannelMessage.room_id == room.id,
                    ChannelMessage.kind == "challenge",
                    ChannelMessage.deleted_at.is_(None),
                )
            )
            if old is not None:
                return self._mr_channel_item(session, old, now)
            message = ChannelMessage(
                player_id=player.id,
                kind="challenge",
                room_id=room.id,
                created_at=now,
            )
            session.add(message)
            session.flush()
            return self._mr_channel_item(session, message, now)

    def advance_mistrealm_deadlines(self, now):
        with self._session() as session:
            rooms = session.scalars(select(Room).where(Room.deadline <= now).with_for_update(skip_locked=True))
            for room in rooms:
                self._mr_advance(session, room, now)
        with self._session() as session:
            self._rank_finalize(session, now, skip_locked=True)


    @staticmethod
    def _mr_clear_queue(p):
        p.queue_ticket = p.queued_at = p.queue_expires_at = None
        p.queue_snapshot = None
        p.queue_rules_version = 1
        p.queue_mode = 'casual'

    @staticmethod
    def _mr_queue_status(p, now):
        if not p.queue_ticket or p.queue_expires_at <= now:
            return {"status": "idle"}
        result = {"status": "waiting", "ticket": str(p.queue_ticket),
                "queued_at_ms": ms(p.queued_at), "expires_at_ms": ms(p.queue_expires_at),
                "elapsed_ms": max(0, ms(now)-ms(p.queued_at))}
        result['mode'] = p.queue_mode
        if p.queue_mode == 'ranked':
            result['ranked'] = dict(p.queue_snapshot['ranked'],radius=search_radius((now-p.queued_at).total_seconds()))
        if p.queue_rules_version in (2,3):
            snapshot = p.queue_snapshot
            result.update(rules_version=p.queue_rules_version, deck=dict(id=snapshot['deck_id'],name=snapshot.get('name','已锁定军团'),faction=snapshot['faction'],leader=snapshot['leader']))
        return result

    def _mr_new_room(self, session, host, now, deck_snapshot=None):
        for _ in range(100):
            try:
                with session.begin_nested():
                    state = _engine(dict(rules_version=deck_snapshot.get('rules_version',2))).new_state(host.platform_uid, deck_snapshot, ms(now)) if deck_snapshot else legacy.new_state(host.platform_uid, ms(now))
                    room = Room(host_id=host.id, active_code=f"{randbelow(1000000):06d}",
                                phase="waiting", state=state, created_at=now,
                                deadline=now+timedelta(minutes=30))
                    session.add(room)
                    session.flush()
                break
            except IntegrityError:
                continue
        else:
            raise MistrealmError("暂时无法生成房间码")
        session.add(Seat(room_id=room.id, seat_index=0, player_id=host.id))
        session.flush()
        return room

    def mistrealm_matchmaking(self, uid, operation, ticket, now, rules_version=1, deck_id=None, mode='casual'):
        if operation not in ("start", "heartbeat", "cancel"):
            raise MistrealmError("匹配操作不正确", 422)
        if mode not in ('casual','ranked') or (mode=='ranked' and rules_version!=3):
            raise MistrealmError('匹配模式不正确',422)
        if operation == "start":
            self._mr_rate(uid, "matchmaking", 10, now)
        with self._session() as session:
            p = self._mr_player(session, uid)
            room = self._mr_active(session, p, now)
            if room:
                self._mr_clear_queue(p)
                return {"status": "matched", "room": self._mr_view(session, room, p)}
            current = self._mr_queue_status(p, now)
            if current['status']=='waiting' and (p.queue_rules_version!=rules_version or p.queue_mode!=mode):
                if operation=='start': raise MistrealmError('请先取消另一模式的匹配')
                return {'status':'idle'}
            if operation=='start' and rules_version in (2,3) and current['status']=='waiting' and str(deck_id)!=p.queue_snapshot['deck_id']:
                raise MistrealmError('请先取消匹配再更换牌组')
            if operation == "cancel":
                if str(p.queue_ticket) == str(ticket):
                    self._mr_clear_queue(p)
                return self._mr_queue_status(p, now)
            if operation == "heartbeat":
                if current["status"] != "waiting" or str(p.queue_ticket) != str(ticket):
                    return {"status": "idle"}
            season = self._rank_current(session, now) if mode=='ranked' else None
            if season and current['status']=='waiting' and p.queue_snapshot['ranked']['season']!=season.id:
                self._mr_clear_queue(p)
                return {'status':'idle','message':'新赛季已开启，请重新匹配'}
            if operation=='start' and current["status"] != "waiting":
                p.queue_ticket, p.queued_at = uuid4(), now
                p.queue_rules_version = rules_version
                p.queue_snapshot = self._mr_deck_snapshot(session,p,deck_id,rules_version) if rules_version in (2,3) else None
                p.queue_mode=mode
                if season:
                    entry=self._rank_entry(session,p,season)
                    p.queue_snapshot=dict(p.queue_snapshot,ranked=dict(season=season.id,rating=entry.rating))
            p.queue_expires_at = now+timedelta(seconds=20)
            session.flush()
            # Lock the caller first; SKIP LOCKED avoids reciprocal candidate deadlocks.
            # Custom-room entry uses the same player lock and clears its queue lease.
            candidates = select(Player).where(
                    Player.id != p.id, Player.queue_ticket.is_not(None),
                    Player.queue_expires_at > now, Player.queue_rules_version == rules_version, Player.queue_mode == mode,
                    ~select(Seat.player_id).where(Seat.player_id == Player.id).exists(),
                )
            if season:
                score=p.queue_snapshot['ranked']['rating']
                gap=func.abs(Player.queue_snapshot['ranked']['rating'].as_integer()-score)
                candidates=candidates.where(Player.queue_snapshot['ranked']['season'].as_integer()==season.id,
                    gap<=search_radius((now-p.queued_at).total_seconds())).order_by(gap,Player.queued_at,Player.id)
                candidate=next((other for other in session.scalars(candidates.with_for_update(skip_locked=True).limit(20))
                    if abs(other.queue_snapshot['ranked']['rating']-score)<=search_radius((now-other.queued_at).total_seconds())),None)
            else:
                candidate=session.scalar(candidates.order_by(Player.queued_at,Player.id).with_for_update(skip_locked=True).limit(1))
            if candidate is None:
                if rules_version == 3 and ms(now)-ms(p.queued_at) >= bots.MATCH_WAIT_MS:
                    state = bots.new_match(uid, deepcopy(p.queue_snapshot), ms(now), SystemRandom())
                    if season:state['ranked_match']=True
                    room = Room(host_id=p.id, active_code=None, phase=state['phase'], state=state,
                                match_id=uuid4(), created_at=now, deadline=None)
                    session.add(room)
                    session.flush()
                    session.add(Seat(room_id=room.id, seat_index=0, player_id=p.id))
                    if season:self._rank_begin(session,room,p,None,now)
                    self._mr_clear_queue(p)
                    self._mr_sync(session, room, state)
                    session.flush()
                    return {"status": "matched", "room": self._mr_view(session, room, p)}
                return self._mr_queue_status(p, now)
            room = self._mr_new_room(session, candidate, now, candidate.queue_snapshot if rules_version in (2,3) else None)
            join_payload={'uid':uid}
            if rules_version in (2,3): join_payload['deck']=deepcopy(p.queue_snapshot)
            state = _engine(room.state).apply_action(room.state, 1, "join", join_payload, ms(now), SystemRandom())
            if rules_version in (2,3):
                state=_engine(state).apply_action(state,0,'lock',{},ms(now),SystemRandom())
                state=_engine(state).apply_action(state,1,'lock',{},ms(now),SystemRandom())
                room.match_id=uuid4()
            if season:
                room.active_code=None
                state['mode']='ranked';state['ranked_match']=True
                self._rank_begin(session,room,candidate,p,now)
            self._mr_sync(session, room, state)
            session.add(Seat(room_id=room.id, seat_index=1, player_id=p.id))
            self._mr_clear_queue(candidate)
            self._mr_clear_queue(p)
            session.flush()
            return {"status": "matched", "room": self._mr_view(session, room, p)}

    @staticmethod
    def _mr_deck(session, player, deck_id):
        deck=session.scalar(select(Deck).where(Deck.id==deck_id,Deck.player_id==player.id).with_for_update())
        if deck is None: raise MistrealmError('牌组不存在',404)
        return deck

    def _mr_deck_snapshot(self, session, player, deck_id, rules_version=2):
        deck=self._mr_deck(session,player,deck_id)
        if deck.rules_version!=rules_version: raise MistrealmError('牌组规则版本不同，请建立对应版本的牌组')
        validator=validate_v3 if rules_version==3 else validate_deck
        return dict(deck_id=str(deck.id),name=deck.name,rules_version=rules_version,**{k:v for k,v in validator(deck.faction,deck.leader,deck.counts).items() if k!='rules_version'})

    @staticmethod
    def _mr_deck_view(deck):
        return dict(id=str(deck.id),name=deck.name,faction=deck.faction,leader=deck.leader,counts=deepcopy(deck.counts),rules_version=deck.rules_version)

    def mistrealm_decks(self, uid, now, rules_version=2):
        with self._session() as session:
            player=self._mr_player(session,uid)
            decks=list(session.scalars(select(Deck).where(Deck.player_id==player.id,Deck.rules_version==rules_version).order_by(Deck.updated_at,Deck.id)))
            result={'decks':[self._mr_deck_view(d) for d in decks]}
            if rules_version==3:
                selected=next((d for d in decks if d.id==player.selected_v3_deck_id),decks[-1] if decks else None)
                result['selected_deck_id']=str(selected.id) if selected else None
            return result

    def mistrealm_select_v3_deck(self, uid, deck_id, now):
        with self._session() as session:
            player=self._mr_player(session,uid)
            deck=self._mr_deck(session,player,deck_id)
            if deck.rules_version!=3: raise MistrealmError('请选择第三版牌组')
            player.selected_v3_deck_id=deck.id
            return {'selected_deck_id':str(deck.id)}

    def mistrealm_save_deck(self, uid, deck_id, name, faction, leader, counts, now, rules_version=2):
        self._mr_rate(uid,'deck',60,now)
        snapshot=(validate_v3 if rules_version==3 else validate_deck)(faction,leader,counts)
        if not isinstance(name,str) or not name.strip() or len(name)>40: raise ValueError('牌组名称需要1至40字')
        with self._session() as session:
            player=self._mr_player(session,uid)
            deck=self._mr_deck(session,player,deck_id) if deck_id else Deck(player_id=player.id)
            if deck_id and deck.rules_version!=rules_version: raise MistrealmError('不能覆盖其他版本的牌组')
            deck.rules_version=rules_version
            deck.name=name.strip();deck.updated_at=now
            deck.faction,deck.leader,deck.counts=snapshot['faction'],snapshot['leader'],snapshot['counts']
            session.add(deck);session.flush()
            if rules_version==3: player.selected_v3_deck_id=deck.id
            return self._mr_deck_view(deck)

    def mistrealm_delete_deck(self, uid, deck_id, now):
        with self._session() as session:
            player=self._mr_player(session,uid)
            deck=self._mr_deck(session,player,deck_id)
            if self._mr_queue_status(player,now)['status']=='waiting' and player.queue_snapshot and player.queue_snapshot.get('deck_id')==str(deck_id):
                raise MistrealmError('匹配中的牌组不能删除')
            room=self._mr_active(session,player,now)
            if room and room.state.get('rules_version') in (2,3):
                for p in room.state['players']:
                    if p and p['uid']==uid and p['locked'] and p['selection'].get('deck_id')==str(deck_id):
                        raise MistrealmError('对局中的牌组不能删除')
            if player.selected_v3_deck_id==deck.id: player.selected_v3_deck_id=None
            session.delete(deck)
            return {'deleted':True}
