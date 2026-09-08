"""Upload and crop fixed-format agricultural display screenshots."""
import base64
import os

from flask import Blueprint, render_template, request

from app.extensions import MAX_UPLOAD_BYTES, save_upload, upload_path
from app.imageops import edge_detect_line_art
from app.ratelimit import limit
from crop_isobus import crop_isobus

bp = Blueprint("screenshot", __name__)
IMAGE_SUFFIX = ".image"


@bp.route("/screenshot", methods=["GET", "POST"])
@limit("upload")
def screenshot():
    error = None
    result = None
    if request.method == "POST":
        file = request.files.get("image")
        if file is None or file.filename == "":
            error = "Choose an image file first."
        elif file.mimetype not in {"image/png", "image/jpeg"}:
            error = "That doesn't look like a PNG or JPEG image."
        else:
            token = save_upload(file, IMAGE_SUFFIX)
            source = upload_path(token, IMAGE_SUFFIX)
            destination = f"{source}.cropped.png"
            try:
                crop_isobus(source, destination)
                with open(destination, "rb") as cropped:
                    result = base64.b64encode(cropped.read()).decode("ascii")
            except (OSError, ValueError):
                error = (
                    "That image is not a supported agricultural display screenshot."
                )
            finally:
                for path in (source, destination):
                    if path and os.path.isfile(path):
                        os.remove(path)

    return render_template(
        "screenshot.html",
        error=error,
        result=result,
        max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    )


@bp.route("/convert", methods=["GET", "POST"])
@limit("upload")
def convert():
    error = None
    result = None
    if request.method == "POST":
        file = request.files.get("image")
        if file is None or file.filename == "":
            error = "Choose an image file first."
        elif file.mimetype not in {"image/png", "image/jpeg"}:
            error = "That doesn't look like a PNG or JPEG image."
        else:
            token = save_upload(file, IMAGE_SUFFIX)
            source = upload_path(token, IMAGE_SUFFIX)
            destination = f"{source}.line-drawing.png"
            try:
                edge_detect_line_art(source, destination)
                with open(destination, "rb") as converted:
                    result = base64.b64encode(converted.read()).decode("ascii")
            except (OSError, ValueError, FileNotFoundError):
                error = "That image could not be converted into a line drawing."
            finally:
                for path in (source, destination):
                    if path and os.path.isfile(path):
                        os.remove(path)

    return render_template(
        "convert.html",
        error=error,
        result=result,
        max_upload_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    )