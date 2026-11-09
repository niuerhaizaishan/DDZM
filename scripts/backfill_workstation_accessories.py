"""Grant environment accessories to existing accounts without charging them.

The command is intentionally explicit: without ``--apply`` it only reports the
number of rows that would be added. It never changes balances or purchase
receipts; existing ownership/equipped flags are preserved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from dzmm_bot.core.workstation_accessories import ACCESSORIES
from dzmm_bot.core.schema import UserRecord, WorkstationComponentRecord, WorkstationAccessoryRecord
from workstation_deploy_config import database_url


def target_environment(connection, user_id) -> int:
    rows = connection.execute(select(WorkstationComponentRecord.category_number,
        WorkstationComponentRecord.highest_level).where(WorkstationComponentRecord.user_id == user_id,
        WorkstationComponentRecord.category_number.between(1, 5))).all()
    levels = {int(row[0]): int(row[1]) for row in rows}
    return min((levels.get(number, 1) + 1) // 2 for number in range(1, 6))


def run(apply: bool, *, env_file=None) -> dict:
    engine = create_engine(database_url(env_file), pool_pre_ping=True)
    planned = 0
    inserted = 0
    users = 0
    with engine.begin() as connection:
        account_rows = connection.execute(select(UserRecord.id).order_by(UserRecord.id).with_for_update()).scalars().all()
        users = len(account_rows)
        for user_id in account_rows:
            environment = target_environment(connection, user_id)
            for item in ACCESSORIES:
                if item["environment"] > environment:
                    continue
                exists = connection.scalar(select(WorkstationAccessoryRecord.accessory_number).where(
                    WorkstationAccessoryRecord.user_id == user_id,
                    WorkstationAccessoryRecord.accessory_number == item['number']))
                if exists:
                    continue
                planned += 1
                if apply:
                    insert = postgres_insert if engine.dialect.name == 'postgresql' else sqlite_insert
                    result = connection.execute(insert(WorkstationAccessoryRecord).values(
                        user_id=user_id, accessory_number=item['number'], equipped=True).on_conflict_do_nothing())
                    inserted += result.rowcount
    engine.dispose()
    return {"apply": apply, "users": users, "planned": planned, "inserted": inserted}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument('--env-file', type=Path, help='Private server environment file; process environment takes precedence')
    args = parser.parse_args()
    print(json.dumps(run(args.apply, env_file=args.env_file), ensure_ascii=False))
