from pathlib import Path

import pytest
from PIL import Image, ImageChops

from dzmm_bot.browser.workstation_image import render_workstation_image
from dzmm_bot.core.workstation_art import ART_ORDER, asset_filename


ASSETS = Path(__file__).resolve().parents[2] / "src/dzmm_bot/admin/static/workstation"


def test_empty_scene_preserves_all_base_objects(tmp_path):
    path = tmp_path / "empty.png"
    render_workstation_image({"equipped": []}, path)
    with Image.open(path) as actual, Image.open(ASSETS / "core-base.png") as base:
        assert actual.size == (1536, 1024)
        assert ImageChops.difference(actual.convert("RGB"), base.convert("RGB")).getbbox() is None


def test_equipment_layers_use_the_same_order_as_the_webpage(tmp_path):
    keys = ["monitor-main", "monitor-left", "keyboard", "chair"]
    path = tmp_path / "equipped.png"
    render_workstation_image({"equipped": [{"asset_key": key} for key in keys]}, path)
    with Image.open(ASSETS / "core-base.png") as base:
        expected = base.convert("RGBA")
    for key in ["monitor-left", "monitor-main", "keyboard", "chair"]:
        with Image.open(ASSETS / f"{key}-layer.png") as layer:
            expected.alpha_composite(layer.convert("RGBA"))
    with Image.open(path) as actual:
        assert ImageChops.difference(actual.convert("RGB"), expected.convert("RGB")).getbbox() is None


def test_untrusted_asset_paths_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown"):
        render_workstation_image({"equipped": [{"asset_key": "../../other"}]}, tmp_path / "invalid.png")


def growth_components(level=1):
    return [{"key": key, "active_level": level, "equipped": True} for key in ART_ORDER]


@pytest.mark.parametrize("level", [1, 5, 10])
def test_growth_art_uses_nine_level_layers_and_preserves_alpha(tmp_path, level):
    output = tmp_path / 'growth.png'
    # Old equipment and supplied paths must never leak into a growth composite.
    render_workstation_image({"equipped": [{"asset_key": "../../ignored"}],
        "progression": {"components": growth_components(level), "scene": {"layers": [{"filename": "../../ignored"}]}}}, output)
    expected = Image.new('RGBA', (1536, 1024))
    for key in ['floor', 'location', 'desk', 'monitor', 'computer', 'keyboard', 'mouse', 'chair', 'plant']:
        with Image.open(ASSETS / asset_filename(key, level)) as layer:
            expected.alpha_composite(layer)
    with Image.open(output) as actual:
        assert actual.mode == 'RGBA' and actual.size == (1536, 1024)
        assert actual.tobytes() == expected.tobytes()


def test_growth_mixed_levels_and_all_unequipped(tmp_path):
    components = growth_components()
    for index, component in enumerate(components):
        component['active_level'] = index + 1
        component['equipped'] = component['key'] in {'desk', 'computer'}
    output = tmp_path / 'mixed.png'
    render_workstation_image({'progression': {'components': components}}, output)
    expected = Image.new('RGBA', (1536, 1024))
    for component in components:
        if component['equipped']:
            with Image.open(ASSETS / asset_filename(component['key'], component['active_level'])) as layer:
                expected.alpha_composite(layer)
    with Image.open(output) as actual:
        assert actual.tobytes() == expected.tobytes()
    for component in components:
        component['equipped'] = False
    render_workstation_image({'progression': {'components': components}}, output)
    with Image.open(output) as actual:
        assert actual.getchannel('A').getextrema() == (0, 0)


@pytest.mark.parametrize('change', ['path', 'level', 'duplicate', 'missing'])
def test_invalid_growth_states_do_not_fall_back_to_legacy_art(tmp_path, change):
    components = growth_components()
    if change == 'path': components[0]['key'] = '../../secret'
    if change == 'level': components[0]['active_level'] = 11
    if change == 'duplicate': components.append(dict(components[0]))
    if change == 'missing': components.pop()
    with pytest.raises(ValueError):
        render_workstation_image({'equipped': [], 'progression': {'components': components}}, tmp_path / 'invalid.png')


def test_stage5_rebuilds_assets_ignores_supplied_paths_and_bakes_owner_status(tmp_path):
    from dzmm_bot.core.workstation_stage5 import accessory_scene
    components = growth_components(10)
    scene=accessory_scene(components)
    payload={'display_name':'糯糯','progression':{'components':components,
        'accessory_scene':{'revision':scene['revision'],'layers':[{'filename':'../../secret'}]}}}
    output=tmp_path/'stage5.png'; render_workstation_image(payload,output)
    expected=Image.new('RGBA',(1536,1024))
    for item in scene['layers']:
        with Image.open(ASSETS/item['filename']) as im: expected.alpha_composite(im)
    with Image.open(output) as im:
        diff=ImageChops.difference(im.convert('RGB'),expected.convert('RGB'))
        bounds=diff.getbbox()
        assert bounds and bounds[0]>=1114 and bounds[1]>=42 and bounds[2]<=1495 and bounds[3]<=275
        original=im.copy()
    payload['display_name']='小小糯'
    render_workstation_image(payload,output)
    with Image.open(output) as im:
        assert ImageChops.difference(original.convert('RGB'),im.convert('RGB')).getbbox() is not None


@pytest.mark.parametrize('change',['unsupported-level','unequipped-environment','revision','marker-type'])
def test_stage5_incompatible_markers_cannot_select_a_room(tmp_path,change):
    from dzmm_bot.core.workstation_stage5 import accessory_scene
    components=growth_components(10); marker=accessory_scene(components)
    if change=='unsupported-level': components[0]['active_level']=1
    if change=='unequipped-environment': components[0]['equipped']=False
    if change=='revision': marker['revision']='../../secret'
    if change=='marker-type': marker=True
    with pytest.raises(ValueError,match='Incompatible'):
        render_workstation_image({'display_name':'糯糯','progression':{'components':components,'accessory_scene':marker}},tmp_path/'bad.png')
