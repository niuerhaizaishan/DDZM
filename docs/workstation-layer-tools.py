import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


DOCS = Path(__file__).resolve().parent
ASSETS = DOCS / "assets" / "workstation"
CONFIG = ASSETS / "core-extraction.json"


def extract_layers():
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    source = Image.open(DOCS / "assets" / "workstation-scene.png").convert("RGBA")
    canvas_size = (config["canvas"]["width"], config["canvas"]["height"])
    if source.size != canvas_size:
        raise ValueError("原图尺寸与画布配置不一致")
    layer_directory = ASSETS / "layers"
    layer_directory.mkdir(parents=True, exist_ok=True)
    removal = Image.new("L", canvas_size, 0)
    equipment_mask = Image.new("L", canvas_size, 0)
    manifest = {
        "canvas": config["canvas"],
        "base": "./assets/workstation/core-base.png",
        "reference": "./assets/workstation-scene.png",
        "scope": "仅拆分 10 件核心装备，桌面上的其他物品保留原样",
        "layers": [],
    }
    previews = []
    for item in config["items"]:
        mask = Image.new("L", (canvas_size[0] * 3, canvas_size[1] * 3), 0)
        drawing = ImageDraw.Draw(mask)
        for polygon in [item["polygon"], *item["extraPolygons"]]:
            drawing.polygon([(point[0] * 3, point[1] * 3) for point in polygon], fill=255)
        mask = mask.resize(canvas_size, Image.Resampling.LANCZOS)
        equipment_mask = ImageChops.lighter(equipment_mask, mask)
        layer = source.copy()
        layer.putalpha(mask)
        bounds = mask.getbbox()
        thumbnail = layer.crop(bounds)
        layer_path = layer_directory / f"{item['id']}-layer.png"
        thumbnail_path = layer_directory / f"{item['id']}.png"
        layer.save(layer_path)
        thumbnail.save(thumbnail_path)
        expanded = mask.filter(ImageFilter.MaxFilter(25))
        removal = ImageChops.lighter(removal, expanded)
        manifest["layers"].append({
            "id": item["id"],
            "name": item["name"],
            "asset": f"./assets/workstation/layers/{item['id']}-layer.png",
            "thumbnail": f"./assets/workstation/layers/{item['id']}.png",
            "bounds": list(bounds),
            "zIndex": item["zIndex"],
            "defaultEquipped": True,
            "method": "从原图可见区域按轮廓提取，保留原有透视与像素",
        })
        previews.append((item["name"], thumbnail))
    edit_mask = Image.new("RGBA", canvas_size, (255, 255, 255, 255))
    edit_mask.putalpha(Image.eval(removal, lambda alpha: 255 - alpha))
    edit_mask.save(ASSETS / "core-edit-mask.png")
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    contact_sheet(previews)
    base_path = ASSETS / "core-base.png"
    repair_path = ASSETS / "core-repair-source.png"
    if repair_path.exists():
        repair = Image.open(repair_path).convert("RGBA")
        if repair.size != canvas_size:
            raise ValueError("修复图尺寸与画布配置不一致")
        base = Image.composite(repair, source, equipment_mask)
        base.save(base_path)
        equipment_mask.save(ASSETS / "core-repair-mask.png")
    if base_path.exists():
        base = Image.open(base_path).convert("RGBA")
        if base.size != canvas_size:
            raise ValueError("底图尺寸与画布配置不一致")
        composite = base.copy()
        for item in sorted(manifest["layers"], key=lambda entry: entry["zIndex"]):
            composite = Image.alpha_composite(composite, Image.open(DOCS / item["asset"].removeprefix("./")).convert("RGBA"))
        composite.save(ASSETS / "core-composite-preview.png")
    print(f"已提取 {len(previews)} 件透明装备；画布 {source.width} × {source.height}")


def contact_sheet(previews):
    cell_width, cell_height = 320, 220
    sheet = Image.new("RGB", (cell_width * 5, cell_height * 2), "#ece7df")
    drawing = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 18)
    for index, (name, thumbnail) in enumerate(previews):
        origin_x = (index % 5) * cell_width
        origin_y = (index // 5) * cell_height
        for column in range(0, cell_width, 16):
            for row in range(0, cell_height - 40, 16):
                if ((column // 16) + (row // 16)) % 2:
                    drawing.rectangle((origin_x + column, origin_y + row, origin_x + column + 15, origin_y + row + 15), fill="#d8d4ce")
        image = thumbnail.copy()
        image.thumbnail((cell_width - 28, cell_height - 66), Image.Resampling.LANCZOS)
        sheet.paste(image, (origin_x + (cell_width - image.width) // 2, origin_y + (cell_height - 40 - image.height) // 2), image)
        drawing.text((origin_x + 16, origin_y + cell_height - 32), name, font=font, fill="#263238")
    sheet.save(ASSETS / "core-equipment-sheet.png")


if __name__ == "__main__":
    extract_layers()
