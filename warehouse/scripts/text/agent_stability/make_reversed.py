"""Write a copy of each blind file with the answer options in reversed order. Usage: python make_reversed.py <dir>"""
import json
import sys
from pathlib import Path

base = Path(sys.argv[1])
for kind in ("header", "heading", "rate"):
    d = json.loads((base / "fwd" / f"blind_{kind}.json").read_text(encoding="utf-8"))
    d["options"] = dict(reversed(list(d["options"].items())))
    (base / "rev" / f"blind_{kind}.json").write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    print(kind, len(d["items"]), "items", list(d["options"])[:3])
