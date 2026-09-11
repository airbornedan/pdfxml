########################################################################
### FIXES -- candidate repairs for LML findings.
###
### Every fix is a pure structural edit (wrap / move / insert marker /
### remove an empty wrapper) and is offered only when it loses no word
### of the input -- the anti-Paligo guarantee. The intern picks; nothing
### is applied automatically.
########################################################################
import re
from collections import Counter

_WS = re.compile(r"\s+")
_TAG = re.compile(r"<[^<>]*>")
_OPEN_TAG = re.compile(r"<\s*([A-Za-z][\w.-]*)([^<>]*?)(/?)\s*>")


def _words(text):
    """Whitespace-separated words with all tags removed -- the content a
    fix must not lose (order-independent)."""
    return sorted(_TAG.sub(" ", text).split())


def _guard(original, candidate):
    """True when every word of `original` survives in `candidate` with at
    least its original count. Additions (a placeholder title, wrapper
    tags) are allowed; losing or dropping a word is not."""
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

    # run = the offending element through the next <section> or the
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

    # options 1 and 2 splice `stripped` at offsets from the original
    # text; only safe when the target sits before the removed run. The
    # line's own leading indent is already in stripped[:offset].
    last_close = text.rfind("</section>", children[-1][0], children[-1][1])
    if last_close != -1 and last_close < cut_start:
        close_indent = _indent_of(text, last_close)
        options.append({
            "label": "Move it into the previous subsection",
            "before": run_block,
            "after": f"…\n{close_indent}  {run_block}\n{close_indent}</section>",
            "new_text": (stripped[:last_close]
                         + f"  {run_block}\n{close_indent}"
                         + stripped[last_close:]),
        })

    first_sub = spec.get("first_sub_start")
    if first_sub is not None and first_sub < cut_start:
        sub_indent = _indent_of(text, first_sub)
        options.append({
            "label": "Move it above the subsections",
            "before": run_block,
            "after": f"{sub_indent}{run_block}\n{sub_indent}<section>…",
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
        "label": "Wrap it in its own new subsection (rename the title)",
        "before": run_block,
        "after": (f"<section>\n{section_indent}    <title>Untitled section</title>\n"
                  f"{section_indent}    {run_block}\n{section_indent}  </section>"),
        "new_text": stripped[:cut_start] + new_section + stripped[cut_start:],
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
    "content-after-subsection": _content_after_subsection,
}
