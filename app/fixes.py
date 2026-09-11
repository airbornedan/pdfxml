########################################################################
### FIXES -- candidate repairs for LML findings.
###
### Every fix is a pure structural edit (wrap / move / insert marker /
### remove an empty wrapper) and is offered only when it loses no word
### of the input -- the anti-Paligo guarantee. The intern picks by a
### plain label; nothing is applied automatically.
########################################################################
import re
from collections import Counter

_TAG = re.compile(r"<[^<>]*>")
_OPEN_TAG = re.compile(r"<\s*([A-Za-z][\w.-]*)([^<>]*?)(/?)\s*>")


def _words(text):
    """Whitespace-separated words with all tags removed -- the content a
    fix must not lose (order-independent)."""
    return sorted(_TAG.sub(" ", text).split())


def _guard(original, candidate):
    """True when every word of `original` survives in `candidate` with at
    least its original count. Additions (a placeholder title, wrapper
    tags) are allowed; losing a word is not."""
    have = Counter(_words(candidate))
    return all(have[word] >= count for word, count in Counter(_words(original)).items())


def _indent_of(text, pos):
    line_start = text.rfind("\n", 0, pos) + 1
    return re.match(r"[ \t]*", text[line_start:]).group(0)


def _element_span(text, start):
    """[start, end) of the element whose opening tag begins at `start`."""
    match = _OPEN_TAG.match(text, start)
    if not match:
        return start, start
    if match.group(3) == "/":
        return start, match.end()
    name = match.group(1)
    tag_re = re.compile(
        rf"<\s*(/?)\s*{re.escape(name)}(?:\s[^<>]*)?(/?)\s*>", re.IGNORECASE
    )
    depth = 0
    for tag in tag_re.finditer(text, start):
        if tag.group(2) == "/":
            continue                       # self-close: no nesting
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            return start, tag.end()
    return start, len(text)


def suggest_fixes(text, finding):
    """Return a list of {"label", "new_text"} options for the finding, or
    [] when there is no safe mechanical repair."""
    spec = finding.get("fix")
    builder = _BUILDERS.get(spec.get("kind")) if spec else None
    if builder is None:
        return []
    return [opt for opt in builder(text, finding) if _guard(text, opt["new_text"])]


# --- builders --------------------------------------------------------

def _loose_block_in_list(text, finding):
    spec = finding["fix"]
    el_start = spec["el_start"]
    _, el_end = _element_span(text, el_start)
    element = text[el_start:el_end]
    indent = _indent_of(text, el_start)

    line_start = text.rfind("\n", 0, el_start) + 1
    line_end = el_end + 1 if text[el_end:el_end + 1] == "\n" else el_end

    options = [{
        "label": "Make it its own list item",
        "new_text": (text[:line_start]
                     + f"{indent}<listitem>\n{indent}  {element}\n{indent}</listitem>\n"
                     + text[line_end:]),
    }]

    prev_close = text.rfind("</listitem>", spec["list_start"], el_start)
    if prev_close != -1:
        li_indent = _indent_of(text, prev_close)
        options.append({
            "label": "Add it to the item above",
            "new_text": (text[:prev_close] + f"{li_indent}  {element}\n"
                         + text[prev_close:line_start] + text[line_end:]),
        })

    end_tag = f"</{spec['list_tag']}>"
    list_close = text.find(end_tag, el_end)
    if list_close != -1:
        close_end = list_close + len(end_tag)
        list_indent = _indent_of(text, list_close)
        options.append({
            "label": "Move it out below the list",
            "new_text": (text[:line_start] + text[line_end:close_end]
                         + f"\n{list_indent}{element}" + text[close_end:]),
        })

    return options


def _delete_stray_close(text, finding):
    start, end = finding.get("start"), finding.get("end")
    if start is None or end is None:
        return []
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = line_end if line_end != -1 else len(text)

    if not text[line_start:start].strip() and not text[end:line_end].strip():
        cut_start, cut_end = line_start, min(line_end + 1, len(text))
    else:
        cut_start, cut_end = start, end

    return [{
        "label": "Delete this closing tag",
        "new_text": text[:cut_start] + text[cut_end:],
    }]


def _empty_listitem(text, finding):
    spec = finding["fix"]
    el_start, el_end = spec["el_start"], spec["el_end"]
    indent = _indent_of(text, el_start)
    options = []

    close_pos = text.rfind("</listitem>", el_start, el_end)
    if close_pos != -1:
        gap_start = close_pos
        while gap_start > el_start and text[gap_start - 1] in " \t\n":
            gap_start -= 1
        options.append({
            "label": "Add an empty paragraph",
            "new_text": (text[:gap_start]
                         + f"\n{indent}  <para></para>\n{indent}"
                         + text[close_pos:]),
        })

    line_start = text.rfind("\n", 0, el_start) + 1
    line_end = el_end + 1 if text[el_end:el_end + 1] == "\n" else el_end
    options.append({
        "label": "Delete the empty list item",
        "new_text": text[:line_start] + text[line_end:],
    })
    return options


def _wrap_in_mediaobject(text, finding):
    el_start = finding["fix"]["el_start"]
    _, el_end = _element_span(text, el_start)
    element = text[el_start:el_end].replace("\n", "\n  ")   # shift block right
    indent = _indent_of(text, el_start)
    line_start = text.rfind("\n", 0, el_start) + 1
    line_end = el_end + 1 if text[el_end:el_end + 1] == "\n" else el_end
    return [{
        "label": "Wrap it in a mediaobject",
        "new_text": (text[:line_start]
                     + f"{indent}<mediaobject>\n{indent}  {element}\n{indent}</mediaobject>\n"
                     + text[line_end:]),
    }]


def _bare_text_in_list(text, finding):
    spec = finding["fix"]
    seg_start, seg_end = spec["text_start"], spec["text_end"]
    segment = text[seg_start:seg_end]
    lead = len(segment) - len(segment.lstrip())
    trail = len(segment) - len(segment.rstrip())
    content = segment[lead:len(segment) - trail]
    if not content:
        return []
    return [{
        "label": "Wrap it in a list item",
        "new_text": (text[:seg_start + lead]
                     + f"<listitem><para>{content}</para></listitem>"
                     + text[seg_end - trail:]),
    }]


_SECTION_TAG = re.compile(r"<\s*(/?)\s*section(?:\s[^<>]*)?(/?)\s*>", re.IGNORECASE)


def _section_bounds(text, open_start):
    """From the offset of a <section> opening tag, return
    (close_start, [(child_start, child_end), ...]) -- the offset of that
    section's own </section> and the spans of its direct <section>
    children."""
    depth = 0
    children = []
    child_start = None
    for tag in _SECTION_TAG.finditer(text, open_start):
        if tag.group(2) == "/":
            continue
        if tag.group(1):                       # </section>
            depth -= 1
            if depth == 1 and child_start is not None:
                children.append((child_start, tag.end()))
                child_start = None
            if depth == 0:
                return tag.start(), children
        else:                                  # <section>
            depth += 1
            if depth == 2 and child_start is None:
                child_start = tag.start()
    return len(text), children


def _content_after_subsection(text, finding):
    spec = finding["fix"]
    el_start = spec["el_start"]
    close_start, children = _section_bounds(text, spec["section_open_start"])
    if not children:
        return []

    # the run: from the offending element to the next <section> or the
    # parent's </section>, whichever comes first
    nxt = re.search(r"<\s*section(?:\s|/|>)", text[el_start + 1:close_start])
    run_end = el_start + 1 + nxt.start() if nxt else close_start
    while run_end > el_start and text[run_end - 1] in " \t\n":
        run_end -= 1
    run_block = text[el_start:run_end].strip()
    if not run_block:
        return []

    line_start = text.rfind("\n", 0, el_start) + 1
    cut_start = line_start if not text[line_start:el_start].strip() else el_start
    cut_end = run_end + 1 if text[run_end:run_end + 1] == "\n" else run_end
    stripped = text[:cut_start] + text[cut_end:]
    section_indent = _indent_of(text, spec["section_open_start"])

    options = []

    # options 1 and 2 splice `stripped` at offsets from the original text;
    # only safe when the target sits before the removed run
    last_close = text.rfind("</section>", children[-1][0], children[-1][1])
    if last_close != -1 and last_close < cut_start:
        close_indent = _indent_of(text, last_close)
        options.append({
            "label": "Move it into the previous subsection",
            "new_text": (stripped[:last_close]
                         + f"  {run_block}\n{close_indent}"
                         + stripped[last_close:]),
        })

    first_sub = spec.get("first_sub_start")
    if first_sub is not None and first_sub < cut_start:
        sub_indent = _indent_of(text, first_sub)
        options.append({
            "label": "Move it above the subsections",
            "new_text": (stripped[:first_sub]
                         + f"{run_block}\n{sub_indent}"
                         + stripped[first_sub:]),
        })

    new_section = (
        f"{section_indent}  <section>\n"
        f"{section_indent}    <title>Untitled section</title>\n"
        f"{section_indent}    {run_block}\n"
        f"{section_indent}  </section>\n"
    )
    options.append({
        "label": "Put it in a new subsection",
        "new_text": stripped[:cut_start] + new_section + stripped[cut_start:],
    })

    return options


### what may sit inside a <para> -- everything else is a block boundary
_INLINE = frozenset({"emphasis", "guilabel", "xref", "indexterm",
                     "primary", "secondary"})
_ANY_TAG = re.compile(r"<\s*(/?)\s*([A-Za-z][\w.-]*)[^<>]*?(/?)\s*>")


def _insert_close(text, finding):
    """An unclosed <para>: put the </para> just before the first
    block-level tag after it. If that tag is a second <para> opening with
    nothing between, the first was a stray duplicate -- offer to drop it."""
    spec = finding["fix"]
    tag = spec["tag"]
    open_start, open_end = spec["open_start"], spec["open_end"]

    boundary = None
    duplicate = False
    for match in _ANY_TAG.finditer(text, open_end):
        if match.group(2).lower() in _INLINE:
            continue
        boundary = match.start()
        duplicate = (
            match.group(2).lower() == tag and not match.group(1)
            and not match.group(3) and not text[open_end:boundary].strip()
        )
        break
    if boundary is None:
        boundary = len(text.rstrip())

    insert_at = boundary
    while insert_at > open_end and text[insert_at - 1] in " \t\n":
        insert_at -= 1

    options = []
    if duplicate:
        line_start = text.rfind("\n", 0, open_start) + 1
        cut_start = line_start if not text[line_start:open_start].strip() else open_start
        cut_end = open_end
        while cut_end < len(text) and text[cut_end] in " \t\n":
            cut_end += 1
        options.append({
            "label": "Delete the extra opening tag",
            "new_text": text[:cut_start] + text[cut_end:],
        })

    options.append({
        "label": "Close the paragraph here",
        "new_text": text[:insert_at] + f"</{tag}>" + text[insert_at:],
    })
    return options


def _root_bounds(text):
    """(open_start, open_end, title_end_or_None, close_start, close_end)
    for the topic's root <section> -- the first one in `text`. None if
    there isn't one."""
    opener = None
    for tag in _SECTION_TAG.finditer(text):
        if tag.group(1) or tag.group(2):
            continue                       # a stray close/self-close first
        opener = tag
        break
    if opener is None:
        return None
    open_start, open_end = opener.start(), opener.end()

    depth = 1
    close_start = close_end = None
    for tag in _SECTION_TAG.finditer(text, open_end):
        if tag.group(2):
            continue
        depth += -1 if tag.group(1) else 1
        if depth == 0:
            close_start, close_end = tag.start(), tag.end()
            break

    title_end = None
    title = re.match(r"\s*<title[^>]*>.*?</title>", text[open_end:], re.DOTALL)
    if title:
        title_end = open_end + title.end()

    return open_start, open_end, title_end, close_start, close_end


def _move_inside_root(text, finding):
    bounds = _root_bounds(text)
    if not bounds:
        return []
    open_start, open_end, title_end, close_start, close_end = bounds
    phase = finding["fix"]["phase"]

    if phase == "before":
        if open_start == 0:
            return []
        run = text[:open_start].strip()
        if not run:
            return []
        insert_at = title_end if title_end is not None else open_end
        indent = _indent_of(text, open_end)
        remainder = text[open_start:]
        rel_insert = insert_at - open_start
        new_text = (remainder[:rel_insert] + f"\n{indent}{run}"
                    + remainder[rel_insert:])
    else:
        if close_start is None:
            return []
        run = text[close_end:].strip()
        if not run:
            return []
        indent = _indent_of(text, close_start)
        new_text = (text[:close_start].rstrip(" \t\n") + "\n"
                    + indent + "  " + run + "\n"
                    + indent + text[close_start:close_end])

    return [{"label": "Move it inside the section", "new_text": new_text}]


_BUILDERS = {
    "loose-block-in-list": _loose_block_in_list,
    "delete-stray-close": _delete_stray_close,
    "empty-listitem": _empty_listitem,
    "bare-text-in-list": _bare_text_in_list,
    "content-after-subsection": _content_after_subsection,
    "insert-close": _insert_close,
    "wrap-in-mediaobject": _wrap_in_mediaobject,
    "move-inside-root": _move_inside_root,
}
