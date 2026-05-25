import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.bdc_cik_review import cli_build_prompt


if __name__ == "__main__":
    raise SystemExit(cli_build_prompt())
