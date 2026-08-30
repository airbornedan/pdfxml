"""App boots, core routes answer, security headers are intact."""
import re


def test_core_routes(client):
    for path in ("/", "/extract/pdf", "/image-crop"):
        assert client.get(path).status_code == 200


def test_security_headers(client):
    h = client.get("/").headers
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["X-Frame-Options"] == "DENY"
    assert h["Cross-Origin-Resource-Policy"] == "same-origin"
    assert h["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "Permissions-Policy" in h
    assert "X-Permitted-Cross-Domain-Policies" in h


def test_csp_has_no_unsafe_inline_and_nonce_coheres(client):
    r = client.get("/image-crop")
    csp = r.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in csp
    assert "style-src 'self'" in csp
    header_nonce = re.search(r"nonce-([\w-]+)", csp).group(1)
    body_nonce = re.search(rb'<script nonce="([\w-]+)"', r.data).group(1).decode()
    assert header_nonce == body_nonce
    # different every request
    assert re.search(r"nonce-([\w-]+)", client.get("/image-crop").headers["Content-Security-Policy"]).group(1) != header_nonce


def test_no_inline_style_attributes(client):
    for path in ("/", "/image-crop", "/extract/pdf", "/terms", "/process"):
        body = client.get(path).data.decode()
        assert 'style="' not in body and "style='" not in body, path


def test_csrf_failure_is_400_not_500():
    # a fresh app WITH csrf on
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    r = app.test_client().post("/upload", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
    assert "Content-Security-Policy" in r.headers  # headers still applied on the error path


def test_unhandled_paths_render_error_page_not_traceback(client):
    r = client.get("/definitely-not-a-route")
    assert r.status_code == 404
    assert b"Traceback" not in r.data
