"""Transactional doudizhu persistence and recipient-specific projections."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
from secrets import SystemRandom, randbelow
from uuid import UUID, uuid4

from sqlalchemy import select

from .doudizhu_state import apply_action, apply_timeout, new_round
from .schema import (DoudizhuRoomRecord as Room, DoudizhuRoundRecord as Round,
                     DoudizhuRequestRecord as Receipt, DoudizhuMessageRecord as Message,
                     ClubPlayerRecord, GroupChatRecord, InboundRecord, OutboundRecord, UserRecord)


COIN_STAKES = {5, 10, 20}


class DoudizhuRateLimitError(ValueError):
    pass


class DoudizhuRepositoryMixin:
    @staticmethod
    def _ddz_account(session, player, *, lock=False):
        if player.user_id is None:
            raise ValueError('摸鱼币场仅限已入职员工')
        query = select(UserRecord).where(UserRecord.id == player.user_id)
        if lock:
            query = query.with_for_update()
        user = session.scalar(query)
        if user is None:
            raise ValueError('摸鱼币场仅限已入职员工')
        return user

    @staticmethod
    def _ddz_room(session, room_id):
        room = session.scalar(select(Room).where(Room.id == room_id).with_for_update())
        if room is None:
            raise ValueError('房间不存在')
        return room

    @staticmethod
    def _ddz_announced(session, room):
        if room.inbound_id is None:
            return True
        return session.scalar(select(OutboundRecord.id).where(
            OutboundRecord.inbound_message_id == room.inbound_id,
            OutboundRecord.group_chat_id == room.group_chat_id,
            OutboundRecord.content_type == 'text', OutboundRecord.status == 'sent').limit(1)) is not None

    def create_doudizhu_room(self, platform_id, group_chat_id=None, inbound_id=None, now=None, *, room_type='casual', stake=0):
        if room_type not in {'casual', 'coin'}:
            raise ValueError('房间类型无效')
        if room_type == 'casual':
            stake = 0
        elif stake not in COIN_STAKES:
            raise ValueError('摸鱼币场仅支持 5、10、20 币')
        with self.transaction():
          with self._session() as session:
            user = self._club_player(session, platform_id, now, lock=True)
            if group_chat_id is not None:
                inbound = session.scalar(select(InboundRecord).where(InboundRecord.id == inbound_id).with_for_update())
                group = session.get(GroupChatRecord, group_chat_id)
                if not inbound or inbound.group_chat_id != group_chat_id or inbound.sender_platform_id != platform_id or not group or not group.listening_enabled:
                    raise ValueError('群聊或入站消息不可用')
            room = session.scalar(select(Room).where(Room.inbound_id == inbound_id)) if inbound_id else None
            if room is None:
                self._ensure_club_player_available(session, user.id, now)
                account = None
                if room_type == 'coin':
                    account = self._ddz_account(session, user, lock=True)
                    if account.balance < stake:
                        raise ValueError(f'余额不足，需要{stake}摸鱼币')
                room = Room(group_chat_id=group_chat_id, inbound_id=inbound_id, creator_id=user.id,
                    short_id=uuid4().hex[:12], code=f'{randbelow(10000):04d}',
                    seats=[str(user.id), None, None], ready=[False] * 3,
                    room_type=room_type, stake=stake,
                    escrowed=[room_type == 'coin', False, False], settled=False, phase='waiting',
                    created_at=now, deadline=now + timedelta(minutes=10))
                session.add(room)
                session.flush()
                if account is not None:
                    self._apply_balance_change(account, -stake, 'doudizhu_buy_in', now,
                                               memo=f'斗地主房间 {room.short_id} 入场托管')
            view = self._ddz_view(session, room, user, now)
            return {**view, 'code': room.code} if room.inbound_id is not None else view

    def _ddz_view(self, session, room, user, now):
        round_row = session.get(Round, room.round_id) if room.round_id else None
        state = round_row.state if round_row else None
        seat = room.seats.index(str(user.id)) if str(user.id) in room.seats else None
        if seat is not None:
            previous_seen = room.presence.get(str(seat))
            if not previous_seen or (now - datetime.fromisoformat(previous_seen)).total_seconds() >= 10:
                room.presence = {**room.presence, str(seat): now.isoformat()}
        players = []
        for i, uid in enumerate(room.seats):
            person = session.get(ClubPlayerRecord, UUID(uid)) if uid else None
            players.append({'id': str(person.id) if person else uid,
                'name': person.display_name if person else '已离开玩家', 'ready': room.ready[i],
                'count': len(state['hands'][i]) if state else 0,
                'trustee': state['trustees'][i] if state else False,
                'online': bool(room.presence.get(str(i))) and (now - datetime.fromisoformat(room.presence[str(i)])).total_seconds() < 30} if uid else None)
        messages = session.execute(select(Message, ClubPlayerRecord.display_name).join(ClubPlayerRecord, ClubPlayerRecord.id == Message.user_id)
            .where(Message.room_id == room.id)
            .order_by(Message.created_at.desc(), Message.id.desc()).limit(100)).all()
        creator = session.get(ClubPlayerRecord, room.creator_id)
        return {'id': str(room.id), 'short_id': room.short_id,
            'creator_name': creator.display_name if creator else '玩家',
            'round_id': str(room.round_id) if room.round_id else None,
            'version': room.version, 'phase': room.phase, 'seat': seat, 'players': players,
            'is_host': user.id == room.creator_id,
            'room_type': room.room_type, 'stake': room.stake, 'settlement': room.settlement,
            'rematch_waiting': room.phase == 'waiting' and room.round_number > 0,
            'deadline': room.deadline.isoformat() if room.deadline else None, 'server_time': now.isoformat(),
            'hand': list(state['hands'][seat]) if state and seat is not None else [],
            'final_hands': [list(hand) for hand in state['hands']] if state and state['phase'] == 'finished' else [],
            'bottom': list(state['bottom']) if state and state['landlord'] is not None else [],
            'turn': state['turn'] if state else None, 'landlord': state['landlord'] if state else None,
            'bid': state['bid'] if state else 0, 'multiplier': state['multiplier'] if state else 1,
            'previous': state['previous'] if state else None, 'table': state['table'] if state else [None] * 3,
            'result': state['result'] if state else None, 'events': state['events'] if state else [],
            'messages': [{'id': str(m.id), 'name': name, 'text': m.content} for m, name in reversed(messages)]}

    def doudizhu_view(self, room_id, platform_id, now):
        with self._session() as session:
            user = self._club_player(session, platform_id, now)
            room = self._ddz_room(session, room_id)
            return self._ddz_view(session, room, user, now)

    def list_doudizhu_rooms(self, platform_id, now):
        with self._session() as session:
            self._club_player(session, platform_id, now)
            rooms = session.scalars(select(Room).where(Room.phase.in_(('waiting', 'bidding', 'playing')))
                .order_by(Room.created_at.desc()).limit(100)).all()
            return [{'id': str(r.id), 'short_id': r.short_id,
                     'creator_name': session.get(ClubPlayerRecord, r.creator_id).display_name,
                     'room_type': r.room_type, 'stake': r.stake, 'phase': r.phase,
                     'occupied': sum(uid is not None for uid in r.seats)} for r in rooms
                    if self._ddz_announced(session, r) and (r.phase != 'waiting' or r.deadline > now)]

    @staticmethod
    def _ddz_notice(session, room, text):
        if room.group_chat_id is None:
            return
        group = session.get(GroupChatRecord, room.group_chat_id)
        if group and group.chatroom_id:
            session.add(OutboundRecord(group_chat_id=group.id, destination_chatroom_id=group.chatroom_id,
                delivery_key=group.chatroom_id, delivery_kind='group', text=text))

    def _ddz_deal(self, session, room, now):
        deck = list(range(54))
        SystemRandom().shuffle(deck)
        room.round_number += 1
        row = Round(room_id=room.id, number=room.round_number, state=new_round(tuple(deck), randbelow(3), now))
        session.add(row)
        session.flush()
        room.round_id = row.id
        room.phase = 'bidding'
        room.deadline = datetime.fromisoformat(row.state['deadline'])
        return row

    def _ddz_sync(self, session, room, row, now):
        state = row.state
        previous_phase = room.phase
        if state['phase'] == 'redeal':
            room.redeals += 1
            if room.redeals < 3:
                self._ddz_deal(session, room, now)
                return
            room.phase, room.deadline = 'cancelled', None
            self._refund_doudizhu_room(session, room, now, '连续无人叫分')
            if not row.notice_sent:
                self._ddz_notice(session, room, f'斗地主房间 {room.short_id} 连续三次无人叫分，已取消。')
                row.notice_sent = True
            return
        room.phase = state['phase']
        room.deadline = datetime.fromisoformat(state['deadline']) if state['deadline'] else None
        if room.phase == 'finished' and not row.notice_sent:
            names = [(session.get(ClubPlayerRecord, UUID(uid)).display_name if session.get(ClubPlayerRecord, UUID(uid)) else '已离开玩家') for uid in room.seats]
            landlord = state['landlord']
            winners = state['result']['winners']
            lines = ['🃏 斗地主对局结束']
            for i, name in enumerate(names):
                lines.append(f'{"地主" if i == landlord else "农民"}：{name} · {"胜利" if i in winners else "落败"}')
            spring = {'spring': '春天', 'reverse_spring': '反春'}.get(state['result']['spring'])
            lines.append(f'本局倍数：{state["multiplier"]}' + (f'（{spring}）' if spring else ''))
            self._ddz_notice(session, room, '\n'.join(lines))
            row.notice_sent = True
        if room.phase == 'finished':
            if previous_phase != 'finished':
                room.ready = [False] * 3
            self._settle_doudizhu_room(session, room, state, now)

    def _refund_doudizhu_room(self, session, room, now, reason):
        if room.room_type != 'coin':
            return
        escrowed = list(room.escrowed or [False, False, False])
        for seat, held in enumerate(escrowed):
            if not held or room.seats[seat] is None:
                continue
            player = session.get(ClubPlayerRecord, UUID(room.seats[seat]))
            account = session.get(UserRecord, player.user_id, with_for_update=True) if player and player.user_id else None
            if account is not None:
                self._apply_balance_change(account, room.stake, 'doudizhu_refund', now,
                                           memo=f'斗地主房间 {room.short_id}：{reason}')
            escrowed[seat] = False
        room.escrowed = escrowed

    def _settle_doudizhu_room(self, session, room, state, now):
        if room.settled:
            return
        winners = list(state['result']['winners'])
        payouts = [0, 0, 0]
        if room.room_type == 'coin':
            if not all(room.escrowed):
                raise RuntimeError('斗地主奖池托管不完整')
            pot = room.stake * 3
            for index, seat in enumerate(winners):
                player = session.get(ClubPlayerRecord, UUID(room.seats[seat]))
                account = session.get(UserRecord, player.user_id, with_for_update=True) if player and player.user_id else None
                if account is None:
                    raise RuntimeError('斗地主结算玩家不存在')
                payout = pot // len(winners) + (1 if index < pot % len(winners) else 0)
                payouts[seat] = payout
                self._apply_balance_change(account, payout, 'doudizhu_settlement', now,
                                           memo=f'斗地主房间 {room.short_id} 胜方结算')
        room.escrowed = [False, False, False]
        room.settled = True
        room.settlement = {
            'winner_seats': winners,
            'payouts': payouts,
            'outcomes': ['win' if seat in winners else 'loss' for seat in range(3)],
        }

    def doudizhu_action(self, room_id, platform_id, round_id, version, request_id, action, payload, now):
        digest = sha256(json.dumps([str(round_id), version, action, payload], sort_keys=True).encode()).hexdigest()
        with self.transaction(), self._session() as session:
            user = self._club_player(session, platform_id, now, lock=True)
            room = self._ddz_room(session, room_id)
            receipt = session.scalar(select(Receipt).where(Receipt.room_id == room_id, Receipt.user_id == user.id, Receipt.request_id == request_id))
            if receipt:
                if receipt.digest != digest:
                    raise ValueError('重复请求内容不同')
                return self._ddz_view(session, room, user, now)
            if room.version != version or room.round_id != round_id:
                raise ValueError('牌局已更新，请刷新')
            if room.deadline and now >= room.deadline:
                raise ValueError('操作已超时，请刷新')
            seat = room.seats.index(str(user.id)) if str(user.id) in room.seats else None
            if room.phase == 'waiting':
                seats, ready = list(room.seats), list(room.ready)
                if action == 'claim':
                    if room.inbound_id is not None and not self._ddz_announced(session, room):
                        raise ValueError('群消息尚未送达')
                    if seat is not None or None not in seats:
                        raise ValueError('已入座或房间已满')
                    self._ensure_club_player_available(
                        session, user.id, now, exclude=('doudizhu', room.id),
                    )
                    if room.inbound_id is not None and payload.get('code') != room.code:
                        raise ValueError('入座码错误')
                    next_seat = seats.index(None)
                    if room.room_type == 'coin':
                        account = self._ddz_account(session, user, lock=True)
                        if account.balance < room.stake:
                            raise ValueError(f'余额不足，需要{room.stake}摸鱼币')
                        self._apply_balance_change(account, -room.stake, 'doudizhu_buy_in', now,
                                                   memo=f'斗地主房间 {room.short_id} 入场托管')
                        escrowed = list(room.escrowed)
                        escrowed[next_seat] = True
                        room.escrowed = escrowed
                    seats[next_seat] = str(user.id)
                elif seat is None:
                    raise ValueError('观众不能操作席位')
                elif action in ('ready', 'unready'):
                    ready[seat] = action == 'ready'
                elif action == 'leave':
                    if user.id == room.creator_id or room.round_number > 0:
                        self._refund_doudizhu_room(session, room, now, '等待阶段退出')
                        room.phase, room.deadline = 'cancelled', None
                        if room.round_number > 0:
                            self._ddz_notice(session, room, f'斗地主房间 {room.short_id} 有玩家退出续局，已结束；换人请发送 /斗地主 重新开局。')
                    else:
                        if room.room_type == 'coin' and room.escrowed[seat]:
                            account = self._ddz_account(session, user, lock=True)
                            self._apply_balance_change(account, room.stake, 'doudizhu_refund', now,
                                                       memo=f'斗地主房间 {room.short_id} 离开等待房间')
                            escrowed = list(room.escrowed)
                            escrowed[seat] = False
                            room.escrowed = escrowed
                        seats[seat], ready[seat] = None, False
                        room.presence = {k: v for k, v in room.presence.items() if k != str(seat)}
                else:
                    raise ValueError('当前不能进行该操作')
                room.seats, room.ready = seats, ready
                if None not in seats and all(ready):
                    room.code = ''
                    self._ddz_deal(session, room, now)
            else:
                if seat is None or room.phase == 'cancelled':
                    raise ValueError('当前不能进行该操作')
                row = session.get(Round, room.round_id)
                if row.state['phase'] == 'finished' and room.phase != 'finished':
                    self._ddz_sync(session, room, row, now)
                if row.state['phase'] == 'finished' and action in ('ready', 'unready'):
                    ready = list(room.ready)
                    ready[seat] = action == 'ready'
                    room.ready = ready
                elif row.state['phase'] == 'finished' and action in ('start', 'rematch'):
                    if user.id != room.creator_id:
                        raise ValueError('只有房主可以开始下一局')
                    if not all(room.ready):
                        raise ValueError('请等待所有玩家准备')
                    if room.room_type == 'coin':
                        accounts = []
                        for raw_player_id in room.seats:
                            player = session.get(ClubPlayerRecord, UUID(raw_player_id))
                            account = self._ddz_account(session, player, lock=True)
                            if account.balance < room.stake:
                                raise ValueError(f'{player.display_name}余额不足，无法续局')
                            accounts.append(account)
                        for account in accounts:
                            self._apply_balance_change(
                                account, -room.stake, 'doudizhu_buy_in', now,
                                memo=f'斗地主房间 {room.short_id} 续局托管',
                            )
                    room.ready = [False] * 3
                    room.settled, room.settlement = False, None
                    room.escrowed = [room.room_type == 'coin'] * 3
                    room.redeals = 0
                    room.code = ''
                    self._ddz_deal(session, room, now)
                else:
                    row.state = apply_action(row.state, seat, 'takeover' if action == 'leave' else action, payload, now)
                    self._ddz_sync(session, room, row, now)
            room.version += 1
            session.add(Receipt(room_id=room_id, user_id=user.id, request_id=request_id, digest=digest))
            session.flush()
            return self._ddz_view(session, room, user, now)

    def advance_doudizhu_deadlines(self, now):
        with self.transaction(), self._session() as session:
            rooms = session.scalars(select(Room).where(Room.phase.in_(('waiting', 'bidding', 'playing')), Room.deadline <= now)
                .order_by(Room.deadline).limit(100).with_for_update(skip_locked=True)).all()
            for room in rooms:
                deadline = room.deadline
                if room.phase == 'waiting':
                    self._refund_doudizhu_room(session, room, now, '房间等待超时')
                    room.phase, room.deadline = 'cancelled', None
                    self._ddz_notice(session, room, f'斗地主房间 {room.short_id} 等待超时，已取消。')
                else:
                    row = session.get(Round, room.round_id)
                    row.state = apply_timeout(row.state, now)
                    self._ddz_sync(session, room, row, deadline)
                room.version += 1
            return len(rooms)

    def doudizhu_chat(self, room_id, platform_id, round_id, request_id, text, now):
        content = text.strip()
        if not 1 <= len(content) <= 300:
            raise ValueError('消息需要 1～300 字')
        with self._session() as session:
            user = self._club_player(session, platform_id, now)
            room = self._ddz_room(session, room_id)
            old = session.scalar(select(Message).where(Message.room_id == room_id, Message.user_id == user.id, Message.request_id == request_id))
            if old:
                if old.content != content or old.round_id != round_id:
                    raise ValueError('重复请求内容不同')
                return {'id': str(old.id), 'name': user.display_name, 'text': old.content}
            if room.round_id != round_id or room.phase not in ('waiting', 'bidding', 'playing', 'finished'):
                raise ValueError('本局当前不能发言')
            previous = session.scalar(select(Message.created_at).where(Message.room_id == room_id, Message.user_id == user.id)
                .order_by(Message.created_at.desc()).limit(1))
            if previous and (now - previous).total_seconds() < 2:
                raise DoudizhuRateLimitError('请间隔两秒再发言')
            message = Message(room_id=room_id, round_id=round_id, user_id=user.id, request_id=request_id,
                              content=content, created_at=now)
            session.add(message)
            session.flush()
            return {'id': str(message.id), 'name': user.display_name, 'text': message.content}
