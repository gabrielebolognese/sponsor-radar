"""Full pipeline, offline: profile -> discover -> select -> scan -> classify -> rank -> contacts -> price -> report -> pipeline.

Claude's judgment steps (niche.json, exclude.json, classified.json) are simulated with the files
Claude would write, so this exercises exactly the hand-offs SKILL.md describes.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fakes


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.env = mock.patch.dict(os.environ, {"SPONSOR_SLEUTH_HOME": cls.tmp.name,
                                               "SPONSOR_SLEUTH_NOW": fakes.NOW_ISO,
                                               "YOUTUBE_API_KEY": "test-key"})
        cls.env.start()
        import contacts
        import sleuth
        import transcripts
        from yt import YouTube
        cls.api = fakes.FakeYouTubeAPI()
        real_tf = transcripts.TranscriptFetcher
        patches = [
            mock.patch.object(sleuth, "_yt", lambda cfg: YouTube("k", None, transport=cls.api, sleep=lambda s: None)),
            mock.patch.object(transcripts, "TranscriptFetcher",
                              lambda max_fetches=100: real_tf(max_fetches=max_fetches,
                                                              backend=fakes.fake_transcript_backend,
                                                              sleep=lambda s: None)),
            mock.patch.object(contacts, "PageFetcher", fakes.FakePageFetcher),
        ]
        for p in patches:
            p.start()
        cls.patches = patches
        cls.sleuth = sleuth
        cls.out = {}

        cls.cli("setup", "--currency", "EUR", "--rate", "80")
        cls.out["profile"] = cls.cli("profile", "@marcofit")
        cls.run_dir = next(Path(cls.tmp.name, "runs", "marcofit").iterdir())
        (cls.run_dir / "niche.json").write_text(json.dumps({
            "niche": "calisthenics / bodyweight training", "language": "it", "region": "IT",
            "queries": ["calisthenics principianti", "allenamento corpo libero"],
            "queries_en": ["calisthenics workout"], "cpm_bucket": "fitness", "exclude_terms": []}), encoding="utf-8")
        cls.out["discover"] = cls.cli("discover", "--run", "@marcofit")
        (cls.run_dir / "exclude.json").write_text(json.dumps({"exclude": ["UCd"]}), encoding="utf-8")
        cls.out["select"] = cls.cli("select", "--run", "@marcofit")
        cls.out["scan"] = cls.cli("scan", "--run", "@marcofit", "--no-resolve")
        amb = json.loads((cls.run_dir / "ambiguous.json").read_text(encoding="utf-8"))
        cls.ambiguous = amb
        results = []
        for a in amb:
            if a["kind"] == "evergreen" and a["brand_key"] == "myprotein":
                results.append({"id": a["id"], "brand": "MyProtein", "domain": "myprotein.it", "type": "code",
                                "confidence": 0.85, "evidence_quote": "MyProtein codice ELLA10"})
            elif a["kind"] == "video" and a["video_id"] == "b3":
                results.append({"id": a["id"], "brand": "Huel", "domain": "huel.com", "type": "sponsored",
                                "confidence": 0.9, "evidence_quote": "il video di oggi è sponsorizzato da huel"})
        (cls.run_dir / "classified.json").write_text(json.dumps(
            {"results": results, "names": {"nordvpn": "NordVPN", "drinkag1": "AG1"}}), encoding="utf-8")
        cls.out["rank"] = cls.cli("rank", "--run", "@marcofit")
        cls.out["contacts"] = cls.cli("contacts", "--run", "@marcofit")
        cls.out["price"] = cls.cli("price", "--run", "@marcofit")
        cls.out["report"] = cls.cli("report", "--run", "@marcofit")
        cls.out["brief"] = cls.cli("brief", "--run", "@marcofit")
        cls.brands = json.loads((cls.run_dir / "brands.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    @classmethod
    def cli(cls, *argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cls.sleuth.main(list(argv))
        return buf.getvalue()

    def brand(self, key):
        return next(b for b in self.brands["brands"] + self.brands["affiliate_only"] if b["key"] == key)

    # ---- profile / discovery ----

    def test_profile(self):
        self.assertIn("mode: MICRO", self.out["profile"])
        prof = json.loads((self.run_dir / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(prof["stats"]["median_views_long"], 8000)
        self.assertEqual(prof["stats"]["language"], "it")

    def test_discovery_bands_and_featured(self):
        cands = {c["id"]: c for c in json.loads((self.run_dir / "candidates.json").read_text(encoding="utf-8"))}
        self.assertNotIn("UCown", cands)
        self.assertEqual(cands["UCa"]["band"], "core")
        self.assertEqual(cands["UCc"]["band"], "bigger")
        self.assertTrue(cands["UCe"]["featured"])

    def test_claude_exclusion_respected(self):
        look = json.loads((self.run_dir / "lookalikes.json").read_text(encoding="utf-8"))
        self.assertNotIn("UCd", [c["id"] for c in look["creators"]])
        self.assertEqual(len(look["creators"]), 4)

    # ---- scan ----

    def test_evergreen_routed_to_claude(self):
        ever = [a for a in self.ambiguous if a["kind"] == "evergreen"]
        self.assertEqual(len(ever), 1)
        self.assertEqual(ever[0]["brand_key"], "myprotein")
        self.assertEqual(ever[0]["in_videos"], "6 of 6")

    def test_transcript_excerpt_attached(self):
        b3 = next(a for a in self.ambiguous if a.get("video_id") == "b3")
        self.assertIn("huel", b3["transcript_excerpt"])
        self.assertNotIn("molto più tardi", b3["transcript_excerpt"])  # beyond 150s

    def test_quota_tracked(self):
        q = json.loads((self.run_dir / "quota.json").read_text(encoding="utf-8"))
        self.assertEqual(q["discover"] // 100, 3)  # 3 searches
        self.assertLess(sum(q.values()), 400)

    # ---- ranking ----

    def test_repeat_sponsor_ranks_first(self):
        top = self.brands["brands"][0]
        self.assertEqual(top["key"], "nordvpn")
        self.assertEqual(top["repeat_max"], 3)
        self.assertIn("came back 3x to Luca Calisthenics", top["labels"])
        self.assertIn("sponsors your competitors, never you", top["labels"])
        self.assertEqual(len(top["proofs"]), 4)

    def test_headline(self):
        h = self.brands["headline"]
        self.assertEqual(h["sponsored_your_size_30d"], 4)  # NordVPN, Squarespace, Prozis, Huel
        self.assertEqual(h["never_sponsored_you"], 5)       # + AG1
        self.assertEqual(h["top_repeat"]["brand"], "NordVPN")
        self.assertEqual(h["own_sponsors"], ["MyProtein"])

    def test_renewal_label(self):
        self.assertTrue(any(lbl.startswith("renewal") for lbl in self.brand("myprotein")["labels"]))

    def test_big_foreign_only_brand_is_downranked(self):
        ag1 = self.brand("drinkag1")
        self.assertEqual(ag1["name"], "AG1")
        self.assertIn("only sponsors bigger creators", ag1["labels"])
        self.assertIn("different language", ag1["labels"])
        self.assertEqual(ag1["rank"], len(self.brands["brands"]))

    def test_claude_verdict_becomes_brand(self):
        huel = self.brand("huel")
        self.assertEqual(huel["type"], "sponsored")
        self.assertEqual(huel["proofs"][0]["video_url"], "https://www.youtube.com/watch?v=b3")

    def test_code_deal(self):
        g = self.brand("gymshark")
        self.assertEqual(g["type"], "code")
        self.assertEqual(g["codes"], ["LUCA10"])

    def test_kids_channel_brand_absent(self):
        self.assertFalse(any(b["key"] == "toyco" for b in self.brands["brands"]))

    def test_growth_reality_check(self):
        g = json.loads((self.run_dir / "growth.json").read_text(encoding="utf-8"))
        self.assertTrue(g["realistic"])  # Luca (15k subs, 9k views) is within 3x of 12k subs / 8k views
        self.assertIn("NordVPN", g["realistic_brands"])
        self.assertIn("REALISTIC=yes", self.out["rank"])
        text = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("**Within reach:**", text)
        self.assertNotIn("## Not yet", text)
        brief = json.loads((self.run_dir / "pitch_brief.json").read_text(encoding="utf-8"))
        self.assertTrue(brief["growth"]["realistic"])

    # ---- contacts / price / report / pipeline ----

    def test_contacts(self):
        c = json.loads((self.run_dir / "contacts.json").read_text(encoding="utf-8"))["nordvpn"]
        self.assertEqual(c["emails"], [{"email": "partners@nordvpn.com", "kind": "partnerships"}])
        self.assertEqual(c["program_pages"][0]["url"], "https://nordvpn.com/affiliate")
        self.assertIn("linkedin.com/search", c["linkedin_search"])

    def test_price(self):
        rate = json.loads((self.run_dir / "rate.json").read_text(encoding="utf-8"))
        self.assertEqual(rate["currency"], "EUR")
        self.assertEqual((rate["low"], rate["high"]), (110, 220))
        self.assertIn("under the bottom", rate["rate_check"])

    def test_report_has_proofs_and_headlines(self):
        text = (self.run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("**4 brands sponsored creators your size in the last 30 days.**", text)
        self.assertIn("NordVPN came back to Luca Calisthenics 3 times", text)
        self.assertIn("https://www.youtube.com/watch?v=a1", text)
        self.assertIn("partners@nordvpn.com", text)

    def test_brief(self):
        brief = json.loads((self.run_dir / "pitch_brief.json").read_text(encoding="utf-8"))
        self.assertEqual(brief["brands"][0]["name"], "NordVPN")
        self.assertEqual(brief["creator"]["language"], "it")
        self.assertEqual(brief["rate"]["currency"], "EUR")

    def test_pipeline_add_and_list(self):
        out = self.cli("pipeline", "add", "--run", "@marcofit", "--top", "3")
        self.assertIn("Added 3", out)
        out = self.cli("pipeline", "update", "NordVPN", "pitched")
        self.assertIn("next follow-up 2026-11-21", out)
        out = self.cli("pipeline", "list")
        self.assertIn("| NordVPN | pitched |", out)


if __name__ == "__main__":
    unittest.main()
