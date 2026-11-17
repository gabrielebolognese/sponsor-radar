import unittest

import fakes  # noqa: F401  (sets sys.path)
from signals import (analyze_description, analyze_transcript, classify_link, extract_urls, find_codes, registrable,
                     video_candidates)

CREATOR = {"id": "UCx", "title": "Marco Fit", "handle": "@marcofit"}


def run(desc, paid=False, creator=CREATOR, resolver=None):
    v = {"id": "v1", "description": desc, "paid_flag": paid}
    return video_candidates(v, analyze_description(desc), creator, resolver)


def by_key(cands):
    return {c["brand_key"]: c for c in cands}


class TestUrls(unittest.TestCase):
    def test_extract_strips_trailing_punctuation(self):
        self.assertEqual(extract_urls("Go to https://nordvpn.com/marco."), ["https://nordvpn.com/marco"])

    def test_bare_domain(self):
        self.assertEqual(extract_urls("Go to squarespace.com/marco for 10% off"), ["https://squarespace.com/marco"])

    def test_email_is_not_a_url(self):
        self.assertEqual(extract_urls("write to partners@brand.com"), [])

    def test_registrable(self):
        self.assertEqual(registrable("www.shop.brand.co.uk"), "brand.co.uk")
        self.assertEqual(registrable("go.nordvpn.net"), "nordvpn.net")

    def test_link_kinds(self):
        self.assertEqual(classify_link("https://amzn.to/abc")["kind"], "marketplace")
        self.assertEqual(classify_link("https://www.amazon.it/dp/B0?tag=x-21")["kind"], "marketplace")
        self.assertEqual(classify_link("https://patreon.com/marco")["kind"], "self")
        self.assertEqual(classify_link("https://instagram.com/marco")["kind"], "social")
        self.assertEqual(classify_link("https://bit.ly/x")["kind"], "shortener")
        self.assertEqual(classify_link("https://nordvpn.com/x")["kind"], "brand")

    def test_network_decodes_destination(self):
        info = classify_link("https://www.awin1.com/cread.php?awinmid=1&awinaffid=2&ued=https%3A%2F%2Fwww.brand.com%2Fshoes")
        self.assertEqual(info["network"], "awin")
        self.assertEqual(info["dest_info"]["domain"], "brand.com")

    def test_shopify_discount_path_is_a_code(self):
        self.assertEqual(classify_link("https://brand.com/discount/MARCO15")["code"], "MARCO15")

    def test_referral_path_is_affiliate(self):
        self.assertTrue(classify_link("https://www.epidemicsound.com/referral/abc123/")["affiliate"])


class TestCodes(unittest.TestCase):
    def test_codes_multilingual(self):
        self.assertIn("MARCO10", find_codes("Use code MARCO10 for 10% off"))
        self.assertIn("MARCO10", find_codes("usa il codice MARCO10"))
        self.assertIn("MARCO10", find_codes("código MARCO10"))
        self.assertIn("MARCO10", find_codes("Rabattcode: MARCO10"))
        self.assertIn("MARCO10", find_codes("code promo MARCO10"))

    def test_stopwords_rejected(self):
        self.assertEqual(find_codes("use the code below"), [])
        self.assertEqual(find_codes("codice sconto in descrizione"), [])


class TestCandidates(unittest.TestCase):
    def test_sponsored_by_with_link(self):
        cands, needs = run("This video is sponsored by NordVPN. Get 70% off at https://nordvpn.com/marco")
        c = by_key(cands)["nordvpn"]
        self.assertEqual(c["type"], "sponsored")
        self.assertIn("offer", c["signals"])
        self.assertIsNone(needs)

    def test_italian_sponsor_with_code(self):
        cands, _ = run("Questo video è sponsorizzato da MyProtein!\nUsa il codice MARCO10 su https://www.myprotein.it/")
        c = by_key(cands)["myprotein"]
        self.assertEqual(c["type"], "sponsored")
        self.assertEqual(c["code"], "MARCO10")

    def test_code_without_disclosure(self):
        cands, needs = run("Le mie scarpe: Gymshark con il codice MARCO10 https://gymshark.com")
        self.assertEqual(by_key(cands)["gymshark"]["type"], "code")
        self.assertIsNone(needs)

    def test_gear_and_self_links_ignored(self):
        cands, needs = run("My camera: https://amzn.to/xyz\nSupport me: https://patreon.com/marco\n"
                           "Coaching: https://marcofit.com/coaching code MARCO10")
        self.assertEqual(cands, [])
        self.assertIsNone(needs)

    def test_paid_flag_single_top_link(self):
        cands, _ = run("Try Prozis: https://www.prozis.com/it/marco\n\nhttps://instagram.com/marco", paid=True)
        c = by_key(cands)["prozis"]
        self.assertEqual(c["type"], "sponsored")
        self.assertIn("paid_flag_top_link", c["signals"])

    def test_paid_flag_two_top_links_is_ambiguous(self):
        cands, needs = run("https://brand-one.com/x\nhttps://brandtwo.com/y", paid=True)
        self.assertFalse(any(c["type"] == "sponsored" for c in cands))
        self.assertIn("paid_flag_no_brand", needs["reasons"])

    def test_paid_flag_no_links_needs_transcript(self):
        cands, needs = run("New workout video!", paid=True)
        self.assertEqual(cands, [])
        self.assertIn("paid_flag_no_brand", needs["reasons"])

    def test_phrase_without_link_goes_to_claude(self):
        cands, needs = run("Thanks to Raycast for sponsoring today's video!")
        self.assertEqual(cands, [])
        self.assertIn("Raycast", needs["hints"])

    def test_creator_collab_is_not_a_brand(self):
        cands, needs = run("In collaborazione con @luca\nhttps://instagram.com/luca")
        self.assertEqual(cands, [])
        self.assertIsNone(needs)

    def test_german_line_start_disclosure(self):
        cands, _ = run("*Werbung\nHolt euch Brand: https://brand.de/marco")
        self.assertEqual(by_key(cands)["brand"]["type"], "sponsored")

    def test_unpaid_werbung_is_not_sponsored(self):
        cands, _ = run("unbezahlte Werbung\nhttps://brand.de/marco")
        self.assertFalse(any(c["type"] == "sponsored" for c in cands))

    def test_bare_domain_sponsor(self):
        cands, _ = run("Sponsored by Squarespace. Go to squarespace.com/marco for 10% off")
        self.assertEqual(by_key(cands)["squarespace"]["type"], "sponsored")

    def test_affiliate_network_link(self):
        cands, _ = run("Shoes I use: https://www.awin1.com/cread.php?awinmid=1&ued=https%3A%2F%2Fwww.brand.com%2F")
        self.assertEqual(by_key(cands)["brand"]["type"], "affiliate")

    def test_unresolved_network_hint_goes_to_claude(self):
        cands, needs = run("Get it here: https://nordvpn.sjv.io/abc")
        self.assertEqual(cands, [])
        self.assertIn("nordvpn", needs["hints"])

    def test_shortener_resolved(self):
        resolver = lambda url: "https://www.brand.com/?ref=marco"  # noqa: E731
        cands, _ = run("Sponsored by Brand: https://bit.ly/abc", resolver=resolver)
        c = by_key(cands)["brand"]
        self.assertEqual(c["type"], "sponsored")
        self.assertEqual(c["link"], "https://www.brand.com/?ref=marco")

    def test_influencer_utm(self):
        cands, _ = run("Check it: https://brand.com/?utm_source=youtube&utm_medium=influencer&utm_campaign=x")
        self.assertEqual(by_key(cands)["brand"]["type"], "code")

    def test_plain_brand_link_ignored(self):
        cands, needs = run("Music from https://somesite.com\nhttps://instagram.com/marco")
        self.assertEqual(cands, [])
        self.assertIsNone(needs)


class TestTranscript(unittest.TestCase):
    def test_ad_read_with_known_key(self):
        r = analyze_transcript("today's video is sponsored by nord vpn get seventy percent off", ["nordvpn", "gym"])
        self.assertEqual(r["matched_keys"], ["nordvpn"])

    def test_no_ad_read(self):
        self.assertIsNone(analyze_transcript("let's start the workout with push ups", ["nordvpn"]))


if __name__ == "__main__":
    unittest.main()
