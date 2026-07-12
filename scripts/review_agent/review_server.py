"""Local blind gold-review server for the B trial (Flask).

Serves a stratified subset (default 8 bundles/rule = 24) of the 45-bundle sample
for human labeling in the browser. Per bundle it shows the blinded claim and
pre-rendered raw-source evidence (overview + totals), lets you roam/grid the cached
filing interactively, and saves your verdict. The agent's verdict is NEVER shown
(blind labeling -> preserves e_FP/e_FN validity).

Writes one label per bundle to gold/labels/<review_id>.json and merges to
gold/gold_labels.csv on save. Cache-only, read-only on production.

Usage:
    python scripts/review_agent/review_server.py            # 8/rule on :5058
    python scripts/review_agent/review_server.py --per 12 --port 5060
Then open http://127.0.0.1:5058
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, request

REPO = Path(__file__).resolve().parents[2]
TRIAL = REPO / "data/output/shadow/trial_2026-06-18"
BUNDLES = TRIAL / "sample/review_bundles"
MANIFEST = TRIAL / "sample/sample_manifest.csv"
GOLD = TRIAL / "gold"
LABELS = GOLD / "labels"
CLI = REPO / "scripts/review_agent/evidence_cli.py"

ASSERTED = {
    "fv_conservation": "Sum of position fair values does NOT reconcile to the independent fund-level total investments at fair value.",
    "pik_le_interest_rate": "A position has a PIK rate GREATER than its total interest rate (PIK should be <= interest).",
    "C113": "A position has an interest_rate OUTSIDE the plausible range 0-25%.",
}
MECHS = {
    "fv_conservation": ["extraction_gap", "subtotal_leak", "comparative_leak", "dimension_double_count", "anchor_bad", "genuine_value_defect", "unknown"],
    "pik_le_interest_rate": ["false_alarm_cash_leg", "genuine_value_defect", "unit_scale", "rate_scale", "extraction_gap", "unknown"],
    "C113": ["false_alarm_rule_range", "rate_scale", "genuine_value_defect", "unknown"],
}


def _select(per: int) -> list[dict]:
    rows = list(csv.DictReader(open(MANIFEST)))
    out: list[dict] = []
    for rule in ("C113", "pik_le_interest_rate", "fv_conservation"):
        rule_rows = [r for r in rows if r["rule_name"] == rule]
        if rule == "fv_conservation":
            picked, seen = [], set()
            for b in ("small", "mid", "big"):
                for r in rule_rows:
                    if r["bucket"] == b and r["review_id"] not in seen:
                        picked.append(r); seen.add(r["review_id"])
                        if len([p for p in picked if p["bucket"] == b]) >= max(1, per // 3):
                            break
            for r in rule_rows:
                if len(picked) >= per:
                    break
                if r["review_id"] not in seen:
                    picked.append(r); seen.add(r["review_id"])
            out += picked[:per]
        else:
            out += rule_rows[:per]
    return out


def _cli(rid: str, *cmd: str) -> dict:
    bp = f"data/output/shadow/trial_2026-06-18/sample/review_bundles/{rid}.json"
    try:
        r = subprocess.run([sys.executable, str(CLI), "--bundle", bp, *cmd],
                           capture_output=True, text=True, cwd=str(REPO), timeout=180)
        return json.loads(r.stdout) if r.stdout.strip() else {"error": r.stderr[-500:]}
    except Exception as exc:
        return {"error": str(exc)}


def _label(rid: str) -> dict | None:
    p = LABELS / f"{rid}.json"
    return json.loads(p.read_text()) if p.exists() else None


def _esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _overview_html(ov: dict) -> str:
    if ov.get("status") or "error" in ov:
        return f'<p class=err>{_esc(ov)}</p>'
    rows = "".join(
        f'<tr><td>{t["table_index"]}</td><td>{t["n_rows"]}</td><td>{_esc(t["header"])}</td></tr>'
        for t in ov.get("soi_like_tables", [])
    )
    return (
        f'<p><b>{_esc(ov.get("entity_name"))}</b> &middot; {_esc(ov.get("form_type"))} '
        f'&middot; {_esc(ov.get("report_date"))} &middot; {ov.get("table_count")} tables '
        f'&middot; <small>{_esc(ov.get("accession"))}</small></p>'
        f'<table class=g><tr><th>table</th><th>rows</th><th>header</th></tr>{rows}</table>'
    )


def _lines_html(data: dict, key: str, hl: str = "") -> str:
    items = data.get(key, [])
    if not items:
        return '<p>(no rows)</p>'
    body = ""
    for m in items:
        txt = m.get("row_text", "")
        cls = " class=hl" if hl and hl.lower() in txt.lower() else ""
        body += f'<tr{cls}><td>{m["table_index"]}</td><td>{m["row_index"]}</td><td>{_esc(txt)}</td></tr>'
    meta = f'<p><small>{data.get("n_hits", "")} rows; scanned {data.get("rows_scanned", "")}{" (truncated)" if data.get("truncated") else ""}</small></p>'
    return meta + f'<table class=g><tr><th>tbl</th><th>row</th><th>text</th></tr>{body}</table>'


def _flagged_html(d: dict) -> str:
    if d.get("note"):
        return f'<p><small>{_esc(d["note"])} (use roam/grid + totals)</small></p>'
    rows = d.get("flagged_rows", [])
    if not rows:
        return '<p>(no flagged rows found in holdings)</p>'
    body = ""
    for r in rows:
        loc = r.get("filing_location")
        issuer = r.get("issuer_name") or r.get("bdc_investment_identifier") or ""
        locc = f'tbl {loc["table_index"]} / row {loc["row_index"]}' if loc else '<span class=err>not located</span>'
        txt = _esc(loc["row_text"]) if loc else f'<small>roam for: <b>{_esc(issuer)}</b></small>'
        body += (
            f'<tr><td>{_esc(issuer)}</td><td>{_esc(r.get("interest_rate"))}</td><td>{_esc(r.get("pik_rate"))}</td>'
            f'<td>{_esc(r.get("asset_class"))}</td><td>{locc}</td><td>{txt}</td></tr>'
        )
    return (
        f'<p><small><b>{d.get("n_flagged")}</b> position(s) tripped this rule '
        '&mdash; located in the filing below (verify the raw-source text):</small></p>'
        '<table class=g><tr><th>issuer</th><th>interest_rate</th><th>pik_rate</th><th>asset_class</th>'
        f'<th>filing loc</th><th>filing row (raw source)</th></tr>{body}</table>'
    )


def _claim_html(claim: dict, asserted: str) -> str:
    d = claim.get("discrepancy")
    disc = ""
    if d:
        disc = (
            '<table class=g><tr><th>value_sum (pipeline)</th><th>anchor_value</th>'
            '<th>residual %</th><th>status</th><th>anchor</th></tr>'
            f'<tr><td>{_esc(d.get("value_sum"))}</td><td>{_esc(d.get("anchor_value"))}</td>'
            f'<td>{_esc(d.get("residual_pct"))}</td><td>{_esc(d.get("status"))}</td>'
            f'<td>{_esc(d.get("anchor_used"))}</td></tr></table>'
        )
    return f'<p>{_esc(asserted)}</p>{disc}'


app = Flask(__name__)
SUBSET: list[dict] = []


PAGE = """<!doctype html><meta charset=utf-8><title>B gold review</title>
<style>body{{font:14px system-ui;margin:0;display:flex;height:100vh}}
#nav{{width:240px;overflow:auto;border-right:1px solid #ccc;padding:8px}}
#main{{flex:1;overflow:auto;padding:16px;max-width:900px}}
a{{display:block;padding:3px;text-decoration:none;color:#0366d6}}
.done{{color:#28a745}} pre{{background:#f6f8fa;padding:8px;overflow:auto;max-height:340px;white-space:pre-wrap}}
.claim{{background:#fff8e1;padding:10px;border:1px solid #ffe082;border-radius:4px}}
button{{cursor:pointer}} input,textarea,select{{font:13px system-ui}}
label.r{{margin-right:12px}}
table.g{{border-collapse:collapse;width:100%;margin:6px 0;font-size:12px}}
table.g th,table.g td{{border:1px solid #ddd;padding:3px 6px;text-align:left;vertical-align:top}}
table.g th{{background:#f0f3f6}} table.g td:first-child,table.g td:nth-child(2){{color:#888;white-space:nowrap;width:1%}}
.err{{color:#b00}} .hl td{{background:#e6ffed}} h4{{margin:14px 0 4px}}</style>
<div id=nav>{nav}</div><div id=main>{main}</div>"""


def _nav():
    items = []
    for r in SUBSET:
        rid = r["review_id"]
        cls = "done" if _label(rid) else ""
        items.append(f'<a class="{cls}" href="/review/{rid}">{"OK " if cls else ""}{r["rule_name"][:10]} {rid[-6:]}</a>')
    n_done = sum(1 for r in SUBSET if _label(r["review_id"]))
    return f'<b>{n_done}/{len(SUBSET)} labeled</b><a href="/export"><b>export CSV</b></a>' + "".join(items)


@app.route("/")
def index():
    return PAGE.format(nav=_nav(), main="<h2>B gold review</h2><p>Pick a bundle (left). Label BLIND - decide from the evidence below before anything else. The agent verdict is hidden by design.</p>")


@app.route("/review/<rid>")
def review(rid):
    r = next((x for x in SUBSET if x["review_id"] == rid), None)
    if not r:
        return "unknown", 404
    rule = r["rule_name"]
    claim = _cli(rid, "claim")
    flagged = _cli(rid, "flagged")
    overview = _cli(rid, "overview")
    totals = _cli(rid, "totals") if rule == "fv_conservation" else {"note": "run roam/grid as needed"}
    cur = _label(rid) or {}
    mech_opts = "".join(f'<option {"selected" if cur.get("true_mechanism")==m else ""}>{m}</option>' for m in MECHS.get(rule, ["unknown"]))
    def chk(v):
        return "checked" if cur.get("true_verdict") == v else ""
    totals_html = _lines_html(totals, "total_lines", hl="total invest") if rule == "fv_conservation" else "<p><small>use roam/grid below</small></p>"
    main = f"""<h3>{rule} &middot; {rid}</h3>
<p>cik {r['cik']} &middot; {r['report_date']} &middot; bucket {r['bucket']}</p>
<div class=claim><b>Claim (the question - do not assume correct):</b><br>{_claim_html(claim, ASSERTED.get(rule,''))}</div>
<h4>Flagged positions (what the rule actually fired on)</h4>{_flagged_html(flagged)}
<details><summary>All tables (index) &mdash; usually unneeded; flagged rows are already located above</summary>{_overview_html(overview)}</details>
<h4>{'Totals (anchor): does the filing total match value_sum or anchor_value?' if rule=='fv_conservation' else 'Totals'}</h4>{totals_html}
<h4>Roam raw source</h4>
<input id=q size=50 placeholder="comma terms e.g. PIK,Total,issuer">
<button onclick="roam()">roam</button>
&nbsp; table <input id=t size=4><button onclick="grid()">grid</button>
<div id=out><small>(roam / grid results render here as a table)</small></div>
<h4>Your verdict (BLIND)</h4>
<form onsubmit="return save(event)">
<label class=r><input type=radio name=v value=real_error {chk('real_error')}> real_error</label>
<label class=r><input type=radio name=v value=false_alarm {chk('false_alarm')}> false_alarm</label>
<label class=r><input type=radio name=v value=ambiguous {chk('ambiguous')}> ambiguous</label><br><br>
<label><input type=checkbox id=loc {'checked' if cur.get('localized') else ''}> localized</label>
&nbsp; mechanism <select id=mech>{mech_opts}</select><br><br>
note (cite table/row): <br><textarea id=note rows=3 cols=80>{cur.get('note','')}</textarea><br><br>
<button>save</button> <span id=msg></span></form>
<script>
const rid="{rid}";
function esc(s){{return (''+s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function tbl(rows,head){{let h='<table class=g><tr>'+head.map(x=>'<th>'+x+'</th>').join('')+'</tr>';
 h+=rows.map(r=>'<tr>'+r.map(c=>'<td>'+esc(c)+'</td>').join('')+'</tr>').join('');return h+'</table>';}}
async function roam(){{const q=document.getElementById('q').value;
 const r=await fetch(`/api/cli/${{rid}}?cmd=roam&query=`+encodeURIComponent(q));const d=await r.json();
 const out=document.getElementById('out');
 if(d.matches){{out.innerHTML=`<small>${{d.n_hits}} hits, scanned ${{d.rows_scanned}}${{d.truncated?' (truncated)':''}}</small>`+
   tbl(d.matches.map(m=>[m.table_index,m.row_index,m.row_text]),['tbl','row','text']);}}
 else out.innerHTML='<p class=err>'+esc(JSON.stringify(d))+'</p>';}}
async function grid(){{const t=document.getElementById('t').value;
 const r=await fetch(`/api/cli/${{rid}}?cmd=grid&table=`+t);const d=await r.json();
 const out=document.getElementById('out');
 if(d.rows){{out.innerHTML=`<small>table ${{d.table_index}}, rows ${{d.start}}-${{d.end}} of ${{d.n_rows}}</small>`+
   tbl(d.rows.map(x=>[x.row_index,(x.cells||[]).filter(c=>c).join('  |  ')]),['row','cells']);}}
 else out.innerHTML='<p class=err>'+esc(JSON.stringify(d))+'</p>';}}
async function save(e){{e.preventDefault();
 const v=document.querySelector('input[name=v]:checked');
 if(!v){{document.getElementById('msg').textContent='pick a verdict';return false;}}
 const body={{true_verdict:v.value,localized:document.getElementById('loc').checked,
  true_mechanism:document.getElementById('mech').value,note:document.getElementById('note').value}};
 await fetch(`/api/save/${{rid}}`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
 document.getElementById('msg').textContent='saved';setTimeout(()=>location.reload(),300);return false;}}
</script>"""
    return PAGE.format(nav=_nav(), main=main)


@app.route("/api/cli/<rid>")
def api_cli(rid):
    cmd = request.args.get("cmd", "overview")
    extra = []
    if cmd == "roam":
        extra = ["--query", request.args.get("query", "")]
    elif cmd == "grid":
        extra = ["--table", request.args.get("table", "0"), "--count", "120"]
    return jsonify(_cli(rid, cmd, *extra))


@app.route("/api/save/<rid>", methods=["POST"])
def api_save(rid):
    r = next((x for x in SUBSET if x["review_id"] == rid), None)
    if not r:
        return "unknown", 404
    LABELS.mkdir(parents=True, exist_ok=True)
    body = request.get_json(force=True)
    rec = {"review_id": rid, "rule_name": r["rule_name"], "cik": r["cik"],
           "report_date": r["report_date"], **body}
    (LABELS / f"{rid}.json").write_text(json.dumps(rec, indent=2))
    return jsonify({"ok": True})


@app.route("/export")
def export():
    rows = [json.loads(p.read_text()) for p in sorted(LABELS.glob("*.json"))]
    cols = ["review_id", "rule_name", "cik", "report_date", "true_verdict", "localized", "true_mechanism", "note"]
    with open(GOLD / "gold_labels.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return f"exported {len(rows)} labels to {GOLD / 'gold_labels.csv'}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per", type=int, default=8)
    ap.add_argument("--port", type=int, default=5058)
    args = ap.parse_args()
    global SUBSET
    SUBSET = _select(args.per)
    print(f"serving {len(SUBSET)} bundles ({args.per}/rule) on http://127.0.0.1:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
