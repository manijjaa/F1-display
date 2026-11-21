"""High-quality track drawing for the 1-bit/6-ink e-paper canvas.

Raw circuit outlines are coarse polylines (Bahrain: ~94 points for 5.4 km), and
Pillow's native wide lines are jagged with uneven thickness on diagonals.
Here the outline is smoothed with a centripetal Catmull-Rom spline, stroked at
8x resolution, averaged down to pixel coverage and thresholded at 50 %, so the
final pixels follow the true geometry with an even stroke.
"""
import math

from PIL import Image, ImageDraw, ImageFilter

SS = 8  # supersampling factor


def smooth_closed(pts, step=0.6, alpha=0.5):
    """Centripetal Catmull-Rom through all points of a closed loop, sampled every `step` px."""
    if math.dist(pts[0], pts[-1]) < 1e-6:
        pts = pts[:-1]
    n = len(pts)
    out = []

    def tj(ti, a, b):
        return ti + max(math.dist(a, b), 1e-6) ** alpha

    for i in range(n):
        p0, p1, p2, p3 = pts[(i - 1) % n], pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        t0 = 0.0
        t1 = tj(t0, p0, p1)
        t2 = tj(t1, p1, p2)
        t3 = tj(t2, p2, p3)
        m = max(2, int(math.dist(p1, p2) / step))
        for k in range(m):
            t = t1 + (t2 - t1) * k / m

            def mix(a, b, ta, tb):
                wa, wb = (tb - t) / (tb - ta), (t - ta) / (tb - ta)
                return (a[0] * wa + b[0] * wb, a[1] * wa + b[1] * wb)

            a1, a2, a3 = mix(p0, p1, t0, t1), mix(p1, p2, t1, t2), mix(p2, p3, t2, t3)
            b1, b2 = mix(a1, a2, t0, t2), mix(a2, a3, t1, t3)
            out.append(mix(b1, b2, t1, t2))
    return out


class Coverage:
    """Draw shapes at SS x resolution inside a box, then read 1x coverage back."""

    def __init__(self, box):
        self.x0, self.y0, x1, y1 = (int(math.floor(box[0])), int(math.floor(box[1])),
                                    int(math.ceil(box[2])), int(math.ceil(box[3])))
        self.w, self.h = x1 - self.x0, y1 - self.y0
        self.big = Image.new("L", (self.w * SS, self.h * SS), 0)
        self.d = ImageDraw.Draw(self.big)

    def _p(self, p):
        return ((p[0] - self.x0) * SS, (p[1] - self.y0) * SS)

    def polyline(self, pts, width, closed=False, round_caps=True):
        q = [self._p(p) for p in pts]
        if closed:
            q = q + q[:2]
        self.d.line(q, fill=255, width=max(1, int(round(width * SS))), joint="curve")
        if round_caps and not closed:
            r = width * SS / 2
            for c in (q[0], q[-1]):
                self.d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=255)

    def disc(self, c, r):
        c = self._p(c)
        r *= SS
        self.d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=255)

    def paint(self, img, ink, threshold=128, blur=0.55):
        small = self.big.resize((self.w, self.h), Image.BOX)
        if blur:
            small = small.filter(ImageFilter.GaussianBlur(blur))  # calmer edges, no speckle
        px, mp = img.load(), small.load()
        W, H = img.size
        for y in range(self.h):
            for x in range(self.w):
                if mp[x, y] >= threshold:
                    X, Y = self.x0 + x, self.y0 + y
                    if 0 <= X < W and 0 <= Y < H:
                        px[X, Y] = ink


def draw_track_hq(img, pts, black, white, red, style="solid", width=7.0):
    """pts: projected 1x points (closed loop, first point = start/finish, in race direction)."""
    curve = smooth_closed(pts)
    xs = [p[0] for p in curve]
    ys = [p[1] for p in curve]
    box = (min(xs) - 30, min(ys) - 30, max(xs) + 30, max(ys) + 30)

    if style == "outlined":
        outer = Coverage(box)
        outer.polyline(curve, width + 3, closed=True)
        outer.paint(img, black)
        inner = Coverage(box)
        inner.polyline(curve, width - 2.5, closed=True)
        inner.paint(img, white)
    else:
        c = Coverage(box)
        c.polyline(curve, width, closed=True)
        c.paint(img, black)

    # start/finish bar across the track (white halo, then red), plus a small direction chevron
    p0 = pts[0]
    j = 1
    while math.dist(pts[j], p0) < 3 and j < len(pts) - 1:
        j += 1
    vx, vy = pts[j][0] - p0[0], pts[j][1] - p0[1]
    n = math.hypot(vx, vy) or 1.0
    vx, vy = vx / n, vy / n
    nx, ny = -vy, vx
    half = width / 2 + 4
    bar = [(p0[0] - nx * half, p0[1] - ny * half), (p0[0] + nx * half, p0[1] + ny * half)]
    rb = Coverage(box)
    rb.polyline(bar, 3.2)
    rb.paint(img, red)

    # chevron on the outside of the loop, pointing in race direction
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    side = 1 if (nx * (p0[0] - cx) + ny * (p0[1] - cy)) > 0 else -1
    o = (p0[0] + nx * side * (half + 10), p0[1] + ny * side * (half + 10))
    tip = (o[0] + vx * 4.5, o[1] + vy * 4.5)
    arm1 = (o[0] - vx * 3.5 + nx * 5, o[1] - vy * 3.5 + ny * 5)
    arm2 = (o[0] - vx * 3.5 - nx * 5, o[1] - vy * 3.5 - ny * 5)
    ch = Coverage(box)
    ch.polyline([arm1, tip, arm2], 2.6)
    ch.paint(img, red)
