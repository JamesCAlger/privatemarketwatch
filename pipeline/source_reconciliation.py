"""Row-level source reconciliation for BDC XBRL holdings.

The reconciliation compares investment-context facts from cached BDC XBRL
instances with rows published in ``private_markets_holdings.csv``.  It is
additive validation: it does not mutate unified holdings.
"""

from __future__ import annotations

import logging
import hashlib
import inspect
import time
from pathlib import Path
from typing import Any, Optional

import duckdb
import pandas as pd
from lxml import etree

from pipeline.bdc_filings import (
    _MONETARY_COLUMNS,
    _VALUE_COLUMNS,
    _local_name,
    _match_concept,
    _parse_fact_value,
    _parse_xbrl_contexts,
    _normalize_mixed_decimals_monetary_facts,
)
from pipeline.bdc_aggregate_overrides import (
    load_bdc_aggregate_overrides,
    resolve_bdc_aggregate_overrides_file,
)
from pipeline.bdc_identifier import (
    _AFFILIATION_PREFIX_RE,
    _AFFILIATION_SUFFIX_RE,
    _INVESTMENTS_HIERARCHY_RE,
    _sql_is_bdc_aggregate,
)
from pipeline.classification import (
    _BAD_ISSUER_ENTITY_SIGNALS,
    _BAD_ISSUER_NAMES_EXACT,
    _BAD_ISSUER_PREFIXES,
    _INDUSTRY_LABELS,
    _MONEY_MARKET_KEYWORDS,
    _sql_exact_match,
    _sql_keyword_check,
    _sql_starts_with_any,
)
from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_SOURCE_FACTS_CACHE_DIR,
    BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE,
    SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE,
    SOURCE_RECONCILIATION_CACHE_STATUS_FILE,
    SOURCE_RECONCILIATION_CALIBRATION_REVIEW_FILE,
    SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR,
    SOURCE_RECONCILIATION_DETAIL_FILE,
    SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR,
    SOURCE_RECONCILIATION_METRICS_FILE,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_MD_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLASSIFICATION_MD_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
    UNIFIED_HOLDINGS_FILE,
)

logger = logging.getLogger(__name__)

VALUE_COLUMNS = ["fair_value", "cost", "principal_amount", "shares_held"]
RATE_COLUMNS = ["interest_rate", "basis_spread", "pik_rate"]

DETAIL_COLUMNS = [
    "status", "match_tier", "issue_severity",
    "residual_class", "blocking_issue", "calibrated_status", "calibration_reason",
    "cik", "entity_name", "report_date", "period", "accession_number",
    "form_type", "filing_date", "context_id",
    "source_row_id", "output_row_id",
    "raw_investment_identifier", "normalized_investment_identifier",
    "dimensions_raw", "concept_names",
    "source_fair_value", "output_fair_value",
    "source_cost", "output_cost",
    "source_principal_amount", "output_principal_amount",
    "source_shares_held", "output_shares_held",
    "source_interest_rate", "output_interest_rate",
    "source_basis_spread", "output_basis_spread",
    "source_pik_rate", "output_pik_rate",
    "mismatched_fields", "issuer_name", "instrument_description",
    "index_classification", "asset_category", "issuer_category",
    "evidence",
]

METRIC_COLUMNS = [
    "cik", "entity_name", "report_date",
    "source_rows", "output_rows", "matched_rows",
    "missing_from_pipeline_rows", "extra_in_pipeline_rows",
    "value_mismatch_rows", "collapsed_duplicate_dimension_path_rows",
    "excluded_comparative_period_rows", "excluded_aggregate_candidate_rows",
    "documented_source_rollup_exact_rows",
    "excluded_no_fair_value_rows", "superseded_amendment_rows",
    "excluded_self_referential_subtotal_rows",
    "excluded_hierarchy_header_rows",
    "excluded_money_market_fund_rows",
    "excluded_bad_issuer_name_rows",
    "excluded_affiliation_dedup_rows",
    "blocking_issue_count", "diagnostic_issue_count",
    "calibrated_reconciled_source_row_rate",
    "strong_issue_count", "reconciled_source_row_rate",
    "reconciliation_status",
]

RESIDUAL_CLASSIFICATION_COLUMNS = [
    "classification_id",
    "cik", "entity_name", "report_date",
    "residual_class", "status", "calibrated_status", "match_tier", "blocking_issue",
    "mechanism",
    "confidence",
    "recommended_action",
    "issue_count",
    "affected_source_fair_value", "affected_output_fair_value",
    "sample_identifiers",
    "sample_accessions",
    "reason",
]

SOURCE_ONLY_DETAIL_COLUMNS = [
    "cik", "entity_name", "report_date", "period", "accession_number",
    "source_row_id", "raw_investment_identifier", "normalized_investment_identifier",
    "mechanism", "disposition", "is_blocking", "confidence", "rule_id",
    "source_fair_value", "evidence_reviewed", "hypotheses_tested",
    "why_not_cleared", "candidate_output_evidence", "recommended_action",
]

SOURCE_ONLY_CLUSTER_COLUMNS = [
    "cik", "entity_name", "report_date", "mechanism", "disposition",
    "accession_number", "row_count", "source_fair_value", "is_blocking",
    "confidence", "sample_identifiers", "rule_ids", "recommended_action",
]

STRONG_STATUSES = {"missing_from_pipeline", "extra_in_pipeline", "value_mismatch"}
INTENTIONAL_SOURCE_STATUSES = {
    "collapsed_duplicate_dimension_path",
    "excluded_comparative_period",
    "excluded_aggregate_candidate",
    "documented_source_rollup_exact",
    "excluded_no_fair_value",
    "superseded_amendment",
    "excluded_self_referential_subtotal",
    "excluded_hierarchy_header",
    "excluded_money_market_fund",
    "excluded_bad_issuer_name",
    "excluded_affiliation_dedup",
}

DOCUMENTED_MECHANISMS = {
    "excluded_comparative_period": "documented_comparative_period",
    "excluded_no_fair_value": "documented_no_fair_value",
    "excluded_aggregate_candidate": "documented_aggregate_candidate",
    "documented_source_rollup_exact": "documented_source_rollup_exact",
    "superseded_amendment": "documented_superseded_amendment",
    "collapsed_duplicate_dimension_path": "documented_duplicate_dimension_path",
    "excluded_self_referential_subtotal": "documented_self_referential_subtotal",
    "excluded_hierarchy_header": "documented_hierarchy_header",
    "excluded_money_market_fund": "documented_money_market_fund",
    "excluded_bad_issuer_name": "documented_bad_issuer_name",
    "excluded_affiliation_dedup": "documented_affiliation_dedup",
}

MECHANISM_RECOMMENDED_ACTIONS = {
    "documented_comparative_period": "Keep documented as non-blocking comparative-period source fact.",
    "documented_no_fair_value": "Keep documented as non-blocking source row without fair value.",
    "documented_aggregate_candidate": "Keep documented as non-blocking aggregate/header candidate.",
    "documented_source_rollup_exact": "Keep documented as non-blocking source rollup; monitor child-count and FV evidence.",
    "documented_superseded_amendment": "Keep documented as non-blocking superseded amendment.",
    "documented_duplicate_dimension_path": "Keep duplicate collapse under audit; verify only if counts move materially.",
    "documented_self_referential_subtotal": "Keep documented as non-blocking self-referential subtotal/hierarchy parent.",
    "documented_hierarchy_header": "Keep documented as non-blocking hierarchy/category header without entity signals.",
    "documented_money_market_fund": "Keep documented as non-blocking money market fund position filtered during staging.",
    "documented_bad_issuer_name": "Keep documented as non-blocking generic/bad issuer name filtered during staging.",
    "documented_affiliation_dedup": "Keep documented as non-blocking affiliation-axis duplicate of a matched position.",
    "diagnostic_secondary_field_mismatch": "Review secondary field extraction only if diagnostics cluster by filer.",
    "reconciled_identifier_normalization": "Keep as reconciled normalization; monitor for unexpected match-tier shifts.",
    "reconciled_issuer_name_extraction": "Keep as reconciled via issuer name extraction from raw identifier.",
    "reconciled_fv_only_identity": "Keep as reconciled via strict 1:1 fair-value identity match.",
    "reconciled_partial_name_fv": "Keep as reconciled via partial name token overlap plus fair-value match.",
    "blocking_numeric_identity_candidate": "Review numeric identity candidate; do not clear until source/output row identity is one-to-one.",
    "blocking_numeric_already_matched_output_alias": "Review numeric alias to an already matched output row; do not clear as a second match.",
    "blocking_numeric_multi_output_collision": "Review many-output numeric collision; require independent identity evidence before clearing.",
    "blocking_numeric_multi_source_collision": "Review many-source numeric collision; require independent identity evidence before clearing.",
    "blocking_source_only_position": "Fix extraction/filtering so eligible source position appears in unified holdings, or document an exclusion with evidence.",
    "documented_source_total_header": "Keep documented as non-blocking total/header source row; verify if source wording changes materially.",
    "documented_source_cash_or_money_market_bucket": "Keep documented as non-blocking cash or money-market bucket excluded from private-market holdings.",
    "documented_source_category_header": "Keep documented as non-blocking category header without entity or instrument-path evidence.",
    "documented_source_affiliation_header": "Keep documented as non-blocking affiliation hierarchy header without entity evidence.",
    "documented_source_country_industry_header": "Keep documented as non-blocking country/industry hierarchy header without entity evidence.",
    "documented_source_pct_total_header": "Keep documented as non-blocking terminal-percentage total/header row without leaf-position evidence.",
    "documented_source_pct_category_rollup": "Keep documented as non-blocking terminal-percentage category/geography/security-type rollup without leaf-position evidence.",
    "blocking_source_pct_leaf_parser_mismatch": "Fix parser/staging for terminal-percentage source rows with issuer, instrument, rate, maturity, or other leaf evidence.",
    "blocking_source_pct_ambiguous_after_review": "Escalate terminal-percentage source rows that lack safe rollup evidence and do not have enough leaf evidence to parse.",
    "blocking_source_pct_hierarchy_parser_mismatch": "Compatibility label only; new classifications should use split pct total, rollup, leaf, or ambiguous mechanisms.",
    "blocking_source_position_like_parser_mismatch": "Fix parser/staging for position-like source text; keep blocking until one-to-one source/output identity exists.",
    "blocking_source_short_plain_unresolved": "Review short plain identifier against the source filing; no deterministic clearing evidence exists.",
    "blocking_source_unclassifiable_after_review": "Escalate CIK-quarter source review; bounded deterministic review found no safe clearing mechanism.",
    "blocking_pipeline_only_position": "Trace pipeline row to cached source facts and fix stale, synthetic, or over-broad output rows.",
    "blocking_fair_value_scale_or_unit_candidate": "Investigate fair-value scale, unit, and decimal handling against the source filing.",
    "blocking_fair_value_disagreement": "Reconcile matched source/output fair value against the source filing and transformation path.",
    "blocking_identifier_parse_artifact": "Fix identifier parsing for this CIK-quarter before treating row identity as a true missing/extra position.",
    "blocking_row_identity_unclassified": "Perform CIK-quarter source review; no deterministic residual mechanism identified.",
}

MECHANISM_REASONS = {
    "documented_comparative_period": "Source row is from a comparative period, not the current report date.",
    "documented_no_fair_value": "Source row has no fair-value fact available for position reconciliation.",
    "documented_aggregate_candidate": "Source row matches aggregate/category wording and is intentionally excluded from position outputs.",
    "documented_source_rollup_exact": "Source row is a header/prefix rollup whose fair value exactly equals multiple child output positions.",
    "documented_superseded_amendment": "Source row belongs to a superseded amendment for the same CIK-quarter.",
    "documented_duplicate_dimension_path": "Equivalent economic fact appears on multiple source dimension paths and was collapsed.",
    "documented_self_referential_subtotal": "Source row is a self-referential subtotal whose identifier is a prefix of multiple child source rows.",
    "documented_hierarchy_header": "Source row is a hierarchy/category header lacking entity signals (LLC, Inc, Corp, etc.).",
    "documented_money_market_fund": "Source row is a money market fund position filtered during BDC staging.",
    "documented_bad_issuer_name": "Source row has a generic/bad issuer name (e.g. 'Investments', 'First Lien Debt') filtered during staging.",
    "documented_affiliation_dedup": "Source row is an affiliation-axis duplicate of another source row that matched to output.",
    "diagnostic_secondary_field_mismatch": "Matched row has a non-fair-value field mismatch tracked as diagnostic.",
    "reconciled_identifier_normalization": "Source and output reconciled through deterministic identifier normalization rather than exact dimensions.",
    "reconciled_issuer_name_extraction": "Source row reconciled to output via issuer name extraction from raw identifier.",
    "reconciled_fv_only_identity": "Source row reconciled to output via strict 1:1 fair-value-only identity match.",
    "reconciled_partial_name_fv": "Source row reconciled to output via partial name token overlap and fair-value match.",
    "blocking_numeric_identity_candidate": "Source/output row has matching fair value and cost, but numeric identity is ambiguous or points to an already matched output row.",
    "blocking_numeric_already_matched_output_alias": "Numeric evidence points to an output row already reconciled by stronger source identity.",
    "blocking_numeric_multi_output_collision": "One source row has matching numeric facts against multiple output rows.",
    "blocking_numeric_multi_source_collision": "Multiple source rows have matching numeric facts against the same output row.",
    "blocking_source_only_position": "Eligible source position has no matching pipeline output row.",
    "documented_source_total_header": "Source-only row is an exact total/subtotal header rather than a position-level holding.",
    "documented_source_cash_or_money_market_bucket": "Source-only row is a cash, cash-equivalent, or money-market bucket intentionally outside private-market holdings.",
    "documented_source_category_header": "Source-only row is a category header lacking entity and position-level instrument signals.",
    "documented_source_affiliation_header": "Source-only row is an affiliation hierarchy header lacking entity and instrument signals.",
    "documented_source_country_industry_header": "Source-only row is a country/industry hierarchy header lacking entity and position-level instrument signals.",
    "documented_source_pct_total_header": "Source-only row is a terminal-percentage total/header row without leaf-position evidence.",
    "documented_source_pct_category_rollup": "Source-only row is a terminal-percentage category/geography/security-type rollup without leaf-position evidence.",
    "blocking_source_pct_leaf_parser_mismatch": "Source-only terminal-percentage row has issuer, instrument, rate, maturity, or other leaf-position evidence.",
    "blocking_source_pct_ambiguous_after_review": "Source-only terminal-percentage row remains ambiguous after strict total/rollup and leaf-signal checks.",
    "blocking_source_pct_hierarchy_parser_mismatch": "Compatibility label only; new classifications should use split pct total, rollup, leaf, or ambiguous mechanisms.",
    "blocking_source_position_like_parser_mismatch": "Source-only row has company, instrument, legal suffix, rate, maturity, or other position-like evidence.",
    "blocking_source_short_plain_unresolved": "Source-only row is short and plain, but lacks enough deterministic evidence to clear or parse.",
    "blocking_source_unclassifiable_after_review": "Source-only row remains ambiguous after bounded deterministic review and is retained as blocking.",
    "blocking_pipeline_only_position": "Pipeline BDC position has no matching current-period source fact.",
    "blocking_fair_value_scale_or_unit_candidate": "Matched source/output fair values differ by an extreme ratio consistent with possible scale or unit error.",
    "blocking_fair_value_disagreement": "Matched source/output fair values differ materially without an extreme scale ratio.",
    "blocking_identifier_parse_artifact": "Row identity residual appears driven by date, placeholder, category-only, or raw dimension-text identifiers.",
    "blocking_row_identity_unclassified": "Blocking row-identity residual lacks a stronger deterministic mechanism.",
}


def _empty_detail() -> pd.DataFrame:
    return pd.DataFrame(columns=DETAIL_COLUMNS)


def _empty_metrics() -> pd.DataFrame:
    return pd.DataFrame(columns=METRIC_COLUMNS)


def _empty_residual_classification() -> pd.DataFrame:
    return pd.DataFrame(columns=RESIDUAL_CLASSIFICATION_COLUMNS)


def _empty_source_only_detail() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_ONLY_DETAIL_COLUMNS)


def _empty_source_only_clusters() -> pd.DataFrame:
    return pd.DataFrame(columns=SOURCE_ONLY_CLUSTER_COLUMNS)


def _bool_series(value: bool, index: pd.Index) -> pd.Series:
    return pd.Series(value, index=index, dtype=bool)


def build_source_only_blocker_detail(detail_df: pd.DataFrame) -> pd.DataFrame:
    """Classify source-only BDC blockers with deterministic evidence buckets.

    This is an additive audit artifact.  It does not mutate
    ``source_reconciliation_detail.csv`` and it deliberately keeps ambiguous or
    position-like rows blocking.
    """
    if detail_df.empty:
        return _empty_source_only_detail()

    df = detail_df.copy()
    for col in DETAIL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    if "_source_detail_row_id" not in df.columns:
        df["_source_detail_row_id"] = range(len(df))
    df["blocking_issue"] = df["blocking_issue"].astype(str).str.lower().isin(
        ["true", "1", "yes"]
    )
    df["source_fair_value"] = pd.to_numeric(df["source_fair_value"], errors="coerce")

    source_only = df[
        df["status"].astype(str).eq("missing_from_pipeline")
        & df["blocking_issue"]
    ].copy()
    if source_only.empty:
        return _empty_source_only_detail()

    raw = source_only["raw_investment_identifier"].fillna("").astype(str).str.strip()
    raw_lower = raw.str.lower()
    normalized = (
        raw_lower.str.replace(r"[^a-z0-9]+", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    dimensions_lower = source_only["dimensions_raw"].fillna("").astype(str).str.lower()
    evidence_lower = source_only["evidence"].fillna("").astype(str).str.lower()

    numeric_alias = evidence_lower.str.contains(
        "blocking numeric identity candidate", regex=False, na=False
    )
    entity_text = raw_lower.str.replace(
        r"\bportfolio company investments?\b|\bportfolio company\b",
        " ",
        regex=True,
    )
    entity_signal = entity_text.str.contains(
        r"\b(inc|inc\.|llc|l\.l\.c\.|corp|corp\.|corporation|co\.|company|ltd|"
        r"limited|lp|l\.p\.|llp|holdings?|holding|partners?|partnership|"
        r"borrower|buyer|issuer|parent|opco|topco|midco|fund|trust|plc|sa|ag|gmbh)\b",
        regex=True,
        na=False,
    )
    position_signal = raw_lower.str.contains(
        r"\b(first lien|second lien|unitranche|term loan|delayed draw|revolver|"
        r"revolving|senior secured|subordinated|notes?|bonds?|debenture|common stock|"
        r"preferred|warrants?|shares?|equity|class [a-z]|sofr|libor|euribor|pik|"
        r"maturity|matures|interest rate|reference rate|spread|acquisition date|"
        r"commitment type)\b",
        regex=True,
        na=False,
    )
    pct_or_rate_signal = raw_lower.str.contains(
        r"(\d+(?:\.\d+)?\s*%|\bsofr\b|\blibor\b|\beuribor\b|\bs\s*\+\s*\d|"
        r"\be\s*\+\s*\d|\bmaturity\b|\binterest rate\b)",
        regex=True,
        na=False,
    )
    terminal_pct = raw_lower.str.contains(
        r"(?:[\s(,\-]*-?\d+(?:\.\d+)?\s*%\)?(?:\s+of\s+net\s+assets)?\s*)$",
        regex=True,
        na=False,
    )
    pct_total_header = (
        terminal_pct
        & ~entity_signal
        & raw_lower.str.match(
            r"^(total|subtotal|net assets?|total net assets?|total investments?|"
            r"total portfolio|portfolio total|investments? total|"
            r"cash and investments|investments)\b",
            na=False,
        )
    )
    pct_leaf_signal = (
        entity_signal
        | raw_lower.str.contains(
            r"\b(investment\s+type|interest\s+rate|reference\s+rate|spread|"
            r"maturity|matures|maturity\s*/\s*dissolution|sofr|libor|euribor|"
            r"term\s+loan|delayed\s+draw|revolver|revolving|notes?|bonds?|"
            r"common\s+equity|preferred|warrants?|par\s+(amount|value)|"
            r"principal\s+amount|acquisition\s+date)\b",
            regex=True,
            na=False,
        )
    )
    pct_category_rollup_text = raw_lower.str.contains(
        r"\b(investments?|debt|equity|securities|first\s+lien|1st\s+lien|"
        r"second\s+lien|2nd\s+lien|senior\s+secured|subordinated|unsecured|"
        r"non[-\s]?controlled|non[-\s]?affiliated|controlled|affiliated|"
        r"united\s+states|united\s+kingdom|canada|netherlands|france|germany|"
        r"industry|industries|software|health\s*care|healthcare|financials?|"
        r"industrials?|energy|consumer|business\s+services|technology|media|"
        r"telecommunications|capital\s+goods|commercial)\b",
        regex=True,
        na=False,
    )
    long_hierarchy = (
        raw.str.len().ge(90)
        | raw_lower.str.contains(r"\binvestment type\b", regex=True, na=False)
        | dimensions_lower.str.contains("axis", regex=False, na=False)
    )
    no_entity_or_position = ~(entity_signal | position_signal | pct_or_rate_signal)
    no_leaf_position_detail = ~(
        entity_signal
        | pct_or_rate_signal
        | raw_lower.str.contains(
            r"\b(company|issuer\s+name|investment\s+type|type\s+of\s+investment|"
            r"initial\s+acquisition\s+date|acquisition\s+date|principal\s+amount|"
            r"par\s+(amount|value)|shares?|units?)\b",
            regex=True,
            na=False,
        )
    )

    total_header = (
        ~entity_signal
        & ~terminal_pct
        & (
            raw_lower.str.match(
                r"^(total|subtotal)\s+("
                r"investments?|portfolio investments?|debt investments?|equity investments?|"
                r"cash equivalents?|cash and investments?|cash and cash equivalents|"
                r"assets?|net assets?|liabilities|unfunded commitments?|commitments?|"
                r"affiliates?|affiliate investments?|control investments?|non control non affiliate investments?"
                r")(\s+at fair value)?"
                r"(\s*[\u2014-]\s*(non[-\s]?controlled/non[-\s]?affiliated|"
                r"non[-\s]?controlled\s+non[-\s]?affiliated|"
                r"non[-\s]?control/non[-\s]?affiliate))?"
                r"(\s*[\u2014-]?\s*\(?-?\d+(?:\.\d+)?%\)?)?$",
                na=False,
            )
            | normalized.str.match(
                r"^investments\s+non\s+controlled\s+non\s+affiliated\s+total\s+unfunded\s+commitments?$",
                na=False,
            )
            | normalized.str.match(
                r"^investments\s+total\s+investments\s+non\s+controlled\s+non\s+affiliat(?:e|ed)$",
                na=False,
            )
        )
    )
    total_pipe_segment = (
        ~entity_signal
        & raw_lower.str.contains(r"\|", regex=True, na=False)
        & raw_lower.str.contains(r"(^|\|)\s*total\s+[^|]+", regex=True, na=False)
        & ~raw_lower.str.contains(
            r"\b(total\s+\w+\s+(inc|inc\.|llc|corp|corp\.|ltd|holdings|group))\b",
            regex=True,
            na=False,
        )
    )
    cash_bucket = (
        ~numeric_alias
        & raw_lower.str.contains(
            r"\b(cash equivalents?|cash and cash equivalents|restricted cash|"
            r"money market|institutional liquidity|treasury portfolio|"
            r"government institutional fund|financial square government|mmda)\b",
            regex=True,
            na=False,
        )
        & ~raw_lower.str.contains(
            r"\b(private equity fund|limited partnership|lp interest|fund interest)\b",
            regex=True,
            na=False,
        )
    )
    affiliation_header = (
        no_entity_or_position
        & normalized.str.match(
            r"^(affiliate|affiliated|control|controlled|non controlled|"
            r"non control|non affiliated|non affiliate|non controlled non affiliated|"
            r"control and affiliate)(\s+portfolio company)?\s+investments?$",
            na=False,
        )
    )
    hierarchy_header_without_entity = (
        ~entity_signal
        & ~pct_or_rate_signal
        & ~raw_lower.str.contains(r"\binvestment type\b|\bmaturity\b|\binterest rate\b", regex=True, na=False)
    )
    category_header = (
        hierarchy_header_without_entity
        & normalized.str.contains(
            r"\b(debt investments?|equity investments?|first lien debt investments?|"
            r"second lien debt investments?|senior secured loans?|subordinated debt|"
            r"unsecured loans?|preferred equity|common equity|warrants?|software|"
            r"health care|healthcare|financials?|industrials?|energy|consumer|"
            r"business services|technology|media|telecommunications|"
            r"commercial services( and supplies)?|high tech industries|"
            r"services business|services consumer|chemicals( plastics? and rubber)?)\b",
            regex=True,
            na=False,
        )
    )
    category_instrument_rollup = (
        ~numeric_alias
        & ~terminal_pct
        & no_leaf_position_detail
        & raw_lower.str.contains(
            r"\b(first\s+lien|1st\s+lien|second\s+lien|2nd\s+lien|"
            r"senior\s+secured|subordinated|unsecured|mezzanine|unitranche|"
            r"common\s+equity|preferred\s+equity|warrants?|equity\s+interest|"
            r"trust\s+interest|corporate\s+bond|secured\s+loans?|secured\s+bonds?)\b",
            regex=True,
            na=False,
        )
        & raw_lower.str.contains(
            r"\b(investments?|controlled|affiliated|non[-\s]?controlled|"
            r"non[-\s]?affiliated|industry|industries|total|debt|equity|"
            r"materials|insurance|manufacturing|wholesale|retail|automotive|"
            r"beverage|construction|building|transportation|advertising|"
            r"printing|publishing|finance|real\s+estate|hotel|gaming|leisure|"
            r"software|health\s*care|healthcare|commercial|services|"
            r"capital\s+equipment|containers|packaging|glass)\b",
            regex=True,
            na=False,
        )
    )
    country_industry_header = (
        hierarchy_header_without_entity
        & (
            raw_lower.isin(_INDUSTRY_LABELS)
            | raw_lower.str.match(r"^investments\s+[a-z][a-z\s,&/-]{2,80}\s+(debt|equity)\s+investments", na=False)
        )
    )
    pct_total_documented = (
        ~numeric_alias
        & pct_total_header
        & ~pct_leaf_signal
        & ~cash_bucket
    )
    pct_category_rollup = (
        ~numeric_alias
        & terminal_pct
        & ~pct_total_documented
        & ~pct_leaf_signal
        & ~cash_bucket
        & pct_category_rollup_text
    )
    pct_leaf_parser = (
        ~numeric_alias
        & terminal_pct
        & pct_leaf_signal
        & ~pct_total_documented
        & ~pct_category_rollup
        & ~cash_bucket
    )
    pct_ambiguous = (
        ~numeric_alias
        & terminal_pct
        & ~pct_total_documented
        & ~pct_category_rollup
        & ~pct_leaf_parser
        & ~cash_bucket
    )
    non_terminal_pct_or_rate_hierarchy = (
        ~numeric_alias
        & pct_or_rate_signal
        & ~terminal_pct
        & long_hierarchy
        & ~total_header
        & ~cash_bucket
    )
    position_like_parser = (
        ~numeric_alias
        & (entity_signal | position_signal)
        & ~terminal_pct
        & ~total_header
        & ~cash_bucket
        & ~affiliation_header
        & ~category_header
        & ~category_instrument_rollup
        & ~country_industry_header
    )
    short_plain = (
        ~numeric_alias
        & raw.str.len().between(1, 45)
        & ~entity_signal
        & ~position_signal
        & ~pct_or_rate_signal
        & ~total_header
        & ~cash_bucket
        & ~affiliation_header
        & ~category_header
        & ~category_instrument_rollup
        & ~country_industry_header
    )

    source_only["mechanism"] = "blocking_source_unclassifiable_after_review"
    source_only["rule_id"] = "SRCONLY_UNCLASSIFIABLE_BOUNDED_REVIEW"
    source_only["confidence"] = "medium"
    source_only["disposition"] = "blocking_reviewed_unresolved"
    source_only["is_blocking"] = True

    def assign(mask: pd.Series, mechanism: str, rule_id: str, confidence: str, blocking: bool) -> None:
        open_mask = source_only["mechanism"].eq("blocking_source_unclassifiable_after_review")
        source_only.loc[mask & open_mask, "mechanism"] = mechanism
        source_only.loc[mask & open_mask, "rule_id"] = rule_id
        source_only.loc[mask & open_mask, "confidence"] = confidence
        source_only.loc[mask & open_mask, "is_blocking"] = blocking
        source_only.loc[mask & open_mask, "disposition"] = (
            "documented_non_position_exclusion" if not blocking else "blocking_parser_or_review_residual"
        )

    assign(
        numeric_alias,
        "blocking_numeric_already_matched_output_alias",
        "SRCONLY_NUMERIC_ALIAS_PRESERVE",
        "medium",
        True,
    )
    assign(total_header, "documented_source_total_header", "SRCONLY_TOTAL_HEADER_EXACT", "high", False)
    assign(total_pipe_segment, "documented_source_total_header", "SRCONLY_TOTAL_PIPE_HEADER", "high", False)
    assign(cash_bucket, "documented_source_cash_or_money_market_bucket", "SRCONLY_CASH_MM_BUCKET", "high", False)
    assign(affiliation_header, "documented_source_affiliation_header", "SRCONLY_AFFILIATION_HEADER", "high", False)
    assign(country_industry_header, "documented_source_country_industry_header", "SRCONLY_COUNTRY_INDUSTRY_HEADER", "high", False)
    assign(category_header, "documented_source_category_header", "SRCONLY_CATEGORY_HEADER", "high", False)
    assign(category_instrument_rollup, "documented_source_category_header", "SRCONLY_CATEGORY_INSTRUMENT_ROLLUP", "high", False)
    assign(pct_total_documented, "documented_source_pct_total_header", "SRCONLY_PCT_TOTAL_HEADER", "high", False)
    assign(pct_category_rollup, "documented_source_pct_category_rollup", "SRCONLY_PCT_CATEGORY_ROLLUP", "high", False)
    assign(pct_leaf_parser, "blocking_source_pct_leaf_parser_mismatch", "SRCONLY_PCT_LEAF_PARSER", "medium", True)
    assign(pct_ambiguous, "blocking_source_pct_ambiguous_after_review", "SRCONLY_PCT_AMBIGUOUS_REVIEW", "medium", True)
    assign(non_terminal_pct_or_rate_hierarchy, "blocking_source_pct_leaf_parser_mismatch", "SRCONLY_PCT_OR_RATE_LEAF_PARSER", "medium", True)
    assign(position_like_parser, "blocking_source_position_like_parser_mismatch", "SRCONLY_POSITION_LIKE_PARSER", "medium", True)
    assign(short_plain, "blocking_source_short_plain_unresolved", "SRCONLY_SHORT_PLAIN_UNRESOLVED", "low", True)

    source_only["recommended_action"] = source_only["mechanism"].map(
        MECHANISM_RECOMMENDED_ACTIONS
    ).fillna("Review source-only residual.")
    source_only["evidence_reviewed"] = (
        "cached XBRL row identifier, dimensions, source FV, reconciliation evidence, "
        "numeric alias evidence, and deterministic entity/header/instrument signals"
    )
    source_only["hypotheses_tested"] = (
        "numeric alias; total/subtotal header; cash or money-market bucket; "
        "affiliation/category/country-industry header; percentage total/header; "
        "percentage category rollup; percentage leaf parser mismatch; percentage ambiguous review; "
        "position-like parser mismatch; short plain unresolved identifier"
    )
    source_only["why_not_cleared"] = source_only["mechanism"].map({
        "documented_source_total_header": "cleared as documented non-position total/header row",
        "documented_source_cash_or_money_market_bucket": "cleared as documented cash or money-market bucket outside private-market output",
        "documented_source_category_header": "cleared as documented category header without entity or instrument-path evidence",
        "documented_source_affiliation_header": "cleared as documented affiliation header without entity or instrument evidence",
        "documented_source_country_industry_header": "cleared as documented country/industry hierarchy header without entity evidence",
        "documented_source_pct_total_header": "cleared as documented terminal-percentage total/header row without leaf-position evidence",
        "documented_source_pct_category_rollup": "cleared as documented terminal-percentage rollup without leaf-position evidence",
        "blocking_numeric_already_matched_output_alias": "numeric evidence points to an already matched output row; many-to-one clearing is unsafe",
        "blocking_source_pct_leaf_parser_mismatch": "terminal-percentage or rate-bearing source text has leaf-position evidence; no one-to-one output identity found",
        "blocking_source_pct_ambiguous_after_review": "terminal-percentage source text lacks safe rollup evidence; retained as blocking pending review",
        "blocking_source_pct_hierarchy_parser_mismatch": "legacy percentage/rate hierarchy bucket retained only for compatibility",
        "blocking_source_position_like_parser_mismatch": "company or instrument signals indicate a likely position; no one-to-one output identity found",
        "blocking_source_short_plain_unresolved": "identifier is too sparse to classify safely without source filing review",
        "blocking_source_unclassifiable_after_review": "bounded deterministic review found no safe non-position or parser mechanism",
    }).fillna("not cleared by deterministic source-only review")
    source_only["candidate_output_evidence"] = source_only["evidence"].fillna("").astype(str)

    columns = SOURCE_ONLY_DETAIL_COLUMNS
    for col in columns:
        if col not in source_only.columns:
            source_only[col] = ""
    return source_only[columns].sort_values(
        ["is_blocking", "cik", "report_date", "mechanism", "raw_investment_identifier"],
        ascending=[False, True, True, True, True],
    )


def build_source_only_blocker_clusters(source_only_detail_df: pd.DataFrame) -> pd.DataFrame:
    """Group classified source-only blockers into CIK-quarter work packets."""
    if source_only_detail_df.empty:
        return _empty_source_only_clusters()
    df = source_only_detail_df.copy()
    df["source_fair_value"] = pd.to_numeric(df["source_fair_value"], errors="coerce").fillna(0)
    df["is_blocking"] = df["is_blocking"].astype(str).str.lower().isin(["true", "1", "yes"])
    con = duckdb.connect()
    con.register("source_only", df)
    clusters = con.execute("""
        SELECT
            cik,
            any_value(entity_name) AS entity_name,
            report_date,
            mechanism,
            any_value(disposition) AS disposition,
            COALESCE(accession_number, '') AS accession_number,
            COUNT(*) AS row_count,
            SUM(source_fair_value) AS source_fair_value,
            bool_or(is_blocking) AS is_blocking,
            any_value(confidence) AS confidence,
            array_to_string(
                list(DISTINCT raw_investment_identifier ORDER BY raw_investment_identifier)
                    FILTER (WHERE COALESCE(raw_investment_identifier, '') != '')[:5],
                ' | '
            ) AS sample_identifiers,
            array_to_string(
                list(DISTINCT rule_id ORDER BY rule_id)
                    FILTER (WHERE COALESCE(rule_id, '') != '')[:5],
                ' | '
            ) AS rule_ids,
            any_value(recommended_action) AS recommended_action
        FROM source_only
        GROUP BY cik, report_date, mechanism, accession_number
        ORDER BY is_blocking DESC, row_count DESC, cik, report_date, mechanism
    """).fetchdf()
    con.close()
    return clusters[SOURCE_ONLY_CLUSTER_COLUMNS]


def build_source_only_blocker_markdown(
    source_only_detail_df: pd.DataFrame,
    source_only_clusters_df: pd.DataFrame,
) -> str:
    """Build readable source-only classification summary."""
    lines = [
        "# Source-Only BDC Blocker Classification",
        "",
        "This artifact classifies source rows missing from unified holdings. "
        "Documented non-position mechanisms are separated from parser defects and "
        "reviewed unresolved blockers; ambiguous rows remain blocking.",
        "",
    ]
    if source_only_detail_df.empty:
        lines.extend(["No source-only blockers were found.", ""])
        return "\n".join(lines)

    detail = source_only_detail_df.copy()
    clusters = source_only_clusters_df.copy()
    detail["source_fair_value"] = pd.to_numeric(detail["source_fair_value"], errors="coerce").fillna(0)
    detail["is_blocking"] = detail["is_blocking"].astype(str).str.lower().isin(["true", "1", "yes"])
    clusters["source_fair_value"] = pd.to_numeric(clusters["source_fair_value"], errors="coerce").fillna(0)
    clusters["row_count"] = pd.to_numeric(clusters["row_count"], errors="coerce").fillna(0)
    clusters["is_blocking"] = clusters["is_blocking"].astype(str).str.lower().isin(["true", "1", "yes"])
    pct_rollup_mask = detail["mechanism"].isin([
        "documented_source_pct_total_header",
        "documented_source_pct_category_rollup",
    ])
    pct_leaf_mask = detail["mechanism"].eq("blocking_source_pct_leaf_parser_mismatch")
    pct_ambiguous_mask = detail["mechanism"].eq("blocking_source_pct_ambiguous_after_review")

    lines.extend([
        "## Totals",
        "",
        f"- Source-only rows reviewed: {len(detail)}",
        f"- Blocking rows after classification: {int(detail['is_blocking'].sum())}",
        f"- Documented non-position rows: {int((~detail['is_blocking']).sum())}",
        f"- Source FV reviewed: {detail['source_fair_value'].sum():,.0f}",
        f"- Terminal-pct documented rollup/header rows: {int(pct_rollup_mask.sum())}",
        f"- Terminal-pct documented rollup/header FV: {detail.loc[pct_rollup_mask, 'source_fair_value'].sum():,.0f}",
        f"- Terminal-pct leaf parser rows: {int(pct_leaf_mask.sum())}",
        f"- Terminal-pct leaf parser FV: {detail.loc[pct_leaf_mask, 'source_fair_value'].sum():,.0f}",
        f"- Terminal-pct ambiguous blocking rows: {int(pct_ambiguous_mask.sum())}",
        f"- Terminal-pct ambiguous blocking FV: {detail.loc[pct_ambiguous_mask, 'source_fair_value'].sum():,.0f}",
        "",
        "## Mechanisms",
        "",
        "| Mechanism | Rows | Blocking Rows | Source FV |",
        "| --- | ---: | ---: | ---: |",
    ])
    by_mechanism = (
        detail.groupby("mechanism", dropna=False)
        .agg(
            rows=("mechanism", "count"),
            blocking_rows=("is_blocking", "sum"),
            source_fv=("source_fair_value", "sum"),
        )
        .reset_index()
        .sort_values(["blocking_rows", "rows", "mechanism"], ascending=[False, False, True])
    )
    for row in by_mechanism.to_dict("records"):
        lines.append(
            f"| {row['mechanism']} | {int(row['rows'])} | "
            f"{int(row['blocking_rows'])} | {row['source_fv']:,.0f} |"
        )

    sections = [
        ("Top CIK Work Packets", clusters[clusters["is_blocking"]]),
        (
            "Pct Leaf Parser Queue",
            clusters[clusters["mechanism"].eq("blocking_source_pct_leaf_parser_mismatch")],
        ),
        (
            "Pct Rollup/Header Exclusions",
            clusters[clusters["mechanism"].isin([
                "documented_source_pct_total_header",
                "documented_source_pct_category_rollup",
            ])],
        ),
        ("Documented Exclusions", clusters[~clusters["is_blocking"]]),
        (
            "Parser-Mismatch Clusters",
            clusters[clusters["mechanism"].astype(str).str.contains("parser_mismatch", na=False)],
        ),
        (
            "Unclassifiable After Review",
            clusters[clusters["mechanism"].eq("blocking_source_unclassifiable_after_review")],
        ),
    ]
    for title, frame in sections:
        lines.extend(["", f"## {title}", ""])
        if frame.empty:
            lines.extend(["None.", ""])
            continue
        lines.extend([
            "| CIK | Entity | Report Date | Mechanism | Rows | Source FV | Samples | Recommended Action |",
            "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
        ])
        for row in frame.sort_values(
            ["row_count", "source_fair_value", "cik", "report_date"],
            ascending=[False, False, True, True],
        ).head(25).to_dict("records"):
            lines.append(
                f"| {row['cik']} | {row['entity_name']} | {row['report_date']} | "
                f"{row['mechanism']} | {int(row['row_count'])} | "
                f"{row['source_fair_value']:,.0f} | {row['sample_identifiers']} | "
                f"{row['recommended_action']} |"
            )
    lines.append("")
    return "\n".join(lines)


def _norm_identifier_sql(expr: str) -> str:
    return (
        "regexp_replace(lower(trim(COALESCE(CAST("
        + expr
        + " AS VARCHAR), ''))), '[^a-z0-9]+', ' ', 'g')"
    )


def _staging_clean_identifier_sql(expr: str) -> str:
    """Mirror BDC staging's deterministic prefix/suffix identifier cleanup."""
    return f"""
        regexp_replace(
            regexp_replace(
                regexp_replace(
                    COALESCE(CAST({expr} AS VARCHAR), ''),
                    '{_AFFILIATION_PREFIX_RE}',
                    ''
                ),
                '{_AFFILIATION_SUFFIX_RE}',
                ''
            ),
            '{_INVESTMENTS_HIERARCHY_RE}',
            ''
        )
    """


def _money_market_check_sql(col: str) -> str:
    """Generate SQL boolean for money market fund detection on source identifier."""
    return _sql_keyword_check(col, _MONEY_MARKET_KEYWORDS)


def _bad_issuer_name_sql(col: str) -> str:
    """Generate SQL boolean for bad/generic issuer name detection on source identifier."""
    stripped = (
        f"lower(TRIM(TRAILING ',' FROM TRIM(TRAILING ';' FROM trim(CAST({col} AS VARCHAR)))))"
    )
    parts = []
    parts.append(_sql_exact_match(stripped, _BAD_ISSUER_NAMES_EXACT))
    parts.append(
        f"(LENGTH(trim(CAST({col} AS VARCHAR))) >= 1"
        f" AND NOT regexp_matches(trim(CAST({col} AS VARCHAR)), '[a-zA-Z]'))"
    )
    prefix_check = _sql_starts_with_any(stripped, _BAD_ISSUER_PREFIXES)
    entity_guards = " AND ".join(
        f"NOT contains({stripped}, '{s}')" for s in _BAD_ISSUER_ENTITY_SIGNALS
    )
    parts.append(f"({prefix_check} AND {entity_guards})")
    return " OR ".join(f"({p})" for p in parts)


def _material_mismatch_sql(source_expr: str, output_expr: str) -> str:
    return f"""
        CASE
            WHEN {source_expr} IS NULL AND {output_expr} IS NULL THEN false
            WHEN {source_expr} IS NULL OR {output_expr} IS NULL THEN true
            WHEN abs({source_expr} - {output_expr}) >
                 greatest(1.0, 0.0001 * greatest(abs({source_expr}), abs({output_expr})))
                 THEN true
            ELSE false
        END
    """


def _coerce_source_df(source_df: pd.DataFrame) -> pd.DataFrame:
    df = source_df.copy()
    required = [
        "cik", "entity_name", "report_date", "period", "accession_number",
        "form_type", "filing_date", "context_id", "investment_identifier",
        "dimensions_raw", "concept_names", "maturity_date",
        *_VALUE_COLUMNS,
    ]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    for col in [*VALUE_COLUMNS, *RATE_COLUMNS]:
        if col not in df.columns:
            df[col] = ""
    df["source_row_id"] = range(len(df))
    return df


def _coerce_output_df(holdings_df: pd.DataFrame) -> pd.DataFrame:
    df = holdings_df.copy()
    required = [
        "source", "cik", "entity_name", "report_date", "period",
        "accession_number", "filing_date", "bdc_form_type",
        "bdc_investment_identifier", "bdc_dimensions_raw",
        "issuer_name", "instrument_description", "index_classification",
        "asset_category", "issuer_category", "maturity_date",
        "fair_value", "cost", "principal_amount", "shares_held",
        "interest_rate", "basis_spread", "pik_rate",
    ]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    df = df[df["source"].astype(str).str.lower().eq("bdc")].copy()
    df["output_row_id"] = range(len(df))
    return df


def extract_bdc_source_facts_from_xbrl(
    filings_index_df: Optional[pd.DataFrame] = None,
    filings_index_path: Optional[Path] = None,
) -> pd.DataFrame:
    """Extract BDC investment-context source facts from cached XBRL files."""
    if filings_index_df is None:
        index_path = filings_index_path or BDC_FILINGS_INDEX_FILE
        if not index_path.exists():
            logger.warning("BDC filings index not found: %s", index_path)
            return pd.DataFrame()
        filings_index_df = pd.read_csv(index_path, dtype=str)

    if filings_index_df.empty or "xbrl_local_path" not in filings_index_df.columns:
        return pd.DataFrame()

    records: list[dict[str, Any]] = []
    for _, filing in filings_index_df.iterrows():
        xml_path = str(filing.get("xbrl_local_path", "") or "").strip()
        if not xml_path:
            continue
        path = Path(xml_path)
        if not path.exists():
            continue
        records.extend(_extract_single_xbrl_source_file(path, filing.to_dict()))

    return pd.DataFrame(records)


def _extract_single_xbrl_source_file(
    xml_path: Path,
    filing_meta: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        tree = etree.parse(str(xml_path))
    except Exception as exc:
        logger.debug("Source reconciliation XML parse failed for %s: %s", xml_path, exc)
        return []

    contexts = _parse_xbrl_contexts(tree)
    investment_contexts = {
        cid: info for cid, info in contexts.items() if info.get("is_investment")
    }
    if not investment_contexts:
        return []

    facts_by_ctx: dict[str, dict[str, Any]] = {}
    concepts_by_ctx: dict[str, set[str]] = {}
    monetary_facts_stored: list[tuple[str, str, int]] = []
    root = tree.getroot()
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref not in investment_contexts:
            continue
        raw_text = (elem.text or "").strip()
        if not raw_text:
            continue
        local = _local_name(elem.tag)
        col = _match_concept(local.lower())
        if col is None:
            continue
        value = _parse_fact_value(col, raw_text)
        facts_by_ctx.setdefault(ctx_ref, {})
        if col not in facts_by_ctx[ctx_ref] or facts_by_ctx[ctx_ref][col] in (None, ""):
            facts_by_ctx[ctx_ref][col] = value
            if col in _MONETARY_COLUMNS and isinstance(value, (int, float)):
                dec_attr = elem.get("decimals")
                if dec_attr is not None:
                    try:
                        monetary_facts_stored.append((ctx_ref, col, int(dec_attr)))
                    except ValueError:
                        pass
        concepts_by_ctx.setdefault(ctx_ref, set()).add(local)

    _normalize_mixed_decimals_monetary_facts(facts_by_ctx, monetary_facts_stored)

    rows: list[dict[str, Any]] = []
    for ctx_id, ctx_info in investment_contexts.items():
        fact_vals = facts_by_ctx.get(ctx_id, {})
        if not fact_vals:
            continue
        row = {
            "cik": filing_meta.get("cik", ""),
            "entity_name": filing_meta.get("entity_name", ""),
            "accession_number": filing_meta.get("accession_number", ""),
            "form_type": filing_meta.get("form_type", ""),
            "filing_date": filing_meta.get("filing_date", ""),
            "report_date": filing_meta.get("report_date", ""),
            "context_id": ctx_id,
            "period": ctx_info.get("period", ""),
            "investment_identifier": ctx_info.get("investment_identifier", ""),
            "industry": ctx_info.get("industry", ""),
            "investment_type": ctx_info.get("investment_type", ""),
            "affiliation": ctx_info.get("affiliation", ""),
            "dimensions_raw": ctx_info.get("dimensions_raw", ""),
            "concept_names": "|".join(sorted(concepts_by_ctx.get(ctx_id, set()))),
        }
        for col in _VALUE_COLUMNS:
            row[col] = fact_vals.get(col)
        rows.append(row)
    return rows


def reconcile_bdc_source_to_holdings(
    source_df: pd.DataFrame,
    holdings_df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reconcile BDC source facts to unified BDC holdings rows."""
    if source_df.empty and holdings_df.empty:
        return _empty_detail(), _empty_metrics()

    source = _coerce_source_df(source_df)
    output = _coerce_output_df(holdings_df)
    con = duckdb.connect()
    con.register("source_raw", source)
    con.register("output_raw", output)
    aggregate_overrides = load_bdc_aggregate_overrides()
    con.register("bdc_aggregate_overrides", aggregate_overrides)
    agg_filter = (
        _sql_is_bdc_aggregate()
        .replace("_lower_id", "lower_id")
        .replace("_raw_id", "raw_investment_identifier")
    )

    mismatch_checks = {
        "fair_value": _material_mismatch_sql("s.source_fair_value", "o.output_fair_value"),
        "cost": _material_mismatch_sql("s.source_cost", "o.output_cost"),
        "principal_amount": _material_mismatch_sql(
            "s.source_principal_amount", "o.output_principal_amount"
        ),
        "shares_held": _material_mismatch_sql("s.source_shares_held", "o.output_shares_held"),
    }
    fair_value_mismatch_expr = mismatch_checks["fair_value"]
    diagnostic_mismatch_expr = " OR ".join(
        mismatch_checks[field] for field in ["cost", "principal_amount", "shares_held"]
    )
    mismatch_fields_expr = "concat_ws(',', " + ", ".join(
        f"CASE WHEN {expr} THEN '{field}' END" for field, expr in mismatch_checks.items()
    ) + ")"
    source_staging_identifier = _staging_clean_identifier_sql("investment_identifier")
    output_staging_identifier = _staging_clean_identifier_sql("bdc_investment_identifier")

    detail = con.execute(f"""
        WITH source_base AS (
            SELECT
                CAST(source_row_id AS BIGINT) AS source_row_id,
                LPAD(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
                CAST(entity_name AS VARCHAR) AS entity_name,
                CAST(report_date AS VARCHAR) AS report_date,
                CAST(period AS VARCHAR) AS period,
                CAST(accession_number AS VARCHAR) AS accession_number,
                CAST(form_type AS VARCHAR) AS form_type,
                CAST(filing_date AS VARCHAR) AS filing_date,
                CAST(context_id AS VARCHAR) AS context_id,
                CAST(investment_identifier AS VARCHAR) AS raw_investment_identifier,
                {_norm_identifier_sql('investment_identifier')} AS normalized_investment_identifier,
                regexp_replace(
                    lower(trim({source_staging_identifier})),
                    '[^a-z0-9]+', ' ', 'g'
                ) AS staging_normalized_investment_identifier,
                lower(trim({source_staging_identifier})) AS lower_id,
                CAST(dimensions_raw AS VARCHAR) AS dimensions_raw,
                CAST(concept_names AS VARCHAR) AS concept_names,
                TRY_CAST(fair_value AS DOUBLE) AS source_fair_value,
                TRY_CAST(cost AS DOUBLE) AS source_cost,
                TRY_CAST(principal_amount AS DOUBLE) AS source_principal_amount,
                TRY_CAST(shares_held AS DOUBLE) AS source_shares_held,
                TRY_CAST(interest_rate AS DOUBLE) AS source_interest_rate,
                TRY_CAST(basis_spread AS DOUBLE) AS source_basis_spread,
                TRY_CAST(pik_rate AS DOUBLE) AS source_pik_rate
            FROM source_raw
        ), source_quarterly_fv AS (
            SELECT cik, report_date, SUM(source_fair_value) AS total_fv
            FROM source_base
            WHERE source_fair_value IS NOT NULL AND source_fair_value > 0
            GROUP BY cik, report_date
        ), source_cik_medians AS (
            SELECT cik, MEDIAN(total_fv) AS median_fv, COUNT(*) AS n_quarters
            FROM source_quarterly_fv
            GROUP BY cik
        ), source_scale_errors AS (
            SELECT q.cik, q.report_date
            FROM source_quarterly_fv q
            JOIN source_cik_medians m ON q.cik = m.cik
            WHERE m.n_quarters >= 3
              AND m.median_fv > 0
              AND q.total_fv / m.median_fv > 100
        ), source_prepared AS (
            SELECT b.* EXCLUDE (
                    source_fair_value, source_cost, source_principal_amount
                ),
                CASE WHEN se.cik IS NOT NULL
                    THEN b.source_fair_value / 1000
                    ELSE b.source_fair_value
                END AS source_fair_value,
                CASE WHEN se.cik IS NOT NULL
                    THEN b.source_cost / 1000
                    ELSE b.source_cost
                END AS source_cost,
                CASE WHEN se.cik IS NOT NULL
                    THEN b.source_principal_amount / 1000
                    ELSE b.source_principal_amount
                END AS source_principal_amount
            FROM source_base b
            LEFT JOIN source_scale_errors se
              ON b.cik = se.cik
             AND b.report_date = se.report_date
        ), source_ranked AS (
            SELECT *,
                DENSE_RANK() OVER (
                    PARTITION BY cik, report_date,
                        regexp_replace(CAST(form_type AS VARCHAR), '/A$', '')
                    ORDER BY CAST(filing_date AS VARCHAR) DESC,
                             CAST(accession_number AS VARCHAR) DESC
                ) AS amendment_rank,
                CASE
                    WHEN TRY_CAST(report_date AS DATE) < '2022-01-01'
                        THEN 'pre_2022_out_of_scope'
                    WHEN TRY_CAST(period AS DATE) IS NOT NULL
                     AND TRY_CAST(report_date AS DATE) IS NOT NULL
                     AND TRY_CAST(period AS DATE) != TRY_CAST(report_date AS DATE)
                        THEN 'excluded_comparative_period'
                    ELSE ''
                END AS period_status
            FROM source_prepared
        ), aggregate_override_matches AS (
            SELECT
                s.source_row_id,
                MAX(CASE WHEN o.action = 'include' THEN 1 ELSE 0 END) AS force_include,
                MAX(CASE WHEN o.action = 'exclude' THEN 1 ELSE 0 END) AS force_exclude,
                MAX(CASE WHEN o.action = 'exclude' AND o.match_mode = 'exact' THEN 1 ELSE 0 END)
                    AS exact_force_exclude
            FROM source_ranked s
            JOIN bdc_aggregate_overrides o
              ON s.cik = o.cik
             AND (o.report_date = '' OR s.report_date = o.report_date)
             AND (o.accession_number = '' OR s.accession_number = o.accession_number)
             AND (
                 (o.match_mode = 'exact' AND lower(trim(CAST(s.raw_investment_identifier AS VARCHAR))) = o.match_text_lower)
                 OR (o.match_mode = 'contains' AND contains(lower(CAST(s.raw_investment_identifier AS VARCHAR)), o.match_text_lower))
             )
            GROUP BY s.source_row_id
        ), source_classified AS (
            SELECT *,
                CASE
                    WHEN COALESCE(aom.force_include, 0) = 1 THEN false
                    WHEN COALESCE(aom.force_exclude, 0) = 1 THEN true
                    ELSE {agg_filter}
                END AS is_aggregate_candidate,
                COALESCE(aom.exact_force_exclude, 0) = 1 AS is_exact_override_exclude,
                {_money_market_check_sql('lower_id')} AS is_money_market,
                ({_bad_issuer_name_sql('staging_normalized_investment_identifier')}) AS is_bad_issuer_candidate,
                CASE WHEN (
                    NOT regexp_matches(lower_id, '(?:inc[.]?|llc|corp[.]?|ltd[.]?|l[.]p[.]|holdings|partners|group)\\b')
                    AND (
                        regexp_matches(lower_id, '^(?:equity investments|debt investments|investments|cash and cash|control investments|affiliate investments|portfolio company|non-control|total |subtotal )')
                        OR (LENGTH(lower_id) < 30 AND NOT regexp_matches(lower_id, '[-|,]')
                            AND array_length(regexp_split_to_array(trim(lower_id), '\\s+')) <= 3)
                        OR (regexp_matches(lower_id, '\\d+\\.\\d+%\\s*$')
                            AND NOT regexp_matches(lower_id, '(?:interest|sofr|spread|coupon|rate|maturity)'))
                    )
                ) THEN true ELSE false END AS is_hierarchy_header,
                CASE
                    WHEN period_status != '' THEN period_status
                    WHEN amendment_rank > 1 THEN 'superseded_amendment'
                    WHEN source_fair_value IS NULL THEN 'excluded_no_fair_value'
                    ELSE ''
                END AS source_exclusion_status
            FROM source_ranked
            LEFT JOIN aggregate_override_matches aom
              ON source_ranked.source_row_id = aom.source_row_id
        ), source_duplicate_marked AS (
            SELECT *,
                ROW_NUMBER() OVER (
                    PARTITION BY cik, report_date, accession_number,
                        staging_normalized_investment_identifier,
                        round(COALESCE(source_fair_value, 0), 2)
                    ORDER BY
                        length(COALESCE(staging_normalized_investment_identifier, '')),
                        source_row_id
                ) AS duplicate_rank,
                COUNT(*) OVER (
                    PARTITION BY cik, report_date, accession_number,
                        staging_normalized_investment_identifier,
                        round(COALESCE(source_fair_value, 0), 2)
                ) AS duplicate_count,
                FIRST_VALUE(source_row_id) OVER (
                    PARTITION BY cik, report_date, accession_number,
                        staging_normalized_investment_identifier,
                        round(COALESCE(source_fair_value, 0), 2)
                    ORDER BY
                        length(COALESCE(staging_normalized_investment_identifier, '')),
                        source_row_id
                ) AS canonical_source_row_id
            FROM source_classified
            WHERE source_exclusion_status = ''
              AND NULLIF(trim(staging_normalized_investment_identifier), '') IS NOT NULL
        ), source_self_referential_subtotals AS (
            SELECT DISTINCT a.source_row_id
            FROM source_classified a
            JOIN source_classified b
              ON a.cik = b.cik
             AND a.accession_number = b.accession_number
             AND a.report_date = b.report_date
             AND b.staging_normalized_investment_identifier
                 LIKE a.staging_normalized_investment_identifier || ' %'
             AND LENGTH(b.staging_normalized_investment_identifier)
                 > LENGTH(a.staging_normalized_investment_identifier) + 10
            WHERE a.source_exclusion_status = ''
              AND b.source_exclusion_status = ''
              AND a.source_fair_value IS NOT NULL
              AND b.source_fair_value IS NOT NULL
              AND NULLIF(TRIM(a.staging_normalized_investment_identifier), '') IS NOT NULL
              AND LENGTH(a.staging_normalized_investment_identifier) >= 3
            GROUP BY a.source_row_id
            HAVING COUNT(DISTINCT b.source_row_id) >= 2
        ), eligible_source AS (
            SELECT
                s.*,
                CASE
                    WHEN d.duplicate_rank > 1 THEN 'collapsed_duplicate_dimension_path'
                    ELSE ''
                END AS duplicate_status,
                COALESCE(d.canonical_source_row_id, s.source_row_id) AS canonical_source_row_id
            FROM source_classified s
            LEFT JOIN source_duplicate_marked d
              ON s.source_row_id = d.source_row_id
        ), output_prepared AS (
            SELECT
                CAST(output_row_id AS BIGINT) AS output_row_id,
                LPAD(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
                CAST(entity_name AS VARCHAR) AS entity_name,
                CAST(report_date AS VARCHAR) AS report_date,
                CAST(accession_number AS VARCHAR) AS accession_number,
                CAST(bdc_form_type AS VARCHAR) AS form_type,
                CAST(filing_date AS VARCHAR) AS filing_date,
                CAST(bdc_investment_identifier AS VARCHAR) AS raw_investment_identifier,
                {_norm_identifier_sql('bdc_investment_identifier')} AS normalized_investment_identifier,
                regexp_replace(
                    lower(trim({output_staging_identifier})),
                    '[^a-z0-9]+', ' ', 'g'
                ) AS staging_normalized_investment_identifier,
                CAST(bdc_dimensions_raw AS VARCHAR) AS dimensions_raw,
                TRY_CAST(fair_value AS DOUBLE) AS output_fair_value,
                TRY_CAST(cost AS DOUBLE) AS output_cost,
                TRY_CAST(principal_amount AS DOUBLE) AS output_principal_amount,
                TRY_CAST(shares_held AS DOUBLE) AS output_shares_held,
                TRY_CAST(interest_rate AS DOUBLE) AS output_interest_rate,
                TRY_CAST(basis_spread AS DOUBLE) AS output_basis_spread,
                TRY_CAST(pik_rate AS DOUBLE) AS output_pik_rate,
                CAST(issuer_name AS VARCHAR) AS issuer_name,
                CAST(instrument_description AS VARCHAR) AS instrument_description,
                CAST(index_classification AS VARCHAR) AS index_classification,
                CAST(asset_category AS VARCHAR) AS asset_category,
                CAST(issuer_category AS VARCHAR) AS issuer_category
            FROM output_raw
        ), output_accession_counts AS (
            SELECT cik, report_date, accession_number, COUNT(*) AS output_count
            FROM output_prepared
            GROUP BY cik, report_date, accession_number
        ), exact_dimension_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'exact_dimensions_raw' AS match_tier,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        0,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        o.output_row_id
                ) AS source_match_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY o.output_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        0,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        s.source_row_id
                ) AS output_match_rank
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND s.dimensions_raw = o.dimensions_raw
             AND NULLIF(trim(s.dimensions_raw), '') IS NOT NULL
             AND abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0))
                 <= greatest(1.0, 0.0001 * greatest(abs(COALESCE(s.source_fair_value, 0)), abs(COALESCE(o.output_fair_value, 0))))
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
        ), exact_dimension_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM exact_dimension_candidates
            WHERE source_match_rank = 1 AND output_match_rank = 1
        ), exact_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'exact_identifier' AS match_tier,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        1,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        o.output_row_id
                ) AS source_match_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY o.output_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        1,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        s.source_row_id
                ) AS output_match_rank
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND s.raw_investment_identifier = o.raw_investment_identifier
            LEFT JOIN exact_dimension_matches eds ON s.source_row_id = eds.source_row_id
            LEFT JOIN exact_dimension_matches edo ON o.output_row_id = edo.output_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND eds.source_row_id IS NULL
              AND edo.output_row_id IS NULL
        ), exact_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM exact_candidates
            WHERE source_match_rank = 1 AND output_match_rank = 1
        ), staging_normalized_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'staging_normalized_identifier' AS match_tier,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        2,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        o.output_row_id
                ) AS source_match_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY o.output_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        2,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        s.source_row_id
                ) AS output_match_rank
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND s.staging_normalized_investment_identifier = o.staging_normalized_investment_identifier
             AND NULLIF(trim(s.staging_normalized_investment_identifier), '') IS NOT NULL
            LEFT JOIN exact_dimension_matches eds ON s.source_row_id = eds.source_row_id
            LEFT JOIN exact_dimension_matches edo ON o.output_row_id = edo.output_row_id
            LEFT JOIN exact_matches ems ON s.source_row_id = ems.source_row_id
            LEFT JOIN exact_matches emo ON o.output_row_id = emo.output_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND eds.source_row_id IS NULL
              AND edo.output_row_id IS NULL
              AND ems.source_row_id IS NULL
              AND emo.output_row_id IS NULL
        ), staging_normalized_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM staging_normalized_candidates
            WHERE source_match_rank = 1 AND output_match_rank = 1
        ), normalized_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'normalized_identifier_fair_value' AS match_tier,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        3,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        o.output_row_id
                ) AS source_match_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY o.output_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        3,
                        length(COALESCE(s.staging_normalized_investment_identifier, '')),
                        s.source_row_id
                ) AS output_match_rank
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.normalized_investment_identifier = o.normalized_investment_identifier
             AND s.accession_number = o.accession_number
             AND abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0))
                 <= greatest(1.0, 0.0001 * greatest(abs(COALESCE(s.source_fair_value, 0)), abs(COALESCE(o.output_fair_value, 0))))
            LEFT JOIN exact_matches ems ON s.source_row_id = ems.source_row_id
            LEFT JOIN exact_matches emo ON o.output_row_id = emo.output_row_id
            LEFT JOIN exact_dimension_matches eds ON s.source_row_id = eds.source_row_id
            LEFT JOIN exact_dimension_matches edo ON o.output_row_id = edo.output_row_id
            LEFT JOIN staging_normalized_matches sns ON s.source_row_id = sns.source_row_id
            LEFT JOIN staging_normalized_matches sno ON o.output_row_id = sno.output_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND ems.source_row_id IS NULL
              AND emo.output_row_id IS NULL
              AND eds.source_row_id IS NULL
              AND edo.output_row_id IS NULL
              AND sns.source_row_id IS NULL
              AND sno.output_row_id IS NULL
        ), normalized_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM normalized_candidates
            WHERE source_match_rank = 1 AND output_match_rank = 1
        ), prior_matches AS (
            SELECT * FROM exact_dimension_matches
            UNION ALL
            SELECT * FROM exact_matches
            UNION ALL
            SELECT * FROM staging_normalized_matches
            UNION ALL
            SELECT * FROM normalized_matches
        ), numeric_identity_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                COUNT(*) OVER (PARTITION BY s.source_row_id) AS source_numeric_candidate_count,
                COUNT(*) OVER (PARTITION BY o.output_row_id) AS output_numeric_candidate_count
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND s.source_fair_value IS NOT NULL
             AND o.output_fair_value IS NOT NULL
             AND s.source_cost IS NOT NULL
             AND o.output_cost IS NOT NULL
             AND abs(s.source_fair_value - o.output_fair_value)
                 <= greatest(1.0, 0.0001 * greatest(abs(s.source_fair_value), abs(o.output_fair_value)))
             AND abs(s.source_cost - o.output_cost)
                 <= greatest(1.0, 0.0001 * greatest(abs(s.source_cost), abs(o.output_cost)))
            LEFT JOIN prior_matches pms ON s.source_row_id = pms.source_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND pms.source_row_id IS NULL
        ), numeric_identity_matches AS (
            SELECT
                nic.source_row_id,
                nic.output_row_id,
                'reconciled_numeric_identity' AS match_tier
            FROM numeric_identity_candidates nic
            LEFT JOIN prior_matches pmo ON nic.output_row_id = pmo.output_row_id
            WHERE nic.source_numeric_candidate_count = 1
              AND nic.output_numeric_candidate_count = 1
              AND pmo.output_row_id IS NULL
        ), numeric_identity_candidate_summary AS (
            SELECT
                nic.source_row_id,
                COUNT(*) AS numeric_identity_candidate_count,
                COUNT(DISTINCT nic.output_row_id) AS numeric_identity_output_count,
                MAX(nic.output_numeric_candidate_count) AS numeric_identity_max_source_count,
                SUM(CASE WHEN pmo.output_row_id IS NOT NULL THEN 1 ELSE 0 END)
                    AS numeric_identity_already_matched_output_count
            FROM numeric_identity_candidates nic
            LEFT JOIN prior_matches pmo ON nic.output_row_id = pmo.output_row_id
            LEFT JOIN numeric_identity_matches nim
              ON nic.source_row_id = nim.source_row_id
             AND nic.output_row_id = nim.output_row_id
            WHERE nim.source_row_id IS NULL
            GROUP BY nic.source_row_id
        ), all_matches_base AS (
            SELECT * FROM prior_matches
            UNION ALL
            SELECT * FROM numeric_identity_matches
        ), issuer_name_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'reconciled_issuer_name_extraction' AS match_tier,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        o.output_row_id
                ) AS source_match_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY o.output_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        s.source_row_id
                ) AS output_match_rank
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0))
                 <= greatest(1.0, 0.0001 * greatest(abs(COALESCE(s.source_fair_value, 0)), abs(COALESCE(o.output_fair_value, 0))))
             AND regexp_replace(lower(trim(COALESCE(o.issuer_name, ''))), '[^a-z0-9]+', ' ', 'g') != ''
             AND (
                 -- Source identifier contains the output issuer_name (normalized)
                 contains(
                     s.staging_normalized_investment_identifier,
                     regexp_replace(lower(trim(COALESCE(o.issuer_name, ''))), '[^a-z0-9]+', ' ', 'g')
                 )
                 -- OR first pipe-segment of source matches output issuer_name
                 OR regexp_replace(lower(trim(
                     CASE WHEN contains(s.raw_investment_identifier, ' | ')
                         THEN split_part(s.raw_investment_identifier, ' | ', 1)
                         WHEN contains(s.raw_investment_identifier, '|')
                         THEN split_part(s.raw_investment_identifier, '|', 1)
                         ELSE ''
                     END
                 )), '[^a-z0-9]+', ' ', 'g') = regexp_replace(lower(trim(COALESCE(o.issuer_name, ''))), '[^a-z0-9]+', ' ', 'g')
                 -- OR first comma-segment of source matches output issuer_name
                 OR regexp_replace(lower(trim(
                     split_part(s.raw_investment_identifier, ',', 1)
                 )), '[^a-z0-9]+', ' ', 'g') = regexp_replace(lower(trim(COALESCE(o.issuer_name, ''))), '[^a-z0-9]+', ' ', 'g')
                 -- OR first dash-segment of source (after stripping hierarchy) matches
                 OR regexp_replace(lower(trim(
                     CASE WHEN contains(s.raw_investment_identifier, ' - ')
                         THEN split_part(
                             regexp_replace(s.raw_investment_identifier, '{_INVESTMENTS_HIERARCHY_RE}', ''),
                             ' - ', 1)
                         ELSE ''
                     END
                 )), '[^a-z0-9]+', ' ', 'g') = regexp_replace(lower(trim(COALESCE(o.issuer_name, ''))), '[^a-z0-9]+', ' ', 'g')
             )
            LEFT JOIN all_matches_base amb ON s.source_row_id = amb.source_row_id
            LEFT JOIN all_matches_base ambo ON o.output_row_id = ambo.output_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND amb.source_row_id IS NULL
              AND ambo.output_row_id IS NULL
              AND LENGTH(regexp_replace(lower(trim(COALESCE(o.issuer_name, ''))), '[^a-z0-9]+', ' ', 'g')) >= 3
        ), issuer_name_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM issuer_name_candidates
            WHERE source_match_rank = 1 AND output_match_rank = 1
        ), all_matches_with_issuer AS (
            SELECT * FROM all_matches_base
            UNION ALL
            SELECT * FROM issuer_name_matches
        ), fv_only_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'reconciled_fv_only_identity' AS match_tier,
                COUNT(*) OVER (PARTITION BY s.source_row_id) AS source_candidate_count,
                COUNT(*) OVER (PARTITION BY o.output_row_id) AS output_candidate_count
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND s.source_fair_value IS NOT NULL
             AND o.output_fair_value IS NOT NULL
             AND abs(s.source_fair_value - o.output_fair_value)
                 <= greatest(1.0, 0.0001 * greatest(abs(s.source_fair_value), abs(o.output_fair_value)))
            LEFT JOIN all_matches_with_issuer awi ON s.source_row_id = awi.source_row_id
            LEFT JOIN all_matches_with_issuer awio ON o.output_row_id = awio.output_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND awi.source_row_id IS NULL
              AND awio.output_row_id IS NULL
        ), fv_only_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM fv_only_candidates
            WHERE source_candidate_count = 1 AND output_candidate_count = 1
        ), all_matches_with_fv AS (
            SELECT * FROM all_matches_with_issuer
            UNION ALL
            SELECT * FROM fv_only_matches
        ), partial_name_candidates AS (
            SELECT
                s.source_row_id,
                o.output_row_id,
                'reconciled_partial_name_fv' AS match_tier,
                ROW_NUMBER() OVER (
                    PARTITION BY s.source_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        o.output_row_id
                ) AS source_match_rank,
                ROW_NUMBER() OVER (
                    PARTITION BY o.output_row_id
                    ORDER BY
                        abs(COALESCE(s.source_fair_value, 0) - COALESCE(o.output_fair_value, 0)),
                        s.source_row_id
                ) AS output_match_rank,
                COUNT(*) OVER (PARTITION BY s.source_row_id) AS source_candidate_count,
                COUNT(*) OVER (PARTITION BY o.output_row_id) AS output_candidate_count
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND s.source_fair_value IS NOT NULL
             AND o.output_fair_value IS NOT NULL
             AND abs(s.source_fair_value - o.output_fair_value)
                 <= greatest(1.0, 0.0001 * greatest(abs(s.source_fair_value), abs(o.output_fair_value)))
             AND LENGTH(s.staging_normalized_investment_identifier) >= 5
             AND LENGTH(o.staging_normalized_investment_identifier) >= 5
             AND (
                 -- At least 2 non-trivial words overlap between source and output identifiers
                 list_count(
                     list_filter(
                         list_intersect(
                             regexp_split_to_array(s.staging_normalized_investment_identifier, '\\s+'),
                             regexp_split_to_array(o.staging_normalized_investment_identifier, '\\s+')
                         ),
                         x -> LENGTH(x) >= 3
                            AND x NOT IN ('the', 'and', 'inc', 'llc', 'ltd', 'non', 'lien',
                                          'investments', 'investment', 'debt', 'equity',
                                          'first', 'second', 'senior', 'secured', 'term',
                                          'loan', 'note', 'controlled', 'affiliated')
                     )
                 ) >= 2
             )
            LEFT JOIN all_matches_with_fv awf ON s.source_row_id = awf.source_row_id
            LEFT JOIN all_matches_with_fv awfo ON o.output_row_id = awfo.output_row_id
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND awf.source_row_id IS NULL
              AND awfo.output_row_id IS NULL
        ), partial_name_matches AS (
            SELECT source_row_id, output_row_id, match_tier
            FROM partial_name_candidates
            WHERE source_match_rank = 1 AND output_match_rank = 1
              AND source_candidate_count = 1 AND output_candidate_count = 1
        ), all_matches AS (
            SELECT * FROM all_matches_with_fv
            UNION ALL
            SELECT * FROM partial_name_matches
        ), source_affiliation_dupes AS (
            SELECT DISTINCT s2.source_row_id
            FROM eligible_source s1
            JOIN all_matches m ON s1.source_row_id = m.source_row_id
            JOIN eligible_source s2
              ON s1.cik = s2.cik
             AND s1.report_date = s2.report_date
             AND s1.accession_number = s2.accession_number
             AND abs(COALESCE(s1.source_fair_value, 0) - COALESCE(s2.source_fair_value, 0)) <= 1.0
             AND s1.source_row_id != s2.source_row_id
            LEFT JOIN all_matches m2 ON s2.source_row_id = m2.source_row_id
            WHERE m2.source_row_id IS NULL
              AND COALESCE(s2.source_exclusion_status, '') = ''
              AND COALESCE(s2.duplicate_status, '') = ''
        ), source_rollup_matches AS (
            SELECT
                s.source_row_id,
                COUNT(o.output_row_id) AS child_output_count,
                SUM(o.output_fair_value) AS child_output_fair_value
            FROM eligible_source s
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND (
                o.staging_normalized_investment_identifier
                    LIKE s.staging_normalized_investment_identifier || ' %'
                OR (
                    COALESCE(s.is_aggregate_candidate, false)
                    AND s.staging_normalized_investment_identifier LIKE 'total %'
                )
             )
            WHERE COALESCE(s.source_exclusion_status, '') = ''
              AND COALESCE(s.duplicate_status, '') = ''
              AND NULLIF(trim(s.staging_normalized_investment_identifier), '') IS NOT NULL
              AND s.source_fair_value IS NOT NULL
              AND o.output_fair_value IS NOT NULL
            GROUP BY s.source_row_id, s.source_fair_value
            HAVING COUNT(o.output_row_id) >= 2
               AND abs(s.source_fair_value - SUM(o.output_fair_value))
                   <= greatest(1.0, 0.0001 * greatest(abs(s.source_fair_value), abs(SUM(o.output_fair_value))))
        ), documented_source_rollups AS (
            SELECT sr.*
            FROM source_rollup_matches sr
            LEFT JOIN all_matches m ON sr.source_row_id = m.source_row_id
            WHERE m.source_row_id IS NULL
        ), rollup_child_outputs AS (
            SELECT DISTINCT o.output_row_id
            FROM documented_source_rollups sr
            JOIN eligible_source s ON sr.source_row_id = s.source_row_id
            JOIN output_prepared o
              ON s.cik = o.cik
             AND s.report_date = o.report_date
             AND s.accession_number = o.accession_number
             AND (
                o.staging_normalized_investment_identifier
                    LIKE s.staging_normalized_investment_identifier || ' %'
                OR (
                    COALESCE(s.is_aggregate_candidate, false)
                    AND s.staging_normalized_investment_identifier LIKE 'total %'
                )
             )
        ), source_detail AS (
            SELECT
                CASE
                    WHEN s.source_exclusion_status != '' THEN s.source_exclusion_status
                    WHEN s.duplicate_status != '' THEN s.duplicate_status
                    WHEN m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL
                        THEN 'documented_source_rollup_exact'
                    WHEN m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL
                        THEN 'excluded_self_referential_subtotal'
                    WHEN COALESCE(s.is_aggregate_candidate, false)
                         AND (COALESCE(s.is_exact_override_exclude, false)
                              OR COALESCE(oac.output_count, 0) = 0)
                        THEN 'excluded_aggregate_candidate'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_money_market, false)
                        THEN 'excluded_money_market_fund'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false)
                        THEN 'excluded_bad_issuer_name'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                         AND NOT COALESCE(s.is_aggregate_candidate, false)
                        THEN 'excluded_hierarchy_header'
                    WHEN m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL
                        THEN 'excluded_affiliation_dedup'
                    WHEN m.source_row_id IS NULL THEN 'missing_from_pipeline'
                    WHEN {fair_value_mismatch_expr} THEN 'value_mismatch'
                    WHEN {diagnostic_mismatch_expr} THEN 'diagnostic_field_mismatch'
                    ELSE 'matched'
                END AS status,
                COALESCE(m.match_tier, '') AS match_tier,
                CASE
                    WHEN s.source_exclusion_status != '' OR s.duplicate_status != ''
                         OR (m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL)
                         OR (m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL)
                         OR (
                             COALESCE(s.is_aggregate_candidate, false)
                             AND (COALESCE(s.is_exact_override_exclude, false)
                                  OR COALESCE(oac.output_count, 0) = 0)
                         )
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_money_market, false))
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false))
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                             AND NOT COALESCE(s.is_aggregate_candidate, false))
                         OR (m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL)
                         THEN ''
                    WHEN m.source_row_id IS NULL THEN 'FAIL'
                    WHEN {fair_value_mismatch_expr} THEN 'FAIL'
                    WHEN {diagnostic_mismatch_expr} THEN 'WARN'
                    ELSE ''
                END AS issue_severity,
                CASE
                    WHEN s.source_exclusion_status != '' OR s.duplicate_status != ''
                         OR (m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL)
                         OR (m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL)
                         OR (
                             COALESCE(s.is_aggregate_candidate, false)
                             AND (COALESCE(s.is_exact_override_exclude, false)
                                  OR COALESCE(oac.output_count, 0) = 0)
                         )
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_money_market, false))
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false))
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                             AND NOT COALESCE(s.is_aggregate_candidate, false))
                         OR (m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL)
                        THEN 'documented_exclusion'
                    WHEN m.source_row_id IS NULL THEN 'row_identity'
                    WHEN {fair_value_mismatch_expr} THEN 'fair_value'
                    WHEN {diagnostic_mismatch_expr} THEN 'field_diagnostic'
                    ELSE 'reconciled'
                END AS residual_class,
                CASE
                    WHEN s.source_exclusion_status != '' OR s.duplicate_status != ''
                         OR (m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL)
                         OR (m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL)
                         OR (
                             COALESCE(s.is_aggregate_candidate, false)
                             AND (COALESCE(s.is_exact_override_exclude, false)
                                  OR COALESCE(oac.output_count, 0) = 0)
                         )
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_money_market, false))
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false))
                         OR (m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                             AND NOT COALESCE(s.is_aggregate_candidate, false))
                         OR (m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL)
                         THEN false
                    WHEN m.source_row_id IS NULL THEN true
                    WHEN {fair_value_mismatch_expr} THEN true
                    ELSE false
                END AS blocking_issue,
                CASE
                    WHEN s.source_exclusion_status != '' THEN s.source_exclusion_status
                    WHEN s.duplicate_status != '' THEN s.duplicate_status
                    WHEN m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL
                        THEN 'documented_source_rollup_exact'
                    WHEN m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL
                        THEN 'excluded_self_referential_subtotal'
                    WHEN COALESCE(s.is_aggregate_candidate, false)
                         AND (COALESCE(s.is_exact_override_exclude, false)
                              OR COALESCE(oac.output_count, 0) = 0)
                        THEN 'excluded_aggregate_candidate'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_money_market, false)
                        THEN 'excluded_money_market_fund'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false)
                        THEN 'excluded_bad_issuer_name'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                         AND NOT COALESCE(s.is_aggregate_candidate, false)
                        THEN 'excluded_hierarchy_header'
                    WHEN m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL
                        THEN 'excluded_affiliation_dedup'
                    WHEN m.source_row_id IS NULL THEN 'blocking_missing_from_pipeline'
                    WHEN {fair_value_mismatch_expr} THEN 'blocking_fair_value_mismatch'
                    WHEN {diagnostic_mismatch_expr} THEN 'diagnostic_field_mismatch'
                    ELSE 'reconciled'
                END AS calibrated_status,
                CASE
                    WHEN s.source_exclusion_status != '' THEN s.source_exclusion_status
                    WHEN s.duplicate_status != '' THEN 'same economic facts reported on multiple dimension paths'
                    WHEN m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL
                        THEN 'source rollup fair_value equals sum of multiple pipeline child positions'
                    WHEN m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL
                        THEN 'self-referential subtotal whose identifier is prefix of multiple child source rows'
                    WHEN COALESCE(s.is_aggregate_candidate, false)
                         AND (COALESCE(s.is_exact_override_exclude, false)
                              OR COALESCE(oac.output_count, 0) = 0)
                        THEN CASE
                            WHEN COALESCE(s.is_exact_override_exclude, false)
                            THEN 'aggregate source row excluded by audited exact override'
                            ELSE 'aggregate source row has no current pipeline output rows for this accession'
                        END
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_money_market, false)
                        THEN 'money market fund position filtered during BDC staging'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false)
                        THEN 'generic/bad issuer name filtered during BDC staging'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                         AND NOT COALESCE(s.is_aggregate_candidate, false)
                        THEN 'hierarchy/category header lacking entity signals'
                    WHEN m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL
                        THEN 'affiliation-axis duplicate of a matched source row with same fair value'
                    WHEN m.source_row_id IS NULL
                         AND COALESCE(nics.numeric_identity_candidate_count, 0) > 0
                         AND COALESCE(nics.numeric_identity_already_matched_output_count, 0) > 0
                        THEN 'eligible source row numeric identity candidate points to an already matched output row'
                    WHEN m.source_row_id IS NULL
                         AND COALESCE(nics.numeric_identity_candidate_count, 0) > 0
                         AND COALESCE(nics.numeric_identity_output_count, 0) > 1
                        THEN 'eligible source row has multiple numeric identity output candidates'
                    WHEN m.source_row_id IS NULL
                         AND COALESCE(nics.numeric_identity_candidate_count, 0) > 0
                         AND COALESCE(nics.numeric_identity_max_source_count, 0) > 1
                        THEN 'eligible source row is part of a multi-source numeric identity collision'
                    WHEN m.source_row_id IS NULL
                         AND COALESCE(nics.numeric_identity_candidate_count, 0) > 0
                        THEN 'eligible source row has numeric identity candidate but not a deterministic one-to-one match'
                    WHEN m.source_row_id IS NULL THEN 'eligible current-period source row has no pipeline output row'
                    WHEN {fair_value_mismatch_expr} THEN 'fair_value differs between matched source and pipeline row'
                    WHEN {diagnostic_mismatch_expr}
                         AND lower(COALESCE(o.asset_category, '')) LIKE 'equity%'
                         AND contains({mismatch_fields_expr}, 'principal_amount')
                        THEN 'principal_amount differs on equity position; tracked as diagnostic'
                    WHEN {diagnostic_mismatch_expr}
                         AND lower(COALESCE(o.issuer_category, '')) = 'fund'
                         AND contains({mismatch_fields_expr}, 'principal_amount')
                        THEN 'principal_amount differs on fund position; tracked as diagnostic'
                    WHEN {diagnostic_mismatch_expr} THEN 'secondary source field differs without fair_value mismatch'
                    WHEN m.match_tier = 'reconciled_numeric_identity'
                        THEN 'source row reconciled to pipeline output by one-to-one numeric identity'
                    WHEN m.match_tier = 'reconciled_issuer_name_extraction'
                        THEN 'source row reconciled to pipeline output by issuer name extraction'
                    WHEN m.match_tier = 'reconciled_fv_only_identity'
                        THEN 'source row reconciled to pipeline output by strict 1:1 fair-value identity'
                    WHEN m.match_tier = 'reconciled_partial_name_fv'
                        THEN 'source row reconciled to pipeline output by partial name token overlap plus FV'
                    ELSE 'source row reconciled to pipeline output'
                END AS calibration_reason,
                s.cik, s.entity_name, s.report_date, s.period, s.accession_number,
                s.form_type, s.filing_date, s.context_id,
                CAST(s.source_row_id AS VARCHAR) AS source_row_id,
                CAST(o.output_row_id AS VARCHAR) AS output_row_id,
                s.raw_investment_identifier, s.normalized_investment_identifier,
                s.dimensions_raw, s.concept_names,
                s.source_fair_value, o.output_fair_value,
                s.source_cost, o.output_cost,
                s.source_principal_amount, o.output_principal_amount,
                s.source_shares_held, o.output_shares_held,
                s.source_interest_rate, o.output_interest_rate,
                s.source_basis_spread, o.output_basis_spread,
                s.source_pik_rate, o.output_pik_rate,
                CASE WHEN m.source_row_id IS NOT NULL THEN {mismatch_fields_expr} ELSE '' END AS mismatched_fields,
                COALESCE(o.issuer_name, '') AS issuer_name,
                COALESCE(o.instrument_description, '') AS instrument_description,
                COALESCE(o.index_classification, '') AS index_classification,
                COALESCE(o.asset_category, '') AS asset_category,
                COALESCE(o.issuer_category, '') AS issuer_category,
                CASE
                    WHEN s.source_exclusion_status != '' THEN s.source_exclusion_status
                    WHEN s.duplicate_status != '' THEN
                        'same economic facts reported on multiple dimension paths; canonical_source_row_id='
                        || CAST(s.canonical_source_row_id AS VARCHAR)
                    WHEN m.source_row_id IS NULL AND sr.source_row_id IS NOT NULL THEN
                        'documented source rollup exact; child_output_count='
                        || CAST(sr.child_output_count AS VARCHAR)
                        || '; child_output_fair_value='
                        || CAST(sr.child_output_fair_value AS VARCHAR)
                    WHEN m.source_row_id IS NULL AND srs.source_row_id IS NOT NULL THEN
                        'self-referential subtotal; identifier is prefix of multiple child source rows'
                    WHEN COALESCE(s.is_aggregate_candidate, false)
                         AND (COALESCE(s.is_exact_override_exclude, false)
                              OR COALESCE(oac.output_count, 0) = 0) THEN
                        CASE
                            WHEN COALESCE(s.is_exact_override_exclude, false)
                            THEN 'aggregate source row documented by audited exact override'
                            ELSE 'aggregate source row documented because accession has no current pipeline output rows'
                        END
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_money_market, false) THEN
                        'money market fund filtered during staging'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_bad_issuer_candidate, false) THEN
                        'generic/bad issuer name filtered during staging'
                    WHEN m.source_row_id IS NULL AND COALESCE(s.is_hierarchy_header, false)
                         AND NOT COALESCE(s.is_aggregate_candidate, false) THEN
                        'hierarchy/category header without entity signals'
                    WHEN m.source_row_id IS NULL AND sad.source_row_id IS NOT NULL THEN
                        'affiliation-axis duplicate of matched source row'
                    WHEN m.source_row_id IS NULL
                         AND COALESCE(nics.numeric_identity_candidate_count, 0) > 0 THEN
                        'blocking numeric identity candidate; candidate_output_count='
                        || CAST(nics.numeric_identity_output_count AS VARCHAR)
                        || '; already_matched_output_count='
                        || CAST(nics.numeric_identity_already_matched_output_count AS VARCHAR)
                        || '; candidate_source_count='
                        || CAST(nics.numeric_identity_max_source_count AS VARCHAR)
                    WHEN m.source_row_id IS NULL THEN 'eligible current-period source row has no pipeline output row'
                    WHEN {fair_value_mismatch_expr} THEN 'matched source/output row has materially different fair_value'
                    WHEN {diagnostic_mismatch_expr} THEN 'matched source/output row has secondary-field diagnostic mismatch'
                    WHEN m.match_tier = 'reconciled_numeric_identity'
                        THEN 'source row reconciled to pipeline output by one-to-one numeric identity'
                    WHEN m.match_tier = 'reconciled_issuer_name_extraction'
                        THEN 'source row reconciled to pipeline output by issuer name extraction'
                    WHEN m.match_tier = 'reconciled_fv_only_identity'
                        THEN 'source row reconciled to pipeline output by strict 1:1 fair-value identity'
                    WHEN m.match_tier = 'reconciled_partial_name_fv'
                        THEN 'source row reconciled to pipeline output by partial name token overlap plus FV'
                    ELSE 'source row reconciled to pipeline output'
                END AS evidence
            FROM eligible_source s
            LEFT JOIN all_matches m ON s.source_row_id = m.source_row_id
            LEFT JOIN output_prepared o ON m.output_row_id = o.output_row_id
            LEFT JOIN documented_source_rollups sr ON s.source_row_id = sr.source_row_id
            LEFT JOIN source_self_referential_subtotals srs ON s.source_row_id = srs.source_row_id
            LEFT JOIN source_affiliation_dupes sad ON s.source_row_id = sad.source_row_id
            LEFT JOIN numeric_identity_candidate_summary nics
              ON s.source_row_id = nics.source_row_id
            LEFT JOIN output_accession_counts oac
              ON s.cik = oac.cik
             AND s.report_date = oac.report_date
             AND s.accession_number = oac.accession_number
            WHERE COALESCE(s.period_status, '') != 'pre_2022_out_of_scope'
        ), output_extras AS (
            SELECT
                'extra_in_pipeline' AS status,
                '' AS match_tier,
                'FAIL' AS issue_severity,
                'row_identity' AS residual_class,
                true AS blocking_issue,
                'blocking_extra_in_pipeline' AS calibrated_status,
                'pipeline BDC row has no matching current-period source fact' AS calibration_reason,
                o.cik, o.entity_name, o.report_date,
                '' AS period, o.accession_number, o.form_type, o.filing_date,
                '' AS context_id,
                '' AS source_row_id,
                CAST(o.output_row_id AS VARCHAR) AS output_row_id,
                o.raw_investment_identifier,
                o.normalized_investment_identifier,
                o.dimensions_raw,
                '' AS concept_names,
                CAST(NULL AS DOUBLE) AS source_fair_value, o.output_fair_value,
                CAST(NULL AS DOUBLE) AS source_cost, o.output_cost,
                CAST(NULL AS DOUBLE) AS source_principal_amount, o.output_principal_amount,
                CAST(NULL AS DOUBLE) AS source_shares_held, o.output_shares_held,
                CAST(NULL AS DOUBLE) AS source_interest_rate, o.output_interest_rate,
                CAST(NULL AS DOUBLE) AS source_basis_spread, o.output_basis_spread,
                CAST(NULL AS DOUBLE) AS source_pik_rate, o.output_pik_rate,
                '' AS mismatched_fields,
                o.issuer_name, o.instrument_description,
                o.index_classification, o.asset_category, o.issuer_category,
                'pipeline BDC row has no matching current-period source fact' AS evidence
            FROM output_prepared o
            LEFT JOIN all_matches m ON o.output_row_id = m.output_row_id
            LEFT JOIN rollup_child_outputs rco ON o.output_row_id = rco.output_row_id
            WHERE m.output_row_id IS NULL
              AND rco.output_row_id IS NULL
              AND TRY_CAST(o.report_date AS DATE) >= '2022-01-01'
        )
        SELECT {", ".join(DETAIL_COLUMNS)}
        FROM source_detail
        UNION ALL
        SELECT {", ".join(DETAIL_COLUMNS)}
        FROM output_extras
        ORDER BY cik, report_date, accession_number, raw_investment_identifier, status
    """).fetchdf()

    metrics = build_source_reconciliation_metrics(detail)
    con.close()
    return detail[DETAIL_COLUMNS], metrics[METRIC_COLUMNS]


def build_source_reconciliation_metrics(detail_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate reconciliation detail rows by CIK-quarter."""
    if detail_df.empty:
        return _empty_metrics()
    detail_df = detail_df.copy()
    if "blocking_issue" not in detail_df.columns:
        detail_df["blocking_issue"] = detail_df["status"].isin(STRONG_STATUSES)
    if "calibrated_status" not in detail_df.columns:
        detail_df["calibrated_status"] = detail_df["status"]
    con = duckdb.connect()
    con.register("detail", detail_df)
    metrics = con.execute(f"""
        WITH grouped AS (
            SELECT
                cik,
                any_value(entity_name) AS entity_name,
                report_date,
                SUM(CASE WHEN source_row_id != '' THEN 1 ELSE 0 END) AS source_rows,
                SUM(CASE WHEN output_row_id != '' THEN 1 ELSE 0 END) AS output_rows,
                SUM(CASE WHEN status = 'matched' THEN 1 ELSE 0 END) AS matched_rows,
                SUM(CASE WHEN status = 'missing_from_pipeline' THEN 1 ELSE 0 END) AS missing_from_pipeline_rows,
                SUM(CASE WHEN status = 'extra_in_pipeline' THEN 1 ELSE 0 END) AS extra_in_pipeline_rows,
                SUM(CASE WHEN status = 'value_mismatch' THEN 1 ELSE 0 END) AS value_mismatch_rows,
                SUM(CASE WHEN status = 'collapsed_duplicate_dimension_path' THEN 1 ELSE 0 END) AS collapsed_duplicate_dimension_path_rows,
                SUM(CASE WHEN status = 'excluded_comparative_period' THEN 1 ELSE 0 END) AS excluded_comparative_period_rows,
                SUM(CASE WHEN status = 'excluded_aggregate_candidate' THEN 1 ELSE 0 END) AS excluded_aggregate_candidate_rows,
                SUM(CASE WHEN status = 'documented_source_rollup_exact' THEN 1 ELSE 0 END) AS documented_source_rollup_exact_rows,
                SUM(CASE WHEN status = 'excluded_no_fair_value' THEN 1 ELSE 0 END) AS excluded_no_fair_value_rows,
                SUM(CASE WHEN status = 'superseded_amendment' THEN 1 ELSE 0 END) AS superseded_amendment_rows,
                SUM(CASE WHEN status = 'excluded_self_referential_subtotal' THEN 1 ELSE 0 END) AS excluded_self_referential_subtotal_rows,
                SUM(CASE WHEN status = 'excluded_hierarchy_header' THEN 1 ELSE 0 END) AS excluded_hierarchy_header_rows,
                SUM(CASE WHEN status = 'excluded_money_market_fund' THEN 1 ELSE 0 END) AS excluded_money_market_fund_rows,
                SUM(CASE WHEN status = 'excluded_bad_issuer_name' THEN 1 ELSE 0 END) AS excluded_bad_issuer_name_rows,
                SUM(CASE WHEN status = 'excluded_affiliation_dedup' THEN 1 ELSE 0 END) AS excluded_affiliation_dedup_rows,
                SUM(CASE WHEN COALESCE(blocking_issue, false) THEN 1 ELSE 0 END)
                    AS blocking_issue_count,
                SUM(CASE WHEN COALESCE(calibrated_status, '') = 'diagnostic_field_mismatch' THEN 1 ELSE 0 END)
                    AS diagnostic_issue_count,
                SUM(CASE WHEN COALESCE(blocking_issue, false) THEN 1 ELSE 0 END)
                    AS strong_issue_count
            FROM detail
            GROUP BY cik, report_date
        )
        SELECT
            *,
            CASE
                WHEN source_rows - excluded_comparative_period_rows
                     - excluded_aggregate_candidate_rows
                     - documented_source_rollup_exact_rows
                     - excluded_no_fair_value_rows
                     - superseded_amendment_rows
                     - collapsed_duplicate_dimension_path_rows
                     - excluded_self_referential_subtotal_rows
                     - excluded_hierarchy_header_rows
                     - excluded_money_market_fund_rows
                     - excluded_bad_issuer_name_rows
                     - excluded_affiliation_dedup_rows <= 0
                    THEN NULL
                ELSE matched_rows::DOUBLE /
                    (source_rows - excluded_comparative_period_rows
                     - excluded_aggregate_candidate_rows
                     - documented_source_rollup_exact_rows
                     - excluded_no_fair_value_rows
                     - superseded_amendment_rows
                     - collapsed_duplicate_dimension_path_rows
                     - excluded_self_referential_subtotal_rows
                     - excluded_hierarchy_header_rows
                     - excluded_money_market_fund_rows
                     - excluded_bad_issuer_name_rows
                     - excluded_affiliation_dedup_rows)
            END AS reconciled_source_row_rate,
            CASE
                WHEN source_rows - excluded_comparative_period_rows
                     - excluded_aggregate_candidate_rows
                     - documented_source_rollup_exact_rows
                     - excluded_no_fair_value_rows
                     - superseded_amendment_rows
                     - collapsed_duplicate_dimension_path_rows
                     - excluded_self_referential_subtotal_rows
                     - excluded_hierarchy_header_rows
                     - excluded_money_market_fund_rows
                     - excluded_bad_issuer_name_rows
                     - excluded_affiliation_dedup_rows <= 0
                    THEN NULL
                ELSE
                    (matched_rows + diagnostic_issue_count)::DOUBLE /
                    (source_rows - excluded_comparative_period_rows
                     - excluded_aggregate_candidate_rows
                     - documented_source_rollup_exact_rows
                     - excluded_no_fair_value_rows
                     - superseded_amendment_rows
                     - collapsed_duplicate_dimension_path_rows
                     - excluded_self_referential_subtotal_rows
                     - excluded_hierarchy_header_rows
                     - excluded_money_market_fund_rows
                     - excluded_bad_issuer_name_rows
                     - excluded_affiliation_dedup_rows)
            END AS calibrated_reconciled_source_row_rate,
            CASE WHEN blocking_issue_count > 0 THEN 'UNDER_REVIEW' ELSE 'RECONCILED' END
                AS reconciliation_status
        FROM grouped
        ORDER BY cik, report_date
    """).fetchdf()
    con.close()
    return metrics[METRIC_COLUMNS]


def build_reconciliation_calibration_review(detail_df: pd.DataFrame) -> pd.DataFrame:
    """Summarize residual mechanisms by CIK-quarter for calibration review."""
    columns = [
        "cik", "entity_name", "report_date", "residual_class",
        "calibrated_status", "match_tier", "blocking_issue",
        "issue_count", "sample_identifiers", "calibration_reasons",
    ]
    if detail_df.empty:
        return pd.DataFrame(columns=columns)

    df = detail_df.copy()
    for col in ["residual_class", "calibrated_status", "match_tier", "calibration_reason"]:
        if col not in df.columns:
            df[col] = ""
    if "blocking_issue" not in df.columns:
        df["blocking_issue"] = df["status"].isin(STRONG_STATUSES)
    reviewable = df[
        (df["status"].astype(str) != "matched")
        | (df["calibrated_status"].astype(str) == "diagnostic_field_mismatch")
        | (df["match_tier"].astype(str).isin([
            "exact_dimensions_raw",
            "staging_normalized_identifier",
            "normalized_identifier_fair_value",
            "reconciled_numeric_identity",
            "reconciled_issuer_name_extraction",
            "reconciled_fv_only_identity",
            "reconciled_partial_name_fv",
        ]))
    ].copy()
    if reviewable.empty:
        return pd.DataFrame(columns=columns)

    con = duckdb.connect()
    con.register("reviewable", reviewable)
    review = con.execute("""
        SELECT
            cik,
            any_value(entity_name) AS entity_name,
            report_date,
            COALESCE(residual_class, '') AS residual_class,
            COALESCE(calibrated_status, '') AS calibrated_status,
            COALESCE(match_tier, '') AS match_tier,
            COALESCE(blocking_issue, false) AS blocking_issue,
            COUNT(*) AS issue_count,
            array_to_string(
                list(DISTINCT raw_investment_identifier ORDER BY raw_investment_identifier)[:5],
                ' | '
            ) AS sample_identifiers,
            array_to_string(
                list(DISTINCT calibration_reason ORDER BY calibration_reason)[:5],
                ' | '
            ) AS calibration_reasons
        FROM reviewable
        GROUP BY cik, report_date, residual_class, calibrated_status, match_tier, blocking_issue
        ORDER BY blocking_issue DESC, issue_count DESC, cik, report_date
    """).fetchdf()
    con.close()
    return review[columns]


def build_source_reconciliation_residual_classification(
    detail_df: pd.DataFrame,
) -> pd.DataFrame:
    """Classify non-plain source reconciliation residuals by mechanism.

    This is an audit layer over ``source_reconciliation_detail``.  It groups
    rows by CIK-quarter and deterministic mechanism, but preserves the source
    reconciliation status and blocking flag instead of recalibrating them.
    """
    if detail_df.empty:
        return _empty_residual_classification()

    df = detail_df.copy()
    for col in DETAIL_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    for col in ["source_fair_value", "output_fair_value"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if "blocking_issue" not in df.columns:
        df["blocking_issue"] = df["status"].isin(STRONG_STATUSES)
    df["blocking_issue"] = (
        df["blocking_issue"].astype(str).str.lower().isin(["true", "1", "yes"])
    )

    raw_identifier = df["raw_investment_identifier"].fillna("").astype(str).str.strip()
    raw_lower = raw_identifier.str.lower()

    date_like_identifier = raw_lower.str.match(
        r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
        r"(19|20)\d{2}q[1-4]|q[1-4]\s+(19|20)\d{2})$",
        na=False,
    )
    placeholder_identifier = raw_lower.str.match(
        r"^(n/?a|none|null|unknown|various|multiple|misc\.?|miscellaneous|other|"
        r"placeholder|not applicable|tbd)$",
        na=False,
    )
    category_identifier = raw_lower.str.match(
        r"^(software|health\s*care|healthcare|financials?|industrials?|energy|"
        r"consumer|business services|technology|media|telecommunications|"
        r"first lien|first lien debt|second lien|second lien debt|subordinated debt|"
        r"senior secured loans?|secured loans?|unsecured loans?|equity securities|"
        r"preferred equity|common equity|warrants?)$",
        na=False,
    )
    dimension_text_identifier = (
        raw_lower.str.contains("axis|member|=", regex=True, na=False)
        & (
            raw_lower.str.contains("investmentidentifier|investmenttype|industry|affiliation", regex=True, na=False)
            | raw_identifier.str.len().gt(140)
        )
    )
    parse_artifact = (
        date_like_identifier
        | placeholder_identifier
        | category_identifier
        | dimension_text_identifier
    )

    source_abs = df["source_fair_value"].abs()
    output_abs = df["output_fair_value"].abs()
    max_fv = pd.concat([source_abs, output_abs], axis=1).max(axis=1)
    min_fv = pd.concat([source_abs, output_abs], axis=1).min(axis=1)
    extreme_fv_ratio = (min_fv > 0) & ((max_fv / min_fv) >= 10)

    df["mechanism"] = ""
    for status, mechanism in DOCUMENTED_MECHANISMS.items():
        df.loc[df["status"].astype(str).eq(status), "mechanism"] = mechanism

    df.loc[
        df["calibrated_status"].astype(str).eq("diagnostic_field_mismatch"),
        "mechanism",
    ] = "diagnostic_secondary_field_mismatch"
    # Specific mechanism for new matching tiers
    for tier_name, mech_name in [
        ("reconciled_issuer_name_extraction", "reconciled_issuer_name_extraction"),
        ("reconciled_fv_only_identity", "reconciled_fv_only_identity"),
        ("reconciled_partial_name_fv", "reconciled_partial_name_fv"),
    ]:
        df.loc[
            df["status"].astype(str).eq("matched")
            & df["mechanism"].eq("")
            & df["match_tier"].astype(str).eq(tier_name),
            "mechanism",
        ] = mech_name
    # Remaining non-exact matched rows get generic normalization mechanism
    df.loc[
        df["status"].astype(str).eq("matched")
        & df["mechanism"].eq("")
        & df["match_tier"].astype(str).ne("")
        & df["match_tier"].astype(str).ne("exact_dimensions_raw"),
        "mechanism",
    ] = "reconciled_identifier_normalization"

    row_identity_blocker = (
        df["blocking_issue"]
        & df["residual_class"].astype(str).eq("row_identity")
        & df["mechanism"].eq("")
    )
    numeric_identity_candidate = (
        row_identity_blocker
        & df["evidence"].astype(str).str.contains(
            "blocking numeric identity candidate", case=False, regex=False, na=False
        )
    )
    numeric_evidence = df["evidence"].astype(str)
    df.loc[
        numeric_identity_candidate
        & numeric_evidence.str.contains(
            r"already_matched_output_count=(?:[1-9]\d*)", regex=True, na=False
        )
        & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_numeric_already_matched_output_alias"
    df.loc[
        numeric_identity_candidate
        & numeric_evidence.str.contains(
            r"candidate_output_count=(?:[2-9]|\d{2,})", regex=True, na=False
        )
        & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_numeric_multi_output_collision"
    df.loc[
        numeric_identity_candidate
        & numeric_evidence.str.contains(
            r"candidate_source_count=(?:[2-9]|\d{2,})", regex=True, na=False
        )
        & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_numeric_multi_source_collision"
    df.loc[
        numeric_identity_candidate & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_numeric_identity_candidate"
    df.loc[row_identity_blocker & parse_artifact & df["mechanism"].eq(""), "mechanism"] = (
        "blocking_identifier_parse_artifact"
    )
    source_only_detail = build_source_only_blocker_detail(df)
    if not source_only_detail.empty:
        source_only_map = source_only_detail[[
            "cik", "report_date", "accession_number", "source_row_id",
            "raw_investment_identifier", "mechanism",
        ]].rename(columns={"mechanism": "source_only_mechanism"})
        df = df.merge(
            source_only_map,
            on=[
                "cik", "report_date", "accession_number", "source_row_id",
                "raw_investment_identifier",
            ],
            how="left",
        )
        df.loc[
            df["status"].astype(str).eq("missing_from_pipeline")
            & df["mechanism"].eq("")
            & df["source_only_mechanism"].fillna("").ne(""),
            "mechanism",
        ] = df["source_only_mechanism"]
        df = df.drop(columns=["source_only_mechanism"])
    df.loc[
        df["status"].astype(str).eq("missing_from_pipeline") & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_source_unclassifiable_after_review"
    df.loc[
        df["status"].astype(str).eq("extra_in_pipeline") & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_pipeline_only_position"
    df.loc[
        df["status"].astype(str).eq("value_mismatch")
        & df["blocking_issue"]
        & extreme_fv_ratio
        & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_fair_value_scale_or_unit_candidate"
    df.loc[
        df["status"].astype(str).eq("value_mismatch")
        & df["blocking_issue"]
        & df["mechanism"].eq(""),
        "mechanism",
    ] = "blocking_fair_value_disagreement"
    df.loc[row_identity_blocker & df["mechanism"].eq(""), "mechanism"] = (
        "blocking_row_identity_unclassified"
    )

    reviewable = df[
        df["mechanism"].astype(str).ne("")
        & ~(
            df["status"].astype(str).eq("matched")
            & df["match_tier"].astype(str).eq("exact_dimensions_raw")
        )
    ].copy()
    if reviewable.empty:
        return _empty_residual_classification()

    reviewable["confidence"] = "high"
    documented_source_only = reviewable["mechanism"].astype(str).str.startswith(
        "documented_source_"
    )
    reviewable.loc[documented_source_only, "blocking_issue"] = False
    reviewable.loc[documented_source_only, "residual_class"] = "documented_exclusion"
    reviewable.loc[
        reviewable["mechanism"].isin([
            "blocking_fair_value_scale_or_unit_candidate",
            "blocking_fair_value_disagreement",
            "blocking_numeric_identity_candidate",
            "blocking_numeric_already_matched_output_alias",
            "blocking_numeric_multi_output_collision",
            "blocking_numeric_multi_source_collision",
            "blocking_row_identity_unclassified",
            "blocking_source_pct_leaf_parser_mismatch",
            "blocking_source_pct_ambiguous_after_review",
            "blocking_source_pct_hierarchy_parser_mismatch",
            "blocking_source_position_like_parser_mismatch",
            "blocking_source_short_plain_unresolved",
            "blocking_source_unclassifiable_after_review",
        ]),
        "confidence",
    ] = "medium"
    reviewable.loc[
        reviewable["mechanism"].eq("blocking_source_short_plain_unresolved"),
        "confidence",
    ] = "low"
    reviewable["recommended_action"] = reviewable["mechanism"].map(
        MECHANISM_RECOMMENDED_ACTIONS
    ).fillna("Review source reconciliation residual.")
    reviewable["reason"] = reviewable["mechanism"].map(MECHANISM_REASONS).fillna(
        "Source reconciliation residual classified by deterministic audit rule."
    )

    con = duckdb.connect()
    con.register("reviewable", reviewable)
    classified = con.execute("""
        WITH grouped AS (
            SELECT
                cik,
                any_value(entity_name) AS entity_name,
                report_date,
                COALESCE(residual_class, '') AS residual_class,
                COALESCE(status, '') AS status,
                COALESCE(calibrated_status, '') AS calibrated_status,
                COALESCE(match_tier, '') AS match_tier,
                COALESCE(blocking_issue, false) AS blocking_issue,
                mechanism,
                any_value(confidence) AS confidence,
                any_value(recommended_action) AS recommended_action,
                COUNT(*) AS issue_count,
                SUM(COALESCE(source_fair_value, 0)) AS affected_source_fair_value,
                SUM(COALESCE(output_fair_value, 0)) AS affected_output_fair_value,
                array_to_string(
                    list(DISTINCT raw_investment_identifier ORDER BY raw_investment_identifier)
                        FILTER (WHERE COALESCE(raw_investment_identifier, '') != '')[:5],
                    ' | '
                ) AS sample_identifiers,
                array_to_string(
                    list(DISTINCT accession_number ORDER BY accession_number)
                        FILTER (WHERE COALESCE(accession_number, '') != '')[:5],
                    ' | '
                ) AS sample_accessions,
                any_value(reason) AS reason
            FROM reviewable
            GROUP BY
                cik, report_date, residual_class, status, calibrated_status,
                match_tier, blocking_issue, mechanism
        )
        SELECT
            'SRCRES-' || lpad(
                CAST(row_number() OVER (
                    ORDER BY blocking_issue DESC, issue_count DESC, cik, report_date,
                             mechanism, status, match_tier
                ) AS VARCHAR),
                6,
                '0'
            ) AS classification_id,
            *
        FROM grouped
        ORDER BY blocking_issue DESC, issue_count DESC, cik, report_date, mechanism
    """).fetchdf()
    con.close()
    return classified[RESIDUAL_CLASSIFICATION_COLUMNS]


def build_source_reconciliation_residual_classification_markdown(
    classification_df: pd.DataFrame,
) -> str:
    """Build a durable markdown summary for residual classifications."""
    lines = [
        "# Source Reconciliation Residual Classification",
        "",
        "This audit groups source reconciliation residuals by deterministic mechanism. "
        "It does not change source reconciliation blocker semantics.",
        "",
    ]
    if classification_df.empty:
        lines.extend([
            "No non-plain source reconciliation residual groups were found.",
            "",
        ])
        return "\n".join(lines)

    df = classification_df.copy()
    df["issue_count"] = pd.to_numeric(df["issue_count"], errors="coerce").fillna(0)
    df["affected_source_fair_value"] = pd.to_numeric(
        df["affected_source_fair_value"], errors="coerce"
    ).fillna(0)
    df["affected_output_fair_value"] = pd.to_numeric(
        df["affected_output_fair_value"], errors="coerce"
    ).fillna(0)
    df["blocking_issue"] = df["blocking_issue"].astype(str).str.lower().isin(
        ["true", "1", "yes"]
    )

    total_groups = len(df)
    total_rows = int(df["issue_count"].sum())
    blocking = df[df["blocking_issue"]]
    non_blocking = df[~df["blocking_issue"]]
    lines.extend([
        "## Totals",
        "",
        f"- Residual groups: {total_groups}",
        f"- Residual rows: {total_rows}",
        f"- Blocking groups: {len(blocking)}",
        f"- Blocking rows: {int(blocking['issue_count'].sum()) if len(blocking) else 0}",
        f"- Non-blocking groups: {len(non_blocking)}",
        f"- Non-blocking rows: {int(non_blocking['issue_count'].sum()) if len(non_blocking) else 0}",
        "",
        "## Mechanisms",
        "",
        "| Mechanism | Groups | Rows | Blocking Rows | Source FV | Output FV |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ])

    by_mechanism = (
        df.groupby("mechanism", dropna=False)
        .agg(
            groups=("classification_id", "count"),
            rows=("issue_count", "sum"),
            blocking_rows=("issue_count", lambda s: s[df.loc[s.index, "blocking_issue"]].sum()),
            source_fv=("affected_source_fair_value", "sum"),
            output_fv=("affected_output_fair_value", "sum"),
        )
        .reset_index()
        .sort_values(["blocking_rows", "rows", "mechanism"], ascending=[False, False, True])
    )
    for row in by_mechanism.to_dict("records"):
        lines.append(
            f"| {row['mechanism']} | {int(row['groups'])} | {int(row['rows'])} | "
            f"{int(row['blocking_rows'])} | {row['source_fv']:,.0f} | {row['output_fv']:,.0f} |"
        )

    lines.extend(["", "## Top Blocking CIK-Quarters", ""])
    if blocking.empty:
        lines.extend(["No blocking residual groups.", ""])
    else:
        lines.extend([
            "| CIK | Entity | Report Date | Blocking Rows | Mechanisms |",
            "| --- | --- | --- | ---: | --- |",
        ])
        top_blocking = (
            blocking.groupby(["cik", "entity_name", "report_date"], dropna=False)
            .agg(
                rows=("issue_count", "sum"),
                mechanisms=("mechanism", lambda s: " | ".join(sorted(set(s.astype(str))))),
            )
            .reset_index()
            .sort_values(["rows", "cik", "report_date"], ascending=[False, True, True])
            .head(20)
        )
        for row in top_blocking.to_dict("records"):
            lines.append(
                f"| {row['cik']} | {row['entity_name']} | {row['report_date']} | "
                f"{int(row['rows'])} | {row['mechanisms']} |"
            )
        lines.append("")

    lines.extend(["## Fair-Value Mismatch Groups", ""])
    fv = df[df["mechanism"].isin([
        "blocking_fair_value_scale_or_unit_candidate",
        "blocking_fair_value_disagreement",
    ])]
    if fv.empty:
        lines.extend(["No fair-value mismatch groups.", ""])
    else:
        lines.extend([
            "| CIK | Entity | Report Date | Mechanism | Rows | Source FV | Output FV | Samples |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
        ])
        for row in fv.sort_values(
            ["issue_count", "cik", "report_date"], ascending=[False, True, True]
        ).to_dict("records"):
            lines.append(
                f"| {row['cik']} | {row['entity_name']} | {row['report_date']} | "
                f"{row['mechanism']} | {int(row['issue_count'])} | "
                f"{row['affected_source_fair_value']:,.0f} | "
                f"{row['affected_output_fair_value']:,.0f} | "
                f"{row['sample_identifiers']} |"
            )
        lines.append("")

    lines.extend(["## Recommended Next Fixes", ""])
    if blocking.empty:
        lines.extend(["No blocking fixes ranked because no blocking residuals were classified.", ""])
    else:
        lines.extend([
            "| Rank | Mechanism | Blocking Rows | Recommended Action |",
            "| ---: | --- | ---: | --- |",
        ])
        ranked = (
            blocking.groupby(["mechanism", "recommended_action"], dropna=False)
            .agg(rows=("issue_count", "sum"))
            .reset_index()
            .sort_values(["rows", "mechanism"], ascending=[False, True])
        )
        for rank, row in enumerate(ranked.to_dict("records"), start=1):
            lines.append(
                f"| {rank} | {row['mechanism']} | {int(row['rows'])} | "
                f"{row['recommended_action']} |"
            )
        lines.append("")

        lines.extend(["## Unresolved Blocking Groups", ""])
        lines.extend([
            "These groups remain blocking after deterministic identifier normalization, "
            "scale normalization, duplicate collapse, and source-rollup checks.",
            "",
            "| CIK | Entity | Report Date | Mechanism | Rows | Source FV | Output FV | Evidence Reviewed | Residual Risk | Samples |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
        ])
        unresolved = blocking.sort_values(
            ["issue_count", "cik", "report_date", "mechanism"],
            ascending=[False, True, True, True],
        )
        for row in unresolved.to_dict("records"):
            evidence_reviewed = (
                "cached XBRL facts vs unified BDC output; exact dimensions, "
                "identifier normalization, FV tolerance, duplicate, amendment, "
                "comparative-period, and rollup mechanisms checked"
            )
            residual_risk = {
                "blocking_source_only_position": (
                    "eligible source facts are absent from position-level output "
                    "or need a documented exclusion"
                ),
                "blocking_source_pct_hierarchy_parser_mismatch": (
                    "percentage/rate hierarchy text may encode real position facts"
                ),
                "blocking_source_position_like_parser_mismatch": (
                    "source row has company or instrument evidence but no output identity"
                ),
                "blocking_source_short_plain_unresolved": (
                    "short identifier lacks enough evidence to clear deterministically"
                ),
                "blocking_source_unclassifiable_after_review": (
                    "bounded deterministic review found no safe clearing mechanism"
                ),
                "blocking_pipeline_only_position": (
                    "pipeline output rows lack current-period source support"
                ),
                "blocking_identifier_parse_artifact": (
                    "row identity may still be distorted by category or parsed-text identifiers"
                ),
                "blocking_numeric_identity_candidate": (
                    "numeric evidence is not one-to-one enough to clear row identity"
                ),
                "blocking_numeric_already_matched_output_alias": (
                    "numeric alias points to an output row already reconciled by stronger evidence"
                ),
                "blocking_numeric_multi_output_collision": (
                    "numeric facts collide with multiple output rows"
                ),
                "blocking_numeric_multi_source_collision": (
                    "multiple source rows collide with the same numeric output facts"
                ),
                "blocking_fair_value_scale_or_unit_candidate": (
                    "source/output fair value scale remains unreconciled"
                ),
                "blocking_fair_value_disagreement": (
                    "source/output fair value differs without an accepted mechanism"
                ),
                "blocking_row_identity_unclassified": (
                    "row identity residual lacks a deterministic mechanism"
                ),
            }.get(row["mechanism"], "unresolved source reconciliation residual")
            lines.append(
                f"| {row['cik']} | {row['entity_name']} | {row['report_date']} | "
                f"{row['mechanism']} | {int(row['issue_count'])} | "
                f"{row['affected_source_fair_value']:,.0f} | "
                f"{row['affected_output_fair_value']:,.0f} | "
                f"{evidence_reviewed} | {residual_risk} | "
                f"{row['sample_identifiers']} |"
            )
        lines.append("")

    return "\n".join(lines)


SOURCE_FACT_COLUMNS = [
    "cik", "entity_name", "accession_number", "form_type", "filing_date",
    "report_date", "context_id", "period", "investment_identifier", "industry",
    "investment_type", "affiliation", "dimensions_raw", "concept_names",
    *_VALUE_COLUMNS,
]

SOURCE_FACT_MANIFEST_COLUMNS = [
    "accession_number", "cik", "report_date", "xbrl_local_path", "file_size",
    "file_hash", "filing_metadata_hash", "parse_status", "fact_row_count",
    "artifact_path", "computed_at",
]

RECONCILIATION_MANIFEST_COLUMNS = [
    "cik", "source_hash", "holdings_hash", "logic_hash", "override_hash",
    "detail_row_count", "metrics_row_count", "detail_artifact_path",
    "metrics_artifact_path", "computed_at",
]

RECONCILIATION_CACHE_STATUS_COLUMNS = [
    "computed_at", "run_mode", "dirty_cik_count", "clean_cik_count",
    "force", "full_invalidation", "elapsed_seconds",
]

LEGACY_RECONCILIATION_OUTPUTS = [
    SOURCE_RECONCILIATION_DETAIL_FILE,
    SOURCE_RECONCILIATION_METRICS_FILE,
    SOURCE_RECONCILIATION_CALIBRATION_REVIEW_FILE,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE,
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_MD_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE,
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLASSIFICATION_MD_FILE,
]


def _now_iso() -> str:
    return pd.Timestamp.utcnow().isoformat()


def _normalize_cik(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(10) if digits else ""


def _safe_partition_name(value: Any) -> str:
    text = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() else "_" for ch in text)
    return safe or "unknown"


def _sql_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _df_content_hash(df: pd.DataFrame, columns: list[str]) -> str:
    if df.empty:
        return hashlib.sha256(b"").hexdigest()
    work = df.copy()
    for col in columns:
        if col not in work.columns:
            work[col] = ""
    con = duckdb.connect()
    con.register("hash_input", work[columns])
    select_expr = " || chr(31) || ".join(
        f"COALESCE(CAST({_sql_ident(col)} AS VARCHAR), '')"
        for col in columns
    )
    order_expr = ", ".join(_sql_ident(col) for col in columns)
    value = con.execute(f"""
        SELECT sha256(COALESCE(string_agg({select_expr}, chr(30) ORDER BY {order_expr}), ''))
        FROM hash_input
    """).fetchone()[0]
    con.close()
    return str(value)


def _write_df_parquet_atomic(df: pd.DataFrame, path: Path, columns: Optional[list[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if columns is not None:
        for col in columns:
            if col not in out.columns:
                out[col] = ""
        out = out[columns]
    tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    con = duckdb.connect()
    con.register("out_df", out)
    con.execute(
        f"COPY (SELECT * FROM out_df) TO '{str(tmp_path).replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET)"
    )
    con.close()
    tmp_path.replace(path)


def _read_parquet_glob(paths: list[Path], columns: Optional[list[str]] = None) -> pd.DataFrame:
    existing = [p for p in paths if p.exists()]
    if not existing:
        return pd.DataFrame(columns=columns or [])
    path_list = "[" + ",".join(f"'{str(p).replace(chr(39), chr(39) * 2)}'" for p in existing) + "]"
    select_cols = "*" if columns is None else ", ".join(_sql_ident(c) for c in columns)
    con = duckdb.connect()
    df = con.execute(
        f"SELECT {select_cols} FROM read_parquet({path_list}, union_by_name=true)"
    ).fetchdf()
    con.close()
    return df


def _read_csv_manifest(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path, dtype=str)
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    return df[columns]


def _write_csv_atomic(df: pd.DataFrame, path: Path, columns: Optional[list[str]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.copy()
    if columns is not None:
        for col in columns:
            if col not in out.columns:
                out[col] = ""
        out = out[columns]
    tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    out.to_csv(tmp_path, index=False)
    tmp_path.replace(path)


def _filing_metadata_hash(filing: dict[str, Any]) -> str:
    keys = ["cik", "entity_name", "accession_number", "form_type", "filing_date", "report_date"]
    payload = "\x1f".join(str(filing.get(k, "") or "") for k in keys)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_single_xbrl_source_file_cached(
    xml_path: Path,
    filing_meta: dict[str, Any],
) -> tuple[pd.DataFrame, str]:
    try:
        etree.parse(str(xml_path))
    except Exception as exc:
        logger.debug("Source reconciliation XML parse failed for %s: %s", xml_path, exc)
        return pd.DataFrame(columns=SOURCE_FACT_COLUMNS), "parse_failed"
    rows = _extract_single_xbrl_source_file(xml_path, filing_meta)
    status = "ok" if rows else "no_facts"
    df = pd.DataFrame(rows)
    for col in SOURCE_FACT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[SOURCE_FACT_COLUMNS], status


def extract_bdc_source_facts_cached(
    force: bool = False,
    filings_index_df: Optional[pd.DataFrame] = None,
    filings_index_path: Optional[Path] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract source facts from cached XBRL files with accession-level Parquet reuse."""
    BDC_SOURCE_FACTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if filings_index_df is None:
        index_path = filings_index_path or BDC_FILINGS_INDEX_FILE
        if not index_path.exists():
            return pd.DataFrame(columns=SOURCE_FACT_COLUMNS), pd.DataFrame(columns=SOURCE_FACT_MANIFEST_COLUMNS)
        filings_index_df = pd.read_csv(index_path, dtype=str)
    if filings_index_df.empty or "xbrl_local_path" not in filings_index_df.columns:
        return pd.DataFrame(columns=SOURCE_FACT_COLUMNS), pd.DataFrame(columns=SOURCE_FACT_MANIFEST_COLUMNS)

    previous = _read_csv_manifest(
        BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE,
        SOURCE_FACT_MANIFEST_COLUMNS,
    )
    previous_by_accession = {
        str(row["accession_number"]): row for row in previous.to_dict("records")
    }
    manifest_rows: list[dict[str, Any]] = []
    artifact_paths: list[Path] = []

    for _, filing_row in filings_index_df.iterrows():
        filing = filing_row.to_dict()
        xml_path_text = str(filing.get("xbrl_local_path", "") or "").strip()
        if not xml_path_text:
            continue
        xml_path = Path(xml_path_text)
        if not xml_path.exists():
            continue
        accession = str(filing.get("accession_number", "") or "").strip()
        if not accession:
            accession = xml_path.stem
        artifact = BDC_SOURCE_FACTS_CACHE_DIR / f"{_safe_partition_name(accession)}.parquet"
        file_size = str(xml_path.stat().st_size)
        file_hash = _file_sha256(xml_path)
        meta_hash = _filing_metadata_hash(filing)
        prev = previous_by_accession.get(accession)
        reuse = (
            not force
            and prev is not None
            and prev.get("xbrl_local_path", "") == str(xml_path)
            and prev.get("file_size", "") == file_size
            and prev.get("file_hash", "") == file_hash
            and prev.get("filing_metadata_hash", "") == meta_hash
            and artifact.exists()
        )
        if reuse:
            parse_status = prev.get("parse_status", "")
            fact_count = prev.get("fact_row_count", "0")
        else:
            facts, parse_status = _extract_single_xbrl_source_file_cached(xml_path, filing)
            facts = facts.astype({col: "string" for col in SOURCE_FACT_COLUMNS})
            fact_count = str(len(facts))
            _write_df_parquet_atomic(facts, artifact, SOURCE_FACT_COLUMNS)
        manifest_rows.append({
            "accession_number": accession,
            "cik": _normalize_cik(filing.get("cik", "")),
            "report_date": str(filing.get("report_date", "") or ""),
            "xbrl_local_path": str(xml_path),
            "file_size": file_size,
            "file_hash": file_hash,
            "filing_metadata_hash": meta_hash,
            "parse_status": parse_status,
            "fact_row_count": fact_count,
            "artifact_path": str(artifact),
            "computed_at": _now_iso(),
        })
        artifact_paths.append(artifact)

    manifest = pd.DataFrame(manifest_rows, columns=SOURCE_FACT_MANIFEST_COLUMNS)
    _write_csv_atomic(manifest, BDC_SOURCE_FACTS_CACHE_MANIFEST_FILE, SOURCE_FACT_MANIFEST_COLUMNS)
    return _read_parquet_glob(artifact_paths, SOURCE_FACT_COLUMNS), manifest


def compute_bdc_holdings_hashes(unified_df: pd.DataFrame) -> pd.DataFrame:
    """Hash per-CIK BDC holdings columns used by source reconciliation."""
    columns = [
        "source", "cik", "entity_name", "report_date", "period",
        "accession_number", "filing_date", "bdc_form_type",
        "bdc_investment_identifier", "bdc_dimensions_raw", "issuer_name",
        "instrument_description", "index_classification", "asset_category",
        "issuer_category", "maturity_date", *VALUE_COLUMNS, *RATE_COLUMNS,
    ]
    df = unified_df.copy()
    for col in columns:
        if col not in df.columns:
            df[col] = ""
    con = duckdb.connect()
    con.register("holdings", df[columns])
    value_expr = " || chr(31) || ".join(
        f"COALESCE(CAST({_sql_ident(col)} AS VARCHAR), '')"
        for col in columns
    )
    order_expr = ", ".join(_sql_ident(col) for col in columns)
    hashes = con.execute(f"""
        SELECT
            LPAD(regexp_replace(CAST(cik AS VARCHAR), '[^0-9]', '', 'g'), 10, '0') AS cik,
            sha256(COALESCE(string_agg({value_expr}, chr(30) ORDER BY {order_expr}), '')) AS holdings_hash,
            COUNT(*) AS holdings_row_count
        FROM holdings
        WHERE lower(CAST(source AS VARCHAR)) = 'bdc'
        GROUP BY 1
    """).fetchdf()
    con.close()
    return hashes


def _compute_source_hashes(source_manifest: pd.DataFrame) -> pd.DataFrame:
    if source_manifest.empty:
        return pd.DataFrame(columns=["cik", "source_hash", "source_accession_count"])
    con = duckdb.connect()
    con.register("source_manifest", source_manifest)
    hashes = con.execute("""
        SELECT
            cik,
            sha256(COALESCE(string_agg(
                accession_number || chr(31) || file_hash || chr(31) || filing_metadata_hash
                || chr(31) || parse_status || chr(31) || fact_row_count,
                chr(30) ORDER BY accession_number
            ), '')) AS source_hash,
            COUNT(*) AS source_accession_count
        FROM source_manifest
        GROUP BY cik
    """).fetchdf()
    con.close()
    return hashes


def compute_reconciliation_logic_hash() -> str:
    """Hash the reconciliation code paths that affect source/output matching."""
    pieces = [
        inspect.getsource(reconcile_bdc_source_to_holdings),
        inspect.getsource(build_source_reconciliation_metrics),
        inspect.getsource(_coerce_source_df),
        inspect.getsource(_coerce_output_df),
        inspect.getsource(_norm_identifier_sql),
        inspect.getsource(_staging_clean_identifier_sql),
        inspect.getsource(_material_mismatch_sql),
    ]
    return hashlib.sha256("\n\n".join(pieces).encode("utf-8")).hexdigest()


def _compute_override_hash() -> str:
    overrides_file = resolve_bdc_aggregate_overrides_file()
    if not overrides_file.exists():
        return hashlib.sha256(b"").hexdigest()
    return _file_sha256(overrides_file)


def plan_dirty_reconciliation_ciks(
    source_manifest: pd.DataFrame,
    holdings_hashes: pd.DataFrame,
    logic_hash: str,
    override_hash: str,
    force: bool = False,
) -> pd.DataFrame:
    """Compare current hashes with the CIK-level reconciliation manifest."""
    source_hashes = _compute_source_hashes(source_manifest)
    current = pd.merge(source_hashes, holdings_hashes, on="cik", how="outer").fillna("")
    previous = _read_csv_manifest(
        SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE,
        RECONCILIATION_MANIFEST_COLUMNS,
    )
    previous_by_cik = {str(row["cik"]): row for row in previous.to_dict("records")}
    rows: list[dict[str, Any]] = []
    for row in current.to_dict("records"):
        cik = str(row.get("cik", ""))
        prev = previous_by_cik.get(cik)
        detail_artifact = SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR / f"{_safe_partition_name(cik)}.parquet"
        metrics_artifact = SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR / f"{_safe_partition_name(cik)}.parquet"
        reason = []
        if force:
            reason.append("force")
        if prev is None:
            reason.append("missing_manifest")
        else:
            if prev.get("source_hash", "") != str(row.get("source_hash", "")):
                reason.append("source_hash")
            if prev.get("holdings_hash", "") != str(row.get("holdings_hash", "")):
                reason.append("holdings_hash")
            if prev.get("logic_hash", "") != logic_hash:
                reason.append("logic_hash")
            if prev.get("override_hash", "") != override_hash:
                reason.append("override_hash")
            if not Path(prev.get("detail_artifact_path", "")).exists():
                reason.append("missing_detail_artifact")
            if not Path(prev.get("metrics_artifact_path", "")).exists():
                reason.append("missing_metrics_artifact")
        rows.append({
            "cik": cik,
            "source_hash": str(row.get("source_hash", "")),
            "holdings_hash": str(row.get("holdings_hash", "")),
            "logic_hash": logic_hash,
            "override_hash": override_hash,
            "dirty": bool(reason),
            "dirty_reason": "|".join(reason),
            "detail_artifact_path": str(detail_artifact),
            "metrics_artifact_path": str(metrics_artifact),
        })
    return pd.DataFrame(rows)


def _legacy_outputs_exist() -> bool:
    return all(path.exists() for path in LEGACY_RECONCILIATION_OUTPUTS)


def _assemble_legacy_reconciliation_outputs(detail: pd.DataFrame, metrics: pd.DataFrame) -> None:
    source_recon_review = build_reconciliation_calibration_review(detail)
    residual = build_source_reconciliation_residual_classification(detail)
    residual_md = build_source_reconciliation_residual_classification_markdown(residual)
    source_only_detail = build_source_only_blocker_detail(detail)
    source_only_clusters = build_source_only_blocker_clusters(source_only_detail)
    source_only_md = build_source_only_blocker_markdown(source_only_detail, source_only_clusters)

    detail.to_csv(SOURCE_RECONCILIATION_DETAIL_FILE, index=False)
    metrics.to_csv(SOURCE_RECONCILIATION_METRICS_FILE, index=False)
    source_recon_review.to_csv(SOURCE_RECONCILIATION_CALIBRATION_REVIEW_FILE, index=False)
    residual.to_csv(SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_FILE, index=False)
    SOURCE_RECONCILIATION_RESIDUAL_CLASSIFICATION_MD_FILE.write_text(residual_md, encoding="utf-8")
    source_only_detail.to_csv(SOURCE_RECONCILIATION_SOURCE_ONLY_DETAIL_FILE, index=False)
    source_only_clusters.to_csv(SOURCE_RECONCILIATION_SOURCE_ONLY_CLUSTERS_FILE, index=False)
    SOURCE_RECONCILIATION_SOURCE_ONLY_CLASSIFICATION_MD_FILE.write_text(source_only_md, encoding="utf-8")


def _read_cached_detail_for_adapter() -> pd.DataFrame:
    artifacts = sorted(SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR.glob("*.parquet"))
    if not artifacts:
        return _empty_detail()
    path_list = "[" + ",".join(f"'{str(p).replace(chr(39), chr(39) * 2)}'" for p in artifacts) + "]"
    con = duckdb.connect()
    df = con.execute(f"""
        SELECT {", ".join(_sql_ident(c) for c in DETAIL_COLUMNS)}
        FROM read_parquet({path_list}, union_by_name=true)
        WHERE status IN ('missing_from_pipeline', 'extra_in_pipeline', 'value_mismatch')
          AND COALESCE(blocking_issue, false)
    """).fetchdf()
    con.close()
    return df


def run_bdc_source_reconciliation_cached(
    unified_df: Optional[pd.DataFrame] = None,
    filings_index_df: Optional[pd.DataFrame] = None,
    force: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run CIK-partitioned cached BDC source reconciliation."""
    started = time.time()
    SOURCE_RECONCILIATION_DETAIL_BY_CIK_DIR.mkdir(parents=True, exist_ok=True)
    SOURCE_RECONCILIATION_METRICS_BY_CIK_DIR.mkdir(parents=True, exist_ok=True)
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            return _empty_detail(), _empty_metrics(), pd.DataFrame(columns=RECONCILIATION_CACHE_STATUS_COLUMNS)
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)

    source_df, source_manifest = extract_bdc_source_facts_cached(
        force=force,
        filings_index_df=filings_index_df,
    )
    holdings_hashes = compute_bdc_holdings_hashes(unified_df)
    logic_hash = compute_reconciliation_logic_hash()
    override_hash = _compute_override_hash()
    plan = plan_dirty_reconciliation_ciks(
        source_manifest,
        holdings_hashes,
        logic_hash,
        override_hash,
        force=force,
    )
    dirty_ciks = set(plan.loc[plan["dirty"], "cik"].astype(str)) if not plan.empty else set()
    full_invalidation = bool(
        force
        or (not plan.empty and plan["dirty_reason"].astype(str).str.contains("logic_hash|override_hash", regex=True).any())
    )

    previous_manifest = _read_csv_manifest(
        SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE,
        RECONCILIATION_MANIFEST_COLUMNS,
    )
    previous_by_cik = {str(row["cik"]): row for row in previous_manifest.to_dict("records")}
    manifest_rows: list[dict[str, Any]] = []
    batch_recomputed_detail: Optional[pd.DataFrame] = None
    batch_recomputed_metrics: Optional[pd.DataFrame] = None
    batch_recompute = full_invalidation or len(dirty_ciks) > 20
    if dirty_ciks and batch_recompute:
        batch_recomputed_detail, batch_recomputed_metrics = reconcile_bdc_source_to_holdings(
            source_df,
            unified_df,
        )
        if not batch_recomputed_detail.empty:
            batch_recomputed_detail["cik"] = batch_recomputed_detail["cik"].astype(str).map(_normalize_cik)
        if not batch_recomputed_metrics.empty:
            batch_recomputed_metrics["cik"] = batch_recomputed_metrics["cik"].astype(str).map(_normalize_cik)

    for row in plan.to_dict("records"):
        cik = str(row["cik"])
        detail_artifact = Path(row["detail_artifact_path"])
        metrics_artifact = Path(row["metrics_artifact_path"])
        if cik in dirty_ciks:
            if batch_recompute:
                detail_part = (
                    batch_recomputed_detail[batch_recomputed_detail["cik"].eq(cik)].copy()
                    if batch_recomputed_detail is not None and not batch_recomputed_detail.empty
                    else _empty_detail()
                )
                metrics_part = (
                    batch_recomputed_metrics[batch_recomputed_metrics["cik"].eq(cik)].copy()
                    if batch_recomputed_metrics is not None and not batch_recomputed_metrics.empty
                    else _empty_metrics()
                )
            else:
                source_part = source_df[source_df.get("cik", pd.Series(dtype=str)).astype(str).map(_normalize_cik).eq(cik)].copy()
                holdings_part = unified_df[
                    unified_df.get("cik", pd.Series(dtype=str)).astype(str).map(_normalize_cik).eq(cik)
                    & unified_df.get("source", pd.Series(dtype=str)).astype(str).str.lower().eq("bdc")
                ].copy()
                detail_part, metrics_part = reconcile_bdc_source_to_holdings(source_part, holdings_part)
            _write_df_parquet_atomic(detail_part, detail_artifact, DETAIL_COLUMNS)
            _write_df_parquet_atomic(metrics_part, metrics_artifact, METRIC_COLUMNS)
            detail_count = len(detail_part)
            metrics_count = len(metrics_part)
        else:
            prev = previous_by_cik.get(cik, {})
            detail_count = prev.get("detail_row_count", "")
            metrics_count = prev.get("metrics_row_count", "")
        manifest_rows.append({
            "cik": cik,
            "source_hash": row["source_hash"],
            "holdings_hash": row["holdings_hash"],
            "logic_hash": logic_hash,
            "override_hash": override_hash,
            "detail_row_count": detail_count,
            "metrics_row_count": metrics_count,
            "detail_artifact_path": str(detail_artifact),
            "metrics_artifact_path": str(metrics_artifact),
            "computed_at": _now_iso(),
        })

    manifest = pd.DataFrame(manifest_rows, columns=RECONCILIATION_MANIFEST_COLUMNS)
    _write_csv_atomic(manifest, SOURCE_RECONCILIATION_CACHE_MANIFEST_FILE, RECONCILIATION_MANIFEST_COLUMNS)

    all_metrics = _read_parquet_glob(
        [Path(p) for p in manifest["metrics_artifact_path"].tolist()],
        METRIC_COLUMNS,
    )
    if not all_metrics.empty:
        all_metrics = all_metrics[METRIC_COLUMNS].sort_values(["cik", "report_date"]).reset_index(drop=True)

    need_legacy = bool(dirty_ciks) or not _legacy_outputs_exist()
    if need_legacy:
        all_detail = _read_parquet_glob(
            [Path(p) for p in manifest["detail_artifact_path"].tolist()],
            DETAIL_COLUMNS,
        )
        if not all_detail.empty:
            all_detail = all_detail[DETAIL_COLUMNS].sort_values(
                ["cik", "report_date", "accession_number", "raw_investment_identifier", "status"]
            ).reset_index(drop=True)
        _assemble_legacy_reconciliation_outputs(all_detail, all_metrics)
        detail_for_reports = all_detail
    else:
        detail_for_reports = _read_cached_detail_for_adapter()

    status = pd.DataFrame([{
        "computed_at": _now_iso(),
        "run_mode": "force" if force else ("dirty" if dirty_ciks else "clean"),
        "dirty_cik_count": len(dirty_ciks),
        "clean_cik_count": max(len(plan) - len(dirty_ciks), 0),
        "force": force,
        "full_invalidation": full_invalidation,
        "elapsed_seconds": round(time.time() - started, 3),
    }], columns=RECONCILIATION_CACHE_STATUS_COLUMNS)
    _write_csv_atomic(status, SOURCE_RECONCILIATION_CACHE_STATUS_FILE, RECONCILIATION_CACHE_STATUS_COLUMNS)
    return detail_for_reports, all_metrics, status


def run_bdc_source_reconciliation(
    unified_df: Optional[pd.DataFrame] = None,
    filings_index_df: Optional[pd.DataFrame] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Read cached BDC XBRL source facts and reconcile to unified holdings."""
    if unified_df is None:
        if not UNIFIED_HOLDINGS_FILE.exists():
            logger.error("Unified holdings file not found: %s", UNIFIED_HOLDINGS_FILE)
            return _empty_detail(), _empty_metrics()
        unified_df = pd.read_csv(UNIFIED_HOLDINGS_FILE, dtype=str)
    source_df = extract_bdc_source_facts_from_xbrl(filings_index_df=filings_index_df)
    return reconcile_bdc_source_to_holdings(source_df, unified_df)
