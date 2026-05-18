import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.validation_rules.diagnostics import cli_build_review_bundle


if __name__ == "__main__":
    raise SystemExit(cli_build_review_bundle())
