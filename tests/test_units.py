"""Unit-level checks that don't need a full request."""
import pytest


# --- upload_path -----------------------------------------------------
def test_upload_path_returns_none_when_it_cannot_touch_the_file(tmp_path, monkeypatch):
    """A file left by a server that ran as another user (sudo) -- we
    can't os.utime it. That must not 500; upload_path treats it as gone."""
    from app import extensions

    token = "a" * 32
    (tmp_path / f"{token}.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(extensions, "UPLOAD_DIR", str(tmp_path))

    assert extensions.upload_path(token) is not None            # normal case
    monkeypatch.setattr(extensions.os, "utime",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "denied")))
    assert extensions.upload_path(token) is None                # can't touch -> gone


def test_choose_pdf_recovers_from_an_untouchable_upload(client, tmp_path, monkeypatch):
    from app import extensions

    token = "b" * 32
    (tmp_path / f"{token}.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(extensions, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(extensions.os, "utime",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError(13, "denied")))

    with client.session_transaction() as s:
        s["pdf_token"] = token
        s["pdf_filename"] = "old.pdf"
    r = client.get("/extract/pdf")
    assert r.status_code == 200
    assert b"upload again" in r.data


# --- clamp_zoom -------------------------------------------------------
def test_clamp_zoom_noop_for_real_pages():
    from app.extensions import clamp_zoom

    z = 600 / 72
    assert clamp_zoom(612, 792, z) == z          # US Letter @ 600 dpi
    assert clamp_zoom(595, 842, 1.5) == 1.5      # A4 preview


def test_clamp_zoom_caps_a_giant_mediabox():
    from app.extensions import MAX_RENDER_MEGAPIXELS, clamp_zoom

    z = clamp_zoom(14400, 14400, 600 / 72)
    px = (14400 * z) ** 2
    assert px <= MAX_RENDER_MEGAPIXELS * 1_000_000 * 1.001


# --- rate limiter sliding window -------------------------------------
def test_ratelimit_window_expires(monkeypatch):
    from flask import Flask
    from werkzeug.exceptions import TooManyRequests

    from app import ratelimit

    monkeypatch.setattr(ratelimit, "TRUSTED_NETWORK", False)
    ratelimit._hits["upload"].clear()
    limit, window = ratelimit._RULES["upload"]

    clock = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])

    @ratelimit.limit("upload")
    def view():
        return "ok"

    ctx = Flask(__name__).test_request_context("/", environ_base={"REMOTE_ADDR": "9.9.9.9"})
    with ctx:
        for _ in range(limit):
            assert view() == "ok"
        with pytest.raises(TooManyRequests):
            view()
        clock[0] += window + 1          # everything ages out
        assert view() == "ok"


# --- sandbox wiring ----------------------------------------------------
def test_sandbox_runs_and_wraps_errors(sample_pdf):
    from app import pdfops, sandbox

    n = sandbox.run(pdfops.page_count, sample_pdf)
    assert n == 5
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(pdfops.page_count, "/no/such/file.pdf")


# --- docbook: page-ref flagging + list-marker stripping --------------
def test_page_refs_flagged_in_preview_not_removed():
    """Preview flags "(see page N)"; the XML keeps it verbatim."""
    from app.docbook import _tokens_html, _para_element, _serialize

    tokens = [("check the module (see page 40) before starting", False, False)]
    html = _tokens_html(tokens)
    assert '<span class="page-ref-flag">(see page 40)</span>' in html
    # text on either side is untouched
    assert "check the module " in html and " before starting" in html
    # the XML fragment keeps the literal reference -- nothing stripped
    xml = _serialize(_para_element(tokens))
    assert "(see page 40)" in xml and "page-ref-flag" not in xml


def test_page_ref_variants_flagged():
    from app.docbook import _tokens_html

    for src in ["do X (see pages 29-31) then Y",
                "the valve (page 29, Fig. 4) opens",
                "refer to (Page 7) now",
                "touch the row on the chart (see pg. 40) then",   # abbreviation
                "set the value (p. 12) before running"]:
        assert 'class="page-ref-flag"' in _tokens_html([(src, False, False)])
    # a digit must follow -- ordinary prose / other parentheticals are not flagged
    for src in ["pages are numbered 1 to 99",
                "replace the part (part 40) if worn",
                "check the pin (pin 4) seating"]:
        assert 'page-ref-flag' not in _tokens_html([(src, False, False)])


def test_list_markers_accept_dot_paren_style():
    """A period+close-paren marker (1.) must register, else no list items."""
    from app.docbook import _split_list_items

    def row(text):                       # (y0, y1, block, spans)
        return (0.0, 10.0, 0, [(text, False, False)])

    items, ordered = _split_list_items(
        [row("1.) Press the HOME button"),
         row("2.)  Open the settings page"),
         row("3.) Choose the device")]
    )
    assert ordered is True
    assert len(items) == 3
    assert items[0][0][0][0] == "Press the HOME button"    # marker peeled off
    # the plain-"1." and "(1)" styles still work
    items2, ordered2 = _split_list_items([row("1. plain step"), row("2. next step")])
    assert ordered2 is True and len(items2) == 2


def test_list_marker_glyph_stripped_even_as_its_own_span():
    from app.docbook import _merge_tokens, _strip_marker

    # bare glyph in its own span -> emptied, then dropped by _merge_tokens
    stripped = _strip_marker([("•", False, False), ("First item", False, False)])
    assert stripped[0][0] == ""
    assert _merge_tokens(stripped) == [("First item", False, False)]
    # glyph glued to the text, ordered marker, and a legit "e.g." start
    assert _strip_marker([("•First item", False, False)]) == [("First item", False, False)]
    assert _strip_marker([("1. Step one", False, False)]) == [("Step one", False, False)]
    assert _strip_marker([("• e.g. keep this", False, False)]) == \
        [("e.g. keep this", False, False)]


# --- markdown Process pages --------------------------------------------
def test_trusted_process_renders_the_surepoint_tabs(trusted_client):
    body = trusted_client.get("/process").data.decode()
    for label in ("Begin", "Extract text", "Extract tables", "Extract images", "Extract lists"):
        assert f">{label}<" in body
    assert body.count('class="tab-panel') == 5


def test_public_process_renders_the_generic_guide(client):
    body = client.get("/process").data.decode()
    for label in ("Overview", "Extract", "Crop an image"):
        assert f">{label}<" in body
    assert body.count('class="tab-panel') == 3
    assert "Paligo" not in body
