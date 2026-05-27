import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.position_match_review import cli_build_worklist


if __name__ == "__main__":
    raise SystemExit(cli_build_worklist())
