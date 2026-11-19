"""YouTube Data API v3 client with response cache, quota ledger, batching and retries.

Only public data is read, with an API key (no OAuth). Costs per call follow the
official quota table: search.list = 100 units, everything else used here = 1 unit.
"""
from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from common import USER_AGENT, chunks, iso, parse_iso, unique

API_ROOT = "https://www.googleapis.com/youtube/v3/"
COST = {"search": 100, "channels": 1, "playlistItems": 1, "videos": 1, "channelSections": 1}
DAILY_QUOTA = 10_000
# Search results are stable enough for a week; stats and uploads change daily.
TTL_SECONDS = {"search": 7 * 86400}
DEFAULT_TTL = 20 * 3600

QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
RETRY_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}


class YouTubeError(Exception):
    def __init__(self, message: str, status: int = 0, reason: str = ""):
        super().__init__(message)
        self.status = status
        self.reason = reason


class QuotaExceeded(YouTubeError):
    pass


def http_transport(url: str, timeout: int = 30) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = {"error": {"message": str(e)}}
        return e.code, body


def quota_day(now: datetime | None = None) -> str:
    """Quota resets at midnight Pacific time. UTC-8 is close enough for a ledger."""
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=8)).strftime("%Y-%m-%d")


def _error_info(body: dict) -> tuple[str, str]:
    err = (body or {}).get("error", {}) or {}
    errors = err.get("errors") or [{}]
    return errors[0].get("reason", "") or "", err.get("message", "") or ""


class YouTube:
    def __init__(self, api_key: str, cache_path=None, transport=None, sleep=time.sleep):
        self.key = api_key
        self.transport = transport or http_transport
        self.sleep = sleep
        self.units_this_run = 0
        self.requests = 0
        self.cache_hits = 0
        self.paid_part_supported = True
        self.db = sqlite3.connect(str(cache_path) if cache_path else ":memory:")
        self.db.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, fetched REAL, body TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS ledger (day TEXT, endpoint TEXT, units INTEGER)")
        self.db.commit()

    # ---------- core ----------

    def _charge(self, endpoint: str) -> None:
        units = COST.get(endpoint, 1)
        self.units_this_run += units
        self.requests += 1
        self.db.execute("INSERT INTO ledger VALUES (?, ?, ?)", (quota_day(), endpoint, units))
        self.db.commit()

    def _get(self, endpoint: str, params: dict) -> dict:
        params = {k: v for k, v in params.items() if v not in (None, "")}
        ck = endpoint + "?" + urllib.parse.urlencode(sorted(params.items()))
        ttl = TTL_SECONDS.get(endpoint, DEFAULT_TTL)
        row = self.db.execute("SELECT fetched, body FROM cache WHERE k=?", (ck,)).fetchone()
        if row and time.time() - row[0] < ttl:
            self.cache_hits += 1
            return json.loads(row[1])

        url = API_ROOT + endpoint + "?" + urllib.parse.urlencode({**params, "key": self.key})
        last = ""
        for attempt in range(4):
            self._charge(endpoint)
            status, body = self.transport(url)
            if status == 200:
                self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                                (ck, time.time(), json.dumps(body)))
                self.db.commit()
                return body
            reason, message = _error_info(body)
            last = f"{endpoint} HTTP {status} {reason}: {message}"
            if reason in QUOTA_REASONS:
                raise QuotaExceeded(
                    "YouTube API daily quota exhausted (resets at midnight Pacific). "
                    "Cached results still work; rerun tomorrow or use another key.", status, reason)
            if status in (429, 500, 502, 503, 504) or reason in RETRY_REASONS:
                self.sleep(2 ** attempt)
                continue
            raise YouTubeError(last, status, reason)
        raise YouTubeError("gave up after retries: " + last)

    def quota_used_today(self) -> int:
        row = self.db.execute("SELECT COALESCE(SUM(units), 0) FROM ledger WHERE day=?", (quota_day(),)).fetchone()
        return int(row[0])

    # ---------- endpoints ----------

    def channel(self, handle: str | None = None, channel_id: str | None = None) -> dict | None:
        params = {"part": "snippet,statistics,contentDetails,brandingSettings,topicDetails"}
        if handle:
            params["forHandle"] = handle if handle.startswith("@") else "@" + handle
        else:
            params["id"] = channel_id
        items = self._get("channels", params).get("items", [])
        return items[0] if items else None

    def channels(self, ids, parts: str = "snippet,statistics,contentDetails") -> list[dict]:
        out = []
        for batch in chunks(unique(ids), 50):
            out += self._get("channels", {"part": parts, "id": ",".join(batch), "maxResults": 50}).get("items", [])
        return out

    def upload_ids(self, uploads_playlist: str, since: datetime, max_items: int = 30) -> list[str]:
        """Video ids from a channel's uploads playlist (newest first), back to `since`."""
        ids, token = [], None
        while len(ids) < max_items:
            body = self._get("playlistItems", {"part": "contentDetails", "playlistId": uploads_playlist,
                                               "maxResults": 50, "pageToken": token})
            stop = False
            for it in body.get("items", []):
                cd = it.get("contentDetails", {})
                pub = cd.get("videoPublishedAt")
                if pub and parse_iso(pub) < since:
                    stop = True
                    break
                if cd.get("videoId"):
                    ids.append(cd["videoId"])
                if len(ids) >= max_items:
                    break
            token = body.get("nextPageToken")
            if stop or not token:
                break
        return ids

    def videos(self, ids) -> list[dict]:
        out = []
        for batch in chunks(unique(ids), 50):
            parts = "snippet,contentDetails,statistics"
            if self.paid_part_supported:
                parts += ",paidProductPlacementDetails"
            try:
                body = self._get("videos", {"part": parts, "id": ",".join(batch), "maxResults": 50})
            except QuotaExceeded:
                raise
            except YouTubeError as e:
                # If the paid-placement part is ever rejected, fall back to text signals only.
                if self.paid_part_supported and e.status == 400:
                    self.paid_part_supported = False
                    body = self._get("videos", {"part": "snippet,contentDetails,statistics",
                                                "id": ",".join(batch), "maxResults": 50})
                else:
                    raise
            out += body.get("items", [])
        return out

    def search_videos(self, q: str, published_after: datetime, language: str | None = None,
                      region: str | None = None, max_results: int = 50) -> list[dict]:
        body = self._get("search", {
            "part": "snippet", "type": "video", "q": q, "maxResults": max_results,
            "order": "relevance", "publishedAfter": iso(published_after),
            "relevanceLanguage": language, "regionCode": region,
        })
        return body.get("items", [])

    def featured_channel_ids(self, channel_id: str) -> list[str]:
        try:
            body = self._get("channelSections", {"part": "snippet,contentDetails", "channelId": channel_id})
        except QuotaExceeded:
            raise
        except YouTubeError:
            return []
        ids = []
        for s in body.get("items", []):
            if (s.get("snippet", {}).get("type") or "").lower() == "multiplechannels":
                ids += s.get("contentDetails", {}).get("channels", []) or []
        return ids
