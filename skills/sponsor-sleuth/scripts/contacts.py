"""Find a brand's contact path: creator/affiliate program pages, partnership emails, affiliate networks.

Public pages only, robots.txt respected, 1 request/second per domain. LinkedIn is never
scraped: we hand the user a prefilled search link instead.
"""
from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from common import read_json, write_json
from net import PageFetcher, page_links, page_title

PATHS = [
    "/creators", "/creator", "/creator-program", "/partners", "/partnerships", "/partner",
    "/affiliate", "/affiliates", "/affiliate-program", "/influencer", "/influencers",
    "/ambassador", "/ambassadors", "/ugc", "/collab", "/sponsorship",
    "/pages/affiliate", "/pages/affiliates", "/pages/ambassador", "/pages/influencer", "/pages/partners",
]
KEYWORDS = re.compile(
    r"creator|partner|affiliat|influencer|ambassador|\bugc\b|collab|sponsor|affiliazion|collabora|"
    r"colaborad|afiliad|embajador|partenaire|kooperation|botschafter", re.I)
NOT_FOUND = re.compile(r"\b404\b|not found|page not found|pagina non trovata|no encontrada|nicht gefunden|introuvable", re.I)
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
PARTNER_EMAIL = re.compile(r"partner|influenc|creator|collab|affiliat|ambassador|sponsor|brand|marketing|"
                           r"press|media|\bpr\b|social|ugc", re.I)
GENERIC_EMAIL = re.compile(r"^(?:info|hello|hi|contact|support|team|ciao|hola|kontakt)@", re.I)
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def linkedin_search(brand: str) -> str:
    q = urllib.parse.quote(f"{brand} influencer marketing")
    return f"https://www.linkedin.com/search/results/people/?keywords={q}"


def _emails(html: str, domain: str) -> list[tuple[str, str]]:
    out = []
    base = domain.split(".")[0]
    for e in set(EMAIL.findall(html or "")):
        el = e.lower()
        if el.endswith(IMG_EXT) or "example" in el or "sentry" in el or "wixpress" in el:
            continue
        if base not in el.split("@", 1)[1]:
            continue  # only addresses on the brand's own domain
        kind = "partnerships" if PARTNER_EMAIL.search(el.split("@")[0]) else \
            "generic" if GENERIC_EMAIL.match(el) else None
        if kind:
            out.append((el, kind))
    return out


def _is_program_page(status: int, final_url: str, requested_path: str, html: str) -> bool:
    if status != 200 or not html:
        return False
    final_path = urllib.parse.urlsplit(final_url).path.rstrip("/").lower()
    if final_path in ("", "/") and requested_path not in ("", "/"):
        return False  # redirected to the homepage
    title = page_title(html)
    if NOT_FOUND.search(title):
        return False
    return bool(KEYWORDS.search(title) or KEYWORDS.search(final_path) or KEYWORDS.search(html[:20000]))


def find_contacts(domain: str, brand: str, networks: list[str], fetcher: PageFetcher, max_probe_hits: int = 2) -> dict:
    out = {"domain": domain, "program_pages": [], "emails": [], "networks": networks,
           "linkedin_search": linkedin_search(brand), "notes": []}
    base = f"https://{domain}"
    pages_html = []
    status, final, html = fetcher.get(base + "/")
    if status == -1:
        out["notes"].append("robots.txt disallows the homepage")
    elif status != 200:
        out["notes"].append(f"homepage returned HTTP {status or 'error'}")
    else:
        pages_html.append(html)
        seen = set()
        for url, text in page_links(html, final):
            host = (urllib.parse.urlsplit(url).hostname or "").lower()
            if domain not in host or url in seen:
                continue
            path = urllib.parse.urlsplit(url).path
            if KEYWORDS.search(path) or KEYWORDS.search(text):
                seen.add(url)
                out["program_pages"].append({"url": url, "label": text or path, "found_by": "homepage link"})
        # open the first two linked program pages: that's where partnership emails usually are
        for p in out["program_pages"][:2]:
            status, final, html = fetcher.get(p["url"])
            if status == 200 and html:
                pages_html.append(html)
    hits = 0
    for path in PATHS:
        if hits >= max_probe_hits:
            break
        if any(urllib.parse.urlsplit(p["url"]).path.rstrip("/").lower() == path for p in out["program_pages"]):
            continue
        status, final, html = fetcher.get(base + path)
        if _is_program_page(status, final, path, html):
            hits += 1
            pages_html.append(html)
            if final not in {p["url"] for p in out["program_pages"]}:
                out["program_pages"].append({"url": final, "label": page_title(html) or path, "found_by": "path probe"})
    for h in pages_html:
        for email, kind in _emails(h, domain):
            if email not in {e["email"] for e in out["emails"]}:
                out["emails"].append({"email": email, "kind": kind})
    out["emails"].sort(key=lambda e: e["kind"] != "partnerships")
    out["program_pages"] = out["program_pages"][:6]
    out["status"] = "found" if (out["program_pages"] or out["emails"] or networks) else "none"
    return out


def run_contacts(run_dir, top: int = 15, fetcher: PageFetcher | None = None) -> dict:
    data = read_json(run_dir / "brands.json")
    brands = data["brands"][:top]
    fetcher = fetcher or PageFetcher()
    results = read_json(run_dir / "contacts.json", default={})

    def work(b):
        if not b.get("domain"):
            return b["key"], {"domain": None, "program_pages": [], "emails": [], "networks": b.get("networks", []),
                              "linkedin_search": linkedin_search(b["name"]), "status": "none",
                              "notes": ["no brand domain known; search the web for the brand's creator program"]}
        try:
            return b["key"], find_contacts(b["domain"], b["name"], b.get("networks", []), fetcher)
        except Exception as e:  # never let one site break the run
            return b["key"], {"domain": b["domain"], "program_pages": [], "emails": [], "networks": b.get("networks", []),
                              "linkedin_search": linkedin_search(b["name"]), "status": "none", "notes": [f"error: {e}"]}

    with ThreadPoolExecutor(max_workers=8) as ex:
        for key, res in ex.map(work, brands):
            prev = results.get(key, {})
            if prev.get("manual"):
                res["manual"] = prev["manual"]  # keep anything Claude/the user added by hand
            results[key] = res
    write_json(run_dir / "contacts.json", results)
    return {"brands": len(brands), "found": sum(1 for b in brands if results[b["key"]]["status"] == "found")}
