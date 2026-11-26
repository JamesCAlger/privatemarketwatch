-- Slice R fix round 1: status and kind of the rate fields in int_field_normalised (tags before corrections). Read-only.
select field, status, rate_kind, count(*) n from int_field_normalised
where field in ('interest_rate', 'interest_rate_cash', 'pik_rate', 'spread') group by all order by 1, 2, 3
