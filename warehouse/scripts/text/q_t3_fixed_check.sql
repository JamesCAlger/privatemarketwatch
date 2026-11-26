-- Text slice R phase 3 check 1d: int_text_check_fixed_rate, every shape in scope.
select cik, unit_key, shape, role_fwd, role_rev, number_rows, rows_with_code, compared, equal, verdict, label_changes from int_text_check_fixed_rate order by 1, 2, 3
