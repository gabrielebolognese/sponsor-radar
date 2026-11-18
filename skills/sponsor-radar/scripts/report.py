"""Deterministic report.md: every number and link comes from the run files, nothing is written freehand."""
from __future__ import annotations

from common import fmt_int, read_json

MODE_NAMES = {"ugc": "UGC mode", "micro": "Micro mode", "conquest": "Conquest mode"}
TYPE_LABEL = {"sponsored": "sponsored", "code": "code/link", "affiliate": "affiliate"}


def _proofs(b: dict, n: int = 3) -> str:
    return " ".join(f"[{i}]({p['video_url']})" for i, p in enumerate(b["proofs"][:n], 1))


def _contact(c: dict | None) -> str:
    if not c:
        return "not checked"
    if c.get("manual"):
        return str(c["manual"])[:60]
    if c.get("emails"):
        return c["emails"][0]["email"]
    if c.get("program_pages"):
        p = c["program_pages"][0]
        return f"[{(p.get('label') or 'program page')[:30]}]({p['url']})"
    if c.get("networks"):
        return "via " + ", ".join(c["networks"])
    return f"[LinkedIn search]({c['linkedin_search']})" if c.get("linkedin_search") else "none found"


def _pct(x) -> str:
    return "" if x is None else f"{round(x * 100)}%"


def _num(x) -> str:
    return "?" if x is None else fmt_int(x)


def _gap(x) -> str:
    return "-" if not x else (f"{round(x)}x" if x >= 10 else f"{x}x")


def growth_section(g: dict, run_dir) -> list[str]:
    """The reality check. Leads the report when no sponsor is within reach."""
    L = ["## Not yet: no brand pays creators your size", "", g["verdict"], ""]
    you, t, gap = g["you"], g["target"], g["gap"]
    if t["subs"] or t["median_views"]:
        who = "smallest paid creator" if g["basis"] == "sponsored" else "smallest creator with a promo-code deal"
        L += [f"| | You | Target ({who}) | Gap |", "|---|---|---|---|",
              f"| Subscribers | {_num(you['subs'])} | {_num(t['subs'])} | {_gap(gap['subs_x'])} |",
              f"| Median views per video | {_num(you['median_views_long'])} | {_num(t['median_views'])} | "
              f"{_gap(gap['views_x'])} |", ""]
    e = g.get("entry_level")
    if e:
        L += [f"Most paid creators in this scan are bigger than the target: the bottom quarter of the {e['n']} starts at "
              f"{fmt_int(e['subs'])} subscribers" + (f" and {fmt_int(e['median_views'])} views per video" if e["median_views"] else "")
              + ". The target is the first door, not the typical one.", ""]
    if len(g["milestones_subs"]) > 1:
        L += ["Milestones: " + " → ".join(fmt_int(m) for m in g["milestones_subs"]) + " subscribers.", ""]
    if g["ladder"]:
        L += ["**The smallest creators brands paid.** Open these: they're what the target looks like.", "",
              "| Creator | Subs | Median views | Uploads/mo | Shorts | Paid by | Proof |", "|---|---|---|---|---|---|---|"]
        for r in g["ladder"]:
            L.append(f"| [{r['title'][:40]}]({r['url']}) | {_num(r['subs'])} | {_num(r['median_views_long'])} | "
                     f"{r['uploads_per_month_90d'] if r['uploads_per_month_90d'] is not None else '?'} | "
                     f"{_pct(r['shorts_share'])} | {', '.join(r['brands'][:3])} | [video]({r['proof_url']}) |")
        L.append("")
    cov, fs = g["coverage"], g.get("floor_subs")
    if fs and cov.get("smallest_scanned_subs") and fs["subs"] <= 1.5 * cov["smallest_scanned_subs"]:
        L += [f"The scan went down to creators with {fmt_int(cov['smallest_scanned_subs'])} subscribers, and the "
              "target sits close to that line, so a smaller paid creator may exist below it.", ""]
    if (run_dir / "growth-plan.md").exists():
        L += ["**Your plan to get there:** `growth-plan.md` in this folder.", ""]
    if g["start_now_codes"]:
        L += ["**Start now:** these brands gave promo codes to creators within reach of your size (often an "
              "open application, not a negotiation): " + ", ".join(g["start_now_codes"][:10]) + ".", ""]
    L += ["Everything below is still useful: it's who pays in your niche once you cross the target.", ""]
    return L


def build_report(run_dir) -> str:
    profile = read_json(run_dir / "profile.json")
    data = read_json(run_dir / "brands.json")
    stats = read_json(run_dir / "scan_stats.json", default={})
    rate = read_json(run_dir / "rate.json", default={})
    contacts = read_json(run_dir / "contacts.json", default={})
    quota = read_json(run_dir / "quota.json", default={})
    growth = read_json(run_dir / "growth.json", default=None)
    ugc = profile["mode"] == "ugc"
    ch, st, h = profile["channel"], profile["stats"], data["headline"]
    brands = data["brands"]
    L = []
    L.append(f"# sponsor-radar: {ch['title']} ({ch.get('handle') or profile['input']})")
    L.append("")
    L.append(f"{MODE_NAMES.get(profile['mode'], profile['mode'])} · {fmt_int(ch.get('subs'))} subscribers · "
             f"median {fmt_int(st.get('median_views_long'))} views (last 10 long-form) · "
             f"run {data['generated_at'][:10]}")
    L.append("")
    L.append(f"Scanned {stats.get('creators_scanned', '?')} lookalike creators and "
             f"{fmt_int(stats.get('videos_scanned'))} videos from the last 90 days"
             + (f", plus {stats.get('own_videos_scanned')} of your own videos (12 months)." if stats.get("own_videos_scanned") else ".")
             + (f" YouTube API quota used: {fmt_int(sum(quota.values()))} units." if quota else ""))
    L.append("")
    if growth and not growth["realistic"]:
        L += growth_section(growth, run_dir)
    L.append("## Headlines")
    L.append("")
    if growth and growth["realistic"]:
        L.append(f"- **Within reach:** {growth['verdict']}")
    size_txt = "small creators (2k-50k subscribers)" if ugc else "creators your size"
    L.append(f"- **{h['sponsored_your_size_30d']} brands sponsored {size_txt} in the last 30 days.**"
             + (f" ({h['deals_your_size_30d_incl_codes']} including promo-code deals.)"
                if h["deals_your_size_30d_incl_codes"] != h["sponsored_your_size_30d"] else ""))
    # "never sponsored you" only means something once a sponsor is within reach
    if h.get("never_sponsored_you") is not None and not (growth and not growth["realistic"]):
        L.append(f"- **{h['never_sponsored_you']} brands sponsor creators like you but have never sponsored you.**")
    if h.get("top_repeat"):
        t = h["top_repeat"]
        L.append(f"- **{t['brand']} came back to {t['creator']} {t['times']} times.** It's working for them. Pitch them first.")
    if rate:
        L.append(f"- **Your rate:** {rate['explain']}")
        if rate.get("rate_check"):
            L.append(f"- **Rate check:** {rate['rate_check']}")
    if h.get("own_sponsors"):
        L.append(f"- Brands already on your channel: {', '.join(h['own_sponsors'])}.")
    L.append("")
    L.append("## Ranked brands")
    L.append("")
    if not brands:
        L.append("No sponsor evidence found. Try broader niche queries, or check the scan stats below.")
    else:
        L.append("| # | Brand | Why | Deal | Last seen | Contact | Proof |")
        L.append("|---|---|---|---|---|---|---|")
        for b in brands[:40]:
            flags = " · ".join(x for x in b["labels"] if "your size" not in x and "small creator" not in x)
            flags = (" · " + flags) if flags else ""
            deal = TYPE_LABEL[b["type"]] + (" + affiliate" if b["hybrid"] else "")
            if b["codes"]:
                deal += f" (code {b['codes'][0]})"
            name = b["name"] if not b.get("domain") or b["name"] == b["domain"] else f"{b['name']} ({b['domain']})"
            L.append(f"| {b['rank']} | **{name}** | {b['why']}{flags} | {deal} | {b['last_seen_days']}d | "
                     f"{_contact(contacts.get(b['key']))} | {_proofs(b)} |")
    if data.get("affiliate_only"):
        L.append("")
        L.append("## Affiliate programs your lookalikes use")
        L.append("")
        L.append("Commission-only evidence (affiliate links, no paid disclosure). Not counted in the headlines, "
                 "but easy to join and a good way in for a later paid deal.")
        L.append("")
        for b in data["affiliate_only"][:15]:
            nets = f" via {', '.join(b['networks'])}" if b["networks"] else ""
            L.append(f"- **{b['name']}**{nets}: {b['n_creators']} creator(s), last seen {b['last_seen_days']}d ago. {_proofs(b, 2)}")
    if rate:
        L.append("")
        L.append("## Your rate")
        L.append("")
        L.append(rate["explain"])
        if rate.get("note"):
            L.append("")
            L.append(rate["note"])
    L.append("")
    L.append("## How to read this")
    L.append("")
    L.append("- **sponsored**: paid evidence (YouTube's paid-promotion flag, a \"sponsored by\" disclosure, or an ad read).")
    L.append("- **code/link**: a promo code or tracking link for the brand, no explicit paid disclosure.")
    L.append("- **affiliate**: commission links only. Nobody necessarily got paid upfront.")
    L.append("- \"Small creators\" means 2k-50k subscribers: under 1k, views are too noisy to match on."
             if ugc else "- \"Your size\" means the creator's median views are 0.5x-3x yours.")
    if growth:
        L.append(f"- \"Within reach\" means at most {growth['reach_multiple']:g}x your subscribers and {growth['reach_multiple']:g}x "
                 "your median views. The growth target is the smallest creator in this scan that a brand paid.")
    L.append("- Every brand links to the exact videos it was found in. Click before you pitch.")
    tr = stats.get("transcripts") or {}
    notes = []
    if not stats.get("paid_flag_supported", True):
        notes.append("the API didn't return the paid-promotion flag, so detection used descriptions only")
    if tr.get("stopped_reason"):
        notes.append(f"transcripts: {tr['stopped_reason']}")
    if stats.get("ambiguous_dropped"):
        notes.append(f"{stats['ambiguous_dropped']} low-priority ambiguous videos were skipped")
    if notes:
        L.append("- Scan notes: " + "; ".join(notes) + ".")
    return "\n".join(L) + "\n"


def run_report(run_dir) -> str:
    text = build_report(run_dir)
    (run_dir / "report.md").write_text(text, encoding="utf-8")
    return text
