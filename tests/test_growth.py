"""Reality check + growth target: tiny channels must get an honest "not yet" with a target and proof."""
import json
import tempfile
import unittest
from pathlib import Path

import fakes
from discover import run_select
from growth import compute_growth, milestones


def profile(subs, views, video_count=5, first_upload_days=120, mode="ugc"):
    return {"mode": mode,
            "channel": {"id": "UCme", "title": "Me", "subs": subs, "video_count": video_count,
                        "published_at": fakes.iso_days_ago(900)},
            "stats": {"median_views_long": views, "median_views_shorts": 0.0, "long_count": 3, "short_count": 2,
                      "uploads_per_month_90d": 1.0, "shorts_share": 0.4, "median_duration_long_min": 8.0,
                      "first_upload": fakes.iso_days_ago(first_upload_days)}}


def creator(cid, subs, views, uploads=6.0, shorts=0.3):
    return {"id": cid, "title": f"Creator {cid}", "handle": f"@{cid.lower()}", "subs": subs, "own": False,
            "median_views_long": views, "median_views_shorts": 0.0, "uploads_per_month_90d": uploads,
            "shorts_share": shorts, "median_duration_long_min": 12.0, "language": "en",
            "top_videos": [{"title": "Best video", "views": views * 3, "is_short": False}]}


def sighting(cid, brand, typ, days=10):
    return {"channel_id": cid, "brand_key": brand, "domain": f"{brand}.com", "type": typ, "own": False,
            "video_id": f"{cid}-{brand}", "video_url": f"https://www.youtube.com/watch?v={cid}-{brand}",
            "title": f"{brand} video", "published_at": fakes.iso_days_ago(days)}


CREATORS = {c["id"]: c for c in [
    creator("C1", 1_800, 900),     # smallest paid creator
    creator("C2", 600, 300),       # code deal only
    creator("C3", 20_000, 9_000),
    creator("C4", 5_000, 2_000),
    creator("C5", 9_000, 700),     # lowest views on a paid deal
]}
SIGHTINGS = [sighting("C1", "huel", "sponsored"), sighting("C2", "gymshark", "code"),
             sighting("C3", "nordvpn", "sponsored"), sighting("C4", "myprotein", "sponsored"),
             sighting("C5", "squarespace", "sponsored")]
NAMES = {"huel": "Huel", "gymshark": "Gymshark", "nordvpn": "NordVPN", "myprotein": "MyProtein",
         "squarespace": "Squarespace"}


class TestGrowth(unittest.TestCase):
    def test_tiny_channel_gets_target_not_sponsors(self):
        g = compute_growth(profile(40, 15), CREATORS, SIGHTINGS, NAMES, {}, fakes.NOW)
        self.assertFalse(g["realistic"])
        self.assertEqual(g["basis"], "sponsored")
        self.assertEqual(g["target"], {"subs": 1_800, "median_views": 700})
        self.assertEqual(g["floor_subs"]["title"], "Creator C1")
        self.assertEqual(g["floor_subs"]["proof_url"], "https://www.youtube.com/watch?v=C1-huel")
        self.assertEqual(g["floor_views"]["title"], "Creator C5")
        self.assertEqual(g["gap"]["subs_x"], 45.0)
        self.assertEqual(g["gap"]["subs_to_go"], 1_760)
        self.assertEqual(g["milestones_subs"], [100, 500, 1_000, 1_800])
        self.assertEqual(g["start_now_codes"], [])  # 600 subs is not within 3x of 40
        self.assertEqual([r["title"] for r in g["ladder"]], ["Creator C1", "Creator C4", "Creator C5", "Creator C3"])
        self.assertEqual(g["entry_level"]["n"], 4)
        self.assertIn("Growth target: 1,800 subscribers and 700 views per video.", g["verdict"])
        self.assertIn("Huel", g["verdict"])

    def test_code_deals_within_reach_are_a_start_now_track(self):
        g = compute_growth(profile(250, 150), CREATORS, SIGHTINGS, NAMES, {}, fakes.NOW)
        self.assertFalse(g["realistic"])
        self.assertEqual(g["start_now_codes"], ["Gymshark"])

    def test_within_reach_is_realistic(self):
        g = compute_growth(profile(700, 400), CREATORS, SIGHTINGS, NAMES, {}, fakes.NOW)
        self.assertTrue(g["realistic"])
        self.assertEqual(g["realistic_brands"], ["Huel"])
        self.assertIn("1 brand paid creators within 3x of your size", g["verdict"])

    def test_views_must_also_be_within_reach(self):
        # 2,000 subs is within 3x of 700, but 9,000 views is not within 3x of 100.
        cr = {"C": creator("C", 2_000, 9_000)}
        g = compute_growth(profile(700, 100), cr, [sighting("C", "huel", "sponsored")], NAMES, {}, fakes.NOW)
        self.assertFalse(g["realistic"])

    def test_brand_new_channel_with_no_videos(self):
        p = profile(0, 0.0, video_count=0)
        p["stats"]["first_upload"] = None
        g = compute_growth(p, CREATORS, SIGHTINGS, NAMES, {}, fakes.NOW)
        self.assertFalse(g["realistic"])
        self.assertIsNone(g["gap"]["subs_x"])
        self.assertEqual(g["target"]["subs"], 1_800)
        self.assertEqual(g["pace"]["subs_per_month"], 0.0)
        self.assertIsNone(g["pace"]["months_to_target"])

    def test_pace_is_flagged_unreliable_for_tiny_channels(self):
        g = compute_growth(profile(40, 15), CREATORS, SIGHTINGS, NAMES, {}, fakes.NOW)
        self.assertEqual(g["pace"]["months_active"], 3.9)
        self.assertFalse(g["pace"]["reliable"])

    def test_no_deals_at_all(self):
        g = compute_growth(profile(40, 15), CREATORS, [], NAMES, {}, fakes.NOW)
        self.assertIsNone(g["basis"])
        self.assertIn("No brand deals found", g["verdict"])

    def test_code_only_fallback(self):
        g = compute_growth(profile(40, 15), CREATORS, [sighting("C2", "gymshark", "code")], NAMES, {}, fakes.NOW)
        self.assertEqual(g["basis"], "code")
        self.assertIn("only promo-code deals", g["verdict"])
        self.assertEqual(g["target"]["subs"], 600)

    def test_milestones(self):
        self.assertEqual(milestones(400, 1_800), [500, 1_000, 1_800])
        self.assertEqual(milestones(1_500, 1_800), [1_800])
        self.assertEqual(milestones(40, None), [])


class TestSelectSmallBand(unittest.TestCase):
    def test_ugc_samples_small_creators(self):
        with tempfile.TemporaryDirectory() as d:
            run = Path(d)
            cands = [{"id": f"{b}{i}", "band": b} for b, n in (("core", 60), ("bigger", 20), ("smaller", 20))
                     for i in range(n)]
            (run / "candidates.json").write_text(json.dumps(cands), encoding="utf-8")
            (run / "profile.json").write_text(json.dumps({"mode": "ugc"}), encoding="utf-8")
            s = run_select(run, {"max_lookalikes": 50})
            self.assertEqual(s["by_band"], {"core": 30, "bigger": 10, "smaller": 10})
            (run / "profile.json").write_text(json.dumps({"mode": "micro"}), encoding="utf-8")
            s = run_select(run, {"max_lookalikes": 50})
            self.assertEqual(s["by_band"], {"core": 35, "bigger": 15, "smaller": 0})


if __name__ == "__main__":
    unittest.main()
