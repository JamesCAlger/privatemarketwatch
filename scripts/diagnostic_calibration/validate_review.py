import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.validation_rules.diagnostics import cli_validate_review


if __name__ == "__main__":
    raise SystemExit(cli_validate_review())
