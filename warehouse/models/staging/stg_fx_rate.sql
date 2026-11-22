-- One row per currency and quote date: US dollars for one unit of the currency (usd_per_unit). Direction: EUR
-- 1.1567 on 2018-10-01 means one euro bought 1.1567 dollars, so dollars = amount in the currency times usd_per_unit
-- (tests/stg_fx_rate_known_rate.sql). Source: data/reference/monetary_conversion/fred_h10_usd_per_unit.csv, the
-- retained file behind the admitted quotes.json that production's principal conversion reads
-- (pipeline/monetary_fx.py principal_reference_table, scripts/programme_closeout/fx.py convert). Types only, no logic:
-- which date's rate applies to a report date is decided in int_field_normalised.
select
    upper(trim(currency)) as currency
    , cast(date as date) as rate_date
    , cast(usd_per_unit as double) as usd_per_unit
    , series
from {{ source('reference', 'fx_rate') }}
