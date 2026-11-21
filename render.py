#!/usr/bin/env python3
"""F1 e-ink race card renderer - locked design (v7, 21 Nov 2026).

Draws one 800x480 screen for a 7.3" E Ink Spectra 6 frame (Waveshare
ESP32-S3-PhotoPainter or Seeed XIAO EE04) using only the 6 inks (black, white,
red, yellow, blue, green). Text is drawn without anti-aliasing, so every pixel
is a real ink colour.

Layout
  top-left: hand-drawn red car   top-centre: race name + dates   top-right: days to race
  left: schedule (+ weather)     centre: outlined track          right: grid top 5, standings top 3

Folder layout (relative to this file)
  assets/fonts/AlbertSans.ttf    Albert Sans variable font (SIL OFL, see OFL.txt)
  assets/circuits/*.geojson      circuit outlines, bacinger/f1-circuits (MIT, see LICENSE.md)
  out/                           rendered images
  track.py, icons.py, car_sketch.py

Run `python render.py` to draw the sample Round 1 card into out/.
"""
import datetime as dt
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from track import draw_track_hq  # noqa: E402
from icons import draw_weather_icon, kind_for_wmo  # noqa: E402,F401
from car_sketch import draw_f1_car_sketch  # noqa: E402

FONT_FILE = ROOT / "assets" / "fonts" / "AlbertSans.ttf"
CIRCUITS = ROOT / "assets" / "circuits"
OUT = ROOT / "out"

W, H = 800, 480
BLACK, WHITE, RED, YELLOW, BLUE, GREEN = range(6)
DEVICE_RGB = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (255, 255, 0), (0, 0, 255), (0, 255, 0)]
# Approximate look of the real panel, only used for review previews.
PREVIEW_RGB = [(30, 31, 36), (238, 235, 226), (185, 40, 38), (226, 192, 30), (40, 74, 160), (46, 120, 74)]

LIGHT, REGULAR, MEDIUM, SEMIBOLD = 300, 400, 500, 600
M = 32            # outer margin
CX = W // 2
RIGHT = W - M
COL3 = 590        # right column

# Team colour dots from 6 inks: solid / dithered mix / ring
TEAM_DOT = {
    "MCL": ("mix", RED, YELLOW),     # papaya
    "FER": ("solid", RED),
    "RBR": ("solid", BLUE),
    "MER": ("mix", GREEN, BLUE),     # teal
    "AMR": ("solid", GREEN),
    "ALP": ("mix", RED, WHITE),      # pink
    "WIL": ("mix", BLUE, WHITE),     # light blue
    "RB":  ("ring", WHITE, BLUE),
    "HAA": ("ring", WHITE, RED),
    "AUD": ("mix", BLACK, WHITE),    # titanium grey
    "CAD": ("solid", BLACK),
}

_fonts = {}


def F(weight, size):
    key = (weight, size)
    if key not in _fonts:
        f = ImageFont.truetype(str(FONT_FILE), size)
        f.set_variation_by_axes([weight])
        _fonts[key] = f
    return _fonts[key]


def canvas():
    img = Image.new("P", (W, H), WHITE)
    pal = [v for rgb in DEVICE_RGB for v in rgb]
    img.putpalette(pal + [0] * (768 - len(pal)))
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    return img, d


def tw(d, s, f):
    return d.textlength(s, font=f)


def fit(d, s, weight, max_size, max_w, min_size=24):
    size = max_size
    while size > min_size and tw(d, s, F(weight, size)) > max_w:
        size -= 1
    return F(weight, size)


def label(d, xy, s, tracking=2.2, size=12):
    """Small letter-spaced caps label."""
    f = F(MEDIUM, size)
    x, y = xy
    for ch in s:
        d.text((x, y), ch, font=f, fill=BLACK, anchor="ls")
        x += tw(d, ch, f) + tracking


def team_dot(img, cx, cy, r, team):
    kind, *c = TEAM_DOT.get(team, ("solid", BLACK))
    px = img.load()
    for y in range(int(cy - r - 1), int(cy + r + 2)):
        for x in range(int(cx - r - 1), int(cx + r + 2)):
            dist = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            if dist > r:
                continue
            if kind == "solid":
                px[x, y] = c[0]
            elif kind == "mix":
                px[x, y] = c[0] if (x + y) % 2 == 0 else c[1]
            else:
                px[x, y] = c[1] if dist > r - 2 else c[0]


def driver_row(img, d, x, y, pos, code, team, value=None):
    d.text((x + 17, y), str(pos), font=F(REGULAR, 14), fill=BLACK, anchor="rs")
    team_dot(img, x + 28, y - 6, 5, team)
    d.text((x + 39, y), code, font=F(MEDIUM, 17), fill=BLACK, anchor="ls")
    if value is not None:
        d.text((RIGHT, y), str(value), font=F(REGULAR, 16), fill=BLACK, anchor="rs")


# ---------------------------------------------------------------- track
def load_track(circuit_file):
    data = json.loads((CIRCUITS / circuit_file).read_text())
    return data["features"][0]["geometry"]["coordinates"]


def track_coords(circuit_file, start=0, reverse=False):
    """Outline with the start/finish point first, running in race direction."""
    coords = load_track(circuit_file)
    # repeated points break the spline smoothing (keep the closing point as it is)
    coords = [c for i, c in enumerate(coords) if i == 0 or c != coords[i - 1] or i == len(coords) - 1]
    if not start and not reverse:
        return coords
    if coords[0] == coords[-1]:          # drop a repeated closing point
        coords = coords[:-1]
    coords = coords[start:] + coords[:start]
    if reverse:
        coords = coords[:1] + coords[1:][::-1]
    return coords


def project_centered(coords, box, rotate_deg=0.0):
    lat0 = sum(c[1] for c in coords) / len(coords)
    k = math.cos(math.radians(lat0))
    pts = [(c[0] * k, -c[1]) for c in coords]
    if rotate_deg:
        a = math.radians(rotate_deg)
        ca, sa = math.cos(a), math.sin(a)
        pts = [(x * ca - y * sa, x * sa + y * ca) for x, y in pts]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / (max(xs) - min(xs)), (y1 - y0) / (max(ys) - min(ys)))
    mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    bx, by = (x0 + x1) / 2, (y0 + y1) / 2
    return [(bx + (x - mx) * s, by + (y - my) * s) for x, y in pts]


# ---------------------------------------------------------------- columns
def draw_schedule(d, rows):
    """rows: (short name, day, time, is_race). Day groups get a little extra air."""
    y = 192
    prev_day = None
    for name, day, t, race in rows:
        if prev_day is not None:
            y += 30 + (10 if day != prev_day else 0)
        prev_day = day
        w = SEMIBOLD if race else REGULAR
        if race:
            d.ellipse([M, y - 10, M + 7, y - 3], fill=RED)
        d.text((M + 16, y), name, font=F(w, 17), fill=BLACK, anchor="ls")
        d.text((M + 104, y), day, font=F(w, 17), fill=BLACK, anchor="ls")
        d.text((M + 196, y), t, font=F(w, 17), fill=BLACK, anchor="rs")


def draw_weather(img, d, weather):
    """weather: [(day, kind, temp)] - empty until the race is inside the forecast window."""
    if not weather:
        return
    for i, (day, kind, temp) in enumerate(weather):
        x = M + i * 72
        draw_weather_icon(img, kind, x + 12, 404, BLACK, WHITE)
        d.text((x, 452), f"{day} {temp}°", font=F(REGULAR, 15), fill=BLACK, anchor="ls")


def draw_grid(img, d, grid, pending):
    label(d, (COL3, 166), "GRID")
    if not grid:
        d.text((COL3, 192), "After qualifying", font=F(REGULAR, 16), fill=BLACK, anchor="ls")
        d.text((COL3, 216), pending, font=F(MEDIUM, 16), fill=BLACK, anchor="ls")
        return
    for i, (code, team) in enumerate(grid[:5]):
        driver_row(img, d, COL3, 192 + i * 24, i + 1, code, team)


def draw_standings(img, d, standings):
    label(d, (COL3, 378), "STANDINGS")
    for i, (code, team, pts) in enumerate(standings[:3]):
        driver_row(img, d, COL3, 404 + i * 24, i + 1, code, team, pts)


def render(race, today, grid=None, standings=None):
    img, d = canvas()

    # top row
    draw_f1_car_sketch(img, 56, 90, BLACK, WHITE, RED, s=1.15)
    d.text((CX, 64), race["name"], font=fit(d, race["name"], LIGHT, 42, 350), fill=BLACK, anchor="ms")
    d.text((CX, 92), race["dates"], font=F(REGULAR, 18), fill=BLACK, anchor="ms")
    days = max(0, (race["race_date"] - today).days)
    if days == 0:
        d.text((RIGHT + 2, 66), "Today", font=F(LIGHT, 40), fill=BLACK, anchor="rs")
        d.text((RIGHT, 92), "race day", font=F(REGULAR, 16), fill=BLACK, anchor="rs")
    else:
        d.text((RIGHT + 2, 66), str(days), font=F(LIGHT, 46), fill=BLACK, anchor="rs")
        d.text((RIGHT, 92), "day" if days == 1 else "days", font=F(REGULAR, 16), fill=BLACK, anchor="rs")

    # centre: track (first point = start/finish, points in race direction)
    if race.get("circuit_file"):
        coords = track_coords(race["circuit_file"], race.get("track_start", 0), race.get("track_reverse", False))
        pts = project_centered(coords, (262, 122, 538, 452), rotate_deg=race.get("map_rotate", 0))
        draw_track_hq(img, pts, BLACK, WHITE, RED, style="outlined")

    # sides
    draw_schedule(d, race["schedule"])
    draw_weather(img, d, race.get("weather"))
    draw_grid(img, d, grid, race["grid_pending"])
    if standings:
        draw_standings(img, d, standings)
    return img


# esp32-photoframe "EPDGZ": gzipped 4-bit panel codes, 2 pixels per byte (left pixel in the
# high nibble), rows top to bottom. The frame shows it as-is, with no dithering.
EPD_CODE = {BLACK: 0x0, WHITE: 0x1, YELLOW: 0x2, RED: 0x3, BLUE: 0x5, GREEN: 0x6}


def epdgz_bytes(img):
    import gzip
    lut = bytes(EPD_CODE.get(i, 0x1) for i in range(256))
    codes = img.tobytes().translate(lut)
    packed = bytes((codes[i] << 4) | codes[i + 1] for i in range(0, len(codes), 2))
    return gzip.compress(packed, compresslevel=9, mtime=0)   # mtime=0: same image, same bytes


def save(img, name, preview=True):
    OUT.mkdir(exist_ok=True)
    img.save(OUT / f"{name}.png")                      # the file the frame downloads
    if preview:
        prev = img.copy()
        pal = [v for rgb in PREVIEW_RGB for v in rgb]
        prev.putpalette(pal + [0] * (768 - len(pal)))
        prev.convert("RGB").resize((W * 2, H * 2), Image.NEAREST).save(OUT / f"{name}_preview.png")


if __name__ == "__main__":
    # Sample: Round 1, 2027. Session times, grid and weather are PLACEHOLDERS.
    race = {
        "name": "Bahrain Grand Prix",
        "dates": "12–14 March",
        "race_date": dt.date(2027, 3, 14),
        "circuit_file": "bh-2002.geojson",
        "schedule": [
            ("FP1", "Fri", "13:30", False),
            ("Sprint Q", "Fri", "17:30", False),
            ("Sprint", "Sat", "14:00", False),
            ("Quali", "Sat", "18:00", False),
            ("Race", "Sun", "17:00", True),
        ],
        "grid_pending": "Sat 18:00",
        "weather": [("Fri", "sun", 27), ("Sat", "partly", 25), ("Sun", "rain", 22)],
    }
    grid = [("NOR", "MCL"), ("VER", "RBR"), ("LEC", "FER"), ("PIA", "MCL"), ("RUS", "MER")]
    standings = [("ANT", "MER", 390), ("VER", "RBR", 279), ("RUS", "MER", 262)]  # after round 20, 2026
    today = dt.date.today()
    save(render(race, today, grid=grid, standings=standings), "sample_with_grid")
    save(render(race, today, grid=None, standings=standings), "sample_before_quali")
    print("rendered into", OUT)
