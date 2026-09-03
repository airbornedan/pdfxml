########################################################################
### APP FACTORY
########################################################################
import os
import secrets

from flask import Flask, g, render_template, request, url_for
from flask_wtf.csrf import CSRFProtect, CSRFError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.extensions import (
    FLASK_SECRET_KEY, MAX_UPLOAD_BYTES, PROJECT_DIR, TRUSTED_NETWORK, logger, sweep_old_uploads,
)

csrf = CSRFProtect()


def create_app():
    ### absolute paths, not "../templates" -- under a frozen build the
    ### app package's own root_path is a synthetic path with no real
    ### directory behind it, so a path relative to it can't resolve
    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_DIR, "templates"),
        static_folder=os.path.join(PROJECT_DIR, "static"),
    )
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    ### dev only; prod (behind the proxy) keeps templates compiled once
    app.config["TEMPLATES_AUTO_RELOAD"] = not os.environ.get("PDFXML_BEHIND_PROXY")
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    csrf.init_app(app)

    ### ProxyFix trusts whatever X-Forwarded-For a client sends, so this
    ### must stay off unless a reverse proxy (deploy/pdfxml.nginx.conf) is
    ### the only thing that can reach this process directly -- otherwise
    ### anyone could spoof their address. PDFXML_BEHIND_PROXY is set in
    ### deploy/pdfxml.service, not locally. Same flag also means TLS is
    ### actually in front, so the session cookie can require it --
    ### forcing this on without TLS would mean the cookie never leaves
    ### the browser.
    if os.environ.get("PDFXML_BEHIND_PROXY"):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
        app.config["SESSION_COOKIE_SECURE"] = True

    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        ### self-contained: nothing is embedded cross-origin, none of
        ### these features are used
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        response.headers["Permissions-Policy"] = (
            "accelerometer=(), autoplay=(), camera=(), display-capture=(), "
            "encrypted-media=(), fullscreen=(), geolocation=(), gyroscope=(), "
            "magnetometer=(), microphone=(), midi=(), payment=(), "
            "picture-in-picture=(), screen-wake-lock=(), usb=(), xr-spatial-tracking=()"
        )
        ### getattr -- a CSRF rejection short-circuits before _set_csp_nonce
        ### runs, and a bare g.csp_nonce would turn the 400 into a 500
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; img-src 'self' data:; "
            f"script-src 'self' 'nonce-{getattr(g, 'csp_nonce', '')}'; "
            "style-src 'self'; form-action 'self'"
        )
        if os.environ.get("PDFXML_BEHIND_PROXY"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    ### fresh nonce per request, threaded into inline <script> tags via
    ### {{ g.csp_nonce }} -- keeps script-src at 'self' + nonce, not
    ### 'unsafe-inline'
    @app.before_request
    def _set_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)

    sweep_old_uploads()

    ### cache-busting -- appends the static file's own mtime as a query
    ### string, so editing it changes the URL and forces a fresh fetch
    ### regardless of what the browser cached under the old URL
    @app.template_global()
    def static_url(filename):
        path = os.path.join(app.static_folder, filename)
        try:
            version = int(os.path.getmtime(path))
        except OSError:
            version = 0
        return url_for("static", filename=filename, v=version)

    from app.blueprints.extract import bp as extract_bp
    from app.blueprints.imagecrop import bp as imagecrop_bp
    from app.blueprints.normalize import bp as normalize_bp
    app.register_blueprint(extract_bp)
    app.register_blueprint(imagecrop_bp)
    app.register_blueprint(normalize_bp)

    ### snapshot at build so registration, the template flag, and pages.py agree
    trusted = TRUSTED_NETWORK
    app.config["PDFXML_TRUSTED"] = trusted

    ### Process is served either way (pages.py picks the content);
    ### Troubleshooting only when trusted; the public profile also gets
    ### /terms + /privacy.
    from app.blueprints.pages import bp as pages_bp
    app.register_blueprint(pages_bp)
    if not trusted:
        from app.blueprints.sitepages import bp as site_bp
        app.register_blueprint(site_bp)

    @app.context_processor
    def _inject_flags():
        return {"trusted_network": trusted}

    ########################################################################
    ### ERROR HANDLING -- NOTHING SHOULD EVER SHOW A RAW TRACEBACK.
    def _err_page_from():
        return request.referrer or "/"

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        return render_template(
            "errorpage.html",
            err_message="Your session expired -- please try again.",
            err_page_from=_err_page_from(),
        ), 400

    @app.errorhandler(429)
    def handle_rate_limited(e):
        return render_template(
            "errorpage.html",
            err_title="Slow down a moment",
            err_message="You're going a bit fast -- wait a minute and retry.",
            err_page_from=_err_page_from(),
        ), 429

    @app.errorhandler(HTTPException)
    def handle_http_exception(e):
        return render_template(
            "errorpage.html", err_message=e.description, err_page_from=_err_page_from()
        ), e.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(e):
        logger.exception("Unhandled exception on %s", request.path)
        return render_template(
            "errorpage.html",
            err_message="Something went wrong. Please try again.",
            err_page_from=_err_page_from(),
        ), 500

    return app
