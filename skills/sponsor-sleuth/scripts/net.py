"""Polite HTTP helpers: link resolution (cached) and page fetching with robots.txt + per-host rate limits."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

from common import USER_AGENT

_HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en,it;q=0.8,es;q=0.6,de;q=0.5,fr;q=0.5"}


class HostThrottle:
    def __init__(self, min_interval: float = 1.0):
        self.min_interval = min_interval
        self.last: dict[str, float] = {}
        self.lock = threading.Lock()

    def wait(self, host: str) -> None:
        with self.lock:
            now = time.monotonic()
            nxt = self.last.get(host, 0) + self.min_interval
            delay = max(0.0, nxt - now)
            self.last[host] = now + delay
        if delay:
            time.sleep(delay)


class LinkResolver:
    """Follow redirects of shortener/affiliate links to find the brand. Results are cached forever,
    so each link is requested at most once (resolving a tracking link registers a click)."""

    def __init__(self, cache_path=None, enabled: bool = True, timeout: float = 6.0):
        self.enabled = enabled
        self.timeout = timeout
        self.throttle = HostThrottle(0.25)
        self.db = sqlite3.connect(str(cache_path) if cache_path else ":memory:", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS links (url TEXT PRIMARY KEY, final TEXT, fetched REAL)")
        self.db.commit()
        self.resolved = 0

    def __call__(self, url: str) -> str | None:
        if not self.enabled:
            return None
        row = self.db.execute("SELECT final FROM links WHERE url=?", (url,)).fetchone()
        if row is not None:
            return row[0] or None
        final = self._resolve(url)
        self.db.execute("INSERT OR REPLACE INTO links VALUES (?, ?, ?)", (url, final or "", time.time()))
        self.db.commit()
        self.resolved += 1
        return final

    def _resolve(self, url: str) -> str | None:
        host = urllib.parse.urlsplit(url).hostname or ""
        self.throttle.wait(host)
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(url, method=method, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return r.geturl()
            except urllib.error.HTTPError as e:
                if method == "HEAD" and e.code in (400, 403, 404, 405, 429, 501):
                    continue
                return e.geturl() if e.geturl() != url else None
            except Exception:
                return None
        return None


class PageFetcher:
    """Fetch public pages, respecting robots.txt and 1 request/second per host."""

    def __init__(self, timeout: float = 8.0, min_interval: float = 1.0, max_bytes: int = 400_000):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.throttle = HostThrottle(min_interval)
        self.robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.lock = threading.Lock()

    def _raw(self, url: str) -> tuple[int, str, str]:
        host = urllib.parse.urlsplit(url).hostname or ""
        self.throttle.wait(host)
        req = urllib.request.Request(url, headers=_HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = r.read(self.max_bytes)
                charset = r.headers.get_content_charset() or "utf-8"
                return r.status, r.geturl(), data.decode(charset, errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.geturl() or url, ""
        except Exception:
            return 0, url, ""

    def allowed(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self.lock:
            known = base in self.robots
        if not known:
            status, _, text = self._raw(base + "/robots.txt")
            rp = None
            if status == 200 and text:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(text.splitlines())
            with self.lock:
                self.robots[base] = rp
        rp = self.robots.get(base)
        return True if rp is None else rp.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> tuple[int, str, str]:
        if not self.allowed(url):
            return -1, url, ""
        return self._raw(url)


_HREF = re.compile(r"<a\b[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def page_links(html: str, base_url: str) -> list[tuple[str, str]]:
    out = []
    for href, inner in _HREF.findall(html or ""):
        text = " ".join(_TAGS.sub(" ", inner).split())[:120]
        out.append((urllib.parse.urljoin(base_url, href.strip()), text))
    return out


def page_title(html: str) -> str:
    m = _TITLE.search(html or "")
    return " ".join(_TAGS.sub(" ", m.group(1)).split())[:200] if m else ""
