-- One row per wrapper declaration entry, as loaded. Empty text becomes null; dates are cast. No other logic.
select
    rule_id
    , nullif(cik, '') as cik
    , try_cast(nullif(valid_from, '') as date) as valid_from
    , try_cast(nullif(valid_to, '') as date) as valid_to
    , validity_basis
    , nullif(sel_accession, '') as sel_accession
    , nullif(sel_axis, '') as sel_axis
    , nullif(sel_member, '') as sel_member
    , nullif(sel_label, '') as sel_label
    , nullif(sel_label_pattern, '') as sel_label_pattern
    , nullif(sel_feature, '') as sel_feature
    , nullif(sel_concept_namespace, '') as sel_concept_namespace
    , nullif(sel_concept_local, '') as sel_concept_local
    , target
    , action
    , nullif(parameter, '') as parameter
    , nullif(evidence, '') as evidence
    , origin
    , rule_class
    , priority
    , valid_from as valid_from_text
    , valid_to as valid_to_text
from {{ source('readings', 'reading_rule') }}
