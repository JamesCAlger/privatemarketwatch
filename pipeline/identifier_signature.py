"""Agent A / P0 -- deterministic format-signature + regime engine for the freeform
BDC ``investment_identifier``.

This is the load-bearing deterministic layer under the planned identifier-enrichment
agent (see docs/adjudication_architecture/A_identifier_enrichment_agent.md). It does
NOT call an LLM and does NOT mutate holdings. It assigns each identifier a structural
SIGNATURE so that (cik, signature) clusters the rows that share a parse grammar, and
classifies each filer into one of two regimes:

- DELIMITED  : clean delimiters, name+type only, rates structural (e.g. Golub). The
               punctuation-shape signature clusters these tightly.
- FLATTENED  : everything concatenated into one string with keyword markers, rates
               embedded (e.g. Antares). A keyword-anchored signature clusters these;
               the per-CIK keyword vocabulary differs by filer (P0 uses a global
               STARTER set and the (none)-share reports where it misses).

Pure functions (``punctuation_shape``, ``keyword_signature``, ``signature_for``,
``is_aggregate_candidate``) are unit-tested against real examples. ``build_report``
streams the cached parquet once and emits a per-CIK summary + a per-(cik, signature)
detail table; it is read-only on production artifacts.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Punctuation-shape masking (delimited regime)
# --------------------------------------------------------------------------- #
_RATE_RE = re.compile(r"[0-9]+\.?[0-9]*\s*%")
_MDY_RE = re.compile(r"[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}")
_ISO_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NUM_RE = re.compile(r"[0-9]+\.?[0-9]*")
_WORD_RE = re.compile(r"[a-z][a-z.&']*")
_WRUN_RE = re.compile(r"(W[ ]*)+")
_WS_RE = re.compile(r"\s+")


def punctuation_shape(s: str) -> str:
    """Mask an identifier to a punctuation/structure skeleton for the delimited regime.

    rates -> '%', m/d/y and ISO dates -> 'D' (these mark real structural fields and
    survive), then ALL remaining content (words and plain numbers) -> 'W' and W-runs
    collapse, so a within-field tranche number ('One stop 1' vs 'One stop 2') does NOT
    fragment the grammar. Delimiters (',', '|', '(', ')', '-', '/', ...) are preserved
    as the skeleton. '%'/'D' are non-lowercase so the content pass cannot re-consume them.
    """
    if not s:
        return "(empty)"
    s = s.lower()
    s = _RATE_RE.sub("%", s)
    s = _MDY_RE.sub("D", s)
    s = _ISO_RE.sub("D", s)
    s = _NUM_RE.sub("W", s)      # plain numbers are content, not structure -> fold into W
    s = _WORD_RE.sub("W", s)
    s = _WRUN_RE.sub("W ", s)
    s = _WS_RE.sub(" ", s)
    return s.strip()


# --------------------------------------------------------------------------- #
# Keyword-anchored signature (flattened regime)
# --------------------------------------------------------------------------- #
# P0 STARTER vocabulary. Tuned on Antares; intentionally global so the report's
# (none)-share surfaces where it fails to generalize (the per-CIK dialect gap that
# the agent learns in later phases). Order here does not matter -- the signature is
# ordered by each anchor's first match POSITION in the string.
STARTER_ANCHORS = [
    ("TOTAL", re.compile(r"^\s*total\b", re.I)),
    ("AFFIL", re.compile(r"non-?controlled|controlled/|/non-?affiliated|/affiliated", re.I)),
    ("SECDEBT", re.compile(r"secured debt", re.I)),
    ("EQUITY", re.compile(r"equity investments", re.I)),
    ("SUBORD", re.compile(r"subordinated", re.I)),
    ("ASSETTYPE", re.compile(r"asset type", re.I)),
    ("COMMIT", re.compile(r"commitment type", re.I)),
    ("COMMITEXP", re.compile(r"commitment expiration", re.I)),
    ("REFRATE", re.compile(r"reference rate|\bsofr\b|\blibor\b|\bprime\b|\beuribor\b", re.I)),
    ("RATE", re.compile(r"[0-9]+\.?[0-9]*\s*%")),
    ("MAT", re.compile(r"\b[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}\b")),
]

# Anchors that mark a real position's instrument/category (used by the aggregate
# heuristic: a category keyword with no issuer-ish content after it is a subtotal).
_CATEGORY_ANCHORS = {"SECDEBT", "EQUITY", "SUBORD"}
_POSITION_ANCHORS = {"ASSETTYPE", "COMMIT", "COMMITEXP", "REFRATE", "RATE", "MAT"}

# A real position carries an issuer (legal-entity suffix); a category subtotal does not.
_LEGAL_SUFFIX_RE = re.compile(
    r"\b(L\.?L\.?C|Inc\.?|Incorporated|L\.?P\.?|Ltd\.?|Limited|Corp\.?|Corporation|"
    r"GmbH|N\.?V|B\.?V|S\.?A\.?R\.?L|S\.?A|PTY|PLC|Holdings|Holdco|Bidco|Topco|Midco|"
    r"Buyer|Parent|Borrower)\b", re.I)

# Per-CIK anchor vocabulary store (agent-induced dialects). A JSON list of
# {"label": str, "regex": str}. Falls back to STARTER_ANCHORS when absent.
_ANCHOR_DIR = None  # resolved lazily to avoid import-time config dependency
_ANCHOR_CACHE: dict = {}


def load_anchors(cik: str, anchor_dir=None):
    """Return the compiled anchor list for ``cik`` (per-CIK dialect if present, else the
    global STARTER set). Cached. ``anchor_dir`` overrides the default store (tests)."""
    global _ANCHOR_DIR
    if anchor_dir is None:
        if _ANCHOR_DIR is None:
            from pipeline import config
            _ANCHOR_DIR = config.DATA_DIR / "overrides" / "identifier_anchors"
        anchor_dir = _ANCHOR_DIR
    key = (str(anchor_dir), cik)
    if key in _ANCHOR_CACHE:
        return _ANCHOR_CACHE[key]
    import json
    path = anchor_dir / f"{cik}.json"
    if not path.exists():
        _ANCHOR_CACHE[key] = STARTER_ANCHORS
        return STARTER_ANCHORS
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)
    compiled = [(a["label"], re.compile(a["regex"], re.I)) for a in spec["anchors"]]
    _ANCHOR_CACHE[key] = compiled
    return compiled


def keyword_signature(s: str, anchors=STARTER_ANCHORS) -> str:
    """Ordered sequence of anchor labels present in ``s`` (by first-match position).

    Rate legs and dates each contribute a single token regardless of count, so the
    cash/PIK leg count does not fragment the signature. Returns '(none)' if no anchor
    fires.
    """
    if not s:
        return "(none)"
    from pipeline.identifier_rate import normalize_identifier_text
    s = normalize_identifier_text(s)   # strip BOM/zero-width so anchors match
    hits = []
    for label, rx in anchors:
        m = rx.search(s)
        if m:
            hits.append((m.start(), label))
    if not hits:
        return "(none)"
    hits.sort()
    return " ".join(label for _, label in hits)


def is_aggregate_candidate(s: str, anchors=STARTER_ANCHORS) -> bool:
    """Heuristic leaked-aggregate flag for the flattened regime: a category keyword
    (SECDEBT/EQUITY/SUBORD) present but NO position-level anchor
    (ASSETTYPE/COMMIT/RATE/MAT/...). e.g. 'Secured Debt Air Freight and Logistics'
    (a GICS-industry subtotal) -> True. A real position carries a position anchor.
    """
    sig = set(keyword_signature(s, anchors).split())
    if "TOTAL" in sig:
        return True
    if not (sig & _CATEGORY_ANCHORS) or (sig & _POSITION_ANCHORS):
        return False
    # category keyword + no position anchor, but a legal-entity suffix means it is a real
    # (e.g. equity) position whose anchors just aren't in vocab -> NOT a subtotal.
    return not _LEGAL_SUFFIX_RE.search(s)


# --------------------------------------------------------------------------- #
# Regime detection
# --------------------------------------------------------------------------- #
RATE_EMBED_FLATTENED_PCT = 20.0   # >= this share of rows embed a '%' rate -> flattened
ANCHOR_PRESENT_FLATTENED_PCT = 30.0  # or >= this share carry a keyword anchor

_ANCHOR_PRESENCE_RE = re.compile(
    r"asset type|investment type|commitment type|reference rate|secured debt|"
    r"non-?controlled|debt investments|equity investments",
    re.I,
)


def detect_regime(rate_embed_pct: float, anchor_present_pct: float) -> str:
    """Classify a filer from two cheap per-CIK signals."""
    if rate_embed_pct >= RATE_EMBED_FLATTENED_PCT or anchor_present_pct >= ANCHOR_PRESENT_FLATTENED_PCT:
        return "flattened"
    return "delimited"


def signature_for(s: str, regime: str, anchors=STARTER_ANCHORS) -> str:
    return keyword_signature(s, anchors) if regime == "flattened" else punctuation_shape(s)


# --------------------------------------------------------------------------- #
# Per-CIK aggregation
# --------------------------------------------------------------------------- #
@dataclass
class CikAccumulator:
    cik: str
    entity_name: str = ""
    n: int = 0
    rate_rows: int = 0
    anchor_rows: int = 0
    _ids: list = field(default_factory=list)  # buffered identifiers for this CIK

    def add(self, entity_name: str, identifier: str) -> None:
        if entity_name and not self.entity_name:
            self.entity_name = entity_name
        self.n += 1
        if _RATE_RE.search(identifier):
            self.rate_rows += 1
        if _ANCHOR_PRESENCE_RE.search(identifier):
            self.anchor_rows += 1
        self._ids.append(identifier)

    def summarize(self, anchors=STARTER_ANCHORS, top_n_detail: int = 10):
        rate_pct = 100.0 * self.rate_rows / self.n if self.n else 0.0
        anchor_pct = 100.0 * self.anchor_rows / self.n if self.n else 0.0
        regime = detect_regime(rate_pct, anchor_pct)

        counts: Counter = Counter()
        examples: dict = {}
        none_n = 0
        rate_captured = 0
        for ident in self._ids:
            sig = signature_for(ident, regime, anchors)
            counts[sig] += 1
            examples.setdefault(sig, ident)
            if sig == "(none)":
                none_n += 1
            if _RATE_RE.search(ident) and "RATE" in sig:
                rate_captured += 1

        ordered = counts.most_common()
        cum = 0
        cover = {80: None, 90: None, 95: None}
        for i, (_, c) in enumerate(ordered, 1):
            cum += c
            for m in cover:
                if cover[m] is None and 100.0 * cum / self.n >= m:
                    cover[m] = i

        summary = {
            "cik": self.cik,
            "entity_name": self.entity_name,
            "n_rows": self.n,
            "regime": regime,
            "rate_embed_pct": round(rate_pct, 1),
            "anchor_present_pct": round(anchor_pct, 1),
            "distinct_signatures": len(ordered),
            "cover80": cover[80],
            "cover90": cover[90],
            "cover95": cover[95],
            "largest_sig_pct": round(100.0 * ordered[0][1] / self.n, 1) if ordered else 0.0,
            "none_pct": round(100.0 * none_n / self.n, 1),
            "rate_capture_pct": (
                round(100.0 * rate_captured / self.rate_rows, 1) if self.rate_rows else None
            ),
            "top1_sig": ordered[0][0] if ordered else "",
            "top2_sig": ordered[1][0] if len(ordered) > 1 else "",
        }
        detail = [
            {
                "cik": self.cik,
                "regime": regime,
                "signature": sig,
                "count": c,
                "pct": round(100.0 * c / self.n, 1),
                "example": str(examples[sig])[:160],
            }
            for sig, c in ordered[:top_n_detail]
        ]
        # free memory
        self._ids = []
        return summary, detail


# --------------------------------------------------------------------------- #
# Report builder (streams the parquet once; read-only)
# --------------------------------------------------------------------------- #
def build_report(parquet_path: str, min_rows: int = 50, anchors=STARTER_ANCHORS,
                 log=print):
    """Stream current-period rows ordered by CIK, accumulate per-CIK, and return
    (summary_rows, detail_rows). One scan; constant memory per CIK.
    """
    import duckdb

    con = duckdb.connect()
    con.execute(
        f"""
        CREATE TEMP VIEW v AS
        SELECT CAST(cik AS VARCHAR) AS cik,
               CAST(entity_name AS VARCHAR) AS entity_name,
               CAST(investment_identifier AS VARCHAR) AS ident
        FROM '{parquet_path}'
        WHERE investment_identifier IS NOT NULL
          AND length(trim(investment_identifier)) > 0
          AND CAST(period AS VARCHAR) = CAST(report_date AS VARCHAR)
        ORDER BY cik
        """
    )
    cur = con.execute("SELECT cik, entity_name, ident FROM v")

    summaries, details = [], []
    acc = None
    seen = 0
    while True:
        batch = cur.fetchmany(20000)
        if not batch:
            break
        for cik, entity_name, ident in batch:
            if acc is None or acc.cik != cik:
                if acc is not None and acc.n >= min_rows:
                    s, d = acc.summarize(anchors)
                    summaries.append(s)
                    details.extend(d)
                acc = CikAccumulator(cik=cik)
            acc.add(entity_name or "", ident or "")
        seen += len(batch)
        log(f"  ...processed {seen} rows ({len(summaries)} CIKs summarized)")
    if acc is not None and acc.n >= min_rows:
        s, d = acc.summarize(anchors)
        summaries.append(s)
        details.extend(d)
    con.close()
    summaries.sort(key=lambda r: r["n_rows"], reverse=True)
    return summaries, details


def main():  # pragma: no cover - thin IO wrapper
    import csv

    from pipeline import config

    parquet = str(config.OUTPUT_DIR / "bdc_holdings.parquet")
    out_summary = config.OUTPUT_DIR / "identifier_signature_report.csv"
    out_detail = config.OUTPUT_DIR / "identifier_signature_detail.csv"

    print(f"Building identifier-signature report from {parquet}")
    summaries, details = build_report(parquet)
    print(f"Summarized {len(summaries)} CIKs; writing report.")

    with open(out_summary, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summaries[0].keys()))
        w.writeheader()
        w.writerows(summaries)
    with open(out_detail, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(details[0].keys()))
        w.writeheader()
        w.writerows(details)

    flat = [s for s in summaries if s["regime"] == "flattened"]
    print(f"Wrote {out_summary.name} and {out_detail.name}")
    print(f"  delimited CIKs: {len(summaries) - len(flat)}  flattened CIKs: {len(flat)}")


if __name__ == "__main__":  # pragma: no cover
    main()
