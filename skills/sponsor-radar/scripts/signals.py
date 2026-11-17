"""Sponsor-signal detection for YouTube descriptions and transcripts.

Pure functions, no network. Link resolution is injected as a callable (see net.py).
Precision beats recall: anything we can't attribute confidently goes to Claude
as an "ambiguous" item instead of being guessed.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from functools import lru_cache

from common import REFERENCES, slug


@lru_cache(maxsize=1)
def lists() -> dict:
    d = json.loads((REFERENCES / "link-domains.json").read_text(encoding="utf-8"))
    for k in ("social", "creator_platforms", "ignore", "marketplaces", "gear", "shorteners",
              "affiliate_params", "coupon_params", "affiliate_path_tokens", "influencer_utm_mediums",
              "generic_subdomains", "multi_part_suffixes"):
        d[k] = set(d[k])
    return d


# ---------------------------------------------------------------------------
# Phrase patterns (EN / IT / ES / DE / FR / PT)
# ---------------------------------------------------------------------------

_B = r"(?P<brand>[^.!?\n]{2,40}?)"
_SPONSOR_SRC = [
    # English
    r"sponsored by", r"this (?:video|episode) is sponsored", r"today'?s (?:video|episode) is sponsored",
    rf"thanks? (?:again )?to {_B} for sponsoring", r"brought to you by", r"paid (?:partnership|promotion)",
    r"in (?:paid )?partnership with", r"partnered with", r"today'?s sponsor",
    r"sponsor of (?:this|today'?s) (?:video|episode)", r"sponsor\s*:",
    # Italian
    r"sponsorizzat[oa] da", r"(?:questo|il) video (?:è|e'|e) sponsorizzato", r"in collaborazione con",
    r"in partnership con", rf"grazie a {_B} per (?:aver )?sponsorizzato", r"contenuto sponsorizzato",
    r"(?:partnership|collaborazione) (?:retribuita|commerciale|a pagamento)",
    r"sponsor (?:del|di questo) video", r"sponsor di oggi",
    # Spanish
    r"patrocinado por", r"patrocinio de", rf"gracias a {_B} por patrocinar", r"en colaboraci[oó]n con",
    r"(?:este|el) v[ií]deo (?:est[aá] )?patrocinado",
    # German
    r"gesponsert von", r"in zusammenarbeit mit", r"bezahlte partnerschaft",
    rf"dank an {_B} f[uü]r (?:das )?sponsoring",
    # French
    r"sponsoris[ée]e? par", r"en partenariat avec", rf"merci [àa] {_B} (?:de|pour) (?:sponsoriser|avoir sponsoris[ée])",
    r"collaboration commerciale", r"partenariat r[ée]mun[ée]r[ée]",
    # Portuguese
    r"em parceria com", r"parceria paga", rf"obrigad[oa] (?:[àa]|ao) {_B} por patrocinar", r"patrocinad[oa] pel[oa]",
]
SPONSOR_RE = [re.compile(r"(?<!\w)" + p, re.I) for p in _SPONSOR_SRC]
# Line-start disclosures ("*Werbung", "Anzeige |"). "unbezahlte Werbung" (gifted, unpaid) does not match.
LINE_START_RE = re.compile(r"^[\W_]*(?:werbung|anzeige|publicidad|publicidade|pubblicit[aà])\b", re.I)
HASHTAG_RE = re.compile(
    r"(?<![\w#])#(?:ad|ads|sponsored|sponsor|adv|advertising|advertisement|sponsorizzato|sponsorizzata|"
    r"publi|publicidad|publicidade|werbung|anzeige|pub|sponso|partenariat|paidpartnership|spon)(?!\w)", re.I)

_Q = r"[\"'“”‘’«»]?"
_CODE = r"([A-Za-z0-9][A-Za-z0-9_-]{2,19})"
_CODE_SRC_CI = [
    rf"\b(?:use|using|with|enter|apply)\s+(?:my\s+|the\s+|our\s+)?(?:promo\s+|discount\s+|coupon\s+)?code\s*[:\-]?\s*{_Q}{_CODE}",
    rf"\b(?:promo|discount|coupon)\s+code\s*[:\-]?\s*{_Q}{_CODE}",
    rf"\bcodice(?:\s+(?:sconto|promo|promozionale))?\s*[:\-]?\s*{_Q}{_CODE}",
    rf"\bc[oó]digo(?:\s+(?:de\s+descuento|promocional|de\s+desconto|de\s+cupom|promo))?\s*[:\-]?\s*{_Q}{_CODE}",
    rf"\b(?:rabatt|gutschein)code\s*[:\-]?\s*{_Q}{_CODE}",
    rf"\bcode\s+promo\s*[:\-]?\s*{_Q}{_CODE}",
    rf"\b(?:cup[oó]n|cupom)\s*[:\-]?\s*{_Q}{_CODE}",
]
CODE_RE = [re.compile(p, re.I) for p in _CODE_SRC_CI]
# "code MARCO10" — only accepted when the code itself is uppercase/digits.
CODE_UPPER_RE = re.compile(rf"\b[Cc]ode\s*[:\-]?\s*{_Q}([A-Z0-9][A-Z0-9_-]{{2,19}})\b")
CODE_STOPWORDS = {
    "code", "codes", "sconto", "the", "for", "per", "and", "below", "here", "qui", "sotto", "off", "checkout",
    "link", "descuento", "desconto", "promo", "this", "that", "una", "uno", "con", "your", "you", "mit",
    "pour", "avec", "para", "por", "with", "get", "use", "and", "und", "della", "dello", "nella", "in",
    "description", "descrizione", "descripcion", "beschreibung", "bio", "above", "sopra",
}

OFFER_RE = re.compile(
    r"\b\d{1,2}\s?%\s?(?:off|di sconto|de descuento|rabatt|de r[ée]duction|de desconto|discount|sconto)\b|"
    r"\b(?:sconto|descuento|rabatt|r[ée]duction|desconto|save)\s+(?:del\s+|de\s+|von\s+)?\d{1,2}\s?%|"
    r"\bfree trial\b|\bprova gratuita\b|\bprueba gratis\b|\bkostenlos testen\b|\bessai gratuit\b|"
    r"\bteste gr[aá]tis\b|\b(?:first|primo|primer) (?:month|mese|mes) (?:free|gratis)\b|\bfree shipping\b|"
    r"\bspedizione gratuita\b", re.I)

AD_READ_RE = re.compile(
    "|".join([r"(?<!\w)" + p.replace("(?P<brand>", "(?:") for p in _SPONSOR_SRC] +
             [r"\bsponsor\w*", r"\bsponsorizza\w*", r"\bpatrocin\w*", r"\bgesponsert\b", r"\bsponsoris\w*",
              r"\bbrought to you\b", r"\buse (?:my )?code\b", r"\bcodice sconto\b", r"\bcon il codice\b"]),
    re.I)


# ---------------------------------------------------------------------------
# URLs and domains
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"'(){}\[\]|\\^`]+", re.I)
_TLDS = ("com|it|io|co|net|org|de|es|fr|eu|uk|app|shop|store|tv|gg|me|us|ca|au|nl|be|ch|at|pt|br|mx|ai|so|"
         "xyz|ly|to|link|pro|fit|health|club|online|site|tech|dev|info|biz|ie|se|dk|no|fi|pl|cz")
_BARE_RE = re.compile(
    r"(?<![@\w./:-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:" + _TLDS + r"))\b(/[^\s<>\"'(){}\[\]]*)?",
    re.I)
_TRAIL = ".,;:!?)]}>…»\"'"


def extract_urls(line: str) -> list[str]:
    urls = [m.group(0).rstrip(_TRAIL) for m in _URL_RE.finditer(line)]
    rest = _URL_RE.sub(" ", line)
    for m in _BARE_RE.finditer(rest):
        urls.append(("https://" + m.group(1) + (m.group(2) or "")).rstrip(_TRAIL))
    return urls


def registrable(host: str) -> str:
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in lists()["multi_part_suffixes"]:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def brand_key(domain: str) -> str:
    return slug(registrable(domain).split(".")[0])


def _find_dest(parts, query: dict) -> str | None:
    for values in query.values():
        for v in values:
            v2 = urllib.parse.unquote(v)
            if v2.lower().startswith(("http://", "https://")):
                return v2
    path = urllib.parse.unquote(parts.path)
    i = path.lower().find("http")
    if i >= 0 and re.match(r"https?:/{1,2}", path[i:], re.I):
        return re.sub(r"^(https?:)/{1,2}", r"\1//", path[i:])
    return None


def classify_link(url: str) -> dict:
    L = lists()
    info = {"url": url, "host": "", "domain": "", "kind": "invalid", "network": None, "dest_info": None,
            "code": None, "utm": {}, "affiliate": False, "brand_hint": None}
    try:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return info
    if "." not in host:
        return info
    reg = registrable(host)
    label = reg.split(".")[0]
    query = {k.lower(): v for k, v in urllib.parse.parse_qs(parts.query, keep_blank_values=True).items()}
    info.update(host=host, domain=reg)

    if reg in L["social"]:
        kind = "social"
    elif reg in L["creator_platforms"]:
        kind = "self"
    elif reg in L["ignore"]:
        kind = "ignore"
    elif label in L["marketplaces"] or reg in L["marketplaces"]:
        kind = "marketplace"
    elif reg in L["gear"]:
        kind = "gear"
    elif reg in L["shorteners"]:
        kind = "shortener"
    elif reg in L["affiliate_networks"]:
        kind = "network"
        info["network"] = L["affiliate_networks"][reg]
        info["affiliate"] = True
        dest = _find_dest(parts, query)
        if dest:
            d = classify_link(dest)
            if d["kind"] == "brand":
                info["dest_info"] = d
        sub = host[: -len(reg)].strip(".").split(".") if host != reg else []
        for lab in sub:
            if lab and lab not in L["generic_subdomains"] and len(lab) >= 3:
                info["brand_hint"] = slug(lab)
                break
    else:
        kind = "brand"
    info["kind"] = kind

    info["utm"] = {k[4:]: (v[0] if v else "") for k, v in query.items() if k.startswith("utm_")}
    for p in L["coupon_params"]:
        if query.get(p) and query[p][0].strip():
            info["code"] = query[p][0].strip()[:20]
            break
    m = re.search(r"/discount/([^/?#]+)", parts.path, re.I)
    if m and not info["code"]:
        info["code"] = urllib.parse.unquote(m.group(1))[:20]
    if any(p in query for p in L["affiliate_params"]):
        info["affiliate"] = True
    segs = [s.lower() for s in parts.path.split("/") if s]
    if any(s in L["affiliate_path_tokens"] for s in segs[:-1] or segs[:1]):
        info["affiliate"] = True
    return info


def effective_brand(link: dict, resolver=None):
    """(domain, brand_key, how) for a link, or None if it isn't a brand link."""
    kind = link["kind"]
    if kind == "brand":
        return link["domain"], brand_key(link["domain"]), "direct"
    if kind == "network" and link.get("dest_info"):
        d = link["dest_info"]
        return d["domain"], brand_key(d["domain"]), "decoded"
    if kind in ("network", "shortener") and resolver:
        final = resolver(link["url"])
        if final and final.rstrip("/") != link["url"].rstrip("/"):
            link["resolved"] = final
            f = classify_link(final)
            if f["kind"] == "network" and f.get("dest_info"):
                f = f["dest_info"]
            if f["kind"] == "brand":
                link["code"] = link.get("code") or f.get("code")
                link["utm"] = link.get("utm") or f.get("utm") or {}
                link["affiliate"] = link.get("affiliate") or f.get("affiliate") or kind == "network"
                return f["domain"], brand_key(f["domain"]), "resolved"
            return None
    if kind == "network" and link.get("brand_hint"):
        return None, link["brand_hint"], "hint"
    return None


# ---------------------------------------------------------------------------
# Description analysis
# ---------------------------------------------------------------------------

def _brand_hint(line: str, m: re.Match) -> str:
    if "brand" in (m.groupdict() or {}) and m.group("brand"):
        return m.group("brand").strip(" :-–—\"'")
    tail = line[m.end():]
    tail = re.split(r"[.!?|(\n]|https?://| - | – | — ", tail.lstrip(" :-–—\"'"), maxsplit=1)[0]
    return " ".join(tail.split()[:5]).strip(" ,;:\"'")


def find_codes(line: str) -> list[str]:
    out = []
    for rx in CODE_RE:
        for m in rx.finditer(line):
            out.append(m.group(1))
    for m in CODE_UPPER_RE.finditer(line):
        out.append(m.group(1))
    good = []
    for c in out:
        c = c.strip("-_")
        if len(c) < 3 or c.lower() in CODE_STOPWORDS or not re.search(r"[A-Za-z]", c):
            continue
        if c not in good:
            good.append(c)
    return good


def analyze_description(desc: str) -> dict:
    lines = (desc or "").splitlines()
    out = {"phrases": [], "codes": [], "offers": [], "links": [], "hashtag_ad": False, "ordinal": {}}
    nonempty = 0
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        nonempty += 1
        out["ordinal"][i] = nonempty
        top = nonempty <= 3
        for rx in SPONSOR_RE:
            m = rx.search(line)
            if m:
                out["phrases"].append({"line": i, "text": m.group(0), "hint": _brand_hint(line, m), "top": top})
                break
        else:
            m = LINE_START_RE.search(line)
            if m:
                out["phrases"].append({"line": i, "text": m.group(0).strip("*| "), "hint": "", "top": top})
        if HASHTAG_RE.search(line):
            out["hashtag_ad"] = True
        for code in find_codes(line):
            out["codes"].append({"line": i, "code": code, "top": top})
        if OFFER_RE.search(line):
            out["offers"].append({"line": i, "top": top})
        for url in extract_urls(line):
            info = classify_link(url)
            info.update(line=i, top=top, text=line[:240])
            out["links"].append(info)
    return out


def creator_tokens(creator: dict) -> set[str]:
    toks = set()
    for v in (creator.get("title"), creator.get("handle"), creator.get("custom_url")):
        s = slug(v or "")
        if len(s) >= 4:
            toks.add(s)
    return toks


def is_self(key: str, tokens: set[str]) -> bool:
    """True when a link's brand key looks like the creator's own name (own site, own shop)."""
    if not key or len(key) < 4:
        return False
    for t in tokens:
        if key == t:
            return True
        if len(key) >= 5 and key in t and len(key) >= len(t) * 0.5:   # "marcofit" in "marcofitness"
            return True
        if len(t) >= 6 and t in key:                                  # "marcofit" in "marcofitshop"
            return True
    return False


def _influencer_utm(link: dict, tokens: set[str]) -> bool:
    utm = link.get("utm") or {}
    if (utm.get("medium") or "").lower().strip() in lists()["influencer_utm_mediums"]:
        return True
    src = (utm.get("source") or "").lower()
    camp = slug((utm.get("campaign") or "") + (utm.get("content") or "") + (utm.get("term") or ""))
    return "youtube" in src and any(len(t) >= 4 and t in camp for t in tokens)


def _hint_matches(hint: str, key: str) -> bool:
    h = slug(hint)
    if not h or not key or len(key) < 3:
        return False
    return key in h or (len(h) >= 4 and h in key)


STRENGTH = {"sponsored": 3, "code": 2, "affiliate": 1}


def video_candidates(video: dict, analysis: dict, creator: dict, resolver=None):
    """Turn one video's signals into confident sightings plus, if needed, an ambiguity note.

    Returns (sightings, needs). `needs` is None or a dict that tells the scanner to try
    the transcript and/or hand the case to Claude.
    """
    flagged = bool(video.get("paid_flag"))
    disclosed = flagged or analysis["hashtag_ad"]
    tokens = creator_tokens(creator)
    ordn = analysis["ordinal"]

    def dist(a: int, b: int) -> int:
        return abs(ordn.get(a, 10_000) - ordn.get(b, -10_000))

    links = []
    hint_only = []
    for L in analysis["links"]:
        b = effective_brand(L, resolver)
        if not b:
            continue
        domain, key, how = b
        if not key or is_self(key, tokens):
            continue
        if how == "hint":
            hint_only.append((L, key))
            continue
        links.append((L, domain, key, how))

    top_keys = {k for (L, d, k, h) in links if L["top"]}
    found: dict[str, dict] = {}
    for L, domain, key, how in links:
        i = L["line"]
        phrase = next((p for p in analysis["phrases"]
                       if dist(p["line"], i) <= 2 or _hint_matches(p["hint"], key)), None)
        near_code = next((c for c in analysis["codes"] if dist(c["line"], i) <= 1), None)
        near_offer = any(dist(o["line"], i) <= 1 for o in analysis["offers"])
        signals = []
        if phrase:
            typ = "sponsored"
            signals.append("phrase:" + phrase["text"].lower())
        elif flagged and L["top"] and len(top_keys) == 1:
            typ = "sponsored"
            signals.append("paid_flag_top_link")
        elif L.get("code") or near_code:
            typ = "code"
            signals.append("code")
        elif _influencer_utm(L, tokens):
            typ = "code"
            signals.append("influencer_utm")
        elif L.get("affiliate") or L["kind"] == "network":
            typ = "affiliate"
            signals.append("affiliate_link")
        else:
            continue
        if flagged:
            signals.append("paid_flag")
        if analysis["hashtag_ad"]:
            signals.append("hashtag_ad")
        if L["top"]:
            signals.append("top_of_description")
        if near_offer:
            signals.append("offer")
        if L.get("network"):
            signals.append("network:" + L["network"])
        code = L.get("code") or (near_code["code"] if near_code else None)
        cand = {"brand_key": key, "domain": domain, "type": typ, "signals": signals, "code": code,
                "link": L.get("resolved") or L["url"], "evidence": L["text"], "how": how,
                "network": L.get("network")}
        prev = found.get(key)
        if not prev or STRENGTH[typ] > STRENGTH[prev["type"]]:
            if prev:
                cand["signals"] = list(dict.fromkeys(cand["signals"] + prev["signals"]))
                cand["code"] = cand["code"] or prev["code"]
            found[key] = cand
        else:
            prev["signals"] = list(dict.fromkeys(prev["signals"] + signals))
            prev["code"] = prev["code"] or code

    # Was every disclosure attached to a brand?
    reasons, hints = [], []
    sponsored_lines = [L["line"] for L, d, k, h in links if found.get(k, {}).get("type") == "sponsored"]
    for p in analysis["phrases"]:
        attached = any(dist(p["line"], j) <= 2 for j in sponsored_lines) or \
            any(_hint_matches(p["hint"], k) for k, c in found.items() if c["type"] == "sponsored")
        if attached:
            continue
        if p["hint"].startswith("@"):
            continue  # collab with another creator, not a brand
        reasons.append("phrase_without_brand_link")
        if p["hint"]:
            hints.append(p["hint"])
    has_sponsored = any(c["type"] == "sponsored" for c in found.values())
    if disclosed and not has_sponsored:
        reasons.append("paid_flag_no_brand" if flagged else "hashtag_ad_no_brand")
    for L, key in hint_only:
        if key not in found:
            reasons.append("affiliate_network_unresolved")
            hints.append(key)

    needs = None
    if reasons:
        needs = {
            "reasons": list(dict.fromkeys(reasons)),
            "hints": list(dict.fromkeys(hints)),
            "candidate_keys": list(dict.fromkeys([k for _, _, k, _ in links] + [k for _, k in hint_only])),
            "snippet": description_excerpt(video.get("description", ""), analysis),
        }
    return list(found.values()), needs


def description_excerpt(desc: str, analysis: dict, limit: int = 700) -> str:
    lines = (desc or "").splitlines()
    keep = set()
    for p in analysis["phrases"]:
        keep.update(range(p["line"] - 1, p["line"] + 3))
    if not keep:
        keep = {i for i, n in analysis["ordinal"].items() if n <= 8}
    text = "\n".join(lines[i].strip() for i in sorted(keep) if 0 <= i < len(lines) and lines[i].strip())
    return text[:limit]


def analyze_transcript(text: str, candidate_keys) -> dict | None:
    """Look for an ad read in the first minutes of a transcript."""
    if not text:
        return None
    m = AD_READ_RE.search(text)
    if not m:
        return None
    compact = slug(text)
    matched = [k for k in candidate_keys if k and len(k) >= 4 and k in compact]
    start = max(0, m.start() - 160)
    return {"phrase": m.group(0), "matched_keys": matched, "snippet": text[start:m.end() + 280].strip()}
