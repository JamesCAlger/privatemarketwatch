"""Global issuer / instrument split of a BDC row's name (default for every filer).

Most filers name a row's context 'Issuer, Instrument [n]' ('Auctane, Inc., First lien senior secured
loan 2', 'Plasma Buyer LLC 3'). Where the member parser keeps it whole, issuer_name carries the
instrument and the row number, and instrument_description is blank. A per-filer wrapper setting
(dispatch.issuer_name_strip_re) did this one fund at a time; this is the shared default, run after
those settings, so a fund whose wrapper already split its names finds nothing left to split.

One cut, conservative: the instrument, from the first ', ' or ' - ' that is followed by an
instrument phrase (lien, secured, subordinated, unsecured, term loan, revolver, delayed draw,
preferred, common stock or units, class/series units, LP/LLC/membership interest, warrants,
notes); not after a section heading, and not when the cut text names a company. A trailing row
number ('Inc. 2') is left to the fund's wrapper (see split_name); ROW_NUMBER only reports it.

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
# The same, spelled out ('Madison Reed, Inc. One', Trinity Capital from 2025-03-31). Reported by
# shapes() for the fund gate; not cut by the split (a fund's wrapper may).
ROW_NUMBER_WORD = re.compile(r"(?:" + "|".join("(?<=%s)" % re.escape(s) for s in _SUFFIXES)
                             + r")\s*,?\s+(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve)$")


def enabled(reference: Path = REFERENCE) -> bool:
    if not reference.exists():
        return False
    return json.loads(reference.read_text(encoding="utf-8")).get("enabled") is True


# What is left in front of the cut is a section heading, not an issuer ('Debt Investments, First Lien
# Senior Secured, Military Retail Solutions': the issuer is at the end).
_HEADING = re.compile(r"(?i)(?:\binvestments?|\baffiliated|\bcontrolled)\s*$")
# The cut text names a company: the cut is inside the issuer ('Wilnat, Inc. - Revolving Credit Lin, LLC').
_LEGAL_FORM = re.compile(r"(?i),\s*(?:LLC|L\.L\.C\.|Inc\.?|Ltd\.?|LP|L\.P\.|Corp\.?|Limited|GmbH|plc)\b")


def split_name(name: str) -> tuple[str, str, str]:
    """(issuer, cut instrument text, cut row number) for one name; '' where nothing is cut."""
    if not isinstance(name, str) or not name.strip():
        return name, "", ""
    issuer, cut, number = name, "", ""
    m = INSTRUMENT_CUT.search(issuer)
    if m:
        before, after = issuer[:m.start()].rstrip(" ,-"), m.group(1).strip()
        if before.strip() and re.search(r"[A-Za-z]{2}", before) and not _HEADING.search(before) \
                and not _LEGAL_FORM.search(after):
            issuer, cut = before, after
    # A row number ('Sylva, Inc. 2') is NOT cut here. Cohort A/B 2026-10-14: TriplePoint numbers
    # tranches of one company with the same instrument text and renumbers them between quarters;
    # with the number off the name the matcher re-paired them each quarter (positions 1,311 to
    # 1,333). Where the numbering is stable a fund's wrapper cuts it (issuer_name_strip_re); the
    # fund gate still reports a leftover number as a shape. ``number`` is kept in the signature.
    return issuer, cut, number


def shapes(name: str) -> list[str]:
    """Which name shapes a published issuer name still has (used by the fund gate)."""
    if not isinstance(name, str):
        return []
    found = []
    if INSTRUMENT_CUT.search(name):
        found.append("instrument_in_name")
    if ROW_NUMBER.search(name) or ROW_NUMBER_WORD.search(name):
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
    changed = {k: v for k, v in table.items() if v[0] != k}
    if not changed:
        return combined
    hit = filed.isin(list(changed))
    idx = filed[hit].index
    names = filed[hit]
    combined.loc[idx, "issuer_name"] = names.map({k: v[0] for k, v in changed.items()}).values
    if "instrument_description" not in combined.columns:
        return combined
    cut = names.map({k: v[1] for k, v in changed.items()}).fillna("")
    number = names.map({k: v[2] for k, v in changed.items()}).fillna("")
    current = combined.loc[idx, "instrument_description"].astype("string").fillna("").str.strip()
    out = current.copy()
    # the instrument text cut off the name: fills a blank instrument, or goes in front of one that
    # does not already hold it
    has_cut = cut != ""
    holds = pd.Series([c.lower() in i.lower() for c, i in zip(cut[has_cut], current[has_cut])], index=cut[has_cut].index, dtype=bool)
    fill = has_cut & (current == "")
    front = has_cut & (current != "")
    front.loc[holds.index] &= ~holds
    out[fill] = cut[fill]
    out[front] = cut[front] + " " + current[front]
    # a row number cut off the name stays with the row: two warrants of one issuer, both
    # 'Warrant Investments', are told apart only by it
    tail = out.str.extract(r"(\d{1,2})\s*$", expand=False).fillna("")
    keep = (number != "") & (tail != number)
    out[keep] = (out[keep] + " " + number[keep]).str.strip()
    combined.loc[idx, "instrument_description"] = out.values
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
