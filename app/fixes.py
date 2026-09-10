########################################################################
### FIXES -- candidate repairs for LML findings.
###
### Every fix is a pure structural edit (wrap / move / insert marker /
### remove an empty wrapper) and is offered only when it loses no word
### of the input -- the anti-Paligo guarantee. The intern picks; nothing
### is applied automatically.
########################################################################
import re

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^<>]*>")
_OPEN_TAG = re.compile(r"<\s*([A-Za-z][\w.-]*)([^<>]*?)(/?)\s*>")


def _words(text):
    """Whitespace-separated words with all tags removed -- the content
    that a fix must preserve exactly (order-independent)."""
    return sorted(_TAG.sub(" ", text).split())


def _guard(original, candidate):
    return _words(original) == _words(candidate)


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
    """Return a list of {"label", "before", "after", "new_text"} for the
    finding, or [] when there is no safe mechanical repair."""
    spec = finding.get("fix")
    builder = _BUILDERS.get(spec.get("kind")) if spec else None
    if builder is None:
        return []
    return [
        option for option in builder(text, finding)
        if _guard(text, option["new_text"])
    ]


# --- builders ----------------------------------------------------------

def _loose_block_in_list(text, finding):
    spec = finding["fix"]
    el_start = spec["el_start"]
    _, el_end = _element_span(text, el_start)
    element = text[el_start:el_end]
    indent = _indent_of(text, el_start)

    line_start = text.rfind("\n", 0, el_start) + 1
    line_end = el_end + 1 if text[el_end:el_end + 1] == "\n" else el_end

    options = []

    wrapped = f"{indent}<listitem>\n{indent}  {element}\n{indent}</listitem>\n"
    options.append({
        "label": "Make it its own list item",
        "before": element,
        "after": f"<listitem>\n{indent}  {element}\n{indent}</listitem>",
        "new_text": text[:line_start] + wrapped + text[line_end:],
    })

    prev_close = text.rfind("</listitem>", spec["list_start"], el_start)
    if prev_close != -1:
        li_indent = _indent_of(text, prev_close)
        insertion = f"{li_indent}  {element}\n"
        options.append({
            "label": "Add it to the item above",
            "before": element,
            "after": f"  {element}\n{li_indent}</listitem>",
            "new_text": (text[:prev_close] + insertion
                         + text[prev_close:line_start] + text[line_end:]),
        })

    end_tag = f"</{spec['list_tag']}>"
    list_close = text.find(end_tag, el_end)
    if list_close != -1:
        close_end = list_close + len(end_tag)
        list_indent = _indent_of(text, list_close)
        options.append({
            "label": "Move it out below the list",
            "before": element,
            "after": f"{end_tag}\n{list_indent}{element}",
            "new_text": (text[:line_start] + text[line_end:close_end]
                         + f"\n{list_indent}{element}" + text[close_end:]),
        })

    return options


def _delete_stray_close(text, finding):
    start, end = finding.get("start"), finding.get("end")
    if start is None or end is None:
        return []
    tag = text[start:end]
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = line_end if line_end != -1 else len(text)

    if not text[line_start:start].strip() and not text[end:line_end].strip():
        cut_start, cut_end = line_start, min(line_end + 1, len(text))
    else:
        cut_start, cut_end = start, end

    return [{
        "label": f"Delete the stray {tag}",
        "before": tag,
        "after": "(removed)",
        "new_text": text[:cut_start] + text[cut_end:],
    }]


def _empty_listitem(text, finding):
    spec = finding["fix"]
    el_start, el_end = spec["el_start"], spec["el_end"]
    element = text[el_start:el_end]
    indent = _indent_of(text, el_start)
    options = []

    close_pos = text.rfind("</listitem>", el_start, el_end)
    if close_pos != -1:
        insertion = f"\n{indent}  <para></para>\n{indent}"
        # replace the whitespace already sitting before </listitem>
        gap_start = close_pos
        while gap_start > el_start and text[gap_start - 1] in " \t\n":
            gap_start -= 1
        options.append({
            "label": "Add an empty <para> to fill in",
            "before": element,
            "after": f"<listitem>{insertion}</listitem>",
            "new_text": text[:gap_start] + insertion + text[close_pos:],
        })

    line_start = text.rfind("\n", 0, el_start) + 1
    line_end = el_end + 1 if text[el_end:el_end + 1] == "\n" else el_end
    options.append({
        "label": "Delete the empty list item",
        "before": element,
        "after": "(removed)",
        "new_text": text[:line_start] + text[line_end:],
    })
    return options


def _bare_text_in_list(text, finding):
    spec = finding["fix"]
    seg_start, seg_end = spec["text_start"], spec["text_end"]
    segment = text[seg_start:seg_end]
    lead = len(segment) - len(segment.lstrip())
    trail = len(segment) - len(segment.rstrip())
    content = segment[lead:len(segment) - trail]
    if not content:
        return []
    wrapped = f"<listitem><para>{content}</para></listitem>"
    return [{
        "label": "Wrap it in a list item",
        "before": content,
        "after": wrapped,
        "new_text": text[:seg_start + lead] + wrapped + text[seg_end - trail:],
    }]


_BUILDERS = {
    "loose-block-in-list": _loose_block_in_list,
    "delete-stray-close": _delete_stray_close,
    "empty-listitem": _empty_listitem,
    "bare-text-in-list": _bare_text_in_list,
}
