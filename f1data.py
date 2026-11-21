"""Live data for the F1 e-ink card.

Sources (no API keys needed):
  Jolpica-F1 (the Ergast successor)  schedule, qualifying, driver standings
  Open-Meteo                         race-weekend forecast at the circuit

Everything on the card is shown in Vilnius time. Every successful API response
is saved in the cache folder. If an API is down, the last good copy is used, so
a short outage never blanks the card.

Rules (see screen-design.md)
  next race      the card switches to the next race at 06:00 Vilnius on the Monday after a race
  grid           top 5 in qualifying order once results are out, otherwise "After qualifying <day time>"
  weather        only when the whole race weekend is inside the 16-day forecast
  standings      current season top 3; before round 1, last season's final table
"""
from __future__ import annotations

import datetime as dt
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from icons import kind_for_wmo

ROOT = Path(__file__).resolve().parent
CIRCUITS_DIR = ROOT / "assets" / "circuits"
TZ = ZoneInfo("Europe/Vilnius")
UTC = dt.timezone.utc

JOLPICA = "https://api.jolpi.ca/ergast/f1"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "f1-eink-card/1.0 (home e-paper display)"

FORECAST_DAYS = 16
QUALI_RESULTS_AFTER = dt.timedelta(minutes=75)   # session length plus a little slack
ROLLOVER = dt.time(6, 0)                          # Monday after the race, Vilnius time

# Jolpica session keys, in weekend order, and their label on the card
SESSION_KEYS = [
    ("FirstPractice", "FP1"),
    ("SecondPractice", "FP2"),
    ("ThirdPractice", "FP3"),
    ("SprintShootout", "Sprint Q"),     # 2023 name
    ("SprintQualifying", "Sprint Q"),   # 2024 onwards
    ("Sprint", "Sprint"),
    ("Qualifying", "Quali"),
]

# Jolpica constructorId -> team key used by render.TEAM_DOT
TEAM_KEYS = {
    "mclaren": "MCL", "ferrari": "FER", "red_bull": "RBR", "mercedes": "MER",
    "aston_martin": "AMR", "alpine": "ALP", "williams": "WIL", "rb": "RB",
    "haas": "HAA", "audi": "AUD", "sauber": "AUD", "cadillac": "CAD",
}

DAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH = ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"]


# ------------------------------------------------------------------ fetching
class FetchError(RuntimeError):
    pass


class Fetcher:
    """GET JSON with retries. Successes are cached; failures fall back to the cache."""

    def __init__(self, cache_dir, offline=False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.stale = []          # keys served from the cache because the API failed
        self._session = None

    def get(self, url, key, params=None):
        path = self.cache_dir / f"{key}.json"
        if self.offline:
            if path.exists():
                return json.loads(path.read_text())
            raise FetchError(f"{key}: not in cache")
        error = "no attempt"
        for attempt in range(3):
            try:
                data = self._get(url, params)
                path.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")))
                return data
            except _Permanent as e:
                error = str(e)
                break
            except Exception as e:  # network error, 429, 5xx, bad JSON
                error = f"{type(e).__name__}: {e}"
                if attempt < 2:
                    time.sleep(3 * (attempt + 1))
        if path.exists():
            self.stale.append(key)
            return json.loads(path.read_text())
        raise FetchError(f"{key}: {error}")

    def _get(self, url, params):
        import requests
        if self._session is None:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = USER_AGENT
        r = self._session.get(url, params=params, timeout=20)
        if 400 <= r.status_code < 500 and r.status_code != 429:
            raise _Permanent(f"HTTP {r.status_code} for {r.url}")
        r.raise_for_status()
        return r.json()


class _Permanent(Exception):
    pass


# ------------------------------------------------------------------ model
@dataclass
class Session:
    label: str
    start: dt.datetime | None    # aware UTC; None when only the date is published
    day: dt.date                 # Vilnius date (the published date if there is no time)

    @property
    def local(self):
        return self.start.astimezone(TZ) if self.start else None

    @property
    def sort_key(self):
        return self.start or dt.datetime.combine(self.day, dt.time(12), tzinfo=TZ)


@dataclass
class Race:
    season: int
    round: int
    name: str
    circuit_id: str
    lat: float | None
    lon: float | None
    sessions: list               # weekend order, race last
    circuit_file: str | None = None

    @property
    def race(self):
        return self.sessions[-1]

    def session(self, label):
        return next((s for s in self.sessions if s.label == label), None)


def _utc_session(label, date_s, time_s):
    if time_s:
        start = dt.datetime.fromisoformat(f"{date_s}T{time_s.replace('Z', '+00:00')}")
        start = (start if start.tzinfo else start.replace(tzinfo=UTC)).astimezone(UTC)
        return Session(label, start, start.astimezone(TZ).date())
    return Session(label, None, dt.date.fromisoformat(date_s))


def _local_session(label, value):
    """Override value in Vilnius time: 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'."""
    if isinstance(value, dt.datetime):
        local = value if value.tzinfo else value.replace(tzinfo=TZ)
        return Session(label, local.astimezone(UTC), local.astimezone(TZ).date())
    if isinstance(value, dt.date):
        return Session(label, None, value)
    s = str(value).strip()
    if len(s) == 10:
        return Session(label, None, dt.date.fromisoformat(s))
    local = dt.datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    return Session(label, local.astimezone(UTC), local.date())


def parse_races(data):
    races = []
    for r in data["MRData"]["RaceTable"]["Races"]:
        sessions = [_utc_session(label, r[key]["date"], r[key].get("time"))
                    for key, label in SESSION_KEYS if key in r]
        sessions.sort(key=lambda s: s.sort_key)
        sessions.append(_utc_session("Race", r["date"], r.get("time")))
        loc = r["Circuit"]["Location"]
        races.append(Race(int(r["season"]), int(r["round"]), r["raceName"],
                          r["Circuit"]["circuitId"], float(loc["lat"]), float(loc["long"]), sessions))
    return races


# ------------------------------------------------------------------ overrides
def load_yaml(path):
    path = Path(path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def apply_overrides(races, overrides, season):
    """Patch API races, or add races the API doesn't have yet (overrides.yaml)."""
    by_round = {r.round: r for r in races}
    for o in overrides.get("races") or []:
        if int(o["season"]) != season:
            continue
        race = by_round.get(int(o["round"]))
        if race is None:
            if "sessions" not in o or "Race" not in o["sessions"] or "name" not in o:
                continue                     # not enough to draw a card
            race = Race(season, int(o["round"]), o["name"], o.get("circuit", ""),
                        o.get("lat"), o.get("lon"), [])
            by_round[race.round] = race
        if "name" in o:
            race.name = o["name"]
        if "circuit_file" in o:
            race.circuit_file = o["circuit_file"]
        if "sessions" in o:
            sessions = [_local_session(label, v) for label, v in o["sessions"].items() if label != "Race"]
            sessions.sort(key=lambda s: s.sort_key)
            race_session = _local_session("Race", o["sessions"]["Race"]) if "Race" in o["sessions"] else race.race
            race.sessions = sessions + [race_session]
    return sorted(by_round.values(), key=lambda r: r.race.sort_key)


# ------------------------------------------------------------------ rules
def rollover(race):
    """The card moves on at 06:00 Vilnius on the Monday after the race."""
    day = race.race.day
    monday = day + dt.timedelta(days=(7 - day.weekday()) % 7 or 7)
    return dt.datetime.combine(monday, ROLLOVER, tzinfo=TZ)


def next_race(fetcher, now, overrides, notes):
    year = now.astimezone(TZ).year
    for season in (year, year + 1):          # year + 1 covers December after the finale
        try:
            data = fetcher.get(f"{JOLPICA}/{season}/races/", f"schedule-{season}", {"limit": 100})
            races = parse_races(data)
        except FetchError as e:
            notes.append(str(e))
            races = []
        races = apply_overrides(races, overrides, season)
        race = next((r for r in races if now < rollover(r)), None)
        if race:
            return race
    raise FetchError("no upcoming race in the API or overrides.yaml")


def date_range(first, last):
    if first == last:
        return f"{last.day} {MONTH[last.month - 1]}"
    if first.month == last.month:
        return f"{first.day}–{last.day} {MONTH[last.month - 1]}"
    return f"{first.day} {MONTH[first.month - 1][:3]} – {last.day} {MONTH[last.month - 1][:3]}"


def team_key(constructor_id):
    return TEAM_KEYS.get(constructor_id, "")


def driver_code(driver):
    return driver.get("code") or driver.get("familyName", "???")[:3].upper()


def points(value):
    p = float(value)
    return int(p) if p.is_integer() else p


def qualifying_top5(fetcher, race, now):
    q = race.session("Quali")
    if q is None or q.start is None or now < q.start + QUALI_RESULTS_AFTER:
        return None
    data = fetcher.get(f"{JOLPICA}/{race.season}/{race.round}/qualifying/",
                       f"quali-{race.season}-{race.round}")
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return None
    rows = sorted(races[0].get("QualifyingResults", []), key=lambda r: int(r["position"]))
    grid = [(driver_code(r["Driver"]), team_key(r["Constructor"]["constructorId"])) for r in rows[:5]]
    return grid or None


def standings_top3(fetcher, season):
    for year in (season, season - 1):
        data = fetcher.get(f"{JOLPICA}/{year}/driverstandings/", f"standings-{year}")
        lists = data["MRData"]["StandingsTable"]["StandingsLists"]
        if lists and lists[0].get("DriverStandings"):
            rows = lists[0]["DriverStandings"][:3]
            return [(driver_code(r["Driver"]), team_key(r["Constructors"][-1]["constructorId"]),
                     points(r["points"])) for r in rows], year
    return None, None


def weekend_weather(fetcher, race, now):
    """[(day, kind, max temp)] for the three days ending on race day, circuit local time."""
    if race.lat is None or (race.race.day - now.astimezone(TZ).date()).days > FORECAST_DAYS - 2:
        return None
    data = fetcher.get(OPEN_METEO, f"weather-{race.season}-{race.round}", {
        "latitude": race.lat, "longitude": race.lon, "timezone": "auto",
        "daily": "weather_code,temperature_2m_max", "forecast_days": FORECAST_DAYS,
        "past_days": 2,          # keeps Friday and Saturday on the card during the weekend
    })
    offset = dt.timedelta(seconds=data.get("utc_offset_seconds", 0))
    race_day = (race.race.start + offset).date() if race.race.start else race.race.day
    days = [race_day - dt.timedelta(days=n) for n in (2, 1, 0)]
    daily = data["daily"]
    index = {d: i for i, d in enumerate(daily["time"])}
    out = []
    for d in days:
        i = index.get(d.isoformat())
        if i is None:
            return None
        code, temp = daily["weather_code"][i], daily["temperature_2m_max"][i]
        if code is None or temp is None:
            return None
        out.append((DAY[d.weekday()], kind_for_wmo(int(code)), int(math.floor(temp + 0.5))))
    return out


# ------------------------------------------------------------------ circuits
_INDEX = None


def _circuit_index():
    global _INDEX
    if _INDEX is None:
        _INDEX = []
        for f in sorted(CIRCUITS_DIR.glob("*.geojson")):
            coords = json.loads(f.read_text())["features"][0]["geometry"]["coordinates"]
            _INDEX.append((f.name, sum(c[1] for c in coords) / len(coords),
                           sum(c[0] for c in coords) / len(coords)))
    return _INDEX


def _km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 12742 * math.asin(math.sqrt(a))


def nearest_circuit(lat, lon, max_km=50):
    if lat is None or lon is None:
        return None
    dist, name = min((_km(lat, lon, la, lo), name) for name, la, lo in _circuit_index())
    return name if dist <= max_km else None


# ------------------------------------------------------------------ card
def build_card(fetcher, now, overrides_path=ROOT / "overrides.yaml", circuits_path=ROOT / "circuits.yaml"):
    """Everything render.render() needs, plus an info dict for status.json."""
    now = now.astimezone(UTC)
    notes = []
    race = next_race(fetcher, now, load_yaml(overrides_path), notes)

    tweak = (load_yaml(circuits_path) or {}).get(race.circuit_id) or {}
    circuit_file = race.circuit_file or tweak.get("file") or nearest_circuit(race.lat, race.lon)
    if circuit_file is None:
        notes.append(f"no outline for circuit '{race.circuit_id}'")

    def guarded(fn, *args):
        try:
            return fn(*args)
        except (FetchError, KeyError, ValueError, TypeError) as e:
            notes.append(f"{fn.__name__}: {e}")
            return None

    grid = guarded(qualifying_top5, fetcher, race, now)
    weather = guarded(weekend_weather, fetcher, race, now)
    standings, standings_season = guarded(standings_top3, fetcher, race.season) or (None, None)

    q = race.session("Quali")
    if q is None:
        pending = "TBC"
    elif q.start is None:
        pending = DAY[q.day.weekday()]
    else:
        pending = f"{DAY[q.day.weekday()]} {q.local:%H:%M}"

    card = {
        "name": race.name,
        "dates": date_range(race.sessions[0].day, race.race.day),
        "race_date": race.race.day,
        "circuit_file": circuit_file,
        "map_rotate": tweak.get("rotate", 0),
        "track_start": tweak.get("start", 0),
        "track_reverse": tweak.get("reverse", False),
        "schedule": [(s.label, DAY[s.day.weekday()], f"{s.local:%H:%M}" if s.start else "TBC",
                      s.label == "Race") for s in race.sessions],
        "grid_pending": pending,
        "weather": weather,
    }
    today = now.astimezone(TZ).date()
    info = {
        "season": race.season,
        "round": race.round,
        "race": race.name,
        "circuit": race.circuit_id,
        "circuit_file": circuit_file,
        "days_to_race": max(0, (race.race.day - today).days),
        "grid": bool(grid),
        "weather": bool(weather),
        "standings_season": standings_season,
        "stale": sorted(set(fetcher.stale)),
        "notes": notes,
    }
    return {"race": card, "today": today, "grid": grid, "standings": standings, "info": info}
