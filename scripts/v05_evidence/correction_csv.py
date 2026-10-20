"""CSV key/serialization helpers for audited row-correction appends."""


def correction_key(row):
    return (row['cik'].zfill(10), row['report_date'], row['accession_number'],
            row['bdc_investment_identifier'], row['field'], row.get('src_context_id', '').strip())


def spec_context(spec):
    # Existing specs use context as source evidence metadata, without narrowing scope.
    return spec.get('correction_context', '')


def append_record(columns, *, cik, quarter, accession, identifier, field, value,
                  reason, evidence, author, added_on, context=''):
    if context and 'src_context_id' not in columns:
        raise ValueError('Scoped correction requires src_context_id CSV column')
    record = dict(cik=cik, report_date=quarter, accession_number=accession,
                  bdc_investment_identifier=identifier, field=field, value=value,
                  reason=reason, source_evidence=evidence, author=author,
                  date_added=added_on, src_context_id=context)
    return {column: record.get(column, '') for column in columns}
