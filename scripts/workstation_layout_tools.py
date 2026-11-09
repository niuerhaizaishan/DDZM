"""Build and release checks for the shared authored workstation layout."""
from itertools import combinations
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

from dzmm_bot.core.workstation_layout import LAYOUTS, ordered_layers
from dzmm_bot.core.workstation_layout_obstacles import PROTECTED_POLYGONS


SIZE = (1536, 1024)
OPAQUE_THRESHOLD = 170
FLAT = {'keyboard-basic', 'keyboard-upgraded', 'mouse-basic', 'mouse-upgraded',
        'console', 'handheld', 'pen-display', 'desk-clock'}
MOUNTED = {'lightbar', 'lightbar-basic'}


def opaque(image):
    return image.getchannel('A').point(lambda value: 255 if value >= OPAQUE_THRESHOLD else 0)


def transform(image, fit):
    ax, ay = fit.anchor
    dx, dy = fit.offset
    scale = fit.scale
    return image.transform(SIZE, Image.Transform.AFFINE,
                           (1/scale, 0, ax-(ax+dx)/scale,
                            0, 1/scale, ay-(ay+dy)/scale), Image.Resampling.BICUBIC)


def foreground_mask(environment):
    mask = Image.new('L', SIZE)
    for _, polygon in PROTECTED_POLYGONS[environment]:
        ImageDraw.Draw(mask).polygon(polygon, fill=255)
    return mask


def apply_layout(environment, layers):
    """Apply once to original extracted/fitted rasters, before content hashing."""
    spec = LAYOUTS[environment]
    fitted = dict(layers)
    for key, fit in spec.fits:
        fitted[key] = transform(fitted[key], fit)
    if spec.speakers:
        image = Image.new('RGBA', SIZE)
        for slot in spec.speakers:
            tile = layers['speakers'].crop(slot.region)
            bounds = tile.getbbox()
            if bounds is None:
                raise ValueError('Missing source speaker for authored slot')
            tile = tile.crop(bounds).resize(slot.size, Image.Resampling.LANCZOS)
            image.alpha_composite(tile, slot.position)
        fitted['speakers'] = image
    for key, slot in spec.props:
        tile = layers[key].crop(slot.region)
        bounds = tile.getbbox()
        if bounds is None:
            raise ValueError('Missing prop for authored slot')
        tile = tile.crop(bounds).resize(slot.size, Image.Resampling.LANCZOS)
        image = Image.new('RGBA', SIZE)
        image.alpha_composite(tile, slot.position)
        fitted[key] = image
    # Clipping happens AFTER every pose change. The original chair, lamp and
    # objects must stay in front even when a monitor or tower has moved.
    foreground = foreground_mask(environment)
    for key, image in fitted.items():
        if key != 'base':
            clipped = image.copy()
            clipped.putalpha(ImageChops.subtract(image.getchannel('A'), foreground))
            fitted[key] = clipped
    return fitted


def prepare_layout(environment, layers):
    fitted = apply_layout(environment, layers)
    report = validate_layers(environment, fitted)
    if report['problems']:
        raise ValueError(f'Workstation {environment} layout: {report["problems"]}')
    return fitted, ordered_layers(fitted)


def footprint(key, image):
    """Use desk contact, rather than a tall object's entire screen silhouette."""
    body = opaque(image)
    if key in FLAT:
        return body
    result = Image.new('L', SIZE)
    regions = ((0, 0, 550, 1024), (550, 0, 1536, 1024)) if key == 'speakers' else ((0, 0, *SIZE),)
    for region in regions:
        part = body.crop(region)
        bounds = part.getbbox()
        if bounds:
            x0, _, x1, y1 = bounds
            band = part.crop((x0, max(0, y1-12), x1, y1))
            result.paste(band, (region[0]+x0, region[1]+max(0, y1-12)))
    return result


def validate_layers(environment, layers):
    """Pair checks cover every possible subset, including full ownership."""
    spec = LAYOUTS[environment]
    order = ordered_layers(layers)
    problems = []
    foreground = foreground_mask(environment)
    surface = Image.new('L', SIZE)
    for polygon in spec.surfaces:
        ImageDraw.Draw(surface).polygon(polygon, fill=255)
    feet = {}
    for key, image in layers.items():
        if image.size != SIZE or image.mode != 'RGBA':
            problems.append(f'{key}: invalid raster dimensions or mode')
            continue
        if key != 'base' and not image.getchannel('A').getbbox():
            problems.append(f'{key}: empty equipment layer')
        if key != 'base' and ImageChops.multiply(image.getchannel('A'), foreground).getbbox():
            problems.append(f'{key}: covers protected room object')
        if key == 'base' or key == 'desk-mat' or key in MOUNTED:
            continue
        feet[key] = footprint(key, image)
        if ImageChops.subtract(feet[key], surface).getbbox():
            problems.append(f'{key}: contact outside desk surface')
    pair_checks = 0
    for first, second in combinations(feet, 2):
        # Two variants of one device are mutually exclusive.
        if first.rsplit('-', 1)[0] == second.rsplit('-', 1)[0] and first.endswith(('basic', 'upgraded')) and second.endswith(('basic', 'upgraded')):
            continue
        pair_checks += 1
        if ImageChops.multiply(feet[first], feet[second]).getbbox():
            problems.append(f'{first}/{second}: footprints intersect')
    if 'speakers' in layers:
        speaker = opaque(layers['speakers'])
        for key in ('monitor-basic','monitor-upgraded','computer-basic','computer-upgraded','headphones','desk-clock'):
            if key in layers and ImageChops.multiply(speaker, opaque(layers[key])).getbbox():
                problems.append(f'speakers/{key}: forbidden visible overlap')
    return {'environment': environment, 'pair_checks': pair_checks, 'layer_order': order,
            'problems': problems}


def validate_registry_assets(assets=None):
    from dzmm_bot.core.workstation_stage5 import REGISTRIES
    if assets is None:
        assets = Path(__file__).resolve().parents[1] / 'src/dzmm_bot/admin/static/workstation'
    reports = []
    for environment, (files, _, _) in REGISTRIES.items():
        layers = {key: Image.open(assets / name).convert('RGBA') for key, name in files.items()}
        reports.append(validate_layers(environment, layers))
    errors = [(row['environment'], issue) for row in reports for issue in row['problems']]
    if errors:
        raise ValueError(f'Workstation layout validation failed: {errors}')
    return reports
