"""Weather icons in the same outlined style as the track (drawn here, ~24 px, 2 px strokes).

Kinds: sun, partly, cloud, rain, storm, fog, snow.
WMO weather codes (as used by Open-Meteo) map to kinds via `kind_for_wmo`.
"""
import math

from track import Coverage

STROKE = 2.0


def kind_for_wmo(code):
    if code == 0:
        return "sun"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloud"
    if code in (45, 48):
        return "fog"
    if code in (71, 73, 75, 77, 85, 86):
        return "snow"
    if code >= 95:
        return "storm"
    return "rain"  # drizzle, rain, showers (51-67, 80-82)


def _cloud(cov, cx, cy, s, inset):
    for (dx, dy, r) in ((-6.0, 2.0, 5.0), (0.5, -2.5, 7.0), (7.0, 2.0, 5.0)):
        cov.disc((cx + dx * s, cy + dy * s), r * s - inset)
    # flat-ish base: a capsule as thick as the side bumps, so the inner shape has no gaps
    cov.polyline([(cx - 6.0 * s, cy + 3.0 * s), (cx + 7.0 * s, cy + 3.0 * s)], 10.0 * s - 2 * inset)


def _draw_cloud(img, cx, cy, s, black, white):
    box = (cx - 16, cy - 14, cx + 16, cy + 12)
    outer = Coverage(box)
    _cloud(outer, cx, cy, s, 0.0)
    outer.paint(img, black, blur=0.3)
    inner = Coverage(box)
    _cloud(inner, cx, cy, s, STROKE)
    inner.paint(img, white, blur=0.3)


def _draw_sun(img, cx, cy, s, black, white):
    box = (cx - 16, cy - 16, cx + 16, cy + 16)
    ring = Coverage(box)
    ring.disc((cx, cy), 5.5 * s)
    ring.paint(img, black, blur=0.3)
    hole = Coverage(box)
    hole.disc((cx, cy), 5.5 * s - STROKE)
    hole.paint(img, white, blur=0.3)
    rays = Coverage(box)
    for k in range(8):
        a = math.pi / 4 * k
        rays.polyline([(cx + math.cos(a) * 8.5 * s, cy + math.sin(a) * 8.5 * s),
                       (cx + math.cos(a) * 11.0 * s, cy + math.sin(a) * 11.0 * s)], STROKE)
    rays.paint(img, black, blur=0.3)


def _lines(img, box, segments, black):
    c = Coverage(box)
    for seg in segments:
        c.polyline(seg, STROKE)
    c.paint(img, black, blur=0.3)


def draw_weather_icon(img, kind, cx, cy, black, white):
    """Icon roughly 24x24 px centred on (cx, cy)."""
    if kind == "sun":
        _draw_sun(img, cx, cy, 1.0, black, white)
    elif kind == "partly":
        _draw_sun(img, cx - 5, cy - 5, 0.72, black, white)
        _draw_cloud(img, cx + 3, cy + 3, 0.85, black, white)
    elif kind == "cloud":
        _draw_cloud(img, cx, cy + 1, 1.0, black, white)
    elif kind in ("rain", "storm", "snow"):
        _draw_cloud(img, cx, cy - 3, 0.95, black, white)
        box = (cx - 14, cy, cx + 14, cy + 18)
        if kind == "rain":
            _lines(img, box, [[(x, cy + 7), (x - 2, cy + 11)] for x in (cx - 5, cx + 1, cx + 7)], black)
        elif kind == "storm":
            _lines(img, box, [[(cx + 2, cy + 6), (cx - 2, cy + 11), (cx + 2, cy + 11), (cx - 1, cy + 16)]], black)
        else:
            c = Coverage(box)
            for x in (cx - 5, cx + 1, cx + 7):
                c.disc((x, cy + 10), 1.6)
            c.paint(img, black, blur=0.3)
    elif kind == "fog":
        box = (cx - 14, cy - 10, cx + 14, cy + 10)
        _lines(img, box, [[(cx - 10, cy - 5), (cx + 10, cy - 5)],
                          [(cx - 7, cy), (cx + 7, cy)],
                          [(cx - 10, cy + 5), (cx + 10, cy + 5)]], black)
