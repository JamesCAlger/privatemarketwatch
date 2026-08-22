"""One-time migration: restamp correction-leaf row_selector row_id values
from legacy natural-key hashes to anchor-based ids (2026-08-22 row_id swap).

Reads the published unified holdings (which already carries the NEW
anchor-based row_id), recomputes what each row's LEGACY id was (md5 of
compute_natural_keys), and rewrites any leaf whose row_selector cites a
legacy id. Fail-loud: ambiguous legacy ids (one legacy id -> multiple new
ids) and unknown ids are reported and exit non-zero; they are never guessed.

Usage:
    python scripts/restamp_row_selectors.py            # dry run (default)
    python scripts/restamp_row_selectors.py --apply    # rewrite leaf files
"""

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
logger = logging.getLogger("restamp")

_BOM = b"\xef\xbb\xbf"


def _legacy_hash(key: str) -> str:
    return "ROW-" + hashlib.md5(key.encode()).hexdigest()[:16]


def build_id_map(frame: pd.DataFrame) -> tuple[dict, list]:
    """Map legacy natural-key row_id -> current published row_id.

    Returns (id_map, ambiguous) where ambiguous lists legacy ids that map to
    more than one distinct current id (refused, never guessed).
    """
    from pipeline.position_id_registry import compute_natural_keys

    legacy = compute_natural_keys(frame).map(_legacy_hash)
    current = frame["row_id"].fillna("").astype(str)
    pairs = pd.DataFrame({"legacy": legacy.values, "current": current.values})
    grouped = pairs.groupby("legacy")["current"].nunique()
    ambiguous = sorted(grouped[grouped > 1].index)
    ok = pairs[~pairs["legacy"].isin(ambiguous)].drop_duplicates("legacy")
    id_map = dict(zip(ok["legacy"], ok["current"]))
    # identity mappings are noise: natural_key-basis rows map to themselves
    return {k: v for k, v in id_map.items() if k != v}, ambiguous


def _iter_selectors(leaf: dict):
    sel = (leaf.get("template") or {}).get("row_selector")
    if isinstance(sel, dict):
        yield sel
    elif isinstance(sel, list):
        for s in sel:
            if isinstance(s, dict):
                yield s


def restamp_leaves(corrections_dir: Path, id_map: dict,
                   current_ids: set, apply: bool) -> tuple[int, list]:
    """Rewrite legacy row_id selector values. Returns (n_changed, unresolved)."""
    changed = 0
    unresolved: list[tuple[str, str]] = []
    for leaf_path in sorted(Path(corrections_dir).glob("*/*.json")):
        if leaf_path.parent.name.startswith("_"):
            continue
        raw = leaf_path.read_bytes()
        had_bom = raw.startswith(_BOM)
        try:
            leaf = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            logger.warning("skipping unreadable leaf %s: %s", leaf_path, exc)
            continue
        touched = False
        for sel in _iter_selectors(leaf):
            rid = str(sel.get("row_id") or "").strip()
            if not rid:
                continue
            if rid in current_ids:
                logger.info("current id, no change: %s (%s)",
                            rid, leaf_path.name)
                continue
            if rid in id_map:
                logger.info("restamp %s: %s -> %s",
                            leaf_path.relative_to(corrections_dir),
                            rid, id_map[rid])
                sel["row_id"] = id_map[rid]
                touched = True
            else:
                unresolved.append((str(leaf_path), rid))
        if touched:
            changed += 1
            if apply:
                out = json.dumps(leaf, indent=2, ensure_ascii=False).encode("utf-8")
                leaf_path.write_bytes((_BOM + out) if had_bom else out)
    return changed, unresolved


def main() -> int:
    from pipeline import config

    ap = argparse.ArgumentParser(
        description="Restamp correction-leaf row_id selectors after the "
                    "anchor-based row_id migration")
    ap.add_argument("--apply", action="store_true",
                    help="Rewrite leaf files (default: dry run)")
    ap.add_argument("--holdings", type=Path, default=None,
                    help="Unified holdings CSV/parquet (default: published)")
    ap.add_argument("--corrections-dir", type=Path,
                    default=config.AGENT_B2_CORRECTIONS_DIR)
    args = ap.parse_args()

    holdings = args.holdings
    if holdings is None:
        pq = config.UNIFIED_HOLDINGS_FILE.with_suffix(".parquet")
        holdings = pq if pq.exists() else config.UNIFIED_HOLDINGS_FILE
    logger.info("loading holdings: %s", holdings)
    if str(holdings).endswith(".parquet"):
        frame = pd.read_parquet(holdings)
    else:
        frame = pd.read_csv(holdings, dtype=str)
    if "row_id" not in frame.columns:
        logger.error("holdings frame has no row_id column -- rebuild first")
        return 1

    id_map, ambiguous = build_id_map(frame)
    logger.info("id map: %d legacy->new entries, %d ambiguous legacy ids",
                len(id_map), len(ambiguous))

    changed, unresolved = restamp_leaves(
        args.corrections_dir, id_map,
        current_ids=set(frame["row_id"].fillna("").astype(str)),
        apply=args.apply)
    mode = "applied" if args.apply else "dry-run"
    logger.info("%s: %d leaf file(s) with restamped selectors", mode, changed)
    for path, rid in unresolved:
        logger.error("UNRESOLVED row_id %s in %s", rid, path)
    return 1 if unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
