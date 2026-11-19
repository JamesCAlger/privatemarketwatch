-- Rules 4 and 5 on hand-made labels, read with the real patterns in seeds/role_pattern.csv (macro role_text_rules).
-- Returns every label whose text rule or cash flag is not the expected one. The labels are invented, not filed.
-- False positives covered: a real position whose label contains 'total' or 'cash' inside a word or later in a segment,
-- an affiliation qualifier that is not a heading, a money-market fund inside the cash bucket wording, and a company
-- name containing money market (not a fund: no cash flag, and it does not stop the cash bucket).
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
        , ('t12', 'Example Money Market Treasury Portfolio - Class I | Some JV LP', null, true)
        , ('t13', 'Some JV LP, Example Money Market Fund', null, true)
        -- money-market fund naming without the words money market (fix round 2)
        , ('t14', 'Example Treasury Obligations Cash Management', null, true)
        , ('t15', 'Example Government Cash Management - Institutional Shares | Some JV LP', null, true)
        , ('t16', 'Example Select Treasury Based Liquidity Fund', null, true)
        , ('t17', 'Example Euro Liquidity Fund, Some JV LP', null, true)
        , ('t18', 'Example Financial Square Government Fund Institutional', null, true)
        , ('t19', 'Example U.S. Government Fund, Institutional Shares | Affiliated Issuer', null, true)
        , ('t20', 'Cash and Cash Equivalents | Example Euro Liquidity Fund', null, true)
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
        -- a company whose name contains money market is not a money-market fund (fix round 1)
        , ('f10', 'Acme Money Market Software LLC | First lien', null, false)
        , ('f11', 'Cash and Cash Equivalents | Acme Money Market Software LLC', 5, false)
        -- operating companies with cash management, liquidity, treasury or government in the name (fix round 2)
        , ('f12', 'Acme Cash Management LLC, First lien senior secured loan', null, false)
        , ('f13', 'Liquidity Services Holdings, Inc. | First lien senior secured loan | Non-Affiliated Issuer', null, false)
        , ('f14', 'Acme Group Treasury, LLC | First lien senior secured loan', null, false)
        , ('f15', 'Acme Government Services Holdings, LLC, First lien senior secured loan', null, false)
        , ('f16', 'Software ExampleTreasury Example Treasury SS LLC', null, false)
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
