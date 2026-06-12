"""Tests for pipeline.utils.hungarian_assignment.

Covers:
- 1x1, 2x2, 3x3 square matrices with known optimal
- Rectangular 3x2 and 2x3 matrices
- All-equal costs (any assignment is optimal)
- Sentinel / infinity handling
- Cross-check against brute-force for small matrices
"""

import itertools

import pytest

from pipeline.utils import hungarian_assignment


class TestHungarianAssignment:
    def test_1x1(self):
        """Trivial 1x1 matrix."""
        row_ind, col_ind = hungarian_assignment([[5.0]])
        assert row_ind == [0]
        assert col_ind == [0]

    def test_2x2_simple(self):
        """2x2 with clear optimal: (0,1) + (1,0) = 1+1 = 2 vs (0,0) + (1,1) = 4+4 = 8."""
        cost = [
            [4.0, 1.0],
            [1.0, 4.0],
        ]
        row_ind, col_ind = hungarian_assignment(cost)
        assert len(row_ind) == 2
        total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))
        assert total == 2.0

    def test_3x3_known_optimal(self):
        """3x3 matrix with known optimal assignment.

        Cost matrix:
          [[9, 2, 7],
           [6, 4, 3],
           [5, 8, 1]]
        Optimal: (0,1)=2 + (1,0)=6 + (2,2)=1 = 9
        """
        cost = [
            [9.0, 2.0, 7.0],
            [6.0, 4.0, 3.0],
            [5.0, 8.0, 1.0],
        ]
        row_ind, col_ind = hungarian_assignment(cost)
        assert len(row_ind) == 3
        total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))
        assert total == 9.0

    def test_rectangular_3x2(self):
        """3 rows, 2 cols: only 2 pairs returned."""
        cost = [
            [10.0, 5.0],
            [3.0, 8.0],
            [7.0, 2.0],
        ]
        row_ind, col_ind = hungarian_assignment(cost)
        assert len(row_ind) == 2
        # Optimal: (1,0)=3 + (2,1)=2 = 5
        total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))
        assert total == 5.0

    def test_rectangular_2x3(self):
        """2 rows, 3 cols: only 2 pairs returned."""
        cost = [
            [10.0, 3.0, 7.0],
            [5.0, 8.0, 2.0],
        ]
        row_ind, col_ind = hungarian_assignment(cost)
        assert len(row_ind) == 2
        # Optimal: (0,1)=3 + (1,2)=2 = 5
        total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))
        assert total == 5.0

    def test_all_equal_costs(self):
        """All-equal costs: any assignment is optimal."""
        cost = [
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0],
        ]
        row_ind, col_ind = hungarian_assignment(cost)
        assert len(row_ind) == 3
        # All assignments have the same cost
        total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))
        assert total == 3.0
        # Each row and col used exactly once
        assert sorted(row_ind) == [0, 1, 2]
        assert sorted(col_ind) == [0, 1, 2]

    def test_sentinel_infinity(self):
        """Large costs act as forbidden assignments."""
        INF = 1e15
        cost = [
            [1.0, INF],
            [INF, 2.0],
        ]
        row_ind, col_ind = hungarian_assignment(cost)
        assert len(row_ind) == 2
        total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))
        assert total == 3.0  # (0,0)=1 + (1,1)=2

    def test_brute_force_cross_check(self):
        """Cross-check against brute-force for random-ish 4x4 matrices."""
        matrices = [
            [
                [7, 3, 5, 9],
                [8, 2, 6, 4],
                [1, 9, 3, 7],
                [4, 6, 8, 2],
            ],
            [
                [12, 7, 9, 3],
                [8, 15, 2, 6],
                [4, 1, 11, 8],
                [9, 5, 7, 14],
            ],
        ]
        for cost in matrices:
            row_ind, col_ind = hungarian_assignment(cost)
            hungarian_total = sum(cost[r][c] for r, c in zip(row_ind, col_ind))

            # Brute-force: try all permutations
            n = len(cost)
            best = float("inf")
            for perm in itertools.permutations(range(n)):
                total = sum(cost[i][perm[i]] for i in range(n))
                best = min(best, total)

            assert hungarian_total == best, (
                f"Hungarian gave {hungarian_total}, brute-force gave {best}"
            )

    def test_empty_matrix(self):
        """Empty matrix returns empty indices."""
        row_ind, col_ind = hungarian_assignment([])
        assert row_ind == []
        assert col_ind == []

    def test_empty_inner(self):
        """Matrix with empty rows returns empty indices."""
        row_ind, col_ind = hungarian_assignment([[]])
        assert row_ind == []
        assert col_ind == []
