"""Readings loader: wrapper declarations and row-level fixes flattened into tables dbt reads.

See warehouse/docs/intermediate_spine.md (section 5) and 2026-11-19-slice1-readings-loader-plan.md.
The loader copies what the stores say. It does not decide or change any value.
"""
import hashlib

LOADER_VERSION = "1"

RULE_COLUMNS = [
    "rule_id", "cik", "valid_from", "valid_to", "validity_basis", "sel_accession", "sel_axis",
    "sel_member", "sel_label", "sel_feature", "target", "action", "parameter", "evidence",
    "origin", "rule_class", "priority",
]
CORRECTION_COLUMNS = [
    "correction_id", "cik", "report_date", "accession", "context_id", "identifier", "field",
    "value", "value_unit", "expected_value", "kind", "store", "reason", "evidence", "author", "date_added",
]
NOT_LOADED_COLUMNS = ["cik", "wrapper_key", "entry", "reason"]


class LoadError(Exception):
    """A store holds something the loader does not understand. Nothing is skipped silently."""


def content_id(row, columns, id_column):
    """First 16 hex characters of the SHA-256 of every column except the id, in column order."""
    h = hashlib.sha256()
    for c in columns:
        if c == id_column:
            continue
        h.update(str(row[c]).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:16]
