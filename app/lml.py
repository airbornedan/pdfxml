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
import json
import re
from pathlib import Path

from markupsafe import escape

### Supported Paligo source-view tags for this checker.
### The runtime vocabulary is loaded from the checked-in JSON rules file,
### with an explicit fallback so the validator still behaves predictably
### if the rules file is missing or malformed.
RULES_PATH = Path(__file__).resolve().parents[1] / "docs" / "xml_snippets" / "lml_rules.json"

_FALLBACK_TAGS = frozenset({
    # structure
    "section", "title", "para",
    "orderedlist", "itemizedlist", "listitem",
    "informaltable", "thead", "tbody", "tr", "th", "td",
    "colgroup", "col",
    # media / image
    "mediaobject", "imageobject", "imagedata", "informalfigure",
    "fileref",
    # inline / references
    "emphasis", "guilabel", "xref", "indexterm",
    # admonitions
    "note", "warning", "caution",
})


def _load_rules_file():
    """Load the JSON rules file, returning a dict with a fallback.

    The JSON file is now the machine-readable rule catalog that can be
    extended without editing code for simple vocabulary updates.
    """
    if not RULES_PATH.exists():
        return {"tags": {"fallback": list(_FALLBACK_TAGS)}}

    try:
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"tags": {"fallback": list(_FALLBACK_TAGS)}}

    return data


RULES = _load_rules_file()


def _load_known_tags():
    tags = set()
    for group in RULES.get("tags", {}).values():
        if isinstance(group, list):
            tags.update(str(tag).lower() for tag in group)
    return frozenset(tags or _FALLBACK_TAGS)


KNOWN_TAGS = _load_known_tags()

### <name ...>, </name>, or <name .../>. Deliberately loose -- we only
### need the element name and whether the tag opens or closes. A literal
### '>' inside a quoted attribute value would fool this; vanishingly
### rare in this content, and a job for a real tokenizer later.
_TAG_RE = re.compile(r"<\s*(/?)\s*([A-Za-z][\w.-]*)([^<>]*?)(/?)\s*>")


def highlight_findings(html, findings):
    """Wrap only the offending tags for structural findings.

    The returned `html` is already escaped for display, so this looks for
    the escaped tag text on the affected line and wraps just that tag.
    """
    if not html or not findings:
        return html

    tags_by_line = {}
    for finding in findings:
        line = finding.get("line")
        tag = finding.get("tag")
        if line is None or not tag:
            continue
        tags_by_line.setdefault(line, set()).add(tag.lower())

    if not tags_by_line:
        return html

    lines = html.splitlines(keepends=True)
    parts = []
    for idx, line in enumerate(lines, start=1):
        tags = tags_by_line.get(idx)
        if not tags:
            parts.append(line)
            continue

        pattern = re.compile(r"&lt;(/?)([A-Za-z][\w.-]*)([^&]*?)&gt;")

        def _wrap(match):
            name = match.group(2).lower()
            if name in tags:
                return f'<span class="lml-bad">{match.group(0)}</span>'
            return match.group(0)

        parts.append(pattern.sub(_wrap, line))

    return "".join(parts)


def strip_xinfo_attrs(text):
    """Return `text` with xinfo attributes stripped except on the first
    <section> tag, which is preserved as-is.
    """
    parts = []
    last_end = 0
    first_section = True

    for match in _TAG_RE.finditer(text):
        name = match.group(2).lower()
        attrs = match.group(3) or ""
        is_close = match.group(1) == "/"
        is_self = match.group(4) == "/" and not is_close

        if name == "section" and not is_close and not is_self and first_section:
            first_section = False
            parts.append(text[last_end:match.end()])
            last_end = match.end()
            continue

        if attrs:
            stripped_attrs = re.sub(
                r"\s+xinfo:[A-Za-z0-9_.-]+\s*=\s*(?:\"[^\"]*\"|'[^']*')",
                "",
                attrs,
            )
            if stripped_attrs != attrs:
                parts.append(text[last_end:match.start()])
                parts.append(
                    f"<{match.group(1) if match.group(1) else ''}{name}{stripped_attrs}{match.group(4) or ''}>"
                )
                last_end = match.end()
                continue

        parts.append(text[last_end:match.start()])
        parts.append(match.group(0))
        last_end = match.end()

    parts.append(text[last_end:])
    return "".join(parts)


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
    seen = set()
    stack = []   # open <informaltable> contexts, innermost last

    def add(line, message, tag=None):
        key = (line, message, tag)
        if key in seen:
            return
        seen.add(key)
        finding = {"line": line, "message": message}
        if tag is not None:
            finding["tag"] = tag
        findings.append(finding)

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
                    add(line, "</informaltable> with no opening tag.", tag="informaltable")
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
                    add(line, f"</{name}> with no matching open cell.", tag=name)
                elif row["open_cell"] != name:
                    add(line, f"</{name}> closes a <{row['open_cell']}> cell.", tag=name)
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

        if table["row"] is not None:
            row = table["row"]
            if row["cells"] == 0:
                add(line, "Content appears before the first <td> or <th> inside a row; move it into a cell.", tag=name)
            elif row["open_cell"] is None:
                add(line, "Content appears after the last <td> or <th> inside a row; move it into a cell.", tag=name)

        if table["row"] is not None:
            row = table["row"]
            if row["cells"] == 0:
                add(line, "Content appears before the first <td> or <th> inside a row; move it into a cell.", tag=name)
            elif row["open_cell"] is None:
                add(line, "Content appears after the last <td> or <th> inside a row; move it into a cell.", tag=name)

    for table in stack:                  # never closed
        add(table["line"],
            f"<informaltable> (line {table['line']}) has no </informaltable>.", tag="informaltable")
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


########################################################################
### LIST STRUCTURE CHECK
###
### <orderedlist> / <itemizedlist> rules for these books:
###   * the list has a closing tag and holds at least one <listitem>
###   * every <listitem> has exactly one </listitem>
###   * nothing sits directly in the list except <listitem> -- every
###     <para>, <mediaobject>, sublist, or stray text between the items
###     must be inside a <listitem>
###   * every <listitem> has real content: a <para>, a <mediaobject>,
###     or a nested list (sublists are allowed)
########################################################################

_LIST_TAGS = frozenset({"orderedlist", "itemizedlist"})
_ITEM_TAG = "listitem"
### what makes a <listitem> "have content"
_LI_CONTENT = frozenset({"para", "mediaobject", "orderedlist", "itemizedlist"})


def check_mediaobjects(text):
    """Return findings for mediaobject/imageobject/imagedata structure.

    This supplements the tag-pair check with the LML rules we explicitly
    use for Paligo source-view snippets: every <imageobject> should be
    inside a <mediaobject>, and every <mediaobject> should contain at
    least one <imageobject> plus an <imagedata> element. The rules are
    intentionally targeted to the snippets this app accepts.
    """
    findings = []
    seen = set()
    stack = []

    def add(line, message, tag=None):
        key = (line, message, tag)
        if key in seen:
            return
        seen.add(key)
        finding = {"line": line, "message": message}
        if tag is not None:
            finding["tag"] = tag
        findings.append(finding)

    for match in _TAG_RE.finditer(text):
        name = match.group(2).lower()
        attrs = match.group(3) or ""
        is_close = match.group(1) == "/"
        is_self = match.group(4) == "/" and not is_close
        line = _line_of(text, match.start())

        if name == "mediaobject":
            if is_self:
                add(line, "<mediaobject/> is not valid here; use a full <mediaobject>...</mediaobject> block.", tag="mediaobject")
                continue
            if is_close:
                if not stack:
                    add(line, "</mediaobject> with no matching <mediaobject>.", tag="mediaobject")
                    continue
                frame = stack.pop()
                if frame["imageobject_count"] == 0:
                    add(frame["line"], "<mediaobject> must contain at least one <imageobject>.", tag="mediaobject")
                if frame["imageobject_count"] > 0 and frame["imagedata_count"] == 0:
                    add(frame["line"], "<mediaobject> contains <imageobject> but no <imagedata>.", tag="imageobject")
                continue
            stack.append({"line": line, "imageobject_count": 0, "imagedata_count": 0})
            continue

        if name == "imageobject":
            if is_self:
                if stack:
                    stack[-1]["imageobject_count"] += 1
                else:
                    add(line, "<imageobject/> must be inside a <mediaobject>.", tag="imageobject")
                continue
            if is_close:
                continue
            if stack:
                stack[-1]["imageobject_count"] += 1
            else:
                add(line, "<imageobject> must be inside a <mediaobject>.", tag="imageobject")
            continue

        if name == "imagedata":
            if is_self:
                if stack:
                    stack[-1]["imagedata_count"] += 1   # self-closed is the normal form
                    if not re.search(r"\bfileref\b", attrs, flags=re.IGNORECASE):
                        add(line, "<imagedata> is missing the required fileref attribute.", tag="imagedata")
                else:
                    add(line, "<imagedata> must be inside a <mediaobject>.", tag="imagedata")
                continue
            if is_close:
                continue
            if stack:
                if not re.search(r"\bfileref\b", attrs, flags=re.IGNORECASE):
                    add(line, "<imagedata> is missing the required fileref attribute.", tag="imagedata")
                stack[-1]["imagedata_count"] += 1
            else:
                add(line, "<imagedata> must be inside a <mediaobject>.", tag="imagedata")
            continue

    findings.sort(key=lambda f: f["line"] or 0)
    return findings


def check_sections(text):
    """Report section-level structural issues from the LML rules.

    The checker intentionally keeps the output focused on the actionable
    issues that interns are likely to hit when pasting Paligo source-view
    fragments into this app: missing or misplaced section titles and
    content that appears after a nested section starts.
    """
    findings = []
    stack = []

    for match in _TAG_RE.finditer(text):
        name = match.group(2).lower()
        is_close = match.group(1) == "/"
        is_self = match.group(4) == "/" and not is_close
        line = _line_of(text, match.start())

        if name == "section":
            if is_self:
                continue
            if not is_close:
                stack.append({
                    "line": line,
                    "nested": False,
                    "reported": False,
                    "title_count": 0,
                    "title_lines": [],
                    "first_child": None,
                })
                if stack[:-1]:
                    stack[-2]["nested"] = True
            else:
                if stack:
                    frame = stack.pop()
                    if frame["title_count"] == 0:
                        findings.append({
                            "line": frame["line"],
                            "tag": "title",
                            "message": "<section> is missing a <title>.",
                        })
                    if frame["first_child"] is not None and frame["first_child"] != "title":
                        findings.append({
                            "line": frame["line"],
                            "tag": frame["first_child"],
                            "message": "<section> must start with a <title>.",
                        })
                    for extra_title_line in frame["title_lines"][1:]:
                        findings.append({
                            "line": extra_title_line,
                            "tag": "title",
                            "message": "<section> has more than one <title>; keep exactly one.",
                        })
            continue

        if not stack:
            continue

        frame = stack[-1]

        if name == "title":
            if not is_close:
                frame["title_count"] += 1
                frame["title_lines"].append(line)
                if frame["first_child"] is None:
                    frame["first_child"] = "title"
            continue

        if frame["first_child"] is None:
            frame["first_child"] = name

        if len(stack) == 1 and frame["nested"] and not frame["reported"]:
            findings.append({
                "line": line,
                "tag": name,
                "message": (
                    f"<{name}> appears after a nested <section>; move it "
                    f"into its own nested <section> or place it before the first subsection."
                ),
            })
            frame["reported"] = True

    findings.sort(key=lambda f: f["line"] or 0)
    return findings


def check_lists(text):
    """Return a list of {"line": int, "message": str} findings for every
    <orderedlist>/<itemizedlist> in `text`. Empty == no problems (or no
    lists). A lenient nested walk: a closing tag unwinds to the nearest
    open element of the same name, and a new <listitem> implicitly
    closes anything still open inside the previous one."""
    findings = []
    stack = []          # {"tag","line","kind": "list"|"li"|"other", ...}
    last_end = 0

    def add(line, message, tag=None):
        finding = {"line": line, "message": message}
        if tag is not None:
            finding["tag"] = tag
        findings.append(finding)

    def finalize(frame, dangling=False):
        if frame["kind"] == "li":
            if dangling:
                add(frame["line"],
                    f"<listitem> (line {frame['line']}) has no </listitem>.", tag="listitem")
            if not frame["content"]:
                add(frame["line"],
                    f"<listitem> (line {frame['line']}) has no content -- it "
                    f"needs a <para>, a <mediaobject>, or a nested list.", tag="listitem")
        elif frame["kind"] == "list":
            if dangling:
                add(frame["line"],
                    f"<{frame['tag']}> (line {frame['line']}) has no closing tag.", tag=frame["tag"])
            if frame["items"] == 0:
                add(frame["line"],
                    f"<{frame['tag']}> (line {frame['line']}) has no "
                    f"<listitem> elements.", tag=frame["tag"])
        # a dangling "other" element is a tag-balance problem, reported by
        # check_tags -- not repeated here

    def note_content(name):
        """Register `name` as content of the nearest enclosing <listitem>,
        unless a list sits between here and it."""
        for frame in reversed(stack):
            if frame["kind"] == "li":
                frame["content"].add(name)
                return
            if frame["kind"] == "list":
                return

    def in_mediaobject():
        """True when the nearest enclosing block is a <mediaobject>."""
        for frame in reversed(stack):
            if frame["kind"] == "list":
                return False
            if frame["tag"] == "mediaobject":
                return True
        return False

    for match in _TAG_RE.finditer(text):
        name = match.group(2).lower()
        is_close = match.group(1) == "/"
        is_self = match.group(4) == "/" and not is_close
        start, end = match.start(), match.end()
        line = _line_of(text, start)
        cont = stack[-1] if stack else None

        if text[last_end:start].strip() and cont and cont["kind"] == "list":
            add(_line_of(text, last_end),
                "Text sits directly inside a list; it must be in a <listitem>.")
        last_end = end

        kind = ("list" if name in _LIST_TAGS
                else "li" if name == _ITEM_TAG
                else "other")

        if is_self:
            if kind == "li":
                if cont and cont["kind"] == "list":
                    cont["items"] += 1
                add(line, f"<listitem/> (line {line}) is empty; it needs content.")
            elif kind == "other":
                if cont and cont["kind"] == "list":
                    add(line, f"<{name}/> sits directly inside a list; it must "
                              f"be inside a <listitem>.", tag=name)
                elif name == "imageobject" and not in_mediaobject():
                    add(line, f"<{name}/> must be inside a <mediaobject>.", tag=name)
                elif name == "mediaobject":
                    note_content("mediaobject")
            continue

        if not is_close:                       # opening tag
            if kind == "list":
                if cont and cont["kind"] == "list":
                    add(line, "A sublist sits directly inside a list; it must "
                              "be inside a <listitem>.", tag=name)
                elif cont and cont["kind"] == "li":
                    cont["content"].add("list")
                stack.append({"tag": name, "line": line, "kind": "list",
                              "items": 0})
            elif kind == "li":
                while stack and stack[-1]["kind"] != "list":
                    finalize(stack.pop(), dangling=True)   # implicit close
                cont = stack[-1] if stack else None
                if not cont or cont["kind"] != "list":
                    add(line, "<listitem> outside any list.", tag="listitem")
                else:
                    cont["items"] += 1
                stack.append({"tag": name, "line": line, "kind": "li",
                              "content": set()})
            else:                              # other element
                if cont and cont["kind"] == "list":
                    add(line, f"<{name}> sits directly inside a list; it must "
                              f"be inside a <listitem>.", tag=name)
                elif name == "imageobject" and not in_mediaobject():
                    add(line, f"<{name}> must be inside a <mediaobject>.", tag=name)
                elif name in ("para", "mediaobject"):
                    note_content(name)
                stack.append({"tag": name, "line": line, "kind": "other"})
            continue

        # closing tag -- unwind to the matching name
        depth = next((i for i in range(len(stack) - 1, -1, -1)
                      if stack[i]["tag"] == name), None)
        if depth is None:
            if kind == "li":
                add(line, "</listitem> with no matching <listitem>.")
            elif kind == "list":
                add(line, f"</{name}> with no matching opening tag.", tag=name)
            continue
        for frame in stack[depth + 1:]:
            finalize(frame, dangling=True)
        closed = stack[depth]
        del stack[depth:]
        finalize(closed, dangling=False)

    for frame in reversed(stack):
        finalize(frame, dangling=True)

    findings.sort(key=lambda f: f["line"] or 0)
    return findings
