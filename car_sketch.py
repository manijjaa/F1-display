"""Hand-drawn style racing car: generic modern F1 car in racing red with a sketchy ink outline.

Original drawing - no team badges, numbers or sponsor marks.
Sketch feel comes from: wobbly outlines (smooth noise along the stroke normal), two loose
passes per outline, hand-drawn circles that overshoot, a slightly offset red fill, and
speed lines behind the car. Coordinates: (x from the rear, h above ground), ~140 units long.
"""
import math
import random

from track import Coverage

BODY = [
    (6, 3), (6, 12.5), (18, 14.5), (34, 17.5), (45, 22.5), (49.5, 25), (55, 25),
    (57.5, 21.5), (60, 20), (74, 18), (82, 15.5), (104, 11.3), (124, 7.3),
    (134.5, 5.4), (136, 3.8), (124, 3.0), (104, 2.6), (6, 2.6),
]
REAR_WING = [(1, 8.5), (4.6, 8.5), (4.6, 20.3), (16.8, 20.3), (16.8, 25.6), (1, 25.6)]
FRONT_WING = [(116.5, 0.8), (141.5, 0.8), (141.5, 7.6), (138.8, 7.6), (138.8, 4.1), (116.5, 3.5)]
HALO = [(57.5, 21.5), (63, 24.4), (69.5, 23.7), (76.5, 17.6)]
SIDEPOD = [(36, 9.5), (52, 11.5), (74, 12.0)]
HELMET, HELMET_R = (64.5, 21.0), 3.4
WHEELS, R = ((22, 9), (112, 9)), 9.0


def _dense(points, closed, step):
    pts = list(points) + ([points[0]] if closed else [])
    out = []
    for a, b in zip(pts, pts[1:]):
        n = max(1, int(math.dist(a, b) / step))
        out += [(a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n) for k in range(n)]
    out.append(pts[-1])
    return out


def _wobble(points, rnd, amp, step=1.5, period=6, closed=False, overshoot=0.0):
    """Offset a dense path along its normal by smooth random noise (cosine-interpolated)."""
    d = _dense(points, closed, step)
    if overshoot and len(d) > 2:  # let the pen run on a little past the end
        (ax, ay), (bx, by) = d[-2], d[-1]
        L = math.hypot(bx - ax, by - ay) or 1
        d.append((bx + (bx - ax) / L * overshoot, by + (by - ay) / L * overshoot))
    ctrl = [rnd.uniform(-amp, amp) for _ in range(len(d) // period + 3)]
    out = []
    for i, p in enumerate(d):
        t = i / period
        i0 = int(t)
        f = (1 - math.cos((t - i0) * math.pi)) / 2
        off = ctrl[i0] * (1 - f) + ctrl[i0 + 1] * f
        a, b = d[max(i - 1, 0)], d[min(i + 1, len(d) - 1)]
        nx, ny = -(b[1] - a[1]), b[0] - a[0]
        L = math.hypot(nx, ny) or 1
        out.append((p[0] + nx / L * off, p[1] + ny / L * off))
    return out


def _sketch_circle(c, r, rnd, amp=0.35, turns=1.12):
    n = max(24, int(2 * math.pi * r * turns / 1.2))
    start = rnd.uniform(0, 2 * math.pi)
    ctrl = [rnd.uniform(-amp, amp) for _ in range(n // 6 + 3)]
    pts = []
    for i in range(n + 1):
        t = i / 6
        i0 = int(t)
        f = (1 - math.cos((t - i0) * math.pi)) / 2
        rr = r + ctrl[i0] * (1 - f) + ctrl[i0 + 1] * f + 0.5 * i / n  # slight spiral
        a = start + 2 * math.pi * turns * i / n
        pts.append((c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)))
    return pts


def draw_f1_car_sketch(img, x0, ground_y, black, white, red, s=1.0, seed=7):
    rnd = random.Random(seed)

    def P(p, dx=0.0, dy=0.0):
        return (x0 + (p[0] + dx) * s, ground_y - (p[1] + dy) * s)

    box = (x0 - 30 * s, ground_y - 34 * s, x0 + 148 * s, ground_y + 6 * s)

    def paint_poly(points, ink, dx=0.0, dy=0.0):
        c = Coverage(box)
        c.d.polygon([c._p(P(p, dx, dy)) for p in points], fill=255)
        c.paint(img, ink, threshold=120, blur=0)

    def ink_lines(paths, width, ink=black):
        c = Coverage(box)
        for path in paths:
            c.polyline(path, width * s, closed=False, round_caps=True)
        c.paint(img, ink, threshold=118, blur=0)

    # 1. red fill, nudged slightly off the outline like a quick marker colouring
    for poly in (BODY, REAR_WING, FRONT_WING):
        paint_poly(poly, red, dx=0.6, dy=-0.4)

    # 2. loose ink outlines: two passes with different wobble
    for amp, w in ((0.55, 1.5), (0.8, 1.1)):
        paths = []
        for poly in (BODY, REAR_WING, FRONT_WING):
            paths.append(_wobble([P(p) for p in poly], rnd, amp * s, closed=True, overshoot=2.5 * s))
        ink_lines(paths, w)

    # details: sidepod line, halo, helmet
    ink_lines([_wobble([P(p) for p in SIDEPOD], rnd, 0.5 * s, overshoot=1.5 * s)], 1.2)
    hel = Coverage(box)
    hel.disc(P(HELMET), HELMET_R * s)
    hel.paint(img, white, threshold=120, blur=0)
    ink_lines([_sketch_circle(P(HELMET), HELMET_R * s, rnd, amp=0.25 * s)], 1.3)
    ink_lines([_wobble([P(p) for p in HALO], rnd, 0.45 * s, overshoot=1.0 * s)], 1.9)

    # 3. wheels: knock out, black tyre, sketchy white rim, hub dot
    for c in WHEELS:
        k = Coverage(box)
        k.disc(P(c), (R + 1.4) * s)
        k.paint(img, white, threshold=120, blur=0)
        t = Coverage(box)
        t.disc(P(c, rnd.uniform(-0.3, 0.3), rnd.uniform(-0.3, 0.3)), R * s)
        t.paint(img, black, threshold=120, blur=0)
        ink_lines([_sketch_circle(P(c), (R - 3.6) * s, rnd, amp=0.3 * s)], 1.4, ink=white)
        hub = Coverage(box)
        hub.disc(P(c), 1.4 * s)
        hub.paint(img, white, threshold=120, blur=0)

    # 4. speed lines behind the car and a scribbled ground shadow
    speed = []
    for h, x_from, length in ((20, -5, 10), (14, -3, 15), (7, -6, 9)):
        a, b = P((x_from, h)), P((x_from - length, h + rnd.uniform(-0.6, 0.6)))
        speed.append(_wobble([a, b], rnd, 0.35 * s))
    ink_lines(speed, 1.3)
    shadow = _wobble([P((12, -1.6)), P((130, -1.6))], rnd, 0.5 * s)
    ink_lines([shadow], 1.2)
