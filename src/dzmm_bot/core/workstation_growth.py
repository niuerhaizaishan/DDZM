"""Growth status and batch prices shared by account views and paid actions."""
from .workstation_catalog import upgrade_cost, environment_upgrade_cost


def current_environment(components):
    return min((c['active_level'] + 1) // 2 for c in components if c['number'] <= 5)


def growth_state(components, accessories, scene=None):
    highest = min((c['highest_level'] + 1) // 2 for c in components if c['number'] <= 5)
    switchable = min((c['highest_level'] + 1) // 2 for c in components)
    return {
        'highest_environment': highest,
        'switchable_environment': switchable,
        'active_environment': scene['environment'] if scene else None,
        'core_equipped_count': sum(c['equipped'] for c in components),
        'accessories_owned': len(accessories),
        'accessories_equipped': sum(a['equipped'] for a in accessories),
    }


def batch_growth_plan(components, kind, *, rules=None):
    stage = min((c['highest_level'] + 1) // 2 for c in components if c['number'] <= 5)
    if kind == 'polish':
        return {'status': 'bundled', 'environment': stage, 'targets': {}, 'price': 0}
    if kind == 'advance' and stage == 5:
        return {'status': 'max', 'environment': stage, 'targets': {}, 'price': 0}
    if kind == 'advance':
        missing = [c['category'] for c in components if c['number'] >= 6 and c['highest_level'] < stage * 2]
        if missing:
            return {'status': 'devices_required', 'environment': stage + 1, 'targets': {}, 'price': 0,
                    'prerequisite_environment': stage, 'missing_devices': missing}
    target = stage * 2 + 1 if kind == 'advance' else stage * 2
    targets = {c['number']: target for c in components
               if (kind == 'advance' or c['number'] <= 5) and c['highest_level'] < target}
    cost = sum(upgrade_cost(c['highest_level'], targets[c['number']], rules=rules)
               for c in components if c['number'] in targets)
    if kind == 'advance':
        # Legacy mixed holdings have already paid for some of the move. Retain
        # that progress as a proportional discount; regular holdings pay exactly
        # the configured bundle price. Integer arithmetic avoids rounding drift.
        full = (5 * upgrade_cost(stage * 2 - 1, target, rules=rules)
                + 4 * upgrade_cost(stage * 2, target, rules=rules))
        cost = environment_upgrade_cost(stage, rules=rules) * min(cost, full) // full
    return {'status': 'available' if targets else 'complete',
            'environment': stage + 1 if kind == 'advance' else stage,
            'targets': targets, 'price': cost}


def growth_offers(components, level_cap, balance, *, rules=None):
    offers = {}
    for kind in ('advance', 'polish'):
        plan = batch_growth_plan(components, kind, rules=rules)
        required = max(plan['targets'].values(), default=0)
        status = plan['status']
        if status == 'available':
            status = 'rank_locked' if required > level_cap else 'insufficient_balance' if plan['price'] > balance else status
        offers[kind] = {**plan, 'status': status, 'required_level': required,
                        'shortage': max(0, plan['price'] - balance)}
    return offers
