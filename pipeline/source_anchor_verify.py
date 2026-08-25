"""Deterministic source verification for ``source_anchored_value`` correction leaves.

The safety core of the general-but-verifiable stage-2 class: the worker never authors a
number, it POINTS at a filing cell; this module re-parses the cached filing with the
SAME parser the evidence CLI exposes (``pipeline.html_extract._extract_tables``) and
refuses the leaf unless every assertion survives four checks:

1. Cell check -- the cited cell parses to exactly ``source.value`` and the cited row
   contains ``quoted_text`` (bounds + transcription handshake).
2. Row fingerprint -- >= 2 witness cells in the SAME parsed row match the position's
   known-correct extracted values (defends against filer-specific parse corruption: a
   column-shifted or cell-merged parse almost never co-locates two independent known
   values coherently).
3. Table health -- deterministic parse-quality heuristics on the cited table; an
   unstable parse refuses the leaf (fail closed) rather than trusting a grid the
   parser itself mangled.
4. XBRL bridge co-sign -- where an audited HTML-section bridge entry covers the cited
   (accession, table, row), its issuer must agree with the selected holdings row; no
   bridge coverage is recorded, not failed (bridges are intentionally sparse).

Cache-only, read-only, no network. Runs twice: dispatcher intake
(``validate_corrections --verify-source``) and the B3-side gate (``run_remediation``
apply path). Fail closed on a missing/unparseable filing. ASCII-only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from pipeline.correction_leaf import MIN_WITNESSES

# Fields whose filing cells are stated at the table's declared scale (thousands etc.);
# rate-ish fields are absolute percentages and never scaled.
_SCALED_FIELDS = frozenset({"fair_value", "cost", "principal_amount", "shares_held"})

_WS_RE = re.compile(r"\s+")
_NUM_CLEAN_RE = re.compile(r"[$,%\s]")

# Table-health heuristic (v1): rows with >= 2 non-empty cells are "content rows"; a
# healthy parse has most content rows within +/-2 cells of the modal width. Tuned
# loose on purpose -- SOI tables legitimately mix section headers and continuation
# rows; the fingerprint check is the precise defense, this catches gross mangling.
_HEALTH_MAX_DEVIANT_FRACTION = 0.40
_HEALTH_WIDTH_TOLERANCE = 2


def _norm_number(text: Any) -> float | None:
    """Parse a filing cell into a number: strips $ % , and whitespace; parenthesized
    values are negative; dashes/empty are None. Returns None when not numeric."""
    s = _WS_RE.sub(" ", str(text or "")).strip()
    if not s or s in {"-", "--"} or set(s) <= {"-", "–", "—"}:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = _NUM_CLEAN_RE.sub("", s)
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _numbers_equal(a: float, b: float, *, rel_tol: float = 1e-6) -> bool:
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    return scale > 0 and abs(a - b) / scale <= rel_tol


def _row_text(row: list) -> str:
    return " | ".join(_WS_RE.sub(" ", str(c)).strip() for c in row
                      if str(c or "").strip())


def table_health(table: list[list]) -> dict:
    """Deterministic parse-quality metrics for one parsed table."""
    content_rows = [r for r in table if sum(1 for c in r if str(c or "").strip()) >= 2]
    if not content_rows:
        return {"healthy": False, "reason": "no content rows", "n_content_rows": 0}
    widths = [len(r) for r in content_rows]
    modal = max(set(widths), key=widths.count)
    deviant = sum(1 for w in widths if abs(w - modal) > _HEALTH_WIDTH_TOLERANCE)
    frac = deviant / len(widths)
    return {"healthy": frac <= _HEALTH_MAX_DEVIANT_FRACTION,
            "n_content_rows": len(content_rows), "modal_width": modal,
            "deviant_fraction": round(frac, 3)}


def _default_html_loader(cik: str, accession: str) -> str | None:
    from pipeline.html_soi_evidence import _html_path
    path = _html_path("bdc", cik, accession)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _load_cik_holdings(cik: str, holdings_path: Path):
    import duckdb
    import pandas as pd  # noqa: F401  (duckdb fetchdf needs pandas present)
    con = duckdb.connect()
    src = str(holdings_path).replace("'", "''")
    reader = ("read_parquet" if str(holdings_path).endswith(".parquet")
              else "read_csv_auto")
    return con.execute(
        f"SELECT * FROM {reader}('{src}') "
        f"WHERE ltrim(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), '0') "
        f"= '{str(cik).lstrip('0')}'").fetchdf()


def _selector_rows(holdings, row_selector, quarters: list[str]):
    """Holdings rows the assertion's selector picks, restricted to the leaf scope."""
    from pipeline.agent_b2_appliers import _selector_mask
    df = holdings
    if quarters and "report_date" in df.columns:
        df = df.loc[df["report_date"].astype(str).isin(quarters)]
    mask, err = _selector_mask(df, row_selector)
    if err:
        return None, err
    picked = df.loc[mask]
    if picked.empty:
        return None, "row_selector matched no in-scope holdings rows"
    return picked, ""


def verify_leaf(
    leaf: dict, *,
    holdings_df=None,
    holdings_path: Path | None = None,
    html_loader: Callable[[str, str], str | None] | None = None,
    bridge_dir: Path | None = None,
) -> dict:
    """Verify every assertion of a source_anchored_value leaf against the cached
    filing + extracted holdings. Returns {"ok": bool, "errors": [...], "checks": [...]}.
    Fail closed: a missing filing, unhealthy table, or unverifiable witness refuses
    the leaf. ``holdings_df``/``html_loader``/``bridge_dir`` are injectable for tests;
    production defaults are the unified holdings parquet and the BDC HTML cache."""
    from pipeline.html_extract import _extract_tables

    errors: list[str] = []
    checks: list[dict] = []
    cik = str(leaf.get("cik") or "").strip()
    quarters = [str(q) for q in (leaf.get("scope") or {}).get("quarters", []) if q]
    assertions = list(((leaf.get("template") or {}).get("assertions")) or [])
    if not assertions:
        return {"ok": False, "errors": ["no assertions to verify"], "checks": []}

    if holdings_df is None:
        if holdings_path is None:
            from pipeline import config
            holdings_path = config.UNIFIED_HOLDINGS_PARQUET_FILE
        if not Path(holdings_path).exists():
            return {"ok": False, "checks": [],
                    "errors": [f"holdings frame unavailable: {holdings_path}"]}
        holdings_df = _load_cik_holdings(cik, holdings_path)

    loader = html_loader or _default_html_loader
    tables_by_accession: dict[str, list | None] = {}
    bridge_rows = None

    for i, a in enumerate(assertions):
        tag = f"assertions[{i}]"
        src = (a or {}).get("source") or {}
        accession = str(src.get("accession_number") or "").strip()
        t, r, c = src.get("table_index"), src.get("row_index"), src.get("cell_index")
        check: dict = {"assertion": i, "accession": accession,
                       "coords": [t, r, c], "field": a.get("field")}
        checks.append(check)

        # -- resolve + parse the filing (once per accession; fail closed) -----------
        if accession not in tables_by_accession:
            raw = loader(cik, accession)
            tables_by_accession[accession] = _extract_tables(raw) if raw else None
        tables = tables_by_accession[accession]
        if tables is None:
            errors.append(f"{tag}: cached filing missing for accession {accession}")
            continue
        if not isinstance(t, int) or not (0 <= t < len(tables)):
            errors.append(f"{tag}: table_index {t!r} out of range (0..{len(tables) - 1})")
            continue
        table = tables[t]

        # -- 3. table health (fail closed on a mangled parse) -----------------------
        health = table_health(table)
        check["table_health"] = health
        if not health["healthy"]:
            errors.append(f"{tag}: cited table {t} fails parse-health "
                          f"({health.get('reason') or health.get('deviant_fraction')}); "
                          "refusing source-anchored correction on an unstable parse")
            continue

        if not isinstance(r, int) or not (0 <= r < len(table)):
            errors.append(f"{tag}: row_index {r!r} out of range for table {t}")
            continue
        row = table[r]
        row_text = _row_text(row)

        # -- 1. cell check + quoted_text handshake ----------------------------------
        quoted = _WS_RE.sub(" ", str(src.get("quoted_text") or "")).strip()
        if quoted and quoted not in row_text:
            errors.append(f"{tag}: quoted_text not found in cited row (row reads: "
                          f"{row_text[:200]!r})")
            continue
        if not isinstance(c, int) or not (0 <= c < len(row)):
            errors.append(f"{tag}: cell_index {c!r} out of range for row (width {len(row)})")
            continue
        parsed = _norm_number(row[c])
        claimed = src.get("value")
        if parsed is None or not _numbers_equal(float(parsed), float(claimed), rel_tol=1e-9):
            errors.append(f"{tag}: cited cell parses to {parsed!r}, leaf claims "
                          f"{claimed!r} -- the filing does not contain the asserted value "
                          "at these coordinates")
            continue
        check["cell_value"] = parsed

        # -- resolve the target holdings rows for witness comparison ----------------
        picked, err = _selector_rows(holdings_df, (a or {}).get("row_selector"), quarters)
        if err:
            errors.append(f"{tag}: {err}")
            continue
        check["n_selected_rows"] = int(len(picked))

        # -- 2. row fingerprint: witnesses ------------------------------------------
        # The table's numeric scale (units/thousands/millions) is INFERRED from the
        # scaled witnesses: one common multiplier must explain every scaled witness
        # against the position's known-correct extracted values. Auto-inference
        # removes the scale as a worker-controlled degree of freedom -- witnesses
        # must equal extracted/m for a single m, which cannot be gamed. A scaled
        # ASSERTED field's declared unit_multiplier must then equal the inferred
        # scale (its own extracted value is the wrong one being corrected, so this
        # cross-check is the only anchor for the applier's multiplication).
        import pandas as pd
        witnesses = list((a or {}).get("witnesses") or [])
        witness_facts: list[tuple[int, str, float, list[float]]] = []
        witness_failed = False
        for j, w in enumerate(witnesses):
            wc, wf, wv = w.get("cell_index"), str(w.get("field") or ""), w.get("value")
            if not isinstance(wc, int) or not (0 <= wc < len(row)):
                errors.append(f"{tag}.witnesses[{j}]: cell_index {wc!r} out of range")
                witness_failed = True
                continue
            wparsed = _norm_number(row[wc])
            if wparsed is None or not _numbers_equal(float(wparsed), float(wv), rel_tol=1e-9):
                errors.append(f"{tag}.witnesses[{j}]: witness cell parses to {wparsed!r}, "
                              f"leaf claims {wv!r}")
                witness_failed = True
                continue
            if wf not in picked.columns:
                errors.append(f"{tag}.witnesses[{j}]: field {wf!r} not in holdings frame")
                witness_failed = True
                continue
            extracted = pd.to_numeric(picked[wf], errors="coerce").dropna()
            if extracted.empty:
                errors.append(f"{tag}.witnesses[{j}]: selected rows carry no extracted "
                              f"{wf} to witness against")
                witness_failed = True
                continue
            witness_facts.append((j, wf, float(wv), [float(x) for x in extracted]))
        if witness_failed or len(witness_facts) < MIN_WITNESSES:
            errors.append(f"{tag}: row fingerprint failed "
                          f"({len(witness_facts)}/{len(witnesses)} witnesses usable, "
                          f"need >= {MIN_WITNESSES} and all passing)")
            continue
        scaled = [(j, wf, wv, xs) for j, wf, wv, xs in witness_facts
                  if wf in _SCALED_FIELDS]
        rate_ws = [(j, wf, wv, xs) for j, wf, wv, xs in witness_facts
                   if wf not in _SCALED_FIELDS]
        table_mult: float | None = None
        if scaled:
            for m in (1.0, 1000.0, 1000000.0):
                if all(all(_numbers_equal(x, wv * m) for x in xs)
                       for _, _, wv, xs in scaled):
                    table_mult = m
                    break
            if table_mult is None:
                errors.append(f"{tag}: no single table scale in {{1, 1000, 1000000}} "
                              "explains the scaled witnesses -- the cited row does not "
                              "describe the selected position")
                continue
        bad_rate = [j for j, _, wv, xs in rate_ws
                    if not all(_numbers_equal(x, wv) for x in xs)]
        if bad_rate:
            errors.append(f"{tag}: rate witness(es) {bad_rate} do not match the "
                          "extracted values")
            continue
        check["witnesses_passed"] = len(witness_facts)
        check["inferred_table_multiplier"] = table_mult
        field = str(a.get("field") or "")
        declared_mult = float(src.get("unit_multiplier", 1) or 1)
        if field in _SCALED_FIELDS:
            if table_mult is None:
                errors.append(f"{tag}: a scaled asserted field ({field}) requires at "
                              "least one scaled witness (fair_value/cost/principal/"
                              "shares) to pin the table scale")
                continue
            if declared_mult != table_mult:
                errors.append(f"{tag}: declared unit_multiplier {declared_mult:g} does "
                              f"not match the witness-inferred table scale "
                              f"{table_mult:g}")
                continue

        # -- 4. XBRL bridge co-sign (where coverage exists) --------------------------
        if bridge_rows is None:
            from pipeline.bdc_xbrl_html_bridge import load_html_section_bridge_rows
            bridge_rows = load_html_section_bridge_rows(bridge_dir, ciks=[cik])
        covered = bridge_rows[
            (bridge_rows["accession_number"].astype(str) == accession)
            & (bridge_rows["table_index"].astype("Int64") == t)
            & (bridge_rows["row_index"].astype("Int64") == r)
        ] if len(bridge_rows) else bridge_rows
        if len(covered):
            bridge_issuer = str(covered.iloc[0].get("issuer_name") or "").strip().lower()
            sel_issuers = {str(x).strip().lower()
                           for x in picked.get("issuer_name", []) if str(x).strip()}
            agree = any(bridge_issuer and (bridge_issuer in s or s in bridge_issuer)
                        for s in sel_issuers)
            check["bridge"] = "agree" if agree else "disagree"
            if not agree:
                errors.append(f"{tag}: XBRL bridge covers the cited row with issuer "
                              f"{bridge_issuer!r}, which does not match the selected "
                              f"holdings issuer(s) {sorted(sel_issuers)[:3]}")
                continue
        else:
            check["bridge"] = "not_covered"

    return {"ok": not errors, "errors": errors, "checks": checks}
