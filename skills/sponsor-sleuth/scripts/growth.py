"""Reality check and growth target.

Answers two questions from the scan data alone:
  1. Did any brand pay a creator within reach of the user's size? (realistic sponsors)
  2. If not, what is the smallest creator in the niche that a brand actually paid? (the growth target)
Every number points back to a creator and a proof video, like everything else in the report.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from common import age_days, fmt_int

REACH_MULTIPLE = 3.0  # "within reach" = at most 3x your subscribers and 3x your median views
NICE_STEPS = [100, 250, 500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000]


def _known(x) -> float | None:
    return float(x) if x else None  # median() returns 0.0 for "no data"


def _nearest_rank(values: list[float], q: float) -> float:
    s = sorted(values)
    return s[max(0, min(len(s) - 1, int(round(q * (len(s) - 1)))))]


def _x(target, current) -> float | None:
    return round(target / current, 1) if target and current else None


def within_reach(cr: dict, user_subs, user_views, reach: float) -> bool:
    """Both size measures must be within reach when both are known; brands buy views, so views alone can decide."""
    checks = []
    if user_views and _known(cr.get("median_views_long")):
        checks.append(cr["median_views_long"] <= reach * user_views)
    if user_subs and cr.get("subs"):
        checks.append(cr["subs"] <= reach * user_subs)
    return bool(checks) and all(checks)


def milestones(current, target) -> list[int]:
    if not target:
        return []
    cur = current or 0
    steps = [n for n in NICE_STEPS if cur < n < target * 0.8]
    if len(steps) > 3:
        steps = [steps[0], steps[len(steps) // 2], steps[-1]]
    return steps + [int(target)]


def _channel_url(cr: dict) -> str:
    h = cr.get("handle") or ""
    return f"https://www.youtube.com/{h}" if h.startswith("@") else f"https://www.youtube.com/channel/{cr['id']}"


def _habits(cr: dict) -> dict:
    v, s = _known(cr.get("median_views_long")), cr.get("subs")
    return {
        "uploads_per_month_90d": cr.get("uploads_per_month_90d"),
        "shorts_share": cr.get("shorts_share"),
        "median_duration_long_min": cr.get("median_duration_long_min"),
        "views_per_100_subs": round(v / s * 100, 1) if v and s else None,
    }


def _median_of(rows: list[dict], key: str):
    vals = sorted(r[key] for r in rows if r.get(key) is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else round((vals[mid - 1] + vals[mid]) / 2, 2)


def _pace(profile: dict, now: datetime, target_subs) -> dict | None:
    ch, st = profile["channel"], profile["stats"]
    subs = ch.get("subs")
    # The first upload is the real start when we saw every video; otherwise fall back to channel creation.
    start = st.get("first_upload") if (ch.get("video_count") or 0) <= 50 and st.get("first_upload") \
        else ch.get("published_at")
    if not start or subs is None:
        return None
    months = age_days(start, now) / 30.44
    if months < 0.5:
        return {"months_active": round(months, 1), "subs_per_month": None, "months_to_target": None,
                "reliable": False, "start": start}
    per_month = subs / months
    to_go = (target_subs or 0) - subs
    return {
        "start": start,
        "months_active": round(months, 1),
        "subs_per_month": round(per_month, 1),
        "months_to_target": round(to_go / per_month, 1) if to_go > 0 and per_month > 0 else None,
        # A straight line through a few months of a tiny channel says very little; flag it.
        "reliable": months >= 3 and subs >= 50,
    }


def compute_growth(profile: dict, creators: dict, look_s: list[dict], names: dict, cfg: dict, now: datetime) -> dict:
    reach = float((cfg.get("growth") or {}).get("reach_multiple", REACH_MULTIPLE))
    ch, st = profile["channel"], profile["stats"]
    user_subs = ch.get("subs")
    user_views = _known(st.get("median_views_long"))

    deals: dict[str, dict[str, dict[str, list]]] = defaultdict(lambda: {"sponsored": defaultdict(list),
                                                                         "code": defaultdict(list)})
    for s in look_s:
        if s["type"] in ("sponsored", "code") and not s.get("own"):
            deals[s["channel_id"]][s["type"]][s["brand_key"]].append(s)

    def entry(cr: dict, by_brand: dict) -> dict:
        latest = max((s for ss in by_brand.values() for s in ss), key=lambda s: s.get("published_at") or "")
        return {
            "id": cr["id"], "title": cr["title"], "url": _channel_url(cr), "subs": cr.get("subs"),
            "median_views_long": _known(cr.get("median_views_long")),
            "median_views_shorts": _known(cr.get("median_views_shorts")),
            "language": cr.get("language"),
            "brands": sorted({names.get(k) or (ss[0].get("domain") or k) for k, ss in by_brand.items()}),
            "proof_url": latest["video_url"], "proof_title": latest["title"],
            "proof_brand": names.get(latest["brand_key"]) or latest.get("domain") or latest["brand_key"],
            "within_reach": within_reach(cr, user_subs, user_views, reach),
            "top_videos": cr.get("top_videos", []),
            **_habits(cr),
        }

    paid, coded = [], []
    for cid, d in deals.items():
        cr = creators.get(cid)
        if not cr or cr.get("own"):
            continue
        if d["sponsored"]:
            paid.append(entry(cr, d["sponsored"]))
        if d["code"]:
            coded.append(entry(cr, d["code"]))

    realistic = sorted({b for e in paid if e["within_reach"] for b in e["brands"]})
    start_now_codes = sorted({b for e in coded if e["within_reach"] for b in e["brands"]} - set(realistic))

    basis = "sponsored" if paid else ("code" if coded else None)
    pool = paid or coded
    by_subs = sorted((e for e in pool if e["subs"] is not None), key=lambda e: e["subs"])
    by_views = sorted((e for e in pool if e["median_views_long"]), key=lambda e: e["median_views_long"])
    floor_subs = by_subs[0] if by_subs else None
    floor_views = by_views[0] if by_views else None
    target = {"subs": floor_subs["subs"] if floor_subs else None,
              "median_views": round(floor_views["median_views_long"]) if floor_views else None}
    entry_level = None
    if len(by_subs) >= 4:
        entry_level = {"subs": round(_nearest_rank([e["subs"] for e in by_subs], 0.25)),
                       "median_views": round(_nearest_rank([e["median_views_long"] for e in by_views], 0.25))
                       if len(by_views) >= 4 else None,
                       "n": len(by_subs)}

    ladder = by_subs[:5]
    scanned = [c for c in creators.values() if not c.get("own")]
    scanned_subs = [c["subs"] for c in scanned if c.get("subs") is not None]
    you = {"subs": user_subs, "median_views_long": user_views,
           "median_views_shorts": _known(st.get("median_views_shorts")),
           "long_count": st.get("long_count"), "short_count": st.get("short_count"),
           **_habits({**st, "subs": user_subs})}
    out = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reach_multiple": reach,
        "realistic": bool(realistic),
        "realistic_brands": realistic,
        "start_now_codes": start_now_codes,
        "basis": basis,
        "you": you,
        "target": target,
        "floor_subs": floor_subs,
        "floor_views": floor_views,
        "entry_level": entry_level,
        "gap": {"subs_x": _x(target["subs"], user_subs), "views_x": _x(target["median_views"], user_views),
                "subs_to_go": max(0, target["subs"] - (user_subs or 0)) if target["subs"] else None},
        "milestones_subs": milestones(user_subs, target["subs"]),
        "ladder": ladder,
        "habits": {"you": _habits({**st, "subs": user_subs}),
                   "floor_creators": {k: _median_of(ladder, k) for k in
                                      ("uploads_per_month_90d", "shorts_share", "median_duration_long_min",
                                       "views_per_100_subs")}},
        "pace": _pace(profile, now, target["subs"]),
        "coverage": {"creators_scanned": len(scanned), "paid_creators": len(paid), "code_creators": len(coded),
                     "smallest_scanned_subs": min(scanned_subs) if scanned_subs else None},
    }
    out["verdict"] = verdict(out)
    return out


def verdict(g: dict) -> str:
    """One deterministic paragraph; the report, the CLI and Claude all quote this instead of paraphrasing numbers."""
    r = g["reach_multiple"]
    you, t = g["you"], g["target"]
    you_txt = f"{fmt_int(you['subs'])} subscribers" + (
        f" and {fmt_int(you['median_views_long'])} median views per video" if you["median_views_long"] else "")
    if g["realistic"]:
        n = len(g["realistic_brands"])
        return (f"{n} brand{'s' if n != 1 else ''} paid creators within {r:g}x of your size "
                f"({you_txt}): {', '.join(g['realistic_brands'][:8])}.")
    cov = g["coverage"]
    if not g["basis"]:
        return (f"No brand deals found among the {cov['creators_scanned']} creators scanned, so there's no growth "
                "target from this data. Broaden the niche queries and rerun.")
    paid = g["basis"] == "sponsored"
    fs, fv = g["floor_subs"], g["floor_views"]
    lead = (f"No brand paid a creator within {r:g}x of your size ({you_txt}). " if paid else
            f"No disclosed paid sponsorships turned up among {cov['creators_scanned']} creators, only promo-code deals. ")
    who = "paid" if paid else "gave a promo code to"
    parts = [lead]
    if fs:
        parts.append(f"The smallest creator a brand {who}: {fs['title']}, {fmt_int(fs['subs'])} subscribers"
                     + (f" and {fmt_int(fs['median_views_long'])} median views" if fs["median_views_long"] else "")
                     + f" ({fs['proof_brand']}, {fs['proof_url']}). ")
    if fv and fs and fv["id"] != fs["id"]:
        parts.append(f"Lowest views on a {'paid' if paid else 'code'} deal: {fv['title']}, "
                     f"{fmt_int(fv['median_views_long'])} median views ({fv['proof_brand']}, {fv['proof_url']}). ")
    goal = " and ".join(x for x in (f"{fmt_int(t['subs'])} subscribers" if t["subs"] else "",
                                    f"{fmt_int(t['median_views'])} views per video" if t["median_views"] else "") if x)
    if goal:
        parts.append(f"Growth target: {goal}.")
    return "".join(parts).strip()
