"""Per-field error sample: published rows read against their printed schedule line.

    python scripts/v05_evidence/field_sample.py [--dir D] draw [--per-fund 20] [--seed 20261014] [--label L --cik C]
    python scripts/v05_evidence/field_sample.py [--dir D] cards [--batch 40]
    python scripts/v05_evidence/field_sample.py [--dir D] check <labels.json>
    python scripts/v05_evidence/field_sample.py [--dir D] score

--dir defaults to docs/investigations/v05_field_sample. With --label and --cik, ``draw`` samples one
fund from one sandbox (the fund-clearing skill's page sample, written under
docs/investigations/v05_readings/samples/<cik>/); without them, every fund's accepted sandbox.

``draw`` takes a fixed-seed random sample of published holdings rows, the same number per fund,
from each fund's accepted sandbox (docs/investigations/v05_readings/accepted_sandboxes.json).
``cards`` finds each row's printed line in the cached inline-XBRL filing by its context id (no text
search): the cells of the <tr> that carries the row's facts, which concept each cell is tagged
with, the facts on the context that are not on that line (hidden or elsewhere), the lines around
it and the table's header rows. Readers label each field on a card (labels/<batch>.json, see
LABELS below); ``score`` turns the labels into per-field rates with 95% intervals, split by cause
(the filer's tag or our pipeline).

Everything is written to docs/investigations/v05_field_sample/. Read-only on sandboxes and filings.
"""
from __future__ import annotations

import argparse
import csv
import html as htmlmod
import json
import math
import re
import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs/investigations/v05_field_sample"
ACCEPTED = REPO / "docs/investigations/v05_readings/accepted_sandboxes.json"
RAW = REPO / "data/raw/filings/bdc_html"

PUBLISHED = ["issuer_name", "instrument_description", "asset_category", "fair_value", "cost", "principal_amount",
             "principal_amount_currency", "shares_held", "pct_of_net_assets", "interest_rate", "basis_spread",
             "reference_rate_type", "coupon_type", "pik_rate", "maturity_date", "bdc_investment_identifier",
             "corrected_fields", "interest_rate_source", "basis_spread_source", "pik_rate_source", "shares_held_source",
             "src_transforms"]
# fields a reader labels, and the published columns each is judged on
FIELDS = {
    "row_identity": [],
    "issuer_name": ["issuer_name"],
    "instrument_and_class": ["instrument_description", "asset_category"],
    "fair_value": ["fair_value"],
    "cost": ["cost"],
    "principal_amount": ["principal_amount", "principal_amount_currency"],
    "shares_held": ["shares_held"],
    "pct_of_net_assets": ["pct_of_net_assets"],
    "interest_rate": ["interest_rate"],
    "basis_spread": ["basis_spread"],
    "reference_rate_type": ["reference_rate_type"],
    "pik_rate": ["pik_rate"],
    "maturity_date": ["maturity_date"],
}
CONCEPT_FIELD = {
    "InvestmentOwnedAtFairValue": "fair_value", "InvestmentOwnedAtCost": "cost",
    "InvestmentOwnedBalancePrincipalAmount": "principal_amount", "InvestmentOwnedBalanceShares": "shares_held",
    "InvestmentOwnedPercentOfNetAssets": "pct_of_net_assets", "InvestmentInterestRate": "interest_rate",
    "InvestmentBasisSpreadVariableRate": "basis_spread", "InvestmentInterestRatePaidInKind": "pik_rate",
    "InvestmentMaturityDate": "maturity_date",
}
PUBLISHED_STATES = ("ok", "wrong", "missing", "extra", "convention", "unclear")
TAG_STATES = ("right", "wrong_value", "wrong_label", "wrong_row", "untagged", "not_printed", "unclear")
CAUSES = ("tag", "pipeline", "page", "unclear", "")


def _sandboxes() -> dict[str, str]:
    return {cik: entry["label"] for cik, entry in json.loads(ACCEPTED.read_text(encoding="utf-8")).items()}


def _filing(cik: str, accession: str) -> Path:
    return RAW / cik.lstrip("0") / (accession.replace("-", "") + ".html")


def draw(per_fund: int, seed: int, only: dict[str, str] | None = None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET memory_limit='3GB'")
    picked = []
    for cik, label in sorted((only or _sandboxes()).items()):
        path = (REPO / "scratch/fund_sandbox" / label / "output/private_markets_holdings.parquet").as_posix()
        rows = con.execute(
            "SELECT %s, CAST(report_date AS VARCHAR) AS report_date, accession_number, src_context_id FROM read_parquet(?) "
            "WHERE cik = ? AND src_context_id IS NOT NULL "
            "ORDER BY md5(cik || src_context_id || CAST(report_date AS VARCHAR) || CAST(fair_value AS VARCHAR) || ?) LIMIT ?"
            % ", ".join("CAST(%s AS VARCHAR) AS %s" % (c, c) for c in PUBLISHED),
            [path, cik, str(seed), per_fund * 4]).fetchdf()
        taken = 0
        for record in rows.to_dict("records"):
            if taken == per_fund:
                break
            if not _filing(cik, record["accession_number"]).exists():
                continue
            record.update(cik=cik, sandbox=label)
            picked.append(record)
            taken += 1
        print("%s %-8s %d rows" % (cik, label, taken))
    for i, record in enumerate(picked, 1):
        record["card"] = "C%03d" % i
    columns = ["card", "cik", "sandbox", "report_date", "accession_number", "src_context_id"] + PUBLISHED
    with open(OUT / "sample.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({k: record.get(k) for k in columns} for record in picked)
    print("%d rows -> %s" % (len(picked), (OUT / "sample.csv").relative_to(REPO).as_posix()))


def _text(fragment: str) -> str:
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def _facts_in(fragment: str) -> list[dict]:
    """ix facts in a fragment: concept, context, displayed text, scale, sign."""
    found = []
    for m in re.finditer(r"<ix:(nonFraction|nonNumeric)\b([^>]*)>(.*?)</ix:\1>", fragment, flags=re.S):
        attrs = dict(re.findall(r'([\w:]+)="([^"]*)"', m.group(2)))
        found.append({"concept": attrs.get("name", "").split(":")[-1], "context": attrs.get("contextRef", ""),
                      "shown": _text(m.group(3)), "scale": attrs.get("scale"), "sign": attrs.get("sign"),
                      "numeric": m.group(1) == "nonFraction", "format": attrs.get("format", "").split(":")[-1]})
    return found


def _value(fact: dict):
    if not fact["numeric"]:
        return fact["shown"]
    digits = re.sub(r"[^\d.]", "", fact["shown"])
    if not digits or digits == ".":
        return 0.0
    value = round(float(digits) * (10 ** int(fact["scale"] or 0)), 10)
    return -value if fact.get("sign") == "-" else value


def _cells(tr: str) -> list[str]:
    cells = []
    for m in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, flags=re.S):
        cells.append(m.group(1))
    return cells


def _row_lines(table: str) -> list[str]:
    return re.findall(r"<tr\b.*?</tr>", table, flags=re.S)


def _matches(field: str, published: str, value) -> str:
    if published in (None, "", "None", "nan"):
        return "published empty"
    try:
        pub = float(published)
    except ValueError:
        shown = str(value)
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", shown.strip())
        if m:
            year = m.group(3) if len(m.group(3)) == 4 else "20" + m.group(3)
            shown = "%s-%02d-%02d" % (year, int(m.group(1)), int(m.group(2)))
        return "equal" if shown[:10] == str(published)[:10] else "differs"
    if not isinstance(value, float):
        return "differs"
    for candidate in (value, value * 100):
        if abs(pub - candidate) <= max(0.005, abs(candidate) * 0.001):
            return "equal"
    return "differs"


def _members(page: str) -> dict[str, str]:
    """Context id -> its dimension members (text), so a fact on a sibling context of the same
    investment (a duration period beside the instant) is not reported as another row's."""
    found = {}
    for m in re.finditer(r'<xbrli:context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</xbrli:context>', page, flags=re.S):
        segment = re.search(r"<xbrli:segment>(.*?)</xbrli:segment>", m.group(2), flags=re.S)
        found[m.group(1)] = _text(segment.group(1)) if segment else ""
    return found


def card(record: dict, page: str, hidden: list[tuple[int, int]], members: dict[str, str]) -> str:
    ctx = record["src_context_id"]
    spots = [m.start() for m in re.finditer(r'contextRef="%s"' % re.escape(ctx), page)]
    visible = [p for p in spots if not any(a <= p < b for a, b in hidden)]
    head = "### %s | %s | %s | %s" % (record["card"], record["cik"], record["report_date"], record["accession_number"])
    lines = [head, ""]
    row_facts = []
    if not visible:
        lines.append("**No printed line found:** every fact on this context is hidden or the context is not in the filing.")
        tr = ""
    else:
        start = page.rfind("<tr", 0, visible[0])
        end = page.find("</tr>", visible[0]) + 5
        tr = page[start:end]
        table_start = page.rfind("<table", 0, start)
        table = page[table_start:end]
        rows = _row_lines(table)
        header = []
        for line in rows:
            if "ix:nonFraction" in line:
                break
            text = " | ".join(t for t in (_text(c) for c in _cells(line)) if t)
            if text:
                header.append(text[:300])
        lines.append("**Table header rows:** " + (" // ".join(header[-4:]) if header else "(none in this table; see the lines above)"))
        before = rows[-4:-1]
        lines.append("")
        lines.append("**Lines printed before it:**")
        for line in before:
            lines.append("- " + (" | ".join(t for t in (_text(c) for c in _cells(line)) if t) or "(blank)")[:300])
        lines.append("")
        lines.append("**The printed line** (cell text, then the facts tagged in that cell):")
        n = 0
        for raw in _cells(tr):
            text = _text(raw)
            facts = _facts_in(raw)
            if not text and not facts:
                continue
            if text in ("$", "") and not facts:
                continue
            n += 1
            tags = []
            for fact in facts:
                if fact["context"] == ctx:
                    where = ""
                elif members.get(fact["context"]) == members.get(ctx):
                    where = " (same investment, other period context)"
                else:
                    where = " ON ANOTHER INVESTMENT'S CONTEXT (%s)" % members.get(fact["context"], fact["context"])[:80]
                shown_value = _value(fact)
                tags.append("%s = %s%s" % (fact["concept"], shown_value if fact["numeric"] else fact["shown"][:80], where))
                if fact["context"] == ctx:
                    row_facts.append(fact)
            lines.append("%d. `%s`%s" % (n, text[:200], ("  <- " + "; ".join(tags)) if tags else ""))
        after = page[end:end + 20000]
        nxt = _row_lines(after)[:2]
        lines.append("")
        lines.append("**Lines printed after it:**")
        for line in nxt:
            lines.append("- " + (" | ".join(t for t in (_text(c) for c in _cells(line)) if t) or "(blank)")[:300])
    # facts on this context that are not on the printed line
    elsewhere = []
    siblings = [cid for cid, member in members.items() if cid != ctx and member and member == members.get(ctx)]
    on_line = (page.rfind("<tr", 0, visible[0]), page.find("</tr>", visible[0])) if visible else (-1, -1)
    for cid in siblings:
        for m in re.finditer(r'contextRef="%s"' % re.escape(cid), page):
            if on_line[0] <= m.start() < on_line[1]:
                continue
            tag_start = page.rfind("<ix:", 0, m.start())
            close = re.search(r"</ix:(nonFraction|nonNumeric)>", page[tag_start:tag_start + 4000])
            fact = _facts_in(page[tag_start: tag_start + close.end()])[0] if close else None
            if fact:
                hid = any(a <= m.start() < b for a, b in hidden)
                elsewhere.append((fact, ("hidden" if hid else "another printed line") + ", other period context"))
                row_facts.append(fact)
    for p in spots:
        if tr and page.rfind("<tr", 0, p) == page.rfind("<tr", 0, visible[0]) and not any(a <= p < b for a, b in hidden):
            continue
        tag_start = page.rfind("<ix:", 0, p)
        close = re.search(r"</ix:(nonFraction|nonNumeric)>", page[tag_start:tag_start + 4000])
        fact = _facts_in(page[tag_start: tag_start + close.end()])[0] if close else None
        if fact:
            hid = any(a <= p < b for a, b in hidden)
            elsewhere.append((fact, "hidden" if hid else "another printed line"))
            row_facts.append(fact)
    lines.append("")
    lines.append("**Facts on this context not on the printed line:** " + (
        "; ".join("%s = %s (%s)" % (f["concept"], _value(f) if f["numeric"] else f["shown"][:60], w) for f, w in elsewhere) or "none"))
    lines.append("")
    lines.append("**Member (identifier text):** `%s`" % str(record.get("bdc_investment_identifier"))[:300])
    lines.append("")
    lines.append("**Published:**")
    by_field = {}
    for fact in row_facts:
        field = CONCEPT_FIELD.get(fact["concept"])
        if field:
            by_field.setdefault(field, []).append(fact)
    for column in PUBLISHED:
        if column == "bdc_investment_identifier":
            continue
        note = ""
        if column in by_field:
            note = "  (tag: %s)" % ", ".join(_matches(column, record.get(column), _value(f)) for f in by_field[column])
        lines.append("- %s = %s%s" % (column, record.get(column), note))
    lines.append("")
    return "\n".join(lines)


def cards(batch: int) -> None:
    with open(OUT / "sample.csv", newline="", encoding="utf-8") as fh:
        records = list(csv.DictReader(fh))
    (OUT / "cards").mkdir(exist_ok=True)
    pages: dict[str, tuple[str, list]] = {}
    made = {}
    # one filing in memory at a time: work in filing order, write in card order
    for record in sorted(records, key=lambda r: r["accession_number"]):
        key = record["accession_number"]
        if key not in pages:
            text = _filing(record["cik"], key).read_text(encoding="utf-8", errors="replace")
            hidden = [(m.start(), m.end()) for m in re.finditer(r"<ix:hidden>.*?</ix:hidden>", text, flags=re.S)]
            pages = {key: (text, hidden, _members(text))}
        made[record["card"]] = card(record, *pages[key])
    written = [made[r["card"]] for r in records]
    for i in range(0, len(written), batch):
        name = "batch_%02d.md" % (i // batch + 1)
        (OUT / "cards" / name).write_text("\n".join(written[i:i + batch]), encoding="utf-8")
        print(name, len(written[i:i + batch]), "cards")


def _wilson(k: int, n: int) -> str:
    if n == 0:
        return "-"
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return "%.1f%% (%.1f-%.1f)" % (100 * p, 100 * max(0, centre - half), 100 * min(1, centre + half))


def problems(label: dict) -> list[str]:
    found = []
    for field in FIELDS:
        entry = (label.get("fields") or {}).get(field)
        if not isinstance(entry, dict):
            found.append("%s: missing" % field)
            continue
        if entry.get("published") not in PUBLISHED_STATES:
            found.append("%s: published must be one of %s" % (field, ", ".join(PUBLISHED_STATES)))
        if entry.get("tag") not in TAG_STATES:
            found.append("%s: tag must be one of %s" % (field, ", ".join(TAG_STATES)))
        if entry.get("published") in ("wrong", "missing", "extra") and entry.get("cause") not in ("tag", "pipeline", "page", "unclear"):
            found.append("%s: a wrong published value needs a cause" % field)
    return found


def score() -> None:
    with open(OUT / "sample.csv", newline="", encoding="utf-8") as fh:
        meta = {r["card"]: r for r in csv.DictReader(fh)}
    labels = {}
    for path in sorted((OUT / "labels").glob("*.json")):
        for label in json.loads(path.read_text(encoding="utf-8")):
            bad = problems(label)
            if bad:
                print("%s %s: %s" % (path.name, label.get("card"), "; ".join(bad[:3])))
                continue
            labels.setdefault(label["card"], []).append(label)
    first = {card: entries[0] for card, entries in labels.items()}
    out = ["# Per-field error sample: results", "",
           "Generated by `scripts/v05_evidence/field_sample.py score`. %d cards labelled of %d drawn." % (len(first), len(meta)), "",
           "Rates are over cards where the page prints the field or we publish it (blank on both sides is not counted).",
           "95% Wilson intervals in brackets.", "",
           "| Field | n | Published wrong | of which tag | of which pipeline | Tag wrong (any) | wrong label | wrong value | wrong row | untagged |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for field in FIELDS:
        rows = [l["fields"][field] for l in first.values()]
        rows = [r for r in rows if not (r["tag"] == "not_printed" and r["published"] == "ok")]
        n = len(rows)
        wrong = [r for r in rows if r["published"] in ("wrong", "missing", "extra")]
        tagged = [r for r in rows if r["tag"] not in ("not_printed", "unclear")]
        tag_bad = [r for r in tagged if r["tag"] != "right"]
        out.append("| %s | %d | %s | %d | %d | %s | %d | %d | %d | %d |" % (
            field, n, _wilson(len(wrong), n), sum(r.get("cause") == "tag" for r in wrong),
            sum(r.get("cause") == "pipeline" for r in wrong), _wilson(len(tag_bad), len(tagged)),
            sum(r["tag"] == "wrong_label" for r in tagged), sum(r["tag"] == "wrong_value" for r in tagged),
            sum(r["tag"] == "wrong_row" for r in tagged), sum(r["tag"] == "untagged" for r in tagged)))
    # rows with any published error, by fund and by era
    out += ["", "| Fund | cards | cards with any published error | with any tag error |", "|---|---|---|---|"]
    by_fund: dict[str, list] = {}
    for card_id, label in first.items():
        by_fund.setdefault(meta[card_id]["cik"], []).append(label)
    for cik, members in sorted(by_fund.items()):
        any_pub = sum(any(f["published"] in ("wrong", "missing", "extra") for f in l["fields"].values()) for l in members)
        any_tag = sum(any(f["tag"] in ("wrong_value", "wrong_label", "wrong_row", "untagged") for f in l["fields"].values()) for l in members)
        out.append("| %s | %d | %s | %s |" % (cik, len(members), _wilson(any_pub, len(members)), _wilson(any_tag, len(members))))
    out += ["", "| Era | cards | with any published error | with any tag error |", "|---|---|---|---|"]
    for era, test in (("to 2023-12-31", lambda d: d <= "2023-12-31"), ("2024 on", lambda d: d > "2023-12-31")):
        members = [l for c, l in first.items() if test(meta[c]["report_date"])]
        any_pub = sum(any(f["published"] in ("wrong", "missing", "extra") for f in l["fields"].values()) for l in members)
        any_tag = sum(any(f["tag"] in ("wrong_value", "wrong_label", "wrong_row", "untagged") for f in l["fields"].values()) for l in members)
        out.append("| %s | %d | %s | %s |" % (era, len(members), _wilson(any_pub, len(members)), _wilson(any_tag, len(members))))
    # agreement where a card was read twice
    twice = {c: e for c, e in labels.items() if len(e) > 1}
    if twice:
        same = total = 0
        for entries in twice.values():
            a, b = entries[0]["fields"], entries[1]["fields"]
            for field in FIELDS:
                total += 1
                same += (a[field]["published"] == b[field]["published"]) and (a[field]["tag"] == b[field]["tag"])
        out += ["", "Read twice: %d cards; the two readers gave the same published and tag label on %d of %d fields (%.0f%%)."
                % (len(twice), same, total, 100 * same / total)]
    # every published error, for the fund agent or the owner to act on
    errors = [(c, f, e) for c, l in sorted(first.items()) for f, e in l["fields"].items()
              if e["published"] in ("wrong", "missing", "extra")]
    out += ["", "Published errors: %d" % len(errors), "", "| Card | Quarter | Field | Published | Cause | Note |", "|---|---|---|---|---|---|"]
    for card_id, field, entry in errors:
        out.append("| %s | %s | %s | %s | %s | %s |" % (card_id, meta[card_id]["report_date"], field, entry["published"],
                                                       entry.get("cause", ""), str(entry.get("note", "")).replace("|", "/")[:200]))
    (OUT / "results.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))


def main(argv=None) -> int:
    global OUT
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--per-fund", type=int, default=20)
    d.add_argument("--seed", type=int, default=20261014)
    d.add_argument("--label")
    d.add_argument("--cik")
    c = sub.add_parser("cards")
    c.add_argument("--batch", type=int, default=40)
    sub.add_parser("score")
    k = sub.add_parser("check")
    k.add_argument("labels")
    args = parser.parse_args(argv)
    if args.dir:
        OUT = Path(args.dir) if Path(args.dir).is_absolute() else REPO / args.dir
    if args.command == "draw":
        if bool(args.label) != bool(args.cik):
            parser.error("--label and --cik go together")
        draw(args.per_fund, args.seed, {args.cik.zfill(10): args.label} if args.cik else None)
    elif args.command == "cards":
        cards(args.batch)
    elif args.command == "check":
        entries = json.loads(Path(args.labels).read_text(encoding="utf-8"))
        bad = [(e.get("card"), problems(e)) for e in entries]
        bad = [(c, p) for c, p in bad if p]
        for card_id, found in bad:
            print(card_id, "; ".join(found))
        print("%d cards, %d with problems" % (len(entries), len(bad)))
        return 1 if bad else 0
    else:
        score()
    return 0


if __name__ == "__main__":
    sys.exit(main())
