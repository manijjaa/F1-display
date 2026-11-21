#!/usr/bin/env python3
"""Build the card: fetch data, render, write the files the frame and you look at.

    python make_image.py                          live data -> site/
    python make_image.py --offline                cached data only (no network)
    python make_image.py --now "2027-03-13 19:30" pretend it is this Vilnius time

Output folder
    f1.epdgz          what the frame downloads (exact pixels, no dithering on the device)
    f1.png            the same image as a normal PNG
    f1_preview.png    2x preview with muted "real panel" colours, for checking on a phone
    status.json       what was drawn, and whether any data came from the cache
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import f1data  # noqa: E402
import render  # noqa: E402
from PIL import Image  # noqa: E402


def write_outputs(img, out):
    out.mkdir(parents=True, exist_ok=True)
    img.save(out / "f1.png", optimize=True)
    (out / "f1.epdgz").write_bytes(render.epdgz_bytes(img))
    prev = img.copy()
    pal = [v for rgb in render.PREVIEW_RGB for v in rgb]
    prev.putpalette(pal + [0] * (768 - len(pal)))
    prev.convert("RGB").resize((render.W * 2, render.H * 2), Image.NEAREST).save(out / "f1_preview.png")


def summary_markdown(info, generated):
    lines = [f"### {info['race']}",
             f"- {info['days_to_race']} days to go (season {info['season']}, round {info['round']})",
             f"- map: `{info['circuit_file']}`, grid: {'yes' if info['grid'] else 'not yet'}, "
             f"weather: {'yes' if info['weather'] else 'not yet'}, standings: {info['standings_season']}",
             f"- generated {generated}"]
    if info["stale"]:
        lines.append(f"- **from cache (API down):** {', '.join(info['stale'])}")
    for note in info["notes"]:
        lines.append(f"- note: {note}")
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="site")
    p.add_argument("--cache", default="cache")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--now", help='Vilnius time, "YYYY-MM-DD HH:MM"')
    a = p.parse_args()

    if a.now:
        now = dt.datetime.strptime(a.now, "%Y-%m-%d %H:%M").replace(tzinfo=f1data.TZ)
    else:
        now = dt.datetime.now(f1data.UTC)

    fetcher = f1data.Fetcher(a.cache, offline=a.offline)
    try:
        card = f1data.build_card(fetcher, now)
    except f1data.FetchError as e:
        # Nothing to draw. Exit non-zero so the old image stays up and the run shows red.
        print(f"error: {e}", file=sys.stderr)
        return 1

    img = render.render(card["race"], card["today"], grid=card["grid"], standings=card["standings"])
    out = Path(a.out)
    write_outputs(img, out)

    generated = now.astimezone(f1data.UTC).strftime("%Y-%m-%d %H:%M UTC")
    status = dict(card["info"], generated=generated)
    (out / "status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(status, ensure_ascii=False))

    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as fh:
            fh.write(summary_markdown(card["info"], generated))
    return 0


if __name__ == "__main__":
    sys.exit(main())
