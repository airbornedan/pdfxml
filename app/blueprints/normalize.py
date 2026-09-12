########################################################################
### NORMALIZE -- paste an existing Paligo topic, get told what's wrong
### and where, with a content-preserving fix offered when one applies.
###
### Two passes before app/lml.py's structural checks ever run:
###   1. app/dialect.py -- translate tags that mean the same thing as
###      one of Paligo's own but aren't (HTML lists/tables, CALS tables,
###      HTML bold/italic), the shape a topic comes back in after a trip
###      through an AI chat.
###   2. app/lml.py -- nesting/pairing/emptiness checks for content
###      pasted into the wrong spot (the Extract-tool failure mode).
########################################################################
from flask import Blueprint, render_template, request, url_for

from app import dialect, fixes as fixes_mod, lml

bp = Blueprint("normalize", __name__)


@bp.route("/check", methods=["GET", "POST"])
def check_xml():
    src = request.form.get("xml", "") if request.method == "POST" else ""
    submitted = request.method == "POST"
    summary, findings, lines, translated = (None, [], [], [])

    if submitted:
        src = src.replace("\r\n", "\n").replace("\r", "\n")
        src = lml.strip_xinfo_attrs(src)
        src, translated, findings = dialect.translate(src)
        findings = findings + (
            lml.check_tags(src)
            + lml.check_tables(src)
            + lml.check_lists(src)
            + lml.check_mediaobjects(src)
            + lml.check_sections(src)
            + lml.check_paragraphs(src)
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
        translated=translated,
    )
