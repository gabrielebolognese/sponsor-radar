"""Shared helpers: paths, config, JSON IO, dates, small math."""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
REFERENCES = SKILL_DIR / "references"
VERSION = "0.1.0"
USER_AGENT = f"Mozilla/5.0 (compatible; sponsor-radar/{VERSION})"

DEFAULT_CONFIG = {
    "youtube_api_key": "",
    "currency": "USD",
    "current_rate": None,
    # Approximate. Edit in ~/.sponsor-radar/config.json if you want exact numbers.
    "fx_from_usd": {
        "USD": 1.0, "EUR": 0.92, "GBP": 0.79, "CHF": 0.88, "CAD": 1.37,
        "AUD": 1.52, "BRL": 5.4, "MXN": 18.0, "INR": 84.0, "JPY": 150.0,
    },
    "max_search_queries": 15,
    "max_lookalikes": 50,
    "max_transcripts": 100,
    "resolve_links": True,
    "weights": {},
}


# ---------- paths ----------

def home() -> Path:
    p = Path(os.environ.get("SPONSOR_RADAR_HOME") or (Path.home() / ".sponsor-radar"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_path() -> Path:
    return home() / "cache.db"


def runs_root() -> Path:
    p = home() / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_name(handle: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", handle.lstrip("@")) or "channel"


def new_run_dir(handle: str, now: datetime | None = None) -> Path:
    now = now or now_utc()
    p = runs_root() / safe_name(handle) / now.strftime("%Y-%m-%d")
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_run(arg: str) -> Path:
    """Accept a run directory path, or a handle (latest run for that handle)."""
    p = Path(arg).expanduser()
    if p.is_dir():
        return p
    base = runs_root() / safe_name(arg)
    if base.is_dir():
        runs = sorted(d for d in base.iterdir() if d.is_dir())
        if runs:
            return runs[-1]
    raise SystemExit(f"No run found for '{arg}'. Start one with: radar.py profile @handle")


# ---------- config ----------

def config_file() -> Path:
    return home() / "config.json"


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    f = config_file()
    if f.exists():
        try:
            user = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"{f} is not valid JSON: {e}")
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save_config(cfg: dict) -> Path:
    f = config_file()
    f.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return f


def api_key(cfg: dict | None = None) -> str:
    key = os.environ.get("YOUTUBE_API_KEY") or (cfg or load_config()).get("youtube_api_key") or ""
    return key.strip()


# ---------- JSON IO ----------

def read_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        raise SystemExit(f"Missing file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


# ---------- dates ----------

def now_utc() -> datetime:
    fixed = os.environ.get("SPONSOR_RADAR_NOW")
    if fixed:
        return parse_iso(fixed)
    return datetime.now(timezone.utc)


def parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def week_floor(dt: datetime) -> datetime:
    """Start of the ISO week (Monday 00:00 UTC). Keeps search cache keys stable for a week."""
    d = dt.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


def age_days(published: str | datetime, now: datetime) -> float:
    dt = parse_iso(published) if isinstance(published, str) else published
    return max(0.0, (now - dt).total_seconds() / 86400)


_DUR = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def duration_seconds(iso_duration: str | None) -> int:
    if not iso_duration:
        return 0
    m = _DUR.fullmatch(iso_duration)
    if not m:
        return 0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


# ---------- small helpers ----------

def median(values) -> float:
    values = [v for v in values if v is not None]
    return float(statistics.median(values)) if values else 0.0


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def unique(seq):
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def fmt_int(n) -> str:
    return f"{int(round(n or 0)):,}"


def parse_channel_arg(arg: str) -> tuple[str, str]:
    """Return ('handle', '@x') or ('id', 'UC...') from a handle, URL or channel id."""
    a = arg.strip().rstrip("/")
    m = re.search(r"youtube\.com/(@[\w.-]+)", a)
    if m:
        return "handle", m.group(1)
    m = re.search(r"youtube\.com/channel/(UC[\w-]{22})", a)
    if m:
        return "id", m.group(1)
    if re.fullmatch(r"UC[\w-]{22}", a):
        return "id", a
    return "handle", a if a.startswith("@") else "@" + a


def utf8_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
