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
    assert n == 2
    with pytest.raises(sandbox.SandboxError):
        sandbox.run(pdfops.page_count, "/no/such/file.pdf")


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
