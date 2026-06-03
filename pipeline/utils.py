"""Shared utility classes and functions for the pipeline."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)


class UnionFind:
    """Disjoint-set / union-find data structure for entity clustering."""

    def __init__(self):
        self._parent = {}
        self._rank = {}

    def find(self, x):
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
            return x
        # Path compression
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return
        # Union by rank
        if self._rank[rx] < self._rank[ry]:
            rx, ry = ry, rx
        self._parent[ry] = rx
        if self._rank[rx] == self._rank[ry]:
            self._rank[rx] += 1

    def components(self):
        """Return dict mapping root -> set of members."""
        comps = defaultdict(set)
        for x in self._parent:
            comps[self.find(x)].add(x)
        return dict(comps)


def write_parquet_companion(csv_file: Path) -> Path | None:
    """Write a Parquet copy alongside a CSV for faster DuckDB reads.

    Returns the Parquet path on success, None on failure.
    """
    import duckdb

    parquet_file = csv_file.with_suffix(".parquet")
    try:
        csv_path = str(csv_file).replace("\\", "/")
        pq_path = str(parquet_file).replace("\\", "/")
        con = duckdb.connect()
        con.execute(
            f"COPY (SELECT * FROM read_csv_auto('{csv_path}', "
            f"header=true, all_varchar=true)) "
            f"TO '{pq_path}' (FORMAT 'parquet')"
        )
        con.close()
        csv_mb = csv_file.stat().st_size / (1024 * 1024)
        pq_mb = parquet_file.stat().st_size / (1024 * 1024)
        logger.info(
            "Parquet companion: %s (%.1f MB -> %.1f MB)",
            parquet_file.name, csv_mb, pq_mb,
        )
        return parquet_file
    except Exception as exc:
        logger.warning("Failed to write Parquet companion %s: %s", parquet_file.name, exc)
        return None
