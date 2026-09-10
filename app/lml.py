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


########################################################################
### TABLE STRUCTURE CHECK
###
### Every table in these books is an <informaltable> with the same
### number of columns in every row (interns don't merge cells). This
### walks each <informaltable> region and reports:
###   * a missing </informaltable>
###   * no rows, or a row with no cells
###   * rows whose column counts don't all match
###   * a <tr> or a cell with a missing or doubled closing tag, or a
###     cell closed by the wrong tag (<th> ended with </td>)
########################################################################

_TABLE_TAG = "informaltable"
_ROW_TAG = "tr"
_CELL_TAGS = frozenset({"td", "th"})


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def check_tables(text):
    """Return a list of {"line": int|None, "message": str} findings for
    every <informaltable> in `text`. Empty list == no table problems (or
    no tables)."""
    findings = []
    stack = []   # open <informaltable> contexts, innermost last

    def add(line, message):
        findings.append({"line": line, "message": message})

    for match in _TAG_RE.finditer(text):
        name = match.group(2).lower()
        is_close = match.group(1) == "/"
        is_self = match.group(4) == "/" and not is_close
        line = _line_of(text, match.start())

        if name == _TABLE_TAG:
            if is_self:
                continue
            if is_close:
                if stack:
                    _finalize_table(stack.pop(), add)
                else:
                    add(line, "</informaltable> with no opening tag.")
            else:
                stack.append({"line": line, "rows": [], "row": None})
            continue

        if not stack:
            continue                      # tags outside any table: not our job here
        table = stack[-1]

        if name == _ROW_TAG:
            if is_self:
                continue
            if is_close:
                if table["row"] is None:
                    add(line, "</tr> with no matching <tr>.")
                else:
                    table["rows"].append(table["row"])
                    table["row"] = None
            else:
                if table["row"] is not None:
                    _close_dangling_row(table, add)
                table["row"] = {"line": line, "cells": 0, "open_cell": None}
            continue

        if name in _CELL_TAGS:
            if is_self:
                continue
            row = table["row"]
            if row is None:
                add(line, f"<{name}> outside any <tr>.")
                continue
            if is_close:
                if row["open_cell"] is None:
                    add(line, f"</{name}> with no matching open cell.")
                elif row["open_cell"] != name:
                    add(line, f"</{name}> closes a <{row['open_cell']}> cell.")
                    row["open_cell"] = None
                else:
                    row["open_cell"] = None
            else:
                if row["open_cell"] is not None:
                    add(line, f"<{row['open_cell']}> (line {row['line']}) "
                              f"has no closing tag before the next cell.")
                row["open_cell"] = name
                row["cells"] += 1
            continue

    for table in stack:                  # never closed
        add(table["line"],
            f"<informaltable> (line {table['line']}) has no </informaltable>.")
        _finalize_table(table, add)

    findings.sort(key=lambda f: f["line"] or 0)
    return findings


def _close_dangling_row(table, add):
    row = table["row"]
    add(row["line"], f"<tr> (line {row['line']}) has no </tr>.")
    if row["open_cell"] is not None:
        add(row["line"], f"<{row['open_cell']}> in that row has no closing tag.")
    table["rows"].append(row)
    table["row"] = None


def _finalize_table(table, add):
    if table["row"] is not None:
        _close_dangling_row(table, add)

    if not table["rows"]:
        add(table["line"],
            f"<informaltable> (line {table['line']}) has no rows.")
        return

    for row in table["rows"]:
        if row["cells"] == 0:
            add(row["line"], f"Row at line {row['line']} has no cells.")

    counts = {row["cells"] for row in table["rows"] if row["cells"] > 0}
    if len(counts) > 1:
        detail = ", ".join(
            f"line {row['line']}: {row['cells']}"
            for row in table["rows"] if row["cells"] > 0
        )
        add(table["line"],
            f"Rows have different column counts ({detail}). Every row in "
            f"these tables should have the same number of columns.")
