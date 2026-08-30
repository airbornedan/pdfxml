# PDFXML

Pull text, lists, tables, and images out of a PDF as **DocBook 5 XML
fragments** (or a PNG), ready to paste into a CMS. Built for technical
writers recovering content from PDFs where the editable source is lost
or awkward to convert.

- Flask + PyMuPDF, no external binaries (no Ghostscript / poppler / ImageMagick).
- No accounts, no database. An uploaded PDF is processed in an isolated
  sandbox and deleted within ~20 minutes.
- One codebase, three ways to run.

## Running it

| | Who | How |
|---|---|---|
| **Desktop** | one user, Windows | ship the single `pdfxml.exe` — build with `deploy/windows/build_windows.bat` |
| **Internal server** | a team, private network | gunicorn + nginx behind an AD-gated proxy — `deploy/pdfxml.service` |
| **Public server** | anyone, internet-facing | hardened profile — `deploy/pdfxml.public.service` |

Which behaviours are on (Process/Troubleshooting pages, rate limiting,
branding) is chosen by the `PDFXML_TRUSTED_NETWORK` env var, hardened by
default. Full setup, configuration, and deployment steps are in
**[`pdfxml.md`](pdfxml.md)**.

## Local development

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py        # http://127.0.0.1:5000
```

`run.py` runs the hardened profile; `PDFXML_TRUSTED_NETWORK=1 .venv/bin/python run.py`
for the internal view (Process/Troubleshooting pages, no rate limiting).

## Tests

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
