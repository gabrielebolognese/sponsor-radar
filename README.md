# sponsor-radar

**Find every brand that paid creators your size this month, and pitch them all in 10 minutes.**

Brands that sponsor creators leave public evidence everywhere: "this video is sponsored by", promo codes, tracking links, YouTube's paid-promotion flag. sponsor-radar is a Claude Code skill that collects that evidence from creators who look like you and turns it into a ranked list of brands that are spending money right now, at your size, in your niche. Every brand comes with a link to the exact video it was found in.

```
/sponsor-radar @yourchannel
```

## What you get

- **A ranked brand list** with proof links. It's scored on size fit, recency, repeat rate (a brand that comes back to the same creator 3 times is paying for results) and language fit.
- **The headlines:**
  - "23 brands sponsored creators your size in the last 30 days."
  - "8 brands sponsor creators like you but have never sponsored you."
  - "This brand came back to the same creator 4 times. Pitch them first."
- **The contact path** for the top brands: creator and affiliate program pages, partnership emails on the brand's own site, the affiliate network they run on, and a LinkedIn search link.
- **Your rate:** median views of your last 10 long-form videos x the CPM range for your niche. For example, 8,000 views x $15-30 = **$120-240 per integration**. The CPM range starts as an assumption and recalibrates from your own closed deals.
- **10 drafted pitches**, each with 2 follow-ups, written from the evidence ("you sponsored X and Y last month..."), with a 60-second integration concept and your rate.
- **A pipeline** (`pipeline.csv`, which opens in Sheets or Excel) that tracks drafted, pitched, replied, negotiating and closed, with follow-up reminders.
- **A reality check.** If no brand pays creators within 3x of your size, it says so instead of handing you pitches that will be ignored. Instead you get:
  - **A growth target:** the smallest creator in your niche that a brand actually paid, in subscribers and views per video, with the proof video.
  - **The gap** between you and that target.
  - **A 90-day plan**, built from what those creators do differently: upload rate, Shorts mix, video length.

It switches mode based on your size:

| Size | Mode | What it hunts |
|---|---|---|
| 0-1k | **UGC** | Brands that pay for content rather than reach, plus affiliate programs. The pitch is built on your portfolio, and the rate is per asset. |
| 1k-50k | **Micro** | Brands sponsoring your lookalikes, plus hybrid deals (a flat fee plus affiliate). |
| 50k+ | **Conquest** | Brands that sponsor your competitors but never you, renewals, and a rate check against your views. |

## Install

Requires [Claude Code](https://claude.com/claude-code) and Python 3.10+. There are no Python packages to install.

**As a plugin:**

```
/plugin marketplace add gabrielebolognese/sponsor-radar
/plugin install sponsor-radar@sponsor-radar
```

Plugin skills are namespaced, so the command is `/sponsor-radar:sponsor-radar @yourchannel`. You can also just ask Claude "find sponsors for @yourchannel".

**Or as a plain skill**, which gives you the shorter `/sponsor-radar` command:

```bash
git clone https://github.com/gabrielebolognese/sponsor-radar
cp -r sponsor-radar/skills/sponsor-radar ~/.claude/skills/
```

### Get a YouTube API key (free, about 5 minutes)

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project.
2. Go to **APIs & Services > Library** and enable **YouTube Data API v3**.
3. Go to **APIs & Services > Credentials > Create credentials > API key**. Restricting the key to the YouTube Data API v3 is a good idea.
4. Run `/sponsor-radar setup` and paste the key when asked, or set the `YOUTUBE_API_KEY` environment variable.

**Optional:** `pip install youtube-transcript-api` turns on ad-read detection in video transcripts (best-effort, see Limits).

## Usage

| Command | What it does |
|---|---|
| `/sponsor-radar @yourchannel` | Full scan: report, rate, 10 pitches, pipeline entries |
| `/sponsor-radar pipeline` | Your pipeline, plus the follow-ups due today and their drafts |
| `/sponsor-radar update NordVPN pitched` | Moves a deal along. `pitched` schedules follow-ups at day 4 and day 10 |
| `/sponsor-radar update NordVPN closed 300` | Logs a closed deal. After 2, your rate calibrates from real prices |
| `/sponsor-radar setup` | Sets the API key, currency, and your current rate (for the rate check) |

Everything is written to `~/.sponsor-radar/runs/<handle>/<date>/`: `report.md`, `pitches/`, and every intermediate file, so you can audit how each brand got on the list.

## How it works

```
profile ─▶ niche (Claude) ─▶ discover ─▶ prune (Claude) ─▶ scan ─▶ classify (Claude) ─▶ rank + reality check ─▶ contacts ─▶ price ─▶ report ─▶ pitches or growth plan (Claude)
```

- **Scripts do the deterministic work:** YouTube API calls, caching, link decoding, regex, scoring, files. They live in `skills/sponsor-radar/scripts/` and use only the Python standard library.
- **Claude does the judgment:** turning your channel into search queries, dropping off-niche lookalikes, classifying unclear signals (is this the creator's own merch or a sponsor?), and writing pitches. Claude is the host, so you don't need an Anthropic API key.

**Detection layers**, strongest first:
1. The paid-promotion flag.
2. Multilingual disclosure phrases (EN/IT/ES/DE/FR/PT): "sponsored by", "sponsorizzato da", "patrocinado por", "gesponsert von", "#ad", "*Werbung"...
3. Promo codes next to brand links.
4. Affiliate and tracking links, decoded to the brand (Impact, Awin, CJ, ShareASale, Partnerize, LTK...).
5. Influencer UTM parameters.
6. Transcript ad reads.

A link that appears in nearly every video of a creator is sent to Claude rather than counted, because it's usually their own shop or a gear list.

**Each brand is labeled `sponsored`, `code` or `affiliate`:**
- `sponsored`: paid evidence.
- `code`: a promo code or tracked link with no disclosure.
- `affiliate`: commission links only.

The headlines count only `sponsored`. Affiliate-only brands get their own section, because they're often the easiest first yes.

### Quota

The YouTube Data API's free tier is 10,000 units a day.

| Step | Units |
|---|---|
| Profile | ~5 |
| Discovery: up to 15 searches x 100 | ≤1,500 |
| Featured channels + channel stats | ~25 |
| Scanning 50 creators x 30 videos | ~100 |
| Your own last 12 months | ~10 |
| **Full scan** | **~1,650** |

That's about 6 full scans a day. Searches are cached for a week and everything else for about a day, so reruns are close to free.

## Guardrails

- **It drafts, you send.** No automated emailing or DMs. That keeps it GDPR-friendly and keeps your domain off spam lists.
- **Every brand has a proof link.** Brands are never inferred from general knowledge.
- **Public pages only.** It respects robots.txt and stays at 1 request per second per site. LinkedIn is never scraped; you get a search link instead.
- **Your data stays local.** Your API key, runs and pipeline live in `~/.sponsor-radar/`. There's no telemetry.

## Limits

- **YouTube only (v1).** Podcasts and Instagram/TikTok are on the roadmap.
- **Transcripts are best-effort.** The official API only returns captions for your own videos, so transcript ad reads rely on `youtube-transcript-api`, which YouTube sometimes blocks. They're only used to name the brand when a video is flagged as paid but its description doesn't say who paid.
- **Recall isn't 100%.** Undisclosed deals with no code or link can't be detected. The system is tuned so that what it does list is real.
- **The rate is a model, not market data.** Nobody publishes what creators actually get paid. The CPM ranges in `references/cpm.json` are starting assumptions until you log your own closed deals.
- **Status: v0.1.** It's fully tested offline against a simulated YouTube API (see `tests/`). Expect tuning after the first real-world runs.

## Development

```bash
python -m unittest discover -s tests -v   # unit + offline end-to-end, no key or network needed
python skills/sponsor-radar/scripts/radar.py --help
```

- **Add a phrase or a language:** edit `_SPONSOR_SRC` and `_CODE_SRC_CI` in `scripts/signals.py` and add a test in `tests/test_signals.py`.
- **Add a domain** (an affiliate network, shortener, creator platform...): edit `references/link-domains.json`. No code change needed.
- **Tune the ranking:** override any weight in `~/.sponsor-radar/config.json` under `"weights"` (see `DEFAULT_WEIGHTS` in `scripts/rank.py`).

The original design notes are in [`docs/plan.md`](docs/plan.md).

## License

MIT
