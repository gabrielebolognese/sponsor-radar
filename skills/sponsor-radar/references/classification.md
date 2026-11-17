# Classifying ambiguous items

The scanner only records sightings it can attribute with confidence. Everything else lands in `ambiguous.json` for you to judge. **Precision matters more than recall.** A missed brand costs the user little; a fake brand on the list destroys trust in every other row.

## Item kinds

- **`video`**: one video. Common reasons it's here:
  - `paid_flag_no_brand`: YouTube's paid-promotion flag is on, but the description doesn't name the brand.
  - `phrase_without_brand_link`: a "sponsored by X" disclosure with no brand link next to it.
  - `hashtag_ad_no_brand`: #ad with no attributable brand.
  - `affiliate_network_unresolved`: a network link where only a brand hint is known.
  - What you get to work with: `description_excerpt`, an optional `transcript_excerpt` (the first ~150 seconds), `hints` (text after the disclosure), and `candidate_domains` (brand links found in the description).
- **`evergreen`**: the same brand link appears in most of one creator's videos (`in_videos`), without a disclosure. You give one verdict for the whole group.

## Types

| type | when |
|---|---|
| `sponsored` | Evidence of a paid deal: an explicit disclosure that names the brand ("sponsored by", "paid partnership", "grazie a X per aver sponsorizzato"), a transcript ad read that names it, or the paid flag on while one brand is clearly the subject. |
| `code` | A brand promo code or tracked link in a sponsor-style spot, with no paid disclosure. Includes standing ambassador codes that run in every video. |
| `affiliate` | Commission links only: network links, referral links, "links may be affiliate", monetized gear lists. |
| `self` | The creator's own product, merch, course, app, coaching, newsletter or membership, or a company they own. |
| `gear` | A plain gear or kit list with no code and no disclosure. |
| `unrelated` | Social links, other creators, credits (music, footage), sources, charities, or not enough information. |

## Rules

1. **Name the brand only from text in the item.** Don't guess from general knowledge which brand probably sponsored a video, or which brand a creator "usually" works with. If the item doesn't say, the answer is `unrelated` with low confidence.
2. **`domain`:** use one from `candidate_domains`, or one written in the excerpt. If the brand is named clearly but no domain appears, give its official domain only if you're certain (for example `huel.com`). Otherwise use `null`. Never use a reseller or marketplace domain.
3. **`confidence`:**
   - 0.9: explicit and named.
   - 0.75: strongly implied (paid flag plus the only brand mentioned).
   - 0.5 or lower: unsure. Anything under 0.6 is ignored by the ranking, so use a low score instead of forcing a verdict.
4. **Evergreen groups:**
   - A standing code or ambassador link is `code`.
   - The creator's own store or site is `self`.
   - A gear list with affiliate links is `affiliate`.
   - It's `sponsored` only if the item shows a disclosure.
5. **Music and asset libraries** (Epidemic Sound, Artlist, Envato) with referral links are `affiliate`, unless they're disclosed as a sponsor.
6. **A collab with another creator is not a brand deal.** Mark it `unrelated`.
7. **`evidence_quote`:** copy the exact words (up to 200 characters) from the excerpt that justify the verdict.
8. Items with `"own": true` are the user's own videos. Classify them the same way; they feed the "never sponsored you" and "renewal" labels.

## Output: `classified.json`

```json
{
  "results": [
    {"id": "a3", "brand": "Huel", "domain": "huel.com", "type": "sponsored", "confidence": 0.9,
     "code": null, "evidence_quote": "il video di oggi è sponsorizzato da huel"},
    {"id": "a7", "brand": "MyProtein", "domain": "myprotein.it", "type": "code", "confidence": 0.85,
     "code": "ELLA10", "evidence_quote": "MyProtein codice ELLA10"},
    {"id": "a9", "brand": null, "domain": null, "type": "unrelated", "confidence": 0.3,
     "evidence_quote": "paid flag on, description has only social links"}
  ],
  "aliases": {"athleticgreens": "drinkag1"},
  "names": {"nordvpn": "NordVPN", "drinkag1": "AG1"},
  "exclude_brands": []
}
```

- **Include every id**, including `unrelated` ones, so the run can be audited.
- **`aliases`**: maps variant brand keys to one canonical key. A key is the domain name without its TLD (`nordvpn.com` becomes `nordvpn`).
- **`names`**: display names for brand keys. Fill these in for the top brands after you rank.
- **`exclude_brands`**: keys to drop from the ranking, such as platforms, the creator's own companies, or obvious mistakes.
