"""Guard the reviewed mouse contrast and tower-computer descriptions."""
from pathlib import Path
import pytest
from PIL import Image,ImageStat
from dzmm_bot.core.workstation_stage5 import REGISTRIES
from dzmm_bot.core.workstation_catalog import CATEGORIES


@pytest.mark.parametrize('room',[2,5])
def test_mouse_upgrade_has_visible_dark_shell_contrast(room):
    assets=Path(__file__).resolve().parents[2]/'src/dzmm_bot/admin/static/workstation'
    means=[]
    for variant in ['basic','upgraded']:
        image=Image.open(assets/REGISTRIES[room][0][f'mouse-{variant}']).convert('RGBA')
        mask=image.getchannel('A').point(lambda a:255 if a>220 else 0)
        means.append(ImageStat.Stat(image.convert('L'),mask).mean[0])
    assert means[1] < means[0] * .85


def test_computer_copy_matches_tower_art():
    computer=next(c for c in CATEGORIES if c['key']=='computer')
    assert all('笔记本' not in name for name in computer['names'])
    assert all('笔记本' not in desc and '移动工作站' not in desc for desc in computer['descriptions'])
