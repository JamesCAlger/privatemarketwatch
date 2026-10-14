"""Global issuer / instrument split of a BDC row's name (default for every filer).

Most filers name a row's context 'Issuer, Instrument [n]' ('Auctane, Inc., First lien senior secured
loan 2', 'Plasma Buyer LLC 3'). Where the member parser keeps it whole, issuer_name carries the
instrument and the row number, and instrument_description is blank. A per-filer wrapper setting
(dispatch.issuer_name_strip_re) did this one fund at a time; this is the shared default, run after
those settings, so a fund whose wrapper already split its names finds nothing left to split.

Two cuts, each conservative:
  - the instrument: from the first ', ' or ' - ' that is followed by an instrument phrase
    (lien, secured, subordinated, unsecured, term loan, revolver, delayed draw, preferred, common
    stock or units, class/series units, LP/LLC/membership interest, warrants, notes);
  - a row number: one or two digits at the end, directly after a legal-form suffix or a closing
    bracket ('Inc. 2', 'LLC3', 'Ltd.,1'). A vintage ('2020-1') or a number inside the name stays.

The cut text goes to instrument_description when that is blank, or in front of it when it does
not already hold it. A name the cuts would empty is left as filed. Switched on in
data/reference/issuer_instrument_split.json; a filer opts out with dispatch.global_issuer_split: false.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

REFERENCE = Path(__file__).resolve().parents[1] / "data/reference/issuer_instrument_split.json"

INSTRUMENT_PHRASE = (
    r"\d?\s*(?:"
    r"(?:first|second|third|1st|2nd)[\s-]+lien\b|(?:senior\s+)?secured\b|senior\s+subordinated\b|subordinated\b"
    r"|(?:senior\s+)?unsecured\b|unitranche\b|mezzanine\b"
    r"|(?:(?:incremental|delayed\s+draw|multi[\s-]draw)\s+)?term\s+loan\b|revolv(?:er|ing)\b|delayed\s+draw\b"
    r"|(?:class|series)\s+[a-z0-9-]+(?:\s+(?:convertible|participating|senior|junior))*\s+(?:preferred|common|units?|shares|stock|interests?)\b"
    r"|(?:perpetual\s+|convertible\s+|senior\s+|participating\s+)*preferred\s+(?:stock|shares|units?|equity|interests?)\b"
    r"|common\s+(?:stock|units?|equity|shares|interests?)\b"
    r"|(?:lp|l\.p\.|llc|l\.l\.c\.|membership|partnership|limited\s+partner(?:ship)?|equity)\s+interests?\b"
    r"|warrants?\b|(?:senior\s+|subordinated\s+)?notes?\b"
    # a filer's section words in front of the instrument ('..., Equity Securities, Class A units')
    r"|equity\s+securities\b|debt\s+investments?\b"
    r")"
)
# the separator and the instrument phrase, to the end of the name
INSTRUMENT_CUT = re.compile(r"(?:\s*,\s*|\s+-\s+)(?=" + INSTRUMENT_PHRASE + r")(.*)$", re.IGNORECASE)
# one or two digits after a legal-form suffix or a bracket, to the end
_SUFFIXES = ("Inc.", "Inc", "LLC", "L.L.C.", "Ltd.", "Ltd", "LP", "L.P.", "Corp.", "Corp", "Co.", "Limited", "GmbH",
             "plc", "PLC", "S.A.", "B.V.", "N.V.", "AB", "AS", "Company", "Holdings", "Sarl", "S.a r.l.", ")")
ROW_NUMBER = re.compile(r"(?:" + "|".join("(?<=%s)" % re.escape(s) for s in _SUFFIXES) + r")\s*,?\s*\d{1,2}$")


def enabled(reference: Path = REFERENCE) -> bool:
    if not reference.exists():
        return False
    return json.loads(reference.read_text(encoding="utf-8")).get("enabled") is True


def split_name(name: str) -> tuple[str, str]:
    """(issuer, cut text) for one name; the cut text is '' when nothing is cut."""
    if not isinstance(name, str) or not name.strip():
        return name, ""
    issuer, cut = name, ""
    m = INSTRUMENT_CUT.search(issuer)
    if m and issuer[:m.start()].strip(" ,-") and re.search(r"[A-Za-z]{2}", issuer[:m.start()]):
        cut = m.group(1).strip()
        issuer = issuer[:m.start()].rstrip(" ,-")
    n = ROW_NUMBER.search(issuer)
    if n and issuer[:n.start()].strip():
        issuer = issuer[:n.start()].rstrip(" ,")
    return issuer, cut


def shapes(name: str) -> list[str]:
    """Which name shapes a published issuer name still has (used by the fund gate)."""
    if not isinstance(name, str):
        return []
    found = []
    if INSTRUMENT_CUT.search(name):
        found.append("instrument_in_name")
    if ROW_NUMBER.search(name):
        found.append("row_number_in_name")
    if re.search(r"(?i)\bJV\s+(?:LP|LLC)\b|\bjoint venture\b", name) and not re.match(r"(?i)^[^,]*\bJV\b[^,]*$", name):
        found.append("holder_label_in_name")
    return found


def split_issuer_instrument(combined: pd.DataFrame, opted_out: set[str] | frozenset[str] = frozenset()) -> pd.DataFrame:
    """Apply split_name to every BDC row's issuer_name (filers in ``opted_out`` excepted)."""
    if "issuer_name" not in combined.columns:
        return combined
    cik = combined["cik"].astype("string").str.zfill(10)
    rows = (combined["source"] == "bdc") & ~cik.isin(opted_out)
    if not rows.any():
        return combined
    filed = combined.loc[rows, "issuer_name"]
    # unique names only: the same name repeats across quarters and tranches
    table = {name: split_name(name) for name in pd.unique(filed.dropna())}
    issuer = filed.map(lambda v: table[v][0] if v in table else v)
    cut = filed.map(lambda v: table[v][1] if v in table else "").fillna("")
    combined.loc[rows, "issuer_name"] = issuer
    if "instrument_description" in combined.columns:
        current = combined.loc[rows, "instrument_description"].astype("string").fillna("").str.strip()
        has_cut = cut != ""
        fill = has_cut & (current == "")
        holds = pd.Series([c.lower() in i.lower() for c, i in zip(cut, current)], index=current.index)
        front = has_cut & (current != "") & ~holds
        idx = fill[fill].index
        combined.loc[idx, "instrument_description"] = cut[fill].values
        idx = front[front].index
        combined.loc[idx, "instrument_description"] = (cut[front] + " " + current[front]).values
    return combined


def opted_out_ciks(wrapper_dir: Path | None = None) -> set[str]:
    from pipeline.staging_bdc import _WRAPPER_DEFINITIONS_DIR
    folder = wrapper_dir or _WRAPPER_DEFINITIONS_DIR
    result: set[str] = set()
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if raw.get("dispatch", {}).get("global_issuer_split") is False:
            result.add(str(raw["cik"]).zfill(10))
    return result
