### DESKTOP LAUNCHER -- entry point for the PyInstaller build
### (pdfxml.exe), not run.py. Opens the browser once the
### server's listening, no reloader (Werkzeug's reloader re-execs the
### process, which frozen builds don't handle).
import multiprocessing
import os
import threading
import webbrowser

### app/sandbox.py imports multiprocessing; without this an un-guarded
### frozen exe re-runs this script per child. Must run first.
multiprocessing.freeze_support()

### the desktop build is a trusted single-user context. Set before
### app.extensions is imported below.
os.environ.setdefault("PDFXML_TRUSTED_NETWORK", "1")

from app import create_app  # noqa: E402
from app.extensions import PORT  # noqa: E402

app = create_app()


def _open_browser():
    webbrowser.open(f"http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    print("PDFXML is running -- close this window to stop it.")
    threading.Timer(1.5, _open_browser).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False)
