"""Outreach pipeline in a CSV you can open in Sheets/Excel: drafted -> pitched -> replied -> negotiating -> closed/lost."""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from common import home, read_json

COLUMNS = ["brand_key", "brand", "domain", "status", "contact", "pitch_file", "added_at", "pitched_at",
           "followups", "next_followup", "closed_at", "amount", "currency", "views_at_deal", "notes"]
STATUSES = ["drafted", "pitched", "followup", "replied", "negotiating", "closed", "lost"]
FOLLOWUP_DAYS = [4, 6]  # first follow-up 4 days after pitching, second 6 days after the first


def pipeline_file() -> Path:
    return home() / "pipeline.csv"


def load(path: Path | None = None) -> list[dict]:
    path = path or pipeline_file()
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{c: row.get(c, "") or "" for c in COLUMNS} for row in csv.DictReader(f)]


def save(rows: list[dict], path: Path | None = None) -> Path:
    path = path or pipeline_file()
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLUMNS})
    return path


def find(rows: list[dict], query: str) -> dict:
    q = query.lower().strip()
    exact = [r for r in rows if q in (r["brand_key"].lower(), r["brand"].lower(), r["domain"].lower())]
    if len(exact) == 1:
        return exact[0]
    partial = [r for r in rows if q in r["brand"].lower() or q in r["domain"].lower() or q in r["brand_key"]]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise SystemExit(f"No pipeline entry matches '{query}'. Run: sleuth.py pipeline list")
    raise SystemExit(f"'{query}' matches several entries: " + ", ".join(r["brand"] for r in partial))


def add_from_run(run_dir: Path, top: int, today: date, currency: str, path: Path | None = None) -> list[dict]:
    rows = load(path)
    have = {r["brand_key"] for r in rows if r["status"] not in ("closed", "lost")}
    brands = read_json(run_dir / "brands.json")["brands"][:top]
    contacts = read_json(run_dir / "contacts.json", default={})
    profile = read_json(run_dir / "profile.json")
    added = []
    for b in brands:
        if b["key"] in have:
            continue
        c = contacts.get(b["key"], {})
        contact = (c.get("emails") or [{}])[0].get("email") or \
            (c.get("program_pages") or [{}])[0].get("url") or ""
        pitch = sorted((run_dir / "pitches").glob(f"*{b['key']}*.md")) if (run_dir / "pitches").exists() else []
        row = {"brand_key": b["key"], "brand": b["name"], "domain": b.get("domain") or "", "status": "drafted",
               "contact": contact, "pitch_file": str(pitch[0]) if pitch else "", "added_at": today.isoformat(),
               "followups": "0", "currency": currency,
               "views_at_deal": str(int(profile["stats"].get("median_views_long") or 0))}
        rows.append(row)
        added.append(row)
    save(rows, path)
    return added


def update(query: str, status: str, today: date, amount: str | None = None, currency: str | None = None,
           views: str | None = None, contact: str | None = None, note: str | None = None,
           path: Path | None = None) -> dict:
    status = status.lower().replace("-", "").replace("_", "")
    status = {"followedup": "followup", "follow": "followup", "won": "closed", "negotiation": "negotiating"}.get(status, status)
    if status not in STATUSES:
        raise SystemExit(f"Unknown status '{status}'. Use one of: {', '.join(STATUSES)}")
    rows = load(path)
    r = find(rows, query)
    if status == "pitched":
        r["status"] = "pitched"
        r["pitched_at"] = r["pitched_at"] or today.isoformat()
        r["followups"] = "0"
        r["next_followup"] = (today + timedelta(days=FOLLOWUP_DAYS[0])).isoformat()
    elif status == "followup":
        n = int(r["followups"] or 0) + 1
        r["followups"] = str(n)
        r["status"] = "pitched"
        r["next_followup"] = (today + timedelta(days=FOLLOWUP_DAYS[n])).isoformat() if n < len(FOLLOWUP_DAYS) else ""
    else:
        r["status"] = status
        r["next_followup"] = ""
        if status == "closed":
            r["closed_at"] = today.isoformat()
    if amount is not None:
        r["amount"] = str(amount)
    if currency:
        r["currency"] = currency.upper()
    if views:
        r["views_at_deal"] = str(views)
    if contact:
        r["contact"] = contact
    if note:
        r["notes"] = (r["notes"] + " | " if r["notes"] else "") + f"{today.isoformat()}: {note}"
    save(rows, path)
    return r


def due(rows: list[dict], today: date) -> list[dict]:
    out = []
    for r in rows:
        if r["status"] == "pitched" and r["next_followup"]:
            try:
                if date.fromisoformat(r["next_followup"]) <= today:
                    out.append(r)
            except ValueError:
                pass
    return out


def closed_deals(rows: list[dict] | None = None) -> list[dict]:
    return [r for r in (rows if rows is not None else load()) if r["status"] == "closed" and r["amount"]]


def render(rows: list[dict], today: date) -> str:
    if not rows:
        return "Pipeline is empty. After a scan: sleuth.py pipeline add --run @handle"
    order = {s: i for i, s in enumerate(["negotiating", "replied", "pitched", "drafted", "closed", "lost"])}
    rows = sorted(rows, key=lambda r: (order.get(r["status"], 9), r["next_followup"] or "9999"))
    out = ["| brand | status | contact | pitched | follow-up due | amount |", "|---|---|---|---|---|---|"]
    for r in rows:
        due_s = r["next_followup"]
        if due_s and r["status"] == "pitched" and date.fromisoformat(due_s) <= today:
            due_s = f"**{due_s} (due)**"
        amt = f"{r['amount']} {r['currency']}" if r["amount"] else ""
        out.append(f"| {r['brand']} | {r['status']} | {r['contact'][:50]} | {r['pitched_at']} | {due_s} | {amt} |")
    d = due(rows, today)
    if d:
        out += ["", f"{len(d)} follow-up(s) due today: " + ", ".join(r["brand"] for r in d)]
    return "\n".join(out)
