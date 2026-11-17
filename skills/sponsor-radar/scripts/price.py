"""Price an integration: median views x niche CPM range, calibrated by your own closed deals."""
from __future__ import annotations

import json

from common import REFERENCES, fmt_int, median, read_json, write_json

SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹", "BRL": "R$", "CHF": "CHF ",
           "CAD": "CA$", "AUD": "A$", "MXN": "MX$"}


def money(amount: float, currency: str) -> str:
    sym = SYMBOLS.get(currency, currency + " ")
    return f"{sym}{fmt_int(amount)}"


def nice_round(x: float) -> float:
    if x < 100:
        return round(x / 5) * 5
    if x < 1000:
        return round(x / 10) * 10
    return round(x / 50) * 50


def cpm_table() -> dict:
    return json.loads((REFERENCES / "cpm.json").read_text(encoding="utf-8"))


def calibration(deals: list[dict], fx: dict, base_mid: float) -> tuple[float | None, int]:
    eff = []
    for d in deals:
        try:
            amount = float(d.get("amount") or 0)
            views = float(d.get("views_at_deal") or 0)
        except ValueError:
            continue
        if amount <= 0 or views <= 0:
            continue
        rate_usd = amount / float(fx.get((d.get("currency") or "USD").upper(), 1.0))
        eff.append(rate_usd / views * 1000)
    if len(eff) < 2 or base_mid <= 0:
        return None, len(eff)
    return median(eff) / base_mid, len(eff)


def compute_rate(profile: dict, niche: dict, cfg: dict, closed_deals: list[dict] | None = None) -> dict:
    table = cpm_table()
    currency = (cfg.get("currency") or "USD").upper()
    fx = cfg.get("fx_from_usd", {})
    rate_fx = float(fx.get(currency, 1.0))
    bucket = (niche.get("cpm_bucket") or "default").lower()
    lo, hi = table["buckets"].get(bucket, table["buckets"]["default"])
    stats = profile["stats"]
    mode = profile["mode"]
    shorts_only = stats.get("long_count", 0) < 3 and stats.get("short_count", 0) > 0
    out = {"currency": currency, "bucket": bucket, "mode": mode, "assumption": True}

    if mode == "ugc":
        a, b = table["ugc_per_asset_usd"]
        out.update(basis="per UGC asset (portfolio-based, not reach-based)",
                   low=nice_round(a * rate_fx), high=nice_round(b * rate_fx), median_views=stats.get("median_views_long"))
        out["explain"] = (f"Under 1k subscribers, brands pay for the content, not the reach: "
                          f"{money(out['low'], currency)}-{money(out['high'], currency)} per video asset is a common starting range.")
    else:
        views = stats.get("median_views_shorts") if shorts_only else stats.get("median_views_long")
        views = views or 0
        if shorts_only:
            m_lo, m_hi = table["shorts_multiplier"]
            lo, hi = lo * m_lo, hi * m_hi
        mult, n_deals = calibration(closed_deals or [], fx, (lo + hi) / 2)
        if mult:
            lo, hi = lo * mult, hi * mult
            out["calibrated_from_deals"] = n_deals
            out["assumption"] = False
        low_usd, high_usd = views * lo / 1000, views * hi / 1000
        out.update(basis="per Short integration" if shorts_only else "per integration (60-90s ad read)",
                   median_views=views, cpm_usd=[round(lo, 1), round(hi, 1)],
                   low=nice_round(low_usd * rate_fx), high=nice_round(high_usd * rate_fx))
        cpm_lo, cpm_hi = money(lo * rate_fx, currency), money(hi * rate_fx, currency)
        out["explain"] = (f"{fmt_int(views)} median views x {cpm_lo}-{cpm_hi} CPM = "
                          f"{money(out['low'], currency)}-{money(out['high'], currency)} {out['basis']}")
        if high_usd < table.get("min_viable_rate_usd", 50):
            out["note"] = ("Your CPM rate is below what most brands bother with. Lead with affiliate or "
                           "flat UGC deals until views grow.")
    if not out.get("calibrated_from_deals"):
        out["explain"] += (f" (CPM range is a starting assumption for '{bucket}'; it calibrates after 2 closed deals.)")

    current = cfg.get("current_rate")
    if current:
        current = float(current)
        out["current_rate"] = current
        if current < out["low"]:
            pct = round((out["low"] - current) / out["low"] * 100)
            out["rate_check"] = (f"You charge {money(current, currency)}. Your views price you at "
                                 f"{money(out['low'], currency)}-{money(out['high'], currency)}: "
                                 f"you're about {pct}% under the bottom of that range.")
        elif current > out["high"]:
            out["rate_check"] = (f"You charge {money(current, currency)}, above the model's "
                                 f"{money(out['high'], currency)} top. Fine if you're closing; if brands go quiet, this is why.")
        else:
            out["rate_check"] = f"You charge {money(current, currency)}, inside the model's range."
    return out


def run_price(run_dir, cfg: dict, closed_deals: list[dict]) -> dict:
    profile = read_json(run_dir / "profile.json")
    niche = read_json(run_dir / "niche.json", default={})
    rate = compute_rate(profile, niche, cfg, closed_deals)
    write_json(run_dir / "rate.json", rate)
    return rate
