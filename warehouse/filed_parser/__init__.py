"""Filed layer parser: each cached SEC filing parsed once into Parquet tables.

See warehouse/docs/filed_layer.md. Every table row starts with the dashed accession.
"""
import re

PARSER_VERSION = "3"


def dashed_accession(stem):
    """'000119312526215667' -> '0001193125-26-215667'. Anything else is returned unchanged."""
    if re.fullmatch(r"\d{18}", stem):
        return f"{stem[:10]}-{stem[10:12]}-{stem[12:]}"
    return stem
