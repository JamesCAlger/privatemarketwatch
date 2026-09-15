"""Decimal reference implementation of the stock-balance FX contract (FRED H.10)."""
from datetime import date
from decimal import Decimal

def convert(amount,currency,report_date,quotes,max_age_days=7):
    """Quotes are frozen provider observations: USD per one unit of each currency on one date.

    Provider is the Federal Reserve H.10 release as published by FRED (owner
    decision 2026-09-15: one canonical FX source). This function does not fetch
    rates, repair source currencies, or reconstruct historical accounting cost.
    Unknown/conflicted source units must be resolved before calling it. Quote
    identity and source evidence remain required inputs.
    """
    value=Decimal(str(amount))
    if not value.is_finite():raise ValueError('Non-finite amount')
    if not currency or currency=='unresolved':raise ValueError('Resolve source currency first')
    if currency=='USD':return dict(value=str(value),method='already_USD',quote_id=None)
    cutoff=date.fromisoformat(report_date)
    eligible=[q for q in quotes if date.fromisoformat(q['date'])<=cutoff
              and currency in (q.get('usd_per_unit') or {})]
    if not eligible:return dict(value=None,method='FX_unavailable',quote_id=None)
    latest=max(q['date'] for q in eligible);selected=[q for q in eligible if q['date']==latest]
    if len(selected)!=1:raise ValueError('Ambiguous FX observations')
    q=selected[0]
    if not q.get('quote_id') or not q.get('source_sha256'):raise ValueError('Unpinned FX observation')
    age=(cutoff-date.fromisoformat(latest)).days
    if age>max_age_days:return dict(value=None,method='FX_stale',quote_id=q['quote_id'])
    rate=Decimal(str(q['usd_per_unit'][currency]))
    if not rate.is_finite() or rate<=0:raise ValueError('Invalid FX rate')
    return dict(value=str(value*rate),method='report_date_reference_conversion',
                quote_id=q['quote_id'],quote_date=latest,age_days=age,rate_USD_per_source=str(rate))
