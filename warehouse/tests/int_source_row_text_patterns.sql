-- Rules 4 and 5 on hand-made labels, read with the real patterns in seeds/role_pattern.csv (macro role_text_rules).
-- Returns every label whose text rule or cash flag is not the expected one. The labels are invented, not filed.
-- False positives covered: a real position whose label contains 'total' or 'cash' inside a word or later in a segment,
-- an affiliation qualifier that is not a heading, and a money-market fund inside the cash bucket wording.
with open_context as (
    select * from (values
        -- rule 4
          ('t01', 'Total Investments', 4, false)
        , ('t02', 'Subtotal First Lien Debt', 4, false)
        , ('t03', 'Sub-total | Controlled Affiliates', 4, false)
        , ('t04', 'Net Assets', 4, false)
        , ('t05', 'Non-Controlled/Non-Affiliated Investments', 4, false)
        , ('t06', 'Acme Corp | Controlled Affiliated Investments', 4, false)
        -- rule 5
        , ('t07', 'Cash and Cash Equivalents', 5, false)
        , ('t08', 'Other Cash and Cash Equivalents | Some JV LP', 5, false)
        , ('t09', 'Some JV LP, Other Cash and Cash Equivalents', 5, false)
        -- rule 5 exception: a money-market fund is cash, not the bucket
        , ('t10', 'Cash and Cash Equivalents | Example Treasury Money Market Fund', null, true)
        , ('t11', 'Example Government Money Market Fund - Institutional Shares', null, true)
        -- false positives: must stay open for the later rules (no text rule, not cash)
        , ('f01', 'TotalCare Holdings, LLC | First lien senior secured loan', null, false)
        , ('f02', 'Acme Total Solutions Inc. | Non-Affiliated Issuer', null, false)
        , ('f03', 'Cashmere Brands LLC, First lien senior secured loan', null, false)
        , ('f04', 'CashFlow Software Inc. | Second Lien', null, false)
        , ('f05', 'Acme Corp | Non-Affiliated Issuer', null, false)
        , ('f06', 'Beta Corp | Affiliated Issuer', null, false)
        , ('f07', 'Petty Cash Lending LLC, Term loan', null, false)
        , ('f08', 'Gamma Net Assets Holdings LLC', null, false)
        , ('f09', 'Delta Totals Inc.', null, false)
    ) v(context_id, identifier_label, expected_rule, expected_cash)
)

select o.context_id, o.identifier_label, o.expected_rule, r.text_rule, o.expected_cash, r.cash_pattern_id
from open_context o
left join (
    with open_with_accession as (
        select 'fixture' as accession, context_id, identifier_label from open_context
    )
    {{ role_text_rules('open_with_accession') }}
) r on r.context_id = o.context_id
where o.expected_rule is distinct from r.text_rule
   or o.expected_cash <> (r.cash_pattern_id is not null)
