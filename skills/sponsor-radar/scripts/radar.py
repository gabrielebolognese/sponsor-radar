#!/usr/bin/env python3
"""sponsor-radar CLI. Each subcommand is one pipeline stage; outputs go to ~/.sponsor-radar/runs/<handle>/<date>/.

  radar.py setup --key YOUR_KEY [--currency EUR] [--rate 150]
  radar.py check
  radar.py profile @handle          -> profile.json   (then Claude writes niche.json)
  radar.py discover --run @handle   -> candidates.json / candidates.md   (then Claude writes exclude.json)
  radar.py select   --run @handle   -> lookalikes.json
  radar.py scan     --run @handle   -> sightings.json, ambiguous.json   (then Claude writes classified.json)
  radar.py rank     --run @handle   -> brands.json
  radar.py contacts --run @handle   -> contacts.json
  radar.py price    --run @handle   -> rate.json
  radar.py report   --run @handle   -> report.md
  radar.py brief    --run @handle   -> pitch_brief.json (input for writing pitches)
  radar.py pipeline list | due | add --run @handle | update <brand> <status> [--amount N]
  radar.py quota | runs
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (VERSION, api_key, cache_path, fmt_int, load_config, new_run_dir, now_utc,  # noqa: E402
                    parse_channel_arg, read_json, resolve_run, runs_root, save_config, utf8_stdout, write_json)

SETUP_HELP = """No YouTube API key configured. Get one (free, ~5 minutes):
  1. https://console.cloud.google.com/ -> create a project
  2. APIs & Services -> Library -> enable "YouTube Data API v3"
  3. APIs & Services -> Credentials -> Create credentials -> API key
     (optional but smart: restrict the key to the YouTube Data API v3)
  4. Run:  radar.py setup --key YOUR_KEY
Or set the YOUTUBE_API_KEY environment variable."""


def _yt(cfg):
    from yt import YouTube
    key = api_key(cfg)
    if not key:
        raise SystemExit(SETUP_HELP)
    return YouTube(key, cache_path())


def _track_quota(run_dir: Path, stage: str, yt) -> None:
    q = read_json(run_dir / "quota.json", default={})
    q[stage] = q.get(stage, 0) + yt.units_this_run
    write_json(run_dir / "quota.json", q)


def _today() -> date:
    return now_utc().date()


# ---------------------------------------------------------------------------

def cmd_setup(a):
    cfg = load_config()
    if a.key:
        cfg["youtube_api_key"] = a.key.strip()
    if a.currency:
        cfg["currency"] = a.currency.upper()
    if a.rate is not None:
        cfg["current_rate"] = a.rate
    path = save_config(cfg)
    print(f"Saved {path}")
    shown = {k: ("***" + v[-4:] if k == "youtube_api_key" and v else v) for k, v in cfg.items()
             if k in ("youtube_api_key", "currency", "current_rate")}
    print(json.dumps(shown, indent=2))
    if a.key:
        cmd_check(a)


def cmd_check(a):
    cfg = load_config()
    yt = _yt(cfg)
    from yt import YouTubeError
    try:
        ch = yt.channel(handle="@YouTube")
        print("YouTube API key: OK" if ch else "YouTube API key: responded, but test channel not found")
    except YouTubeError as e:
        raise SystemExit(f"YouTube API key check failed: {e}")
    print(f"Quota used today (this machine): {fmt_int(yt.quota_used_today())} / 10,000 units")
    try:
        import youtube_transcript_api  # noqa: F401
        print("Transcripts: youtube-transcript-api installed (best-effort ad-read detection on)")
    except ImportError:
        print("Transcripts: not installed (optional). Enable with: pip install youtube-transcript-api")


def cmd_profile(a):
    from channel import build_profile
    cfg = load_config()
    yt = _yt(cfg)
    kind, value = parse_channel_arg(a.channel)
    now = now_utc()
    prof = build_profile(yt, kind, value, now)
    handle = prof["channel"].get("handle") or value
    run_dir = new_run_dir(handle, now)
    write_json(run_dir / "profile.json", prof)
    _track_quota(run_dir, "profile", yt)
    ch, st = prof["channel"], prof["stats"]
    print(f"RUN_DIR={run_dir}")
    print(f"{ch['title']} ({handle}) · {fmt_int(ch['subs'])} subs · mode: {prof['mode'].upper()}")
    print(f"median views (last 10 long-form): {fmt_int(st['median_views_long'])} · shorts median: "
          f"{fmt_int(st['median_views_shorts'])} · long/short videos: {st['long_count']}/{st['short_count']}")
    print(f"language: {st['language'] or 'unknown'} · country: {ch.get('country') or 'unknown'} · "
          f"uploads/month (90d): {st['uploads_per_month_90d']} · topics: {', '.join(ch['topics']) or '-'}")
    b = prof["bands"]
    print(f"lookalike bands (subs): core {fmt_int(b['core'][0])}-{fmt_int(b['core'][1])}, "
          f"bigger {fmt_int(b['bigger'][0])}-{fmt_int(b['bigger'][1])}")
    print("recent titles:")
    for v in prof["recent_videos"][:15]:
        print(f"  - {v['title']}{' [short]' if v['is_short'] else ''}")
    print(f"\nNext: write {run_dir / 'niche.json'} (see references/niche-and-queries.md), then: radar.py discover --run {handle}")


def cmd_discover(a):
    from discover import run_discover
    cfg = load_config()
    run_dir = resolve_run(a.run)
    yt = _yt(cfg)
    s = run_discover(yt, run_dir, cfg, now_utc())
    _track_quota(run_dir, "discover", yt)
    for w in s["warnings"]:
        print("WARNING:", w)
    print(f"{s['searches']} searches -> {s['channels_found']} channels -> {s['in_band']} in size band "
          f"(core {s['by_band']['core']}, bigger {s['by_band']['bigger']}, smaller {s['by_band']['smaller']}); "
          f"{s['out_of_band']} out of band, {s['excluded_by_terms']} excluded by terms.")
    print(f"Review: {run_dir / 'candidates.md'}")
    print(f"Next: write exclude.json for off-niche channels (or skip), then: radar.py select --run {a.run}")


def cmd_select(a):
    from discover import run_select
    run_dir = resolve_run(a.run)
    s = run_select(run_dir, load_config())
    print(f"Selected {s['selected']} lookalikes (core {s['by_band']['core']}, bigger {s['by_band']['bigger']}, "
          f"smaller {s['by_band']['smaller']}); {s['excluded']} excluded.")
    if s["selected"] < 10:
        print("WARNING: fewer than 10 lookalikes. Results will be thin; consider broader queries in niche.json.")
    print(f"Next: radar.py scan --run {a.run}")


def cmd_scan(a):
    from net import LinkResolver
    from scan import run_scan
    from transcripts import TranscriptFetcher
    cfg = load_config()
    run_dir = resolve_run(a.run)
    yt = _yt(cfg)
    resolver = LinkResolver(cache_path(), enabled=cfg.get("resolve_links", True) and not a.no_resolve)
    tf = None if a.no_transcripts else TranscriptFetcher(max_fetches=int(cfg.get("max_transcripts", 100)))
    try:
        s = run_scan(yt, run_dir, cfg, now_utc(), resolver=resolver, transcripts=tf)
    finally:
        resolver.db.close()
    _track_quota(run_dir, "scan", yt)
    print(f"Scanned {s['creators_scanned']} creators / {fmt_int(s['videos_scanned'])} videos "
          f"(+{s['own_videos_scanned']} of yours). Sightings: {s['sightings']} {s['sightings_by_type']}. "
          f"Paid-flag videos: {s['paid_flag_videos']}.")
    tr = s["transcripts"]
    if tr.get("available"):
        print(f"Transcripts: {tr['fetched']} fetched, {tr['failed']} unavailable, {tr['blocked']} blocked"
              + (f" (stopped: {tr['stopped_reason']})" if tr.get("stopped_reason") else ""))
    else:
        print("Transcripts: off (pip install youtube-transcript-api to enable)")
    for e in s["errors"][:5]:
        print("note:", e)
    print(f"Ambiguous items for Claude: {s['ambiguous']}" + (f" ({s['ambiguous_dropped']} dropped)" if s["ambiguous_dropped"] else ""))
    print(f"Next: classify {run_dir / 'ambiguous.json'} -> classified.json (references/classification.md), "
          f"then: radar.py rank --run {a.run}")


def cmd_rank(a):
    from rank import run_rank
    run_dir = resolve_run(a.run)
    out = run_rank(run_dir, load_config(), now_utc())
    h = out["headline"]
    print(f"{h['brands_ranked']} brands ranked ({h['affiliate_only']} affiliate-only listed separately).")
    print(f"Sponsored creators your size in last 30d: {h['sponsored_your_size_30d']} brands "
          f"({h['deals_your_size_30d_incl_codes']} incl. codes).")
    if h["never_sponsored_you"] is not None:
        print(f"Sponsor lookalikes but never you: {h['never_sponsored_you']}")
    if h["top_repeat"]:
        t = h["top_repeat"]
        print(f"Top repeat: {t['brand']} x{t['times']} with {t['creator']}")
    for b in out["brands"][:a.show]:
        print(f"  {b['rank']:>2}. {b['name']} [{b['type']}] score {b['score']} · {b['why']}"
              + (f" · {'; '.join(b['labels'])}" if b["labels"] else ""))
    print(f"Next: radar.py contacts --run {a.run}")


def cmd_contacts(a):
    from contacts import run_contacts
    run_dir = resolve_run(a.run)
    s = run_contacts(run_dir, top=a.top)
    print(f"Contact paths found for {s['found']} of {s['brands']} brands -> {run_dir / 'contacts.json'}")


def cmd_price(a):
    from pipeline import closed_deals
    from price import run_price
    run_dir = resolve_run(a.run)
    r = run_price(run_dir, load_config(), closed_deals())
    print(r["explain"])
    if r.get("rate_check"):
        print(r["rate_check"])
    if r.get("note"):
        print(r["note"])


def cmd_report(a):
    from report import run_report
    run_dir = resolve_run(a.run)
    run_report(run_dir)
    print(f"REPORT={run_dir / 'report.md'}")


def cmd_brief(a):
    run_dir = resolve_run(a.run)
    prof = read_json(run_dir / "profile.json")
    data = read_json(run_dir / "brands.json")
    contacts = read_json(run_dir / "contacts.json", default={})
    rate = read_json(run_dir / "rate.json", default={})
    niche = read_json(run_dir / "niche.json", default={})
    brief = {
        "creator": {"title": prof["channel"]["title"], "handle": prof["channel"].get("handle"),
                    "subs": prof["channel"]["subs"], "median_views": prof["stats"]["median_views_long"],
                    "language": niche.get("language") or prof["stats"]["language"], "niche": niche.get("niche"),
                    "mode": prof["mode"], "recent_titles": [v["title"] for v in prof["recent_videos"][:12]],
                    "best_videos": [v["title"] for v in sorted(prof["recent_videos"], key=lambda v: -v["views"])[:3]]},
        "rate": {k: rate.get(k) for k in ("low", "high", "currency", "basis", "explain")},
        "brands": [],
    }
    for b in data["brands"][:a.top]:
        c = contacts.get(b["key"], {})
        brief["brands"].append({
            "rank": b["rank"], "key": b["key"], "name": b["name"], "domain": b["domain"], "type": b["type"],
            "deal_types": b["deal_types"], "hybrid": b["hybrid"], "repeat_max": b["repeat_max"], "labels": b["labels"], "why": b["why"], "languages": b["languages"], "codes": b["codes"],
            "creators": b["creators"][:5],
            "proofs": [{k: p[k] for k in ("video_url", "title", "channel", "published_at", "type", "evidence")}
                       for p in b["proofs"][:3]],
            "contact": {"emails": c.get("emails", [])[:2], "program_pages": c.get("program_pages", [])[:2],
                        "networks": c.get("networks", []), "manual": c.get("manual")},
        })
    write_json(run_dir / "pitch_brief.json", brief)
    (run_dir / "pitches").mkdir(exist_ok=True)
    print(json.dumps(brief, indent=1, ensure_ascii=False))
    print(f"\nWrite pitches to {run_dir / 'pitches'} as NN-<brand_key>.md (references/pitch-guide.md).")


def cmd_pipeline(a):
    import pipeline as P
    today = _today()
    if a.action == "list":
        print(P.render(P.load(), today))
    elif a.action == "due":
        d = P.due(P.load(), today)
        print("No follow-ups due." if not d else "\n".join(
            f"- {r['brand']}: follow-up #{int(r['followups'] or 0) + 1} due {r['next_followup']} ({r['pitch_file']})" for r in d))
    elif a.action == "add":
        if not a.run:
            raise SystemExit("pipeline add needs --run @handle")
        added = P.add_from_run(resolve_run(a.run), a.top, today, load_config().get("currency", "USD"))
        print(f"Added {len(added)} brands as 'drafted' -> {P.pipeline_file()}")
    elif a.action == "update":
        if not a.brand or not a.status:
            raise SystemExit("usage: radar.py pipeline update <brand> <status> [--amount N]")
        r = P.update(a.brand, a.status, today, amount=a.amount, currency=a.currency, views=a.views,
                     contact=a.contact, note=a.note)
        print(f"{r['brand']}: {r['status']}" + (f", next follow-up {r['next_followup']}" if r["next_followup"] else ""))
        if r["status"] == "closed" and r["amount"]:
            n = len(P.closed_deals())
            print(f"Logged. {n} closed deal(s) with amounts" +
                  (": your CPM range now calibrates from them." if n >= 2 else ": rates calibrate after 2."))


def cmd_quota(a):
    yt = _yt(load_config())
    print(f"Quota used today (this machine): {fmt_int(yt.quota_used_today())} / 10,000 units")


def cmd_runs(a):
    root = runs_root()
    for d in sorted(root.glob("*/*")):
        if d.is_dir():
            done = "report" if (d / "report.md").exists() else "brands" if (d / "brands.json").exists() else \
                "scan" if (d / "sightings.json").exists() else "started"
            print(f"{d.parent.name}/{d.name}  [{done}]  {d}")


def main(argv=None):
    utf8_stdout()
    p = argparse.ArgumentParser(prog="radar.py", description=f"sponsor-radar {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup")
    s.add_argument("--key")
    s.add_argument("--currency")
    s.add_argument("--rate", type=float, help="what you charge per integration today, in your currency")
    s.set_defaults(fn=cmd_setup)
    sub.add_parser("check").set_defaults(fn=cmd_check)

    s = sub.add_parser("profile")
    s.add_argument("channel")
    s.set_defaults(fn=cmd_profile)

    for name, fn in (("discover", cmd_discover), ("select", cmd_select), ("price", cmd_price), ("report", cmd_report)):
        s = sub.add_parser(name)
        s.add_argument("--run", required=True)
        s.set_defaults(fn=fn)

    s = sub.add_parser("scan")
    s.add_argument("--run", required=True)
    s.add_argument("--no-transcripts", action="store_true")
    s.add_argument("--no-resolve", action="store_true", help="don't follow shortener/affiliate redirects")
    s.set_defaults(fn=cmd_scan)

    s = sub.add_parser("rank")
    s.add_argument("--run", required=True)
    s.add_argument("--show", type=int, default=15)
    s.set_defaults(fn=cmd_rank)

    s = sub.add_parser("contacts")
    s.add_argument("--run", required=True)
    s.add_argument("--top", type=int, default=15)
    s.set_defaults(fn=cmd_contacts)

    s = sub.add_parser("brief")
    s.add_argument("--run", required=True)
    s.add_argument("--top", type=int, default=10)
    s.set_defaults(fn=cmd_brief)

    s = sub.add_parser("pipeline")
    s.add_argument("action", choices=["list", "due", "add", "update"])
    s.add_argument("brand", nargs="?")
    s.add_argument("status", nargs="?")
    s.add_argument("--run")
    s.add_argument("--top", type=int, default=10)
    s.add_argument("--amount")
    s.add_argument("--currency")
    s.add_argument("--views")
    s.add_argument("--contact")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_pipeline)

    sub.add_parser("quota").set_defaults(fn=cmd_quota)
    sub.add_parser("runs").set_defaults(fn=cmd_runs)

    a = p.parse_args(argv)
    from yt import QuotaExceeded
    try:
        a.fn(a)
    except QuotaExceeded as e:
        raise SystemExit(f"STOPPED: {e}")


if __name__ == "__main__":
    main()
