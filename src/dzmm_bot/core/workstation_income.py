"""Daily account-level workstation income, with atomic receipts and ledger credits."""
from sqlalchemy import select

from .schema import BEIJING, UserRecord, WorkstationIncomeSettingsRecord, WorkstationIncomeRecord


class WorkstationIncomeMixin:
    def workstation_income_enabled(self):
        with self._session() as session:
            return bool(session.scalar(select(WorkstationIncomeSettingsRecord.enabled).where(
                WorkstationIncomeSettingsRecord.id == 1)))

    def run_workstation_income_jobs(self, now):
        if now.tzinfo is None:
            raise ValueError('Workstation settlement requires an aware timestamp')
        now = now.astimezone(BEIJING)
        today = now.date()
        with self.transaction(), self._session() as session:
            self.lock_workstation_rules(session)
            # Serialize the entire daily snapshot across scheduler processes.
            settings = session.scalar(select(WorkstationIncomeSettingsRecord).where(
                WorkstationIncomeSettingsRecord.id == 1).with_for_update())
            if (settings is None or not settings.enabled or settings.first_settlement_date > today
                    or settings.last_settled_on is not None and settings.last_settled_on >= today):
                return {'accounts': 0, 'amount': 0}
            accounts, total = 0, 0
            users = session.scalars(select(UserRecord).order_by(UserRecord.id).with_for_update()).all()
            for user in users:
                if session.get(WorkstationIncomeRecord, (user.id, today)) is not None:
                    continue
                components = self._component_views(session, user.id)
                amount = sum(c['daily_income'] for c in components)
                session.add(WorkstationIncomeRecord(user_id=user.id, settlement_date=today,
                    amount=amount, components=components, settled_at=now))
                session.flush()  # receipt uniqueness before crediting; same transaction
                self._apply_balance_change(user, amount, 'workstation_income', now,
                    memo=f'{today.isoformat()} 工位日收益')
                accounts += 1
                total += amount
            settings.last_settled_on = today
            return {'accounts': accounts, 'amount': total}
