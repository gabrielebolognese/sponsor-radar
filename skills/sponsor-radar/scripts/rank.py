"""Rank brands: size fit x recency x repeat rate x language fit. Every brand keeps its proof links."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from common import age_days, iso, read_json, slug, write_json
from signals import brand_key

DEFAULT_WEIGHTS = {
    "strength": {"sponsored": 1.0, "code": 0.6, "affiliate": 0.3},
    "half_life_days": 30,
    "size_fit": {"core": 1.0, "smaller": 0.8, "bigger": 0.5, "giant": 0.25},
    "repeat_step": 0.5,
    "repeat_cap": 2.5,
    "lang_mismatch": 0.6,
    "min_confidence": 0.6,
}
DEAL_TYPES = ("sponsored", "code", "affiliate")


def weights(cfg: dict) -> dict:
    w = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_WEIGHTS.items()}
    for k, v in (cfg.get("weights") or {}).items():
        if isinstance(v, dict) and isinstance(w.get(k), dict):
            w[k].update(v)
        else:
            w[k] = v
    return w


def size_class(creator: dict, user_median: float, mode: str) -> str:
    cm = creator.get("median_views_long") or 0
    if mode != "ugc" and user_median > 0 and cm > 0:
        r = cm / user_median
        if 0.5 <= r <= 3:
            return "core"
        if r < 0.5:
            return "smaller"
        return "bigger" if r <= 10 else "giant"
    return {"core": "core", "smaller": "smaller", "bigger": "bigger"}.get(creator.get("band"), "bigger")


def expand_classified(ambiguous: list[dict], classified: dict, min_conf: float) -> tuple[list[dict], dict]:
    """Turn Claude's verdicts on ambiguous items into sightings."""
    items = {a["id"]: a for a in ambiguous}
    out, names = [], {}
    for r in classified.get("results", []):
        a = items.get(r.get("id"))
        if not a or r.get("type") not in DEAL_TYPES:
            continue
        if float(r.get("confidence", 0)) < min_conf:
            continue
        domain = (r.get("domain") or a.get("domain") or "").lower().strip() or None
        key = brand_key(domain) if domain else slug(r.get("brand", ""))
        if not key:
            continue
        if r.get("brand"):
            names.setdefault(key, r["brand"])
        base = {"brand_key": key, "domain": domain, "type": r["type"], "code": r.get("code"),
                "evidence": r.get("evidence_quote") or a.get("sample_evidence") or a.get("description_excerpt", "")[:240],
                "signals": ["claude:" + a["kind"]], "source": "claude", "channel_id": a["channel_id"],
                "channel_title": a["channel_title"], "own": a.get("own", False), "link": None, "network": None}
        videos = a["videos"] if a["kind"] == "evergreen" else [a]
        for v in videos:
            out.append({**base, "id": f"{a['id']}:{v['video_id']}", "video_id": v["video_id"],
                        "video_url": v["video_url"], "title": v["title"], "published_at": v["published_at"],
                        "views": v.get("views")})
    for k, v in (classified.get("names") or {}).items():
        names[k] = v
    return out, names


def run_rank(run_dir, cfg: dict, now: datetime) -> dict:
    w = weights(cfg)
    profile = read_json(run_dir / "profile.json")
    niche = read_json(run_dir / "niche.json", default={})
    creators = {c["id"]: c for c in read_json(run_dir / "creators.json")}
    sightings = read_json(run_dir / "sightings.json")
    ambiguous = read_json(run_dir / "ambiguous.json", default=[])
    classified = read_json(run_dir / "classified.json", default={"results": []})
    extra, names = expand_classified(ambiguous, classified, w["min_confidence"])
    aliases = {slug(k): slug(v) for k, v in (classified.get("aliases") or {}).items()}
    excluded_brands = {slug(x) for x in classified.get("exclude_brands", [])}

    all_s = sightings + extra
    for s in all_s:
        s["brand_key"] = aliases.get(s["brand_key"], s["brand_key"])
    all_s = [s for s in all_s if s["brand_key"] and s["brand_key"] not in excluded_brands]

    mode = profile["mode"]
    user_median = profile["stats"].get("median_views_long") or 0
    user_lang = (niche.get("language") or profile["stats"].get("language") or "").lower() or None
    own_rows = [c for c in creators.values() if c.get("own")]
    own_scanned = own_rows[0]["videos_scanned"] if own_rows else 0
    own_s = [s for s in all_s if s.get("own")]
    look_s = [s for s in all_s if not s.get("own")]
    own_by_brand = defaultdict(list)
    for s in own_s:
        own_by_brand[s["brand_key"]].append(s)
    user_has_sponsors = any(s["type"] in ("sponsored", "code") for s in own_s)

    brands: dict[str, dict] = {}
    for s in look_s:
        cr = creators.get(s["channel_id"], {})
        sc = size_class(cr, user_median, mode)
        age = age_days(s["published_at"], now)
        val = w["strength"][s["type"]] * 0.5 ** (age / w["half_life_days"]) * w["size_fit"][sc]
        b = brands.setdefault(s["brand_key"], {"key": s["brand_key"], "domains": defaultdict(int),
                                               "creators": {}, "sightings": []})
        if s.get("domain"):
            b["domains"][s["domain"]] += 1
        ce = b["creators"].setdefault(s["channel_id"], {"title": s["channel_title"], "size": sc,
                                                        "lang": cr.get("language"), "best": 0.0,
                                                        "deal_videos": set(), "types": set()})
        ce["best"] = max(ce["best"], val)
        ce["types"].add(s["type"])
        if s["type"] in ("sponsored", "code"):
            ce["deal_videos"].add(s["video_id"])
        b["sightings"].append({**s, "_age": age, "_size": sc})

    ranked, affiliate_only = [], []
    for key, b in brands.items():
        ss = b["sightings"]
        types = {s["type"] for s in ss}
        top_type = next(t for t in DEAL_TYPES if t in types)
        repeat, repeat_creator = 0, None
        for ce in b["creators"].values():
            if len(ce["deal_videos"]) > repeat:
                repeat, repeat_creator = len(ce["deal_videos"]), ce["title"]
        repeat_mult = min(w["repeat_cap"], 1 + w["repeat_step"] * max(0, repeat - 1))
        langs = {ce["lang"] for ce in b["creators"].values() if ce["lang"]}
        lang_fit = 1.0 if (not user_lang or not langs or user_lang in langs) else w["lang_mismatch"]
        score = sum(ce["best"] for ce in b["creators"].values()) * repeat_mult * lang_fit
        deal_creators = [ce for ce in b["creators"].values() if ce["types"] & {"sponsored", "code"}]
        n_core = sum(1 for ce in deal_creators if ce["size"] == "core")
        last = min(s["_age"] for s in ss)
        domain = max(b["domains"], key=b["domains"].get) if b["domains"] else None
        proofs = sorted(ss, key=lambda s: (DEAL_TYPES.index(s["type"]), s["_age"]))
        seen, proof_rows = set(), []
        for s in proofs:
            if s["video_id"] in seen:
                continue
            seen.add(s["video_id"])
            proof_rows.append({"video_url": s["video_url"], "title": s["title"], "channel": s["channel_title"],
                               "published_at": s["published_at"], "type": s["type"], "code": s.get("code"),
                               "evidence": (s.get("evidence") or "")[:200]})
            if len(proof_rows) >= 5:
                break

        own_hits = own_by_brand.get(key, [])
        labels = []
        if n_core:
            labels.append(f"{n_core} creator{'s' if n_core != 1 else ''} your size")
        elif deal_creators and all(ce["size"] in ("bigger", "giant") for ce in deal_creators):
            labels.append("only sponsors bigger creators")
        if repeat >= 2:
            labels.append(f"came back {repeat}x to {repeat_creator}")
        own_status = None
        if own_hits:
            own_last = min(age_days(s["published_at"], now) for s in own_hits)
            if own_last > 90:
                own_status = "renewal"
                labels.append(f"renewal: worked with you {int(own_last // 30)} months ago")
            else:
                own_status = "current"
                labels.append("already works with you")
        elif own_scanned and top_type in ("sponsored", "code") and (user_has_sponsors or mode == "conquest"):
            own_status = "never"
            labels.append("sponsors your competitors, never you" if top_type == "sponsored"
                          else "works with your competitors, never you")
        if lang_fit < 1:
            labels.append("different language")

        why_bits = []
        if deal_creators:
            why_bits.append(f"{len(deal_creators)} creator{'s' if len(deal_creators) != 1 else ''} "
                            f"({n_core} your size)")
        why_bits.append(f"last seen {int(last)}d ago")
        if lang_fit == 1 and user_lang and user_lang in langs:
            why_bits.append(f"same language ({user_lang})")
        row = {
            "key": key, "name": names.get(key) or domain or key, "domain": domain, "score": round(score, 3),
            "type": top_type, "deal_types": [t for t in DEAL_TYPES if t in types],
            "hybrid": "sponsored" in types and bool(types & {"code", "affiliate"}),
            "n_creators": len(b["creators"]), "n_deal_creators": len(deal_creators), "n_core": n_core,
            "n_videos": len({s["video_id"] for s in ss}), "repeat_max": repeat, "repeat_creator": repeat_creator,
            "last_seen_days": int(last), "languages": sorted(langs),
            "codes": sorted({s["code"] for s in ss if s.get("code")})[:5],
            "networks": sorted({s["network"] for s in ss if s.get("network")}),
            "own_status": own_status, "labels": labels, "why": ", ".join(why_bits), "proofs": proof_rows,
            "creators": sorted({ce["title"] for ce in b["creators"].values()}),
        }
        if top_type == "affiliate" and mode != "ugc":
            affiliate_only.append(row)
        else:
            ranked.append(row)

    ranked.sort(key=lambda r: -r["score"])
    affiliate_only.sort(key=lambda r: -r["score"])
    for i, r in enumerate(ranked, 1):
        r["rank"] = i

    recent_core = [r for r in ranked if any(
        s["type"] == "sponsored" and s["_age"] <= 30 and s["_size"] == "core" for s in brands[r["key"]]["sightings"])]
    recent_core_incl_codes = [r for r in ranked if any(
        s["type"] in ("sponsored", "code") and s["_age"] <= 30 and s["_size"] == "core"
        for s in brands[r["key"]]["sightings"])]
    # own_status is only "renewal"/"current" when the brand appears on the user's channel
    never = [r for r in ranked if r["own_status"] in ("never", None) and r["type"] == "sponsored"]
    # "came back N times" is a paid-deal claim, so only disclosed sponsorships qualify for the headline
    top_repeat = max((r for r in ranked if r["type"] == "sponsored"), key=lambda r: r["repeat_max"], default=None)
    headline = {
        "sponsored_your_size_30d": len(recent_core),
        "sponsored_your_size_30d_brands": [r["name"] for r in recent_core][:30],
        "deals_your_size_30d_incl_codes": len(recent_core_incl_codes),
        "never_sponsored_you": len(never) if own_scanned else None,
        "never_sponsored_you_brands": [r["name"] for r in never][:30] if own_scanned else [],
        "top_repeat": ({"brand": top_repeat["name"], "times": top_repeat["repeat_max"],
                        "creator": top_repeat["repeat_creator"]}
                       if top_repeat and top_repeat["repeat_max"] >= 2 else None),
        "brands_ranked": len(ranked),
        "affiliate_only": len(affiliate_only),
        "own_sponsors": sorted({names.get(k) or k for k, v in own_by_brand.items()
                                if any(s["type"] in ("sponsored", "code") for s in v)}),
    }
    out = {"generated_at": iso(now), "mode": mode, "headline": headline, "brands": ranked,
           "affiliate_only": affiliate_only, "weights": w}
    write_json(run_dir / "brands.json", out)
    return out
