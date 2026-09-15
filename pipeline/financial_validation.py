"""Structural checks for the written financial convention, separate from flags."""
import duckdb


def violations(frame):
    if frame.empty: return []
    enums={
        'interest_rate_kind':('cash','all_in','effective_yield','other','unresolved'),
        'maturity_precision':('day','month','year','unknown'),
        'maturity_status':('dated','partial','perpetual','not_disclosed','unresolved','not_applicable'),
        'nonaccrual_status':('nonaccrual','accrual_confirmed','unknown','not_applicable'),
    }
    missing=(set(enums)|{'cost_reported','interest_rate_reported','interest_rate_cash','basis_spread_kind'})-set(frame.columns)
    if missing: return [('financial_missing_columns',len(missing))]
    with duckdb.connect(config={'threads':2,'memory_limit':'-1'}) as con:
        con.register('h',frame)
        checks={}
        if 'fair_value_currency' in frame:
            checks['financial_fair_value_currency']="""TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
                AND upper(coalesce(trim(CAST(fair_value_currency AS VARCHAR)),'')) NOT IN ('','USD')"""
        if 'cost_currency' in frame:
            checks['financial_cost_currency']="""TRY_CAST(cost AS DOUBLE) IS NOT NULL
                AND upper(coalesce(trim(CAST(cost_currency AS VARCHAR)),'')) NOT IN ('','USD')"""
        for name,values in enums.items():
            checks['financial_'+name+'_enum']='coalesce(CAST("'+name+'" AS VARCHAR),\'\') NOT IN '+repr(values)
        checks['financial_coupon_consistency']="""
            CASE WHEN interest_rate_kind='cash' AND isfinite(TRY_CAST(interest_rate_reported AS DOUBLE))
                     AND isfinite(TRY_CAST(pik_rate AS DOUBLE))
                 THEN TRY_CAST(interest_rate AS DOUBLE) IS NULL OR
                      abs(TRY_CAST(interest_rate AS DOUBLE)-TRY_CAST(interest_rate_reported AS DOUBLE)-TRY_CAST(pik_rate AS DOUBLE))>1e-10
                 WHEN interest_rate_kind='all_in' AND isfinite(TRY_CAST(interest_rate_reported AS DOUBLE))
                 THEN TRY_CAST(interest_rate AS DOUBLE) IS DISTINCT FROM TRY_CAST(interest_rate_reported AS DOUBLE)
                 ELSE TRY_CAST(interest_rate AS DOUBLE) IS NOT NULL END
        """
        checks['financial_reported_cost_preserved']="""TRY_CAST(cost_reported AS DOUBLE) IS NOT NULL AND
            TRY_CAST(cost AS DOUBLE) IS DISTINCT FROM TRY_CAST(cost_reported AS DOUBLE)"""
        checks['financial_unlabelled_cost_proxy']="""TRY_CAST(cost_reported AS DOUBLE) IS NULL
            AND TRY_CAST(cost AS DOUBLE) IS NOT NULL AND
            coalesce(CAST(cost_source AS VARCHAR),'')<>'first_observed_fv_proxy'"""
        checks['financial_maturity_state']="""
            (maturity_status='dated' AND (maturity_precision<>'day' OR TRY_CAST(maturity_date AS DATE) IS NULL)) OR
            (maturity_status='partial' AND (maturity_precision NOT IN ('month','year') OR TRY_CAST(maturity_date AS DATE) IS NULL)) OR
            (maturity_status IN ('not_disclosed','not_applicable','perpetual') AND TRY_CAST(maturity_date AS DATE) IS NOT NULL)
        """
        found=[]
        for name,condition in checks.items():
            count=con.execute('SELECT count(*) FROM h WHERE '+condition).fetchone()[0]
            if count: found.append((name,count))
        return found
