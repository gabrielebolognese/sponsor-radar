"""Offline fakes: a synthetic YouTube API, a transcript backend and a page fetcher. No network, no quota."""
from __future__ import annotations

import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "sponsor-radar" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
NOW_ISO = "2026-11-17T12:00:00Z"


def iso_days_ago(d: float) -> str:
    return (NOW - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ")


def channel(cid, title, handle, subs, country="IT"):
    return {"id": cid,
            "snippet": {"title": title, "customUrl": handle, "country": country, "description": f"{title} channel"},
            "statistics": {"subscriberCount": str(subs), "viewCount": "1000000", "videoCount": "100",
                           "hiddenSubscriberCount": False},
            "contentDetails": {"relatedPlaylists": {"uploads": "UU" + cid[2:]}},
            "topicDetails": {"topicCategories": ["https://en.wikipedia.org/wiki/Physical_fitness"]}}


def video(vid, cid, days_ago, desc, views=8000, dur="PT10M", paid=False, lang="it", title=None):
    return {"id": vid,
            "snippet": {"channelId": cid, "title": title or f"Video {vid}", "publishedAt": iso_days_ago(days_ago),
                        "description": desc, "defaultAudioLanguage": lang, "tags": ["calisthenics"]},
            "contentDetails": {"duration": dur},
            "statistics": {"viewCount": str(views), "likeCount": "100", "commentCount": "10"},
            "paidProductPlacementDetails": {"hasPaidProductPlacement": paid}}


PLAIN_IT = "Allenamento completo a corpo libero.\n\nInstagram: https://instagram.com/{h}"


class FakeYouTubeAPI:
    """Callable transport: url -> (status, json). Mimics the endpoints radar uses."""

    def __init__(self):
        self.calls = []
        self.channels, self.videos, self.playlists = {}, {}, {}
        self.handles = {}
        self.featured = {}
        self.search_channels = []
        self.reject_paid_part = False
        self._build()

    def add_channel(self, ch, vids):
        self.channels[ch["id"]] = ch
        self.handles[ch["snippet"]["customUrl"].lower()] = ch["id"]
        vids = sorted(vids, key=lambda v: v["snippet"]["publishedAt"], reverse=True)
        self.playlists[ch["contentDetails"]["relatedPlaylists"]["uploads"]] = [v["id"] for v in vids]
        for v in vids:
            self.videos[v["id"]] = v

    def _build(self):
        own = channel("UCown", "Marco Fit", "@marcofit", 12000)
        own_v = [video(f"o{i}", "UCown", 5 + i * 14, PLAIN_IT.format(h="marcofit"), views=8000) for i in range(10)]
        own_v.append(video("o11", "UCown", 200, "Video sponsorizzato da MyProtein: https://www.myprotein.it/marco",
                           views=7000))
        self.add_channel(own, own_v)

        a = channel("UCa", "Luca Calisthenics", "@lucacali", 15000)
        nord_it = "Questo video è sponsorizzato da NordVPN! Vai su https://nordvpn.com/luca per il 70% di sconto\n\nInstagram: https://instagram.com/luca"
        a_v = [video("a1", "UCa", 5, nord_it, views=9000),
               video("a2", "UCa", 35, nord_it, views=9000),
               video("a3", "UCa", 65, "This video is sponsored by NordVPN\nhttps://nordvpn.com/luca\n\nGear below", views=9000),
               video("a4", "UCa", 20, "Le mie scarpe Gymshark: usa il codice LUCA10 https://gymshark.com/luca", views=9000)]
        a_v += [video(f"a{i}", "UCa", 10 + i * 9, PLAIN_IT.format(h="luca"), views=9000) for i in range(5, 9)]
        self.add_channel(a, a_v)

        b = channel("UCb", "Street Workout IT", "@streetit", 20000)
        b_v = [video("b1", "UCb", 10, "Sponsored by Squarespace. Go to squarespace.com/streetit for 10% off", views=12000),
               video("b2", "UCb", 15, "Prova Prozis: https://www.prozis.com/it/it/streetit\n\nSeguimi: https://instagram.com/streetit",
                     views=12000, paid=True),
               video("b3", "UCb", 25, "Nuovo video di allenamento!\nSeguimi su https://instagram.com/streetit",
                     views=12000, paid=True)]
        b_v += [video(f"b{i}", "UCb", 30 + i * 5, PLAIN_IT.format(h="streetit"), views=12000) for i in range(4, 7)]
        self.add_channel(b, b_v)

        c = channel("UCc", "Big Fitness", "@bigfitness", 100000, country="US")
        c_v = [video("c1", "UCc", 8, "This video is sponsored by NordVPN: https://nordvpn.com/big", views=90000, lang="en"),
               video("c2", "UCc", 40, "Thanks to AG1 for sponsoring this video! https://drinkag1.com/big", views=90000, lang="en")]
        c_v += [video(f"c{i}", "UCc", 12 + i * 7, "Full workout.\nhttps://instagram.com/big", views=90000, lang="en")
                for i in range(3, 6)]
        self.add_channel(c, c_v)

        d = channel("UCd", "Calisthenics Kids News", "@kidsnews", 18000)
        self.add_channel(d, [video("d1", "UCd", 3, "Sponsored by ToyCo https://toyco.com", views=5000)])

        e = channel("UCe", "Ella Fitness", "@ellafit", 9000)
        mp = "Il mio integratore preferito: MyProtein codice ELLA10 https://www.myprotein.it/\nInstagram: https://instagram.com/ella"
        self.add_channel(e, [video(f"e{i}", "UCe", 3 + i * 12, mp, views=6000) for i in range(6)])

        self.search_channels = ["UCa", "UCb", "UCc", "UCd", "UCown"]
        self.featured = {"UCown": ["UCe"]}

    def __call__(self, url: str):
        parts = urllib.parse.urlsplit(url)
        endpoint = parts.path.rsplit("/", 1)[-1]
        q = dict(urllib.parse.parse_qsl(parts.query))
        self.calls.append((endpoint, q))
        if endpoint == "channels":
            if "forHandle" in q:
                cid = self.handles.get(q["forHandle"].lower())
                ids = [cid] if cid else []
            else:
                ids = q["id"].split(",")
            return 200, {"items": [self.channels[i] for i in ids if i in self.channels]}
        if endpoint == "playlistItems":
            vids = self.playlists.get(q["playlistId"])
            if vids is None:
                return 404, {"error": {"errors": [{"reason": "playlistNotFound"}], "message": "not found"}}
            start = int(q.get("pageToken") or 0)
            page = vids[start:start + int(q.get("maxResults", 50))]
            body = {"items": [{"contentDetails": {"videoId": v,
                                                  "videoPublishedAt": self.videos[v]["snippet"]["publishedAt"]}}
                              for v in page]}
            if start + len(page) < len(vids):
                body["nextPageToken"] = str(start + len(page))
            return 200, body
        if endpoint == "videos":
            if self.reject_paid_part and "paidProductPlacementDetails" in q["part"]:
                return 400, {"error": {"errors": [{"reason": "unknownPart"}], "message": "bad part"}}
            items = []
            for i in q["id"].split(","):
                if i in self.videos:
                    v = dict(self.videos[i])
                    if "paidProductPlacementDetails" not in q["part"]:
                        v.pop("paidProductPlacementDetails", None)
                    items.append(v)
            return 200, {"items": items}
        if endpoint == "search":
            items = []
            for cid in self.search_channels:
                ch = self.channels[cid]
                vid = self.playlists[ch["contentDetails"]["relatedPlaylists"]["uploads"]][0]
                items.append({"snippet": {"channelId": cid, "channelTitle": ch["snippet"]["title"],
                                          "title": self.videos[vid]["snippet"]["title"]}})
            return 200, {"items": items}
        if endpoint == "channelSections":
            ids = self.featured.get(q["channelId"], [])
            return 200, {"items": [{"snippet": {"type": "multipleChannels"}, "contentDetails": {"channels": ids}}]
                         if ids else []}
        return 404, {"error": {"message": "unknown endpoint"}}


def fake_transcript_backend(video_id, languages):
    if video_id == "b3":
        return [("ciao a tutti", 0.0), ("il video di oggi è sponsorizzato da huel il pasto completo", 12.0),
                ("trovate il link in descrizione", 20.0), ("molto più tardi", 400.0)]
    raise RuntimeError("TranscriptsDisabled")


class FakePageFetcher:
    def __init__(self, pages=None):
        self.pages = pages or {
            "https://nordvpn.com/": (200, "https://nordvpn.com/",
                                     '<html><title>NordVPN</title><a href="/affiliate">Affiliate program</a></html>'),
            "https://nordvpn.com/affiliate": (200, "https://nordvpn.com/affiliate",
                                              "<html><title>NordVPN Affiliate Program</title>"
                                              "Write to partners@nordvpn.com or logo@2x.png</html>"),
        }
        self.requested = []

    def get(self, url):
        self.requested.append(url)
        return self.pages.get(url, (404, url, ""))
