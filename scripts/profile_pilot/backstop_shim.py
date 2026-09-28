"""Run the MAIN checkout's `scripts/diff_outputs.py --semantic`, read-only.

Invoked by the launcher with cwd = main_repo_root. The existing script is loaded
unmodified from the main checkout (its ROOT therefore resolves to main); the only
change is that SEMANTIC_REPORT_FILE, which it would otherwise write into
data/output/, is redirected into the pilot run's verification directory. A write
guard over the main protected roots turns any other write into a crash, which the
launcher records as a failed inspection.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import sys

import protection  # sibling module; stdlib-only at import


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    sys.stdout.reconfigure(encoding="ascii", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="ascii", errors="backslashreplace")
    main_root = Path.cwd().resolve()
    roots = [main_root / "data" / "output", main_root / "frontend" / "public" / "data"]
    # Passed via the environment so no path lands in this process's command line.
    report = Path(os.environ["PROFILE_PILOT_BACKSTOP_REPORT"]).resolve()
    if protection.is_under(report, roots) or not report.is_relative_to(main_root):
        print("backstop shim: report must be under the main root and outside protected roots")
        return 2
    protection.install_open_guard(roots)
    script = main_root / "scripts" / "diff_outputs.py"
    spec = importlib.util.spec_from_file_location("pilot_main_diff_outputs", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(module.ROOT).resolve() != main_root:
        print("backstop shim: diff_outputs ROOT is not the main root")
        return 2
    module.SEMANTIC_REPORT_FILE = report
    print("backstop shim: python scripts/diff_outputs.py --semantic (report redirected to "
          + str(report) + ", pid " + str(os.getpid()) + ")", flush=True)
    return module.diff(compare_sql=True, semantic=True)


if __name__ == "__main__":
    raise SystemExit(main())
