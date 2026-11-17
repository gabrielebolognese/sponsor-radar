---
name: sponsor-radar
description: Find the brands that are paying YouTube creators your size in your niche right now, each with a link to the exact sponsored video as proof, price your integration, and draft personalized pitches and follow-ups. Use when the user runs /sponsor-radar, asks who sponsors creators like them, wants brand deals or sponsors for their YouTube channel, wants to pitch brands, asks what to charge for a sponsorship or integration, or wants to track sponsor outreach (pitched, replied, follow-ups due).
argument-hint: "@yourchannel | setup | pipeline | update <brand> <status> [amount]"
---

# sponsor-radar

Request: `$ARGUMENTS`

All data work is done by one CLI. Run it as:

```
python "${CLAUDE_SKILL_DIR}/scripts/radar.py" <command>
```

(Use `python3` if `python` isn't Python 3.10+.) Below, `RADAR` means that full command. Every stage writes its output into a run folder, `~/.sponsor-radar/runs/<handle>/<date>/`. Each stage prints `RUN_DIR`, a summary, and the next step. Stages can be rerun on their own.

## Route the request

- `setup`, or first use with no API key: go to **Setup**.
- `pipeline`, `followups`, `update <brand> <status> ...`: go to **Pipeline**.
- A handle (`@name`), a channel URL, or a channel ID: go to **Full scan**.
- Nothing given: run `RADAR runs`. If there are past runs, offer to show the latest report or the pipeline. Otherwise ask for their YouTube channel.

## Rules (non-negotiable)

1. **Nothing is guessed.** Every brand, number, rate and link must come from the run files. Every claim in a pitch must map to a proof in `pitch_brief.json`. If the data is thin, say so plainly instead of padding.
2. **Drafts only.** Never send an email or a DM, submit a form, or contact a brand. The user sends everything.
3. **Only `sponsored` means paid.** `code` means a promo code or tracked link, with no paid disclosure. `affiliate` means commission links only. Never call a `code` or `affiliate` brand one that "paid" a creator.
4. **The rate is a model.** It is median views x a CPM assumption until it's calibrated by the user's own closed deals. Never claim to know what other creators charge.
5. **Public pages only.** Never scrape LinkedIn or anything behind a login. Give the user the search link instead.
6. **Keep the context small.** The CLI prints summaries, so read JSON files only when a step needs them. Read big files in parts.

## Setup

1. Run `RADAR check`. If there's no key, it prints the 4 steps to get a free YouTube Data API key. Show them to the user and ask them to paste the key.
2. Ask for their currency (infer it from their country if known) and, optionally, what they charge per integration today. Then run `RADAR setup --key KEY --currency EUR [--rate 150]`. This validates the key.
3. Optional: `pip install youtube-transcript-api` turns on ad-read detection in transcripts. It's best-effort and nothing depends on it.

## Full scan

Tell the user up front that it scans about 50 lookalike creators, takes around 10 minutes, and uses about 1,700 of their 10,000 free daily API units.

1. **Profile.** Run `RADAR profile <channel>`. It prints the run folder, mode (UGC / Micro / Conquest), size, median views, language and recent titles.
2. **Niche.** Write `RUN_DIR/niche.json`, following `references/niche-and-queries.md`. The search queries you choose decide who the lookalikes are, so this is the most important judgment call in the run.
3. **Discover.** Run `RADAR discover --run <handle>`, then read `RUN_DIR/candidates.md`.
   - Write `RUN_DIR/exclude.json` (`{"exclude": ["UC..."]}`) for off-niche channels: wrong topic, news or compilation or reupload channels, kids channels, music labels, brand channels.
   - When unsure, keep the channel.
   - Then run `RADAR select --run <handle>`.
   - If fewer than 10 are selected, broaden the queries in `niche.json` and rerun discover. Each new query costs 100 units; queries already run come from the cache.
4. **Scan.** Run `RADAR scan --run <handle>`. It reads up to 30 videos per lookalike from the last 90 days, plus your own last 12 months.
5. **Classify.** Read `RUN_DIR/ambiguous.json` and write `RUN_DIR/classified.json`, following `references/classification.md`. Give every item a verdict. With more than 60 items, read and classify in batches, then write one combined file.
6. **Rank.** Run `RADAR rank --run <handle>`, then sanity-check the top 15.
   - If something is clearly the creator's own product, a platform, or not a brand, add its key to `exclude_brands` in `classified.json`.
   - If the same brand appears under two keys, add an `aliases` entry.
   - Add proper display names under `names` (for example `"nordvpn": "NordVPN"`).
   - Rerun rank after any change.
7. **Contacts.** Run `RADAR contacts --run <handle>`.
   - For the top 5 brands whose status is `none`, search the web: "<brand> creator program", "<brand> influencer partnership", "<brand> affiliate program".
   - If you find a program page or partnership email on the brand's own site or official program page, add it to that brand's entry in `contacts.json` as `"manual": "<url or email> (source: <url>)"`.
   - Don't use personal emails or data-broker sites.
8. **Price.** Run `RADAR price --run <handle>`. If the user mentions their current rate, run `RADAR setup --rate N` first.
9. **Report.** Run `RADAR report --run <handle>`. This writes `report.md` deterministically, so don't rewrite its numbers.
10. **Pitches.** Run `RADAR brief --run <handle>`.
    - Write one pitch file per brand for the top 10, into `RUN_DIR/pitches/NN-<key>.md` (for example `01-nordvpn.md`), following `references/pitch-guide.md`.
    - Follow the mode-specific framing in `references/modes.md`.
11. **Pipeline.** Run `RADAR pipeline add --run <handle> --top 10`.

### Present the results

Keep the chat answer short; the report has the detail.

- The headline lines from `report.md`, with the numbers exactly as written there.
- The top 10: brand, why it's ranked there, deal type, and one proof link each.
- The rate line, plus the rate check if there is one.
- Full paths to `report.md`, the pitches folder, and `~/.sponsor-radar/pipeline.csv`.
- One next action, for example: "Open pitch 01, watch the proof video, send it, then run `/sponsor-radar update <brand> pitched`."

If fewer than 5 brands turned up, say why (small niche, few disclosures, quota cut the discovery short) and what to try next.

## Pipeline

- **`pipeline`:** run `RADAR pipeline list`. For each follow-up that's due, show the matching follow-up draft from its pitch file.
- **`update <brand> <status> [amount]`:** run `RADAR pipeline update <brand> <status> [--amount N] [--note "..."]`.
  - Statuses: `pitched` (schedules follow-ups at day 4 and day 10), `followup` (you sent one), `replied`, `negotiating`, `closed`, `lost`.
  - When a deal closes with an amount, say that after 2 closed deals the rate model calibrates from real prices.
- **Replies:** if the user pastes a brand's reply, help them answer it as a draft. Anchor on the rate range, offer a hybrid (a flat fee plus affiliate) when the brand runs an affiliate program, and never go below the bottom of the range without saying so.

## When things go wrong

- **Quota exhausted:** results already fetched stay cached. Resume from the failed stage tomorrow, or with another key. `RADAR runs` shows how far each run got.
- **Channel not found:** ask for the exact handle as it appears in youtube.com/@handle.
- **YouTube blocks transcripts:** the scan carries on. Mention it once; detection then relies on descriptions and the paid-promotion flag.
- **No `classified.json`:** rank still works, but it uses only confident sightings.
