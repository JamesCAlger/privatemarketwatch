"""Score any build against an adjudicated continuation batch.

The continuation strata ask a question about the filings, not about the matcher:
"for this position in this quarter, which row in a later quarter is its
continuation, or none".  The answer is therefore build-independent, and this
script replays it against whatever holdings artifact it is pointed at.  One
adjudication, every future build scored.

Verdict mapping (build_packets `_TASK_TEXT["continuation"]`):

    MISSED_LINK + one proposed_link   the position continues into that row
    CONFIRMED                         the position ends here
    INSUFFICIENT_EVIDENCE / other     undecidable, excluded from the rates

Outcomes per adjudicated packet:

    correct_link      truth says continue, build chains anchor to that row
    wrong_link        truth says continue, build chains anchor to a DIFFERENT row
    missing_link      truth says continue, build leaves the anchor unchained forward
    correct_end       truth says end, build leaves the anchor unchained forward
    false_link        truth says end, build chains the anchor forward anyway

Precision  = correct_link / (correct_link + wrong_link + false_link)
Recall     = correct_link / (correct_link + wrong_link + missing_link)

Usage:
    python scripts/match_gold/score_continuation.py \
        --batch-dir data/output/match_quality/gold/mg6_continuation \
        --holdings data/output/private_markets_holdings.csv \
        --label current [--holdings ... --label ...] \
        --out scratch/<session>/continuation_scores.md
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import duckdb
import pandas as pd

_ROW_ID_RE = re.compile(r"^ROW-[0-9a-f]{16}$")
DECIDED = ("correct_link", "wrong_link", "missing_link", "correct_end", "false_link")


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval; the sample is small enough that the normal
    approximation would misstate the bounds near 0 and 1."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_truth(batch_dir: Path) -> pd.DataFrame:
    """One row per adjudicated continuation packet."""
    rows: list[dict] = []
    for vpath in sorted((batch_dir / "verdicts").glob("*.json")):
        pid = vpath.stem
        ppath = batch_dir / "packets" / f"{pid}.json"
        if not ppath.exists():
            continue
        packet = json.loads(ppath.read_text(encoding="utf-8-sig"))
        meta_path = batch_dir / "packets_meta" / f"{pid}.json"
        stratum = ""
        if meta_path.exists():
            stratum = json.loads(meta_path.read_text(encoding="utf-8-sig")).get("stratum", "")
        if not str(stratum).startswith("continuation"):
            continue
        verdict = json.loads(vpath.read_text(encoding="utf-8-sig"))
        prows = packet.get("rows") or []
        anchor = str(prows[0].get("row_id")) if prows else ""
        v = verdict.get("verdict", "")
        links = verdict.get("proposed_links") or []
        truth_row, truth = "", "undecided"
        if v == "MISSED_LINK" and links:
            b = str(links[0].get("row_id_b") or "")
            a = str(links[0].get("row_id_a") or "")
            # The adjudicator may write the pair in either order.
            if a and a != anchor and _ROW_ID_RE.match(a) and b == anchor:
                a, b = b, a
            if _ROW_ID_RE.match(b):
                truth_row, truth = b, "continues"
        elif v == "CONFIRMED":
            truth = "ends"
        rows.append({
            "packet_id": pid, "stratum": stratum, "cik": packet.get("cik", ""),
            "anchor_row_id": anchor, "truth": truth, "truth_row_id": truth_row,
            "confidence": verdict.get("confidence"),
            "n_proposed": len(links),
            "rationale": (verdict.get("rationale") or "").replace("\n", " ")[:300],
        })
    return pd.DataFrame(rows)


def score_build(truth: pd.DataFrame, holdings_path: Path) -> pd.DataFrame:
    """Attach this build's answer for every adjudicated anchor."""
    con = duckdb.connect()
    con.register("t", truth)
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE h AS
        SELECT row_id, cik, position_id, report_date,
               TRY_CAST(fair_value AS DOUBLE) AS fv
        FROM read_csv_auto('{Path(holdings_path).as_posix()}',
                           all_varchar=true, sample_size=-1)
        WHERE row_id IS NOT NULL
    """)
    out = con.execute("""
        WITH anchor AS (
            SELECT t.*, h.position_id AS a_pid, h.report_date AS a_date, h.fv AS a_fv
            FROM t LEFT JOIN h ON h.row_id = t.anchor_row_id
        ),
        -- what the build says continues the anchor: the next row, in a later
        -- quarter, carrying the same position_id
        fwd AS (
            SELECT a.packet_id, MIN(h.report_date) AS f_date
            FROM anchor a JOIN h
              ON h.position_id = a.a_pid AND h.cik = a.cik
             AND h.report_date > a.a_date
            WHERE a.a_pid IS NOT NULL
            GROUP BY a.packet_id
        ),
        built AS (
            SELECT a.packet_id, h.row_id AS built_row_id
            FROM anchor a JOIN fwd f ON f.packet_id = a.packet_id
            JOIN h ON h.position_id = a.a_pid AND h.cik = a.cik
                  AND h.report_date = f.f_date
        )
        SELECT a.*, b.built_row_id,
            CASE
              WHEN a.truth = 'continues' AND b.built_row_id IS NULL THEN 'missing_link'
              WHEN a.truth = 'continues' AND b.built_row_id = a.truth_row_id
                   THEN 'correct_link'
              WHEN a.truth = 'continues' THEN 'wrong_link'
              WHEN a.truth = 'ends' AND b.built_row_id IS NULL THEN 'correct_end'
              WHEN a.truth = 'ends' THEN 'false_link'
              ELSE 'undecided'
            END AS outcome
        FROM anchor a LEFT JOIN built b ON b.packet_id = a.packet_id
    """).df()
    # A build that puts two rows of one later quarter on one position_id is a
    # separate defect (uniqueness is asserted elsewhere); keep one row per packet.
    return out.drop_duplicates("packet_id").reset_index(drop=True)


def _rates(sub: pd.DataFrame) -> dict:
    c = sub["outcome"].value_counts().to_dict()
    correct = c.get("correct_link", 0)
    wrong = c.get("wrong_link", 0)
    missing = c.get("missing_link", 0)
    false_l = c.get("false_link", 0)
    p_den = correct + wrong + false_l
    r_den = correct + wrong + missing
    return {
        "n_decided": int(sum(c.get(k, 0) for k in DECIDED)),
        "undecided": int(c.get("undecided", 0)),
        **{k: int(c.get(k, 0)) for k in DECIDED},
        "precision": correct / p_den if p_den else float("nan"),
        "precision_ci": _wilson(correct, p_den),
        "recall": correct / r_den if r_den else float("nan"),
        "recall_ci": _wilson(correct, r_den),
    }


def render(scored: dict[str, pd.DataFrame]) -> str:
    lines = ["# Continuation metric", "",
             "Build-independent: the adjudicated answer is a fact about the filings,",
             "so every build below is scored against the same sample.", ""]
    strata = sorted({s for df in scored.values() for s in df["stratum"].unique()})
    for scope in ["ALL"] + strata:
        lines += [f"## {scope}", "",
                  "| build | decided | correct | wrong | missing | ended ok | false link "
                  "| precision | recall |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for label, df in scored.items():
            sub = df if scope == "ALL" else df[df["stratum"] == scope]
            m = _rates(sub)
            lines.append(
                "| {} | {} | {} | {} | {} | {} | {} | {:.3f} [{:.2f}-{:.2f}] | "
                "{:.3f} [{:.2f}-{:.2f}] |".format(
                    label, m["n_decided"], m["correct_link"], m["wrong_link"],
                    m["missing_link"], m["correct_end"], m["false_link"],
                    m["precision"], *m["precision_ci"], m["recall"], *m["recall_ci"]))
        lines.append("")
    first = next(iter(scored.values()))
    lines += [f"undecided (insufficient evidence or unresolvable row id): "
              f"{int((first['outcome'] == 'undecided').sum())} of {len(first)} packets", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--batch-dir", required=True, type=Path)
    ap.add_argument("--holdings", required=True, type=Path, action="append",
                    help="holdings CSV to score; repeat to compare builds")
    ap.add_argument("--label", type=str, action="append",
                    help="label for each --holdings, in the same order")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)

    truth = load_truth(args.batch_dir)
    if truth.empty:
        print("no adjudicated continuation packets in %s" % args.batch_dir)
        return 1
    print("adjudicated packets: %d  %s"
          % (len(truth), truth["truth"].value_counts().to_dict()))

    labels = args.label or []
    labels += [p.parent.name or p.name for p in args.holdings[len(labels):]]
    scored = {}
    for label, path in zip(labels, args.holdings):
        scored[label] = score_build(truth, path)
        print("scored %s: %s" % (label, scored[label]["outcome"].value_counts().to_dict()))

    report = render(scored)
    print("\n" + report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        for label, df in scored.items():
            slug = re.sub(r"[^A-Za-z0-9_.-]", "_", label)
            df.to_csv(args.out.with_name(f"{args.out.stem}_{slug}.csv"), index=False)
        print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
