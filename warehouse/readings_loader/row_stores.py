"""The two row-correction CSV stores as correction rows, for the scope funds only."""
import csv
from pathlib import Path

from . import CORRECTION_COLUMNS, LoadError, content_id

REQUIRED = ["cik", "report_date", "accession_number", "bdc_investment_identifier", "field", "value",
            "reason", "source_evidence", "author", "date_added"]


def read_row_corrections(path, store, ciks):
    """Correction rows of one CSV. `store` names it; `ciks` are 10-digit. Other funds are left out."""
    wanted = set(ciks)
    out = []
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise LoadError(f"{store}: missing column(s) {', '.join(missing)}")
        for line, raw in enumerate(reader, start=2):
            cik = (raw["cik"] or "").strip().zfill(10)
            if cik not in wanted:
                continue
            field = (raw["field"] or "").strip()
            accession = (raw["accession_number"] or "").strip()
            if not field or not accession:
                raise LoadError(f"{store} line {line}: empty field or accession")
            row = {c: "" for c in CORRECTION_COLUMNS}
            row.update(
                cik=cik, report_date=(raw["report_date"] or "").strip(), accession=accession,
                context_id=(raw.get("src_context_id") or "").strip(),
                identifier=(raw["bdc_investment_identifier"] or "").strip(), field=field,
                value=(raw["value"] or "").strip(), kind="value", store=store,
                reason=raw["reason"] or "", evidence=raw["source_evidence"] or "",
                author=(raw["author"] or "").strip(), date_added=(raw["date_added"] or "").strip(),
                source_file=Path(path).name)
            row["correction_id"] = content_id(row, CORRECTION_COLUMNS, "correction_id")
            out.append(row)
    return out
