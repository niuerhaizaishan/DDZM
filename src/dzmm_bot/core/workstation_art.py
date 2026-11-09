"""Shared, deterministic mapping from equipped growth components to artwork."""
from .workstation_art_assets import ART_REVISION
from .workstation_catalog import CATEGORIES

ART_SIZE = (1536, 1024)
ART_ORDER = ('floor', 'location', 'desk', 'monitor', 'computer', 'keyboard', 'mouse', 'chair', 'plant')
ART_KEYS = frozenset(ART_ORDER)


def asset_filename(key, level):
    if key not in ART_KEYS or type(level) is not int or not 1 <= level <= 10:
        raise ValueError('Unknown workstation component or level')
    return f'growth-{ART_REVISION}-{key}-lv{level:02d}.png'


ART_FILENAMES = frozenset(asset_filename(key, level) for key in ART_ORDER for level in range(1, 11))


def component_scene(components):
    by_key = {}
    for component in components:
        key, level = component.get('key'), component.get('active_level')
        asset_filename(key, level)
        if key in by_key or type(component.get('equipped')) is not bool:
            raise ValueError('Invalid workstation component state')
        by_key[key] = component
    if set(by_key) != ART_KEYS:
        raise ValueError('Workstation requires all nine component states')
    return {'revision': ART_REVISION, 'width': ART_SIZE[0], 'height': ART_SIZE[1],
            'layers': [{'key': key, 'level': by_key[key]['active_level'],
                        'filename': asset_filename(key, by_key[key]['active_level'])}
                       for key in ART_ORDER if by_key[key]['equipped']]}


def preview_art_manifest():
    return {'revision': ART_REVISION, 'order': ART_ORDER,
            'categories': [{k: c[k] for k in ('number', 'key', 'name', 'names', 'group')} for c in CATEGORIES]}
