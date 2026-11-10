from pathlib import Path

from PIL import Image

from dzmm_bot.core.workstation import WORKSTATION_LAYERS
from dzmm_bot.core.workstation_art import ART_SIZE
from dzmm_bot.core.workstation_stage5 import captured_scene
from .workstation_status import draw_stage5_status


def _save_image(canvas, output_path, preview_size):
    if preview_size:
        preview = canvas.convert('RGB')
        preview.thumbnail(preview_size, Image.Resampling.LANCZOS)
        preview.save(output_path, format='WEBP', quality=88, method=4)
    else:
        canvas.save(output_path, format='PNG')


def render_workstation_image(payload, output_path, *, preview_size=None):
    assets = Path(__file__).resolve().parents[1] / "admin" / "static" / "workstation"
    progression = payload.get("progression")
    if progression is not None:
        # Rebuild trusted paths from captured component state, never from supplied filenames.
        scene, stage5 = captured_scene(progression)
        canvas = Image.new("RGBA", ART_SIZE)
        for item in scene["layers"]:
            with Image.open(assets / item["filename"]) as layer:
                if layer.size != ART_SIZE:
                    raise ValueError("Workstation layer dimensions do not match")
                canvas.alpha_composite(layer.convert("RGBA"))
        if stage5:
            draw_stage5_status(canvas, payload,scene['environment'])
        _save_image(canvas, output_path, preview_size)
        return
    # Retain compatibility for queued snapshots from before progression existed.
    with Image.open(assets / "core-base.png") as base:
        canvas = base.convert("RGBA")
    keys = list(dict.fromkeys(item["asset_key"] for item in payload["equipped"]))
    for key in sorted(keys, key=lambda value: WORKSTATION_LAYERS.get(value, 0)):
        if key not in WORKSTATION_LAYERS:
            raise ValueError("Unknown workstation equipment asset")
        with Image.open(assets / f"{key}-layer.png") as layer:
            if layer.size != canvas.size:
                raise ValueError("Workstation layer dimensions do not match")
            canvas.alpha_composite(layer.convert("RGBA"))
    _save_image(canvas.convert("RGB"), output_path, preview_size)
