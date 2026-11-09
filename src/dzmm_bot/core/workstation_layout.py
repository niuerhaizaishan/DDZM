"""Authored desk space and shared layer rules for all workstation renderers.

Coordinates use the original 1536 x 1024 artwork, never CSS viewport pixels.
Raster transforms are applied once during asset construction. Ownership and
equipment state do not change when selecting or validating a layout.
"""
from dataclasses import dataclass


LAYOUT_VERSION = 1
LAYER_ORDER = (
    'base', 'desk-mat', 'computer-basic', 'computer-upgraded',
    'monitor-basic', 'monitor-upgraded', 'speakers', 'lightbar', 'lightbar-basic',
    'keyboard-basic', 'keyboard-upgraded', 'mouse-basic', 'mouse-upgraded',
    'console', 'handheld', 'pen-display', 'headphones', 'microphone', 'desk-clock',
)


@dataclass(frozen=True)
class SpriteSlot:
    region: tuple[int, int, int, int]
    position: tuple[int, int]
    size: tuple[int, int]


@dataclass(frozen=True)
class RasterFit:
    scale: float
    anchor: tuple[int, int]
    offset: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class EnvironmentLayout:
    surfaces: tuple[tuple[tuple[int, int], ...], ...]
    speakers: tuple[SpriteSlot, ...] = ()
    fits: tuple[tuple[str, RasterFit], ...] = ()
    props: tuple[tuple[str, SpriteSlot], ...] = ()


def _surfaces(front, slope, *, side=False, corner=False):
    edge = ((1000, 571), (840, 552), (0, front)) if corner else ((1000, round(front-slope*1000)), (0, front))
    main = ((0, 540), (700, 430), (1000, 490), *edge)
    if not side:
        return (main,)
    # Trace the visible wooden edge, including each room's angled right return.
    if corner:
        wing = ((900, 470), (1535, 510), (1535, 585), (1450, 625), (1140, 590), (900, 550))
    elif front == 673:
        wing = ((900, 475), (1535, 510), (1535, 550), (1470, 579), (1100, 550), (900, 540))
    else:
        wing = ((900, 475), (1535, 510), (1535, 575), (1510, 583), (1100, 550), (900, 540))
    return (main, wing)


# Both halves keep their source material, perspective and contact shadows.
# These slots reserve actual space against BOTH variants of every core device.
LAYOUTS = {
    1: EnvironmentLayout(_surfaces(732, .2)),
    2: EnvironmentLayout(_surfaces(706, .186667), (
        SpriteSlot((0, 0, 550, 1024), (339, 507), (34, 45)),
        SpriteSlot((550, 0, 1536, 1024), (674, 498), (40, 45)),
    ), props=(('desk-clock', SpriteSlot((0, 0, 1536, 1024), (335, 554), (67, 42))),)),
    3: EnvironmentLayout(_surfaces(688, 1/6, side=True), (
        SpriteSlot((0, 0, 550, 1024), (349, 520), (50, 56)),
        SpriteSlot((550, 0, 1536, 1024), (696, 488), (47, 48)),
    )),
    4: EnvironmentLayout(_surfaces(673, .145, side=True), (
        SpriteSlot((0, 0, 550, 1024), (351, 520), (38, 48)),
        SpriteSlot((550, 0, 1536, 1024), (742, 498), (38, 48)),
    ), fits=(('headphones', RasterFit(1, (0, 0), (-24, 0))),),
        props=(('console', SpriteSlot((0, 0, 1536, 1024), (1228, 520), (54, 30))),)),
    5: EnvironmentLayout(_surfaces(720, .2, side=True, corner=True), (
        SpriteSlot((0, 0, 550, 1024), (385, 496), (41, 48)),
        SpriteSlot((550, 0, 1536, 1024), (740, 500), (40, 48)),
    ), (
        *((key, RasterFit(.90, (500, 530), (-18, 0))) for key in
          ('monitor-basic', 'monitor-upgraded', 'lightbar', 'lightbar-basic')),
        *((key, RasterFit(.93, (850, 520), (16, 0))) for key in
          ('computer-basic', 'computer-upgraded')),
        *((key, RasterFit(.85, (410, 606))) for key in
          ('keyboard-basic', 'keyboard-upgraded')),
        ('console', RasterFit(.80, (308, 600))),
        ('pen-display', RasterFit(.90, (1162, 600), (0, -12))),
    )),
}


def ordered_layers(available):
    """Reject missing depth rules instead of silently losing a new sprite."""
    keys = set(available)
    if keys - set(LAYER_ORDER):
        raise ValueError('Workstation layer has no authored depth rule')
    return [key for key in LAYER_ORDER if key in keys]


def visible_layers(selected):
    """Resolve mounted equipment against the support actually being shown."""
    selected = set(selected)
    if 'lightbar' in selected:
        selected.remove('lightbar')
        if 'monitor-upgraded' in selected:
            selected.add('lightbar')
        elif 'monitor-basic' in selected:
            selected.add('lightbar-basic')
    return ordered_layers(selected)
