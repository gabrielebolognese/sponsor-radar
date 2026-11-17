"""Best-effort transcript fetching.

The official API only returns captions for videos you own, so this uses the optional
`youtube-transcript-api` package. YouTube rate-limits and blocks it from time to time,
so everything here is capped, throttled and allowed to fail: sponsor detection works
without transcripts, they only help name the brand when a video is flagged as paid
promotion but its description doesn't say who paid.
"""
from __future__ import annotations

import time

BLOCK_HINTS = ("Block", "TooMany", "PoToken", "AgeRestricted")


def _default_backend():
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        return None

    def backend(video_id: str, languages: list[str]):
        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):  # 1.x
            data = api.fetch(video_id, languages=languages)
            return [(s.text, s.start) for s in data]
        data = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)  # 0.x
        return [(d["text"], d["start"]) for d in data]

    return backend


class TranscriptFetcher:
    def __init__(self, max_fetches: int = 100, max_seconds: int = 150, delay: float = 1.0,
                 backend="default", sleep=time.sleep):
        self.backend = _default_backend() if backend == "default" else backend
        self.available = self.backend is not None
        self.max_fetches = max_fetches
        self.max_seconds = max_seconds
        self.delay = delay
        self.sleep = sleep
        self.attempts = 0
        self.fetched = 0
        self.failed = 0
        self.blocked = 0
        self._consecutive_blocks = 0
        self.stopped_reason = None if self.available else "youtube-transcript-api not installed"

    def get(self, video_id: str, languages: list[str]) -> str | None:
        if not self.available or self.stopped_reason:
            return None
        if self.attempts >= self.max_fetches:
            self.stopped_reason = f"cap of {self.max_fetches} reached"
            return None
        if self._consecutive_blocks >= 3:
            self.stopped_reason = "YouTube is blocking transcript requests from this network"
            return None
        if self.attempts:
            self.sleep(self.delay)
        self.attempts += 1
        try:
            rows = self.backend(video_id, languages)
        except Exception as e:  # the library raises many specific exception types
            if any(h in type(e).__name__ for h in BLOCK_HINTS):
                self.blocked += 1
                self._consecutive_blocks += 1
            else:
                self.failed += 1
            return None
        self._consecutive_blocks = 0
        self.fetched += 1
        return " ".join(str(t).replace("\n", " ") for t, start in rows if start <= self.max_seconds)

    def stats(self) -> dict:
        return {"available": self.available, "attempts": self.attempts, "fetched": self.fetched,
                "failed": self.failed, "blocked": self.blocked, "stopped_reason": self.stopped_reason}
