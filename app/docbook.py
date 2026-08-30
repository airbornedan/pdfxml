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


### clip= can corrupt line reconstruction near a rotated watermark --
### fetch the whole page once, filter by line center in Python instead.
### Split from the fetch so callers needing many regions (table cells)
### fetch once and filter many times.
def _filter_lines(text_dict, rect):
    lines = []
    for block in text_dict["blocks"]:
        for line in block.get("lines", []):
            bbox = line["bbox"]
            center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
            if center not in rect:
                continue
            dir_x, dir_y = line["dir"]
            if abs(dir_x * dir_y) > _ROTATED_DIR_THRESHOLD:
                continue
            text = "".join(span["text"] for span in line["spans"]).strip()
            if text:
                lines.append(text)
    return lines


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


########################################################################
### PARAGRAPH -- wrapped lines joined into one block, not one <para>
### per line.
def extract_paragraph(page, rect):
    text = _join_lines(_region_lines(page, rect))
    elem = etree.Element("para")
    elem.text = text
    return text, _serialize(elem)


########################################################################
### LISTS -- a marker line starts a new item; continuation lines join
### it until the next marker. Lines before the first marker are dropped.
def _split_list_items(lines):
    items = []
    current = []
    in_list = False
    ordered = False
    for line in lines:
        if _MARKER_ONLY_RE.match(line):
            if not items and not current:
                ordered = bool(_ORDERED_MARKER_RE.match(line))
            if current:
                items.append(_join_lines(current))
            current = []
            in_list = True
        elif _MARKER_PREFIX_RE.match(line):
            if not items and not current:
                ordered = bool(_ORDERED_MARKER_RE.match(line))
            if current:
                items.append(_join_lines(current))
            current = [_MARKER_PREFIX_RE.sub("", line, count=1)]
            in_list = True
        elif in_list:
            current.append(line)
    if current:
        items.append(_join_lines(current))
    return items, ordered


def extract_list(page, rect):
    items, ordered = _split_list_items(_region_lines(page, rect))
    element_type = "orderedlist" if ordered else "itemizedlist"
    root = etree.Element(element_type)
    for item_text in items:
        listitem = etree.SubElement(root, "listitem")
        para = etree.SubElement(listitem, "para")
        para.text = item_text
    return element_type, items, _serialize(root)


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
