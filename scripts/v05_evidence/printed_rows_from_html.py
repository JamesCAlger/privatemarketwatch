"""Read-only: draft source_encodings.printed_rows_without_context entries from a cached filing's
printed schedule tables, for a quarter whose XBRL instance carries no schedule.

    python scripts/v05_evidence/printed_rows_from_html.py <cik> <accession> <quarter> <spec.json> <out.json>

spec.json gives the table indices and the cell column of each field:
    {"tables": [19, 20], "issuer": 0, "instrument": 2, "reference": 4, "spread": 11, "spread_text": 10,
     "coupon": 15, "maturity": 18, "principal": 21, "cost": 25, "fair_value": 29,
     "totals": {"cost": 210903951, "fair_value": 207554379}}

A row is a position when both the issuer and instrument cells are filled. The industry is the last
row above it with only its first cell filled. Each entry carries the printed line (the row's cells
joined, normalised as the fund gate compares quotes) and is refused unless the line is found in the
page text and passes the wrapper loader's own check (pipeline.printed_rows.entry_errors). Spread is
declared only where the spread cell is a single number (a 'x% Cash + y% PIK' cell is left out, as is
the reference rate of a fixed-rate row). The run fails unless the rows sum to the printed totals.
Nothing is written outside <out.json>.
"""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "v05_evidence"))
from fund_gate import normalise, page_text  # noqa: E402
from pipeline.html_extract import _extract_tables  # noqa: E402
from pipeline.printed_rows import entry_errors  # noqa: E402


def _cell(row, col):
    return row[col].strip() if col is not None and col < len(row) else ""


def _money(text):
    text = normalise(text).replace("$", "").strip()
    if text in ("-", ""):
        return 0
    negative = text.startswith("(")
    number = int(text.strip("() ").replace(",", ""))
    return -number if negative else number


def _percent(text):
    text = normalise(text).strip()
    return float(text) if re.fullmatch(r"\d+(\.\d+)?", text) else None


def main(cik, accession, quarter, spec_path, out_path):
    spec = json.loads(Path(spec_path).read_text())
    cik10 = cik.zfill(10)
    page = REPO / "data/raw/filings/bdc_html" / cik10.lstrip("0") / (accession.replace("-", "") + ".html")
    tables = _extract_tables(page.read_text(encoding="utf-8", errors="replace"))
    text = page_text(cik10, accession)
    entries, problems, industry, seen = [], [], "", {}
    for index in spec["tables"]:
        for row in tables[index]:
            filled = [i for i, c in enumerate(row) if c.strip()]
            issuer, instrument = _cell(row, spec["issuer"]), _cell(row, spec["instrument"])
            if filled == [spec["issuer"]] and not issuer.lower().startswith("debt investments"):
                industry = normalise(issuer)
                continue
            if not issuer or not instrument or issuer == "Issuer(F)":
                continue
            line = normalise(" ".join(c for c in row if c.strip()))
            entry = {"accession": accession, "quarter": quarter, "issuer": normalise(issuer),
                     "instrument": normalise(instrument),
                     "fair_value": _money(_cell(row, spec["fair_value"])),
                     "cost": _money(_cell(row, spec["cost"])),
                     "principal_amount": _money(_cell(row, spec["principal"]))}
            coupon = _percent(_cell(row, spec["coupon"]))
            if coupon is not None:
                entry["interest_rate"] = coupon
            spread = _percent(_cell(row, spec["spread"]))
            if spread is not None and not _cell(row, spec.get("spread_text")):
                entry["basis_spread"] = spread
            reference = normalise(_cell(row, spec["reference"])).split("(")[0].strip().upper()
            if re.fullmatch(r"[A-Z]{2,12}", reference) and reference != "FIXED":
                entry["reference_rate_type"] = reference
            maturity = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", _cell(row, spec["maturity"]))
            if maturity:
                entry["maturity_date"] = "%s-%02d-%02d" % (maturity.group(3), int(maturity.group(1)), int(maturity.group(2)))
            if industry:
                entry["industry"] = industry
            key = (entry["issuer"].lower(), entry["instrument"].lower())
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                entry["occurrence"] = seen[key]
            entry["printed_line"] = line
            errors = entry_errors(entry)
            if line not in text:
                errors.append("line not found in the page text")
            if errors:
                problems.append((line, errors))
            entries.append(entry)
    cost = sum(e["cost"] for e in entries)
    fair_value = sum(e["fair_value"] for e in entries)
    print("rows %d  cost %s  fair value %s" % (len(entries), "{:,}".format(cost), "{:,}".format(fair_value)))
    for line, errors in problems:
        print("REFUSED:", line, errors)
    totals = spec.get("totals", {})
    tied = cost == totals.get("cost") and fair_value == totals.get("fair_value")
    print("printed totals cost %s fair value %s: %s" % ("{:,}".format(totals.get("cost", 0)),
                                                       "{:,}".format(totals.get("fair_value", 0)),
                                                       "TIE" if tied else "DO NOT TIE"))
    if problems or not tied:
        raise SystemExit(1)
    Path(out_path).write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print("wrote", out_path)


if __name__ == "__main__":
    main(*sys.argv[1:6])
