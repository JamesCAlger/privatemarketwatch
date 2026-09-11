"""Conservative comparison primitives for isolated programme measurements."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def decimal_or_none(value) -> Decimal | None:
    if value is None or str(value).strip()=='':return None
    try:
        d=Decimal(str(value))
        return d if d.is_finite() else None
    except InvalidOperation:return None


def compare_field(reference, actual, *, rounding=None, reference_currency=None, actual_currency=None) -> dict:
    """No percentage slack is approved here; compare with declared source precision."""
    ref=decimal_or_none(reference);act=decimal_or_none(actual);bound=decimal_or_none(rounding)
    if ref is None:return {'status':'unassessable_reference','absolute_error':None}
    if act is None:return {'status':'missing_candidate_value','absolute_error':None}
    if reference_currency is not None:
        if actual_currency is None:return {'status':'unresolved_candidate_currency','absolute_error':None}
        if reference_currency!=actual_currency:return {'status':'currency_mismatch','absolute_error':None}
    delta=abs(ref-act)
    if bound is None and delta:
        return {'status':'rounding_not_established','absolute_error':str(delta)}
    return {'status':'within_source_precision' if delta<=(bound or 0) else 'value_mismatch','absolute_error':str(delta)}


def match_roster(reference: list[dict], candidate: list[dict]) -> dict:
    """Score an explicitly reviewed source roster with stable, unique source-lot keys.

    Duplicate published rows cannot all receive credit. An ambiguous duplicated
    reference key prevents scoring, rather than manufacturing one-to-one truth.
    Used only on reviewed development/reference populations, not raw fact candidates.
    """
    refs={}
    for r in reference:
        if not r.get('key') or r['key'] in refs:
            return {'status':'blocked_ambiguous_reference_key'}
        refs[r['key']]=r
    seen=set();matched=set();supported=[];extras=[]
    for c in candidate:
        key=c.get('key')
        if key in refs and key not in seen:
            matched.add(key);supported.append(c)
        else:extras.append(c)
        seen.add(key)
    source_fv=[decimal_or_none(r.get('fair_value')) for r in reference]
    published_fv=[decimal_or_none(r.get('fair_value')) for r in candidate]
    source_missing=sum(x is None for x in source_fv);published_missing=sum(x is None for x in published_fv)
    recall_den=sum(abs(x) for x in source_fv if x is not None)
    precision_den=sum(abs(x) for x in published_fv if x is not None)
    recall_num=sum(abs(decimal_or_none(refs[k].get('fair_value')) or 0) for k in matched)
    precision_num=sum(abs(decimal_or_none(c.get('fair_value')) or 0) for c in supported)
    ambiguous_fv_keys = {
        key for key in matched
        if len({decimal_or_none(c.get('fair_value')) for c in candidate if c.get('key') == key}) > 1
    }
    return {'status':'reviewed_reference_comparison','reference_rows':len(reference),'candidate_rows':len(candidate),
      'matched_rows':len(matched),'source_only_rows':len(reference)-len(matched),'output_only_or_duplicate_rows':len(extras),
      'row_recall':len(matched)/len(reference) if reference else None,
      'row_precision':len(matched)/len(candidate) if candidate else None,
      'fv_recall':float(recall_num/recall_den) if recall_den and not source_missing else None,
      'fv_precision':float(precision_num/precision_den) if precision_den and not published_missing and not ambiguous_fv_keys else None,
      'ambiguous_duplicate_fv_keys':len(ambiguous_fv_keys),
      'source_missing_fv_rows':source_missing,'published_missing_fv_rows':published_missing,
      'source_abs_fv_known':str(recall_den),'published_abs_fv_known':str(precision_den)}


def primary_error_ratio(anchors: list[dict]) -> dict:
    """Aggregate only independently selected primary, basis-verified anchors; never net errors."""
    eligible=[a for a in anchors if a.get('primary') and a.get('basis_verified')]
    keys=[(a['cik'],a['report_date']) for a in eligible]
    if len(set(keys))!=len(keys):raise ValueError('multiple primary anchors for a fund-quarter')
    assessed=[]
    for a in eligible:
        ref=decimal_or_none(a.get('reference'));actual=decimal_or_none(a.get('actual'))
        if ref is not None and actual is not None:assessed.append((ref,actual))
    numerator=sum(abs(a-r) for r,a in assessed);denominator=sum(abs(r) for r,a in assessed)
    return {'eligible_primary_anchors':len(eligible),'assessed_primary_anchors':len(assessed),
      'absolute_residual_sum':str(numerator),'source_abs_total':str(denominator),
      'ratio':float(numerator/denominator) if denominator and len(assessed)==len(eligible) else None}
