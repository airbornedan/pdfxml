########################################################################
### EXTENSIONS -- SHARED HELPERS: TEMP UPLOAD FILES, PROCESSING LIMIT, LOGGING
########################################################################
import logging
import json
import os
import secrets
import sys
import time
import tomllib
from functools import wraps
from threading import BoundedSemaphore

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

### everyday behavior tuning lives in config.toml, not env vars or
### code -- deployment concerns (mode, proxy, paths, port) stay env
### vars. Missing file or missing keys fall back to the defaults below.
try:
    with open(os.path.join(PROJECT_DIR, "config.toml"), "rb") as f:
        _config = tomllib.load(f)
except FileNotFoundError:
    _config = {}


def _cfg(section, key, default):
    return _config.get(section, {}).get(key, default)


### env > config.toml > default -- config.toml is one shared file, so a
### per-install override has to be an env var (as with PDFXML_PORT).
def _env_int(name, fallback):
    raw = os.environ.get(name)
    try:
        return int(raw) if raw else fallback
    except ValueError:
        return fallback

### only a frozen PyInstaller build needs a separate data dir -- it
### extracts to a fresh temp location every launch and wipes it on
### exit. getattr(sys, "frozen", False) is PyInstaller's own flag.
if getattr(sys, "frozen", False):
    import platformdirs
    DATA_DIR = platformdirs.user_data_dir("PDFXML", "SurePoint")
else:
    DATA_DIR = PROJECT_DIR
os.makedirs(DATA_DIR, exist_ok=True)

UPLOAD_DIR = os.environ.get("PDFXML_UPLOAD_DIR", os.path.join(DATA_DIR, "uploads"))

### local dev server (run.py) / desktop build (desktop_launcher.py)
### only -- gunicorn's own --bind flag governs the real deployment.
### 5000 collides with macOS AirPlay Receiver, and Windows can reserve
### ports too -- override per-machine, not here.
PORT = int(os.environ.get("PDFXML_PORT", "5000"))

MAX_UPLOAD_BYTES = _cfg("upload", "max_bytes", 50 * 1024 * 1024)  # generous for a scanned/watermarked doc, still bounded

### measured from last access (upload_path() bumps mtime), not upload
### time -- only an abandoned upload goes idle long enough to sweep
UPLOAD_MAX_AGE_SECONDS = _cfg("upload", "max_age_minutes", 20) * 60

### concurrent PDF work per worker -- resource guard, not a per-user
### limit. Effective concurrency = gunicorn workers x this.
PDF_PROCESSING_SLOTS = BoundedSemaphore(
    value=_env_int("PDFXML_MAX_CONCURRENT", _cfg("processing", "max_concurrent", 3))
)

### on-screen page preview and region-select zoom; submitted coordinates
### divide back to PDF points in this space.
PREVIEW_ZOOM = _cfg("render", "preview_zoom", 1.5)
IMAGE_ZOOM = _cfg("render", "image_dpi", 600) / 72  # PyMuPDF's 1.0 zoom == 72 dpi
THUMBNAIL_ZOOM = _cfg("render", "thumbnail_zoom", 0.3)  # first-page sanity check on upload.html, not a real preview
PAGE_GRID_ZOOM = _cfg("render", "page_grid_zoom", 0.5)  # page-select thumbnail grid on choose_page.html

### pixmap-area ceiling -- a huge MediaBox at full zoom would OOM.
### Letter/A4 @ 600dpi is ~34MP; past 50MP clamp_zoom() drops the dpi.
MAX_RENDER_MEGAPIXELS = _cfg("render", "max_megapixels", 50)


def clamp_zoom(width_pt, height_pt, zoom):
    pixels = (width_pt * zoom) * (height_pt * zoom)
    ceiling = MAX_RENDER_MEGAPIXELS * 1_000_000
    if pixels <= ceiling:
        return zoom
    return zoom * (ceiling / pixels) ** 0.5


### the exact diagonal watermark text stamped on every page -- not used
### as running body text anywhere in these manuals
WATERMARK_TEXT = _cfg("watermark", "text", "SurePoint Ag Systems")

### the sandbox worker's ceilings (app/sandbox.py). POSIX server only;
### direct call on Windows / frozen.
SANDBOX_TIMEOUT_SECONDS = _cfg("sandbox", "timeout_seconds", 25)
SANDBOX_MEMORY_MB = _cfg("sandbox", "memory_mb", 1536)
SANDBOX_CPU_SECONDS = _cfg("sandbox", "cpu_seconds", 20)

### trusted audience (LAN / AD proxy / desktop). Unset = the hardened,
### internet-facing default: no Process pages, rate limiting on, generic
### branding. Fail closed. Set by desktop_launcher.py + deploy/pdfxml.service.
TRUSTED_NETWORK = os.environ.get("PDFXML_TRUSTED_NETWORK") == "1"

### secret key -- generated once, persisted to disk, same pattern as
### the sibling COBWEBS/IMPS apps
SECRET_KEY_PATH = os.path.join(DATA_DIR, ".secret_key")
if os.path.exists(SECRET_KEY_PATH):
    with open(SECRET_KEY_PATH) as f:
        FLASK_SECRET_KEY = f.read().strip()
else:
    FLASK_SECRET_KEY = secrets.token_hex(32)
    with open(SECRET_KEY_PATH, "w") as f:
        f.write(FLASK_SECRET_KEY)
    os.chmod(SECRET_KEY_PATH, 0o600)

### logging -- stderr, same shape as the sibling apps' logger
logger = logging.getLogger("pdfxml")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False


def pdf_processing_limit(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        with PDF_PROCESSING_SLOTS:
            return f(*args, **kwargs)
    return decorated_function


########################################################################
### PER-SESSION UPLOAD STORAGE -- random-token filenames, never a
### user-controllable path. One PDF per session -- a fresh upload
### replaces the old one.
########################################################################
def save_upload(file_storage):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    token = secrets.token_hex(16)
    file_storage.save(os.path.join(UPLOAD_DIR, f"{token}.pdf"))
    return token


def upload_path(token):
    ### token comes from our own secrets.token_hex() output, never
    ### request data directly -- hex-checked anyway as defense in depth
    if not token or not all(c in "0123456789abcdef" for c in token):
        return None
    path = os.path.join(UPLOAD_DIR, f"{token}.pdf")
    if not os.path.isfile(path):
        return None
    try:
        os.utime(path, None)  # mark as just used -- see UPLOAD_MAX_AGE_SECONDS
    except OSError:
        ### can't access file clock, so ignore.
        return None
    return path


def delete_upload(token):
    path = upload_path(token)
    if path:
        os.remove(path)
    delete_result(token)


def sweep_old_uploads():
    if not os.path.isdir(UPLOAD_DIR):
        return
    cutoff = time.time() - UPLOAD_MAX_AGE_SECONDS
    for name in os.listdir(UPLOAD_DIR):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
            os.remove(path)


########################################################################
### LAST EXTRACTION RESULT -- can exceed the ~4KB session cookie, so
### this lives on disk keyed by the same token as the upload, not in
### session[] directly.
########################################################################
def save_result(token, result_dict):
    path = upload_path(token)
    if path is None:
        return
    with open(f"{path}.result.json", "w") as f:
        json.dump(result_dict, f)


def load_result(token):
    path = upload_path(token)
    if path is None:
        return None
    result_path = f"{path}.result.json"
    if not os.path.isfile(result_path):
        return None
    with open(result_path) as f:
        return json.load(f)


def delete_result(token):
    if not token or not all(c in "0123456789abcdef" for c in token):
        return
    result_path = os.path.join(UPLOAD_DIR, f"{token}.pdf.result.json")
    if os.path.isfile(result_path):
        os.remove(result_path)
