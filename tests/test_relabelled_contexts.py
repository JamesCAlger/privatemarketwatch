"""Wrapper opt-in source_encodings.relabelled_contexts: a context whose identifier member names another line than
the printed row carrying its facts is renamed to the printed identifier (Blue Owl Credit Income, 10-Q for
2026-03-31, unfunded-commitment table shifted against its members; nboc run, 2026-11-11)."""
import json
import tempfile
from pathlib import Path

import pytest

from pipeline import page_labelled_contexts as plc

ACC = "0001812554-26-000027"
MEMBER = "Activate Holdings (US) Corp. (dba Absolute Software) | First lien senior secured revolving loan"
PRINTED = "AI Titan Parent, Inc. (dba Prometheus Group) | First lien senior secured revolving loan"


def _listed(monkeypatch):
    monkeypatch.setattr(plc, "_relabelled_by_accession", lambda: {("0001812554", ACC): {"c-806": (MEMBER, PRINTED)}})
    return {"cik": "1812554", "accession_number": ACC}


def test_renames_a_context_carrying_the_listed_member(monkeypatch):
    meta = _listed(monkeypatch)
    contexts = {"c-806": {"is_investment": True, "investment_identifier": MEMBER},
                "c-807": {"is_investment": True, "investment_identifier": "Aerosmith Bidco 1 Limited | First lien senior secured revolving loan"}}
    assert plc.relabel_declared_contexts(contexts, meta) == 1
    assert contexts["c-806"]["investment_identifier"] == PRINTED
    # a context the wrapper does not list keeps its member
    assert contexts["c-807"]["investment_identifier"].startswith("Aerosmith")


def test_leaves_a_context_whose_member_is_not_the_listed_one(monkeypatch):
    # false positive guard: a refiled or re-read filing whose member differs must not be renamed
    meta = _listed(monkeypatch)
    contexts = {"c-806": {"is_investment": True, "investment_identifier": PRINTED}}
    assert plc.relabel_declared_contexts(contexts, meta) == 0
    assert contexts["c-806"]["investment_identifier"] == PRINTED
    unnamed = {"c-806": {"is_investment": False}}
    assert plc.relabel_declared_contexts(unnamed, meta) == 0
    assert "investment_identifier" not in unnamed["c-806"]


def test_other_funds_and_filings_are_untouched(monkeypatch):
    _listed(monkeypatch)
    contexts = {"c-806": {"is_investment": True, "investment_identifier": MEMBER}}
    assert plc.relabel_declared_contexts(contexts, {"cik": "1803498", "accession_number": ACC}) == 0
    assert plc.relabel_declared_contexts(contexts, {"cik": "1812554", "accession_number": "0001812554-26-000047"}) == 0
    assert contexts["c-806"]["investment_identifier"] == MEMBER


def _load(entries):
    from pipeline.source_encodings import load_encodings
    with tempfile.TemporaryDirectory() as folder:
        wrapper = {"schema_version": "bdc-xbrl-wrapper.v3", "cik": "0001812554",
                   "source_encodings": {"relabelled_contexts": entries}}
        (Path(folder) / "0001812554.json").write_text(json.dumps(wrapper), encoding="utf-8")
        return load_encodings(folder)


def test_loader_admits_the_three_part_form_and_parses_it():
    entry = "%s c-806 :: %s :: %s" % (ACC, MEMBER, PRINTED)
    assert _load([entry])["0001812554"]["relabelled_contexts"] == [entry]
    accession, context, member, printed = plc._RELABELLED_RE.fullmatch(entry).groups()
    assert (accession, context, member, printed) == (ACC, "c-806", MEMBER, PRINTED)


@pytest.mark.parametrize("entry", [
    "%s c-806 => %s" % (ACC, PRINTED),                      # context_identifiers form, no member to check
    "%s c-806 :: %s" % (ACC, PRINTED),                      # member missing
    "%s c-806 :: a :: b :: c" % ACC,                        # ambiguous split
    "c-806 :: %s :: %s" % (MEMBER, PRINTED),                # no accession
])
def test_loader_refuses_malformed_entries(entry):
    with pytest.raises(ValueError):
        _load([entry])
