########################################################################
### EXTRACT -- UPLOAD, PAGE SELECTION, REGION-SELECT WIZARD
########################################################################
from flask import Blueprint, render_template, request, redirect, url_for, session, Response, abort

from app.extensions import (
    pdf_processing_limit, save_upload, upload_path, delete_upload,
    save_result, load_result, sweep_old_uploads,
    PREVIEW_ZOOM, IMAGE_ZOOM, THUMBNAIL_ZOOM, PAGE_GRID_ZOOM,
    MAX_RENDER_MEGAPIXELS, WATERMARK_TEXT,
)
from app import docbook, pdfops, ratelimit, sandbox

bp = Blueprint("extract", __name__)

TYPE_LABELS = {
    "paragraph": "Paragraph",
    "orderedlist": "Ordered list",
    "itemizedlist": "Unordered list",
    "table": "Table",
    "image": "Image",
}

### the four buttons on the region-select page. "list" isn't a real
### element_type on its own -- extract_list() resolves it to
### orderedlist/itemizedlist from the content itself.
ALLOWED_ELEMENT_TYPES = {"paragraph", "list", "table", "image"}


### just the path -- every PDF op runs in the sandbox worker, so the
### request process never holds a fitz handle.
def _current_pdf_path():
    return upload_path(session.get("pdf_token"))


### Home -> Extract -> current step, current step omitted on
### choose_pdf itself since that IS the wizard's landing page
def _breadcrumbs(step_label=None):
    items = [("Home", url_for("extract.index"))]
    if step_label is None:
        items.append(("Extract", ""))
    else:
        items.append(("Extract", url_for("extract.choose_pdf")))
        items.append((step_label, ""))
    return items


@bp.route("/")
def index():
    return render_template("index.html")


def _clear_pdf():
    delete_upload(session.get("pdf_token"))
    session.pop("pdf_token", None)
    session.pop("pdf_filename", None)
    session.pop("page_count", None)
    session.pop("page_number", None)


@bp.route("/extract/pdf")
def choose_pdf():
    ### the session can still name a pdf_token whose file the sweep
    ### already removed (upload activity elsewhere, or this one just
    ### went idle too long) -- catch that here rather than letting
    ### "Continue with this PDF" walk into a confusing dead end further
    ### into the wizard
    error = None
    if session.get("pdf_token") and upload_path(session["pdf_token"]) is None:
        _clear_pdf()
        error = "Your previous upload expired -- please upload again."

    return render_template(
        "upload.html",
        breadcrumbs=_breadcrumbs(),
        pdf_filename=session.get("pdf_filename"),
        page_count=session.get("page_count"),
        error=error,
    )


@bp.route("/extract/pdf/clear", methods=["POST"])
def clear_pdf():
    _clear_pdf()
    return redirect(url_for("extract.choose_pdf"))


@bp.route("/upload", methods=["POST"])
@ratelimit.limit("upload")
@pdf_processing_limit
def upload():
    sweep_old_uploads()  # opportunistic, not scheduled

    file = request.files.get("pdf")
    if file is None or file.filename == "":
        return render_template(
            "upload.html",
            breadcrumbs=_breadcrumbs(),
            pdf_filename=None,
            page_count=None,
            error="Choose a PDF file first.",
        )

    delete_upload(session.get("pdf_token"))
    token = save_upload(file)

    ### confirm it's a real PDF, not just the extension. First parse of
    ### an untrusted file -- through the sandbox like every PDF op.
    try:
        page_count = sandbox.run(pdfops.page_count, upload_path(token))
    except Exception:
        delete_upload(token)
        return render_template(
            "upload.html",
            breadcrumbs=_breadcrumbs(),
            pdf_filename=None,
            page_count=None,
            error="That doesn't look like a valid PDF.",
        )

    session["pdf_token"] = token
    session["pdf_filename"] = file.filename
    session["page_count"] = page_count
    session.pop("page_number", None)
    return redirect(url_for("extract.choose_page"))


@bp.route("/extract/page", methods=["GET", "POST"])
@ratelimit.limit("render")
@pdf_processing_limit
def choose_page():
    path = _current_pdf_path()
    if path is None:
        return redirect(url_for("extract.index"))
    try:
        page_count = sandbox.run(pdfops.page_count, path)
    except Exception:
        return redirect(url_for("extract.index"))

    error = None
    if request.method == "POST":
        ### the grid's thumbnail buttons submit thumb_page_number; the
        ### text field submits page_number -- either can drive selection
        raw_page_number = request.form.get("thumb_page_number") or request.form.get("page_number", "")
        try:
            page_number = int(raw_page_number)
        except ValueError:
            page_number = None
        if page_number is None or not (1 <= page_number <= page_count):
            error = f"Enter a page number between 1 and {page_count}."
        else:
            session["page_number"] = page_number
            return redirect(url_for("extract.select_region"))

    return render_template(
        "choose_page.html",
        breadcrumbs=_breadcrumbs("Choose page"),
        page_count=page_count,
        error=error,
    )


@bp.route("/extract/select", methods=["GET", "POST"])
@ratelimit.limit("render")
@pdf_processing_limit
def select_region():
    path = _current_pdf_path()
    if path is None or "page_number" not in session:
        return redirect(url_for("extract.index"))

    def _page(error):
        return render_template(
            "select_region.html",
            breadcrumbs=_breadcrumbs("Select region"),
            page_number=session["page_number"],
            page_count=session.get("page_count"),
            pdf_filename=session.get("pdf_filename"),
            error=error,
        )

    if request.method == "POST":
        element_type = request.form.get("element_type")
        if element_type not in ALLOWED_ELEMENT_TYPES:
            abort(400)
        try:
            x0 = float(request.form["x0"]) / PREVIEW_ZOOM
            y0 = float(request.form["y0"]) / PREVIEW_ZOOM
            x1 = float(request.form["x1"]) / PREVIEW_ZOOM
            y1 = float(request.form["y1"]) / PREVIEW_ZOOM
        except (KeyError, ValueError):
            abort(400)
        if x1 <= x0 or y1 <= y0:
            return _page("Draw a region on the page first.")

        try:
            result = _run_extraction(path, session["page_number"], (x0, y0, x1, y1), element_type)
        except sandbox.SandboxError:
            return _page("Couldn't read that region -- try a different selection.")
        save_result(session["pdf_token"], result)
        ### image goes straight to an in-page modal (fetch) -- no result
        ### page. text/list/table still have XML to show there.
        if element_type == "image" and request.headers.get("X-Requested-With") == "fetch":
            return ("", 204)
        return redirect(url_for("extract.result"))

    return _page(None)


### moves to the adjacent page without going back through choose_page --
### for content (lists, tables) that continues past the current page.
### No-op at either end; a full page reload resets the region-select JS
### state either way.
@bp.route("/extract/page/prev", methods=["POST"])
def page_prev():
    if session.get("page_number", 1) > 1:
        session["page_number"] -= 1
    return redirect(url_for("extract.select_region"))


@bp.route("/extract/page/next", methods=["POST"])
def page_next():
    if session.get("page_number", 0) < session.get("page_count", 0):
        session["page_number"] += 1
    return redirect(url_for("extract.select_region"))


### an empty selection still produces well-formed, schema-valid XML
### with nothing worth converting -- caught here so result.html can
### flag it instead of showing a false "Valid"
def _extraction_is_empty(element_type, preview):
    if element_type == "paragraph":
        return not preview.strip()
    if element_type in ("orderedlist", "itemizedlist"):
        return not preview
    if element_type == "table":
        rows = ([preview["header"]] if preview["header"] else []) + preview["body"]
        return not any(cell.strip() for row in rows for cell in row)
    return False


### image has no DocBook fragment -- rendered on demand by
### extracted_image(). rect is PDF points. fitz work is in the worker;
### the emptiness check + validation are pure and stay here.
def _run_extraction(path, page_number, rect, element_type):
    result = {"element_type": element_type, "rect": list(rect), "page_number": page_number}
    if element_type == "image":
        return result

    raw = sandbox.run(pdfops.extract_region, path, page_number - 1, rect, element_type)
    result["element_type"] = raw["element_type"]
    result["preview"] = raw["preview"]
    result["xml"] = raw["xml"]

    result["empty"] = _extraction_is_empty(result["element_type"], result["preview"])
    if result["empty"]:
        result["valid"], result["validation_message"] = None, None
    else:
        result["valid"], result["validation_message"] = docbook.validate_fragment(result["xml"])

    return result


@bp.route("/extract/result")
def result():
    result_data = load_result(session.get("pdf_token"))
    if result_data is None:
        return redirect(url_for("extract.index"))
    return render_template(
        "result.html",
        breadcrumbs=_breadcrumbs("Result"),
        result=result_data,
        element_label=TYPE_LABELS.get(result_data["element_type"], ""),
    )


def _png_response(png_bytes):
    return Response(png_bytes, mimetype="image/png")


@bp.route("/extract/thumbnail")
@ratelimit.limit("render")
@pdf_processing_limit
def thumbnail():
    path = _current_pdf_path()
    if path is None:
        abort(404)
    try:
        png = sandbox.run(pdfops.render_page_png, path, 0, THUMBNAIL_ZOOM, MAX_RENDER_MEGAPIXELS)
    except Exception:
        abort(500)
    return _png_response(png)


@bp.route("/extract/page-thumbnail")
@ratelimit.limit("render")
@pdf_processing_limit
def page_thumbnail():
    path = _current_pdf_path()
    if path is None:
        abort(404)
    try:
        page_number = int(request.args.get("page", ""))
    except ValueError:
        abort(400)
    if page_number < 1:
        abort(404)
    try:
        ### an out-of-range page raises IndexError in the worker -> 404
        png = sandbox.run(pdfops.render_page_png, path, page_number - 1, PAGE_GRID_ZOOM, MAX_RENDER_MEGAPIXELS)
    except sandbox.SandboxError:
        abort(404)
    except Exception:
        abort(500)
    return _png_response(png)


@bp.route("/extract/page-image")
@ratelimit.limit("render")
@pdf_processing_limit
def page_image():
    path = _current_pdf_path()
    if path is None or "page_number" not in session:
        abort(404)
    ### not clamp_zoom'd -- select_region's coords are pinned to PREVIEW_ZOOM.
    ### a giant MediaBox hits the worker's RLIMIT_AS -> 500, not an OOM.
    try:
        png = sandbox.run(pdfops.render_page_png, path, session["page_number"] - 1, PREVIEW_ZOOM, None)
    except Exception:
        abort(500)
    return _png_response(png)


@bp.route("/extract/image")
@ratelimit.limit("render")
@pdf_processing_limit
def extracted_image():
    result_data = load_result(session.get("pdf_token"))
    if result_data is None or result_data["element_type"] != "image":
        abort(404)
    path = _current_pdf_path()
    if path is None:
        abort(404)
    try:
        png = sandbox.run(
            pdfops.render_region_png,
            path,
            result_data["page_number"] - 1,
            tuple(result_data["rect"]),
            IMAGE_ZOOM,
            WATERMARK_TEXT,
            MAX_RENDER_MEGAPIXELS,
        )
    except Exception:
        abort(500)
    return _png_response(png)


### back to drawing a new region on the same PDF/page -- select_region
### itself falls back to index if either is no longer in session
@bp.route("/extract/another", methods=["POST"])
def extract_another():
    return redirect(url_for("extract.select_region"))


@bp.route("/new-upload", methods=["POST"])
def new_upload():
    _clear_pdf()
    return redirect(url_for("extract.index"))
