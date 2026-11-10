"""Public UID-trust HTTP/SSE interface; independent from employee accounts."""
import asyncio
import json
import re
from time import monotonic
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictBool, field_validator

from .mistrealm_repository import MistrealmError
from .mistrealm_state import FIELDS
from .mistrealm_sync import history_cursor, history_delta, channel_delta


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Profile(Body):
    name: str = Field(min_length=1, max_length=40)
    avatar: str | None = Field(default=None, max_length=2048)

    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        if not value.strip():
            raise ValueError("请输入昵称")
        return value.strip()

    @field_validator("avatar")
    @classmethod
    def avatar_valid(cls, value):
        from urllib.parse import urlsplit
        if value and (urlsplit(value).scheme != "https" or not urlsplit(value).hostname):
            raise ValueError("头像必须是HTTPS地址")
        return value or None


class RequestBody(Body):
    request_id: UUID


class MatchTicket(Body):
    ticket: UUID


class Join(RequestBody):
    code: str = Field(pattern=r"^[0-9]{6}$")


class Action(RequestBody):
    match_id: UUID | None = None
    version: StrictInt = Field(ge=0)
    action: Literal["select_faction", "ready", "unready", "start", "mulligan",
                    "play", "leader", "pass", "concede", "leave", "rematch"]
    payload: dict = Field(default_factory=dict)


class ClassicDeck(Body):
    id: UUID | None = None
    name: str = Field(min_length=1,max_length=40)
    faction: str
    leader: str
    counts: dict[str, StrictInt]


class ClassicCreate(RequestBody):
    deck_id: UUID


class ClassicJoin(ClassicCreate):
    code: str = Field(pattern=r"^[0-9]{6}$")


class ClassicQueue(Body):
    deck_id: UUID


class StoryStart(ClassicQueue):
    chapter: StrictInt = Field(ge=1, le=5)


class ExpeditionAction(Body):
    run_id: UUID
    version: StrictInt = Field(ge=0)
    action: Literal['choose','battle','buy','sell','upgrade','skip','leave','restart']
    payload: dict = Field(default_factory=dict)


class RankedHonor(Body):
    season_id: StrictInt | None = Field(default=None, ge=1)


class Preferences(Body):
    challenges: Literal['all','friends','off'] | None = None
    friend_requests: StrictBool | None = None
    spectate: StrictBool | None = None
    animations: StrictBool | None = None
    sound: StrictBool | None = None


class ChannelText(Body):
    text: str = Field(min_length=1, max_length=200)


class ChannelChallenge(Body):
    room_id: UUID


class SocialTarget(Body):
    uid: str = Field(min_length=1,max_length=255)


class PrivateText(SocialTarget):
    text: str = Field(min_length=1,max_length=200)
    request_id: UUID


class PrivateRead(SocialTarget):
    through_id: StrictInt = Field(ge=1)


class FriendAction(SocialTarget):
    operation: Literal['request','accept','decline']


class DirectChallenge(SocialTarget):
    deck_id: UUID


class ChallengeReply(Body):
    operation: Literal['accept','decline','cancel']
    deck_id: UUID | None = None


class ClassicAction(RequestBody):
    match_id: UUID | None = None
    version: StrictInt = Field(ge=0)
    action: Literal['select_deck','lock','unlock','first','mulligan','play','choose','leader','pass','concede','leave','rematch']
    payload: dict = Field(default_factory=dict)


def mistrealm_router(repository, clock):
    router = APIRouter(prefix="/api/mistrealm")
    from .mistrealm_events import SocialEvents
    social_events = SocialEvents(repository, clock)

    def identity(value):
        if not value or not value.startswith("MistrealmUid "):
            raise HTTPException(401, "无法读取玩家身份")
        uid = value[len("MistrealmUid "):]
        if not re.fullmatch(r"[^\s\x00-\x1f\x7f]{1,255}", uid):
            raise HTTPException(401, "无法读取玩家身份")
        return uid

    def call(fn, *args):
        try:
            return fn(*args)
        except MistrealmError as error:
            raise HTTPException(error.status, str(error)) from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @router.get('/v3/profile')
    def player_profile(uid: str | None = Query(None,min_length=1,max_length=255), authorization: str | None = Header(None)):
        return call(repository.mistrealm_profile,identity(authorization),uid,clock())

    @router.post('/v3/profile/settings')
    def player_settings(body: Preferences, authorization: str | None = Header(None)):
        return call(repository.mistrealm_preferences,identity(authorization),body.model_dump(exclude_none=True),clock())

    @router.get('/v3/profile/history')
    def player_history(page: int = Query(0,ge=0,le=10000), authorization: str | None = Header(None)):
        return call(repository.mistrealm_history,identity(authorization),page,clock())

    @router.get('/v3/profile/history/{match_id}')
    def player_history_detail(match_id: UUID, authorization: str | None = Header(None)):
        return call(repository.mistrealm_history_detail,identity(authorization),match_id)

    @router.post("/players/me")
    def register(body: Profile, authorization: str | None = Header(None)):
        return call(repository.mistrealm_register, identity(authorization), body.name, body.avatar, clock())

    @router.get("/players/me")
    def me(authorization: str | None = Header(None)):
        return call(repository.mistrealm_me, identity(authorization), clock())

    @router.post('/social/presence')
    def social_presence(authorization: str | None = Header(None)):
        return call(repository.mistrealm_social_pulse,identity(authorization),clock())

    @router.get('/social/events')
    async def social_stream(request: Request, authorization: str | None = Header(None)):
        uid = identity(authorization)
        player_id = await asyncio.to_thread(call, repository.mistrealm_social_connect, uid, clock())

        async def stream():
            signal = social_events.subscribe(player_id)
            channel_cursor, channel_revision = None, None
            previous_summary = None
            changed = {'players', 'channel', 'social:'+str(player_id), 'messages:'+str(player_id)}
            touch_at = monotonic()
            try:
                while not await request.is_disconnected():
                    if 'unavailable' in changed:
                        yield 'event: unavailable\ndata: {}\n\n'
                        return
                    packet = {}
                    if 'channel' in changed:
                        value = await asyncio.to_thread(call, repository.mistrealm_channel_messages, uid, 50, clock())
                        delta = channel_delta(value, channel_cursor, channel_revision)
                        channel_cursor = value['items'][-1]['id'] if value['items'] else None
                        channel_revision = delta['revision']
                        if not delta.get('unchanged'): packet['channel'] = delta
                    if changed - {'channel'}:
                        summary = await asyncio.to_thread(repository.mistrealm_social_pulse, uid, clock(), touch=False)
                        if summary != previous_summary:
                            packet['summary'] = summary
                            previous_summary = summary
                        packet['players_changed'] = 'players' in changed
                        packet['social_changed'] = 'social:'+str(player_id) in changed
                        packet['messages_changed'] = 'messages:'+str(player_id) in changed
                    if packet:
                        yield 'event: social\ndata: '+json.dumps(packet,ensure_ascii=False,separators=(',',':'))+'\n\n'
                    if monotonic()-touch_at >= 15:
                        await asyncio.to_thread(repository.mistrealm_social_touch,uid,clock())
                        touch_at = monotonic()
                        yield ': heartbeat\n\n'
                    try:
                        await asyncio.wait_for(signal.wait(), timeout=max(.1,15-(monotonic()-touch_at)))
                    except asyncio.TimeoutError:
                        pass
                    changed = social_events.take(signal)
            finally:
                social_events.unsubscribe(signal)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={
            'Cache-Control':'no-store','X-Accel-Buffering':'no'})

    @router.get('/social/players')
    def social_players(scope: Literal['all','friends','requests']='all',search: str=Query('',max_length=40),
                       page: int=Query(0,ge=0),authorization: str | None = Header(None)):
        return call(repository.mistrealm_social_players,identity(authorization),scope,search.strip(),page,clock())

    @router.post('/social/friends')
    def social_friend(body: FriendAction,authorization: str | None = Header(None)):
        return call(repository.mistrealm_friend,identity(authorization),body.uid,body.operation,clock())

    @router.post('/social/challenges')
    def social_challenge(body: DirectChallenge,authorization: str | None = Header(None)):
        return call(repository.mistrealm_invite,identity(authorization),body.uid,body.deck_id,clock())

    @router.post('/social/challenges/{invite_id}')
    def social_reply(invite_id: UUID,body: ChallengeReply,authorization: str | None = Header(None)):
        return call(repository.mistrealm_invite_reply,identity(authorization),invite_id,body.operation,body.deck_id,clock())

    @router.get('/social/conversations')
    def private_conversations(page: int=Query(0,ge=0),authorization: str | None = Header(None)):
        return call(repository.mistrealm_dm_conversations,identity(authorization),page,clock())

    @router.get('/social/messages')
    def private_messages(uid: str=Query(min_length=1,max_length=255),before: int | None=Query(None,ge=1),
                         after: int | None=Query(None,ge=1),authorization: str | None = Header(None)):
        if before is not None and after is not None: raise HTTPException(422,'只能选择向前或向后翻页')
        return call(repository.mistrealm_dm_messages,identity(authorization),uid,before,after,clock())

    @router.post('/social/messages')
    def private_send(body: PrivateText,authorization: str | None = Header(None)):
        return call(repository.mistrealm_dm_send,identity(authorization),body.uid,body.text,body.request_id,clock())

    @router.post('/social/messages/read')
    def private_read(body: PrivateRead,authorization: str | None = Header(None)):
        return call(repository.mistrealm_dm_read,identity(authorization),body.uid,body.through_id,clock())

    @router.post("/rooms")
    def create(body: RequestBody, authorization: str | None = Header(None)):
        return call(repository.mistrealm_create, identity(authorization), body.request_id, clock())

    @router.post("/rooms/join")
    def join(body: Join, authorization: str | None = Header(None)):
        return call(repository.mistrealm_join, identity(authorization), body.code, body.request_id, clock())

    @router.post("/matchmaking")
    def match_start(authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking, identity(authorization), "start", None, clock())

    @router.post("/matchmaking/heartbeat")
    def match_heartbeat(body: MatchTicket, authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking, identity(authorization), "heartbeat", body.ticket, clock())

    @router.post("/matchmaking/cancel")
    def match_cancel(body: MatchTicket, authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking, identity(authorization), "cancel", body.ticket, clock())

    @router.get("/v3/rooms/{room_id}")
    @router.get("/classic/rooms/{room_id}")
    @router.get("/rooms/{room_id}")
    def view(room_id: UUID, request: Request, authorization: str | None = Header(None),
             watch: str | None = Query(None,min_length=1,max_length=255),watch_match: UUID | None = None):
        uid=identity(authorization)
        if watch is not None:
            if watch_match is None: raise HTTPException(422,'缺少观战对局标识')
            value=call(repository.mistrealm_spectate,room_id,uid,watch,watch_match,clock())
        else: value=call(repository.mistrealm_view,room_id,uid,clock())
        return history_delta(value,request.query_params)

    @router.post("/rooms/{room_id}/actions")
    def action(room_id: UUID, body: Action, authorization: str | None = Header(None)):
        if set(body.payload) != FIELDS[body.action]:
            raise HTTPException(422, "操作参数不正确")
        return call(repository.mistrealm_action, room_id, identity(authorization), body.match_id,
                    body.version, body.request_id, body.action, body.payload, clock())

    @router.get("/v3/rooms/{room_id}/events")
    @router.get("/classic/rooms/{room_id}/events")
    @router.get("/rooms/{room_id}/events")
    async def events(room_id: UUID, request: Request, authorization: str | None = Header(None),
                     watch: str | None = Query(None,min_length=1,max_length=255),watch_match: UUID | None = None):
        uid = identity(authorization)
        if watch is not None and watch_match is None: raise HTTPException(422,'缺少观战对局标识')
        read=repository.mistrealm_spectate if watch is not None else repository.mistrealm_view
        args=(room_id,uid,watch,watch_match) if watch is not None else (room_id,uid)
        initial = await asyncio.to_thread(call, read, *args, clock())

        async def stream():
            last, heartbeat, value = None, monotonic(), initial
            cursor = dict(request.query_params)
            while not await request.is_disconnected():
                version = value["state"]["version"]
                if version != last:
                    yield "event: update\ndata: " + json.dumps(history_delta(value, cursor), ensure_ascii=False, separators=(',',':')) + "\n\n"
                    if 'sync_match' in cursor: cursor = history_cursor(value)
                    last, heartbeat = version, monotonic()
                elif monotonic()-heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = monotonic()
                if value["state"]["phase"] == "closed":
                    return
                await asyncio.sleep(0.7)
                try:
                    value = await asyncio.to_thread(read, *args, clock())
                except ValueError:
                    yield "event: unavailable\ndata: {}\n\n"
                    return

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
    @router.get('/classic/decks')
    def decks(authorization: str | None = Header(None)):
        return call(repository.mistrealm_decks,identity(authorization),clock())

    @router.post('/classic/decks')
    def save_deck(body: ClassicDeck,authorization: str | None = Header(None)):
        return call(repository.mistrealm_save_deck,identity(authorization),body.id,body.name,body.faction,body.leader,body.counts,clock())

    @router.post('/classic/decks/{deck_id}/delete')
    def delete_deck(deck_id: UUID,authorization: str | None = Header(None)):
        return call(repository.mistrealm_delete_deck,identity(authorization),deck_id,clock())

    @router.post('/classic/rooms')
    def classic_create(body: ClassicCreate,authorization: str | None = Header(None)):
        return call(repository.mistrealm_create,identity(authorization),body.request_id,clock(),body.deck_id)

    @router.post('/classic/rooms/join')
    def classic_join(body: ClassicJoin,authorization: str | None = Header(None)):
        return call(repository.mistrealm_join,identity(authorization),body.code,body.request_id,clock(),body.deck_id)

    @router.post('/classic/matchmaking')
    def classic_match(body: ClassicQueue,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'start',None,clock(),2,body.deck_id)

    @router.post('/classic/matchmaking/heartbeat')
    def classic_heartbeat(body: MatchTicket,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'heartbeat',body.ticket,clock(),2)

    @router.post('/classic/matchmaking/cancel')
    def classic_cancel(body: MatchTicket,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'cancel',body.ticket,clock(),2)

    @router.get('/classic/story')
    def story_progress(authorization: str | None = Header(None)):
        return call(repository.mistrealm_story_progress,identity(authorization),clock())

    @router.post('/classic/story/start')
    def story_start(body: StoryStart, authorization: str | None = Header(None)):
        return call(
            repository.mistrealm_story_start,
            identity(authorization),
            body.chapter,
            body.deck_id,
            clock(),
        )

    @router.get('/channel/messages')
    def channel_messages(
        after: str | None = Query(default=None, max_length=36),
        revision: str | None = Query(default=None, max_length=24),
        limit: int = Query(default=50, ge=1, le=100),
        authorization: str | None = Header(None),
    ):
        return channel_delta(call(
            repository.mistrealm_channel_messages,
            identity(authorization),
            limit,
            clock(),
        ), after, revision)

    @router.post('/channel/messages')
    def channel_post(body: ChannelText, authorization: str | None = Header(None)):
        return call(
            repository.mistrealm_channel_post,
            identity(authorization),
            body.text,
            clock(),
        )

    @router.post('/channel/challenges')
    def channel_challenge(body: ChannelChallenge, authorization: str | None = Header(None)):
        return call(
            repository.mistrealm_channel_challenge,
            identity(authorization),
            body.room_id,
            clock(),
        )

    @router.post('/v3/rooms/{room_id}/actions')
    @router.post('/classic/rooms/{room_id}/actions')
    def classic_action(room_id: UUID,body: ClassicAction,request: Request,authorization: str | None = Header(None)):
        from .mistrealm_classic_state import FIELDS as CLASSIC_FIELDS
        expected={'deck_id'} if body.action=='select_deck' else CLASSIC_FIELDS.get(body.action)
        if expected is None or set(body.payload)!=expected: raise HTTPException(422,'操作参数不正确')
        if body.action=='select_deck':
            try: UUID(body.payload['deck_id'])
            except (ValueError,TypeError,AttributeError): raise HTTPException(422,'牌组编号不正确')
        return history_delta(call(repository.mistrealm_action,room_id,identity(authorization),body.match_id,body.version,body.request_id,body.action,body.payload,clock()), request.query_params)

    @router.get('/v3/decks')
    def v3_decks(authorization: str | None = Header(None)):
        return call(repository.mistrealm_decks,identity(authorization),clock(),3)

    @router.post('/v3/decks')
    def v3_save(body: ClassicDeck,authorization: str | None = Header(None)):
        return call(repository.mistrealm_save_deck,identity(authorization),body.id,body.name,body.faction,body.leader,body.counts,clock(),3)

    @router.post('/v3/decks/{deck_id}/select')
    def v3_select_deck(deck_id: UUID,authorization: str | None = Header(None)):
        return call(repository.mistrealm_select_v3_deck,identity(authorization),deck_id,clock())

    @router.post('/v3/decks/{deck_id}/delete')
    def v3_delete(deck_id: UUID,authorization: str | None = Header(None)):
        return call(repository.mistrealm_delete_deck,identity(authorization),deck_id,clock())

    @router.post('/v3/rooms')
    def v3_create(body: ClassicCreate,authorization: str | None = Header(None)):
        return call(repository.mistrealm_create,identity(authorization),body.request_id,clock(),body.deck_id,3)

    @router.post('/v3/rooms/join')
    def v3_join(body: ClassicJoin,authorization: str | None = Header(None)):
        return call(repository.mistrealm_join,identity(authorization),body.code,body.request_id,clock(),body.deck_id,3)

    @router.post('/v3/matchmaking')
    def v3_match(body: ClassicQueue,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'start',None,clock(),3,body.deck_id)

    @router.post('/v3/matchmaking/heartbeat')
    def v3_heartbeat(body: MatchTicket,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'heartbeat',body.ticket,clock(),3)

    @router.post('/v3/matchmaking/cancel')
    def v3_cancel(body: MatchTicket,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'cancel',body.ticket,clock(),3)

    @router.get('/v3/ranked')
    def ranked_profile(authorization: str | None = Header(None)):
        return call(repository.mistrealm_ranked_profile,identity(authorization),clock())

    @router.get('/v3/ranked/leaderboard')
    def ranked_leaderboard(season_id: int | None = Query(default=None,ge=1),
                           page: int = Query(default=0,ge=0,le=10000), authorization: str | None = Header(None)):
        return call(repository.mistrealm_ranked_leaderboard,identity(authorization),season_id,page,clock())

    @router.post('/v3/ranked/honor')
    def ranked_honor(body: RankedHonor,authorization: str | None = Header(None)):
        return call(repository.mistrealm_ranked_equip,identity(authorization),body.season_id,clock())

    @router.post('/v3/ranked/matchmaking')
    def ranked_match(body: ClassicQueue,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'start',None,clock(),3,body.deck_id,'ranked')

    @router.post('/v3/ranked/matchmaking/heartbeat')
    def ranked_heartbeat(body: MatchTicket,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'heartbeat',body.ticket,clock(),3,None,'ranked')

    @router.post('/v3/ranked/matchmaking/cancel')
    def ranked_cancel(body: MatchTicket,authorization: str | None = Header(None)):
        return call(repository.mistrealm_matchmaking,identity(authorization),'cancel',body.ticket,clock(),3,None,'ranked')

    @router.get('/v3/story')
    def v3_story(authorization: str | None = Header(None)):
        return call(repository.mistrealm_story_progress,identity(authorization),clock())

    @router.post('/v3/story/start')
    def v3_story_start(body: StoryStart,authorization: str | None = Header(None)):
        return call(repository.mistrealm_story_start,identity(authorization),body.chapter,body.deck_id,clock(),3)

    @router.get('/v3/expedition/catalogue')
    def expedition_catalogue():
        from .mistrealm_expedition_cards import CARDS, FACTIONS
        return dict(cards=CARDS,factions=FACTIONS)

    @router.get('/v3/expedition')
    def expedition_get(authorization: str | None = Header(None)):
        return call(repository.mistrealm_expedition_get,identity(authorization),clock())

    @router.post('/v3/expedition/start')
    def expedition_start(authorization: str | None = Header(None)):
        return call(repository.mistrealm_expedition_start,identity(authorization),clock())

    @router.post('/v3/expedition/actions')
    def expedition_action(body: ExpeditionAction,authorization: str | None = Header(None)):
        return call(repository.mistrealm_expedition_action,identity(authorization),body.run_id,body.version,body.action,body.payload,clock())

    return router
