"""Offline checks of the data rules with sample API responses (tests/fixtures).

    python tests/test_offline.py      (or: pytest tests)

Renders every scenario into out/tests/ so the cards can be eyeballed too.
"""
import datetime as dt
import gzip
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import f1data  # noqa: E402
import make_image  # noqa: E402
import render  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
OUT = ROOT / "out" / "tests"
NO_OVERRIDES = ROOT / "tests" / "no-such-file.yaml"


def vilnius(s):
    return dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=f1data.TZ)


def card_at(when, cache=FIXTURES, overrides=NO_OVERRIDES, offline=True, name=None):
    fetcher = f1data.Fetcher(cache, offline=offline)
    card = f1data.build_card(fetcher, vilnius(when), overrides_path=overrides)
    img = render.render(card["race"], card["today"], grid=card["grid"], standings=card["standings"])
    if name:
        make_image.write_outputs(img, OUT / name)
    return card, img


def test_race_weekend_with_grid_and_weather():
    card, _ = card_at("2026-11-21 12:00", name="vegas_saturday")
    r = card["race"]
    assert r["name"] == "Las Vegas Grand Prix"
    assert r["dates"] == "20–22 November"
    assert r["circuit_file"] == "us-2023.geojson"
    assert r["schedule"] == [("FP1", "Fri", "02:30", False), ("FP2", "Fri", "06:00", False),
                             ("FP3", "Sat", "02:30", False), ("Quali", "Sat", "06:00", False),
                             ("Race", "Sun", "06:00", True)]
    assert card["grid"][0] == ("RUS", "MER") and len(card["grid"]) == 5
    assert [w[0] for w in r["weather"]] == ["Thu", "Fri", "Sat"]          # circuit local days
    assert r["weather"][0] == ("Thu", "sun", 18)
    assert card["info"]["days_to_race"] == 1
    assert card["standings"][0] == ("ANT", "MER", 390)


def test_rollover_waits_until_monday_0600():
    card, _ = card_at("2026-11-23 05:59", name="vegas_monday_early")
    assert card["race"]["name"] == "Las Vegas Grand Prix"
    assert card["info"]["days_to_race"] == 0                                 # shows "Today"
    card, _ = card_at("2026-11-23 06:00")
    assert card["race"]["name"] == "Qatar Grand Prix"


def test_before_qualifying_shows_pending_time():
    card, _ = card_at("2026-11-23 08:00", name="qatar_monday")
    assert card["grid"] is None
    assert card["race"]["grid_pending"] == "Sat 20:00"
    assert card["race"]["schedule"][1] == ("Sprint Q", "Fri", "19:30", False)
    assert card["info"]["days_to_race"] == 6
    assert card["race"]["weather"] is not None


def test_off_season_uses_next_year_and_last_standings():
    card, _ = card_at("2026-12-20 10:00", name="off_season")
    assert card["race"]["name"] == "Bahrain Grand Prix"
    assert card["race"]["dates"] == "12–14 March"
    assert card["race"]["schedule"][-1] == ("Race", "Sun", "17:00", True)
    assert card["info"]["days_to_race"] == 84
    assert card["info"]["standings_season"] == 2026
    assert card["race"]["weather"] is None and card["grid"] is None


def test_bahrain_after_qualifying():
    card, _ = card_at("2027-03-13 19:30", name="bahrain_saturday")
    assert [g[0] for g in card["grid"]] == ["NOR", "VER", "LEC", "PIA", "RUS"]
    assert card["race"]["weather"] == [("Fri", "sun", 27), ("Sat", "partly", 25), ("Sun", "rain", 22)]


def test_race_day_and_dates_without_times():
    card, _ = card_at("2027-03-14 18:00", name="bahrain_race_day")
    assert card["info"]["days_to_race"] == 0
    card, _ = card_at("2027-03-16 09:00", name="saudi_times_tbc")
    assert card["race"]["name"] == "Saudi Arabian Grand Prix"
    assert card["race"]["schedule"][-1] == ("Race", "Sun", "TBC", True)
    assert card["race"]["grid_pending"] == "Sat"


def test_overrides_fill_a_missing_season():
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache"
        shutil.copytree(FIXTURES, cache)
        (cache / "schedule-2027.json").unlink()
        overrides = Path(tmp) / "overrides.yaml"
        overrides.write_text(
            "races:\n"
            "  - {season: 2027, round: 1, name: Bahrain Grand Prix, circuit: bahrain, lat: 26.0325, lon: 50.5106,\n"
            "     sessions: {FP1: '2027-03-12 14:30', Quali: '2027-03-13 18:00', Race: '2027-03-14 17:00'}}\n")
        card, _ = card_at("2026-12-20 10:00", cache=cache, overrides=overrides)
        assert card["race"]["name"] == "Bahrain Grand Prix"
        assert card["race"]["circuit_file"] == "bh-2002.geojson"
        assert card["race"]["schedule"][0] == ("FP1", "Fri", "14:30", False)


def test_api_down_falls_back_to_cache():
    saved = f1data.JOLPICA, f1data.OPEN_METEO, f1data.time.sleep
    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "cache"
        shutil.copytree(FIXTURES, cache)
        f1data.JOLPICA = "http://127.0.0.1:9/ergast/f1"      # nothing listens here
        f1data.OPEN_METEO = "http://127.0.0.1:9/v1/forecast"
        f1data.time.sleep = lambda s: None                   # skip retry waits
        try:
            card, _ = card_at("2026-11-21 12:00", cache=cache, offline=False)
        finally:
            f1data.JOLPICA, f1data.OPEN_METEO, f1data.time.sleep = saved
        assert card["race"]["name"] == "Las Vegas Grand Prix"
        assert "schedule-2026" in card["info"]["stale"]


def test_epdgz_matches_png_pixel_for_pixel():
    _, img = card_at("2027-03-13 19:30")
    raw = gzip.decompress(render.epdgz_bytes(img))
    assert len(raw) == render.W * render.H // 2
    code_to_index = {v: k for k, v in render.EPD_CODE.items()}
    unpacked = bytearray()
    for b in raw:
        unpacked += bytes((code_to_index[b >> 4], code_to_index[b & 0x0F]))
    assert bytes(unpacked) == img.tobytes()
    assert render.epdgz_bytes(img) == render.epdgz_bytes(img)          # deterministic


def test_every_circuit_outline_draws():
    for f in sorted((ROOT / "assets" / "circuits").glob("*.geojson")):
        race = {"name": f.stem, "dates": "1–3 May", "race_date": dt.date(2027, 5, 3), "circuit_file": f.name,
                "schedule": [("Race", "Sun", "15:00", True)], "grid_pending": "Sat 16:00"}
        render.render(race, dt.date(2027, 5, 1))


if __name__ == "__main__":
    tests = [(n, fn) for n, fn in sorted(globals().items()) if n.startswith("test_") and callable(fn)]
    for name, fn in tests:
        fn()
        print("ok ", name)
    print(f"{len(tests)} passed; cards in {OUT}")
