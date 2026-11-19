"""Readings loader: wrapper declarations and row-level fixes flattened into tables dbt reads.

See warehouse/docs/intermediate_spine.md (section 5) and 2026-11-19-slice1-readings-loader-plan.md.
The wrappers read are the new pipeline's own copies, warehouse/wrappers/<cik>.json (owner decision 2026-11-19);
production's wrappers are only hashed, for the drift table. New-style fund rules (Task 5 of slice 2) are the
copy's top-level `reading_rules` list.
The loader copies what the stores say. It does not decide or change any value.
"""
import hashlib

# 2: rule rows gain sel_concept_namespace and sel_concept_local (new-style fund rules, `reading_rules`). Every
# rule_id changes with the column list, since the id hashes every column.
# 3: rule rows gain sel_label_pattern (fund rule position_without_term_fact, slice 2 Task 6). Every rule_id changes again.
# 4: the manifest gains wrapper_copy_sha256 (fund -> SHA-256 of the copy read), checked by dbt at build time (final
# fix wave F1). Tables and rule ids are unchanged.
LOADER_VERSION = "4"

RULE_COLUMNS = [
    "rule_id", "cik", "valid_from", "valid_to", "validity_basis", "sel_accession", "sel_axis",
    "sel_member", "sel_label", "sel_label_pattern", "sel_feature", "sel_concept_namespace", "sel_concept_local",
    "target", "action",
    "parameter", "evidence", "origin", "rule_class", "priority",
]
CORRECTION_COLUMNS = [
    "correction_id", "cik", "report_date", "accession", "context_id", "identifier", "field",
    "value", "value_unit", "expected_value", "kind", "store", "reason", "evidence", "author", "date_added",
]
NOT_LOADED_COLUMNS = ["cik", "wrapper_key", "entry", "reason"]
# A fund rule's own label fixtures (reading_rules label_examples_match / label_examples_no_match; slice 2 Task 6).
LABEL_EXAMPLE_COLUMNS = ["rule_id", "cik", "label", "expected_match"]
# Production wrapper against the copy the new pipeline reads: SHA-256 when copied, now, and whether it changed.
WRAPPER_DRIFT_COLUMNS = ["cik", "copied_sha256", "current_sha256", "changed"]


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
