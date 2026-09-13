########################################################################
### CONVERT -- whole-document HTML/AI-paste -> Paligo dialect.
###
### Distinct from Fix XML (/check): that tool assumes the paste is
### already one Paligo <section> topic with a few foreign tags mixed in
### somewhere inside it, and lints its structure. This one assumes
### nothing about structure at all -- raw HTML copied off a web page or
### out of an AI chat, no <section>, headings and paragraphs still in
### HTML's own tags. It unwraps AI-added wrapper elements
### (article/div/body/...) and converts top-level lists and tables
### (HTML or CALS) to Paligo's dialect via app/paligo.py's real
### converters. Headings, <p>, and anything else outside a list/table
### pass through untouched -- inferring <section>/<title> nesting from
### heading levels is a judgment call this tool deliberately leaves to
### a person, not a guess it makes for them.
########################################################################
from flask import Blueprint, render_template, request, url_for

from app import paligo

bp = Blueprint("convert", __name__)


@bp.route("/convert", methods=["GET", "POST"])
def convert_html():
    src = request.form.get("html", "") if request.method == "POST" else ""
    submitted = request.method == "POST"
    output, changed, diagnostic = (None, False, None)

    if submitted:
        output, changed, diagnostic = paligo.normalize(src)

    return render_template(
        "convert.html",
        breadcrumbs=[("Home", url_for("extract.index")), ("Convert HTML", "")],
        src=src,
        submitted=submitted,
        output=output,
        changed=changed,
        diagnostic=diagnostic,
    )
