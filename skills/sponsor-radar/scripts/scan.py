"""Scan lookalikes (last 90 days) and the user's own channel (last 12 months) for sponsor signals."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from channel import creator_stats, video_summary
from common import read_json, slug, unique, write_json
from signals import analyze_description, analyze_transcript, video_candidates
from yt import QuotaExceeded, YouTubeError

LOOKALIKE_DAYS, LOOKALIKE_MAX = 90, 30
OWN_DAYS, OWN_MAX = 365, 100
MAX_AMBIGUOUS = 150
TRANSCRIPT_LANGS = ["en", "it", "es", "de", "fr", "pt"]


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _sighting(cand: dict, v: dict, c: dict, sid: str, source: str = "description") -> dict:
    return {
        "id": sid, "brand_key": cand["brand_key"], "domain": cand.get("domain"), "type": cand["type"],
        "signals": cand.get("signals", []), "code": cand.get("code"), "link": cand.get("link"),
        "evidence": cand.get("evidence"), "network": cand.get("network"), "source": source,
        "video_id": v["id"], "video_url": video_url(v["id"]), "title": v["title"],
        "published_at": v["published_at"], "views": v["views"],
        "channel_id": c["id"], "channel_title": c["title"], "own": bool(c.get("own")),
    }


def run_scan(yt, run_dir, cfg: dict, now: datetime, resolver=None, transcripts=None) -> dict:
    profile = read_json(run_dir / "profile.json")
    lookalikes = read_json(run_dir / "lookalikes.json")["creators"]
    own = {**profile["channel"], "band": "own", "own": True}
    creators = lookalikes + [own]
    errors: list[str] = []

    uploads: dict[str, list[str]] = {}
    for c in creators:
        if not c.get("uploads"):
            uploads[c["id"]] = []
            continue
        is_own = bool(c.get("own"))
        since = now - timedelta(days=OWN_DAYS if is_own else LOOKALIKE_DAYS)
        try:
            uploads[c["id"]] = yt.upload_ids(c["uploads"], since, OWN_MAX if is_own else LOOKALIKE_MAX)
        except QuotaExceeded:
            raise
        except YouTubeError as e:
            errors.append(f"{c['title']}: {e}")
            uploads[c["id"]] = []

    all_ids = unique(i for ids in uploads.values() for i in ids)
    vids = {v["id"]: v for v in (video_summary(x) for x in yt.videos(all_ids))}

    sightings, ambiguous, creator_rows, queue = [], [], [], []
    counter = {"s": 0, "a": 0}

    def nid(prefix: str) -> str:
        counter[prefix] += 1
        return f"{prefix}{counter[prefix]}"

    for c in creators:
        vs = [vids[i] for i in uploads[c["id"]] if i in vids]
        st = creator_stats(vs, now)
        creator_rows.append({
            "id": c["id"], "title": c["title"], "handle": c.get("handle"), "subs": c.get("subs"),
            "band": c.get("band"), "own": bool(c.get("own")), "videos_scanned": len(vs), **st,
        })
        per_video = []
        for v in vs:
            an = analyze_description(v["description"])
            cands, needs = video_candidates(v, an, c, resolver)
            if needs is not None:
                needs["candidate_domains"] = {k["brand_key"]: k.get("domain") for k in cands}
                for L in an["links"]:
                    if L.get("kind") == "brand":
                        needs["candidate_domains"].setdefault(slug(L["domain"].split(".")[0]), L["domain"])
            per_video.append([v, cands, needs])

        # Evergreen filter: a domain in most of a creator's videos is usually their own site,
        # a gear list or a standing affiliate code. Let Claude decide, once, for the whole group.
        n = len(vs)
        counts = Counter(k for _, cands, _ in per_video for k in {x["brand_key"] for x in cands})
        for key, cnt in counts.items():
            if n < 5 or cnt < 4 or cnt / n < 0.6:
                continue
            group = [(v, x) for v, cands, _ in per_video for x in cands if x["brand_key"] == key]
            disclosed = all(any(s.startswith("phrase:") or s == "paid_flag_top_link" for s in x["signals"])
                            for _, x in group)
            if disclosed:
                continue  # a disclosed long-term sponsor: keep, it's a strong repeat signal
            for row in per_video:
                row[1] = [x for x in row[1] if x["brand_key"] != key]
            group.sort(key=lambda g: g[0]["published_at"] or "", reverse=True)
            ambiguous.append({
                "id": nid("a"), "kind": "evergreen", "own": bool(c.get("own")),
                "channel_id": c["id"], "channel_title": c["title"],
                "brand_key": key, "domain": group[0][1].get("domain"),
                "in_videos": f"{cnt} of {n}", "types_seen": sorted({x["type"] for _, x in group}),
                "codes": sorted({x["code"] for _, x in group if x.get("code")}),
                "sample_evidence": group[0][1].get("evidence"),
                "videos": [{"video_id": v["id"], "video_url": video_url(v["id"]), "title": v["title"],
                            "published_at": v["published_at"], "views": v["views"]} for v, _ in group],
            })

        for v, cands, needs in per_video:
            for x in cands:
                sightings.append(_sighting(x, v, c, nid("s")))
            if needs:
                queue.append((v, c, needs))

    # Transcripts: only for videos that are disclosed as paid but whose brand we couldn't pin down.
    queue.sort(key=lambda q: q[0]["published_at"] or "", reverse=True)
    by_video_key = {(s["video_id"], s["brand_key"]): s for s in sightings}
    video_items = []
    for v, c, needs in queue:
        tr = None
        if transcripts is not None and transcripts.available and not transcripts.stopped_reason:
            langs = unique([x for x in [v.get("language"), *TRANSCRIPT_LANGS] if x])
            text = transcripts.get(v["id"], langs)
            keys = list(needs["candidate_domains"]) + [slug(h) for h in needs["hints"]]
            tr = analyze_transcript(text, keys) if text else None
        if tr and len(tr["matched_keys"]) == 1 and needs["candidate_domains"].get(tr["matched_keys"][0]):
            key = tr["matched_keys"][0]
            existing = by_video_key.get((v["id"], key))
            if existing:
                existing["type"] = "sponsored"
                existing["signals"] = existing["signals"] + ["transcript_ad_read"]
            else:
                s = _sighting({"brand_key": key, "domain": needs["candidate_domains"][key], "type": "sponsored",
                               "signals": ["transcript_ad_read"] + (["paid_flag"] if v["paid_flag"] else []),
                               "evidence": tr["snippet"][:240]}, v, c, nid("s"), source="transcript")
                sightings.append(s)
                by_video_key[(v["id"], key)] = s
            continue
        if not tr and not needs["snippet"].strip() and not needs["hints"]:
            continue
        video_items.append({
            "id": nid("a"), "kind": "video", "own": bool(c.get("own")),
            "channel_id": c["id"], "channel_title": c["title"],
            "video_id": v["id"], "video_url": video_url(v["id"]), "title": v["title"],
            "published_at": v["published_at"], "views": v["views"], "paid_flag": v["paid_flag"],
            "reasons": needs["reasons"], "hints": needs["hints"],
            "candidate_domains": needs["candidate_domains"],
            "description_excerpt": needs["snippet"],
            "transcript_excerpt": tr["snippet"] if tr else None,
        })

    room = max(0, MAX_AMBIGUOUS - len(ambiguous))
    dropped = max(0, len(video_items) - room)
    ambiguous += video_items[:room]

    write_json(run_dir / "sightings.json", sightings)
    write_json(run_dir / "ambiguous.json", ambiguous)
    write_json(run_dir / "creators.json", creator_rows)
    stats = {
        "creators_scanned": len(lookalikes),
        "videos_scanned": sum(r["videos_scanned"] for r in creator_rows if not r["own"]),
        "own_videos_scanned": next((r["videos_scanned"] for r in creator_rows if r["own"]), 0),
        "sightings": len(sightings),
        "sightings_by_type": dict(Counter(s["type"] for s in sightings)),
        "ambiguous": len(ambiguous), "ambiguous_dropped": dropped,
        "paid_flag_videos": sum(1 for v in vids.values() if v["paid_flag"]),
        "paid_flag_supported": getattr(yt, "paid_part_supported", True),
        "transcripts": transcripts.stats() if transcripts is not None else {"available": False},
        "links_resolved": getattr(resolver, "resolved", 0),
        "quota_units_this_run": getattr(yt, "units_this_run", 0),
        "errors": errors[:20],
    }
    write_json(run_dir / "scan_stats.json", stats)
    return stats
