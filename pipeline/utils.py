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


def hungarian_assignment(
    cost_matrix: list[list[float]],
) -> tuple[list[int], list[int]]:
    """Solve the linear assignment problem using the Hungarian algorithm.

    Pure Python O(N^3) implementation for small matrices (entity groups
    are typically 2-8 positions, max ~15).  Handles rectangular matrices
    by padding with a sentinel cost.

    Parameters
    ----------
    cost_matrix : list[list[float]]
        n_rows x n_cols cost matrix.

    Returns
    -------
    (row_ind, col_ind) : tuple of lists
        Indices of optimal assignment.  Length = min(n_rows, n_cols).
        Same interface as scipy.optimize.linear_sum_assignment.
    """
    if not cost_matrix or not cost_matrix[0]:
        return ([], [])

    n_orig_rows = len(cost_matrix)
    n_orig_cols = len(cost_matrix[0])

    # Pad to square matrix
    n = max(n_orig_rows, n_orig_cols)
    SENTINEL = 1e15
    C = []
    for i in range(n):
        row = []
        for j in range(n):
            if i < n_orig_rows and j < n_orig_cols:
                row.append(float(cost_matrix[i][j]))
            else:
                row.append(SENTINEL)
        C.append(row)

    # Hungarian algorithm (Kuhn-Munkres) using potential method
    # u[i] = potential for row i, v[j] = potential for col j
    # p[j] = row assigned to col j (0 = unassigned, 1-indexed internally)
    INF = float("inf")
    u = [0.0] * (n + 1)
    v = [0.0] * (n + 1)
    p = [0] * (n + 1)      # p[j] = row assigned to col j (1-indexed)
    way = [0] * (n + 1)    # way[j] = previous col in alternating path

    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)

        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = C[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break

        while j0:
            p[j0] = p[way[j0]]
            j0 = way[j0]

    # Extract assignment, filtering out padded rows/cols
    row_ind = []
    col_ind = []
    for j in range(1, n + 1):
        i = p[j] - 1  # back to 0-indexed
        if i < n_orig_rows and (j - 1) < n_orig_cols:
            row_ind.append(i)
            col_ind.append(j - 1)

    # Sort by row index for deterministic output
    pairs = sorted(zip(row_ind, col_ind))
    if pairs:
        row_ind, col_ind = zip(*pairs)
        return list(row_ind), list(col_ind)
    return ([], [])


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
