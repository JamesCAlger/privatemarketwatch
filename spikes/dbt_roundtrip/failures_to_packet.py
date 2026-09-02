"""Convert dbt stored-failure rows into B1-style blocker packets.

The point of the spike: prove that a model-boundary test failure carries
enough provenance to become an adjudicable packet mechanically. Output
vocabulary deliberately mirrors source_only_detail.csv fields
(source_row_id, mechanism, is_blocking, recommended_action) plus the two
fields the incumbent CANNOT provide: boundary_model / downstream_fix_model.
"""
import json
import sys
from pathlib import Path

import duckdb

ART = Path(__file__).resolve().parent / "artifacts"
TABLE_LIKE = "%duplicate_dimension_paths%"


class NoFailuresTable(RuntimeError):
    pass


def build_packets(db_path: Path) -> list[dict]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        hit = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_name LIKE ? AND table_schema LIKE '%dbt_test__audit%'",
            [TABLE_LIKE]).fetchone()
        if hit is None:
            raise NoFailuresTable(
                f"no stored-failure table matching {TABLE_LIKE}; "
                "run: dbt test --store-failures")
        rows = con.execute(
            f'SELECT * FROM "{hit[0]}"."{hit[1]}" '
            "ORDER BY key_sig, source_row_id").fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()
    groups: dict[str, list[dict]] = {}
    for row in rows:
        rec = dict(zip(cols, row))
        groups.setdefault(rec["key_sig"], []).append(rec)
    packets = []
    for key_sig in sorted(groups):
        members = groups[key_sig]
        first = members[0]
        packets.append({
            "schema_version": "dbt-spike-packet.v0",
            "mechanism": "boundary_duplicate_dimension_path",
            "boundary_model": "stg_bdc_holdings",
            "downstream_fix_model": "bdc_dim_deduped",
            "cik": first["cik"],
            "entity_name": first["entity_name"],
            "accession_number": first["accession_number"],
            "report_date": str(first["report_date"]),
            "key_sig": key_sig,
            "group_size": len(members),
            "source_row_ids": [m["source_row_id"] for m in members],
            "fair_values": [m["fair_value"] for m in members],
            "is_blocking": True,
            "recommended_action": "dimension_path_dedup",
        })
    return packets


def main() -> int:
    packets = build_packets(ART / "spike.duckdb")
    out = ART / "packet.json"
    out.write_text(json.dumps(packets, indent=2, default=str),
                   encoding="utf-8")
    print(f"wrote {len(packets)} packets to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
