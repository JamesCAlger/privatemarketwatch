"""The margin a schedule line prints over its benchmark, read the D-031 way.

Shared by the agentA shadow engine (scripts/shadow_agent_a_engine.py) and the agentA retirement check
(scripts/v05_evidence/agenta_retirement_check.py), so both read a printed margin the same way:

- the margin is the number printed after the benchmark code: 'S + 5.25 %', 'S+525' (basis points),
  'SOFR 5.00 %', or the cell labelled Cash / Spread / PIK;
- a number labelled Floor ('1.00 % Floor', '(100 Floor)', 'Floor 1.00 %') is a floor, never the margin;
- per D-031 the published spread is the total margin: 'X % Cash + Y % PIK' or 'X Cash plus Y % PIK'
  is X + Y; '(includes Y % PIK)' is X; 'S + 0.00 %; 0.75 % Floor; 5.75 % PIK' is 5.75;
- two or more unlabelled numbers after the code (a floor column next to a spread column) are ambiguous:
  ``total`` is None and a caller must fail closed.
Text only; the line is the row as printed, cells joined by spaces (or ' | ', which is treated as space).
"""
from __future__ import annotations

import re

BENCHMARK_CODES = {"S": "SOFR", "SF": "SOFR", "SOFR": "SOFR", "TSOFR": "SOFR", "L": "LIBOR", "LIBOR": "LIBOR",
                   "E": "EURIBOR", "EURIBOR": "EURIBOR", "P": "PRIME", "PRIME": "PRIME", "SONIA": "SONIA",
                   "SN": "SONIA", "SARON": "SARON", "STIBOR": "STIBOR", "CORRA": "CORRA", "BBSY": "BBSY",
                   "BBSW": "BBSW", "CDOR": "CDOR", "NIBOR": "NIBOR", "C": "CDOR", "SA": "SARON"}
CODE_RE = re.compile(r"\b([A-Z]{1,6})(?:\s*\([A-Z0-9]{1,3}\))?\s*(\+|-\s|\s)(?=\s*(?:\d|-))")
DATE_RE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?![\d/])")
NUM_RE = re.compile(r"(?<![\w.])(\d{1,4}(?:\.\d+)?)\s*(%?)\s*(Floor|floor|Cash|cash|PIK|pik)?")


def parse_rate(line: str) -> dict | None:
    """{'code', 'cash', 'pik', 'total', 'floors'} of the first benchmark code on the line and the margin
    printed after it; None when no benchmark is printed; 'total' None when the margin is ambiguous."""
    line = " ".join(str(line or "").replace("|", " ").split())
    for m in CODE_RE.finditer(line):
        code, sep = m.group(1), m.group(2)
        bench = BENCHMARK_CODES.get(code.upper())
        if not bench or (len(code) <= 2 and sep != "+"):
            continue
        seg = line[m.end():]
        d = DATE_RE.search(seg)
        seg = seg[:d.start()] if d else seg[:90]
        includes = re.search(r"(?i)incl(?:udes|\.|uding)?\s*(\d{1,4}(?:\.\d+)?)\s*%\s*PIK", seg)
        nums = []
        for n in NUM_RE.finditer(seg):
            before = seg[max(0, n.start() - 10):n.start()].lower()
            label = (n.group(3) or "").lower()
            if not label and re.search(r"floor\s*:?\s*$", before):  # 'Floor 1.00 %'
                label = "floor"
            if not label and re.search(r"spread\s*:?\s*$", before):  # 'Spread 3.50 %'
                label = "spread"
            value = float(n.group(1))
            if not n.group(2) and "." not in n.group(1) and value >= 25:
                value /= 100.0  # basis points
            nums.append((value, label, n.start()))
        floors = [v for v, lab, _ in nums if lab == "floor"]
        rest = [(v, lab, pos) for v, lab, pos in nums if lab != "floor"]
        if includes:
            rest = [(v, lab, pos) for v, lab, pos in rest if pos < includes.start()]
        cash = pik = None
        if sep == "+" and rest:
            cash = rest[0][0]
            if rest[0][1] == "pik":
                cash, pik = 0.0, rest[0][0]
            elif rest[0][1] == "cash":
                pk = [v for v, lab, _ in rest[1:] if lab == "pik"]
                pik = pk[0] if pk else None
            else:  # 'S + 0.00 %; 0.75 % Floor; 5.75 % PIK'
                pk = [v for v, lab, _ in rest[1:] if lab == "pik"]
                if pk and not re.search(r";|Cash|plus|\+", seg):
                    # 'S + 2.88 % (3.38 % PIK)' / 'S + 725 (300 PIK)': filers use this both for 'plus'
                    # and for 'of which'; the line does not say which -> ambiguous
                    return {"code": bench, "cash": cash, "pik": pk[0], "total": None, "floors": floors}
                pik = pk[0] if pk else None
        else:
            labelled = [(v, lab) for v, lab, _ in rest if lab in ("cash", "spread", "pik")]
            unlabelled = [v for v, lab, _ in rest if not lab]
            if any(lab in ("cash", "spread") for _, lab in labelled):
                cash_pos = next(pos for v, lab, pos in rest if lab in ("cash", "spread"))
                cash = next(v for v, lab in labelled if lab in ("cash", "spread"))
                pk = [v for v, lab, pos in rest if lab == "pik" and pos > cash_pos]
                pik = pk[0] if pk else None
                floors += [v for v, lab, pos in rest if not lab and pos < cash_pos]  # a floor column first
            elif labelled:  # PIK only, after an unlabelled floor column
                cash, pik = 0.0, labelled[0][0]
                pik_pos = next(pos for v, lab, pos in rest if lab == "pik")
                floors += [v for v, lab, pos in rest if not lab and pos < pik_pos]
            elif len(unlabelled) == 1:
                cash = unlabelled[0]
            else:
                return {"code": bench, "cash": None, "pik": None, "total": None, "floors": floors}
        total = None if cash is None else round(cash + (pik or 0.0), 6)
        return {"code": bench, "cash": cash, "pik": pik, "total": total, "floors": floors}
    return None
