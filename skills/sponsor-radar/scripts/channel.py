"""Channel/video normalization, size modes and bands, and the user's profile."""
from __future__ import annotations

import html
from collections import Counter
from datetime import datetime, timedelta, timezone

from common import age_days, duration_seconds, iso, median

SHORT_MAX_SECONDS = 180  # Shorts can be up to 3 minutes since Oct 2024
MIN_AGE_FOR_MEDIAN_DAYS = 7  # brand-new videos haven't collected their views yet


def mode_for(subs: int | None) -> str:
    s = subs or 0
    if s < 1_000:
        return "ugc"
    if s < 50_000:
        return "micro"
    return "conquest"


def bands_for(subs: int | None) -> dict:
    """Subscriber bands of creators to scan. See references/modes.md."""
    s = subs or 0
    m = mode_for(s)
    if m == "ugc":
        return {"core": [2_000, 50_000], "bigger": [50_001, 300_000], "smaller": [500, 1_999]}
    if m == "micro":
        core_hi = max(3 * s, 5_000)
        return {"core": [int(0.5 * s), core_hi],
                "bigger": [core_hi + 1, max(10 * s, 50_000)],
                "smaller": [max(int(0.2 * s), 300), int(0.5 * s) - 1]}
    return {"core": [int(0.3 * s), 3 * s], "bigger": [3 * s + 1, 20 * s], "smaller": [int(0.1 * s), int(0.3 * s) - 1]}


def band_of(subs: int | None, bands: dict) -> str | None:
    if subs is None:
        return None
    for name in ("core", "bigger", "smaller"):
        lo, hi = bands[name]
        if lo <= subs <= hi:
            return name
    return None


def _int(x) -> int | None:
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def channel_summary(item: dict) -> dict:
    sn, st = item.get("snippet", {}), item.get("statistics", {})
    cd = item.get("contentDetails", {})
    hidden = st.get("hiddenSubscriberCount")
    return {
        "id": item.get("id"),
        "title": html.unescape(sn.get("title", "")),
        "handle": sn.get("customUrl", ""),
        "subs": None if hidden else _int(st.get("subscriberCount")),
        "views": _int(st.get("viewCount")),
        "video_count": _int(st.get("videoCount")),
        "country": sn.get("country"),
        "default_language": sn.get("defaultLanguage"),
        "description": (sn.get("description") or "")[:1500],
        "uploads": cd.get("relatedPlaylists", {}).get("uploads"),
        "topics": [t.rsplit("/", 1)[-1].replace("_", " ")
                   for t in item.get("topicDetails", {}).get("topicCategories", [])],
    }


def video_summary(item: dict) -> dict:
    sn, st, cd = item.get("snippet", {}), item.get("statistics", {}), item.get("contentDetails", {})
    dur = duration_seconds(cd.get("duration"))
    paid = (item.get("paidProductPlacementDetails") or {}).get("hasPaidProductPlacement")
    return {
        "id": item.get("id"),
        "channel_id": sn.get("channelId"),
        "title": html.unescape(sn.get("title", "")),
        "published_at": sn.get("publishedAt"),
        "description": sn.get("description") or "",
        "tags": (sn.get("tags") or [])[:12],
        "language": (sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "").split("-")[0].lower() or None,
        "duration_s": dur,
        "is_short": 0 < dur <= SHORT_MAX_SECONDS,
        "views": _int(st.get("viewCount")) or 0,
        "likes": _int(st.get("likeCount")),
        "comments": _int(st.get("commentCount")),
        "paid_flag": bool(paid),
    }


def creator_stats(videos: list[dict], now: datetime) -> dict:
    vids = sorted(videos, key=lambda v: v.get("published_at") or "", reverse=True)
    mature = [v for v in vids if v.get("published_at") and age_days(v["published_at"], now) >= MIN_AGE_FOR_MEDIAN_DAYS]
    long_ = [v for v in mature if not v["is_short"]][:10]
    shorts = [v for v in mature if v["is_short"]][:10]
    langs = Counter(v["language"] for v in vids if v.get("language"))
    recent90 = [v for v in vids if v.get("published_at") and age_days(v["published_at"], now) <= 90]
    return {
        "median_views_long": median([v["views"] for v in long_]),
        "median_views_shorts": median([v["views"] for v in shorts]),
        "long_count": len([v for v in vids if not v["is_short"]]),
        "short_count": len([v for v in vids if v["is_short"]]),
        "language": langs.most_common(1)[0][0] if langs else None,
        "uploads_per_month_90d": round(len(recent90) / 3, 1),
        "last_upload": vids[0]["published_at"] if vids else None,
        "paid_flag_count": sum(1 for v in vids if v.get("paid_flag")),
    }


def build_profile(yt, kind: str, value: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    item = yt.channel(handle=value) if kind == "handle" else yt.channel(channel_id=value)
    if not item:
        raise SystemExit(f"Channel not found: {value}. Check the handle (it must match youtube.com/{value}).")
    ch = channel_summary(item)
    ids = yt.upload_ids(ch["uploads"], since=now - timedelta(days=3650), max_items=50) if ch["uploads"] else []
    videos = [video_summary(v) for v in yt.videos(ids)]
    stats = creator_stats(videos, now)
    if not stats["language"] and ch.get("default_language"):
        stats["language"] = ch["default_language"].split("-")[0].lower()
    videos.sort(key=lambda v: v.get("published_at") or "", reverse=True)
    return {
        "created_at": iso(now),
        "input": value,
        "channel": ch,
        "stats": stats,
        "mode": mode_for(ch["subs"]),
        "bands": bands_for(ch["subs"]),
        "recent_videos": [{
            "title": v["title"], "published_at": v["published_at"], "views": v["views"],
            "is_short": v["is_short"], "paid_flag": v["paid_flag"], "tags": v["tags"][:8],
            "description": v["description"][:300],
        } for v in videos[:30]],
    }
