########################################################################
### LML -- "lying markup language": the pseudo-DocBook that Paligo's
### source view shows and accepts. It is NOT real DocBook 5 (see
### docs/paligo-source-view.md), so we can't just hand it to a schema.
###
### This module does the smallest useful first check: for the elements
### we actually see in these books, does every opening tag have a
### closing tag and vice versa? It does NOT check content models or
### nesting order yet -- one independent stack per element name, pure
### open/close balance. Unmatched tags are marked; nothing is edited.
########################################################################
import re

from markupsafe import escape

### the vocabulary from docs/paligo-source-view.md. Tags outside this
### set are ignored for now (a later pass can flag unknowns).
KNOWN_TAGS = frozenset({
    "section", "title", "para",
    "orderedlist", "itemizedlist", "listitem",
    "informaltable", "thead", "tbody", "tr", "th", "td",
    "mediaobject", "imageobject",
    "emphasis", "guilabel",
})

### <name ...>, </name>, or <name .../>. Deliberately loose -- we only
### need the element name and whether the tag opens or closes. A literal
### '>' inside a quoted attribute value would fool this; vanishingly
### rare in this content, and a job for a real tokenizer later.
_TAG_RE = re.compile(r"<\s*(/?)\s*([A-Za-z][\w.-]*)([^<>]*?)(/?)\s*>")


def check_tags(text):
    """Pair opening and closing tags of known elements in `text`.

    Returns (html, unmatched_count):
      * html  -- `text`, HTML-escaped for display, with every unmatched
                 tag wrapped in <span class="lml-bad">...</span>. Order
                 and surrounding text are otherwise untouched.
      * unmatched_count -- how many tags had no partner.

    Nesting/order between different elements is deliberately ignored: a
    closing tag matches the most recent still-open tag of the SAME name,
    regardless of what else is open.
    """
    entries = []        # every known-element tag, in document order
    open_stacks = {}     # name -> [opener entries not yet closed]

    for match in _TAG_RE.finditer(text):
        name = match.group(2).lower()
        if name not in KNOWN_TAGS:
            continue
        is_close = match.group(1) == "/"
        is_self_close = match.group(4) == "/" and not is_close
        if is_self_close:
            continue     # <foo/> balances itself

        entry = {"start": match.start(), "end": match.end(), "bad": False}
        entries.append(entry)

        if is_close:
            stack = open_stacks.get(name)
            if stack:
                stack.pop()             # closes the most recent opener
            else:
                entry["bad"] = True      # closing tag with nothing open
        else:
            open_stacks.setdefault(name, []).append(entry)

    for stack in open_stacks.values():
        for entry in stack:
            entry["bad"] = True          # opener that never closed

    unmatched_count = sum(1 for e in entries if e["bad"])

    parts = []
    cursor = 0
    for entry in entries:
        if not entry["bad"]:
            continue
        parts.append(str(escape(text[cursor:entry["start"]])))
        parts.append('<span class="lml-bad">')
        parts.append(str(escape(text[entry["start"]:entry["end"]])))
        parts.append("</span>")
        cursor = entry["end"]
    parts.append(str(escape(text[cursor:])))

    return "".join(parts), unmatched_count
