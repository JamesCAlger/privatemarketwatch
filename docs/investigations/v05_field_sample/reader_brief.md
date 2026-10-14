# Reader brief: per-field error sample

You label cards. Each card is one published holdings row with its printed schedule line, found in the
cached inline-XBRL filing by the row's context id. You judge two things per field:

1. **published**: does our published value match what the filing prints?
2. **tag**: did the filer's XBRL tag the printed value correctly on this row?

Work only from the card. If a card is genuinely not decidable from it (a position printed over two
lines, a header you cannot see), you may read the filing:
`python scripts/v05_evidence/page_line.py <cik> <accession> "<phrase>" 3 600 300`.
Do not write any file except your labels file. Never run `python -` or `python -c`.

## What is on a card

- **Table header rows**: the column headings. Units are usually in the filing's headings (thousands,
  or millions for Ares-style "5.2"). Published money is in dollars.
- **The printed line**: its cells in order. After `<-` are the facts tagged in that cell: concept = value
  (value already scaled; rates as decimals, 0.0957 = 9.57 %). "(same investment, other period context)"
  is normal. "ON ANOTHER INVESTMENT'S CONTEXT" means the fact belongs to a different row.
- **Lines printed before / after it**: some filers print one position over two lines (for example a
  "9.29 % Cash/" part above the name), and continuation rows print no issuer name: the issuer is on
  the nearest line above that prints one.
- **Facts on this context not on the printed line**: hidden facts (enumerations such as the reference
  rate, the investment type) or facts printed elsewhere. They count as tags.
- **Member (identifier text)**: the filer's free-text label for the row's context.
- **Published**: our values. `(tag: equal | differs)` compares our value with the tag on the row.

## Fields and conventions

| Field | Judge | Counts as matching |
|---|---|---|
| row_identity | Is the published row this printed position? | Fair value, cost and par agree with the printed line. |
| issuer_name | The company | Footnote markers, punctuation, "(dba ...)" and "(fka ...)" differences. A legal name from the member that is the same company. |
| instrument_and_class | `instrument_description` and `asset_category` together | Wording from the member is fine. Wrong only if it contradicts the page: wrong lien, loan vs equity, common vs preferred vs warrant, revolver vs term loan. |
| fair_value, cost, principal_amount | Value (and currency for principal) | Unit scaling and the printed rounding. A dash is zero or blank. |
| shares_held | Unit count | Count printed in its column or in the name, "( 652,174 Class A-1 units)". |
| pct_of_net_assets | Percent | Published in percent (0.1 = 0.1 %). |
| interest_rate | The coupon | Either the cash part or the all-in coupon. |
| basis_spread | The margin over the reference rate | |
| reference_rate_type | The benchmark | S / SF / SOFR = SOFR; E = EURIBOR; SO / SONIA = SONIA; L = LIBOR; P = PRIME; C / CORRA = CORRA (a "C" with no legend: unclear). |
| pik_rate | The PIK part | |
| maturity_date | Maturity | A printed MM/YYYY matches any day of that month. |

**published**, one of:
- `ok`: matches the page, or both blank.
- `missing`: the page prints a value; we publish none.
- `extra`: we publish a value; the page prints none (a dash or no such column).
- `wrong`: both present and they differ.
- `convention`: differs only by the open convention D-092: the whole coupon is printed as PIK beside a spread, and we publish the PIK rate and spread with no interest rate. Use only for interest_rate in that shape.
- `unclear`: you cannot tell from the card (say why in `note`).

**tag** (the filer's XBRL against its own printed line, regardless of what we published), one of:
- `right`: the printed value is tagged with the right concept and value on this row's context. For issuer_name, instrument_and_class and row_identity the "tag" is the member text and the context's facts: `right` if they agree with the printed line.
- `wrong_value`: right concept, but the value or scale differs from the printed figure.
- `wrong_label`: the value matches the printed figure but the concept is wrong. Examples: a plain coupon tagged as PIK; a margin tagged as the rate or as PIK with no spread fact; a par tagged as a share count. For the member text: a lien, class or name that contradicts the page.
- `wrong_row`: the fact belongs to another printed line, or this line's fact is on another investment's context.
- `untagged`: the page prints it and no fact on this context carries it (look at the hidden facts too).
- `not_printed`: the page does not print this field.
- `unclear`.

**cause**, required when published is `missing`, `extra` or `wrong`:
- `tag`: we followed the filer's wrong or missing tag.
- `pipeline`: the tag (or the page, where untagged) was clear and we published something else.
- `page`: the printed page is itself inconsistent.
- `unclear`.

**note**: one short sentence for every field that is not `ok` / `right`, with the printed text.

Judge each field on its own. Do not assume a figure is right because the tag agrees with our value:
the point is to compare both with the page.

## Output

A JSON list, one object per card, every field present:

```json
[{"card": "C001",
  "fields": {
    "row_identity": {"published": "ok", "tag": "right", "cause": "", "note": ""},
    "issuer_name": {"published": "ok", "tag": "right", "cause": "", "note": ""},
    "instrument_and_class": {...}, "fair_value": {...}, "cost": {...}, "principal_amount": {...},
    "shares_held": {...}, "pct_of_net_assets": {...}, "interest_rate": {...}, "basis_spread": {...},
    "reference_rate_type": {...}, "pik_rate": {...},
    "maturity_date": {"published": "missing", "tag": "untagged", "cause": "pipeline", "note": "prints 05/2029; none published"}}}]
```

Then run `python scripts/v05_evidence/field_sample.py check <your labels file>` and fix every problem
it lists. Reply with: the file path, the number of cards, and the five most notable errors you saw
(card, field, one line).
