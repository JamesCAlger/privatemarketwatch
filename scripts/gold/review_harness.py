"""Gold-set review harness (local web app).

Force-multiplier for solo labeling: per sampled unit it locates the CACHED SOURCE
filing, pulls the matching schedule-of-investments row(s), and shows them next to
the pipeline value with the candidate pre-filled. The human confirms / corrects /
marks-ambiguous in one keystroke. Labels are SOURCE-adjudicated; the pipeline value
is shown only so the human can see whether it matches source.

READ-ONLY on data/output and frontend. Writes ONLY to data/gold/labels/.

Run:
    python scripts/gold/review_harness.py            # serves http://127.0.0.1:5057
    python scripts/gold/review_harness.py --port 5099 --draw batch1

Independence note: this harness shows the raw filing. A separate labeler agent (see
data/gold/labeler_protocol.md) may pre-fill candidates blind to the pipeline; if
data/gold/candidates/candidates_<draw>.jsonl exists, its values prefill instead of
the pipeline values. The human is always the final adjudicator.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
from collections import defaultdict
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path

from bs4 import BeautifulSoup
from lxml import etree
from flask import Flask, redirect, request, url_for

ROOT = Path(__file__).resolve().parents[2]
BDC_HTML = ROOT / "data" / "raw" / "filings" / "bdc_html"
HOLDINGS_CSV = ROOT / "data" / "output" / "private_markets_holdings.csv"
SAMPLES = ROOT / "data" / "gold" / "samples"
CANDIDATES = ROOT / "data" / "gold" / "candidates"
LABELS = ROOT / "data" / "gold" / "labels"
LABELS.mkdir(parents=True, exist_ok=True)

POSITION_FIELDS = ["fair_value", "cost", "classification", "lien"]  # batch-1 scope
PIPE_KEY = {"fair_value": "fair_value", "cost": "cost",
            "classification": "index_classification", "lien": "lien_position"}

app = Flask(__name__)
STATE: dict = {}


# --------------------------------------------------------------------------- io
def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       cwd=str(ROOT)).decode().strip()
    except Exception:
        return "unknown"


def load_frame(draw: str) -> list[dict]:
    path = SAMPLES / f"sample_frame_{draw}.jsonl"
    units = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    for i, u in enumerate(units):
        u["_idx"] = i
        u["_key"] = unit_key(u)
    return units


def unit_key(u: dict) -> str:
    tag = u.get("source_identifier") or (u.get("flag") or {}).get("rule_name") or "-"
    return f"{u['unit_type']}|{u['cik']}|{u.get('report_date')}|{tag}"


def load_candidates(draw: str) -> dict:
    path = CANDIDATES / f"candidates_{draw}.jsonl"
    if not path.exists():
        return {}
    out = {}
    for ln in path.read_text().splitlines():
        if ln.strip():
            r = json.loads(ln)
            out[r.get("_key") or unit_key(r)] = r
    return out


def labeled_keys() -> set[str]:
    keys = set()
    for fn in ("position_labels.jsonl", "cik_quarter_labels.jsonl", "flag_labels.jsonl"):
        p = LABELS / fn
        if p.exists():
            for ln in p.read_text().splitlines():
                if ln.strip():
                    r = json.loads(ln)
                    keys.add(r.get("_key", ""))
    return keys


def append_label(filename: str, record: dict) -> None:
    with (LABELS / filename).open("a", encoding="ascii") as fh:
        fh.write(json.dumps(record, default=str) + "\n")


# ------------------------------------------------------------------- source doc
def doc_path(cik: str, accession: str | None) -> Path | None:
    if not accession:
        return None
    cikdir = str(int(cik))
    p = BDC_HTML / cikdir / (accession.replace("-", "") + ".html")
    return p if p.exists() else None


def _rel_doc(cik: str, accession: str | None) -> str | None:
    dp = doc_path(cik, accession)
    return str(dp.relative_to(ROOT)) if dp else None


def list_cached(cik: str) -> list[str]:
    d = BDC_HTML / str(int(cik))
    if not d.exists():
        return []
    return sorted(f.name for f in d.glob("*.html"))


@lru_cache(maxsize=16)
def _soup(path_str: str) -> BeautifulSoup:
    txt = Path(path_str).read_text(encoding="utf-8", errors="ignore")
    return BeautifulSoup(txt, "html.parser")


def search_tokens(identifier: str) -> list[str]:
    core = identifier.split("|")[0]
    core = re.sub(r"\b(the|inc|llc|lp|ltd|corp|co|holdings|company)\b\.?", "", core, flags=re.I)
    core = re.sub(r"[^a-z0-9 ]", " ", core.lower())
    words = [w for w in core.split() if len(w) > 2]
    toks = []
    if words:
        toks.append(" ".join(words[:3]))   # first 3 significant words
        toks.append(words[0])              # primary token
    return list(dict.fromkeys(t for t in toks if t))


def extract_rows(cik: str, accession: str | None, identifier: str) -> dict:
    p = doc_path(cik, accession)
    if p is None:
        return {"ok": False, "msg": "cached source doc not found",
                "alts": list_cached(cik), "rows": []}
    soup = _soup(str(p))
    toks = search_tokens(identifier)
    all_rows = []
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [re.sub(r"\s+", " ", c) for c in cells if c.strip()]
        if cells:
            all_rows.append((cells, " ".join(cells).lower()))
    # Prefer the MOST SPECIFIC token (3-word) over the broad single word; only
    # fall back to a broader token when the specific one finds nothing.
    rows, used = [], None
    for tok in toks:
        m = [c for c, j in all_rows if tok in j]
        if m:
            rows, used = m[:15], tok
            break
    return {"ok": True, "rows": rows, "tokens": used,
            "doc": str(p.relative_to(ROOT)), "nrows": len(rows)}


def extract_total_fv(cik: str, accession: str | None) -> dict:
    """For cik_quarter units: surface candidate 'total investments at fair value'
    rows from the financial statements so the human can confirm the independent
    anchor against source."""
    p = doc_path(cik, accession)
    if p is None:
        return {"ok": False, "rows": [], "alts": list_cached(cik)}
    soup = _soup(str(p))
    rows = []
    for tr in soup.find_all("tr"):
        txt = tr.get_text(" ", strip=True).lower()
        if "total investment" in txt or "total investments at fair value" in txt:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            cells = [re.sub(r"\s+", " ", c) for c in cells if c.strip()]
            if cells:
                rows.append(cells)
        if len(rows) >= 10:
            break
    return {"ok": True, "rows": rows, "doc": str(p.relative_to(ROOT))}


# ----------------------------------------------------------- contextRef anchor
def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) and "}" in tag else (tag or "")


@lru_cache(maxsize=8)
def _tree(path_str: str):
    return etree.parse(path_str)


def _row_cells(tr) -> list[str]:
    cells = []
    for c in tr.iter():
        if _local(c.tag) in ("td", "th"):
            txt = re.sub(r"\s+", " ", " ".join(c.itertext())).strip()
            cells.append(txt)
    return cells


def _grid(tr) -> list[str]:
    """Colspan-aware cell list over DIRECT children, so a header row and a data
    row align at the same grid index (the SEC schedules use colspan + spacer
    cells heavily)."""
    out = []
    for c in tr:
        if _local(c.tag) not in ("td", "th"):
            continue
        txt = re.sub(r"\s+", " ", " ".join(c.itertext())).strip()
        span = c.get("colspan") or "1"
        span = int(span) if span.isdigit() else 1
        out.append(txt)
        out.extend([""] * (span - 1))
    return out


def _resolve(text: str, scale) -> float | None:
    try:
        return float(re.sub(r"[^0-9.\-]", "", text)) * (10 ** int(scale or 0))
    except (ValueError, TypeError):
        return None


def _scale_word(scale) -> str:
    s = str(scale) if scale not in (None, "") else "0"
    return {"0": "dollars", "3": "thousands", "6": "millions", "9": "billions"}.get(
        s, f"x10^{s}")


_HEADER_KW = ["portfolio company", "industry", "investment", "investment type",
              "coupon", "interest rate", "reference rate", "spread", "maturity",
              "principal", "par amount", "par value", "amortized cost", "cost",
              "fair value", "% of net", "percentage of net", "shares",
              "acquisition", "footnote", "type of investment"]


def _is_header(cells: list[str]) -> bool:
    blob = " ".join(cells).lower()
    return sum(1 for k in _HEADER_KW if k in blob) >= 2


def extract_anchored(cik: str, accession: str | None, context_id: str | None) -> dict | None:
    """Show the ONE schedule-of-investments row for this exact position, located by
    the FV fact's contextRef (not a text guess), plus that table's header row."""
    p = doc_path(cik, accession)
    if p is None or not context_id:
        return None
    try:
        root = _tree(str(p)).getroot()
    except Exception:
        return None
    target = None
    for el in root.iter():
        if (_local(el.tag) == "nonFraction" and el.get("contextRef") == context_id
                and (el.get("name") or "").rsplit(":", 1)[-1] == "InvestmentOwnedAtFairValue"):
            target = el
            break
    if target is None:
        return None
    tr = next((a for a in target.iterancestors() if _local(a.tag) == "tr"), None)
    if tr is None:
        return None
    all_tr = [e for e in root.iter() if _local(e.tag) == "tr"]
    try:
        idx = all_tr.index(tr)
    except ValueError:
        return None
    header = None
    for j in range(idx - 1, max(-1, idx - 80), -1):
        c = _grid(all_tr[j])
        if _is_header(c):
            header = c
            break
    # cost fact in the same row (same position context preferred)
    cost_text = cost_scale = pct_text = None
    for el in tr.iter():
        if _local(el.tag) != "nonFraction":
            continue
        nm = el.get("name") or ""
        if nm.rsplit(":", 1)[-1] == "InvestmentOwnedAtCost":
            cost_text = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()
            cost_scale = el.get("scale")
        elif "PercentOfNetAssets" in nm:
            pct_text = re.sub(r"\s+", " ", " ".join(el.itertext())).strip()
    # nearest preceding row that carries the issuer name (continuation rows blank it)
    name_row = None
    for j in range(idx, max(-1, idx - 6), -1):
        g = _grid(all_tr[j])
        if g and re.search(r"[A-Za-z]{3}", g[0]):
            name_row = g[0].strip()
            break
    # nearest preceding instrument/lien SECTION header (where flattened filers like
    # Blackstone encode the instrument type, since the identifier strips it)
    section = None
    for j in range(idx - 1, max(-1, idx - 150), -1):
        g = _grid(all_tr[j])
        ne = [c for c in g if c.strip()]
        if len(ne) == 1 and not re.search(r"[$%]|\d{3,}", ne[0]) and _SECTION_KW.search(ne[0]):
            section = re.sub(r"\s*\(continued\)\s*", "", ne[0], flags=re.I).strip()
            break
    fact_text = re.sub(r"\s+", " ", " ".join(target.itertext())).strip()
    return {"header": header, "row": _grid(tr), "name_row": name_row, "section": section,
            "fact_text": fact_text, "scale": target.get("scale"),
            "cost_text": cost_text, "cost_scale": cost_scale, "pct_text": pct_text,
            "context_id": context_id, "doc": str(p.relative_to(ROOT))}


_SECTION_KW = re.compile(
    r"(first lien|second lien|1st lien|2nd lien|senior secured|senior debt|subordinated|"
    r"unsecured|mezzanine|unitranche|term loan|revolv|delayed draw|equity|preferred|"
    r"common stock|warrant|membership|partnership interest|debt investment|bonds?|"
    r"\bnotes?\b|structured|joint venture)", re.I)


def value_anchor(cik: str, accession: str | None, report_date: str,
                 pipe_fv: float) -> dict | None:
    """When the name-anchor fails (flattened identifier), find the CURRENT-PERIOD
    InvestmentOwnedAtFairValue fact whose resolved value == the pipeline FV. A unique
    match proves the pipeline's value is a real tagged fact for this period (rules
    out scale errors and comparative-period contamination); the fact's own member is
    read back so the human can confirm the issuer."""
    p = doc_path(cik, accession)
    if p is None or pipe_fv is None:
        return None
    try:
        root = _tree(str(p)).getroot()
    except Exception:
        return None
    rd = re.sub(r"\s+", " ", str(report_date)).strip()
    ctx = {}
    for c in root.iter():
        if _local(c.tag) != "context":
            continue
        ident = inst = ""
        for sub in c.iter():
            st = _local(sub.tag)
            if st in ("typedMember", "explicitMember") and "Investment" in (sub.get("dimension") or ""):
                kids = list(sub)
                ident = re.sub(r"\s+", " ", ((kids[0].text if kids else sub.text) or "")).strip()
            elif st == "instant":
                inst = re.sub(r"\s+", " ", (sub.text or "")).strip()
        if c.get("id"):
            ctx[c.get("id")] = (ident, inst)
    tol = max(1.0, 0.0001 * abs(pipe_fv))
    matches = []
    for el in root.iter():
        if _local(el.tag) != "nonFraction":
            continue
        if (el.get("name") or "").rsplit(":", 1)[-1] != "InvestmentOwnedAtFairValue":
            continue
        ident, inst = ctx.get(el.get("contextRef"), ("", ""))
        if inst != rd or not ident:
            continue
        val = _resolve(" ".join(el.itertext()), el.get("scale"))
        if val is not None and abs(val - pipe_fv) <= tol:
            matches.append({"context_id": el.get("contextRef"), "member": ident})
    if len(matches) == 1:
        return {"n": 1, **matches[0]}
    return {"n": len(matches), "candidates": matches[:6]} if matches else None


# ---------------------------------------------------- issuer narrative (prose)
@lru_cache(maxsize=8)
def _doc_text(path_str: str) -> str:
    raw = Path(path_str).read_text(encoding="utf-8", errors="replace")
    return re.sub(r"\s+", " ", BeautifulSoup(raw, "html.parser").get_text(" ", strip=True))


_NARR_KW = re.compile(
    r"(advise?r|asset manager|asset management|wholly[ -]?owned|portfolio company|"
    r"deemed to control|control investment|registered investment|manages|managed \d+|"
    r"collateralized loan|joint venture|formed|organized|incorporated|subsidiary|"
    r"assets under management|provides|operates|holding company)", re.I)
# the inline-XBRL context dump is dense with ISO dates / axis= / Member tags;
# prose uses 'December 31, 2025', so exclude windows carrying those markers.
_NARR_NOISE = re.compile(r"\d{4}-\d{2}-\d{2}|axis=|contextRef|[A-Za-z]+Member\b")


def _ascii(s: str) -> str:
    return (s.replace("’", "'").replace("‘", "'").replace("“", '"')
             .replace("”", '"').replace("—", "--").replace("–", "-")
             .replace("�", '"').encode("ascii", "ignore").decode())


_PHRASE_STOP = {"interest", "loan", "loans", "note", "notes", "equity", "units", "unit",
                "member", "warrant", "warrants", "revolving", "revolver", "subordinated",
                "senior", "lien", "secured", "unsecured", "common", "preferred", "term",
                "delayed", "draw", "first", "second", "holdings", "holding", "the", "and"}


def _issuer_phrases(identifier: str) -> list[str]:
    """Candidate contiguous name phrases (most to least specific) for prose search.
    Strips instrument/tranche stopwords so e.g. 'BCRED Emerald JV LP - LP Interest'
    yields 'bcred emerald', not 'bcred emerald interest'."""
    core = identifier.split("|")[0]
    core = re.split(r",\s*(member interest|lp interest|subordinated|first lien|second lien|"
                    r"senior|common|preferred|warrant|revolv|term loan|delayed draw|note|"
                    r"equity|unsecured|llc interest|partnership interest)", core, flags=re.I)[0]
    core = re.sub(r"[^A-Za-z0-9 ]", " ", core)
    words = [w for w in core.split() if len(w) > 2 and w.lower() not in _PHRASE_STOP]
    # most-specific contiguous phrase first, then progressively shorter, down to the
    # single most significant token (so 'Pioneer LLC' falls back to 'Pioneer').
    cands = [" ".join(words[:n]) for n in (3, 2, 1) if len(words) >= n]
    return list(dict.fromkeys(c for c in cands if c))


def _issuer_phrase(identifier: str) -> str:
    ph = _issuer_phrases(identifier)
    return ph[0] if ph else ""


def extract_issuer_narrative(cik: str, accession: str | None, identifier: str) -> list[str]:
    """Prose the filing writes ABOUT this issuer (control-investment notes, JV
    descriptions, adviser/asset-manager language) -- the basis for the equity-vs-
    credit / fund-vs-operating-company classification call. Filters out the
    inline-XBRL context dump."""
    p = doc_path(cik, accession)
    if p is None:
        return []
    phrases = [ph.lower() for ph in _issuer_phrases(identifier) if len(ph) >= 4]
    if not phrases:
        return []
    text = _doc_text(str(p))
    low = text.lower()
    for phrase in phrases:               # most specific first; fall back to shorter
        out, seen = [], set()
        for m in re.finditer(re.escape(phrase), low):
            s = max(0, m.start() - 90)
            e = min(len(text), m.start() + 430)
            win = text[s:e]
            if _NARR_KW.search(win) and not _NARR_NOISE.search(win):
                key = win[:50].lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(_ascii(win).strip())
                if len(out) >= 3:
                    break
        if out:
            return out
    return []


def _narr_block(u: dict) -> str:
    ident = u.get("source_identifier") or u.get("issuer_name") or ""
    snips = extract_issuer_narrative(u["cik"], u.get("accession"), ident)
    if not snips:
        return ("<p class='meta' style='margin-top:10px'>No issuer narrative found in "
                "this filing (search term: <code>" + _issuer_phrase(ident) + "</code>). "
                "Classify from the schedule row above.</p>")
    body = "".join(f"<p class='narr'>&hellip; {s} &hellip;</p>" for s in snips)
    return ("<h3 style='margin-top:12px'>What the filing says about this issuer</h3>"
            "<p class='meta'>For the credit-vs-equity / fund-vs-operating-company call. "
            "Verify it describes THIS issuer.</p>" + body)


# ----------------------------------------------------- full-filing token search
_SEARCH_STOP = _PHRASE_STOP | {
    "llc", "inc", "lp", "ltd", "corp", "co", "company", "plc", "sa", "nv", "bv",
}


def _query_tokens(query: str) -> list[str]:
    """Tokenize a free-text query into independent search terms. Unlike the old
    full-company-name match, ANY token can hit -- so 'Pioneer LLC' searches for
    'pioneer' (and 'llc' is dropped as noise)."""
    q = re.sub(r"[^a-z0-9 ]", " ", (query or "").lower())
    return list(dict.fromkeys(w for w in q.split() if len(w) >= 3 and w not in _SEARCH_STOP))


def _default_query(identifier: str) -> str:
    """Default search box text from the position identifier (significant words)."""
    core = identifier.split("|")[0].split(",")[0]
    return " ".join(_query_tokens(core)[:4])


_UNFUNDED_RE = re.compile(r"\s*(revolver|revolving loan|delayed draw term loan|delayed draw)\s*",
                          re.I)


def _section_of_cells(cells: list[str]) -> str | None:
    """If a row is a single-cell schedule grouping header (lien / instrument /
    affiliation section), return its text -- else None. Mirrors the anchored-view
    section heuristic so search hits can show the grouping they fall under."""
    ne = [c for c in cells if c.strip()]
    if len(ne) == 1 and not re.search(r"[$%]|\d{3,}", ne[0]) and _SECTION_KW.search(ne[0]):
        return re.sub(r"\s*\(continued\)\s*", "", ne[0], flags=re.I).strip()
    return None


def search_filing(cik: str, accession: str | None, query: str,
                  max_rows: int = 30, match_all: bool = False) -> dict:
    """Search the FULL cached filing for the query tokens.

    Each hit carries the nearest preceding schedule grouping header (lien /
    instrument / affiliation section), since lien rank lives in a section header,
    not on the row. Ranking down-weights generic tokens via inverse document
    frequency (so a rare token like 'armstrong' outranks a ubiquitous one like
    'bidco'). With match_all, only rows containing EVERY token are returned."""
    p = doc_path(cik, accession)
    if p is None:
        return {"ok": False, "rows": [], "terms": [], "alts": list_cached(cik)}
    toks = _query_tokens(query)
    if not toks:
        return {"ok": True, "rows": [], "terms": [], "doc": str(p.relative_to(ROOT)),
                "nrows": 0, "match_all": match_all}
    soup = _soup(str(p))
    section = ""
    cands: list[tuple[str, list[str], set]] = []
    df: dict[str, int] = defaultdict(int)
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c.strip()]
        if not cells:
            continue
        sec = _section_of_cells(cells)
        if sec is not None:
            section = sec
            continue
        blob = " ".join(cells).lower()
        hits = {t for t in toks if t in blob}
        if not hits:
            continue
        for t in hits:                       # df over all hit rows -> idf weight
            df[t] += 1
        if match_all and len(hits) < len(toks):
            continue
        # Unfunded-commitment rows spell out the instrument per-row (a bare
        # "Revolver" / "Delayed Draw Term Loan" cell) and live in a separate table
        # that often falls AFTER the JV section with no header of its own -- so they
        # inherit a stale "Investments in Joint Ventures" tag. Relabel them directly.
        row_sec = "Unfunded Commitment" if any(_UNFUNDED_RE.fullmatch(c) for c in cells) else section
        cands.append((row_sec, cells, hits))

    def _score(item: tuple[str, list[str], set]) -> tuple:
        sec, cells, hits = item
        idf = sum(1.0 / df[t] for t in hits)   # rarer tokens dominate
        return (len(hits), idf, -len(" ".join(cells)))

    cands.sort(key=_score, reverse=True)
    rows = [(sec, cells) for sec, cells, _ in cands[:max_rows]]
    return {"ok": True, "rows": rows, "terms": toks, "doc": str(p.relative_to(ROOT)),
            "nrows": len(cands), "match_all": match_all}


def _search_results_table(rows: list) -> str:
    html = ("<table><tr class='hdr'><th>section grouping (lien / instrument)</th>"
            "<th>matched schedule row &rarr;</th></tr>")
    for sec, cells in rows:
        sec_disp = escape("[" + sec + "]") if sec else "&mdash;"
        sec_td = f"<td style='color:#ffd479;white-space:normal'>{sec_disp}</td>"
        tds = "".join(f"<td>{escape(c)}</td>" for c in cells)
        html += f"<tr class='hit'>{sec_td}{tds}</tr>"
    return html + "</table>"


def _search_block(u: dict, q: str, match_all: bool = True) -> str:
    ident = u.get("source_identifier") or u.get("issuer_name") or ""
    effective = q.strip() or _default_query(ident)
    checked = "checked" if match_all else ""
    box = (
        "<form method='get' style='margin:8px 0'>"
        f"<input type='text' name='q' value='{escape(effective)}' "
        "placeholder='search filing (e.g. Pioneer)' "
        "style='width:62%;background:#0d1017;color:#dfe3ea;border:1px solid #333a47;border-radius:5px;padding:5px 7px'>"
        f" <label style='margin:0 8px;color:#9aa3b2'><input type='checkbox' name='all' value='1' {checked}> all terms</label>"
        " <button class='sec' type='submit'>search</button></form>"
    )
    if not effective:
        return "<h3 style='margin-top:12px'>Search filing</h3>" + box
    res = search_filing(u["cik"], u.get("accession"), effective, match_all=match_all)
    if not res.get("ok"):
        alts = "<br>".join(escape(a) for a in res.get("alts", [])[:20]) or "(none cached)"
        return ("<h3 style='margin-top:12px'>Search filing</h3>" + box +
                f"<p class='meta'>doc not cached. cached docs:<br>{alts}</p>")
    terms = ", ".join(escape(t) for t in res.get("terms", []))
    mode = "all terms" if res.get("match_all") else "any term (rare terms ranked first)"
    head = (f"<h3 style='margin-top:12px'>Search filing &mdash; terms: <code>{terms}</code> "
            f"<span class='meta'>(mode: {mode}; {res['nrows']} matching rows; "
            f"top {min(res['nrows'], 30)})</span></h3>" + box)
    if not res["rows"]:
        hint = ("uncheck 'all terms' to broaden" if match_all else "try a different term")
        return head + f"<p class='meta'>no rows match &mdash; {hint}.</p>"
    return head + _search_results_table(res["rows"])


# ------------------------------------------------- raw pipeline source row lookup
@lru_cache(maxsize=1)
def _holdings_index() -> dict:
    """Index private_markets_holdings.csv by (cik, report_date) -> raw rows, so the
    review page can surface what the PIPELINE extracted (issuer_name,
    instrument_description, bdc_investment_identifier, fair_value, cost) next to the
    source. Built once per process (~one stream of the holdings CSV)."""
    idx: dict = defaultdict(list)
    if not HOLDINGS_CSV.exists():
        return idx
    cols = ("issuer_name", "instrument_description", "bdc_investment_identifier",
            "fair_value", "cost", "lien_position", "index_classification", "accession_number")
    with HOLDINGS_CSV.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            raw_cik = (r.get("cik") or "").strip()
            key_cik = str(int(raw_cik)) if raw_cik.isdigit() else raw_cik
            key = (key_cik, (r.get("report_date") or "").strip())
            if len(idx[key]) < 6000:
                idx[key].append({c: r.get(c, "") for c in cols})
    return idx


def pipeline_source_rows(u: dict) -> list[dict]:
    """The pipeline's own extracted row(s) for this position -- matched within the
    (cik, report_date) group by identifier-token overlap and/or FV proximity."""
    try:
        key_cik = str(int(str(u["cik"]).strip()))
    except (ValueError, KeyError):
        key_cik = str(u.get("cik", ""))
    group = _holdings_index().get((key_cik, (u.get("report_date") or "").strip()), [])
    if not group:
        return []
    toks = _query_tokens(u.get("source_identifier") or u.get("issuer_name") or "")
    fv = (u.get("pipeline") or {}).get("fair_value")
    scored = []
    for r in group:
        blob = " ".join((r.get("issuer_name", ""), r.get("instrument_description", ""),
                         r.get("bdc_investment_identifier", ""))).lower()
        hits = sum(1 for t in toks if t in blob)
        fv_match = 0
        try:
            if fv and r.get("fair_value") and abs(float(r["fair_value"]) - float(fv)) <= max(1.0, abs(float(fv)) * 0.01):
                fv_match = 1
        except (ValueError, TypeError):
            pass
        if hits or fv_match:
            scored.append((fv_match * 100 + hits, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:8]]


def _pipeline_rows_block(u: dict) -> str:
    if u.get("unit_type") not in ("position", "pps_body", "tail_census", "silent_bulk", None):
        # still useful for any per-position unit; skip purely fund-level units below
        pass
    rows = pipeline_source_rows(u)
    if not rows:
        if not HOLDINGS_CSV.exists():
            return ""
        return ("<h3 style='margin-top:12px'>Raw pipeline source row(s)</h3>"
                "<p class='meta'>No matching unified-holdings row found for this "
                "(CIK, quarter) by identifier or fair value.</p>")
    flds = [("issuer_name", "issuer_name"), ("instrument_description", "instrument_description"),
            ("bdc_investment_identifier", "bdc_investment_identifier"),
            ("fair_value", "fair_value"), ("cost", "cost"),
            ("lien_position", "lien_position"), ("index_classification", "index_classification")]
    table = "<table><tr class='hdr'><th>field</th>" + "".join(
        f"<th>row {i+1}</th>" for i in range(len(rows))) + "</tr>"
    for label, col in flds:
        tds = "".join(f"<td>{escape(str(r.get(col, '') or ''))}</td>" for r in rows)
        table += f"<tr class='kv'><td>{label}</td>{tds}</tr>"
    table += "</table>"
    return ("<h3 style='margin-top:12px'>Raw pipeline source row(s)</h3>"
            "<p class='meta'>What the pipeline extracted for this position "
            "(verify the parsed text vs the source above).</p>" + table)


# ------------------------------------------------------------------------ views
PAGE = """<!doctype html><html><head><meta charset="ascii"><title>gold review</title>
<style>
 body{{font:13px/1.45 ui-monospace,Consolas,monospace;margin:0;background:#0f1115;color:#dfe3ea}}
 header{{position:sticky;top:0;background:#171a21;border-bottom:1px solid #2a2f3a;padding:8px 14px}}
 .bar{{display:flex;gap:18px;align-items:center;flex-wrap:wrap}}
 .pill{{background:#222733;border:1px solid #333a47;border-radius:10px;padding:1px 8px}}
 .strat-tail_census{{color:#ffd479}}.strat-pps_body{{color:#7fd1ff}}.strat-silent_bulk{{color:#b08bff}}
 .strat-surfaced_flag{{color:#7fffa8}}.strat-suppressed_flag{{color:#ff9b9b}}
 main{{display:grid;grid-template-columns:1fr 1fr;gap:14px;padding:14px}}
 .panel{{background:#141821;border:1px solid #262c38;border-radius:8px;padding:12px;overflow:auto}}
 h3{{margin:0 0 8px;font-size:12px;color:#8b93a3;text-transform:uppercase;letter-spacing:.06em}}
 table{{border-collapse:collapse;width:100%;font-size:12px}}
 td,th{{border:1px solid #283040;padding:2px 6px;text-align:left;white-space:nowrap}}
 .hit td{{background:#2a3550;outline:1px solid #4a6cff}}
 .hdr th{{background:#20262f;color:#9aa3b2;font-weight:600}}
 .ctx td{{background:#161a22;color:#7a8290}}
 .kv td:first-child{{color:#9aa3b2;width:230px;white-space:normal}}
 .kv td:last-child{{white-space:normal}}
 .narr{{background:#101820;border-left:3px solid #2b6cff;padding:7px 10px;margin:6px 0;color:#cfe0ff;white-space:normal;font-style:italic}}
 .fld{{display:flex;gap:8px;align-items:center;margin:6px 0}}
 .fld label{{width:120px;color:#9aa3b2}} .fld input[type=text]{{flex:1;background:#0d1017;color:#dfe3ea;border:1px solid #333a47;border-radius:5px;padding:5px 7px}}
 .pipeval{{color:#ffd479}} .changed input{{border-color:#ff9b9b!important}}
 button{{background:#2b6cff;color:#fff;border:0;border-radius:6px;padding:8px 14px;font:inherit;cursor:pointer}}
 button.sec{{background:#39414f}} a{{color:#7fd1ff}}
 .note{{width:100%;background:#0d1017;color:#dfe3ea;border:1px solid #333a47;border-radius:5px;padding:6px;min-height:42px}}
 .meta{{color:#8b93a3}} .big{{font-size:15px;color:#fff}}
</style></head><body>
<header><div class="bar">
 <span class="pill">{done}/{total} labeled</span>
 <span class="pill strat-{stratum}">{stratum}</span>
 <span class="pill">{unit_type}</span>
 <span class="pill">CIK {cik}{pub}</span>
 <span class="pill">{report_date}</span>
 <span class="big">{title}</span>
 <span style="margin-left:auto"><a href="{prev}">&larr; prev</a> &nbsp; <a href="{nxt}">skip &rarr;</a></span>
</div></header>
<main>
 <section class="panel"><h3>Source &mdash; cached filing {doc}</h3>{source}</section>
 <section class="panel"><h3>Adjudicate (read from source above)</h3>{form}</section>
</main>
<script>
 document.querySelectorAll('input[type=text]').forEach(function(i){{
   var o=i.defaultValue; i.addEventListener('input',function(){{i.parentNode.classList.toggle('changed',i.value!==o);}});}});
 document.addEventListener('keydown',function(e){{if(e.key==='Enter'&&!e.shiftKey){{var f=document.querySelector('form');if(f){{e.preventDefault();f.submit();}}}}}});
</script>
</body></html>"""


def _cells_table(rows: list[tuple[str, list[str]]]) -> str:
    html = "<table>"
    for cls, cells in rows:
        tag = "th" if cls == "hdr" else "td"
        tds = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
        html += f"<tr class='{cls}'>{tds}</tr>"
    return html + "</table>"


def render_source(u: dict, cand: dict | None = None, q: str = "", match_all: bool = True) -> str:
    """Core source view + the raw pipeline row(s) + the full-filing search panel."""
    return _source_core(u, cand) + _pipeline_rows_block(u) + _search_block(u, q, match_all)


def _source_core(u: dict, cand: dict | None = None) -> str:
    if u["unit_type"] in ("cik_quarter", "flag"):
        ex = extract_total_fv(u["cik"], u.get("accession"))
        if not ex.get("ok"):
            alts = "<br>".join(ex.get("alts", [])[:20]) or "(none cached)"
            return f"<p class='meta'>doc not found.</p><p class='meta'>cached docs:<br>{alts}</p>"
        if not ex["rows"]:
            return f"<p class='meta'>no 'total investments' row found. Open:<br><code>{ex['doc']}</code></p>"
        rows = [("hdr", ["(financial-statement 'total investments' rows)"])]
        rows += [("hit", c) for c in ex["rows"]]
        return _cells_table(rows)

    # ---- position: anchor on the FV fact's contextRef ----------------------
    ctx = (cand or {}).get("source_ref", {}).get("context_id")
    anc = extract_anchored(u["cik"], u.get("accession"), ctx)
    va_member = va_multi = None
    if anc is None:
        pipe_fv = (u.get("pipeline") or {}).get("fair_value")
        va = value_anchor(u["cik"], u.get("accession"), u.get("report_date"), pipe_fv)
        if va and va.get("n") == 1:
            anc = extract_anchored(u["cik"], u.get("accession"), va["context_id"])
            va_member = va.get("member")
        elif va and va.get("n", 0) > 1:
            va_multi = va["n"]
    if anc is not None:
        va_banner = ""
        if va_member is not None:
            va_banner = (f"<p class='meta' style='color:#ffd479'>Name-anchor failed "
                         f"(flattened identifier). Matched the pipeline's FV to the unique "
                         f"current-period FV fact &rarr; contextRef <code>{anc['context_id']}</code>, "
                         f"tagged member <b>{va_member}</b>. Confirm this is the right "
                         f"issuer/tranche.</p>")
        fv = _resolve(anc["fact_text"], anc.get("scale"))
        cost = _resolve(anc.get("cost_text") or "", anc.get("cost_scale"))
        sw = _scale_word(anc.get("scale"))
        scale_tag = f" <span class='meta'>[scale {anc.get('scale') or '0'} = {sw}]</span>"
        fv_s = (f"{anc['fact_text']}{scale_tag} &rarr; <b>${fv:,.0f}</b>"
                if fv is not None else anc["fact_text"])
        cost_s = (f"{anc['cost_text']} &rarr; <b>${cost:,.0f}</b>" if cost is not None
                  else (anc.get("cost_text") or "<i>not separately tagged</i>"))
        # filed % of net assets = independent magnitude cross-check
        pct = anc.get("pct_text")
        pct_row = ""
        if pct:
            try:
                implied = fv / (float(re.sub(r"[^0-9.\-]", "", pct)) / 100.0) if fv else None
                imp_s = f" &rarr; implies fund net assets ~ <b>${implied/1e9:,.1f}B</b>" if implied else ""
            except (ValueError, ZeroDivisionError):
                imp_s = ""
            pct_row = (f"<tr class='kv'><td>% of net assets (as filed)</td>"
                       f"<td>{pct}%{imp_s}</td></tr>")
        name = anc.get("name_row") or u.get("source_identifier") or ""
        sec = anc.get("section")
        sec_line = (f"Instrument / lien section (schedule grouping): <b>{sec}</b><br>"
                    if sec else "")
        head = (va_banner +
                f"<p class='meta'>Issuer: <b>{name}</b><br>"
                f"{sec_line}"
                f"Anchored to this exact position by FV fact "
                f"<code>contextRef={anc['context_id']}</code>. Scale comes from the XBRL "
                f"fact's <code>scale=</code> attribute (the filer's own declaration). As "
                f"reported in this filing's schedule of investments:</p>"
                f"<table><tr class='hdr'><th>field</th><th>value as shown -&gt; dollars</th></tr>"
                f"<tr class='hit'><td>Fair Value</td><td>{fv_s}</td></tr>"
                f"<tr class='hit'><td>Cost</td><td>{cost_s}</td></tr>"
                f"{pct_row}</table>")
        # full anchored row, vertically (column header -> cell value), no h-scroll
        hdr = anc.get("header") or []
        row = anc["row"]
        vrows = [("hdr", ["column", "value for this position"])]
        for i in range(max(len(hdr), len(row))):
            label = hdr[i] if i < len(hdr) and hdr[i] else f"col {i}"
            val = row[i] if i < len(row) else ""
            if not val and not (i < len(hdr) and hdr[i]):
                continue
            vrows.append(("kv", [label, val or "&mdash;"]))
        note = ("<p class='meta'>Confirm: is this the RIGHT position (issuer/tranche), at the "
                "right scale, and a real holding (not a 'Total/Subtotal' or prior-period row)? "
                "Use the row below for classification / lien / instrument type.</p>")
        return head + note + _cells_table(vrows) + _narr_block(u)

    # ---- fallback: not anchored (member-QName quirk / unmatched) ------------
    ex = extract_rows(u["cik"], u.get("accession"),
                      u.get("source_identifier") or u.get("issuer_name") or "")
    if not ex.get("ok"):
        alts = "<br>".join(ex.get("alts", [])[:20]) or "(none cached)"
        return f"<p class='meta'>doc not found.</p><p class='meta'>cached docs:<br>{alts}</p>"
    va_extra = (f" Value-anchor found {va_multi} current-period facts with this exact FV "
                f"(ambiguous -- cannot auto-pick)." if va_multi else
                " Value-anchor also failed (no current-period FV fact matches the pipeline value).")
    warn = ("<p class='meta'>NOT anchored to a single FV fact (this position has the "
            "member-QName / flattened-identifier quirk)." + va_extra +
            " Showing token matches across the filing &mdash; <b>verify which row is the "
            f"schedule line</b>. Doc: <code>{ex['doc']}</code></p>")
    if not ex["rows"]:
        return warn + "<p class='meta'>no token match either; open the doc and read manually.</p>" + _narr_block(u)
    return warn + _cells_table([("hit", c) for c in ex["rows"]]) + _narr_block(u)


def render_form(u: dict, cand: dict | None) -> str:
    if u["unit_type"] == "flag":
        fl = u["flag"]
        return f"""<form method="post" action="{url_for('save', idx=u['_idx'])}">
         <p class='meta'>engine <b>{fl['engine']}</b> / rule <b>{fl['rule_name']}</b>
            ({fl['tier']}, {fl['enforcement']})</p>
         <p>metric: <span class='pipeval'>{fl['metric']} {fl['metric_name']}</span><br>
            status: {fl['status']} &nbsp; confidence: <b>{fl['confidence']}</b> &nbsp;
            surface: {fl['surface']}</p>
         <p class='meta'>Read the source. Is the flagged condition a REAL defect at source?</p>
         <div class='fld'><label>verdict</label>
           <select name="verdict" class="note" style="min-height:auto">
             <option value="real_error">real_error (true defect)</option>
             <option value="false_alarm">false_alarm (pipeline/source is fine)</option>
             <option value="ambiguous">ambiguous (indeterminate from source)</option>
           </select></div>
         <textarea class="note" name="note" placeholder="citation / why (table, row, value)"></textarea>
         <p><button type="submit">Save &amp; next (Enter)</button></p>
        </form>"""
    # position / cik_quarter field form
    src = cand or {}
    fields = POSITION_FIELDS if u["unit_type"] == "position" else ["total_investments_fv", "position_count"]
    rows = ""
    for f in fields:
        if u["unit_type"] == "position":
            pipe = u["pipeline"].get(PIPE_KEY[f])
            prefill = src.get(f"true_{f}", pipe)
        else:
            pipe = (u["pipeline"].get("sum_fair_value") if f == "total_investments_fv"
                    else u["pipeline"].get("position_count"))
            if f == "total_investments_fv":
                # prefer the labeler's iXBRL no-dimension total (independent of the
                # position sum); fall back to the companyfacts candidate.
                prefill = src.get("true_total_investments_fv") or u.get("candidate_total_fv")
            else:
                prefill = pipe
        pipe_s = "" if pipe is None else pipe
        rows += f"""<div class='fld'><label>{f}</label>
          <input type="text" name="true_{f}" value="{'' if prefill is None else prefill}">
          <span class='pipeval' title='pipeline'>pipe: {pipe_s}</span>
          <label style='width:auto'><input type='checkbox' name='amb_{f}'> amb</label></div>"""
    disp = ("<div class='fld'><label>row disposition</label>"
            "<select name='disposition' class='note' style='min-height:auto'>"
            "<option value='valid'>valid position (a real holding)</option>"
            "<option value='aggregate_subtotal'>aggregate / subtotal -- EXCLUDE (sums other rows / category total)</option>"
            "<option value='look_through'>JV / co-investment look-through -- EXCLUDE (vehicle's underlying, double-counts the interest line)</option>"
            "<option value='comparative'>prior-period / comparative row -- EXCLUDE</option>"
            "<option value='non_position'>not a position / other -- EXCLUDE</option>"
            "</select></div>")
    return f"""<form method="post" action="{url_for('save', idx=u['_idx'])}">
      <p class='meta'>Pre-filled with {'agent candidate' if cand else 'pipeline value'}.
        Leave a field as-is to CONFIRM it matches source; edit it to CORRECT;
        check <b>amb</b> if source is indeterminate. Set <b>row disposition</b> to flag a
        row that should NOT be a constituent (aggregate / look-through / comparative).</p>
      {disp}
      {rows}
      <textarea class="note" name="note" placeholder="citation / note (table, row)"></textarea>
      <p><button type="submit">Save &amp; next (Enter)</button>
         <button class="sec" type="submit" name="ambiguous_all" value="1">Mark whole unit ambiguous</button></p>
    </form>"""


@app.route("/")
def home():
    done = labeled_keys()
    for u in STATE["frame"]:
        if u["_key"] not in done:
            return redirect(url_for("unit", idx=u["_idx"]))
    return redirect(url_for("unit", idx=0))


@app.route("/unit/<int:idx>")
def unit(idx: int):
    frame = STATE["frame"]
    idx = max(0, min(idx, len(frame) - 1))
    u = frame[idx]
    cand = STATE["candidates"].get(u["_key"])
    q = request.args.get("q", "")
    # default 'all terms' ON (issuer queries want precision). A GET form omits an
    # unchecked box, so use the presence of `q` as the "form submitted" signal --
    # only then honor the (possibly absent => unchecked) `all` param.
    submitted = "q" in request.args
    match_all = (request.args.get("all") == "1") if submitted else True
    title = u.get("source_identifier") or (u.get("flag") or {}).get("rule_name") or u["unit_type"]

    # The dynamic HTML (source/form/title) is spliced into PAGE via str.format, so any
    # literal { } in filing text would break formatting -- double them so format restores them.
    def _braces(s: str) -> str:
        return str(s).replace("{", "{{").replace("}", "}}")

    return PAGE.format(
        done=len(labeled_keys()), total=len(frame),
        stratum=u["stratum"], unit_type=u["unit_type"], cik=u["cik"],
        pub=" *pub" if u.get("in_published_cohort") else "",
        report_date=u.get("report_date", ""), title=_braces(title),
        prev=url_for("unit", idx=idx - 1), nxt=url_for("unit", idx=idx + 1),
        doc="", source=_braces(render_source(u, cand, q, match_all)), form=_braces(render_form(u, cand)))


@app.route("/save/<int:idx>", methods=["POST"])
def save(idx: int):
    frame = STATE["frame"]
    u = frame[idx]
    base = {
        "schema_version": "1.0", "_key": u["_key"], "record_type": u["unit_type"],
        "cik": u["cik"], "report_date": u.get("report_date"),
        "accession": u.get("accession"), "stratum": u["stratum"],
        "adjudicator": f"human:{STATE['who']}", "label_status": "human_confirmed",
        "pipeline_version": STATE["sha"], "labeled_date": date.today().isoformat(),
        "source_ref": {"doc": _rel_doc(u["cik"], u.get("accession")),
                       "context_id": None, "note": request.form.get("note", "")},
    }
    if u["unit_type"] == "flag":
        base["unit_type"] = "flag"
        base["flag"] = u["flag"]
        base["verdict"] = request.form.get("verdict", "ambiguous")
        append_label("flag_labels.jsonl", base)
    elif u["unit_type"] == "cik_quarter":
        amb_all = request.form.get("ambiguous_all") == "1"
        base["record_type"] = "cik_quarter"
        base["true_total_investments_fv"] = _num(request.form.get("true_total_investments_fv"))
        base["true_position_count"] = _num(request.form.get("true_position_count"))
        base["ambiguous"] = amb_all
        append_label("cik_quarter_labels.jsonl", base)
    else:
        amb_all = request.form.get("ambiguous_all") == "1"
        base["record_type"] = "position"
        base["source_identifier"] = u.get("source_identifier")
        base["unit_uid"] = u.get("unit_uid")
        amb_fields = []
        for f in POSITION_FIELDS:
            key = f if f in ("classification", "lien") else f
            val = request.form.get(f"true_{f}")
            base[f"true_{f if f not in ('classification','lien') else f}"] = (
                _num(val) if f in ("fair_value", "cost") else (val or None))
            if request.form.get(f"amb_{f}"):
                amb_fields.append(f"true_{f}")
        base["ambiguous"] = amb_all or bool(amb_fields)
        base["ambiguous_fields"] = amb_fields
        base["disposition"] = request.form.get("disposition", "valid")
        append_label("position_labels.jsonl", base)
    nxt = idx + 1 if idx + 1 < len(frame) else 0
    return redirect(url_for("unit", idx=nxt))


def _num(s):
    if s is None or str(s).strip() == "":
        return None
    try:
        return float(str(s).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draw", default="batch1")
    ap.add_argument("--port", type=int, default=5057)
    ap.add_argument("--who", default="james")
    ap.add_argument("--no-reload", action="store_true",
                    help="Disable Flask auto-reload on source edits.")
    args = ap.parse_args()
    STATE["frame"] = load_frame(args.draw)
    STATE["candidates"] = load_candidates(args.draw)
    STATE["sha"] = git_sha()
    STATE["who"] = args.who
    print(f"[harness] draw={args.draw} units={len(STATE['frame'])} "
          f"candidates={len(STATE['candidates'])} -> http://127.0.0.1:{args.port}")
    # Auto-reload on source edits (localhost dev tool; reloader only, no debugger).
    # The reloader re-execs this script, so main() re-runs and STATE repopulates.
    app.run(host="127.0.0.1", port=args.port, debug=False,
            use_reloader=not args.no_reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
