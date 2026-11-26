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
# 5: wrapper hashes (wrapper_drift.copied/current_sha256, manifest wrapper_copy_sha256) are text hashes, CRLF read as
# LF (store.text_sha256; slice 4 Task 5). Tables other than wrapper_drift and rule ids are unchanged.
# 6: slice 5 Task 2. The two agent stores production applies (data/overrides/agent_b2_corrections and
# agent_investigate_rules, readings_loader/agent_stores.py): value entries become correction rows (kind value, keyed by
# a production row_id; kind add_row, one row per field of an added position), row-selecting rules become rows of the
# new table correction_rule (recorded, not applied). Correction rows gain row_id, add_group_id and source_file, so every
# correction_id changes (the id hashes every column). The manifest gains agent_store_sha256 (text hash of every file
# of a scope fund in the two stores, loaded or skipped) and agent_store_skipped (why a file was not loaded).
# 7: slice 5 Task 4. source_encodings.rate_only_contexts 'adopt_adjacent' is a rule row (rule_class convention, target
# interest_rate, action adopt_adjacent_rate_context) instead of a not_loaded row. Other rows and ids are unchanged.
LOADER_VERSION = "7"

RULE_COLUMNS = [
    "rule_id", "cik", "valid_from", "valid_to", "validity_basis", "sel_accession", "sel_axis",
    "sel_member", "sel_label", "sel_label_pattern", "sel_feature", "sel_concept_namespace", "sel_concept_local",
    "target", "action",
    "parameter", "evidence", "origin", "rule_class", "priority",
]
CORRECTION_COLUMNS = [
    "correction_id", "cik", "report_date", "accession", "context_id", "identifier", "field",
    "value", "value_unit", "expected_value", "kind", "store", "reason", "evidence", "author", "date_added",
    # loader version 6: row_id keys an agent correction to a production holdings row (resolved in slice 5 Task 3);
    # add_group_id groups the add_row corrections of one added position; source_file is the store file, relative to
    # the store (row_corrections.csv, wrappers/<cik>.json, agent_b2_corrections/<dir>/<file>.json, ...).
    "row_id", "add_group_id", "source_file",
]
# A row-selecting rule of an agent store, loaded for the record; no model applies it (slice 5 decision 1).
# predicate_form: sql (production's predicate_sql, written in production's column names) or template (a B2 leaf's
# template, as JSON).
CORRECTION_RULE_COLUMNS = [
    "rule_row_id", "cik", "store", "rule_id", "rule_type", "action", "scope_quarters", "predicate", "predicate_form",
    "evidence", "reason", "source_file",
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
