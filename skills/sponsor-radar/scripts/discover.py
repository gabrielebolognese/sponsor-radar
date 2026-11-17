"""Find lookalike creators: niche searches + featured-channel expansion, then size-band filtering."""
from __future__ import annotations

import html
from datetime import datetime, timedelta

from channel import band_of, channel_summary
from common import fmt_int, read_json, week_floor, write_json
from yt import DAILY_QUOTA

BAND_ORDER = {"core": 0, "bigger": 1, "smaller": 2}


def run_discover(yt, run_dir, cfg: dict, now: datetime) -> dict:
    profile = read_json(run_dir / "profile.json")
    niche = read_json(run_dir / "niche.json")
    since = week_floor(now - timedelta(days=90))
    lang = niche.get("language") or profile["stats"].get("language")
    region = niche.get("region") or profile["channel"].get("country")
    own_id = profile["channel"]["id"]

    queries = [(q, lang, region) for q in niche.get("queries", [])]
    queries += [(q, "en", None) for q in niche.get("queries_en", [])]
    queries = queries[: int(cfg.get("max_search_queries", 15))]
    if not queries:
        raise SystemExit("niche.json has no queries. Add 'queries' (and optionally 'queries_en').")

    budget_left = DAILY_QUOTA - yt.quota_used_today() - 150  # keep room for scanning
    affordable = max(0, budget_left // 100)
    warnings = []
    if affordable < len(queries):
        warnings.append(f"Quota is tight today: running {affordable} of {len(queries)} searches "
                        "(cached searches are free).")
        queries = queries[:affordable] if affordable else queries[:0]

    hits: dict[str, dict] = {}
    for q, l, r in queries:
        for it in yt.search_videos(q, since, l, r):
            sn = it.get("snippet", {})
            cid = sn.get("channelId")
            if not cid:
                continue
            h = hits.setdefault(cid, {"id": cid, "queries": set(), "matched_titles": [], "featured": False})
            h["queries"].add(q)
            t = html.unescape(sn.get("title", ""))
            if len(h["matched_titles"]) < 3 and t not in h["matched_titles"]:
                h["matched_titles"].append(t)
    hits.pop(own_id, None)

    top = sorted(hits.values(), key=lambda h: -len(h["queries"]))[:10]
    featured = set(yt.featured_channel_ids(own_id))
    for h in top:
        featured.update(yt.featured_channel_ids(h["id"]))
    for cid in featured:
        if cid == own_id:
            continue
        hits.setdefault(cid, {"id": cid, "queries": set(), "matched_titles": [], "featured": False})["featured"] = True

    excl = [t.lower() for t in niche.get("exclude_terms", []) if t.strip()]
    bands = profile["bands"]
    cands, out_of_band, excluded = [], 0, 0
    for item in yt.channels(list(hits)):
        s = channel_summary(item)
        h = hits.get(s["id"])
        if not h:
            continue
        text = (s["title"] + " " + " ".join(h["matched_titles"])).lower()
        if any(t in text for t in excl):
            excluded += 1
            continue
        band = band_of(s["subs"], bands)
        if band is None:
            out_of_band += 1
            continue
        cands.append({
            "id": s["id"], "title": s["title"], "handle": s["handle"], "subs": s["subs"],
            "country": s["country"], "uploads": s["uploads"], "band": band,
            "relevance": len(h["queries"]) + (0.5 if h["featured"] else 0),
            "featured": h["featured"], "matched_titles": h["matched_titles"],
        })
    cands.sort(key=lambda c: (BAND_ORDER[c["band"]], -c["relevance"], -(c["subs"] or 0)))
    write_json(run_dir / "candidates.json", cands)
    write_candidates_md(run_dir, cands, profile)
    summary = {
        "searches": len(queries), "channels_found": len(hits), "in_band": len(cands),
        "out_of_band": out_of_band, "excluded_by_terms": excluded,
        "by_band": {b: sum(1 for c in cands if c["band"] == b) for b in BAND_ORDER},
        "warnings": warnings,
    }
    write_json(run_dir / "discover_stats.json", summary)
    return summary


def write_candidates_md(run_dir, cands: list[dict], profile: dict) -> None:
    lines = [f"# Lookalike candidates for {profile['channel']['title']} ({fmt_int(profile['channel']['subs'])} subs)",
             "", "Prune channels that are off-niche (wrong topic, news/compilation/reupload channels, kids, music labels).",
             "Write their ids to exclude.json as {\"exclude\": [\"UC...\"]}.", "",
             "| id | channel | subs | band | country | matched videos |", "|---|---|---|---|---|---|"]
    for c in cands:
        titles = " / ".join(t[:70] for t in c["matched_titles"][:2]) or ("(featured channel)" if c["featured"] else "")
        lines.append(f"| {c['id']} | {c['title'][:40]} | {fmt_int(c['subs'])} | {c['band']} | {c['country'] or ''} | "
                     f"{titles.replace('|', '/')} |")
    (run_dir / "candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_select(run_dir, cfg: dict) -> dict:
    cands = read_json(run_dir / "candidates.json")
    ex = read_json(run_dir / "exclude.json", default={"exclude": []})
    excluded = set(ex if isinstance(ex, list) else ex.get("exclude", []))
    keep = [c for c in cands if c["id"] not in excluded]
    by = {b: [c for c in keep if c["band"] == b] for b in BAND_ORDER}
    max_total = int(cfg.get("max_lookalikes", 50))
    n_core = min(len(by["core"]), round(max_total * 0.7))
    n_big = min(len(by["bigger"]), max_total - n_core)
    pick = by["core"][:n_core] + by["bigger"][:n_big]
    leftovers = by["core"][n_core:] + by["bigger"][n_big:] + by["smaller"]
    pick += leftovers[: max(0, max_total - len(pick))]
    write_json(run_dir / "lookalikes.json", {"creators": pick, "excluded": sorted(excluded)})
    return {"selected": len(pick), "excluded": len(excluded),
            "by_band": {b: sum(1 for c in pick if c["band"] == b) for b in BAND_ORDER}}
