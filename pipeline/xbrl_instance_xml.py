"""Shared lxml parse of a cached XBRL instance document.

libxml2's default parser refuses a text node over 10 MB ("xmlSAX2Characters: huge
text node") and trees deeper than 256 levels. Some 10-K instances embed whole
narrative sections (risk factors as escaped XHTML) in one text block, so the
default parser fails on them and the caller sees an empty or missing filing
(MidCap Apollo Institutional 0001193125-26-104070, 43.9 MB, 2026-10-19).

``huge_tree=True`` only lifts those size limits; every other parser option is
lxml's default, so a file the default parser accepts parses to the same tree.

Used by the verification side (provenance re-verifier, source reconciliation) and,
since 2026-10-19 (D-213), by the extraction stages (fund income, highlights, sector
breakdown, position PIK, derivatives, html bridge, printed sections). Cohort
measurement before that switch: of 301 cached instances over 10 MB in 40 funds, only
MidCap Apollo Institutional's 2025-12-31 10-K failed the default parser.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union

from lxml import etree


def instance_parser() -> etree.XMLParser:
    """A parser identical to lxml's default except that the size limits are lifted."""
    return etree.XMLParser(huge_tree=True)


def parse_instance(path: Union[str, Path]) -> etree._ElementTree:
    """Parse an XBRL instance file; raises like ``etree.parse`` on malformed XML."""
    return etree.parse(str(path), instance_parser())
