"""Independent accessory art adapter using captured ownership and equip state."""
from .workstation_art import ART_SIZE, component_scene
from .workstation_stage5_assets import ASSOCIATION, FILES, ORDER, REVISION
from . import workstation_stage1_assets as stage1
from . import workstation_stage2_assets as stage2
from . import workstation_stage3_assets as stage3
from . import workstation_stage4_assets as stage4
from .workstation_accessories import BY_NUMBER
from .workstation_layout import visible_layers

STAGE5_FILENAMES = frozenset(FILES.values())
REGISTRIES = {1: (stage1.FILES, stage1.ORDER, stage1.REVISION),
              2: (stage2.FILES, stage2.ORDER, stage2.REVISION),
              3: (stage3.FILES, stage3.ORDER, stage3.REVISION),
              4: (stage4.FILES, stage4.ORDER, stage4.REVISION), 5: (FILES, ORDER, REVISION)}
ACCESSORY_FILENAMES = frozenset(filename for files, _, _ in REGISTRIES.values() for filename in files.values())
CORE_KEYS = ('computer', 'monitor', 'keyboard', 'mouse')


def accessory_scene(components, accessories=()):
    component_scene(components)  # Apply the same strict nine-state validation.
    states = {item['key']: item for item in components}
    # A room is a fixed raster: never silently depict unequipped environmental
    # parts, nor reinterpret arbitrary mixed legacy levels as the fifth room.
    environment=next((s for s in REGISTRIES if all(item['active_level'] in (s*2-1,s*2) for item in states.values())),None)
    if environment is None:return None
    if any(not item['equipped'] for key, item in states.items() if key not in CORE_KEYS):
        return None
    selected = {'base'}
    files,order,revision=REGISTRIES[environment]
    for key in CORE_KEYS:
        state = states[key]
        if not state['equipped']:
            continue
        upgraded = state['active_level'] == environment*2
        selected.add(key + ('-upgraded' if upgraded else '-basic'))
    seen=set()
    for holding in accessories:
        number=holding.get('number');item=BY_NUMBER.get(number)
        if type(number) is not int or item is None or number in seen or type(holding.get('equipped')) is not bool:
            raise ValueError('Invalid workstation accessory snapshot')
        seen.add(number)
        if holding['equipped'] and item['environment']==environment:selected.add(item['key'])
    return {'revision': revision, 'environment': environment, 'width': ART_SIZE[0], 'height': ART_SIZE[1],
            'layers': [{'key': key, 'filename': files[key]} for key in visible_layers(selected)]}


def captured_scene(progression):
    """Rebuild trusted filenames from a captured snapshot; support older jobs."""
    legacy = component_scene(progression['components'])
    marker = progression.get('accessory_scene')
    if marker is None:
        return legacy, False
    scene = accessory_scene(progression['components'],progression.get('accessories',()))
    if scene is None or not isinstance(marker, dict) or marker.get('revision') != scene['revision']:
        raise ValueError('Incompatible stage-five workstation snapshot')
    return scene, True
