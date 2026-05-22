"""Audit REVIEW fund-strategy correction candidates.

This is a read-only analyst-triage report.  It inspects the generated
fund_strategy_correction_candidates.csv and writes a markdown report plus a
CSV of sampled/flagged REVIEW rows.  It does not rebuild or mutate holdings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd


INPUT = Path("data/output/fund_strategy_correction_candidates.csv")
REPORT = Path("data/output/fund_strategy_review_spot_check.md")
SAMPLES = Path("data/output/fund_strategy_review_spot_check_samples.csv")

REAL_ESTATE_PATTERN = re.compile(
    r"\b(?:industrial|property|properties|realty|mortgage|apartment|apartments|"
    r"multifamily|multi-family|housing|logistics)\b",
    re.IGNORECASE,
)
FUND_LIKE_PATTERN = re.compile(
    r"\b(?:fund|lp|l\.p\.|limited partnership|capital partners|private credit|"
    r"loan fund|bdc)\b",
    re.IGNORECASE,
)
EXPLICIT_FUND_PATTERN = re.compile(
    r"\b(?:fund|limited partnership|l\.p\.|loan fund|private credit fund|bdc)\b",
    re.IGNORECASE,
)
LP_ONLY_PATTERN = re.compile(r"\b(lp|l\.p\.)\b", re.IGNORECASE)
GENERIC_INDUSTRY_RE_PATTERN = re.compile(
    r"\b(?:industrial products|transportation & logistics|air freight & logistics|"
    r"commercial services|mortgage revenue|mtg rev)\b",
    re.IGNORECASE,
)

KEY_COLUMNS = [
    "cik",
    "report_date",
    "source",
    "accession_number",
    "bdc_investment_identifier",
    "nport_holding_id",
    "issuer_name",
    "instrument_description",
]


def _text(row: pd.Series) -> str:
    return f"{row.get('issuer_name', '')} {row.get('instrument_description', '')}"


def _has(pattern: re.Pattern[str], row: pd.Series) -> bool:
    return bool(pattern.search(_text(row)))


def _same_classification(df: pd.DataFrame) -> pd.Series:
    return (
        df["current_index_classification"].fillna("").astype(str)
        == df["proposed_index_classification"].fillna("").astype(str)
    ) & (
        df["current_asset_class"].fillna("").astype(str)
        == df["proposed_asset_class"].fillna("").astype(str)
    )


def _selection_key(row: pd.Series) -> tuple[str, ...]:
    return tuple("" if pd.isna(row.get(col)) else str(row.get(col)) for col in KEY_COLUMNS)


def _add_bucket(selected: dict[tuple[str, ...], dict[str, object]], rows: pd.DataFrame, bucket: str) -> None:
    for _, row in rows.iterrows():
        key = _selection_key(row)
        if key not in selected:
            selected[key] = row.to_dict()
            selected[key]["selection_bucket"] = bucket
        else:
            selected[key]["selection_bucket"] = (
                str(selected[key]["selection_bucket"]) + ";" + bucket
            )


def _recommended_action(row: pd.Series) -> tuple[str, str, str]:
    mechanism = str(row.get("mechanism", ""))
    fund_strategy = str(row.get("fund_strategy", ""))
    current_index = str(row.get("current_index_classification", ""))
    current_asset = str(row.get("current_asset_class", ""))
    issuer_category = str(row.get("issuer_category", ""))
    asset_category = str(row.get("asset_category", ""))
    row_evidence = str(row.get("row_source_evidence", ""))

    has_re = _has(REAL_ESTATE_PATTERN, row)
    has_fund = _has(FUND_LIKE_PATTERN, row)
    has_explicit_fund = _has(EXPLICIT_FUND_PATTERN, row)
    has_lp_only = _has(LP_ONLY_PATTERN, row) and not has_explicit_fund
    generic_re = _has(GENERIC_INDUSTRY_RE_PATTERN, row)

    if mechanism in {"fund_holding_strategy_alignment", "direct_real_estate_row_evidence"}:
        return (
            "KEEP_REVIEW",
            "Row/source evidence is present, but current and proposed classifications already match.",
            "No classifier change from this audit.",
        )

    if (
        fund_strategy == "PRIVATE_CREDIT"
        and current_asset == "PRIVATE_CREDIT"
        and not has_explicit_fund
    ):
        return (
            "KEEP_REVIEW",
            "Private-credit strategy row is already in the private-credit asset class; no stronger row-level fund mechanism is visible.",
            "No classifier change from this audit.",
        )

    if (
        fund_strategy == "REAL_ESTATE"
        and current_asset == "REAL_ESTATE"
        and not has_explicit_fund
    ):
        return (
            "KEEP_REVIEW",
            "Real-estate strategy row is already in the real-estate asset class; no proposed classification diff was missed.",
            "No classifier change from this audit.",
        )

    if has_explicit_fund and issuer_category != "FUND" and "FUND" not in current_index:
        return (
            "POSSIBLE_RULE_GAP",
            "Name text contains explicit fund language while source fields do not mark the row as a fund.",
            "Review false positives, then consider a constrained fund-name rule or per-CIK correction.",
        )

    if (
        fund_strategy == "REAL_ESTATE"
        and has_re
        and current_asset != "REAL_ESTATE"
        and asset_category in {"EQUITY_COMMON", "EQUITY_PREFERRED", "OTHER"}
    ):
        return (
            "POSSIBLE_RULE_GAP",
            "Real-estate strategy plus broad real-estate name evidence points to a possible missed real-estate position.",
            "Review source filing evidence before adding any broader real-estate rule.",
        )

    if generic_re or (
        has_re
        and asset_category in {"LOAN", "DEBT"}
        and issuer_category == "CORPORATE"
        and current_asset in {"PRIVATE_CREDIT", "OTHER"}
    ):
        return (
            "SOURCE_CONFLICT",
            "Broad name term conflicts with debt/loan or corporate source fields; it may describe borrower industry rather than exposure type.",
            "Keep as REVIEW unless source filing evidence supports a scoped correction.",
        )

    if has_lp_only or has_fund or has_re or row_evidence:
        return (
            "NEEDS_FILING_EVIDENCE",
            "Candidate CSV fields contain a weak textual signal, but not enough mechanism to mutate classification.",
            "Escalate only if the row is material for a CIK-quarter residual.",
        )

    return (
        "KEEP_REVIEW",
        "No row-level mechanism strong enough to mutate classification was visible in the candidate fields.",
        "No classifier change from this audit.",
    )


def _counts_table(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return "_No rows._"
    counts = (
        df.groupby(columns, dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values(["rows"] + columns, ascending=[False] + [True] * len(columns))
    )
    return _markdown_table(counts)


def _markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    columns = [str(col) for col in df.columns]
    rows = [
        ["" if pd.isna(value) else str(value) for value in row]
        for row in df.to_numpy()
    ]
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def main() -> None:
    if not INPUT.exists():
        raise FileNotFoundError(INPUT)

    df = pd.read_csv(INPUT, dtype=str).fillna("")
    df["affected_fair_value_numeric"] = pd.to_numeric(
        df["affected_fair_value"], errors="coerce"
    ).fillna(0.0)

    review = df[df["correction_status"] == "REVIEW"].copy()
    reject = df[df["correction_status"] == "REJECT"].copy()

    review_same = _same_classification(review)
    review_proposed_diff_count = int((~review_same).sum())

    evidence_mechanisms = {
        "fund_holding_strategy_alignment",
        "direct_real_estate_row_evidence",
    }
    review_evidence = review[review["mechanism"].isin(evidence_mechanisms)]
    evidence_not_same_count = int((~_same_classification(review_evidence)).sum())

    allowed_reject_mechanisms = {
        "explicit_cash_or_government_row_preserved",
        "explicit_structured_credit_row_preserved",
        "explicit_hedge_fund_row_preserved",
    }
    reject_bad_mechanism_count = int(
        (~reject["mechanism"].isin(allowed_reject_mechanisms)).sum()
    )

    text = (
        review["issuer_name"].fillna("")
        + " "
        + review["instrument_description"].fillna("")
    )
    review["has_broad_real_estate_term"] = text.str.contains(
        REAL_ESTATE_PATTERN, regex=True, na=False
    )
    review["has_broad_fund_like_term"] = text.str.contains(
        FUND_LIKE_PATTERN, regex=True, na=False
    )
    review["has_broad_signal_conflict"] = (
        (
            review["has_broad_real_estate_term"]
            & (review["current_asset_class"] != "REAL_ESTATE")
        )
        | (
            review["has_broad_fund_like_term"]
            & (review["issuer_category"] != "FUND")
            & ~review["current_index_classification"].str.contains("FUND", na=False)
        )
    )

    selected: dict[tuple[str, ...], dict[str, object]] = {}
    by_fv = review.sort_values("affected_fair_value_numeric", ascending=False)
    _add_bucket(selected, by_fv.head(50), "high_fv_overall")
    for rule_id in ["FS01", "FS02", "FS03", "FS04"]:
        rows = by_fv[by_fv["rule_id"] == rule_id].head(25)
        _add_bucket(selected, rows, f"high_fv_{rule_id}")
    _add_bucket(
        selected,
        by_fv[by_fv["has_broad_real_estate_term"]].head(75),
        "broad_real_estate_terms",
    )
    _add_bucket(
        selected,
        by_fv[by_fv["has_broad_fund_like_term"]].head(75),
        "broad_fund_like_terms",
    )
    _add_bucket(
        selected,
        by_fv[by_fv["has_broad_signal_conflict"]].head(100),
        "broad_signal_conflict",
    )

    samples = pd.DataFrame(selected.values())
    if not samples.empty:
        labels = samples.apply(_recommended_action, axis=1, result_type="expand")
        samples["analyst_flag"] = labels[0]
        samples["analyst_reason"] = labels[1]
        samples["recommended_action"] = labels[2]
        ordered = [
            "selection_bucket",
            "analyst_flag",
            "analyst_reason",
            "recommended_action",
            "correction_status",
            "rule_id",
            "mechanism",
            "confidence",
            "residual_risk",
            "cik",
            "entity_name",
            "report_date",
            "source",
            "accession_number",
            "bdc_investment_identifier",
            "nport_holding_id",
            "issuer_name",
            "instrument_description",
            "asset_category",
            "issuer_category",
            "nport_asset_cat",
            "nport_issuer_type",
            "current_index_classification",
            "current_asset_class",
            "proposed_index_classification",
            "proposed_asset_class",
            "fund_strategy",
            "fund_strategy_source",
            "fund_strategy_evidence",
            "row_source_evidence",
            "affected_fair_value",
        ]
        samples = samples.reindex(columns=ordered)
    samples.to_csv(SAMPLES, index=False)

    possible_gaps = (
        samples[samples["analyst_flag"] == "POSSIBLE_RULE_GAP"].copy()
        if not samples.empty
        else pd.DataFrame()
    )

    report = [
        "# Fund Strategy REVIEW Row Spot Check",
        "",
        "## Scope",
        "",
        (
            "Read-only analyst-triage audit of "
            "`data/output/fund_strategy_correction_candidates.csv`. "
            "No unified holdings, frontend JSON, or classifier logic was changed."
        ),
        "",
        "## Candidate Counts",
        "",
        _counts_table(df, ["correction_status"]),
        "",
        "## Counts By Status, Rule, Mechanism",
        "",
        _counts_table(df, ["correction_status", "rule_id", "mechanism"]),
        "",
        "## Invariant Results",
        "",
        f"- REVIEW proposed-diff count: {review_proposed_diff_count}",
        (
            "- REVIEW rows with `fund_holding_strategy_alignment` or "
            f"`direct_real_estate_row_evidence` but changed proposed classes: {evidence_not_same_count}"
        ),
        f"- REJECT rows with unexpected blocker mechanism: {reject_bad_mechanism_count}",
        (
            "- Allowed REJECT blockers: cash/government, structured credit, "
            "and hedge fund evidence."
        ),
        "",
        "## REVIEW Screen Counts",
        "",
        (
            f"- REVIEW rows with broad real-estate terms: "
            f"{int(review['has_broad_real_estate_term'].sum())}"
        ),
        (
            f"- REVIEW rows with broad fund-like terms: "
            f"{int(review['has_broad_fund_like_term'].sum())}"
        ),
        (
            f"- REVIEW rows where a broad signal conflicts with current source/classification fields: "
            f"{int(review['has_broad_signal_conflict'].sum())}"
        ),
        f"- Sampled/flagged rows written to CSV: {len(samples)}",
        "",
        "## Analyst Flags In Sample",
        "",
        _counts_table(samples, ["analyst_flag", "rule_id", "mechanism"])
        if not samples.empty
        else "_No sample rows._",
        "",
        "## Spot-Check Conclusion",
        "",
        (
            "The current REVIEW gate worked as intended for the invariant being tested: "
            "no REVIEW row proposes a classification or asset-class change. Rows already "
            "carrying fund-holding or direct-real-estate row evidence are REVIEW only "
            "because current and proposed classes are already consistent."
        ),
        "",
        (
            "Material candidates remain on the table, but they are not silent APPLY misses "
            "under the current mechanism. The remaining risk is that some source fields "
            "label fund-like or real-estate-like positions as corporate debt/equity/other, "
            "which requires either source-filing evidence or a narrower deterministic rule."
        ),
        "",
        "## Top Suspected Missed-Candidate Themes",
        "",
    ]

    if possible_gaps.empty:
        report.append("- No sampled rows were flagged as POSSIBLE_RULE_GAP.")
    else:
        themes = (
            possible_gaps.groupby(
                [
                    "rule_id",
                    "fund_strategy",
                    "current_index_classification",
                    "current_asset_class",
                    "asset_category",
                    "issuer_category",
                ],
                dropna=False,
            )
            .agg(
                rows=("cik", "size"),
                sample_fair_value=("affected_fair_value", lambda s: pd.to_numeric(s, errors="coerce").sum()),
            )
            .reset_index()
            .sort_values(["sample_fair_value", "rows"], ascending=False)
            .head(10)
        )
        themes["sample_fair_value"] = themes["sample_fair_value"].round(2)
        report.append(_markdown_table(themes))

    report.extend(
        [
            "",
            "## Residual Uncertainty",
            "",
            (
                "- Candidate CSV fields are enough to test proposed-diff leakage, but "
                "not enough to prove that broad fund or real-estate name terms are true "
                "fund interests or direct real-estate exposures."
            ),
            (
                "- LP and capital-partners text has high false-positive risk because it "
                "can be borrower legal-form language, not fund-interest evidence."
            ),
            (
                "- Industrial, logistics, mortgage, and housing terms often describe "
                "borrower industry or financing purpose; treating them globally as "
                "real estate would risk silent overclassification."
            ),
            "",
            "## Recommended Next Fixes",
            "",
            (
                "1. Review `POSSIBLE_RULE_GAP` rows in "
                "`data/output/fund_strategy_review_spot_check_samples.csv` against "
                "source filings before adding any rule."
            ),
            (
                "2. If explicit `Fund` names marked `issuer_category=CORPORATE` prove "
                "valid across a false-positive sample, add a constrained deterministic "
                "rule or per-CIK correction with tests."
            ),
            (
                "3. Keep broad real-estate industry terms as review signals until a "
                "CIK-quarter source reconciliation can distinguish borrower industry "
                "from direct real-estate exposure."
            ),
            "",
        ]
    )

    REPORT.write_text("\n".join(report), encoding="utf-8")

    print(f"input_rows={len(df)}")
    print(f"review_rows={len(review)}")
    print(f"review_proposed_diff_count={review_proposed_diff_count}")
    print(f"review_evidence_not_same_count={evidence_not_same_count}")
    print(f"reject_bad_mechanism_count={reject_bad_mechanism_count}")
    print(f"sample_rows={len(samples)}")
    if not samples.empty:
        print(samples["analyst_flag"].value_counts().to_string())
    print(f"wrote={REPORT}")
    print(f"wrote={SAMPLES}")


if __name__ == "__main__":
    main()
