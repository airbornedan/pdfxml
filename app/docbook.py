########################################################################
### DOCBOOK -- REGION-SCOPED EXTRACTION + FRAGMENT GENERATION
###
### Builders return (preview, xml): preview is plain data for Jinja to
### render; xml is the DocBook fragment, no xmlns, meant to paste into
### an existing document. extract_image() returns PNG bytes only.
########################################################################
import os
import re

import fitz
from lxml import etree
from markupsafe import escape

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema", "docbook.rng")
DOCBOOK_NS = "http://docbook.org/ns/docbook"

### a bullet/number marker, alone on its own line or prefixing text
### ("•", "1. First item"). Capped at 4 chars so a word ending in a
### period ("bracket.") isn't mistaken for a marker.
_MARKER_ONLY_RE = re.compile(r"^\s*(?:[•\-\*◦▪‣]|\(?[a-zA-Z0-9]{1,4}[\.\)])\s*$")
_MARKER_PREFIX_RE = re.compile(r"^\s*(?:[•\-\*◦▪‣]|\(?[a-zA-Z0-9]{1,4}[\.\)])\s+")

### these PDFs don't mark line-wrap hyphens differently from real ones
### (no soft hyphens, plain "-"). Lowercase before the hyphen + lowercase
### starting the next line -> join with no hyphen. Misses a real
### compound word breaking at a line end.
_EOL_HYPHEN_RE = re.compile(r"(?<=[a-z])-$")

### paragraph split: a vertical gap over this fraction of a line's height
### (these PDFs set wrapped lines near-flush, ~0pt, and paragraphs ~1
### line-height apart), or a new text block. A gap that also reads as a
### wrap -- no sentence end + next line lowercase -- never splits.
_PARA_GAP_FRACTION = 0.5
_SENTENCE_END_RE = re.compile(r"""[.!?:;)"']\s*$""")

### classifies a marker as ordered ("1.", "a)") vs a bullet symbol --
### used to auto-detect ordered vs unordered from the first marker
### found in a selection. Mixed markers within one selection classify
### by the first one only.
_ORDERED_MARKER_RE = re.compile(r"^\s*\(?[a-zA-Z0-9]{1,4}[\.\)]")


def _serialize(elem):
    return etree.tostring(elem, pretty_print=True, encoding="unicode").strip()


### watermarks are rotated text, real content is axis-aligned -- drop
### non-axis-aligned lines by direction vector
_ROTATED_DIR_THRESHOLD = 0.01


### bold/italic per span -- the flag, or the font name as a fallback
def _span_style(span):
    font = span.get("font", "").lower()
    flags = span.get("flags", 0)
    bold = bool(flags & fitz.TEXT_FONT_BOLD) or "bold" in font
    italic = bool(flags & fitz.TEXT_FONT_ITALIC) or "italic" in font or "oblique" in font
    return bold, italic


def _line_text(spans):
    return "".join(t for t, _, _ in spans).strip()


### clip= can corrupt line reconstruction near a rotated watermark --
### fetch the whole page once, filter by line center in Python instead.
### Split from the fetch so callers needing many regions (table cells)
### fetch once and filter many times.
def _lines_in_region(text_dict, rect):
    ### (y0, y1, block index, [(text, bold, italic), ...]) per axis-aligned
    ### line whose centre is in rect
    rows = []
    for bnum, block in enumerate(text_dict["blocks"]):
        for line in block.get("lines", []):
            bbox = line["bbox"]
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            if center not in rect:
                continue
            dir_x, dir_y = line["dir"]
            if abs(dir_x * dir_y) > _ROTATED_DIR_THRESHOLD:
                continue
            spans = [(s["text"], *_span_style(s)) for s in line["spans"] if s["text"]]
            if _line_text(spans):
                rows.append((bbox[1], bbox[3], bnum, spans))
    return rows


def _filter_lines(text_dict, rect):
    return [_line_text(spans) for _, _, _, spans in _lines_in_region(text_dict, rect)]


def _region_lines(page, rect):
    return _filter_lines(page.get_text("dict"), rect)


def _join_lines(lines):
    result = ""
    for line in lines:
        if not result:
            result = line
        elif _EOL_HYPHEN_RE.search(result) and line[:1].islower():
            result = result[:-1] + line
        else:
            result = result + " " + line
    return result


### group a region's lines into paragraphs; each paragraph a list of its
### line span-lists (a new block or a gap over para_gap starts one; a gap
### that reads as a wrap never does)
def _region_paragraphs(page, rect):
    rows = sorted(_lines_in_region(page.get_text("dict"), rect), key=lambda r: r[:3])
    if not rows:
        return []
    heights = sorted(y1 - y0 for y0, y1, _, _ in rows)
    para_gap = heights[len(heights) // 2] * _PARA_GAP_FRACTION

    paras, current = [], [rows[0][3]]
    for i in range(1, len(rows)):
        _, prev_y1, prev_bnum, prev_spans = rows[i - 1]
        y0, _, bnum, spans = rows[i]
        big_gap = (y0 - prev_y1) > para_gap
        wrap = not _SENTENCE_END_RE.search(_line_text(prev_spans)) and _line_text(spans)[:1].islower()
        if (big_gap or bnum != prev_bnum) and not (wrap and not big_gap):
            paras.append(current)
            current = [spans]
        else:
            current.append(spans)
    paras.append(current)
    return paras


### one paragraph's line span-lists -> a flat [(text, bold, italic)] run:
### EOL-hyphen de-wrap at a line join (see _join_lines), else a joining
### space -- styled to match when both sides agree, so the run stays one
### <emphasis>
def _para_tokens(lines):
    tokens = []
    for i, spans in enumerate(lines):
        if i and tokens:
            prev_text, prev_b, prev_i = tokens[-1]
            first = spans[0] if spans else ("", False, False)
            if _EOL_HYPHEN_RE.search(prev_text) and first[0][:1].islower():
                tokens[-1] = (prev_text[:-1], prev_b, prev_i)
            elif not prev_text[-1:].isspace():
                style = (prev_b, prev_i) if (prev_b, prev_i) == first[1:] else (False, False)
                tokens.append((" ", *style))
        tokens.extend(spans)
    return tokens


### merge same-style neighbours, push whitespace off the edge of a styled
### run out to a plain token, trim the ends
def _merge_tokens(tokens):
    out = []
    for text, bold, italic in tokens:
        if not text:
            continue
        if out and out[-1][1:] == (bold, italic):
            out[-1] = (out[-1][0] + text, bold, italic)
        else:
            out.append((text, bold, italic))

    shifted = []
    for text, bold, italic in out:
        if (bold or italic) and text.strip() and text.strip() != text:
            lead, core, trail = text[:len(text) - len(text.lstrip())], text.strip(), text[len(text.rstrip()):]
            shifted += [(lead, False, False), (core, bold, italic), (trail, False, False)]
        else:
            shifted.append((text, bold, italic))

    if shifted:
        shifted[0] = (shifted[0][0].lstrip(), *shifted[0][1:])
        shifted[-1] = (shifted[-1][0].rstrip(), *shifted[-1][1:])
    return [t for t in shifted if t[0]]


### <para> mixed content: bold -> <emphasis role="strong">, italic -> <emphasis>
def _para_element(tokens):
    para = etree.Element("para")
    last = None
    for text, bold, italic in tokens:
        if (bold or italic) and text.strip():
            last = etree.SubElement(para, "emphasis")
            if bold:
                last.set("role", "strong")
            last.text = text
        elif last is None:
            para.text = (para.text or "") + text
        else:
            last.tail = (last.tail or "") + text
    return para


### same run, as preview HTML: bold -> <strong>, italic -> <em>, text escaped
def _tokens_html(tokens):
    parts = []
    for text, bold, italic in tokens:
        piece = str(escape(text))
        if bold:
            piece = f"<strong>{piece}</strong>"
        elif italic:
            piece = f"<em>{piece}</em>"
        parts.append(piece)
    return "".join(parts)


########################################################################
### PARAGRAPH -- wrapped lines joined per paragraph, one <para> each for a
### multi-paragraph selection; bold/italic spans kept as <emphasis>.
def extract_paragraph(page, rect):
    previews, fragments = [], []
    for lines in _region_paragraphs(page, rect):
        tokens = _merge_tokens(_para_tokens(lines))
        previews.append(_tokens_html(tokens))
        fragments.append(_serialize(_para_element(tokens)))
    return previews, "\n".join(fragments)


########################################################################
### LISTS -- a marker line starts a new item; continuation lines join
### it until the next marker. Lines before the first marker are dropped.
### Each item carries its lines' span-lists so <emphasis> survives too.
def _strip_marker(spans):
    if not spans:
        return spans
    text, bold, italic = spans[0]
    return [(_MARKER_PREFIX_RE.sub("", text, count=1), bold, italic), *spans[1:]]


def _split_list_items(rows):
    items, current, in_list, ordered = [], [], False, False
    for _, _, _, spans in rows:
        text = _line_text(spans)
        if _MARKER_ONLY_RE.match(text):
            if not items and not current:
                ordered = bool(_ORDERED_MARKER_RE.match(text))
            if current:
                items.append(current)
            current, in_list = [], True
        elif _MARKER_PREFIX_RE.match(text):
            if not items and not current:
                ordered = bool(_ORDERED_MARKER_RE.match(text))
            if current:
                items.append(current)
            current, in_list = [_strip_marker(spans)], True
        elif in_list:
            current.append(spans)
    if current:
        items.append(current)
    return items, ordered


def extract_list(page, rect):
    rows = _lines_in_region(page.get_text("dict"), rect)
    items, ordered = _split_list_items(rows)
    element_type = "orderedlist" if ordered else "itemizedlist"
    root = etree.Element(element_type)
    previews = []
    for lines in items:
        tokens = _merge_tokens(_para_tokens(lines))
        etree.SubElement(root, "listitem").append(_para_element(tokens))
        previews.append(_tokens_html(tokens))
    return element_type, previews, _serialize(root)


########################################################################
### TABLE -- page.find_tables() scoped to the region, falls back to
### one single-cell row if nothing's detected. Cell text is rebuilt via
### _filter_lines() so the watermark filter applies per cell too.
### Markup is DocBook 5's HTML table model (tr/th/td), not CALS --
### Paligo's XML source view only accepts this form.
def extract_table(page, rect):
    finder = page.find_tables(clip=rect)
    if finder.tables:
        table = finder.tables[0]
        text_dict = page.get_text("dict")  # fetched once, reused for every cell below
        rows = [_table_row_text(text_dict, row) for row in table.rows]
        has_header = _has_reliable_header(page, table)
    else:
        whole_text = _join_lines(_region_lines(page, rect))
        rows = [[whole_text]] if whole_text else [[""]]
        has_header = False

    root = etree.Element("informaltable", frame="box", rules="all")

    header_row = None
    body_rows = rows
    if has_header:
        header_row = rows[0]
        body_rows = rows[1:]
        thead = etree.SubElement(root, "thead")
        _append_row(thead, header_row, "th")

    tbody = etree.SubElement(root, "tbody")
    for row in body_rows:
        _append_row(tbody, row, "td")

    preview = {"header": header_row, "body": body_rows}
    return preview, _serialize(root)


def _table_row_text(text_dict, row):
    return [_join_lines(_filter_lines(text_dict, fitz.Rect(cell))) if cell else "" for cell in row.cells]


def _append_row(parent, row, cell_tag):
    row_elem = etree.SubElement(parent, "tr")
    for cell in row:
        cell_elem = etree.SubElement(row_elem, cell_tag)
        para = etree.SubElement(cell_elem, "para")
        para.text = cell


### PyMuPDF's table.header assumes a header even on plain data grids --
### only trust bold top row + non-bold next row instead
_BOLD_HEADER_THRESHOLD = 0.5


def _row_bold_fraction(page, bbox):
    text_dict = page.get_text("dict", clip=fitz.Rect(bbox), flags=fitz.TEXTFLAGS_TEXT)
    spans = [s for b in text_dict["blocks"] for l in b.get("lines", []) for s in l["spans"] if s["text"].strip()]
    if not spans:
        return None
    return sum(1 for s in spans if s["flags"] & fitz.TEXT_FONT_BOLD) / len(spans)


def _has_reliable_header(page, table):
    if table.row_count < 2:
        return False
    top_bold = _row_bold_fraction(page, table.rows[0].bbox)
    next_bold = _row_bold_fraction(page, table.rows[1].bbox)
    return top_bold is not None and top_bold > _BOLD_HEADER_THRESHOLD and next_bold == 0.0


### Region image rendering + watermark redaction moved to app/pdfops.py
### (fitz -> runs in the sandbox worker).

########################################################################
### VALIDATION -- wraps the fragment in a minimal DocBook 5 container
### and validates in-process against the vendored schema (parsed once
### at import). Returns (is_valid, message).
_WRAP = '<article xmlns="{ns}" version="5.2"><title>x</title>{fragment}</article>'
_SCHEMA = etree.RelaxNG(etree.parse(SCHEMA_PATH))

### fragment is app-generated; defence in depth -- no entities, no
### network, no DTD
_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)


def validate_fragment(xml_fragment):
    wrapped = _WRAP.format(ns=DOCBOOK_NS, fragment=xml_fragment)
    try:
        document = etree.fromstring(wrapped.encode("utf-8"), _SAFE_PARSER)
    except etree.XMLSyntaxError as e:
        return False, str(e)
    if _SCHEMA.validate(document):
        return True, "Valid DocBook 5."
    return False, str(_SCHEMA.error_log.last_error)
