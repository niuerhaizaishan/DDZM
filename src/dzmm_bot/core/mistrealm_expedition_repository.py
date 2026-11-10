"""Expedition progress is private and separate from PvP rooms and ratings."""
from secrets import SystemRandom

from .schema import MistrealmExpeditionRecord
from . import mistrealm_expedition as expedition


class MistrealmExpeditionMixin:
    def mistrealm_expedition_get(self, uid, now):
        with self._session() as session:
            player=self._mr_player(session,uid)
            record=session.get(MistrealmExpeditionRecord,player.id)
            return expedition.project(record.state) if record else None

    def mistrealm_expedition_start(self, uid, now):
        with self._session() as session:
            player=self._mr_player(session,uid)
            record=session.get(MistrealmExpeditionRecord,player.id)
            if record is None:
                record=MistrealmExpeditionRecord(player_id=player.id,state=expedition.new_run(SystemRandom()),updated_at=now)
                session.add(record)
            return expedition.project(record.state)

    def mistrealm_expedition_action(self, uid, run_id, version, action, payload, now):
        from .mistrealm_repository import MistrealmError, ms
        with self._session() as session:
            player=self._mr_player(session,uid)
            record=session.get(MistrealmExpeditionRecord,player.id)
            if record is None:raise MistrealmError('请先开始远征',404)
            if record.state['id']!=str(run_id) or record.state['version']!=version:
                raise MistrealmError('远征进度已更新，请刷新后继续')
            record.state=expedition.act(record.state,uid,action,payload,ms(now),SystemRandom())
            record.updated_at=now
            return expedition.project(record.state)
