"""Unit tests: YouTube client, pricing, pipeline, bands."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import fakes
from channel import band_of, bands_for, mode_for
from price import compute_rate
from yt import QuotaExceeded, YouTube


def make_yt(api=None):
    return YouTube("test-key", None, transport=api or fakes.FakeYouTubeAPI(), sleep=lambda s: None)


class TestYouTube(unittest.TestCase):
    def test_cache_avoids_second_request(self):
        api = fakes.FakeYouTubeAPI()
        yt = make_yt(api)
        yt.channel(handle="@marcofit")
        yt.channel(handle="@marcofit")
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(yt.cache_hits, 1)
        self.assertEqual(yt.units_this_run, 1)

    def test_search_costs_100(self):
        yt = make_yt()
        yt.search_videos("calisthenics", fakes.NOW)
        self.assertEqual(yt.units_this_run, 100)
        self.assertEqual(yt.quota_used_today(), 100)

    def test_videos_batched_by_50(self):
        api = fakes.FakeYouTubeAPI()
        yt = make_yt(api)
        yt.videos([f"x{i}" for i in range(120)])
        self.assertEqual(sum(1 for e, _ in api.calls if e == "videos"), 3)

    def test_upload_ids_stop_at_since(self):
        yt = make_yt()
        ids = yt.upload_ids("UUa", fakes.NOW - timedelta(days=30), 30)
        self.assertIn("a1", ids)
        self.assertNotIn("a2", ids)  # 35 days old

    def test_paid_part_fallback(self):
        api = fakes.FakeYouTubeAPI()
        api.reject_paid_part = True
        yt = make_yt(api)
        out = yt.videos(["a1"])
        self.assertEqual(out[0]["id"], "a1")
        self.assertFalse(yt.paid_part_supported)

    def test_quota_exceeded_raises(self):
        yt = make_yt(lambda url: (403, {"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}}))
        with self.assertRaises(QuotaExceeded):
            yt.channel(handle="@x")


class TestBands(unittest.TestCase):
    def test_modes(self):
        self.assertEqual(mode_for(300), "ugc")
        self.assertEqual(mode_for(12000), "micro")
        self.assertEqual(mode_for(80000), "conquest")

    def test_ugc_band_is_floored(self):
        self.assertEqual(bands_for(300)["core"], [2000, 50000])

    def test_micro_band(self):
        b = bands_for(12000)
        self.assertEqual(band_of(15000, b), "core")
        self.assertEqual(band_of(100000, b), "bigger")
        self.assertIsNone(band_of(5_000_000, b))
        self.assertIsNone(band_of(None, b))


PROFILE = {"mode": "micro", "stats": {"median_views_long": 8000, "median_views_shorts": 0,
                                      "long_count": 20, "short_count": 0}}


class TestPrice(unittest.TestCase):
    def test_example_from_the_spec(self):
        r = compute_rate(PROFILE, {"cpm_bucket": "fitness"}, {"currency": "USD", "fx_from_usd": {"USD": 1}})
        self.assertEqual((r["low"], r["high"]), (120, 240))
        self.assertIn("8,000 median views", r["explain"])
        self.assertTrue(r["assumption"])

    def test_currency_and_rate_check(self):
        r = compute_rate(PROFILE, {"cpm_bucket": "fitness"},
                         {"currency": "EUR", "fx_from_usd": {"EUR": 0.9}, "current_rate": 80})
        self.assertEqual((r["low"], r["high"]), (110, 220))
        self.assertIn("under the bottom", r["rate_check"])

    def test_calibration_after_two_deals(self):
        deals = [{"amount": "400", "currency": "USD", "views_at_deal": "8000"},
                 {"amount": "400", "currency": "USD", "views_at_deal": "8000"}]
        r = compute_rate(PROFILE, {"cpm_bucket": "fitness"}, {"currency": "USD", "fx_from_usd": {"USD": 1}}, deals)
        self.assertEqual(r["calibrated_from_deals"], 2)
        self.assertEqual(r["cpm_usd"], [33.3, 66.7])  # effective CPM 50 vs midpoint 22.5

    def test_ugc_prices_per_asset(self):
        r = compute_rate({**PROFILE, "mode": "ugc"}, {}, {"currency": "USD", "fx_from_usd": {"USD": 1}})
        self.assertEqual((r["low"], r["high"]), (100, 300))
        self.assertIn("asset", r["basis"])

    def test_shorts_only(self):
        p = {"mode": "micro", "stats": {"median_views_long": 0, "median_views_shorts": 50000,
                                        "long_count": 0, "short_count": 30}}
        r = compute_rate(p, {"cpm_bucket": "fitness"}, {"currency": "USD", "fx_from_usd": {"USD": 1}})
        self.assertIn("Short", r["basis"])
        self.assertEqual((r["low"], r["high"]), (75, 380))


class TestPipeline(unittest.TestCase):
    def setUp(self):
        import pipeline
        self.P = pipeline
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "pipeline.csv"
        self.P.save([{"brand_key": "nordvpn", "brand": "NordVPN", "domain": "nordvpn.com", "status": "drafted",
                      "followups": "0", "currency": "EUR", "views_at_deal": "8000"}], self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_followup_schedule(self):
        d0 = date(2026, 11, 17)
        r = self.P.update("nordvpn", "pitched", d0, path=self.path)
        self.assertEqual(r["next_followup"], "2026-11-21")
        self.assertEqual(self.P.due(self.P.load(self.path), d0 + timedelta(days=4))[0]["brand"], "NordVPN")
        r = self.P.update("NordVPN", "followup", d0 + timedelta(days=4), path=self.path)
        self.assertEqual(r["next_followup"], "2026-11-27")
        r = self.P.update("nord", "followup", d0 + timedelta(days=10), path=self.path)
        self.assertEqual(r["next_followup"], "")

    def test_close_with_amount(self):
        r = self.P.update("nordvpn", "closed", date(2026, 11, 17), amount="300", path=self.path)
        self.assertEqual(r["status"], "closed")
        self.assertEqual(len(self.P.closed_deals(self.P.load(self.path))), 1)

    def test_unknown_status(self):
        with self.assertRaises(SystemExit):
            self.P.update("nordvpn", "maybe", date(2026, 11, 17), path=self.path)


if __name__ == "__main__":
    unittest.main()
