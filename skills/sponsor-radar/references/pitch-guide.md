# Writing the pitches

Input: `pitch_brief.json`. It holds the creator's profile, the rate, and the top brands, each with labels, its proofs (the actual sponsored videos) and contact paths. Output: one file per brand in `RUN_DIR/pitches/NN-<key>.md`.

## Hard rules

- **Every factual claim must come from the brief.** That means which creators the brand sponsored, when, the creator's numbers, and the rate.
- **Never claim audience overlap, demographics, conversion rates or past results.** We don't have that data.
- If a sentence needs something only the user knows (their name, a past result, a specific idea they'd film), put a `[placeholder in brackets]`.
- **Language:**
  - Write in the language of the brand's market, taken from `languages` in the brief.
  - If the brand only sponsors Italian creators, write in Italian. Mixed or English sponsors get English.
  - If the creator's language differs from the brand's, write in the brand's.
- **Rate:**
  - State one number, not a range.
  - Anchor at the top of the range for brands with a repeat or "your size" label, and in the middle otherwise.
  - Never go below `rate.low`.
  - If the brand runs codes or affiliate links (`codes` or the `hybrid` flag), offer a hybrid as an option: a lower flat fee plus a commission on their code.

## Structure

```markdown
# 01 · NordVPN (nordvpn.com)

**Send to:** partners@nordvpn.com
**Why them:** 3 creators your size this quarter; came back 3x to Luca Calisthenics
**Proof:** https://www.youtube.com/watch?v=... · https://www.youtube.com/watch?v=...
**Rate in this pitch:** €220 (your range €110-220)

## Subject options
1. Calisthenics integration for NordVPN
2. You sponsored Luca Calisthenics. I'm next door.
3. 60s NordVPN spot, Italian calisthenics audience

## Email
...

## Follow-up 1 (day 4, if no reply)
...

## Follow-up 2 (day 10, last one)
...
```

## The email: under 150 words, in this order

1. **Evidence (1-2 sentences).** Name the creators they sponsored, taken from the proofs: "You sponsored Luca Calisthenics and Street Workout IT in the last two months."
2. **Fit (1-2 sentences).** Use only the creator's real numbers: niche, language, subscribers, median views per video. "Same niche, same audience language, {median} views per video."
3. **Concept (2-3 sentences).** A specific 60-second integration that fits the creator's actual content. Use `recent_titles` to pick a format that already exists on the channel: where the spot sits, what's on screen, the call to action (their code or link).
4. **Rate (1 sentence).** "My rate for a 60-second integration is €220."
5. **One ask.** A low-friction yes or no question: "Open to a test video in [month]?"
6. Sign-off: `[Your name]`, then the channel URL.

## Follow-ups

- **Day 4:** 2-3 lines with a new angle, such as a second concept idea, a fresh video that fits, or a seasonal hook. No "just checking in", no guilt.
- **Day 10:** 2 lines. Give them an easy out ("if the timing's wrong, no problem, I'll try again next quarter") and leave the door open.

## By mode

- **UGC (<1k subs):** lead with the work, not the numbers. Link the 3 best videos (`best_videos`) and pitch content they can run as ads or post on their own channels, priced per asset. Affiliate-program brands get a one-line "I'd like to join your creator program" ask instead.
- **Micro:** the structure above, plus the hybrid offer whenever the brand runs codes.
- **Conquest (50k+):**
  - For brands labeled "never you", say plainly that they back competitors and that this channel is the gap in their lineup.
  - For renewals, write "We worked together in [month]; [result]" and leave the result for the user to fill in.
  - If an agency appears in `contact`, address the agency.

## Style: no AI tells

- No em dashes. Use a period, a comma or a colon instead.
- Short sentences and contractions. At most one exclamation mark per email.
- Banned phrases: "I hope this email finds you well", "delve", "elevate", "seamless", "leverage", "unlock", "game-changer", "synergy", "thrilled", "excited to", "resonate", "testament", "in today's fast-paced", "I came across your brand".
- It should read like a creator who watches their own analytics wrote it in 5 minutes.
- If a humanizer or de-AI skill is installed, run each draft through it before saving.
