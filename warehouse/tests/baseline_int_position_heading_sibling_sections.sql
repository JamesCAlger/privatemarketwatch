-- Text slice P4 baseline (fix round 2, 2026-11-26): published positions whose level-1 and level-2 headings
-- (int_position_heading) both name 'controlled' or 'affiliated', with different normalised texts (macro
-- page_heading_key): a sibling section kept as a parent. Cause: a section heading printed without the upper heading
-- of its stack (for example "Controlled/Affiliated Investments" in a shorter run than the earlier "Non-Controlled/
-- Affiliated Investments") gets a lower level from its own runs, so it neither replaces nor drops the older section at
-- the higher level. Structure cannot tell this from a real parent; deciding what a heading means is a later slice with
-- a per-fund rule. Counted against a ceiling set to the measured count
-- (baseline_max.int_position_heading_sibling_sections). Measured 2026-11-26: see the ceiling (one fund 10, a second 9,
-- a third 4). The affiliation words are a test measure only; no model reads them.
{{ config(severity='error', warn_if='>0', error_if='>' ~ var('baseline_max')['int_position_heading_sibling_sections']) }}
select a.accession, a.context_id, a.text as level_1_text, b.text as level_2_text
from {{ ref('int_position_heading') }} a
join {{ ref('int_position_heading') }} b
    on b.accession = a.accession and b.context_id = a.context_id and b.heading_level = 2
where a.heading_level = 1 and a.is_published
    and regexp_matches(lower(a.text), 'controlled|affiliated') and regexp_matches(lower(b.text), 'controlled|affiliated')
    and {{ page_heading_key('a.text') }} <> {{ page_heading_key('b.text') }}
