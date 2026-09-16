"""Conservative source-name preservation for explicitly co-listed legal borrowers."""

# This is an anchored name list, not a search for any occurrence of "and".
# Each side must end with a legal suffix. Trailing instrument text is removed
# only at a comma/pipe boundary following the final legal name.
LEGAL=r'(?:incorporated|corporation|limited|l\.?l\.?c\.?|inc\.?|corp\.?|ltd\.?|l\.?p\.?|plc|gmbh)'
ENTITY=r'[^|;%]+?\b'+LEGAL
JOINT_LABEL_RE=r'(?i)^('+ENTITY+r'\s*,?\s+(?:and|&)\s+'+ENTITY+r')\s*(?:[,|]|$)'


def joint_label_sql(expression):
    clean="trim(regexp_replace(coalesce(CAST("+expression+" AS VARCHAR),''),'\\s+',' ','g'))"
    return "nullif(trim(regexp_extract("+clean+",'"+JOINT_LABEL_RE.replace("'","''")+"',1)),'')"


def compatible_names(name_a,name_b):
    """Fuzzy/structured-ID similarity cannot equate joint and single borrowers.

    A loan identifier may refer to an instrument shared by its co-borrowers.
    It does not authorize merging that borrower set with an individual party.
    Joint lists use conservative exact normalized-name agreement here.
    """
    if name_a.startswith('joint:') or name_b.startswith('joint:'):
        return name_a==name_b
    return True
