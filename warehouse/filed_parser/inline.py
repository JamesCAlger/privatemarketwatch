"""Parser for the inline XBRL (XHTML) document of a filing.

parse_inline(path, accession=None) returns a dict:
  document_row, fact_placement, footnote, fact_footnote: lists of tuples (accession first, store.TABLES order)
  html_parser: "xml" (strict XML parse) or "html" (fallback, lxml.html)
  stats: (name, value) pairs
No interpretation: where a fact is printed, the cell texts, the footnotes. Nothing is dropped.

Definitions (spec: warehouse/docs/filed_layer.md, section 4):
  kept table  a table that is the nearest enclosing table of at least one ix:nonFraction / ix:nonNumeric
  document_row  every tr whose nearest enclosing table is kept
  cells  one text per direct td/th child of the tr; white space (incl. U+00A0) collapsed; empty cells kept
  a fact nested in another fact is its own placement
"""
import gc
import hashlib
import re
from pathlib import Path

from lxml import etree
from lxml import html as lxml_html

from . import dashed_accession

TEXT_LIMIT = 4000
_STRING = etree.XPath("string()")
_FACTS = {"nonfraction": "nonFraction", "nonnumeric": "nonNumeric"}


class InlineError(ValueError):
    """The inline document cannot be read without losing or guessing something."""


def _collapse(text):
    # str.split() with no argument splits on all Unicode white space, including U+00A0
    return " ".join(text.split())


def _text(elem):
    return _collapse(_STRING(elem))


# Elements whose boundaries are printed line breaks. A space is inserted at both edges of each one
# (see _separate_blocks) so that text on separate printed lines is not glued together.
_BLOCKS = frozenset(("br", "p", "div", "tr", "td", "th", "li"))
_HIDDEN_LINK = re.compile(r"-sec-ix-hidden\s*:\s*([^;\s]+)", re.IGNORECASE)


def _separate_blocks(elem):
    elem.text = " " + (elem.text or "")
    elem.tail = " " + (elem.tail or "")


def _span(elem, name):
    """colspan / rowspan as an integer; 1 when absent or not a positive integer."""
    v = _attr(elem, name)
    if v is None:
        return 1
    m = re.fullmatch(r"\s*\+?([0-9]+)\s*", v)
    n = int(m.group(1)) if m else 0
    return n if n > 0 else 1


def _attr(elem, name):
    v = elem.get(name)
    if v is None:
        low = name.lower()
        for k, val in elem.attrib.items():
            if k.lower() == low:
                return val
    return v


def _is_ix_ns(ns):
    return ns.startswith("http://www.xbrl.org/") and ns.endswith("/inlineXBRL")


def _kind(elem, xml_mode):
    """('ix', local_lower) for inline XBRL elements, ('html', local_lower) for others, None for non-elements."""
    tag = elem.tag
    if not isinstance(tag, str):
        return None
    if tag.startswith("{"):
        ns, local = tag[1:].split("}", 1)
        return ("ix" if _is_ix_ns(ns) else "html", local.lower())
    if not xml_mode and ":" in tag:
        # fallback parser: the namespace is lost and the prefix stays in the tag name
        return ("ix", tag.rsplit(":", 1)[1].lower())
    return ("html", tag.lower())


def _load(path):
    """(root, parser_name). Strict XML first; any XML syntax error falls back to the HTML parser."""
    try:
        parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True, remove_comments=True)
        return etree.parse(str(path), parser).getroot(), "xml"
    except etree.XMLSyntaxError:
        parser = lxml_html.HTMLParser(huge_tree=True, remove_comments=True)
        root = lxml_html.parse(str(path), parser=parser).getroot()
        if root is None:
            raise InlineError(f"{path}: not readable as XML or HTML")
        return root, "html"


def parse_inline(path, accession=None):
    path = Path(path)
    if accession is None:
        accession = dashed_accession(path.stem)
    root, parser_name = _load(path)
    try:
        return _extract(root, accession, parser_name == "xml", parser_name)
    finally:
        del root
        gc.collect()


def _extract(root, accession, xml_mode, parser_name):
    facts, footnotes, relationships, tables, trs, linkers = [], [], [], [], [], []
    for elem in root.iter():
        k = _kind(elem, xml_mode)
        if k is None:
            continue
        source, local = k
        style = _attr(elem, "style")
        if style and "-sec-ix-hidden" in style.lower():
            linkers.append((elem, style))
        if source == "html" and local in _BLOCKS:
            _separate_blocks(elem)
        if source == "ix":
            if local in _FACTS:
                facts.append(elem)
            elif local == "footnote":
                footnotes.append(elem)
            elif local == "relationship":
                relationships.append(elem)
        else:
            if local == "table":
                tables.append(elem)
            elif local == "tr":
                trs.append(elem)

    def locate(start, child):
        # nearest table, nearest row below that table, the child of the row that holds the start element
        hidden = False
        table = row = cell = None
        p = start
        while p is not None:
            pk = _kind(p, xml_mode)
            if pk is not None:
                if pk[0] == "ix" and pk[1] == "hidden":
                    hidden = True
                if pk[0] == "html" and table is None:
                    if pk[1] == "table":
                        table = p
                    elif pk[1] == "tr" and row is None:
                        row, cell = p, child
            child = p
            p = p.getparent()
        return hidden, table, row, cell

    # Locate every fact
    located = []
    kept = set()
    for f in facts:
        hidden, table, row, cell = locate(f.getparent(), f)
        located.append((f, hidden, table, row, cell))
        if table is not None:
            kept.add(table)

    # Printed elements that point at a hidden fact (style "-sec-ix-hidden:<fact id>"): first in document order
    # among those inside a table; their table counts as kept
    link_at = {}
    for elem, style in linkers:
        _, table, row, cell = locate(elem, None)
        if table is None:
            continue
        kept.add(table)
        for fid in _HIDDEN_LINK.findall(style):
            link_at.setdefault(fid, (row, cell))

    # Rows of kept tables, in document order
    table_index = {}
    for t in tables:
        if t in kept:
            table_index[t] = len(table_index)
    row_info = {}  # tr element -> (row_index, cell element list)
    doc_rows = []
    in_table_counter = {}
    for tr in trs:
        p = tr.getparent()
        t = None
        while p is not None:
            pk = _kind(p, xml_mode)
            if pk is not None and pk[0] == "html" and pk[1] == "table":
                t = p
                break
            p = p.getparent()
        if t is None or t not in table_index:
            continue
        n = in_table_counter.get(t, 0)
        in_table_counter[t] = n + 1
        cell_elems = [c for c in tr if _kind(c, xml_mode) in (("html", "td"), ("html", "th"))]
        row_info[tr] = (len(doc_rows), cell_elems)
        doc_rows.append([
            table_index[t], n, [_text(c) for c in cell_elems],
            [_span(c, "colspan") for c in cell_elems], [_span(c, "rowspan") for c in cell_elems], 0])

    # Placements
    placements = []
    seen = {}
    dup = []
    for i, (f, hidden, table, row, cell) in enumerate(located):
        fid = _attr(f, "id")
        if fid is None:
            fid = f"noid-html:{i}"
        if fid in seen:
            dup.append(fid)
        seen[fid] = i
        row_index = cell_index = None
        if row is not None and table is not None and row in row_info:
            row_index, cell_elems = row_info[row]
            doc_rows[row_index][5] += 1
            for ci, ce in enumerate(cell_elems):
                if ce is cell:
                    cell_index = ci
                    break
        disp = _text(f)[:TEXT_LIMIT]
        shown_row = shown_cell = None
        link = link_at.get(fid)
        if link is not None and link[0] in row_info:
            shown_row, link_cells = row_info[link[0]]
            for ci, ce in enumerate(link_cells):
                if ce is link[1]:
                    shown_cell = ci
                    break
        placements.append((
            accession, fid, i, _FACTS[_kind(f, xml_mode)[1]], _attr(f, "name"), _attr(f, "contextRef"),
            row_index, cell_index, disp, _attr(f, "scale"), _attr(f, "sign"), _attr(f, "format"), hidden,
            shown_row, shown_cell))
    if dup:
        uniq = sorted(set(dup))
        raise InlineError(
            f"{accession}: {len(uniq)} fact id(s) occur more than once in the document: "
            + ", ".join(uniq[:5]))

    row_rows = [
        (accession, i, ti, rin, len(cells), cells, cs, rs, fc)
        for i, (ti, rin, cells, cs, rs, fc) in enumerate(doc_rows)]

    # Footnotes
    fn_rows, fn_ids, fn_dup = [], set(), []
    for j, e in enumerate(footnotes):
        fid = _attr(e, "id")
        if fid is None:
            fid = f"noid-html-fn:{j}"
        if fid in fn_ids:
            fn_dup.append(fid)
        fn_ids.add(fid)
        full = _text(e)
        fn_rows.append((accession, fid, full[:TEXT_LIMIT], len(full), hashlib.sha256(full.encode("utf-8")).hexdigest()))
    if fn_dup:
        uniq = sorted(set(fn_dup))
        raise InlineError(f"{accession}: {len(uniq)} footnote id(s) occur more than once: " + ", ".join(uniq[:5]))

    pairs = []
    arcs_total = 0
    for e in relationships:
        arcs_total += 1
        arc = _attr(e, "arcrole") or ""
        if not arc.endswith("fact-footnote"):
            continue
        froms = (_attr(e, "fromRefs") or "").split()
        tos = (_attr(e, "toRefs") or "").split()
        for a in froms:
            for b in tos:
                pairs.append((accession, a, b))

    stats = [
        ("placements", len(placements)),
        ("kept_tables", len(table_index)),
        ("tables_total", len(tables)),
        ("placements_in_rows", sum(1 for p in placements if p[6] is not None)),
        ("relationships_total", arcs_total),
    ]
    return {
        "document_row": row_rows,
        "fact_placement": placements,
        "footnote": fn_rows,
        "fact_footnote": pairs,
        "html_parser": parser_name,
        "stats": stats,
    }
