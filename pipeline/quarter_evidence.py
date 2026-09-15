"""Deterministic collectors for the production-stack quarter-acceptance rows.

This module measures evidence. Threshold comparisons and the verdict belong to
quarter_acceptance; missing collectors never disappear from that gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from pipeline.programme.core import ContractError, read_json, sha


@dataclass
class Evidence:
    manifest: Path
    holdings: Path

    def __post_init__(self):
        self.manifest = Path(self.manifest).resolve()
        self.holdings = Path(self.holdings).resolve()
        self.data = read_json(self.manifest)
        self.candidate = sha(self.holdings)
        if self.data.get("holdings_sha256") != self.candidate:
            raise ContractError("Quarter evidence belongs to different holdings")
        self.paths = {}
        for name, record in self.data.get("files", {}).items():
            path = (self.manifest.parent / record["path"]).resolve()
            if not path.is_file() or sha(path) != record["sha256"]:
                raise ContractError("Quarter evidence changed: " + name)
            self.paths[name] = path

    def path(self, name, *, candidate_bound=False):
        path = self.paths.get(name)
        if path and candidate_bound:
            record = self.data["files"][name]
            if record.get("holdings_sha256") != self.candidate:
                return None
        return path

    def verify(self):
        if sha(self.holdings) != self.candidate:
            raise ContractError("Holdings changed during quarter evaluation")
        for name, path in self.paths.items():
            if sha(path) != self.data["files"][name]["sha256"]:
                raise ContractError("Evidence changed during quarter evaluation: " + name)


def observation(actual=None, *, reason="", details=None, assessable=True):
    return dict(actual=actual, assessable=assessable and actual is not None,
                reason=reason, details=details or {})


def table(con, name, path):
    if Path(path).suffix == ".parquet":
        con.execute('CREATE OR REPLACE TEMP TABLE "' + name + '" AS SELECT * FROM read_parquet(?)', [str(path)])
    else:
        con.execute('CREATE OR REPLACE TEMP TABLE "' + name + '" AS SELECT * FROM read_csv(?,all_varchar=true)', [str(path)])


def _ratio(numerator, denominator):
    return float(numerator / denominator) if denominator else None


def collect_contexts(con, evidence, quarter, results):
    register = evidence.path("obligations")
    if not register:
        return
    table(con, "obligations", register)
    con.execute("""CREATE TEMP TABLE eligible AS SELECT lpad(cik,10,'0') AS cik FROM obligations
      WHERE report_date=? AND eligibility_status LIKE 'eligible%'""", [quarter])
    eligible = con.execute("SELECT count(*) FROM eligible").fetchone()[0]
    duplicates = con.execute("SELECT count(*)-count(DISTINCT cik) FROM eligible").fetchone()[0]
    if duplicates:
        raise ContractError("Obligation register repeats an eligible fund-quarter")
    present = con.execute("SELECT count(DISTINCT cik) FROM h SEMI JOIN eligible USING(cik)").fetchone()[0]
    adopted = bool(evidence.data.get("denominator_adoption"))
    results["fund_coverage_share"] = observation(_ratio(present, eligible), assessable=adopted,
        reason="Adopted obligation register" if adopted else "Provisional: exclusion audit has not certified the denominator",
        details=dict(funds_with_holdings=present, eligible_funds=eligible, register_sha256=sha(register), provisional=not adopted))
    exclusions = evidence.path("exclusions")
    if exclusions:
        table(con,"exclusions",exclusions)
        n, contradicted, unresolved = con.execute("""SELECT count(*),
          count(*) FILTER(WHERE verdict LIKE 'exclusion_contradicted%' OR TRY_CAST(P AS BIGINT)>0
            OR TRY_CAST(positive_total_observations AS BIGINT)>0),
          count(*) FILTER(WHERE verdict='exclusion_unassessable') FROM exclusions WHERE quarter=?""", [quarter]).fetchone()
        expected = con.execute("SELECT count(*) FROM obligations WHERE report_date=? AND eligibility_status NOT LIKE 'eligible%'", [quarter]).fetchone()[0]
        results["excluded_with_positive_facts"] = observation(contradicted,
            assessable=bool(contradicted) or (n == expected and unresolved == 0),
            reason="Contradictions fail; unresolved or absent exclusions prevent certification",
            details=dict(assessed_records=n,expected_records=expected,unresolved=unresolved))
    contexts = evidence.path("contexts")
    if not contexts:
        return
    table(con,"contexts",contexts)
    con.execute("CREATE TEMP TABLE cq AS SELECT c.* FROM contexts c SEMI JOIN eligible e ON lpad(c.cik,10,'0')=e.cik WHERE quarter=?", [quarter])
    n, evidenced, reconciled, unresolved, incomplete = con.execute("""SELECT count(*),
      count(*) FILTER(WHERE lower(source_complete)='true' AND nullif(evidence_sha256,'') IS NOT NULL),
      count(*) FILTER(WHERE TRY_CAST(P_with_result AS BIGINT)>0),sum(TRY_CAST(U AS BIGINT)),
      count(*) FILTER(WHERE lower(source_complete)!='true' OR source_complete IS NULL) FROM cq""").fetchone()
    if n != con.execute("SELECT count(DISTINCT cik) FROM cq").fetchone()[0]:
        raise ContractError("Context inventory repeats an eligible fund-quarter")
    # A documented unresolved/source-unavailable status is still an evidenced
    # status; it does not certify the source or excuse an output omission.
    statuses = con.execute("SELECT count(*) FROM cq WHERE nullif(evidence_sha256,'') IS NOT NULL").fetchone()[0]
    results["obligation_status_coverage"] = observation(_ratio(statuses,eligible),
        details=dict(evidenced_statuses=statuses,eligible=eligible,complete_sources=evidenced,unresolved_contexts=unresolved))
    results["reconciliation_coverage"] = observation(_ratio(reconciled,eligible),
        details=dict(with_result=reconciled,eligible=eligible,missing_context_assessments=eligible-n))
    records = con.execute("""SELECT cik,TRY_CAST(P AS BIGINT),TRY_CAST(U AS BIGINT),
      TRY_CAST(unrecognized_context_share AS DOUBLE),lower(source_complete)='true' FROM cq ORDER BY cik""").fetchall()
    results["unrecognized_context_share"] = observation(
        max((r[3] for r in records if r[3] is not None),default=None),
        assessable=n == eligible and not incomplete and not unresolved,
        reason="Per-fund maximum; all unsupported and unresolved contexts remain visible",
        details=dict(fund_quarters=[dict(cik=c,P=p,U=u,share=s,complete=complete) for c,p,u,s,complete in records]))


def collect_holdings(con, evidence, quarter, cohort, results):
    table(con,"all_holdings",evidence.holdings)
    con.execute("""CREATE TEMP TABLE h AS SELECT * REPLACE(lpad(cik,10,'0') AS cik)
      FROM all_holdings WHERE substr(CAST(report_date AS VARCHAR),1,10)=?
      AND lpad(cik,10,'0') IN (SELECT unnest(?))""", [quarter,sorted(cohort)])
    columns = {r[0] for r in con.execute("DESCRIBE h").fetchall()}
    n = con.execute("SELECT count(*) FROM h").fetchone()[0]
    if "position_id" in columns:
        filled = con.execute("SELECT count(*) FROM h WHERE nullif(trim(position_id),'') IS NOT NULL").fetchone()[0]
        results["position_id_fill"] = observation(_ratio(filled,n),details=dict(rows=n,filled=filled))
    hierarchy = evidence.path("gics_hierarchy")
    if hierarchy and "gics_sub_industry" in columns:
        mapping = read_json(hierarchy)
        keys = sorted(name for name,item in mapping.items() if item.get("sector") not in (None,"","Unknown","Other"))
        row_n, total_fv, known_fv, missing = con.execute("""SELECT
          count(*) FILTER(WHERE gics_sub_industry IN (SELECT unnest(?))),
          sum(abs(TRY_CAST(fair_value AS DOUBLE))),
          sum(abs(TRY_CAST(fair_value AS DOUBLE))) FILTER(WHERE gics_sub_industry IN (SELECT unnest(?))),
          count(*) FILTER(WHERE TRY_CAST(fair_value AS DOUBLE) IS NULL) FROM h""", [keys,keys]).fetchone()
        results["sector_row_coverage"] = observation(_ratio(row_n,n),details=dict(rows=n,assigned=row_n))
        results["sector_fv_coverage"] = observation(_ratio(known_fv or 0,total_fv),assessable=missing==0,
            details=dict(absolute_fv=total_fv,assigned_absolute_fv=known_fv,missing_fv_rows=missing))
    # Validate the actual written artifact using the same final schema, including
    # required columns and blocking enum/date violations. This is a small-quarter
    # frame; validation itself uses column operations rather than row iteration.
    from pipeline.unified_holdings import validate_final_holdings_schema
    try:
        validate_final_holdings_schema(con.execute("SELECT * FROM h").fetchdf())
    except ValueError as error:
        results["schema_violations_post_write"] = observation(1,reason=str(error))
    else:
        results["schema_violations_post_write"] = observation(0)


def collect_fields(con, evidence, quarter, results, *, name='fields',
                   metric='amount_field_accuracy', expected_fields=None):
    path = evidence.path(name,candidate_bound=True)
    if not path:
        return
    table(con,"fields",path)
    # E4 conserves a field grid per reference context. Supplemental
    # candidate-only anchors are not a source roster and cannot increase recall.
    columns = {r[0] for r in con.execute("DESCRIBE fields").fetchall()}
    weight_column = "source_fv" if "source_fv" in columns else "source_fair_value"
    rows = con.execute(f"""SELECT field,coalesce(source_fv_currency,''),category,count(*),
      sum(abs(TRY_CAST({weight_column} AS DOUBLE))),
      count(*) FILTER(WHERE TRY_CAST({weight_column} AS DOUBLE) IS NULL)
      FROM fields WHERE quarter=? AND reference_origin='selected_source_roster'
      GROUP BY field,source_fv_currency,category ORDER BY field,source_fv_currency,category""", [quarter]).fetchall()
    by_field = {}
    for field, currency, category, count, fv, missing in rows:
        by_field.setdefault((field,currency),{})[category] = dict(rows=count,source_fv=fv or 0,missing_fv=missing)
    details = {}
    floors = evidence.data.get("field_assessability_floors",{})
    floor_authority = bool(evidence.data.get("field_floor_adoption"))
    complete_roster = bool(evidence.data.get("source_roster_certified"))
    scores, coverage_scores, assessable = [], [], True
    for (field,currency), categories in by_field.items():
        assessed = [categories.get(key,{}) for key in ("correct","incorrect","missing_output")]
        unresolved = categories.get("disclosed_unassessable",{})
        nr = sum(item.get("rows",0) for item in assessed)
        nf = sum(item.get("source_fv",0) for item in assessed)
        row_coverage = _ratio(nr,nr+unresolved.get("rows",0))
        fv_coverage = _ratio(nf,nf+unresolved.get("source_fv",0))
        missing = sum(item.get("missing_fv",0) for item in [*assessed,unresolved])
        floor = floors.get(field)
        met = (floor_authority and complete_roster and floor is not None and not missing and bool(currency)
               and row_coverage is not None and fv_coverage is not None
               and min(row_coverage,fv_coverage)>=floor)
        correct = categories.get("correct",{})
        accuracy_row = _ratio(correct.get("rows",0),nr) if met else None
        accuracy_fv = _ratio(correct.get("source_fv",0),nf) if met else None
        details[field+"|"+currency] = dict(field=field,source_fv_currency=currency,categories=categories,assessed_row_share=row_coverage,
            assessed_source_fv_share=fv_coverage,accuracy_row=accuracy_row,accuracy_source_fv=accuracy_fv,
            floor=floor,floor_met=met,missing_source_fv=missing)
        if met and accuracy_row is not None and accuracy_fv is not None:
            scores.extend([accuracy_row,accuracy_fv])
        else:
            assessable=False
        coverage_scores.extend(v for v in (row_coverage,fv_coverage) if v is not None)
    if expected_fields is None:
        from pipeline.field_assessment import FIELDS
        expected_fields = FIELDS
    assessable = assessable and {f for f,c in by_field}==set(expected_fields)
    results[metric] = observation(min(scores) if scores and assessable else None,
        assessable=assessable,reason="All fields and both weights must meet adopted assessability floors; roster completeness also required",details=details)
    coverage = observation(min(coverage_scores) if coverage_scores else None,
        assessable=floor_authority and complete_roster and assessable,details=details,
        reason="Per-field floors await evidence-backed adoption; missing source FV stays unresolved")
    prior = results.get('field_assessed_coverage')
    if prior:
        values = [v for v in (prior['actual'], coverage['actual']) if v is not None]
        coverage = observation(min(values) if values else None,
            assessable=prior['assessable'] and coverage['assessable'],
            details={**prior['details'], **coverage['details']}, reason=coverage['reason'])
    results['field_assessed_coverage'] = coverage


def collect_primary(con,evidence,quarter,results):
    path = evidence.path("primary_anchors",candidate_bound=True)
    if not path:
        return
    table(con,"anchors",path)
    rows = con.execute("""SELECT a.cik,a.anchor_value,a.published_value,a.currency,a.source_evidence,
      a.anchor_kind,a.scope_comparable FROM anchors a SEMI JOIN eligible e ON lpad(a.cik,10,'0')=e.cik
      WHERE a.quarter=?""", [quarter]).fetchall()
    if len({r[0] for r in rows}) != len(rows):
        raise ContractError("More than one primary anchor per fund-quarter")
    supported = {"verified_override","fund_financials_plus_cash","fund_financials","companyfacts_concept"}
    membership=evidence.path('accounting_anchor_summaries',candidate_bound=True)
    comparable_population=None
    if membership:
        table(con,'anchor_membership_summary',membership)
        comparable_population={c for c,excluded,unknown in con.execute('''SELECT lpad(cik,10,'0'),
            TRY_CAST(excluded_rows AS BIGINT),TRY_CAST(unknown_rows AS BIGINT)
            FROM anchor_membership_summary WHERE anchor_date=?''',[quarter]).fetchall()
            if excluded==0 and unknown==0}
    valid, reasons = [], []
    for cik, target, published, currency, source, kind, comparable in rows:
        if comparable_population is not None and str(cik).zfill(10) not in comparable_population:
            reasons.append(dict(cik=cik,reason='Public population differs from anchor membership or contains unresolved rows'))
            continue
        if kind not in supported or not source or currency != "USD" or str(comparable).lower() != "true":
            reasons.append(dict(cik=cik,reason="Non-independent, missing evidence, currency or scope unresolved"))
            continue
        try:
            from decimal import Decimal
            target,published=Decimal(str(target)),Decimal(str(published))
            if not target.is_finite() or not published.is_finite():
                raise ValueError("nonfinite")
        except (ValueError,ArithmeticError):
            reasons.append(dict(cik=cik,reason="Anchor/value unavailable")); continue
        error=abs(published-target)
        ratio=error/abs(target) if target else (0 if error==0 else None)
        valid.append(dict(cik=cik,anchor=str(target),residual=str(published-target),
                          absolute_error=str(error),ratio=float(ratio) if ratio is not None else None))
    eligible=con.execute("SELECT count(*) FROM eligible").fetchone()[0]
    results["primary_fund_coverage"]=observation(_ratio(len(valid),eligible),details=dict(eligible=eligible,independent=len(valid),unavailable=reasons))
    if valid:
        from decimal import Decimal
        numerator=sum(Decimal(r["absolute_error"]) for r in valid)
        denominator=sum(abs(Decimal(r["anchor"])) for r in valid)
        results["primary_absolute_error_ratio"]=observation(_ratio(numerator,denominator),
            details=dict(absolute_error=str(numerator),absolute_anchor=str(denominator),funds=valid))
        zero_mismatch=any(r["ratio"] is None for r in valid)
        results["fund_primary_error_ratio"]=observation(max((r["ratio"] for r in valid if r["ratio"] is not None),default=None),
            assessable=not zero_mismatch,reason="Zero anchors require exact zero; a nonzero published balance cannot pass",details=dict(funds=valid))
        results["fund_primary_error_ratio"]["exact_failure"] = zero_mismatch
    if evidence.path("reconciliation",candidate_bound=True) and evidence.data.get("source_roster_certified"):
        ciks=[r["cik"] for r in valid]
        all_fv,anchored_fv,missing=con.execute("""SELECT sum(abs(fv)),
          sum(abs(fv)) FILTER(WHERE cik IN (SELECT unnest(?))),
          count(*) FILTER(WHERE fv IS NULL OR fv_variants!=1) FROM roster""",[ciks]).fetchone()
        results["primary_source_fv_coverage"]=observation(_ratio(anchored_fv or 0,all_fv),
            assessable=not missing and evidence.data.get("source_roster_currency")=="USD",
            details=dict(source_fv=all_fv,source_fv_under_independent_anchor=anchored_fv,missing_or_conflicting=missing))
    # Source-FV denominator must come from a deduplicated source roster. It
    # cannot be substituted with candidate weights or duplicated context FV.


def collect_pairs(con,evidence,results):
    from pipeline.output_schemas import OUTPUT_SCHEMAS
    from pipeline.programme.artifacts import verify_pair
    missing, failures, verified = [], [], []
    for name in OUTPUT_SCHEMAS:
        csv_path=evidence.path(name,candidate_bound=True)
        parquet_name=str(Path(name).with_suffix(".parquet"))
        parquet_path=evidence.path(parquet_name,candidate_bound=True)
        if csv_path is None or parquet_path is None:
            missing.append(name); continue
        if csv_path.with_suffix(".parquet")!=parquet_path:
            raise ContractError("Companion is not beside its canonical CSV: "+name)
        try:
            verify_pair(csv_path,con)
        except (ContractError,duckdb.Error) as error:
            failures.append(dict(artifact=name,reason=str(error)))
        else:
            verified.append(name)
    results["companion_parity"]=observation(len(failures),assessable=bool(failures) or not missing,
        reason="All eleven governed artifacts must be supplied from the same candidate",
        details=dict(verified=verified,failures=failures,missing=missing))


def collect_public(con,evidence,quarter,results):
    portfolio=evidence.path("public_portfolio",candidate_bound=True)
    sectors=evidence.path("public_sectors",candidate_bound=True)
    contributors=evidence.path("public_contributors",candidate_bound=True)
    if not all((portfolio,sectors,contributors)):
        return
    from decimal import Decimal
    p,s,contributors_data=read_json(portfolio),read_json(sectors),read_json(contributors)
    if p.get("asOf")!=quarter or contributors_data.get("asOf")!=quarter:
        return
    table_rows=contributors_data["rows"]
    con.execute("CREATE TEMP TABLE public_members(row_id VARCHAR,instrument VARCHAR,sector VARCHAR)")
    if table_rows:
        con.execute("""INSERT INTO public_members SELECT item.row_id,item.instrument,item.sector
          FROM (SELECT unnest(rows) AS item FROM read_json(?))""",[str(contributors)])
    # CSV strings and typed Parquet doubles must use the same decimal basis.
    # A direct DOUBLE -> high-scale DECIMAL cast can add binary scaling noise.
    missing=con.execute("SELECT count(*) FROM h WHERE TRY_CAST(CAST(fair_value AS VARCHAR) AS DECIMAL(38,12)) IS NULL").fetchone()[0]
    columns={r[0] for r in con.execute('DESCRIBE h').fetchall()}
    incompatible=con.execute("""SELECT count(*) FROM h WHERE TRY_CAST(fair_value AS DOUBLE) IS NOT NULL
        AND upper(coalesce(trim(CAST(fair_value_currency AS VARCHAR)),'')) NOT IN ('','USD')""").fetchone()[0] if 'fair_value_currency' in columns else 0
    total=con.execute("SELECT coalesce(sum(TRY_CAST(CAST(fair_value AS VARCHAR) AS DECIMAL(38,12))),0) FROM h").fetchone()[0]
    membership=con.execute("""SELECT count(*) FROM ((SELECT row_id FROM h EXCEPT ALL SELECT row_id FROM public_members)
      UNION ALL (SELECT row_id FROM public_members EXCEPT ALL SELECT row_id FROM h))""").fetchone()[0]
    partition_deltas={}
    bucket_failures=0
    for dimension,rows in (("instrument",p["instrumentBreakdown"]),("sector",s)):
        exact=sum((Decimal(r["fairValueExact"]) for r in rows),Decimal(0))
        partition_deltas[dimension]=str(total-exact)
        expected=con.execute(f"""SELECT m.{dimension},coalesce(sum(TRY_CAST(CAST(h.fair_value AS VARCHAR) AS DECIMAL(38,12))),0),count(*)
          FROM public_members m JOIN h USING(row_id) GROUP BY 1""").fetchall()
        got={r.get("label",r.get("sector")): (Decimal(r["fairValueExact"]),r["positionCount"]) for r in rows}
        want={label:(fv,count) for label,fv,count in expected}
        bucket_failures+=int(got!=want or len(got)!=len(rows))
    headline_delta=total-Decimal(p["fairValueExact"])
    failure=bool(incompatible or headline_delta or membership or bucket_failures or any(Decimal(v) for v in partition_deltas.values()))
    results["public_partition_delta"]=observation(int(failure),assessable=failure or missing==0,
        details=dict(headline_delta=str(headline_delta),partition_deltas=partition_deltas,
                     contributor_multiset_difference=membership,bucket_failures=bucket_failures,missing_fv=missing,
                     incompatible_currency_rows=incompatible))


def collect_rule_audits(con,evidence,results):
    admissions=evidence.path("input_admission_audit",candidate_bound=True)
    if admissions:
        table(con,"admissions",admissions)
        total,failures=con.execute("""SELECT count(*),count(*) FILTER(WHERE lower(loaded)='true' AND
          (admission_status!='promoted' OR lower(path) LIKE '%.proposed.%')) FROM admissions""").fetchone()
        results["proposed_input_admission"]=observation(failures,assessable=total>0,
            details=dict(audited_inputs=total),reason="Actual loader audit; empty audit cannot establish non-admission")
    spreads=evidence.path("spread_unit_audit",candidate_bound=True)
    if spreads:
        table(con,"spread_audit",spreads)
        n,failures=con.execute("""SELECT count(*),count(*) FILTER(WHERE
          TRY_CAST(actual_pct AS DECIMAL(38,12)) IS NULL OR TRY_CAST(expected_pct AS DECIMAL(38,12)) IS NULL
          OR TRY_CAST(actual_pct AS DECIMAL(38,12))!=TRY_CAST(expected_pct AS DECIMAL(38,12))) FROM spread_audit""").fetchone()
        results["spread_unit_violations"]=observation(failures,assessable=n>0,
            details=dict(audited_rows=n),reason="Compare admitted corrections with written percentage-point values")


def collect_roster(con,evidence,quarter,results):
    path=evidence.path("reconciliation",candidate_bound=True)
    if path is None or evidence.path("obligations") is None:
        return
    table(con,"reconciliation",path)
    con.execute("""CREATE TEMP TABLE recon_scope AS SELECT r.* FROM reconciliation r
      SEMI JOIN eligible e ON lpad(r.cik,10,'0')=e.cik
      WHERE substr(r.period,1,10)=? AND r.status IN
      ('matched','value_mismatch','missing_from_pipeline','extra_in_pipeline')""",[quarter])
    con.execute("""CREATE TEMP TABLE roster AS SELECT lpad(cik,10,'0') AS cik,source_row_id,
      min(TRY_CAST(source_fair_value AS DOUBLE)) AS fv,
      count(DISTINCT TRY_CAST(source_fair_value AS DOUBLE)) AS fv_variants
      FROM recon_scope WHERE nullif(source_row_id,'') IS NOT NULL GROUP BY 1,2""")
    con.execute("""CREATE TEMP TABLE comparable AS SELECT h.* FROM h SEMI JOIN eligible USING(cik)
      WHERE nullif(src_context_id,'') IS NOT NULL""")
    con.execute("""CREATE TEMP TABLE proposed_links AS SELECT DISTINCT r.source_row_id,h.row_id
      FROM recon_scope r JOIN comparable h ON r.output_row_id=h.row_id AND lpad(r.cik,10,'0')=h.cik
      WHERE nullif(r.source_row_id,'') IS NOT NULL""")
    con.execute("""CREATE TEMP TABLE one_to_one AS SELECT * FROM proposed_links
      QUALIFY count(*) OVER(PARTITION BY source_row_id)=1 AND count(*) OVER(PARTITION BY row_id)=1""")
    source_rows,source_fv,missing,conflicts=con.execute("SELECT count(*),sum(abs(fv)),count(*) FILTER(WHERE fv IS NULL),count(*) FILTER(WHERE fv_variants>1) FROM roster").fetchone()
    candidate_rows=con.execute("SELECT count(*) FROM comparable").fetchone()[0]
    matches,matched_fv=con.execute("SELECT count(*),sum(abs(r.fv)) FROM roster r SEMI JOIN one_to_one USING(source_row_id)").fetchone()
    ambiguous=con.execute("SELECT count(*) FROM proposed_links ANTI JOIN one_to_one USING(source_row_id,row_id)").fetchone()[0]
    certified=bool(evidence.data.get("source_roster_certified")) and not ambiguous and not conflicts
    diagnostic=dict(source_rows=source_rows,comparable_candidate_rows=candidate_rows,one_to_one_matches=matches,
        ambiguous_links=ambiguous,conflicting_source_fv=conflicts,missing_source_fv=missing,
        source_roster_certified=certified,source_reconciliation_sha256=sha(path))
    results["roster_row_recall"]=observation(_ratio(matches,source_rows),assessable=certified,details=diagnostic)
    results["roster_row_precision"]=observation(_ratio(matches,candidate_rows),assessable=certified,details=diagnostic)
    currency_resolved=evidence.data.get("source_roster_currency")=="USD"
    results["roster_fv_recall"]=observation(_ratio(matched_fv or 0,source_fv),assessable=certified and not missing and currency_resolved,details=diagnostic)
    # With extras, candidate values cannot substitute for their absent source
    # weights. Row precision is still reported, FV precision stays unassessable.
    extras=candidate_rows-matches
    results["roster_fv_precision"]=observation(1.0 if candidate_rows and not extras else None,
        assessable=certified and not missing and currency_resolved and not extras,
        reason="Extra candidate rows have no established source-FV weight" if extras else "All comparable rows have one source correspondence",
        details=dict(**diagnostic,extra_candidate_rows=extras))
    fund_rows=con.execute("""WITH r AS (SELECT cik,count(*) AS rows,sum(abs(fv)) AS fv FROM roster GROUP BY 1),
      m AS (SELECT cik,count(*) AS rows,sum(abs(fv)) AS fv FROM roster SEMI JOIN one_to_one USING(source_row_id) GROUP BY 1),
      p AS (SELECT cik,count(*) AS rows FROM comparable GROUP BY 1)
      SELECT e.cik,r.rows,r.fv,coalesce(m.rows,0),coalesce(m.fv,0),coalesce(p.rows,0)
      FROM eligible e LEFT JOIN r USING(cik) LEFT JOIN m USING(cik) LEFT JOIN p USING(cik) WHERE r.rows>0 ORDER BY e.cik""").fetchall()
    from pipeline import config
    floors=read_json(config.REFERENCE_DIR/"quarter_acceptance_programme_thresholds.json")["per_fund_roster_floors"]
    details=[]
    for cik,n,fv,m,mfv,p in fund_rows:
        recall,precision,fv_recall=_ratio(m,n),_ratio(m,p),_ratio(mfv,fv)
        breach=any(value is not None and value<bar for value,bar in
                   ((recall,floors["rows"]),(precision,floors["rows"]),(fv_recall,floors["fair_value"])))
        details.append(dict(cik=cik,row_recall=recall,row_precision=precision,fv_recall=fv_recall,
                            breach=breach))
    results["fund_roster_floor_breaches"]=observation(sum(row["breach"] for row in details),
        assessable=certified and not missing and currency_resolved and not extras,
        details=dict(funds=details,unresolved_fv_precision=bool(extras)))


def collect(holdings,manifest,quarter,cohort,*,evidence=None):
    evidence=evidence or Evidence(manifest,holdings)
    results={}
    with duckdb.connect(config={"threads":2,"memory_limit":"-1"}) as con:
        collect_holdings(con,evidence,quarter,cohort,results)
        collect_contexts(con,evidence,quarter,results)
        collect_fields(con,evidence,quarter,results)
        from pipeline.categorical_field_assessment import FIELDS as OTHER_FIELDS
        collect_fields(con,evidence,quarter,results,name='other_fields',
                       metric='other_field_accuracy',expected_fields=OTHER_FIELDS)
        collect_roster(con,evidence,quarter,results)
        if evidence.path("obligations"):
            collect_primary(con,evidence,quarter,results)
        collect_pairs(con,evidence,results)
        collect_public(con,evidence,quarter,results)
        collect_rule_audits(con,evidence,results)
    evidence.verify()
    return results
