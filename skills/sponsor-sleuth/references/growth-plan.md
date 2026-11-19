# Writing the growth plan

Write this when `rank` prints `REALISTIC=no`, meaning no brand in the scan paid a creator within 3x of the user's subscribers and views. Pitching those brands now would waste the contact. The honest answer is a target and a way to get there.

Input: `growth.json` (target, gap, ladder, habits, pace, start_now_codes), `profile.json` (the user's recent titles and views), `niche.json`, `brands.json` (`affiliate_only`), and `rate.json`.

Output: `RUN_DIR/growth-plan.md`. Write it in the language the user is chatting in.

## Hard rules

- **Every number comes from the run files.** That covers the target, the gap, milestones, upload rates, Shorts share, video length and views. Quote `verdict` rather than paraphrasing it.
- **The target is the smallest creator a brand paid, with proof.** Link the `floor_subs` and `floor_views` proof videos. If `basis` is `"code"`, say plainly that nobody in the scan had a disclosed paid deal, so the target is the smallest creator with a promo-code deal.
- **No invented growth facts.** Don't write things like "Shorts get 3x reach" or "consistency boosts the algorithm by 40%". Recommendations come from the gap between the user and the floor creators (`habits`), or are labeled as common practice.
- **No promised dates.** Only quote `pace.months_to_target` when `pace.reliable` is true, and call it a straight-line estimate at the user's average pace so far. Otherwise, say the channel is too new to estimate.
- **Steps the user can sustain.** If they upload once a month, don't jump to daily. Step up by roughly 2x per phase, toward the floor creators' cadence.
- **Video ideas are adapted, never copied.** Use the floor creators' `top_videos` and the user's own best recent videos to spot formats and topics that work. Never reuse another creator's title word for word.
- Same no-AI-tells rules as the pitches: no em dashes, none of the banned phrases in `pitch-guide.md`.

## Structure

```markdown
# Growth plan: <channel> to a first paid sponsor

**Target:** <subs> subscribers and <views> views per video. That's the smallest creator a brand paid in your niche (<brand>: <proof link>).
**You now:** <subs> subscribers, <views> median views. **Gap:** <subs_x>x subscribers, <views_x>x views.
**Milestones:** <milestones_subs joined with arrows>

## What the creators at the target do differently

| | You | Smallest paid creators (median of N) |
|---|---|---|
| Uploads per month | ... | ... |
| Shorts share | ... | ... |
| Long-form length | ... min | ... min |
| Views per 100 subscribers | ... | ... |

<2-3 sentences: the biggest gap first, each tied to a row of the table.>
<1-2 sentences on what their best recent videos have in common, from top_videos titles only.>

## The plan: next 90 days

### Weeks 1-4: <goal: first milestone>
- **Every week:** <uploads: N long-form + N Shorts>
- **Make these:** 3 concrete video ideas with working titles, in the user's channel language
- **Done when:** <a number: subscribers or median views>

### Weeks 5-8: <goal>
...

### Weeks 9-12: <goal>
...

## Meanwhile: what can pay now

- **Promo-code programs at your size:** <start_now_codes>. These are usually an open application, so apply rather than pitch.
- **Affiliate programs your lookalikes use:** top 3-5 from `brands.json` `affiliate_only`, with the network if known.
- **UGC:** brands buy videos for their own channels at <rate.json range> per asset. This needs 3 videos you'd show a brand. Offer to draft 3 UGC pitches when the user has them.

## Check-in

Run `/sponsor-sleuth @<handle>` again every 30 days, or at each milestone. The gap in the report should shrink. When it says `REALISTIC=yes`, sponsor pitches unlock.
```

## Choosing the phases

1. Start from the biggest `habits` gap. Usually that's upload frequency, then format: no long-form at all, or Shorts only when the floor creators mix the two.
2. Phase 1 builds the habit: a cadence the user can hold for 4 weeks. Its goal is the first milestone, or a median-views number if subscribers are already close.
3. Phase 2 doubles down on whatever got the most views in phase 1. Tell the user to check their own analytics, because we can't see watch time or retention.
4. Phase 3 moves toward the floor creators' cadence and format mix. It also builds the 3-video portfolio that UGC pitches need.
5. If the channel has fewer than 3 videos, phase 1 is simply to publish the first 4-6 videos in the niche, then rerun sponsor-sleuth so the comparison has real data.
