########################################################################
### NORMALIZE -- paste any DocBook / HTML list or table, get it back in
### the exact form Paligo's XML source view accepts. app/paligo.py does
### the work; this is just the page. Shown on both deployment profiles.
###
### /check is the first piece of the "why won't this validate" tool:
### app/lml.py pairs opening/closing tags of known elements and marks
### the unmatched ones. No content-model checks, no editing yet.
########################################################################
from flask import Blueprint, render_template, request, url_for

from app import lml, paligo

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


@bp.route("/check", methods=["GET", "POST"])
def check_xml():
    src = request.form.get("xml", "") if request.method == "POST" else ""
    marked, unmatched = (None, 0)
    errors = []
    if request.method == "POST":
        src = lml.strip_xinfo_attrs(src)
        marked, unmatched = lml.check_tags(src)
        table_findings = lml.check_tables(src)
        list_findings = lml.check_lists(src)
        media_findings = lml.check_mediaobjects(src)
        section_findings = lml.check_sections(src)

        errors = list(table_findings) + list(list_findings) + list(media_findings) + list(section_findings)
        errors.sort(key=lambda f: f.get("line") or 0)

        seen = set()
        deduped = []
        for finding in errors:
            key = (finding.get("line") or 0, finding.get("message"), finding.get("tag"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(finding)
        errors = deduped

        if errors:
            marked = lml.highlight_findings(marked, errors)

    return render_template(
        "check.html",
        breadcrumbs=[("Home", url_for("extract.index")), ("Check XML", "")],
        src=src,
        marked=marked,
        unmatched=unmatched,
        errors=errors,
    )
