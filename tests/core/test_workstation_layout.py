"""Regress real collision cases and the renderer's shared selection rules."""
from itertools import product
from pathlib import Path
import sys

from PIL import Image, ImageDraw
import pytest

from dzmm_bot.core.workstation_art import ART_ORDER
from dzmm_bot.core.workstation_accessories import ACCESSORIES
from dzmm_bot.core.workstation_layout import ordered_layers
from dzmm_bot.core.workstation_stage5 import REGISTRIES, accessory_scene

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from workstation_layout_tools import validate_layers, validate_registry_assets


def test_all_current_rasters_pass_contact_and_collision_gate():
    reports = validate_registry_assets()
    assert len(reports) == 5
    assert sum(row['pair_checks'] for row in reports) >= 300
    assert not any(row['problems'] for row in reports)


def test_validator_catches_floating_contact_and_real_footprint_collision():
    layers = {key: Image.new('RGBA', (1536, 1024)) for key in ('base','computer-basic','mouse-basic')}
    ImageDraw.Draw(layers['computer-basic']).rectangle((790,480,840,530),fill='white')
    ImageDraw.Draw(layers['mouse-basic']).rectangle((805,520,850,540),fill='white')
    assert any('footprints intersect' in error for error in validate_layers(2,layers)['problems'])
    layers['computer-basic'] = Image.new('RGBA',(1536,1024))
    ImageDraw.Draw(layers['computer-basic']).rectangle((400,200,450,260),fill='white')
    assert any('contact outside desk' in error for error in validate_layers(2,layers)['problems'])


def test_validator_catches_screen_occlusion_even_when_feet_do_not_collide():
    layers = {key: Image.new('RGBA',(1536,1024)) for key in ('base','monitor-basic','speakers')}
    ImageDraw.Draw(layers['monitor-basic']).rectangle((400,350,650,490),fill='white')
    ImageDraw.Draw(layers['monitor-basic']).rectangle((510,490,530,550),fill='white')
    ImageDraw.Draw(layers['speakers']).rectangle((420,460,460,540),fill='white')
    assert 'speakers/monitor-basic: forbidden visible overlap' in validate_layers(2,layers)['problems']


def test_new_sprites_require_an_explicit_depth_rule():
    with pytest.raises(ValueError,match='depth rule'):
        ordered_layers({'base','unreviewed-prop'})


def test_validator_protects_foreground_chair_from_moved_equipment():
    from dzmm_bot.core.workstation_layout_obstacles import PROTECTED_POLYGONS
    chair = dict(PROTECTED_POLYGONS[5])['chair']
    layers = {key: Image.new('RGBA',(1536,1024)) for key in ('base','computer-basic')}
    ImageDraw.Draw(layers['computer-basic']).polygon(chair,fill='white')
    assert 'computer-basic: covers protected room object' in validate_layers(5,layers)['problems']


@pytest.mark.parametrize('environment',range(1,6))
def test_every_accessory_subset_and_visual_core_state_uses_shared_order(environment):
    catalog=[item for item in ACCESSORIES if item['environment']==environment]
    files,_,_=REGISTRIES[environment]
    for state in product(('basic','upgraded','off'),repeat=4):
        components=[{'key':key,'active_level':environment*2,'equipped':True} for key in ART_ORDER]
        for key,variant in zip(('computer','monitor','keyboard','mouse'),state):
            row=next(row for row in components if row['key']==key)
            row.update(active_level=environment*2-(variant=='basic'),equipped=variant!='off')
        for bits in product((False,True),repeat=len(catalog)):
            holdings=[{'number':item['number'],'equipped':bit} for item,bit in zip(catalog,bits)]
            scene=accessory_scene(components,holdings)
            keys=[row['key'] for row in scene['layers']]
            assert keys==ordered_layers(keys) and len(keys)==len(set(keys))
            assert all(row['filename']==files[row['key']] for row in scene['layers'])
            expected={item['key'] for item,bit in zip(catalog,bits) if bit}
            actual=set(keys)-{'base',*(key+'-'+variant for key,variant in zip(('computer','monitor','keyboard','mouse'),state) if variant!='off')}
            if 'lightbar' in expected and state[1]!='upgraded':
                expected.remove('lightbar')
                if state[1]=='basic':expected.add('lightbar-basic')
            assert actual==expected
