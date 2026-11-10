"""Inspect or explicitly enable daily settlement without resetting existing receipts."""
import argparse
from datetime import date
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dzmm_bot.core.schema import WorkstationIncomeSettingsRecord
from workstation_deploy_config import database_url


def configure(*, enabled=None, first_date=None, apply=False, env_file=None):
    engine = create_engine(database_url(env_file))
    try:
        with Session(engine) as session, session.begin():
            current = session.get(WorkstationIncomeSettingsRecord, 1, with_for_update=True)
            before = None if current is None else {
                'enabled': current.enabled, 'first_settlement_date': current.first_settlement_date.isoformat(),
                'last_settled_on': current.last_settled_on.isoformat() if current.last_settled_on else None,
            }
            if enabled is None:
                return {'apply': False, 'before': before, 'after': before}
            if current is None and first_date is None:
                raise ValueError('Initial configuration requires --first-date YYYY-MM-DD')
            if current is not None and first_date is not None and first_date != current.first_settlement_date:
                raise ValueError('Existing first settlement date cannot be changed; receipts and cursor must be preserved')
            after = {**(before or {}), 'enabled': enabled,
                     'first_settlement_date': (current.first_settlement_date if current else first_date).isoformat(),
                     'last_settled_on': before['last_settled_on'] if before else None}
            if apply:
                if current is None:
                    session.add(WorkstationIncomeSettingsRecord(id=1, enabled=enabled, first_settlement_date=first_date))
                else:
                    current.enabled = enabled
            return {'apply': apply, 'before': before, 'after': after}
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    change = parser.add_mutually_exclusive_group()
    change.add_argument('--enable', action='store_true')
    change.add_argument('--disable', action='store_true')
    parser.add_argument('--first-date', type=date.fromisoformat)
    parser.add_argument('--apply', action='store_true', help='Without this flag, only report the proposed configuration')
    parser.add_argument('--env-file', type=Path)
    args = parser.parse_args()
    if args.apply and not (args.enable or args.disable):
        parser.error('--apply requires --enable or --disable')
    try:
        print(json.dumps(configure(enabled=True if args.enable else False if args.disable else None,
            first_date=args.first_date, apply=args.apply, env_file=args.env_file)))
    except ValueError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
