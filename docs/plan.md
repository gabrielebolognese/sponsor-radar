# sponsor-radar: v1 build plan

## 0. What v1 ships

One command, run locally with the user's own YouTube API key, done in under 10 minutes:

```
/sponsor-radar @handle
```

Output:
- a ranked brand list, every row with at least one proof link to the sponsored video
- your rate (median views x niche CPM range)
- 10 drafted pitches, each with 2 follow-ups
- a pipeline file with follow-up reminders

Plus three small commands: `/sponsor-radar setup`, `/sponsor-radar pipeline`, `/sponsor-radar update <brand> <status> [amount]`.

**Not in v1:** podcasts, Instagram/TikTok, the shared database, any automated sending, an HTML dashboard (stretch goal for the demo video).

---

## 1. Reality check: what I'd change from the pitch

| Claim in the pitch | Problem | v1 fix |
|---|---|---|
| "Brands that **paid** creators your size" | Promo codes and affiliate links are often commission-only. Nobody got paid. | Every sighting gets a type: `sponsored` (paid evidence: paid-promotion flag, "sponsored by", ad read) or `affiliate` (code/link only). Headline numbers count only `sponsored`. Affiliate brands still show up, and they're the main target in UGC mode. |
| "You're charging €150. Creators your size are getting €300-400." | There's no public data on what other creators get paid. | v1 says "your views price you at €X-Y per integration (CPM model)" and, if you enter your current rate, compares it to that. Real market rates only come from closed deals logged in the pipeline. That's the data moat, so we don't fake it in the demo. |
| Ad read in the first minute of the transcript | The official API only gives captions for videos you own. Other people's transcripts mean hitting player endpoints that YouTube rate-limits and blocks. | Best-effort and targeted: only for videos that have the paid flag (or a sponsor phrase) but no brand in the description. Capped per scan. Everything else works without transcripts. |
| UGC mode lookalikes at 0.5-3x | 0.5-3x of 300 subscribers is channels with no sponsors at all. | Floor the band. In UGC mode we scan 2k-50k creators in the niche and rank brands by "works with small creators" plus affiliate/UGC programs. |
| Pitch says "my audience overlaps with theirs" | We can't measure audience overlap. | Pitches only state what we can prove: same niche, same language, similar size, link to the video. |
| Paid tier = shared database | A database built from YouTube API data runs into the YouTube API Services policies (storage/refresh limits, restrictions on selling API data). | Not a v1 problem, since everyone runs locally with their own key. Needs a proper policy read before building the paid tier. |

---

## 2. Architecture

**Format:** a Claude Code skill, packaged as a plugin (also works copied into `~/.claude/skills/`).

**Split of work:**
- **Scripts** do the deterministic work: API calls, caching, regex, link classification, scoring, files.
- **Claude** does the judgment: niche to search queries, pruning off-niche channels, classifying ambiguous sponsor signals, merging brand aliases, writing pitches.

Claude is the host LLM, so users don't need an Anthropic API key.

**Runtime:** Python 3.10+, standard library only for the core (urllib, sqlite3, json, re). One optional dependency for transcripts (`youtube-transcript-api`). Nothing to pip install before the first result.

**Repo layout:**

```
sponsor-radar/
  .claude-plugin/plugin.json
  skills/sponsor-radar/
    SKILL.md                    # the orchestration Claude follows
    scripts/
      radar.py                  # CLI entry: profile | discover | scan | rank | contacts | price | pipeline
      yt.py                     # API client, cache, quota ledger, retries
      signals.py                # multilingual regex, link classifier
      transcripts.py            # best-effort ad-read extraction
      rank.py
      contacts.py
      pipeline.py
    references/
      classification.md         # rules for Claude: what counts as a sponsor
      pitch-guide.md            # pitch structure, tone, no-AI-tells rules
      modes.md
      cpm.json                  # niche -> CPM range (assumptions)
      link-domains.json         # affiliate networks, shorteners, self/platform domains
  tests/
    fixtures/                   # recorded API responses, so tests cost no quota
    labeled/                    # hand-labeled videos for the precision eval
  README.md
```

**Local state** in `~/.sponsor-radar/`:
- `config.json`: API key, currency, your current rate (optional)
- `cache.db`: API response cache (7-day TTL) and a quota ledger
- `pipeline.csv`
- `runs/<handle>/<date>/`: every stage's output file, so any stage can be rerun alone

---

## 3. The pipeline, stage by stage

### Stage 1: Profile (script, then Claude)
- `channels.list?forHandle=@x` (1 unit), then the uploads playlist, then `videos.list` in batches of 50.
- Computes: subscribers, **median views of the last 10 long-form videos** (Shorts excluded, which means anything 180s or shorter), upload cadence, language, country.
- Picks the mode from subscriber count.
- Claude reads the last 30 titles and descriptions and writes `niche.json`: a niche label, 10-15 search queries in the channel's language plus 3-5 in English, a CPM bucket, and exclusion terms.

### Stage 2: Discover lookalikes (script, then Claude)
- `search.list type=video`, last 90 days, `relevanceLanguage` + `regionCode`, 50 results per query, then collect the channel IDs. 12-15 queries come to about 1,200-1,500 units. **This is the only expensive call.**
- Cheap expansion: featured channels (`channelSections`, 1 unit each) of your channel and the top candidates.
- `channels.list` for stats (1 unit per 50 channels). Filter by size band (see Modes) and require an upload in the last 30 days.
- Claude prunes off-niche channels from a compact table (name, subs, 5 recent titles).
- Final set is up to 50 channels: about 35 in the core band and about 15 bigger ones (3-20x), weighted lower.

### Stage 3: Scan for sponsor signals (script)
For each lookalike: last 90 days of uploads, capped at 30, then `videos.list part=snippet,contentDetails,statistics,paidProductPlacementDetails`. About 100 units total.

Detection layers, strongest first:
1. **Paid-promotion flag** (`paidProductPlacementDetails.hasPaidProductPlacement`). Verify on Day 0 that it's populated for other people's videos.
2. **Description phrases**, multilingual regex (EN/IT/ES/DE/FR/PT): "sponsored by", "sponsorizzato da", "in collaborazione con", "patrocinado por", "gesponsert von", "use code", "codice sconto", "código", "Rabattcode", "% off", "sconto"...
3. **Links.** Extract every URL and classify it:
   - social, self, or creator platform (Patreon, merch, Linktree, courses): ignored
   - shortener: resolved
   - affiliate network (Impact, Awin, Partnerize, ShareASale...): decoded to the brand
   - Amazon / gear list: `affiliate` tier
   - brand domain with UTM params naming the creator: strong signal
   - Decode statically first and only HEAD-resolve shorteners (resolving tracking links registers clicks on other creators' links). Cache every result.
4. **Position.** A code or link in the first 3 lines of the description means it's in the sponsor slot.
5. **Evergreen filter.** A domain that shows up in more than 60% of one creator's videos is probably self-promo, a gear list, or a long-term partner. Send it to Claude instead of guessing.
6. **Transcript (best-effort).** Only for videos with the flag or a phrase match but no resolved brand. First 150 seconds, ad-read regex. Capped at 100 per scan, throttled.

Outputs: `sightings.json` (resolved, confident) and `ambiguous.json` (short snippets for Claude).

### Stage 4: Classify the ambiguous ones (Claude)
- Batches of about 25 snippets. For each: `{brand, domain, type: sponsored|affiliate|self|gear|unrelated, confidence, evidence_quote}`.
- Rules live in `references/classification.md`: your own merch, courses, Patreon, and gear lists don't count.
- Claude also merges aliases (nordvpn.com, nordvpn.sjv.io, and "Nord" are one brand).
- **Context budget rule:** Claude never sees 1,500 descriptions. The scripts prefilter, and Claude sees at most about 150 snippets.

### Stage 5: Rank (script)
Starting weights live in config and get tuned against the labeled eval.

```
sighting value = strength x recency x size_fit
  strength  = sponsored 1.0 | code+brand link 0.6 | affiliate only 0.3
  recency   = 0.5 ^ (age_days / 30)
  size_fit  = based on r = creator median views / your median views
              0.5-3x: 1.0 | under 0.5x: 0.8 | 3-10x: 0.5 | over 10x: 0.25

creator value = max sighting value for that creator  (one spammy creator can't dominate)
brand score   = sum(creator values) x repeat_mult x lang_fit
  repeat_mult = 1 + 0.5 x (max repeats with a single creator - 1), capped at 2.5
  lang_fit    = 1.0 if seen on same-language creators, else 0.6
```

Labels per brand: "sponsored 4 creators your size", "only sponsors giants", "came back 4x to @x", "sponsors your competitors, never you", "renewal: sponsored you 5 months ago".

The last two need a scan of **your own** last 12 months of videos, which costs about 10 units.

Every brand gets a one-line "why it's ranked here".

### Stage 6: Contact path (script, then Claude, top 15 brands)
- Probe the brand domain for `/creators`, `/creator-program`, `/partners`, `/partnerships`, `/affiliate(s)`, `/influencer(s)`, `/ambassador(s)`, `/ugc`, and `/collab`, the Shopify forms `/pages/affiliate` and `/pages/ambassador`, and the sitemap for those keywords.
- Collect `mailto:` addresses that match partner|influencer|collab|marketing|press|pr.
- If the link came through an affiliate network, that network is the application path.
- **LinkedIn:** no scraping. Output a prefilled search URL ("{brand} influencer marketing manager") for the user to open.
- Claude uses WebSearch only for the top 5 brands that still have no path.
- Respects robots.txt and stays at 1 request per second per domain.

### Stage 7: Price (script)
- Median views (last 10 long-form) x niche CPM range from `cpm.json`, in local currency.
- Starting CPM ranges are **assumptions** and labeled that way in the output:
  - tech, finance, business: $25-50
  - education, productivity: $20-40
  - fitness, health, beauty, lifestyle: $15-30
  - gaming, entertainment, vlogs: $10-20
- Shorts-only channels get a separate, lower range. UGC mode prices per asset (portfolio-based), not by CPM.
- **Calibration:** every closed deal in the pipeline gives an effective CPM (price / views x 1000). After 2 deals it blends into a personal multiplier.

### Stage 8: Report and pitches (Claude)
- `report.md` has:
  - the headline numbers
  - the ranked table: brand, score, why, creators, last seen, deal type, contact, proof links
  - your rate box
- **10 pitches**, each in the brand's language:
  - 3 subject lines
  - a body under 150 words: evidence, fit, a 60-second integration concept tied to your real content, your rate, one ask
  - a follow-up for day 4 and another for day 10
- **Hard rule:** every factual claim in a pitch has to map to a row in the evidence. Then a no-AI-tells pass (em dashes, slop words).

### Stage 9: Pipeline (script)
- `pipeline.csv` columns: brand, contact, status (drafted / pitched / replied / negotiating / closed / lost), pitched_at, next_followup, amount, currency, views_at_deal, notes.
- CSV so it opens in Sheets or Excel.
- `/sponsor-radar pipeline` shows the table and any overdue follow-ups. `/sponsor-radar update` moves a deal along, and closing one with an amount feeds price calibration.

---

## 4. Quota per full scan

| Step | Units |
|---|---|
| Profile | ~5 |
| Discovery searches (15 x 100) | 1,500 |
| Featured channels | ~20 |
| Channel stats | ~5 |
| Scan 50 channels | ~100 |
| Your own 12-month history | ~10 |
| **Total** | **~1,650** |

That's about 6 full scans a day on the free 10,000-unit quota. A rerun within 7 days hits the cache and spends close to zero search units.

---

## 5. Modes

| Mode | Size | Creator band scanned | What changes |
|---|---|---|---|
| **UGC** | 0-1k | 2k-50k in niche (floored, not relative) | Ranks brands that run UGC/affiliate programs and sponsor the smallest creators. Pitch leads with your 3 best videos. Rate is per asset. |
| **Micro** | 1k-50k | 0.5-3x core, plus 3-10x at lower weight | Suggests hybrid deals (flat fee + affiliate) when a brand runs both. |
| **Conquest** | 50k+ | 0.3-3x, plus your top competitors | Adds the "never sponsored you" list, renewals, a rate check against the model, and agency paths in contacts. |

---

## 6. Quality bar and testing

- **Unit tests:** the regex and link classifier, run against fixture descriptions in EN/IT/ES/DE.
- **Recorded API fixtures:** tests run offline and cost no quota.
- **Labeled eval:** hand-label about 150 videos from 6 channels (sponsored or not, which brand), then measure precision and recall.
  - Target: **at least 90% precision on the top 20 brands.** Recall matters less, because a missed brand costs little and a fake brand kills trust.
- **End-to-end runs** on 3 real channels, one per mode. Target under 10 minutes each.

---

## 7. Build schedule

| Day | Work |
|---|---|
| **0 (half day)** | Spikes: get an API key; check that `forHandle` and `paidProductPlacementDetails` work on known sponsored videos; fetch transcripts for 30 videos from your machine (the success rate decides whether transcripts stay in v1); pick the test channels; start labeling. |
| **1** | `yt.py` (cache, quota ledger, retries), `profile`, the niche step in SKILL.md, `discover`. |
| **2** | `scan`: description signals, link classifier, domain lists, shortener resolution, evergreen filter. Finish the labeled set and get the first precision numbers. |
| **3** | Transcripts (best-effort), the ambiguous-to-Claude classification loop, alias merging, `rank` and labels. |
| **4** | Modes (bands, UGC and conquest extras, own-channel scan), `price`, `contacts`. |
| **5** | Report, pitches and follow-ups, `pipeline`, the `setup` flow, README. |
| **6** | End-to-end on 3 channels, tune weights against the eval, fix false positives, check timing. |
| **7** | Package as a plugin, record the demo, ship. |

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| YouTube blocks transcript fetching | Transcripts are optional. Description and flag signals carry v1. |
| Paid-promotion field is missing or empty for other people's videos | Fall back to text and link signals. Checked on Day 0. |
| Search relevance is weak for small niches or languages | Featured-channel expansion, and Claude rewrites the queries after the first pass. |
| False positives (gear lists, own products) | Evergreen filter, Claude classification, and the precision eval as a release gate. |
| Claude's context fills up | Scripts prefilter, and Claude sees at most about 150 snippets. |
| YouTube API policy blocks the shared database | Check the policies before building the paid tier. Doesn't affect v1. |

---

## 9. Decisions I've made (say if you disagree)

- Claude Code skill packaged as a plugin, not a hosted app.
- Python standard library, no install step.
- Every user brings their own API key and everything runs locally.
- Pipeline is a CSV and the report is Markdown. An HTML report is the stretch goal for the demo.
- Headline numbers count only `sponsored` evidence, never affiliate-only.

## 10. What I need from you

1. **A YouTube Data API key.** The setup flow walks you through it (about 5 minutes in Google Cloud Console).
2. **3 test channels:** yours, one around 500 subs, and one at 100k or more. Ideally one is Italian.
3. **Name check** before the public launch (GitHub, plugin marketplace, existing SaaS).
