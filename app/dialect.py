########################################################################
### DIALECT -- translate tags that mean the same thing as one of
### Paligo's own, but aren't: HTML lists (ul/ol/li), CALS tables
### (tgroup/row/entry), HTML bold/italic (b/strong, i/em). This is what
### happens to a topic that gets "fixed" by round-tripping through an
### AI chat -- the structure survives but the tags come back generic.
###
### Runs as a pass BEFORE app/lml.py's structural checks, so Check XML
### catches this failure mode too, not just Extract-pasted-in-the-
### wrong-spot. Reuses app/paligo.py's real (lxml-based) converters, but
### only on the exact foreign span found in the text -- spliced back in
### place, never by reparsing/reformatting the whole document. Anything
### already in Paligo's own dialect (orderedlist/itemizedlist/listitem,
### informaltable/table with tr/td/th) is left completely alone; Check
### XML's own checks are what look at those.
########################################################################
import re

from app.fixes import _indent_of
from app.paligo import _Bail, _drop_comments, _norm_list, _norm_table, _parse, _strip_namespaces
from app.docbook import _serialize

_TAG_RE = re.compile(r"<\s*(/?)\s*([A-Za-z][\w.-]*)([^<>]*?)(/?)\s*>")
_BOLD_TAGS = {"b", "strong"}
_ITALIC_TAGS = {"i", "em"}
_INLINE_TAGS = _BOLD_TAGS | _ITALIC_TAGS


def translate(text):
    """-> (output, translated, problems).

    translated: list[str], one line per successful translation (for a
    quiet "translated N things" note) -- empty if nothing foreign found.
    problems: list[{"line", "message"}], one per foreign-looking spot
    that couldn't be translated automatically -- ready to merge straight
    into Check XML's findings.
    """
    translated = []
    problems = []

    text, n = _rename_inline(text)
    if n:
        translated.append(f"Translated {n} bold/italic tag{'s' if n != 1 else ''} to <emphasis>.")

    text = _convert_spans(text, {"ul", "ol"}, _convert_list, translated, problems)
    text = _convert_spans(text, {"table", "informaltable"}, _convert_cals_table, translated, problems,
                           only_if=lambda snippet: "<tgroup" in snippet)

    return text, translated, problems


########################################################################
### INLINE BOLD / ITALIC -- pure tag rename, no restructuring, safe
### anywhere at any depth.

def _rename_inline(text):
    count = 0

    def repl(m):
        nonlocal count
        is_close, name, is_self = m.group(1), m.group(2).lower(), m.group(4)
        if name not in _INLINE_TAGS:
            return m.group(0)
        count += 1
        if is_self and not is_close:
            return ""  # empty <b/> etc. -- meaningless, drop it
        if is_close:
            return "</emphasis>"
        return '<emphasis role="strong">' if name in _BOLD_TAGS else "<emphasis>"

    return _TAG_RE.sub(repl, text), count


########################################################################
### LISTS / TABLES -- locate the exact span of each foreign element,
### convert just that snippet with paligo.py's real converters, and
### splice the (reindented) result back in place.

def _find_top_level_spans(text, open_names):
    """(start, end) of each maximal run of nested `open_names` tags --
    an outer tag and everything nested inside it, even a different tag
    from the same set. Self-closed tags and stray closes are ignored."""
    spans = []
    depth = 0
    span_start = None
    for m in _TAG_RE.finditer(text):
        if m.group(2).lower() not in open_names:
            continue
        is_close = m.group(1) == "/"
        is_self = m.group(4) == "/" and not is_close
        if is_self:
            continue
        if not is_close:
            if depth == 0:
                span_start = m.start()
            depth += 1
        elif depth > 0:
            depth -= 1
            if depth == 0 and span_start is not None:
                spans.append((span_start, m.end()))
                span_start = None
    return spans


def _convert_spans(text, open_names, converter, translated, problems, only_if=None):
    spans = _find_top_level_spans(text, open_names)
    if only_if:
        spans = [(s, e) for s, e in spans if only_if(text[s:e])]
    for start, end in reversed(spans):  # back-to-front: earlier offsets stay valid
        replacement, note = converter(text[start:end])
        if replacement is None:
            problems.append({"line": text.count("\n", 0, start) + 1, "message": note})
            continue
        indent = _indent_of(text, start)
        text = text[:start] + replacement.replace("\n", "\n" + indent) + text[end:]
        translated.append(note)
    return text


def _parse_snippet(snippet, wanted_tags):
    try:
        root = _parse(snippet)
    except _Bail:
        return None
    _strip_namespaces(root)
    _drop_comments(root)
    kids = [k for k in root if isinstance(k.tag, str)]
    if len(kids) != 1 or kids[0].tag not in wanted_tags:
        return None
    return kids[0]


def _convert_list(snippet):
    el = _parse_snippet(snippet, {"ul", "ol"})
    if el is None:
        return None, "Couldn't parse a foreign list -- check for unclosed or mismatched tags."
    try:
        out = _norm_list(el)
    except _Bail as e:
        return None, f"Couldn't translate a <{el.tag}> automatically: {e}"
    return _serialize(out), f"Translated a <{el.tag}> list to <{out.tag}>."


def _convert_cals_table(snippet):
    el = _parse_snippet(snippet, {"table", "informaltable"})
    if el is None:
        return None, "Couldn't parse a foreign table -- check for unclosed or mismatched tags."
    try:
        out = _norm_table(el)
    except _Bail as e:
        return None, f"Couldn't translate a CALS table automatically: {e}"
    return "\n".join(_serialize(e) for e in out), "Translated a CALS table to Paligo's table markup."
