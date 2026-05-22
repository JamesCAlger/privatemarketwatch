import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipeline.fund_strategy_group_review import cli_summarize_verdicts


if __name__ == "__main__":
    raise SystemExit(cli_summarize_verdicts())
