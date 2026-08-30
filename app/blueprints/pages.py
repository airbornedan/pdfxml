########################################################################
### PAGES -- Process (+ Troubleshooting), Markdown tabs from content/.
### One .md per tab, filename order, first line "# Label". Read-only.
### app.config["PDFXML_TRUSTED"] picks the content: SurePoint tabs, or
### the generic content/process-public/ guide. See content/README.md.
########################################################################
import os

import mistune
from flask import abort, Blueprint, current_app, render_template, url_for

from app.extensions import PROJECT_DIR

bp = Blueprint("pages", __name__)

CONTENT_DIR = os.path.join(PROJECT_DIR, "content")

_TRUSTED_PAGES = {
    "process": {"title": "Process", "dir": "process"},
    "troubleshooting": {"title": "Troubleshoot", "dir": "troubleshooting"},
}
_PUBLIC_PAGES = {
    "process": {"title": "Process", "dir": "process-public"},
}


def _pages():
    return _TRUSTED_PAGES if current_app.config.get("PDFXML_TRUSTED") else _PUBLIC_PAGES


### escape=True -- no raw HTML needed, and "<product>" / "</section>" in
### prose then render literally without backticking.
_render_markdown = mistune.create_markdown(escape=True, plugins=["table"])


def _split_label(text):
    lines = text.lstrip().splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "Untitled", text


def _read_tabs(page):
    page_dir = os.path.join(CONTENT_DIR, page["dir"])
    tabs = []
    if os.path.isdir(page_dir):
        for name in sorted(os.listdir(page_dir)):
            if not name.endswith(".md"):
                continue
            with open(os.path.join(page_dir, name), encoding="utf-8") as f:
                label, body = _split_label(f.read())
            tabs.append({"label": label, "content": _render_markdown(body)})
    return tabs or [{"label": page["title"], "content": ""}]


def _view(page_key):
    pages = _pages()
    if page_key not in pages:  # e.g. /troubleshooting on the public profile
        abort(404)
    page = pages[page_key]
    breadcrumbs = [("Home", url_for("extract.index")), (page["title"], "")]
    return render_template(
        "tabs_view.html",
        title=page["title"],
        tabs=_read_tabs(page),
        breadcrumbs=breadcrumbs,
    )


@bp.route("/process")
def process():
    return _view("process")


@bp.route("/troubleshooting")
def troubleshooting():
    return _view("troubleshooting")
