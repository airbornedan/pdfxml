"""Shared fixtures. The sandbox (app/sandbox.py) runs for real here --
it's fast enough (~0.2s/op on Linux) and worth exercising."""
import threading

import fitz
import pytest
from werkzeug.serving import make_server

from app import create_app


@pytest.fixture(autouse=True)
def _reset_ratelimit():
    """Rate-limit counters are module-level; clear them between tests."""
    from app import ratelimit

    for bucket in ratelimit._hits.values():
        bucket.clear()
    yield


def _make_app():
    app = create_app()
    app.config.update(WTF_CSRF_ENABLED=False, TESTING=True)
    return app


@pytest.fixture
def client():
    """Hardened profile (PDFXML_TRUSTED_NETWORK unset)."""
    return _make_app().test_client()


@pytest.fixture
def trusted_client(monkeypatch):
    """Trusted profile -- flip the flag everywhere it was import-bound."""
    monkeypatch.setattr("app.TRUSTED_NETWORK", True, raising=False)
    monkeypatch.setattr("app.ratelimit.TRUSTED_NETWORK", True, raising=False)
    monkeypatch.setattr("app.extensions.TRUSTED_NETWORK", True, raising=False)
    return _make_app().test_client()


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory):
    """A 2-page PDF: a paragraph in the top half of page 1, a bulleted
    list (ASCII '-' markers) in the bottom half; page 2 has a 3-line
    paragraph then, after a clear gap, a one-line second paragraph."""
    path = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((72, 100), "This is a plain paragraph of body text on the first page.", fontsize=12)
    p1.insert_text((72, 400), "- first bullet item\n- second bullet item\n- third bullet item",
                   fontsize=12)
    p2 = doc.new_page(width=612, height=792)
    for i, line in enumerate(["First paragraph, line one of three,",
                              "line two continues the thought,",
                              "and line three wraps it up."]):
        p2.insert_text((72, 120 + i * 15), line, fontsize=11)
    p2.insert_text((72, 210), "A second paragraph, clearly separated.", fontsize=11)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture(scope="session")
def live_url():
    """A real HTTP server in a thread, for the playwright test."""
    app = _make_app()
    srv = make_server("127.0.0.1", 0, app, threaded=True)
    port = srv.server_port
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()
