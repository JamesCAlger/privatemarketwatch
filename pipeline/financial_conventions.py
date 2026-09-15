"""Financial contract v2: supported coupons, reported cost and donor provenance.

Preparation happens after corrections and before matching. Cost proxies are
assigned only after position identity. Generic rate concepts do not establish
cash/all-in meaning; unresolved evidence stays outside coupon calculations.
"""
from __future__ import annotations
import json
from pathlib import Path

import duckdb
import pandas as pd

VERSION="financial-contract.v2"
ADDITIONS={
    "cost_reported":"DOUBLE","interest_rate_reported":"DOUBLE","interest_rate_kind":"VARCHAR",
    "interest_rate_cash":"DOUBLE","basis_spread_kind":"VARCHAR","pct_of_net_assets_calculated":"DOUBLE",
    "maturity_precision":"VARCHAR","maturity_status":"VARCHAR","nonaccrual_status":"VARCHAR","gics_sector":"VARCHAR",
}


def raw_cost_state_sql(cost,facts):
    """Retain an invalid source literal before a staging TRY_CAST erases it."""
    return ("CAST(json_merge_patch(coalesce(TRY_CAST("+facts+" AS JSON),'{}'::JSON),"
        "json_object('_financial_cost',json_object('state',CASE "
        "WHEN nullif(trim(CAST("+cost+" AS VARCHAR)),'') IS NULL THEN 'absent' "
        "WHEN TRY_CAST("+cost+" AS DOUBLE) IS NULL OR NOT isfinite(TRY_CAST("+cost+" AS DOUBLE)) THEN 'invalid' "
        "ELSE 'present' END,'raw',CAST("+cost+" AS VARCHAR)))) AS VARCHAR)")


def prepare(frame,*,nav=None,hierarchy=None,prior_states=None,source_frame=False,fx_quotes=(),unit_adjudications=()):
    """Prepare supported fields without allocating identity or inventing rates.

    Explicit kinds/precision may be supplied by governed source producers. A
    previous v2 row is idempotent: use the retained reported rate and cost, never
    add PIK to an already normalized all-in rate or rematch using proxy cost.
    """
    frame=frame.copy()
    migrated=not source_frame and "interest_rate_reported" in frame and "interest_rate_kind" in frame and frame["interest_rate_kind"].fillna("").ne("").any()
    if migrated and prior_states is None:
        raise ValueError("Migrated financial rows require their retained field states")
    if prior_states is None:
        prior_states=pd.DataFrame(columns=["row_id","cost_state"])
    defaults={"cost":"","interest_rate":"","pik_rate":"","basis_spread":"","src_facts":"{}",
        "cost_source":"","cost_currency":"","fair_value_currency":"","fair_value_source":"","src_context_id":"",
        "interest_rate_source":"","maturity_date":"","maturity_date_source":"","bdc_investment_identifier":"",
        "nonaccrual_footnote":"","nonaccrual_dimension":"","asset_category":"","gics_sub_industry":"",
        "corrected_fields":"","src_conflict_fields":"","src_filled_fields":"",
        "src_field_overrides":"","src_transforms":"","source":"",
        "pct_of_net_assets":"","fair_value":"","position_id":""}
    for name,value in defaults.items():
        if name not in frame: frame[name]=value
    for name,kind in ADDITIONS.items():
        if name not in frame: frame[name]=None if kind=="DOUBLE" else ""
    text_fields={'cost_currency','fair_value_currency','cost_source','src_context_id','src_facts',
        'interest_rate_source','fair_value_source','maturity_date_source','gics_sub_industry',
        'corrected_fields','src_conflict_fields','src_filled_fields','src_field_overrides',
        'src_transforms','source','cik'} | {name for name,kind in ADDITIONS.items() if kind=='VARCHAR'}
    for name in text_fields:
        if name in frame: frame[name]=frame[name].astype('string').fillna('')
    from pipeline.monetary_fx import apply_fair_value
    frame=apply_fair_value(frame,quotes=fx_quotes,decisions=unit_adjudications)
    if frame.empty:
        return frame,pd.DataFrame(columns=['row_id','cost_state','donor_valid','source_cost_value',
            'source_rate_value','rate_kind','coupon_state','maturity_precision'])
    if nav is None: nav=pd.DataFrame(columns=["cik","report_date","net_assets"])
    else: nav=nav[["cik","report_date","net_assets"]].copy()
    if hierarchy is None: hierarchy=pd.DataFrame(columns=["sub_industry","sector"])
    else: hierarchy=hierarchy[["sub_industry","sector"]].copy()
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        con.register("input",frame);con.register("nav",nav);con.register("taxonomy",hierarchy)
        con.register("prior_states",prior_states)
        if con.execute('SELECT count(*) FROM (SELECT row_id FROM prior_states GROUP BY ALL HAVING count(*)>1)').fetchone()[0]:
            raise ValueError('Retained financial states repeat observation identity')
        if migrated and con.execute('SELECT count(*) FROM input i ANTI JOIN prior_states p USING(row_id)').fetchone()[0]:
            raise ValueError('Migrated financial rows have missing retained field states')
        if migrated:
            if not {'source_cost_value','source_rate_value'}.issubset(prior_states.columns):
                raise ValueError('Retained financial states lack reported values')
            if con.execute("""SELECT count(*) FROM input i JOIN prior_states p USING(row_id)
                WHERE TRY_CAST(i.interest_rate_reported AS DOUBLE) IS DISTINCT FROM TRY_CAST(p.source_rate_value AS DOUBLE)
                OR (p.cost_state='present' AND TRY_CAST(i.cost_reported AS DOUBLE) IS DISTINCT FROM TRY_CAST(p.source_cost_value AS DOUBLE))""").fetchone()[0]:
                raise ValueError('Retained financial states disagree with reported values')
        # Duplicate denominators/parents must agree; no arbitrary last-row wins.
        if con.execute("""SELECT count(*) FROM (SELECT cik,report_date FROM nav GROUP BY ALL
            HAVING count(DISTINCT TRY_CAST(net_assets AS DOUBLE))>1)""").fetchone()[0]:
            raise ValueError("Conflicting NAV denominators")
        if con.execute("SELECT count(*) FROM (SELECT sub_industry FROM taxonomy GROUP BY ALL HAVING count(DISTINCT sector)>1)").fetchone()[0]:
            raise ValueError("Conflicting GICS parents")
        reported_rate="interest_rate_reported" if migrated else "interest_rate"
        reported_cost="cost_reported" if migrated else "cost"
        con.execute("""CREATE TABLE typed AS SELECT *,
            TRY_CAST("""+reported_rate+""" AS DOUBLE) AS reported_rate,
            TRY_CAST("""+reported_cost+""" AS DOUBLE) AS reported_cost,
            NULLIF(trim(CAST("""+reported_cost+""" AS VARCHAR)),'') AS raw_cost,
            TRY_CAST(pik_rate AS DOUBLE) AS pik,
            TRY_CAST(fair_value AS DOUBLE) AS fv,
            TRY_CAST(src_facts AS JSON) AS facts,
            lower(coalesce(json_extract_string(TRY_CAST(src_facts AS JSON),'$.interest_rate.c'),'')) AS rate_concept,
            coalesce(json_extract_string(TRY_CAST(src_facts AS JSON),'$.maturity_date.r'),'') AS maturity_raw
            FROM input""")
        con.execute("""CREATE TABLE conventions AS SELECT typed.*,
            CASE WHEN upper(trim(fair_value_currency)) NOT IN ('','USD') THEN
                      CASE WHEN json_extract_string(facts,'$._financial_fx.fair_value.conversion.method')='FX_stale'
                           THEN 'FX_stale'
                           WHEN regexp_full_match(upper(trim(fair_value_currency)),'[A-Z]{3}')
                           THEN 'FX_unavailable' ELSE 'unit_unresolved' END
                 WHEN fv IS NULL OR NOT isfinite(fv) THEN 'not_available'
                 WHEN upper(trim(fair_value_currency))='USD' THEN 'explicit_usd'
                 ELSE 'assumed_usd' END AS fv_state,
            CASE WHEN NULLIF(interest_rate_kind,'') IS NOT NULL THEN interest_rate_kind
                 WHEN rate_concept LIKE '%effectiveyield%' OR rate_concept LIKE '%yieldtomaturity%' THEN 'effective_yield'
                 WHEN rate_concept IN ('investmentinterestratepaidincash','investmentcashinterestrate') THEN 'cash'
                 WHEN rate_concept LIKE '%allininterestrate%' THEN 'all_in'
                 ELSE 'unresolved' END AS rate_kind,
            CASE WHEN p.cost_state IS NOT NULL THEN p.cost_state
                 WHEN upper(trim(cost_currency)) NOT IN ('','USD') THEN 'unresolved_currency'
                 WHEN cost_source IN ('derived_proxy','first_observed_fv_proxy') AND NOT ? THEN 'absent'
                 WHEN json_extract_string(facts,'$._financial_cost.state')='invalid'
                      AND (reported_cost IS NULL OR NOT isfinite(reported_cost)) THEN 'invalid'
                 WHEN raw_cost IS NULL THEN 'absent'
                 WHEN reported_cost IS NULL OR NOT isfinite(reported_cost) THEN 'invalid'
                 ELSE 'present' END AS cost_state,
            CASE WHEN fv IS NULL OR NOT isfinite(fv) THEN false
                 WHEN upper(trim(fair_value_currency)) NOT IN ('','USD') THEN false
                 WHEN coalesce(json_extract_string(facts,'$.fair_value.disputed'),'false')='true' THEN false
                 -- An anchor alone does not attest the current value. Filled,
                 -- disputed, transformed or corrected values need independent
                 -- verification before they can supply a cost proxy.
                 WHEN regexp_matches(concat_ws(';',corrected_fields,src_conflict_fields,
                      src_filled_fields,src_field_overrides,src_transforms),
                      '(^|;)fair_value([;:=]|$)') THEN false
                 WHEN coalesce(json_array_length(json_extract(facts,'$.fair_value.x')),0)>0 THEN false
                 WHEN json_extract_string(facts,'$.fair_value.r') IS NOT NULL
                      AND TRY_CAST(json_extract_string(facts,'$.fair_value.r') AS DOUBLE)
                          IS DISTINCT FROM fv
                      AND NOT coalesce((json_extract_string(facts,'$._financial_fx.fair_value.conversion.method')='report_date_reference_conversion'
                          AND TRY_CAST(json_extract_string(facts,'$._financial_fx.fair_value.source_value') AS DOUBLE)
                              =TRY_CAST(json_extract_string(facts,'$.fair_value.r') AS DOUBLE)
                          AND TRY_CAST(json_extract_string(facts,'$._financial_fx.fair_value.final_value') AS DOUBLE)=fv),false)
                      THEN false
                 WHEN source='bdc' AND fair_value_source='xbrl_field'
                      AND NULLIF(trim(src_context_id),'') IS NOT NULL THEN true
                 WHEN source='nport' AND fair_value_source='nport' THEN true
                 ELSE false END AS donor_valid,
            CASE WHEN maturity_precision IN ('day','month','year') THEN maturity_precision
                 WHEN regexp_full_match(maturity_raw,'[0-9]{4}-[0-9]{2}') THEN 'month'
                 WHEN regexp_full_match(maturity_raw,'[0-9]{4}') THEN 'year'
                 WHEN regexp_full_match(maturity_raw,'[0-9]{4}-[0-9]{2}-[0-9]{2}') THEN 'day'
                 WHEN maturity_date_source IN ('xbrl_field','nport') AND TRY_CAST(maturity_date AS DATE) IS NOT NULL THEN 'day'
                 ELSE 'unknown' END AS precision_value
            FROM typed LEFT JOIN (SELECT row_id,cost_state FROM prior_states) p USING(row_id)""",[bool(migrated)])
        con.execute("""CREATE TABLE calculated AS SELECT *,
            CASE WHEN rate_kind='all_in' AND isfinite(reported_rate) THEN reported_rate
                 WHEN rate_kind='cash' AND isfinite(reported_rate) AND isfinite(pik) THEN reported_rate+pik END AS all_in,
            CASE WHEN rate_kind='cash' AND isfinite(reported_rate) THEN reported_rate
                 WHEN rate_kind='all_in' AND isfinite(reported_rate) AND isfinite(pik) THEN reported_rate-pik END AS cash,
            CASE WHEN precision_value='month' THEN last_day(coalesce(TRY_CAST(maturity_raw||'-01' AS DATE),TRY_CAST(maturity_date AS DATE)))
                 WHEN precision_value='year' THEN coalesce(TRY_CAST(maturity_raw||'-12-31' AS DATE),
                    CAST(date_trunc('year',TRY_CAST(maturity_date AS DATE))+INTERVAL '1 year'-INTERVAL '1 day' AS DATE))
                 ELSE TRY_CAST(maturity_date AS DATE) END AS final_maturity
            FROM conventions""")
        result=con.execute("""SELECT i.* REPLACE(
            CASE WHEN c.fv_state IN ('explicit_usd','assumed_usd') THEN c.fv END AS fair_value,
            CAST(json_merge_patch(coalesce(TRY_CAST(i.src_facts AS JSON),'{}'::JSON),
                json_object('_financial_fair_value',
                    coalesce(json_extract(TRY_CAST(i.src_facts AS JSON),'$._financial_fair_value'),
                        json_object('raw',coalesce(CAST(i.fair_value AS VARCHAR),
                            json_extract_string(TRY_CAST(i.src_facts AS JSON),'$._financial_fx.fair_value.source_value')),
                            'currency',i.fair_value_currency,
                            'state',c.fv_state)))) AS VARCHAR) AS src_facts,
            CASE WHEN c.cost_state='present' THEN c.reported_cost END AS cost,
            CASE WHEN c.cost_state='present' THEN c.reported_cost END AS cost_reported,
            c.reported_rate AS interest_rate_reported,c.rate_kind AS interest_rate_kind,
            c.all_in AS interest_rate,c.cash AS interest_rate_cash,
            concat_ws(';',nullif(array_to_string(list_filter(string_split(coalesce(i.src_transforms,''),';'),
                event -> event NOT IN ('interest_rate:cash_plus_pik','interest_rate:coupon_unresolved')),';'),''),
                CASE WHEN c.rate_kind='cash' AND c.all_in IS NOT NULL THEN 'interest_rate:cash_plus_pik'
                     WHEN c.all_in IS NULL THEN 'interest_rate:coupon_unresolved' END) AS src_transforms,
            coalesce(nullif(i.basis_spread_kind,''),'unresolved') AS basis_spread_kind,
            CASE WHEN c.fv_state IN ('explicit_usd','assumed_usd') AND isfinite(n.net_assets)
                      AND n.net_assets<>0 THEN c.fv/n.net_assets*100 END AS pct_of_net_assets_calculated,
            CAST(c.final_maturity AS VARCHAR) AS maturity_date,c.precision_value AS maturity_precision,
            CASE WHEN i.maturity_status IN ('perpetual','not_applicable') THEN i.maturity_status
                 WHEN c.final_maturity IS NOT NULL AND c.precision_value='day' THEN 'dated'
                 WHEN c.final_maturity IS NOT NULL AND c.precision_value IN ('month','year') THEN 'partial'
                 WHEN c.final_maturity IS NOT NULL OR c.maturity_raw<>'' THEN 'unresolved'
                 ELSE 'not_disclosed' END AS maturity_status,
            CASE WHEN TRY_CAST(i.nonaccrual_footnote AS BOOLEAN) OR TRY_CAST(i.nonaccrual_dimension AS BOOLEAN) THEN 'nonaccrual'
                 WHEN i.nonaccrual_status IN ('accrual_confirmed','not_applicable') THEN i.nonaccrual_status ELSE 'unknown' END AS nonaccrual_status,
            t.sector AS gics_sector)
            FROM input i JOIN calculated c USING(row_id)
            LEFT JOIN (SELECT lpad(cast(cik AS VARCHAR),10,'0') AS cik,cast(report_date AS VARCHAR) AS report_date,
                max(TRY_CAST(net_assets AS DOUBLE)) AS net_assets FROM nav GROUP BY ALL) n
                ON lpad(cast(i.cik AS VARCHAR),10,'0')=n.cik AND cast(i.report_date AS VARCHAR)=n.report_date
            LEFT JOIN (SELECT DISTINCT sub_industry,sector FROM taxonomy) t ON i.gics_sub_industry=t.sub_industry""").fetchdf()
        audit=con.execute("""SELECT row_id,cost_state,donor_valid,reported_cost AS source_cost_value,reported_rate AS source_rate_value,
            rate_kind,CASE WHEN all_in IS NOT NULL THEN 'supported' ELSE 'unresolved' END AS coupon_state,
            precision_value AS maturity_precision FROM calculated ORDER BY row_id""").fetchdf()
    if len(result)!=len(frame): raise ValueError("Financial preparation changed observation grain")
    return result,audit


def cost_proxies(frame,states,*,release_id):
    """Use the unique earliest source-valid observation of an established position."""
    if not release_id: raise ValueError("Cost donor requires a release identity")
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        con.register("holdings",frame);con.register("states",states)
        if con.execute("""SELECT count(*) FROM holdings WHERE coalesce(position_id,'')=''""").fetchone()[0]:
            raise ValueError("Cost proxies require complete position identity")
        con.execute("""CREATE TABLE donors AS WITH valid AS (
            SELECT h.*,min(TRY_CAST(report_date AS DATE)) OVER(PARTITION BY cik,position_id) AS first_date
            FROM holdings h JOIN states s USING(row_id) WHERE s.donor_valid), earliest AS (
            SELECT * FROM valid WHERE TRY_CAST(report_date AS DATE)=first_date)
            SELECT cik,position_id,count(*) AS candidates,min(row_id) AS donor_row_id,
                min(first_date) AS donor_date,min(TRY_CAST(fair_value AS DOUBLE)) AS donor_value
            FROM earliest GROUP BY cik,position_id""")
        con.execute("""CREATE TABLE proxy_audit AS SELECT h.row_id,
            CASE WHEN s.cost_state='present' THEN 'reported'
                 WHEN s.cost_state<>'absent' THEN s.cost_state
                 WHEN d.candidates>1 THEN 'ambiguous_earliest_donor'
                 WHEN d.candidates=1 THEN 'first_observed_fv_proxy'
                 ELSE 'no_source_valid_donor' END AS method,
            CASE WHEN s.cost_state='absent' AND d.candidates=1 THEN d.donor_row_id END AS donor_row_id,
            CASE WHEN s.cost_state='absent' AND d.candidates=1 THEN d.donor_date END AS donor_date,
            CASE WHEN s.cost_state='absent' AND d.candidates=1 THEN ? END AS donor_release,
            CASE WHEN s.cost_state='absent' AND d.candidates=1 THEN d.donor_value END AS proxy_value
            FROM holdings h JOIN states s USING(row_id) LEFT JOIN donors d USING(cik,position_id)""",[release_id])
        result=con.execute("""SELECT h.* REPLACE(CASE WHEN a.method='first_observed_fv_proxy' THEN a.proxy_value
            ELSE h.cost_reported END AS cost,CASE WHEN a.method='first_observed_fv_proxy' THEN a.method
            ELSE h.cost_source END AS cost_source) FROM holdings h JOIN proxy_audit a USING(row_id)""").fetchdf()
        audit=con.execute("SELECT * FROM proxy_audit ORDER BY row_id").fetchdf()
    if len(result)!=len(frame): raise ValueError("Cost proxy changed observation grain")
    return result,audit


def maturity_interval_sql(date,precision):
    """SQL bounds for comparisons; unknown precision cannot assert a veto."""
    low=f"CASE WHEN {precision}='year' THEN date_trunc('year',TRY_CAST({date} AS DATE)) WHEN {precision}='month' THEN date_trunc('month',TRY_CAST({date} AS DATE)) WHEN {precision}='day' THEN TRY_CAST({date} AS DATE) END"
    high=f"CASE WHEN {precision}='year' THEN date_trunc('year',TRY_CAST({date} AS DATE))+INTERVAL '1 year'-INTERVAL '1 day' WHEN {precision}='month' THEN last_day(TRY_CAST({date} AS DATE)) WHEN {precision}='day' THEN TRY_CAST({date} AS DATE) END"
    return low,high


def synchronize_matches(matches,holdings):
    """Replace raw comparative cash rates with finalized observation values.

    Tier-A matching reads cached extraction rows. Those raw values are useful
    for identifying a pair, but cannot enter the all-in return contract. Join
    final values by position, fund, source and economic date; never by borrower.
    Missing selected observations leave income unassessable.
    """
    if matches.empty: return matches.copy()
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.register('matches',matches);con.register('holdings',holdings)
        if con.execute("""SELECT count(*) FROM (SELECT cik,source,position_id,report_date FROM holdings
            GROUP BY ALL HAVING count(*)>1)""").fetchone()[0]:
            raise ValueError('Final financial observations are not position/date unique')
        replacements=[]
        for side,alias in (('begin','b'),('end','e')):
            for field in ('fair_value','cost','interest_rate','basis_spread'):
                if side+'_'+field in matches:
                    replacements.append('TRY_CAST('+alias+'.'+field+' AS DOUBLE) AS '+side+'_'+field)
        result=con.execute('SELECT m.* REPLACE('+','.join(replacements)+""" ) FROM matches m
            LEFT JOIN holdings b ON lpad(CAST(m.cik AS VARCHAR),10,'0')=lpad(CAST(b.cik AS VARCHAR),10,'0')
                AND m.source=b.source AND m.position_id=b.position_id
                AND TRY_CAST(m.begin_report_date AS DATE)=TRY_CAST(b.report_date AS DATE)
            LEFT JOIN holdings e ON lpad(CAST(m.cik AS VARCHAR),10,'0')=lpad(CAST(e.cik AS VARCHAR),10,'0')
                AND m.source=e.source AND m.position_id=e.position_id
                AND TRY_CAST(m.end_report_date AS DATE)=TRY_CAST(e.report_date AS DATE)""").fetchdf()
    if len(result)!=len(matches): raise ValueError('Financial synchronization changed matched-pair grain')
    return result
