########################################################################
### NORMALIZE -- paste any DocBook / HTML list or table, get it back in
### the exact form Paligo's XML source view accepts. app/paligo.py does
### the work; this is just the page. Shown on both deployment profiles.
########################################################################
from flask import Blueprint, render_template, request, url_for

from app import paligo

bp = Blueprint("normalize", __name__)


@bp.route("/normalize", methods=["GET", "POST"])
def fix_xml():
    src = request.form.get("xml", "") if request.method == "POST" else ""
    output, changed, diagnostic = (None, False, None)
    if request.method == "POST":
        output, changed, diagnostic = paligo.normalize(src)

    return render_template(
        "normalize.html",
        breadcrumbs=[("Home", url_for("extract.index")), ("Fix XML", "")],
        src=src,
        output=output,
        changed=changed,
        diagnostic=diagnostic,
    )
