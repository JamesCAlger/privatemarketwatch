r"""Print the warn_if / error_if / severity dbt recorded for tests whose name contains a substring. Diagnostic only.

Usage (from the repository root):
  warehouse\.venv\Scripts\python.exe warehouse\scripts\slice4\show_test_config.py <substring>

Reads warehouse/target/manifest.json (written by the last dbt command). Prints at most 50 tests.
"""
import json
import os
import sys

needle = sys.argv[1]
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "target", "manifest.json")
with open(path, encoding="utf-8") as f:
    nodes = json.load(f)["nodes"]
shown = 0
for key, node in sorted(nodes.items()):
    if node.get("resource_type") != "test" or needle not in node.get("name", ""):
        continue
    cfg = node.get("config", {})
    print(node["name"], "| severity", cfg.get("severity"), "| warn_if", cfg.get("warn_if"), "| error_if", cfg.get("error_if"))
    shown += 1
    if shown >= 50:
        break
print("-- tests shown:", shown)
