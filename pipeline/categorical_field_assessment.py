"""Independent, conservative source references for nonnumeric field fidelity.

Read source facts and explicit classification axes; never call the production
classifiers or infer a reference from a candidate's value or borrower name.
Unsupported disclosed members remain unassessable, rather than disappearing
from the disclosure denominator. This module does not change holdings.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
import re

from pipeline.context_inventory import XBRLI, local

POLICY_VERSION = 'categorical-field-assessment.v1'
FIELDS = ('interest_rate_kind', 'maturity_date', 'maturity_precision',
          'maturity_status', 'instrument_type', 'lien_position')

# Exact disclosed member labels. A custom member outside this small vocabulary
# requires independent interpretation; production keyword rules cannot certify it.
INSTRUMENT_MEMBERS = {
    'TermLoanMember': 'Term Loan', 'TermLoansMember': 'Term Loan',
    'DelayedDrawTermLoanMember': 'Delayed Draw Term Loan',
    'DelayedDrawTermLoansMember': 'Delayed Draw Term Loan',
    'RevolvingCreditFacilityMember': 'Revolver',
    'RevolvingCreditFacilitiesMember': 'Revolver',
    'RevolverMember': 'Revolver', 'UnitrancheMember': 'Unitranche',
    'UnitrancheLoansMember': 'Unitranche',
}
LIEN_MEMBERS = {
    'FirstLienMember': 'First Lien', 'FirstLienLoansMember': 'First Lien',
    'FirstLienSeniorSecuredLoansMember': 'First Lien',
    'SecondLienMember': 'Second Lien', 'SecondLienLoansMember': 'Second Lien',
    'SecondLienSeniorSecuredLoansMember': 'Second Lien',
    'UnsecuredLoansMember': 'Unsecured', 'UnsecuredDebtMember': 'Unsecured',
}


def maturity_reference(raw):
    """Interpret only valid ISO day/month/year or explicit perpetual wording."""
    raw = (raw or '').strip()
    if raw.casefold() in {'perpetual', 'no maturity', 'no maturity date'}:
        return dict(maturity_date=None, maturity_precision='unknown',
                    maturity_status='perpetual'), 'ready'
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw):
            value, precision, status = date.fromisoformat(raw), 'day', 'dated'
        elif re.fullmatch(r'\d{4}-\d{2}', raw):
            year, month = map(int, raw.split('-'))
            value = date(year, month, monthrange(year, month)[1])
            precision, status = 'month', 'partial'
        elif re.fullmatch(r'\d{4}', raw):
            value, precision, status = date(int(raw), 12, 31), 'year', 'partial'
        else:
            raise ValueError('Unsupported lexical form')
    except (ValueError, OverflowError):
        return {}, 'unresolved_maturity_text'
    return dict(maturity_date=value.isoformat(), maturity_precision=precision,
                maturity_status=status), 'ready'


def read_facts(tree, contexts):
    """Return references from a parsed, network-disabled cached XBRL instance.

    The caller supplies independently checked entity/date contexts and pins the
    source document hash. A separate assessment joins these to candidate rows.
    """
    facts = []

    def emit(context_id, field, value, concept, raw, reason='ready', nil=False):
        context = contexts.get(context_id)
        if not context or not context.get('quarter'):
            return
        if not context.get('valid_entity'):
            reason = 'reporting_entity_mismatch'
        facts.append(dict(context_id=context_id, quarter=context['quarter'],
            field=field, reference_value=value, concept=concept, raw=raw,
            reason=reason, nil=nil))

    for node in tree.getroot():
        context_id = node.get('contextRef')
        if not context_id:
            continue
        concept = local(node.tag).lower()
        raw = ''.join(node.itertext()).strip()
        nil = node.get('{http://www.w3.org/2001/XMLSchema-instance}nil') in {'true', '1'}
        if 'investmentmaturitydate' in concept:
            reference, reason = maturity_reference(raw)
            for field in ('maturity_date', 'maturity_precision', 'maturity_status'):
                emit(context_id, field, reference.get(field), node.tag, raw,
                     'source_nil' if nil else reason, nil)
        elif ('interestrate' in concept or 'effectiveyield' in concept or
              'yieldtomaturity' in concept):
            # Spread/floor/PIK facts describe another quantity, not coupon kind.
            if any(part in concept for part in ('spread', 'floor', 'paidinkind', 'pik')):
                continue
            if concept in {'investmentinterestratepaidincash', 'investmentcashinterestrate'}:
                kind = 'cash'
            elif 'allininterestrate' in concept:
                kind = 'all_in'
            elif 'effectiveyield' in concept or 'yieldtomaturity' in concept:
                kind = 'effective_yield'
            else:
                kind = None
            emit(context_id, 'interest_rate_kind', kind, node.tag, raw,
                 'source_nil' if nil else ('ready' if kind else 'unresolved_rate_kind'), nil)

    for node in tree.findall(f'{{{XBRLI}}}context'):
        context_id = node.get('id')
        for member in node.iter():
            if local(member.tag) != 'explicitMember':
                continue
            axis = local(member.get('dimension', '')).lower()
            if not any(part in axis for part in ('investmenttype', 'investmentinstrument', 'lienposition')):
                continue
            raw = (member.text or '').strip()
            name = local(raw)
            # A recognized product alone says nothing about lien, and vice
            # versa. An unsupported member stays unresolved for both fields.
            mappings = [('lien_position', LIEN_MEMBERS)] if 'lienposition' in axis else [
                ('instrument_type', INSTRUMENT_MEMBERS), ('lien_position', LIEN_MEMBERS)]
            for field, mapping in mappings:
                value = mapping.get(name)
                if value is None and any(name in known for _, known in mappings):
                    continue
                emit(context_id, field, value, member.get('dimension'), raw,
                     'ready' if value else 'unsupported_classification_member')
    return facts


def comparison_sql():
    """Compare references after aggregating source/candidate multiplicity.

    Inputs use the same source roster, candidate correspondences and absolute
    source FV as numeric assessments. NULL-safe equality handles an explicitly
    perpetual maturity without inventing a date.
    """
    return """SELECT s.*,p.candidate_rows,p.published,
      CASE
        WHEN NOT s.source_complete THEN 'disclosed_unassessable'
        WHEN coalesce(s.fact_count,0)=0 THEN 'not_disclosed'
        WHEN s.reason<>'ready' OR s.variants<>1 OR s.source_role<>'confirmed_position'
          OR s.correspondence_status<>'ready' OR coalesce(p.candidate_rows,0)>1
          THEN 'disclosed_unassessable'
        WHEN coalesce(p.candidate_rows,0)=0 THEN 'missing_output'
        WHEN p.published IS NOT DISTINCT FROM s.reference_value THEN 'correct'
        WHEN p.published IS NULL THEN 'missing_output'
        ELSE 'incorrect' END AS category,
      CASE
        WHEN NOT s.source_complete THEN 'incomplete_source'
        WHEN coalesce(s.fact_count,0)=0 THEN 'no_categorical_tag_disclosed'
        WHEN s.variants<>1 THEN 'conflicting_source_facts'
        WHEN s.reason<>'ready' THEN s.reason
        WHEN s.source_role<>'confirmed_position' THEN 'unresolved_position_role'
        WHEN s.correspondence_status<>'ready' THEN s.correspondence_status
        WHEN coalesce(p.candidate_rows,0)>1 THEN 'ambiguous_candidate_context_join'
        WHEN coalesce(p.candidate_rows,0)=0 THEN 'missing_row'
        ELSE 'exact_source_meaning_comparison' END AS assessment_reason
      FROM other_source_fields s LEFT JOIN other_published p
      USING(cik,quarter,accession,context_id,field)"""


def assemble_comparisons(con, source_facts):
    """Use the E4 source roster and independently nominated candidate links."""
    con.execute("""CREATE TABLE other_fact_groups AS SELECT cik,accession,quarter,context_id,field,
      count(*) FILTER(WHERE NOT CAST(nil AS BOOLEAN)) AS fact_count,
      count(DISTINCT struct_pack(value:=reference_value)) FILTER(WHERE NOT CAST(nil AS BOOLEAN)) AS variants,
      min(reference_value) AS reference_value,
      CASE WHEN bool_and(reason='ready') THEN 'ready' ELSE string_agg(DISTINCT reason,';') END AS reason
      FROM read_csv(?,all_varchar=true) GROUP BY 1,2,3,4,5""", [str(source_facts)])
    con.execute('CREATE TABLE other_fields(field VARCHAR)')
    con.executemany('INSERT INTO other_fields VALUES (?)', [(f,) for f in FIELDS])
    con.execute("""CREATE TABLE other_source_fields AS SELECT r.cik,r.quarter,r.accession,r.context_id,
      r.source_role,r.reference_origin,r.source_fv,r.currency AS source_fv_currency,
      r.source_complete AND coalesce(CAST(d.complete AS BOOLEAN),false) AS source_complete,
      f.field,g.fact_count,g.variants,g.reference_value,g.reason,
      CASE WHEN coalesce(q.rows,0)=0 OR EXISTS(SELECT 1 FROM links l WHERE
        l.cik=r.cik AND l.quarter=r.quarter AND l.accession=r.accession AND l.context_id=r.context_id)
        THEN 'ready' ELSE 'unresolved_source_candidate_correspondence' END AS correspondence_status
      FROM reference_contexts r CROSS JOIN other_fields f
      LEFT JOIN other_fact_groups g USING(cik,quarter,accession,context_id,field)
      LEFT JOIN document_status d USING(cik,accession)
      LEFT JOIN quarter_candidate_counts q USING(cik,quarter)""")
    columns = {r[0] for r in con.execute('DESCRIBE candidate').fetchall()}
    parts = []
    for field in FIELDS:
        expression = f"nullif(trim(CAST(h.{field} AS VARCHAR)),'')" if field in columns else 'NULL::VARCHAR'
        parts.append(f"""SELECT l.cik,l.quarter,l.accession,l.context_id,'{field}' AS field,
          count(*) AS candidate_rows,min({expression}) AS published
          FROM links l JOIN candidate h USING(row_id) GROUP BY 1,2,3,4""")
    con.execute('CREATE TABLE other_published AS '+' UNION ALL '.join(parts))
    con.execute('CREATE TABLE other_assessments AS '+comparison_sql())
