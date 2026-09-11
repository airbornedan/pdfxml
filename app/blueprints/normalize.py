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

from app import fixes as fixes_mod
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
    submitted = request.method == "POST"
    summary, findings, lines = (None, [], [])

    if submitted:
        src = src.replace("\r\n", "\n").replace("\r", "\n")
        src = lml.strip_xinfo_attrs(src)
        findings = (
            lml.check_tags(src)
            + lml.check_tables(src)
            + lml.check_lists(src)
            + lml.check_mediaobjects(src)
            + lml.check_sections(src)
        )

        seen = set()
        deduped = []
        for finding in findings:
            key = (finding.get("line") or 0, finding.get("message"), finding.get("tag"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(finding)
        findings = sorted(
            deduped, key=lambda f: (f.get("line") or 0, f.get("start") or 0)
        )
        for finding in findings:
            finding["_fixes"] = fixes_mod.suggest_fixes(src, finding)

        summary = lml.summarize(findings)
        lines = lml.build_lines(src, findings)

    return render_template(
        "check.html",
        breadcrumbs=[("Home", url_for("extract.index")), ("Check XML", "")],
        src=src,
        submitted=submitted,
        summary=summary,
        findings=findings,
        lines=lines,
    )
