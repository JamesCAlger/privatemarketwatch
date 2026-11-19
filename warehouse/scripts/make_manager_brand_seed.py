"""Write warehouse/seeds/manager_brand.csv from CIK_TO_MANAGER_BRAND in pipeline/config.py.

Run with the machine's python from the repository root (it needs the pipeline package):

    python warehouse/scripts/make_manager_brand_seed.py

The mapping lives in Python; dbt reads tables. Until the website export reads this file too, the
two copies can drift: rerun this after any change to the mapping.
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pipeline.config import CIK_TO_MANAGER_BRAND  # noqa: E402

OUT = ROOT / "warehouse" / "seeds" / "manager_brand.csv"


def main() -> int:
    rows = sorted((str(cik).zfill(10), brand) for cik, brand in CIK_TO_MANAGER_BRAND.items())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["cik", "manager_brand"])
        writer.writerows(rows)
    print("wrote %d rows to %s" % (len(rows), OUT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
