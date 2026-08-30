########################################################################
### PDFOPS -- PyMuPDF ops that run inside a sandbox worker (app/sandbox.py).
### Path + plain data in, plain data out; no fitz objects cross the
### process boundary. fitz-only at import; docbook/resource lazy.
########################################################################
import fitz

_REDACT_IMAGES = fitz.PDF_REDACT_IMAGE_NONE
_REDACT_GRAPHICS = fitz.PDF_REDACT_LINE_ART_NONE


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


### per-character quads, not one for the rotated line -- redaction tests
### bounding boxes, so a wide quad would erase unrelated content.
def _redact_watermark(page, watermark_text):
    if not watermark_text:  # no text set -> redaction off
        return
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            line_text = "".join(c["c"] for s in line["spans"] for c in s["chars"])
            if watermark_text not in line_text:
                continue
            for span in line["spans"]:
                for ch in span["chars"]:
                    page.add_redact_annot(fitz.Rect(ch["bbox"]).quad, fill=None)
    page.apply_redactions(images=_REDACT_IMAGES, graphics=_REDACT_GRAPHICS)


### renders the region, not the embedded image object.
def render_region_png(pdf_path, page_index, rect, zoom, watermark_text, max_megapixels):
    clip = fitz.Rect(*rect)
    with fitz.open(pdf_path) as doc:
        page = doc[page_index]
        _redact_watermark(page, watermark_text)
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
            text, xml = docbook.extract_paragraph(page, r)
            return {"element_type": "paragraph", "preview": text, "xml": xml}
        if element_type == "list":
            resolved_type, items, xml = docbook.extract_list(page, r)
            return {"element_type": resolved_type, "preview": items, "xml": xml}
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
        except Exception:
            pass
    finally:
        conn.close()
