"""Extract comprehensive fund-level highlights from cached BDC XBRL filings.

Extracts ~40 fund-level XBRL concepts across categories:
  - Per-share / NAV (instant, per-class)
  - Financial highlights (duration, per-class): total return, expense ratios, etc.
  - Distributions (duration, per-class)
  - Capital activity (duration, per-class): stock issuance, repurchases, DRIP
  - Income / PIK (duration, entity-level mostly)
  - Borrowing (instant, entity-level)
  - Fair value hierarchy (instant/duration, entity-level)

Handles both instant and duration contexts, and both entity-level (no dimensions)
and per-share-class (StatementClassOfStockAxis) contexts.

Normalization rules (applied post-extraction):
  1. Filter non-share-class dimension members (DRIP, issuance date, etc.)
  2. Canonical share class mapping (ClassIMember -> ClassI, etc.)
  3. Concept pollution cleanup (null entity-dollar columns on per-class rows)
  4. Duration scaling for flow columns (annual -> quarterly, per bdc_fund_income)
  5. Ratio format normalization (decimal -> pct, per fund_financials convention)

Public API
----------
extract_bdc_fund_highlights(filings_index=None) -> pd.DataFrame
"""

import logging
import re
import time
from datetime import date
from typing import Any, Optional

import pandas as pd
from lxml import etree

from pipeline.config import (
    BDC_FILINGS_INDEX_FILE,
    BDC_FUND_HIGHLIGHTS_FILE,
)
from pipeline.fund_highlights_wrapper import (
    HighlightsWrapperSpec,
    load_highlights_wrapper,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Concept map: substring-match-first-wins (longest first per convention)
# ---------------------------------------------------------------------------
HIGHLIGHTS_CONCEPT_MAP = [
    # --- Per-share / NAV (instant) ---
    ("netassetvaluepershare", "nav_per_share"),
    ("commonstocksharesoutstanding", "shares_outstanding"),
    ("entitycommonstocksharesoutstanding", "shares_outstanding"),
    ("assetsnet", "assets_net"),

    # --- Financial highlights (duration, per-class) ---
    ("investmentcompanytotalreturn", "total_return"),
    ("investmentcompanyportfolioturnover", "portfolio_turnover"),
    ("investmentcompanygainlossoninvestmentpershare", "gain_loss_per_share"),
    ("investmentcompanydistributiontoshareholderspershare", "distribution_per_share"),
    ("investmentcompanyinvestmentincomelosspershare", "nii_per_share"),
    ("investmentcompanyinvestmentincomelossfromoperationspershare", "ops_per_share"),
    ("investmentcompanyexpenseratioincludingincentivefee", "expense_ratio_incl_incentive"),
    # Note: InvestmentCompanyExpenseAfterReductionOfFeeWaiverAndReimbursement is
    # total expenses in DOLLARS (unitRef=USD), not an expense ratio despite the
    # name. Mapped to expenses_after_waiver (dollar amount, flow column).
    ("investmentcompanyexpenseafterreductionoffeewaiverandreimbursement", "expenses_after_waiver"),
    ("investmentcompanyratioofexpensesnetofwaiversexcludinginterestexpensetoaveragenetassets", "expense_ratio_ex_interest"),
    ("expensesnetofwaiversexcludingmanagementandincentivefeesandinterestexpense", "expense_ratio_ex_mgmt_incentive"),
    ("investmentcompanyinvestmentincomelossratio", "nii_ratio"),
    ("assetcoverageperunit", "asset_coverage_per_unit"),
    ("lineofcreditassetcoverageperunit", "asset_coverage_per_unit"),

    # --- Distributions (duration, per-class) ---
    ("commonstockdividendspersharedeclared", "dividends_per_share_declared"),
    ("investmentcompanydividenddistribution", "dividend_distribution"),
    ("investmentcompanydistributionordinaryincome", "distribution_ordinary_income"),

    # --- Capital activity (duration, per-class) ---
    ("stockissuedduringperiodvaluenewissues", "stock_issued_value"),
    ("stockissuedduringperiodsharesnewissues", "stock_issued_shares"),
    ("stockrepurchasedduringperiodvalue", "stock_repurchased_value"),
    ("stockrepurchasedduringperiodshares", "stock_repurchased_shares"),
    ("stockissuedduringperiodvaluedividendreinvestmentplan", "drip_value"),
    ("stockissuedduringperiodsharesdividendreinvestmentplan", "drip_shares"),
    ("investmentcompanyincreasedecreasefromsharetransaction", "net_share_transactions"),
    ("percentageofsharesrepurchased", "pct_shares_repurchased"),
    ("percentageofoutstandingsharesrepurchase", "pct_shares_repurchased"),
    ("stockissuedduringperiodsharesperiodincreasedecrease", "net_shares_period_change"),
    ("proceedsfromissuanceofcommonstock", "proceeds_from_issuance"),
    ("paymentsforrepurchaseofcommonstock", "payments_for_repurchases"),

    # --- Income / PIK (duration, entity-level mostly) ---
    ("interestincomeoperatingpaidincash", "cash_interest_income"),
    ("administrativefeesexpense", "admin_fee_expense"),
    ("incentivefeeexpense", "incentive_fee_expense"),
    ("managementfeeexpense", "management_fee_expense"),
    ("realizedinvestmentgainslosses", "realized_gains_losses"),
    ("debtandequitysecuritiesrealizedgainloss", "realized_gains_losses"),
    ("unrealizedgainlossoninvestments", "unrealized_gains_losses"),
    ("netunrealizedappreciationdepreciationoninvestments", "unrealized_gains_losses"),
    ("debtandequitysecuritiesunrealizedgainloss", "unrealized_gains_losses"),
    ("grossinvestmentincomeoperating", "total_investment_income"),
    ("totalinvestmentincome", "total_investment_income"),
    ("netinvestmentincome", "net_investment_income"),
    ("investmentincomenet", "net_investment_income"),
    ("interestexpensedebt", "interest_expense"),
    ("interestanddebtexpense", "interest_expense"),
    ("interestexpense", "interest_expense"),
    ("investmentincomeinvestmentexpense", "total_expenses"),

    # --- Borrowing (instant, entity-level) ---
    ("lineofcreditfacilitymaximumborrowingcapacity", "facility_max_capacity"),
    ("lineofcreditfacilitycurrentborrowingcapacity", "facility_remaining_capacity"),
    ("debtinstrumentbasisspreadonvariablerate1", "fund_debt_spread"),
    ("investmentcompanyseniorsecurityindebtednessassetcoverageratio", "senior_security_coverage_ratio"),
    ("longtermdebt", "long_term_debt"),
    ("debtlongtermandshorttermcombinedamount", "total_debt"),

    # --- Fair value hierarchy (instant/duration, entity-level) ---
    ("fairvaluemeasurementwithunobservableinputsreconciliationrecurringbasisassetvalue", "fv_level3_balance"),
    ("fairvaluemeasurementwithunobservableinputsreconciliationrecurringbasisassetpurchases", "fv_level3_purchases"),
    ("fairvaluemeasurementwithunobservableinputsreconciliationrecurringbasisassetpurchasessalesissuancessettlements", "fv_level3_net_activity"),
    ("fairvaluemeasurementwithunobservableinputsreconciliationrecurringbasisassettransfersintolevel3", "fv_level3_transfers_in"),
    ("fairvaluemeasurementwithunobservableinputsreconciliationrecurringbasisassettransfersoutoflevel3", "fv_level3_transfers_out"),
    ("fairvaluemeasurementwithunobservableinputsreconciliationrecurringbasisassetgainlossincludedinearnings1", "fv_level3_gain_loss"),

    # --- Additional balance sheet (instant) ---
    ("assets", "total_assets"),
    ("liabilities", "total_liabilities"),
    ("stockholdersequity", "stockholders_equity"),
]

# Investment-level dimension axes to REJECT -- contexts with these
# are position-level, not fund-level.
_INVESTMENT_AXES = {
    "investmentidentifieraxis",
    "investmenttypeaxis",
    "investmentcountryaxis",
    "investmentcompanynonconsolidatedinvesteeaxis",
    "investmentindustryaxis",
    "investmentsecondaryaxis",
    "investmentissuernameaxis",
    "financingreceivablerecordedinvestmentbyclassoffinancingreceivableaxis",
    "scheduleofinvestmentsaxis",
}

# Dimension axis for share class -- we KEEP contexts with only this dimension
_SHARE_CLASS_AXIS = "statementclassofstockaxis"


# ---------------------------------------------------------------------------
# Normalization rule 1: non-share-class member filter
# Patterns that indicate the StatementClassOfStockAxis member is NOT
# an actual share class. These leak through because filers reuse the axis
# for issuance dates, distribution types, DRIP breakouts, etc.
# ---------------------------------------------------------------------------
_NON_SHARE_CLASS_RE = re.compile(
    r"(?i)"
    r"IssuanceDate|"           # Per-issuance breakouts (e.g. IssuanceDateOneMember)
    r"Fiscal\d|"               # Per-fiscal-year transactions
    r"FiscalTwo|"              # Spelled-out fiscal year variants
    r"DRIPMember|"
    r"DividendReinvestment|"
    r"BasicMember|"
    r"DilutedMember|"
    r"OrdinaryIncomeMember|"
    r"LongTermCapitalGains|"
    r"Short-TermCapitalGains|"
    r"CapitalContributionMember|"
    r"CommonGrossProceeds|"
    r"CommonOfferingExpenses|"
    r"IntellectualProperty|"
    r"ReverseStockSplit|"
    r"VariableInterestEntity|"
    r"NotesPayable|"
    r"TwoThousand.*Payable|"    # Debt instrument members (e.g. TwoThousandsAndTwentySixNotes...)
    r"Security1Common|"
    r"TotalSourceOfDistribution|"
    r"InitialConversion|"
    # Date-named members (December292022Member, March312023Member, etc.)
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\d"
)


# ---------------------------------------------------------------------------
# Normalization rule 2: canonical share class mapping
# Follows entity_resolution.py pattern -- regex-based, priority-ordered.
# ---------------------------------------------------------------------------
# Match "ClassI", "ClassD", "ClassS" etc. The letter must be followed by
# a known suffix (Member, Shares, Common, Units, Stock) or end-of-string,
# so "ClassIMember", "ClassISharesMember", and "ClassMMember" all match,
# but "ClassInstitutional" does NOT.
_CLASS_LETTER_RE = re.compile(
    r"(?i)Class\s*([A-Z])(?=Member|Shares|Common|Units|Stock|$)"
)
_COMMON_CLASS_RE = re.compile(
    r"(?i)CommonClass([A-Z])(?=Member|Shares|Common|Units|Stock|$)"
)
_SERIES_PREFERRED_RE = re.compile(r"(?i)Series\s*([A-Z])\d*\s*(?:Convertible\s*)?Preferred")
_PREFERRED_CLASS_RE = re.compile(r"(?i)Preferred\s*(?:Class|Stock)?\s*([A-Z])\s*Member")


def _canonical_share_class(raw: str, aliases: Optional[dict[str, str]] = None) -> str:
    """Map raw XBRL member name to canonical share class label.

    Parameters
    ----------
    raw : str
        Raw XBRL member name (e.g. 'ClassICommonSharesMember').
    aliases : dict, optional
        Per-CIK aliases from a highlights wrapper.  Keys are substrings
        matched against the raw member name; values are canonical labels.
        Checked before the global regex chain.
    """
    if not raw:
        return ""

    # Per-CIK aliases take priority
    if aliases:
        for substring, canonical in aliases.items():
            if substring in raw:
                return canonical

    upper = raw.upper().replace(" ", "")

    # Institutional class variants -> ClassI
    if "INSTITUTIONAL" in upper:
        return "ClassI"

    # Multi-letter class codes (SP, etc.) before single-letter matching
    if "CLASSSP" in upper or "COMMONCLASSSP" in upper:
        return "ClassSP"

    # CommonClassX pattern (e.g. CommonClassIMember, CommonClassDMember)
    m = _COMMON_CLASS_RE.search(raw)
    if m:
        return f"Class{m.group(1).upper()}"

    # ClassX patterns (e.g. ClassISharesMember, ClassDCommonSharesMember,
    # ClassMMember, ClassNSharesMember)
    m = _CLASS_LETTER_RE.search(raw)
    if m:
        return f"Class{m.group(1).upper()}"

    # Preferred stock series (e.g. SeriesAPreferredStockMember)
    m = _SERIES_PREFERRED_RE.search(raw)
    if m:
        return f"PreferredSeries{m.group(1).upper()}"
    m = _PREFERRED_CLASS_RE.search(raw)
    if m:
        return f"PreferredSeries{m.group(1).upper()}"
    if "PREFERRED" in upper:
        return "Preferred"

    # Plain common stock / shares / units
    if any(tok in upper for tok in [
        "COMMONSTOCK", "COMMONSHARE", "COMMONUNIT",
        "COMMONEQUITY", "ORDINARYSHARE", "CAPITALSTOCK",
    ]):
        return "CommonStock"

    # Depositary shares
    if "DEPOSITARY" in upper or "DEPOSITORY" in upper:
        return "DepositaryShares"

    # Warrant
    if "WARRANT" in upper:
        return "Warrant"

    # Unrecognized -- keep original for audit trail
    return raw


# ---------------------------------------------------------------------------
# Normalization rule 3: concept pollution guard
# In per-class contexts, dollar-amount columns actually contain per-share or
# ratio values (the XBRL concept is the same but the axis changes semantics).
# Null these out on per-class rows to prevent cross-CIK comparison errors.
# ---------------------------------------------------------------------------
_ENTITY_ONLY_DOLLAR_COLS = frozenset([
    "total_investment_income", "net_investment_income",
    "realized_gains_losses", "unrealized_gains_losses",
    "interest_expense", "total_expenses",
    "admin_fee_expense", "incentive_fee_expense", "management_fee_expense",
    "cash_interest_income", "expenses_after_waiver",
    "total_assets", "total_liabilities", "stockholders_equity",
    "facility_max_capacity", "facility_remaining_capacity",
    "long_term_debt", "total_debt",
    "fv_level3_balance", "fv_level3_purchases", "fv_level3_net_activity",
    "fv_level3_transfers_in", "fv_level3_transfers_out", "fv_level3_gain_loss",
    "fund_debt_spread", "senior_security_coverage_ratio",
    "assets_net",
])


# ---------------------------------------------------------------------------
# Normalization rule 4: duration scaling for flow columns
# Same pattern as bdc_fund_income._derive_quarterly_income():
#   dm 2-4 -> quarterly (scale=1), dm 11-13 -> annual (/4), else -> 3/dm
# ---------------------------------------------------------------------------
_FLOW_COLS = [
    "total_investment_income", "net_investment_income",
    "realized_gains_losses", "unrealized_gains_losses",
    "interest_expense", "total_expenses",
    "admin_fee_expense", "incentive_fee_expense", "management_fee_expense",
    "cash_interest_income", "expenses_after_waiver",
    "stock_issued_value", "stock_repurchased_value", "drip_value",
    "stock_issued_shares", "stock_repurchased_shares", "drip_shares",
    "dividend_distribution", "distribution_ordinary_income",
    "net_share_transactions", "net_shares_period_change",
    "proceeds_from_issuance", "payments_for_repurchases",
    "fv_level3_purchases", "fv_level3_net_activity",
    "fv_level3_transfers_in", "fv_level3_transfers_out", "fv_level3_gain_loss",
]


# ---------------------------------------------------------------------------
# Normalization rule 5: ratio format normalization
# Follows fund_financials.py Fix 2 convention:
#   |val| <= 1.0 -> val * 100 (decimal to pct)
#   |val| > max_abs_pct -> NULL (reject outlier)
#   else -> keep (already in pct)
# max_abs_pct varies by field to avoid clipping legitimate values.
# ---------------------------------------------------------------------------
_RATIO_FIELDS = {
    # field: max_abs in percentage terms (above this -> null)
    "total_return": 200.0,         # >200% total return is suspect
    "portfolio_turnover": 500.0,   # high-turnover funds can exceed 100%
    "expense_ratio_incl_incentive": 100.0,
    "expense_ratio_ex_interest": 100.0,
    "expense_ratio_ex_mgmt_incentive": 100.0,
    "nii_ratio": 100.0,
    "pct_shares_repurchased": 100.0,
}


# ---------------------------------------------------------------------------
# Output columns
# ---------------------------------------------------------------------------
HIGHLIGHTS_COLUMNS = [
    "cik", "entity_name", "accession_number", "form_type", "filing_date",
    "period_end", "period_start", "period_type", "duration_months",
    "share_class", "report_quarter",
    # Per-share / NAV
    "nav_per_share", "shares_outstanding", "assets_net",
    # Financial highlights
    "total_return", "portfolio_turnover", "gain_loss_per_share",
    "distribution_per_share", "nii_per_share", "ops_per_share",
    "expense_ratio_incl_incentive", "expenses_after_waiver",
    "expense_ratio_ex_interest", "expense_ratio_ex_mgmt_incentive",
    "nii_ratio", "asset_coverage_per_unit",
    # Distributions
    "dividends_per_share_declared", "dividend_distribution",
    "distribution_ordinary_income",
    # Capital activity
    "stock_issued_value", "stock_issued_shares",
    "stock_repurchased_value", "stock_repurchased_shares",
    "drip_value", "drip_shares",
    "net_share_transactions", "pct_shares_repurchased",
    "net_shares_period_change", "proceeds_from_issuance",
    "payments_for_repurchases",
    # Income / PIK
    "cash_interest_income",
    "admin_fee_expense", "incentive_fee_expense", "management_fee_expense",
    "realized_gains_losses", "unrealized_gains_losses",
    "total_investment_income", "net_investment_income",
    "interest_expense", "total_expenses",
    # Borrowing
    "facility_max_capacity", "facility_remaining_capacity",
    "fund_debt_spread", "senior_security_coverage_ratio",
    "long_term_debt", "total_debt",
    # Fair value
    "fv_level3_balance", "fv_level3_purchases", "fv_level3_net_activity",
    "fv_level3_transfers_in", "fv_level3_transfers_out", "fv_level3_gain_loss",
    # Balance sheet
    "total_assets", "total_liabilities", "stockholders_equity",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _local_name(tag: str) -> str:
    """Strip namespace URI from an lxml tag."""
    if not isinstance(tag, str):
        return ""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def _match_highlights_concept(local_lower: str) -> Optional[str]:
    """Match a lowercase local name to a highlights column."""
    for pattern, col in HIGHLIGHTS_CONCEPT_MAP:
        if pattern in local_lower:
            return col
    return None


def _match_concept_with_wrapper(
    local_lower: str,
    wrapper: Optional[HighlightsWrapperSpec],
) -> Optional[str]:
    """Wrapper-aware concept matching.

    Checks per-CIK concept_overrides first (ordered), then falls back to the
    global HIGHLIGHTS_CONCEPT_MAP.  If no wrapper exists, behavior is identical
    to _match_highlights_concept.
    """
    if wrapper:
        for substring, target_field, action in wrapper.concept_overrides:
            if substring in local_lower:
                if action == "suppress":
                    return None
                # "map" and "prefer" both route to target_field
                return target_field
    return _match_highlights_concept(local_lower)


def _strip_ns_prefix(raw_member: str) -> str:
    """Strip CIK namespace prefix from member value.

    E.g. 'ck0001920453:ClassICommonSharesMember' -> 'ClassICommonSharesMember'
    """
    if ":" in raw_member:
        raw_member = raw_member.split(":", 1)[1]
    return raw_member


# ---------------------------------------------------------------------------
# Context parser -- handles BOTH instant and duration, entity and per-class
# ---------------------------------------------------------------------------

def _parse_highlights_contexts(tree: etree._ElementTree) -> dict:
    """Parse <xbrli:context> elements for fund-level highlights.

    Returns dict keyed by context ID with:
        period_start, period_end, period_type ('instant'|'duration'),
        duration_months, share_class (''/member label),
        has_investment_dims (bool)
    """
    root = tree.getroot()
    contexts: dict[str, dict] = {}

    for ctx in root.iter():
        if _local_name(ctx.tag) != "context":
            continue

        ctx_id = ctx.get("id", "")
        if not ctx_id:
            continue

        # Parse period
        period_start = ""
        period_end = ""
        period_type = ""

        for child in ctx:
            ln = _local_name(child.tag)
            if ln == "period":
                for pc in child:
                    pln = _local_name(pc.tag)
                    if pln == "startDate":
                        period_start = (pc.text or "").strip()
                    elif pln == "endDate":
                        period_end = (pc.text or "").strip()
                    elif pln == "instant":
                        period_type = "instant"
                        period_end = (pc.text or "").strip()

        if not period_type:
            if period_start and period_end:
                period_type = "duration"
            else:
                continue

        if not period_end:
            continue

        # Parse dimensions
        share_class = ""
        has_investment_dims = False
        has_other_dims = False

        for seg in ctx.iter():
            seg_ln = _local_name(seg.tag)
            if seg_ln == "explicitMember":
                dim = (seg.get("dimension") or "").lower()
                val = (seg.text or "").strip()

                # Extract dimension local name
                if ":" in dim:
                    dim_local = dim.split(":", 1)[1]
                else:
                    dim_local = dim

                if dim_local in _INVESTMENT_AXES:
                    has_investment_dims = True
                    break
                elif dim_local == _SHARE_CLASS_AXIS:
                    share_class = _strip_ns_prefix(val)
                else:
                    has_other_dims = True
            elif seg_ln == "typedMember":
                # Typed dimensions are usually investment-level
                has_investment_dims = True
                break

        # Skip investment-level and other non-share-class dimensioned contexts
        if has_investment_dims or has_other_dims:
            continue

        # Compute duration months for duration contexts
        duration_months = 0
        if period_type == "duration" and period_start and period_end:
            try:
                sd = date.fromisoformat(period_start)
                ed = date.fromisoformat(period_end)
                duration_months = (ed.year - sd.year) * 12 + (ed.month - sd.month)
                if ed.day >= 28:
                    duration_months += 1
            except (ValueError, TypeError):
                pass

        contexts[ctx_id] = {
            "period_start": period_start,
            "period_end": period_end,
            "period_type": period_type,
            "duration_months": duration_months,
            "share_class": share_class,
        }

    return contexts


# ---------------------------------------------------------------------------
# Fact extractor
# ---------------------------------------------------------------------------

def _extract_highlights_facts(
    tree: etree._ElementTree,
    contexts: dict,
    cik: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Extract fund-level highlights facts from accepted contexts.

    Parameters
    ----------
    tree : lxml ElementTree
    contexts : dict from _parse_highlights_contexts
    cik : str, optional
        CIK for wrapper lookup.  If a highlights wrapper exists for this CIK,
        its concept_overrides are applied before the global concept map.

    Returns one dict per unique (period_end, period_type, share_class) group.
    """
    if not contexts:
        return []

    # Look up per-CIK wrapper (None if not found)
    wrapper = load_highlights_wrapper(cik) if cik else None

    # Group by (period_end, period_type, share_class)
    facts_by_group: dict[tuple, dict[str, Any]] = {}

    root = tree.getroot()
    for elem in root.iter():
        ctx_ref = elem.get("contextRef")
        if ctx_ref is None or ctx_ref not in contexts:
            continue

        # Skip nil
        nil = elem.get("{http://www.w3.org/2001/XMLSchema-instance}nil")
        if nil and nil.lower() == "true":
            continue

        local = _local_name(elem.tag).lower()
        raw_text = (elem.text or "").strip()
        if not raw_text:
            continue

        col = _match_concept_with_wrapper(local, wrapper)
        if col is None:
            continue

        # Parse numeric value
        try:
            value = float(raw_text.replace(",", ""))
        except (ValueError, TypeError):
            continue

        ctx_info = contexts[ctx_ref]
        group_key = (
            ctx_info["period_end"],
            ctx_info["period_type"],
            ctx_info["share_class"],
        )

        if group_key not in facts_by_group:
            facts_by_group[group_key] = {
                "period_start": ctx_info["period_start"],
                "period_end": ctx_info["period_end"],
                "period_type": ctx_info["period_type"],
                "duration_months": ctx_info["duration_months"],
                "share_class": ctx_info["share_class"],
            }

        # Keep first non-None value per column per group
        if col not in facts_by_group[group_key]:
            facts_by_group[group_key][col] = value

    return list(facts_by_group.values())


# ---------------------------------------------------------------------------
# Normalization pipeline (post-extraction)
# ---------------------------------------------------------------------------

def _normalize_highlights(df: pd.DataFrame) -> pd.DataFrame:
    """Apply global normalization rules to raw highlights DataFrame.

    Rules follow existing pipeline conventions:
      1. Filter non-share-class dimension members (_NON_SHARE_CLASS_RE)
      2. Canonical share class mapping (_canonical_share_class)
      3. Null entity-dollar columns on per-class rows (_ENTITY_ONLY_DOLLAR_COLS)
      4. Duration scaling for flow columns (bdc_fund_income pattern)
      5. Ratio format normalization (fund_financials Fix 2 pattern)
    """
    if df.empty:
        return df

    n_before = len(df)

    # --- Rule 1: filter non-share-class members ---
    has_class = df["share_class"].notna() & (df["share_class"] != "")
    is_junk = has_class & df["share_class"].apply(
        lambda x: bool(_NON_SHARE_CLASS_RE.search(str(x))) if pd.notna(x) else False
    )
    n_junk = is_junk.sum()
    if n_junk:
        df = df[~is_junk].copy()
        logger.info("Rule 1 (member filter): dropped %d non-share-class rows", n_junk)

    # --- Rule 2: canonical share class mapping (with per-CIK aliases) ---
    has_class = df["share_class"].notna() & (df["share_class"] != "")
    if has_class.any():
        raw_classes = df.loc[has_class, "share_class"].unique()

        # Build per-CIK alias lookup once
        cik_aliases: dict[str, dict[str, str] | None] = {}
        for cik_val in df.loc[has_class, "cik"].unique():
            wrapper = load_highlights_wrapper(cik_val)
            cik_aliases[cik_val] = wrapper.share_class_aliases if wrapper else None

        def _map_share_class(row):
            aliases = cik_aliases.get(row["cik"])
            return _canonical_share_class(row["share_class"], aliases=aliases)

        df.loc[has_class, "share_class"] = df.loc[has_class].apply(
            _map_share_class, axis=1
        )
        mapped_classes = df.loc[has_class, "share_class"].unique()
        logger.info(
            "Rule 2 (share class): %d raw labels -> %d canonical labels",
            len(raw_classes), len(mapped_classes),
        )

    # --- Rule 3: concept pollution cleanup ---
    per_class_mask = df["share_class"].notna() & (df["share_class"] != "")
    pollution_cols = [c for c in _ENTITY_ONLY_DOLLAR_COLS if c in df.columns]
    if per_class_mask.any() and pollution_cols:
        n_nulled = df.loc[per_class_mask, pollution_cols].notna().sum().sum()
        df.loc[per_class_mask, pollution_cols] = None
        logger.info(
            "Rule 3 (concept pollution): nulled %d per-class cells across %d columns",
            n_nulled, len(pollution_cols),
        )

    # --- Rule 4: duration scaling for flow columns ---
    # Convert to numeric for scaling
    dm_col = pd.to_numeric(df["duration_months"], errors="coerce").fillna(0)
    dur_mask = df["period_type"] == "duration"
    n_scaled = 0

    for col in _FLOW_COLS:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        needs_scale = dur_mask & vals.notna() & (dm_col > 0)

        if not needs_scale.any():
            continue

        # Compute scale factor: same logic as bdc_fund_income
        scale = pd.Series(1.0, index=df.index)
        # Quarterly (2-4 months): no scaling
        quarterly = dm_col.between(2, 4)
        # Annual (11-13 months): divide by 4
        annual = dm_col.between(11, 13)
        scale[annual] = 1.0 / 4.0
        # Other: 3/dm (general case)
        other = ~quarterly & ~annual & (dm_col > 0)
        scale[other] = 3.0 / dm_col[other]

        to_scale = needs_scale & ~quarterly  # quarterly already = 1.0
        if to_scale.any():
            df.loc[to_scale, col] = vals[to_scale] * scale[to_scale]
            n_scaled += to_scale.sum()

    if n_scaled:
        logger.info("Rule 4 (duration scaling): scaled %d flow-column cells to quarterly", n_scaled)

    # --- Rule 5: ratio format normalization ---
    # Follows fund_financials Fix 2: |val| <= 1.0 -> *100, > max -> NULL
    n_converted = 0
    n_rejected = 0

    for col, max_abs_pct in _RATIO_FIELDS.items():
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        notna = vals.notna()
        if not notna.any():
            continue

        # Decimal form: |val| <= 1.0 -> multiply by 100
        decimal_mask = notna & (vals.abs() <= 1.0)
        if decimal_mask.any():
            df.loc[decimal_mask, col] = vals[decimal_mask] * 100.0
            n_converted += decimal_mask.sum()

        # Reject outliers: |val| > max_abs_pct (after conversion)
        # Re-read since we just wrote some values
        vals2 = pd.to_numeric(df[col], errors="coerce")
        reject_mask = vals2.notna() & (vals2.abs() > max_abs_pct)
        if reject_mask.any():
            df.loc[reject_mask, col] = None
            n_rejected += reject_mask.sum()

    if n_converted or n_rejected:
        logger.info(
            "Rule 5 (ratio normalization): converted %d decimal->pct, rejected %d outliers",
            n_converted, n_rejected,
        )

    logger.info(
        "Normalization: %d rows in -> %d rows out",
        n_before, len(df),
    )
    return df


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def extract_bdc_fund_highlights(
    filings_index: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Extract comprehensive fund-level highlights from cached BDC XBRL files.

    Parameters
    ----------
    filings_index : DataFrame, optional
        Filings index with xbrl_download_status and xbrl_local_path.
        Loaded from disk if None.

    Returns
    -------
    DataFrame with fund-level highlights per CIK / period / share_class.
    """
    t0 = time.time()

    if filings_index is None:
        if not BDC_FILINGS_INDEX_FILE.exists():
            logger.warning("No filings index found at %s", BDC_FILINGS_INDEX_FILE)
            return pd.DataFrame(columns=HIGHLIGHTS_COLUMNS)
        filings_index = pd.read_csv(BDC_FILINGS_INDEX_FILE, dtype=str)
        logger.info("Loaded filings index: %d rows", len(filings_index))

    # Filter to cached XBRL files
    cached = filings_index[
        filings_index["xbrl_download_status"].isin(["cached", "downloaded"])
        & filings_index["xbrl_local_path"].notna()
        & (filings_index["xbrl_local_path"] != "")
    ].copy()
    logger.info(
        "Processing %d cached XBRL files for fund-level highlights", len(cached)
    )

    if cached.empty:
        return pd.DataFrame(columns=HIGHLIGHTS_COLUMNS)

    all_records: list[dict] = []
    parsed = 0
    errors = 0

    for _, row in cached.iterrows():
        xml_path = row["xbrl_local_path"]
        filing_meta = {
            "cik": str(row.get("cik", "")),
            "entity_name": str(row.get("entity_name", "")),
            "form_type": str(row.get("form_type", "")),
            "accession_number": str(row.get("accession_number", "")),
            "filing_date": str(row.get("filing_date", "")),
        }

        try:
            tree = etree.parse(xml_path)
            contexts = _parse_highlights_contexts(tree)
            facts = _extract_highlights_facts(tree, contexts, cik=filing_meta["cik"])

            for fact in facts:
                record = {**filing_meta, **fact}
                # Derive report_quarter from period_end
                try:
                    ed = date.fromisoformat(fact["period_end"])
                    q = (ed.month - 1) // 3 + 1
                    record["report_quarter"] = f"{ed.year}q{q}"
                except (ValueError, TypeError):
                    record["report_quarter"] = ""
                all_records.append(record)

            parsed += 1
        except Exception as exc:
            errors += 1
            if errors <= 5:
                logger.debug("Error parsing %s: %s", xml_path, exc)

    logger.info(
        "Parsed %d filings (%d errors), produced %d raw records",
        parsed, errors, len(all_records),
    )

    if not all_records:
        return pd.DataFrame(columns=HIGHLIGHTS_COLUMNS)

    df = pd.DataFrame(all_records)

    # Ensure all columns exist
    for col in HIGHLIGHTS_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # ---- Apply normalization rules ----
    df = _normalize_highlights(df)

    # Dedup: same (cik, report_quarter, share_class, period_type) from multiple
    # filings. Prefer quarterly duration (dm 3-4) over annual, then 10-K > 10-Q.
    df["_dm_int"] = (
        pd.to_numeric(df["duration_months"], errors="coerce").fillna(0).astype(int)
    )
    df["_dm_pref"] = df["_dm_int"].apply(
        lambda x: 0 if 2 <= x <= 4 else (1 if 11 <= x <= 13 else 2)
    )
    # Instant contexts have dm=0, give them neutral rank
    df.loc[df["period_type"] == "instant", "_dm_pref"] = 0
    df["_form_rank"] = df["form_type"].apply(
        lambda x: 0 if "10-K" in str(x) else 1
    )

    # Count non-null data columns per row (more data = better row to keep)
    data_cols = [
        c for c in HIGHLIGHTS_COLUMNS
        if c not in {
            "cik", "entity_name", "accession_number", "form_type",
            "filing_date", "period_end", "period_start", "period_type",
            "duration_months", "share_class", "report_quarter",
        }
    ]
    df["_data_count"] = df[data_cols].notna().sum(axis=1)

    df = df.sort_values(
        ["cik", "report_quarter", "share_class", "period_type",
         "_dm_pref", "_form_rank", "_data_count"],
        ascending=[True, True, True, True, True, True, False],
    )
    df = df.drop_duplicates(
        subset=["cik", "report_quarter", "share_class", "period_type"],
        keep="first",
    )
    df = df.drop(columns=["_form_rank", "_dm_pref", "_dm_int", "_data_count"])

    # Reorder and save
    df = df[[c for c in HIGHLIGHTS_COLUMNS if c in df.columns]]
    df.to_csv(BDC_FUND_HIGHLIGHTS_FILE, index=False)

    n_ciks = df["cik"].nunique()
    n_quarters = df["report_quarter"].nunique()
    n_with_class = (df["share_class"] != "").sum()
    logger.info(
        "Fund highlights: %d rows, %d CIKs, %d quarters, %d per-class rows",
        len(df), n_ciks, n_quarters, n_with_class,
    )

    # Coverage summary
    _log_coverage_summary(df, data_cols)

    elapsed = time.time() - t0
    logger.info("Fund highlights extraction complete in %.1f s", elapsed)

    return df


def _log_coverage_summary(df: pd.DataFrame, data_cols: list[str]) -> None:
    """Log per-concept coverage statistics."""
    n_ciks = df["cik"].nunique()
    if n_ciks == 0:
        return

    logger.info("--- Coverage summary (CIKs with at least one non-null) ---")
    for col in data_cols:
        if col not in df.columns:
            continue
        non_null = df[col].notna()
        cik_count = df.loc[non_null, "cik"].nunique()
        row_count = non_null.sum()
        if cik_count > 0:
            logger.info(
                "  %-45s %3d CIKs (%4.0f%%)  %5d rows",
                col, cik_count, 100.0 * cik_count / n_ciks, row_count,
            )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    extract_bdc_fund_highlights()
