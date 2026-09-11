"""Decimal reference implementation of the proposed stock-balance FX contract."""
from datetime import date
from decimal import Decimal

def convert(amount,currency,report_date,quotes,max_age_days=7):
    """Quotes are frozen provider observations, currency units per EUR on one date.

    This function does not fetch rates, repair source currencies, or reconstruct
    historical accounting cost. Unknown/conflicted source units must be resolved
    before calling it. Quote identity and source evidence remain required inputs.
    """
    value=Decimal(str(amount))
    if not value.is_finite():raise ValueError('Non-finite amount')
    if not currency or currency=='unresolved':raise ValueError('Resolve source currency first')
    if currency=='USD':return dict(value=str(value),method='already_USD',quote_id=None)
    cutoff=date.fromisoformat(report_date)
    eligible=[q for q in quotes if date.fromisoformat(q['date'])<=cutoff
              and (currency=='EUR' or currency in q['per_EUR']) and 'USD' in q['per_EUR']]
    if not eligible:return dict(value=None,method='FX_unavailable',quote_id=None)
    latest=max(q['date'] for q in eligible);selected=[q for q in eligible if q['date']==latest]
    if len(selected)!=1:raise ValueError('Ambiguous FX observations')
    q=selected[0]
    if not q.get('quote_id') or not q.get('source_sha256'):raise ValueError('Unpinned FX observation')
    age=(cutoff-date.fromisoformat(latest)).days
    if age>max_age_days:return dict(value=None,method='FX_stale',quote_id=q['quote_id'])
    source=Decimal(1) if currency=='EUR' else Decimal(str(q['per_EUR'][currency]));usd=Decimal(str(q['per_EUR']['USD']))
    if not source.is_finite() or not usd.is_finite() or source<=0 or usd<=0:raise ValueError('Invalid FX rate')
    return dict(value=str(value*usd/source),method='report_date_reference_conversion',
                quote_id=q['quote_id'],quote_date=latest,age_days=age,rate_USD_per_source=str(usd/source))
