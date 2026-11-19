-- Decides rules 4 and 5 of the row roles (spec 6.2) by text: which context's label reads as a total, net assets, an
-- affiliation heading (rule 4) or the cash bucket (rule 5), and which names a money-market fund (the rule 5 exception,
-- which also marks the row as cash, D7). The patterns are the rows of seeds/role_pattern.csv; the matching is the macro
-- role_text_rules (macros/role_text_rules.sql). This model holds no label text. Only contexts that rules 0 to 3 left
-- open are read; a context with no identifier label gets no text rule.
with open_context as (
    select s.accession, s.context_id, cf.identifier_label
    from {{ ref('int_role_structure') }} s
    join {{ ref('int_context_feature') }} cf on cf.accession = s.accession and cf.context_id = s.context_id
    where s.role is null
)

{{ role_text_rules('open_context') }}
