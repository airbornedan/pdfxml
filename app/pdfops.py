########################################################################
### PDFOPS -- PyMuPDF ops that run inside a sandbox worker (app/sandbox.py).
### Path + plain data in, plain data out; no fitz objects cross the
### process boundary. fitz-only at import; docbook/resource lazy.
########################################################################
import os
import re
import tempfile
from contextlib import contextmanager

import fitz

_REDACT_IMAGES = fitz.PDF_REDACT_IMAGE_NONE
_REDACT_GRAPHICS = fitz.PDF_REDACT_LINE_ART_NONE
_WATERMARK_DIRECTION_TOLERANCE = 0.01
_PDF_STRING_RE = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]+>")
_PDF_SHOW_RE = re.compile(rb"(\[[^\]]*\]|\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]+>)\s*T[Jj]")


### mirror of app.extensions.clamp_zoom, kept fitz-only. Keep in step.
def _clamp_zoom(width_pt, height_pt, zoom, max_megapixels):
    if not max_megapixels:
        return zoom
    pixels = (width_pt * zoom) * (height_pt * zoom)
    ceiling = max_megapixels * 1_000_000
    if pixels <= ceiling:
        return zoom
    return zoom * (ceiling / pixels) ** 0.5


def page_count(pdf_path):
    with fitz.open(pdf_path) as doc:
        return doc.page_count


def render_page_png(pdf_path, page_index, zoom, max_megapixels):
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        zoom = _clamp_zoom(page.rect.width, page.rect.height, zoom, max_megapixels)
        return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


def _inspect_page_streams(doc, page):
    """Return page content streams as immutable xref/bytes records."""
    records = []
    for xref in page.get_contents() or []:
        stream = doc.xref_stream(xref)
        if stream is not None:
            records.append({"xref": xref, "stream": bytes(stream)})
    return records


def _pdf_string_bytes(token):
    if token.startswith(b"<"):
        return bytes.fromhex(re.sub(rb"\s+", b"", token[1:-1]).decode())
    value = token[1:-1]
    return re.sub(rb"\\([\\()\\])", rb"\1", value)


def _stream_text_bytes(stream):
    return b"".join(_pdf_string_bytes(token) for token in _PDF_STRING_RE.findall(stream))


def _watermark_lines(page, watermark_text, direction=None):
    if not watermark_text:
        return []
    matches = []
    for block in page.get_text("rawdict").get("blocks", []):
        for line in block.get("lines", []):
            line_text = "".join(
                char["c"] for span in line.get("spans", []) for char in span.get("chars", [])
            )
            if line_text != watermark_text:
                continue
            line_direction = tuple(line.get("dir", (1.0, 0.0)))
            if direction is not None and any(
                abs(actual - expected) > _WATERMARK_DIRECTION_TOLERANCE
                for actual, expected in zip(line_direction, direction)
            ):
                continue
            matches.append({"text": line_text, "dir": line_direction, "bbox": tuple(line["bbox"])})
    return matches


def _watermark_object_ids(doc, page, watermark_text, direction=None):
    """Return content-stream xrefs that contain a verified watermark line."""
    if not _watermark_lines(page, watermark_text, direction):
        return []
    encoded = watermark_text.encode("latin-1")
    return [
        record["xref"]
        for record in _inspect_page_streams(doc, page)
        if encoded in _stream_text_bytes(record["stream"])
    ]


class WatermarkMappingError(ValueError):
    """The watermark cannot be mapped to one unambiguous text sequence."""


def _show_operand_text(operand):
    return b"".join(_pdf_string_bytes(token) for token in _PDF_STRING_RE.findall(operand))


def _watermark_operator_spans(stream, watermark_text):
    encoded = watermark_text.encode("latin-1")
    candidates = []
    for block in re.finditer(rb"\bBT\b(.*?)\bET\b", stream, flags=re.DOTALL):
        operators = list(_PDF_SHOW_RE.finditer(block.group(1)))
        for start in range(len(operators)):
            text = b""
            for end in range(start, len(operators)):
                text += _show_operand_text(operators[end].group(1))
                if text == encoded:
                    candidates.append(tuple(
                        (block.start(1) + operators[index].start(), block.start(1) + operators[index].end())
                        for index in range(start, end + 1)
                    ))
                    break
                if not encoded.startswith(text):
                    break
    return candidates


def _rewrite_watermark_stream(stream, watermark_text):
    candidates = _watermark_operator_spans(stream, watermark_text)
    if len(candidates) != 1:
        raise WatermarkMappingError(
            f"Watermark text maps to {len(candidates)} content-stream sequences; expected exactly one."
        )
    rewritten = stream
    for start, end in reversed(candidates[0]):
        rewritten = rewritten[:start] + rewritten[end:]
    return rewritten


@contextmanager
def _temporary_watermark_document(pdf_path, page_index, watermark_text, direction=None):
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    os.unlink(temp_path)
    try:
        with fitz.open(pdf_path) as doc:
            page = doc[page_index]
            lines = _watermark_lines(page, watermark_text, direction)
            if len(lines) > 1:
                raise WatermarkMappingError(
                    f"Watermark text appears in {len(lines)} matching lines; expected exactly one."
                )
            if lines:
                xrefs = _watermark_object_ids(doc, page, watermark_text, direction)
                if len(xrefs) != 1:
                    raise WatermarkMappingError(
                        f"Watermark text maps to {len(xrefs)} content streams; expected exactly one."
                    )
                stream = doc.xref_stream(xrefs[0])
                doc.update_stream(xrefs[0], _rewrite_watermark_stream(stream, watermark_text))
            doc.save(temp_path)
        yield temp_path
    finally:
        try:
            os.unlink(temp_path)
        except FileNotFoundError:
            pass


### redact only the matching characters, not every character on a matching
### line. recover_quad keeps each rotated glyph tight instead of turning its
### axis-aligned bbox into a larger rectangle.
def _redact_watermark(page, watermark_text):
    if not watermark_text:  # no text set -> redaction off
        return
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            line_text = "".join(c["c"] for s in line["spans"] for c in s["chars"])
            match_start = line_text.find(watermark_text)
            if match_start < 0:
                continue
            match_end = match_start + len(watermark_text)
            char_index = 0
            for span in line["spans"]:
                for ch in span["chars"]:
                    next_index = char_index + 1
                    if match_start <= char_index < match_end:
                        char_span = {**span, "bbox": ch["bbox"], "origin": ch["origin"]}
                        quad = fitz.recover_quad(line["dir"], char_span)
                        page.add_redact_annot(quad, fill=None)
                    char_index = next_index
    page.apply_redactions(images=_REDACT_IMAGES, graphics=_REDACT_GRAPHICS)


### renders the region, not the embedded image object. erase_rects
### (PDF points, page-relative) are painted white before rendering --
### lets the caller punch out stray content that overlapped the crop
### rectangle without hand-editing the source PDF.
def render_region_png(pdf_path, page_index, rect, zoom, watermark_text, max_megapixels, erase_rects=None):
    clip = fitz.Rect(*rect)
    with _temporary_watermark_document(pdf_path, page_index, watermark_text) as working_path:
        with fitz.open(working_path) as doc:
            page = doc[page_index]
            for er in (erase_rects or []):
                page.draw_rect(fitz.Rect(*er), color=(1, 1, 1), fill=(1, 1, 1), width=0)
            zoom = _clamp_zoom(clip.width, clip.height, zoom, max_megapixels)
            return page.get_pixmap(clip=clip, matrix=fitz.Matrix(zoom, zoom)).tobytes("png")


### raw extraction only; emptiness + validation stay in the parent.
### "image" never reaches here -- that route just records the rect.
def extract_region(pdf_path, page_index, rect, element_type):
    from app import docbook

    r = fitz.Rect(*rect)
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        if element_type == "paragraph":
            paras, fragments = docbook.extract_paragraph(page, r)
            xml = docbook.wrap_paragraphs(fragments)
            return {"element_type": "paragraph", "preview": paras, "xml": xml, "items": fragments}
        if element_type == "list":
            resolved_type, items, items_xml = docbook.extract_list(page, r)
            xml = docbook.wrap_list(resolved_type, items_xml)
            return {"element_type": resolved_type, "preview": items, "xml": xml, "items": items_xml}
        if element_type == "table":
            rows, xml = docbook.extract_table(page, r)
            return {"element_type": "table", "preview": rows, "xml": xml}
        raise ValueError(f"unknown element_type {element_type!r}")


### app/sandbox.py's Process target -- here, not there, so a worker
### imports only this module + fitz. Caps resources, runs one op, pipes
### back (ok, result-or-message).
def worker_entry(conn, rlimit_as, rlimit_cpu, func, args):
    try:
        import resource

        if rlimit_as:
            resource.setrlimit(resource.RLIMIT_AS, (rlimit_as, rlimit_as))
        if rlimit_cpu:
            resource.setrlimit(resource.RLIMIT_CPU, (rlimit_cpu, rlimit_cpu))
        conn.send((True, func(*args)))
    except BaseException as exc:  # noqa: BLE001 -- report anything, MemoryError included
        try:
            conn.send((False, f"{type(exc).__name__}: {exc}"))
        except Exception:  # noqa: BLE001, S110 -- pipe already dead (parent
            # gone); nothing to do but let finally close us out. The parent
            # sees this as EOFError and logs "worker died" on its side.
            pass
    finally:
        conn.close()
