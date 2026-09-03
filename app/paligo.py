########################################################################
### PALIGO -- normalize arbitrary DocBook / HTML tag soup into the exact
### dialect app/docbook.py emits, which is what Paligo's XML source view
### accepts. Lists and tables only; everything else passes through
### unchanged. All-or-nothing: either a fully normalized fragment, or
### the input returned untouched with a best-guess diagnostic -- never a
### half-converted mix (interns copy-paste without reading closely).
########################################################################
import re
from collections import namedtuple

from lxml import etree

from app.docbook import _merge_tokens, _para_element, _serialize, validate_fragment, wrap_list
from app.extensions import logger


class _Bail(Exception):
    """Can't cleanly normalize -- caller returns the original + this text."""


### recover=True tolerates unclosed tags, stray text, bad nesting
_PARSER = etree.XMLParser(recover=True, resolve_entities=False, no_network=True, load_dtd=False)

_FENCE_RE = re.compile(r"\A\s*```[a-zA-Z0-9]*[ \t]*\r?\n|\r?\n?[ \t]*```\s*\Z")
_PROLOG_RE = re.compile(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", re.IGNORECASE)

_LIST_MAP = {"ul": "itemizedlist", "ol": "orderedlist",
             "itemizedlist": "itemizedlist", "orderedlist": "orderedlist"}
_ITEM_TAGS = {"li", "listitem"}
_TABLE_TAGS = {"table", "informaltable"}
_BOLD_TAGS = {"b", "strong"}
_ITALIC_TAGS = {"i", "em"}
_ITEM_BLOCK_BAIL = {"table", "informaltable", "figure", "mediaobject", "informalfigure"}
_UNWRAP_ROOTS = {"article", "section", "chapter", "book", "topic", "div", "body",
                 "sect1", "sect2", "sect3"}
_NUMERATIONS = {"arabic", "loweralpha", "upperalpha", "lowerroman", "upperroman"}

Cell = namedtuple("Cell", "text is_th colspan rowspan")


def normalize(src):
    """-> (output, changed, diagnostic).

    changed True: output is the normalized fragment, diagnostic a short
    confirmation. changed False: output == src (untouched), diagnostic
    the best-guess reason it was left alone.
    """
    stripped = _strip_envelope(src)
    if not stripped:
        return src, False, "Nothing to normalize -- paste some XML first."
    try:
        root = _parse(stripped)
        _strip_namespaces(root)
        _drop_comments(root)
        _unwrap_roots(root)
        fragments, n_lists, n_tables = _transform(root)
    except _Bail as e:
        return src, False, str(e)
    except Exception as e:  # noqa: BLE001 -- never surface a traceback
        logger.info("paligo.normalize failed: %s: %s", type(e).__name__, e)
        return src, False, "Couldn't make sense of this XML -- check for unclosed or mismatched tags."

    if not n_lists and not n_tables:
        return src, False, "No list or table found here -- nothing to change."

    out = "\n".join(fragments)
    ok, msg = validate_fragment(out)
    if not ok:
        logger.info("paligo.normalize output did not validate: %s", msg)

    if _squash(out) == _squash(stripped):
        return out, False, "Already in the right form -- nothing to change."

    parts = []
    if n_lists:
        parts.append(f"{n_lists} list{'s' if n_lists != 1 else ''}")
    if n_tables:
        parts.append(f"{n_tables} table{'s' if n_tables != 1 else ''}")
    return out, True, "Normalized " + " and ".join(parts) + "."


########################################################################
### PARSE / CLEAN

def _strip_envelope(s):
    s = (s or "").strip()
    s = _FENCE_RE.sub("", s)
    s = _PROLOG_RE.sub("", s)
    return s.strip()


def _parse(s):
    try:
        root = etree.fromstring(f"<_paligo_root_>{s}</_paligo_root_>".encode("utf-8"), _PARSER)
    except etree.XMLSyntaxError:
        root = None
    if root is None or (len(root) == 0 and not (root.text or "").strip()):
        raise _Bail("Couldn't parse this as XML -- check for unclosed or mismatched tags.")
    return root


def _strip_namespaces(root):
    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
        for name in list(el.attrib):
            if "}" in name:
                el.attrib[name.split("}", 1)[1]] = el.attrib.pop(name)
    etree.cleanup_namespaces(root)


def _drop_comments(root):
    for node in root.xpath("//comment() | //processing-instruction()"):
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)


def _unwrap_roots(root):
    ### hoist the children of an AI-added <article>/<section>/<div>/... so
    ### the real payload sits at the top level
    for _ in range(5):
        kids = [k for k in root if isinstance(k.tag, str)]
        if len(kids) == 1 and not (root.text or "").strip() and kids[0].tag in _UNWRAP_ROOTS:
            inner = kids[0]
            text = inner.text
            children = list(inner)
            root.remove(inner)
            root.text = text
            root.extend(children)
        else:
            break


########################################################################
### TOP-LEVEL TRANSFORM

def _transform(root):
    """-> (fragment_strings, n_lists, n_tables). Lists go through
    docbook.wrap_list so the output is byte-identical to the Extract
    tool's; tables and pass-through nodes are serialized directly."""
    n_lists = n_tables = 0
    frags = []

    if (root.text or "").strip():
        frags.append(_serialize(_bare_text_para(root.text)))

    for el in list(root):
        tag = el.tag if isinstance(el.tag, str) else None
        if tag in _LIST_MAP:
            listel = _norm_list(el)
            frags.append(wrap_list(listel.tag, [_serialize(li) for li in listel]))
            n_lists += 1
        elif tag in _TABLE_TAGS:
            frags.extend(_serialize(e) for e in _norm_table(el))
            n_tables += 1
        else:
            frags.append(_serialize(el))  # pass through untouched
        if (el.tail or "").strip():
            frags.append(_serialize(_bare_text_para(el.tail)))

    return frags, n_lists, n_tables


def _bare_text_para(text):
    p = etree.Element("para")
    p.text = " ".join(text.split())
    return p


########################################################################
### LISTS

def _norm_list(el):
    out = etree.Element(_LIST_MAP[el.tag])
    num = el.get("numeration")
    if out.tag == "orderedlist" and num in _NUMERATIONS:
        out.set("numeration", num)

    last_item = None
    for child in el:
        ctag = child.tag if isinstance(child.tag, str) else None
        if ctag in _ITEM_TAGS:
            last_item = etree.SubElement(out, "listitem")
            _fill_item(last_item, child)
        elif ctag in _LIST_MAP:
            ### a nested list that's a sibling of the items -> fold it
            ### into the previous item, after its <para>
            if last_item is None:
                last_item = etree.SubElement(out, "listitem")
                etree.SubElement(last_item, "para")
            last_item.append(_norm_list(child))
        ### stray text / inline directly under <ul>/<ol> is dropped
        ### (almost always just whitespace)

    if len(out) == 0:
        raise _Bail("Found a list with no items.")
    return out


def _fill_item(item, src_li):
    """Fill a fresh <listitem> from an <li>/<listitem>: one <para> per
    <p>/<para> (or per run of loose inline/text), then any nested lists,
    docbook.py style."""
    buf = _TokenBuf()
    buf.add_text(src_li.text)
    nested = []

    def flush():
        if buf.has_content():
            item.append(_para_from_tokens(buf.tokens()))
        buf.reset()

    for child in src_li:
        ctag = child.tag if isinstance(child.tag, str) else None
        if ctag in ("p", "para"):
            flush()
            item.append(_para_from_element(child))
        elif ctag in _LIST_MAP:
            flush()
            nested.append(_norm_list(child))
        elif ctag in _ITEM_BLOCK_BAIL:
            raise _Bail(f"A list item contains a <{ctag}> -- restructure that by hand in Paligo.")
        else:
            buf.add_element(child)
        buf.add_text(child.tail)
    flush()

    if not any(isinstance(k.tag, str) and k.tag == "para" for k in item):
        item.insert(0, etree.Element("para"))
    for nl in nested:
        item.append(nl)


class _TokenBuf:
    """Collects (text, bold, italic) tokens from mixed inline content --
    the shape docbook.py's _merge_tokens / _para_element consume."""

    def __init__(self):
        self._t = []

    def reset(self):
        self._t = []

    def has_content(self):
        return any(txt.strip() for txt, _, _ in self._t)

    def tokens(self):
        return list(self._t)

    def add_text(self, s, bold=False, italic=False):
        if s:
            self._t.append((s, bold, italic))

    def add_element(self, el, bold=False, italic=False):
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag == "br":
            self.add_text(" ", bold, italic)
            self.add_text(el.tail, bold, italic)
            return
        b = bold or tag in _BOLD_TAGS or (tag == "emphasis" and el.get("role") == "strong")
        i = italic or tag in _ITALIC_TAGS or (tag == "emphasis" and el.get("role") != "strong")
        self.add_text(el.text, b, i)
        for kid in el:
            self.add_element(kid, b, i)
            self.add_text(kid.tail, b, i)


def _para_from_tokens(tokens):
    merged = _merge_tokens(tokens)
    return _para_element(merged) if merged else etree.Element("para")


def _para_from_element(p):
    buf = _TokenBuf()
    buf.add_text(p.text)
    for kid in p:
        buf.add_element(kid)
        buf.add_text(kid.tail)
    return _para_from_tokens(buf.tokens())


########################################################################
### TABLES

def _norm_table(el):
    out = []
    for cap in el.xpath("./caption | ./title | ./tgroup/caption"):
        txt = _norm_ws(" ".join(cap.itertext()))
        if txt:
            p = etree.Element("para")
            p.text = txt
            out.append(p)

    header_rows, body_rows = _collect_rows(el)
    if not header_rows and not body_rows:
        raise _Bail("Found a table with no rows.")

    table = etree.Element("informaltable", frame="box", rules="all")
    if header_rows:
        thead = etree.SubElement(table, "thead")
        for row in header_rows:
            _emit_row(thead, row, force_th=True)
    tbody = etree.SubElement(table, "tbody")
    for row in body_rows or [[]]:
        _emit_row(tbody, row, force_th=False)

    out.append(table)
    return out


def _collect_rows(el):
    tgroup = el.find("tgroup")
    if tgroup is not None:
        if el.xpath(".//entry[@namest or @nameend or @morerows or @spanname]"):
            raise _Bail("This table uses CALS column/row spans -- convert it by hand in Paligo.")
        thead = tgroup.find("thead")
        header = [_cals_row(r) for r in thead.findall("row")] if thead is not None else []
        body = []
        for section in list(tgroup.findall("tbody")) + list(tgroup.findall("tfoot")):
            body += [_cals_row(r) for r in section.findall("row")]
        return header, body

    thead = el.find("thead")
    header = [_html_row(r) for r in thead.findall("tr")] if thead is not None else []
    body = []
    for name in ("tbody", "tfoot"):
        for section in el.findall(name):
            body += [_html_row(r) for r in section.findall("tr")]
    body += [_html_row(r) for r in el.findall("tr")]  # rows with no <tbody>

    ### no explicit <thead>: promote a leading row that's all <th>
    if not header and len(body) > 1 and body[0] and all(c.is_th for c in body[0]):
        header = [body.pop(0)]

    header = [r for r in header if r]
    body = [r for r in body if r]
    return header, body


def _html_row(tr):
    cells = []
    for c in tr:
        tag = c.tag if isinstance(c.tag, str) else None
        if tag not in ("td", "th"):
            continue
        cells.append(Cell(_norm_ws(" ".join(c.itertext())), tag == "th",
                          _span(c, "colspan"), _span(c, "rowspan")))
    return cells


def _cals_row(row):
    return [Cell(_norm_ws(" ".join(e.itertext())), False, 1, 1) for e in row.findall("entry")]


def _emit_row(parent, cells, force_th):
    tr = etree.SubElement(parent, "tr")
    for c in cells:
        cell = etree.SubElement(tr, "th" if (force_th or c.is_th) else "td")
        if c.colspan > 1:
            cell.set("colspan", str(c.colspan))
        if c.rowspan > 1:
            cell.set("rowspan", str(c.rowspan))
        para = etree.SubElement(cell, "para")
        para.text = c.text or None


def _span(el, name):
    try:
        return max(1, int(el.get(name, "1")))
    except (TypeError, ValueError):
        return 1


def _norm_ws(s):
    return " ".join((s or "").split())


_TAG_GAP_RE = re.compile(r">\s+<")


def _squash(s):
    """collapse inter-tag whitespace so 'same structure, different indent'
    compares equal -- used to tell a real transform from a no-op reformat."""
    return _TAG_GAP_RE.sub("><", s.strip())
