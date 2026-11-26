"""Text slice R fix round 1: no int_text_* model depends, directly or through any chain of models, on production's
holdings (stg_holdings) or on a comparison model (cmp_*). Bundles and checks must be built from the filed layer and the
tags before corrections; the correction models reach stg_holdings, so they are excluded too by this test.

The graph is read from the SQL files, not from a dbt manifest (none is needed): a model depends on every ref('x') in
its file and in every macro of macros/ it calls, recursively. A macro is "called" when its name appears as
"name(" inside a Jinja expression or statement of the file.
"""
import re
from pathlib import Path

WAREHOUSE = Path(__file__).resolve().parent.parent
REF = re.compile(r"""ref\(\s*['"]([A-Za-z0-9_]+)['"]\s*\)""")
MACRO_DEF = re.compile(r"""\{%-?\s*macro\s+([A-Za-z0-9_]+)\s*\(""")
JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(")
FORBIDDEN = re.compile(r"^(stg_holdings|cmp_.*)$")


def _macros():
    """macro name -> body text."""
    bodies = {}
    for path in (WAREHOUSE / "macros").glob("*.sql"):
        text = path.read_text(encoding="utf-8")
        starts = [(m.group(1), m.start()) for m in MACRO_DEF.finditer(text)]
        for i, (name, start) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
            bodies[name] = text[start:end]
    return bodies


def _refs(text, macros, seen=None):
    seen = set() if seen is None else seen
    refs = set(REF.findall(text))
    for block in JINJA.findall(text):
        for name in CALL.findall(block):
            if name in macros and name not in seen:
                seen.add(name)
                refs |= _refs(macros[name], macros, seen)
    return refs


def _graph():
    macros = _macros()
    graph = {}
    for path in (WAREHOUSE / "models").rglob("*.sql"):
        graph[path.stem] = _refs(path.read_text(encoding="utf-8"), macros)
    return graph


def _ancestors(graph, node):
    out, stack = set(), [node]
    while stack:
        for parent in graph.get(stack.pop(), ()):
            if parent not in out:
                out.add(parent)
                stack.append(parent)
    return out


def test_text_models_found():
    assert any(name.startswith("int_text_") for name in _graph())


def test_no_text_model_reads_production():
    graph = _graph()
    bad = {}
    for name in sorted(graph):
        if name.startswith("int_text_"):
            hits = sorted(a for a in _ancestors(graph, name) if FORBIDDEN.match(a))
            if hits:
                bad[name] = hits
    assert bad == {}, "int_text_* models depending on production or comparison models: %r" % bad


def test_detector_sees_a_known_dependency():
    """Guard against a detector that sees nothing: cmp_rate reads stg_holdings."""
    graph = _graph()
    assert "stg_holdings" in _ancestors(graph, "cmp_rate")
