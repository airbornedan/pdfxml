"""Waitress entry point for IIS HttpPlatformHandler on Windows Server.

IIS launches this via web.config (repo root) and passes the internal
loopback port in HTTP_PLATFORM_PORT. Windows Authentication and the
public port (5055) are handled by IIS in front of this process.
See deploy/iis/README.md.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

# Internal, AD-authenticated audience (web.config sets this too; belt and braces).
os.environ.setdefault("PDFXML_TRUSTED_NETWORK", "1")

from waitress import serve

from app import create_app

app = create_app()
port = int(os.environ.get("HTTP_PLATFORM_PORT", os.environ.get("PDFXML_PORT", "5000")))
serve(app, host="127.0.0.1", port=port, threads=8)
