"""Classify the 2026-11-19 blind items through the API, one call per item, and record the tokens billed.

Usage: python run_api.py <blind_dir> <out_dir> <env_file> [--limit N]
  blind_dir holds fwd/ and rev/ (blind_header.json, blind_heading.json, blind_rate.json).
Writes <out_dir>/answers/<model>_<order>.json and <out_dir>/usage.csv. Prints progress. ASCII output only.
One request per item (the production shape: one bundle, one call). Same effort for both models.
"""
import concurrent.futures as cf
import csv
import json
import re
import sys
import time
from pathlib import Path

import anthropic

MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}
EFFORT = "low"
MAX_TOKENS = 2000
WORKERS = 6

blind, out, env_file = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

key = None
for line in env_file.read_text(encoding="utf-8").splitlines():
    if line.startswith("ANTHROPIC_API_KEY="):
        key = line.split("=", 1)[1].strip().strip('"').strip("'")
if not key:
    sys.exit("no ANTHROPIC_API_KEY in env file")
client = anthropic.Anthropic(api_key=key, max_retries=4, timeout=120.0)


def build(order):
    jobs = []
    for kind in ("rate", "header", "heading"):
        d = json.loads((blind / order / f"blind_{kind}.json").read_text(encoding="utf-8"))
        opts = "\n".join(f"- {k}: {v}" for k, v in d["options"].items())
        system = (d["instructions"] + "\n\nAllowed answers (choose exactly one key):\n" + opts
                  + '\n\nReply with one JSON object and nothing else: {"answer": "<key>", "confidence": <0 to 1>}')
        items = d["items"][:limit] if limit else d["items"]
        for it in items:
            state = dict(it["state"])
            for k, v in list(state.items()):
                if isinstance(v, dict) and "see_shared" in v:
                    state[k] = d["shared"][v["see_shared"]]
            jobs.append((kind, it["item_id"], system, json.dumps(state, ensure_ascii=False), set(d["options"])))
    return jobs


def call(model_id, job):
    kind, item_id, system, user, keys = job
    t0 = time.time()
    try:
        r = client.messages.create(model=model_id, max_tokens=MAX_TOKENS, system=system,
                                   output_config={"effort": EFFORT},
                                   messages=[{"role": "user", "content": user}])
    except anthropic.APIStatusError as e:
        return {"item_id": item_id, "kind": kind, "answer": "api_error", "confidence": 0, "note": str(e.status_code),
                "in": 0, "out": 0, "cr": 0, "cw": 0, "secs": time.time() - t0, "stop": "error"}
    except anthropic.APIConnectionError:
        return {"item_id": item_id, "kind": kind, "answer": "api_error", "confidence": 0, "note": "connection",
                "in": 0, "out": 0, "cr": 0, "cw": 0, "secs": time.time() - t0, "stop": "error"}
    text = "".join(b.text for b in r.content if b.type == "text")
    ans, conf = "unparsed", 0.0
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            o = json.loads(m.group(0))
            ans, conf = str(o.get("answer")), float(o.get("confidence", 0))
        except (ValueError, TypeError):
            pass
    if ans not in keys and ans != "unparsed":
        ans = "invalid:" + ans[:30]
    u = r.usage
    return {"item_id": item_id, "kind": kind, "answer": ans, "confidence": conf, "note": "",
            "in": u.input_tokens, "out": u.output_tokens, "cr": u.cache_read_input_tokens or 0,
            "cw": u.cache_creation_input_tokens or 0, "secs": time.time() - t0, "stop": r.stop_reason}


(out / "answers").mkdir(parents=True, exist_ok=True)
rows = []
for name, model_id in MODELS.items():
    for order in ("fwd", "rev"):
        jobs = build(order)
        t0 = time.time()
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            res = []
            for i, r in enumerate(ex.map(lambda j: call(model_id, j), jobs), 1):
                res.append(r)
                if i % 40 == 0 or i == len(jobs):
                    print(f"{name} {order}: {i}/{len(jobs)} done, {time.time() - t0:.0f}s", flush=True)
        (out / "answers" / f"{name}_{order}.json").write_text(
            json.dumps([{k: r[k] for k in ("item_id", "kind", "answer", "confidence", "note")} for r in res], indent=0),
            encoding="utf-8")
        for r in res:
            rows.append({"model": name, "order": order, **r})
        bad = sum(r["answer"] in ("api_error", "unparsed") or r["answer"].startswith("invalid") for r in res)
        print(f"{name} {order}: input {sum(r['in'] for r in res)} output {sum(r['out'] for r in res)} "
              f"bad {bad} stops {sorted(set(r['stop'] for r in res))} wall {time.time() - t0:.0f}s", flush=True)
with open(out / "usage.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print("wrote", len(rows), "rows")
