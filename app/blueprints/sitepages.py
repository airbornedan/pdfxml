########################################################################
### SITEPAGES -- Terms / Privacy, registered only on the public profile.
### mistune, same as pages.py. The public how-to is the Process card.
########################################################################
import os
import re

import mistune
from flask import Blueprint, abort, render_template

from app.extensions import PROJECT_DIR

bp = Blueprint("site", __name__)

_CONTENT = os.path.join(PROJECT_DIR, "content")
_render_markdown = mistune.create_markdown(escape=True, plugins=["table"])

### key -> (file under content/, page title)
_PAGES = {
    "terms": ("legal/terms.md", "Terms of use"),
    "privacy": ("legal/privacy.md", "Privacy"),
}

### strip editor <!-- REVIEW --> notes and a leading "# Title"
### (sitepage.html renders the heading). escape=True would print them.
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_LEADING_H1_RE = re.compile(r"\A\s*#\s.*\n")


def _page(key):
    rel, title = _PAGES[key]
    path = os.path.join(_CONTENT, rel)
    if not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        text = _COMMENT_RE.sub("", f.read())
    body = _render_markdown(_LEADING_H1_RE.sub("", text.lstrip()))
    return render_template("sitepage.html", title=title, body=body)


@bp.route("/terms")
def terms():
    return _page("terms")


@bp.route("/privacy")
def privacy():
    return _page("privacy")
