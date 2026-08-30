# PDFXML -- Setup & Configuration

Converts unstructured PDFs into DocBook XML fragments (paragraphs,
lists, tables) plus cropped/watermarked images, for hand-off into
Paligo. Flask app, PyMuPDF for all PDF handling. No accounts, no
login. It runs three ways -- as a local desktop app, behind an
AD-gated reverse proxy on the internal network, or internet-facing on
a public host -- selected by `PDFXML_TRUSTED_NETWORK` (see Deployment
profiles).

## Requirements

- Python 3.12
- `requirements.txt` is the core runtime set; the rest pull it in with
  `-r` and add to it:
  - `requirements-server.txt` -- core + gunicorn (shapes B/C)
  - `deploy/windows/requirements-desktop.txt` -- core + pyinstaller (the
    `pdfxml.exe` build)
  - `requirements-dev.txt` -- core + pytest + Playwright (the UI tests)
- `requirements.lock` is the fully pinned, hash-verified transitive set,
  compiled from `requirements-server.txt` (`uv pip compile
  requirements-server.txt --generate-hashes -o requirements.lock`). Use
  it for the server deploy and CI; regenerate it after any change to
  `requirements.txt` or `requirements-server.txt`.
- XML validation is `lxml`-based and in-process -- no
  `xmllint`/`libxml2-utils` system package needed.

## First-time setup (any environment)

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt                 # dev + tests
.venv/bin/pip install --require-hashes -r requirements.lock   # server / CI
```

The in-app Process / Troubleshooting pages are plain Markdown under
`content/` (one `.md` file per tab; see `content/README.md`). Edited in
the repo and committed -- there is no in-app editor.

## Configuration

Everyday behavior tuning lives in `config.toml` at the project root. A
missing file, or a missing key, falls back to the defaults the app
shipped with; nothing breaks if it's deleted. Sections:

- `[upload]` -- max size, idle-sweep timeout
- `[processing]` -- `max_concurrent` renders per worker (`PDFXML_MAX_CONCURRENT` overrides)
- `[render]` -- preview/thumbnail/output zoom, `max_megapixels` OOM ceiling
- `[watermark]` -- `text` redacted from extracted images; set `""` to skip redaction
- `[sandbox]` -- the per-render subprocess's `timeout_seconds` / `memory_mb` / `cpu_seconds`
- `[ratelimit]` -- per-IP `upload_per_minute` / `render_per_minute` (hardened profile only)

Deployment concerns stay environment variables, not `config.toml` --
they vary per install.

## PDF sandbox

On POSIX servers every PyMuPDF call (parse, render, extract) runs in a
short-lived `forkserver` child with `RLIMIT_AS`, `RLIMIT_CPU`, and a
wall-clock kill (`config.toml` `[sandbox]`). A hostile PDF that trips a
MuPDF memory bug, blows up allocation, or loops forever takes down that
one child, not the request process; the route returns 500.

- **Windows / the frozen desktop build** call PyMuPDF directly (single
  local user, and spawning from a frozen exe is its own problem).
  `PDFXML_SANDBOX=0` forces that fallback anywhere.
- If you tighten the systemd unit's `SystemCallFilter` /
  `RestrictAddressFamilies`, keep `AF_UNIX` and the default
  fork/clone/socket calls -- the forkserver needs them.
  `MemoryDenyWriteExecute=true` breaks native deps (lxml) -- leave it off.

## Environment variables

All optional; sane defaults if unset.

| Variable | Default | Purpose |
|---|---|---|
| `PDFXML_PORT` | `5000` | local dev server / desktop build port |
| `PDFXML_UPLOAD_DIR` | `<project>/uploads` | per-session upload/result scratch space |
| `PDFXML_BEHIND_PROXY` | unset | a TLS-terminating reverse proxy is in front: enables ProxyFix, `Secure` cookie, HSTS. Both `.service` units set it. |
| `PDFXML_TRUSTED_NETWORK` | unset | the audience is trusted (LAN / AD proxy / desktop). See Deployment profiles below. |
| `PDFXML_MAX_CONCURRENT` | `config.toml` `[processing] max_concurrent`, else `3` | in-process cap on concurrent PDF renders; env wins over `config.toml` |
| `PDFXML_WORKERS` | `1` (`2` in `pdfxml.public.service`) | gunicorn worker count; the `.service` units set it explicitly |
| `PDFXML_SANDBOX` | unset (enabled) | `0` disables the per-render subprocess sandbox (POSIX server only) |

The render cap is **per worker process**, so effective concurrency is
`PDFXML_WORKERS` x `PDFXML_MAX_CONCURRENT`. Raise `PDFXML_WORKERS` only
if you also lower the cap, or the box will run more concurrent MuPDF
renders than intended.

## Deployment profiles

`PDFXML_TRUSTED_NETWORK` is orthogonal to `PDFXML_BEHIND_PROXY` (which
is only about whether TLS/a proxy sits in front). **Unset is the
hardened, internet-facing default** -- fail closed:

| | `TRUSTED_NETWORK=1` | unset (hardened) |
|---|---|---|
| `/process` | SurePoint tabs (`content/process/`) | generic guide (`content/process-public/`) |
| `/troubleshooting` | served | route absent |
| `/terms`, `/privacy` + footer | absent | served (`content/legal/*.md`) |
| index cards | Process, Extract, Crop, Troubleshooting | Process, Extract, Crop |
| per-IP rate limiting | off | on (`config.toml` `[ratelimit]`) |
| Style Guide link in the topbar | shown | hidden |
| watermark redaction | per `config.toml` `[watermark] text` | same (set `text = ""` to skip) |

- **Desktop build** (`desktop_launcher.py`) sets it automatically.
- **Internal / AD-gated server** -- `deploy/pdfxml.service` sets it.
- **Public server** -- `deploy/pdfxml.public.service`; does *not* set it.
- **Local `python run.py`** -- unset, so you get the hardened view;
  run `PDFXML_TRUSTED_NETWORK=1 python run.py` for the internal one.

## Secrets

`.secret_key` (session signing / CSRF) is generated on first run and
`chmod 600`'d automatically -- nothing to configure. Deleting it forces
a new key, which drops any session mid-flight (an in-progress upload
or wizard step, not an account -- there isn't one).

## Local development

```
.venv/bin/python3 run.py
```

Runs Flask's own dev server (`debug=False` always, regardless of
environment). `TEMPLATES_AUTO_RELOAD` is on, so template edits show up
without a restart; Python changes still need one. `PDFXML_BEHIND_PROXY`
stays unset locally, so `http://localhost` works without TLS.

`run.py` always binds `127.0.0.1` on an unprivileged port
(`PDFXML_PORT`, default 5000) -- no elevated rights needed. A server
deploy doesn't use `run.py` as a script; gunicorn imports `run:app`
directly (see Deploying).

## Deploying

Three shapes, all gunicorn + nginx + systemd on the server side. Pick
one. Every `deploy/` file also has install commands in its header
comment.

### A. Desktop (single user, Windows)

Not a server deploy. Shipped as one file, `pdfxml.exe` -- no Python on
the target. `desktop_launcher.py` (the frozen entry point) sets
`PDFXML_TRUSTED_NETWORK=1` itself.

**Building it: [`deploy/windows/BUILD.md`](deploy/windows/BUILD.md)** --
the full step-by-step, written to follow cold. In short: on Windows,
with Python 3.12, from an intact checkout, run
`deploy\windows\build_windows.bat` -> `dist\pdfxml.exe`. The spec
bundles `templates/ static/ schema/ content/ config.toml`.
`deploy/windows/windows_readme.txt` is the note that ships with the exe.

- Build on the **oldest Windows you must support** -- an exe built on
  Win11 may not start on Win8.1; older to newer is fine.
- Unsigned one-file exe trips SmartScreen ("unknown publisher") and
  often endpoint AV/AppLocker (it unpacks to `%TEMP%` each launch).
  "More info -> Run anyway", or code-sign it. For a faster start and
  less AV friction switch the spec to one-dir (add a `COLLECT()`).
- Frozen mode is already handled: `desktop_launcher.py` calls
  `multiprocessing.freeze_support()` first, and `app/sandbox.py`
  disables the subprocess isolation under `sys.frozen` (forkserver
  can't work in an exe) -- PDF ops run in-process, which is fine for a
  single local user. `platformdirs` keeps `uploads/` and `.secret_key`
  under `%LOCALAPPDATA%`.

### B. Internal / AD-gated server

Trusted audience on a private network. `deploy/pdfxml.service` +
`deploy/pdfxml.nginx.conf`. The unit sets `PDFXML_BEHIND_PROXY=1`,
`PDFXML_TRUSTED_NETWORK=1`, and `PDFXML_WORKERS=1`.

1. Copy the checkout to the host -- **not** `.venv/`, `.secret_key`, or
   `uploads/` (architecture-specific or this box's own state).
2. `python3 -m venv .venv && .venv/bin/pip install --require-hashes -r requirements.lock`
3. Edit `deploy/pdfxml.service` (User/Group, `WorkingDirectory`, venv
   path) and `deploy/pdfxml.nginx.conf` (`server_name`, cert paths).
4. TLS cert: a private address isn't publicly resolvable, so Let's
   Encrypt can't validate it -- use a self-signed cert or an internal CA.
5. Install and enable both units (header comments have the commands).
6. Firewall to 80/443 plus your admin access; front it with the
   AD-gated proxy. There is no login to fall back on.

### C. Public / internet-facing

Hardened profile -- `deploy/pdfxml.public.service` +
`deploy/pdfxml.public.nginx.conf`. `PDFXML_TRUSTED_NETWORK` is **not**
set: `/process` serves the generic guide (`content/process-public/`),
no `/troubleshooting`, per-IP rate limiting on, `/terms` + `/privacy`
served, Style Guide link hidden.

1. **DNS** -- point an A/AAAA record at the host.
2. **User + layout** -- dedicated service account, code under
   `/srv/pdfxml`, writable state under `/var/lib/pdfxml` (the unit's
   `StateDirectory`; `PDFXML_UPLOAD_DIR` points there):

   ```
   sudo useradd --system --home /srv/pdfxml --shell /usr/sbin/nologin pdfxml
   sudo rsync -a --exclude .venv --exclude .secret_key --exclude uploads/ ./ /srv/pdfxml/
   sudo chown -R pdfxml:pdfxml /srv/pdfxml
   sudo -u pdfxml python3 -m venv /srv/pdfxml/.venv
   sudo -u pdfxml /srv/pdfxml/.venv/bin/pip install --require-hashes -r /srv/pdfxml/requirements.lock
   ```
3. **Site content** -- `content/process-public/*.md` (the generic
   "Process" guide) is ready as-is. Edit `content/legal/terms.md` and
   `content/legal/privacy.md`: fill every `<!-- REVIEW -->` (operator
   name, a real contact address, governing jurisdiction). Both already
   carry an "EU/EEA/UK not available" clause; if you want to *enforce*
   that, add a geo block in nginx or at the CDN (see the nginx conf
   comment). The renderer strips the REVIEW comments.
4. **systemd** -- edit `deploy/pdfxml.public.service` for real paths;
   size `MemoryMax` to roughly `[sandbox] memory_mb` x
   (`PDFXML_WORKERS` x `PDFXML_MAX_CONCURRENT`) plus slack. Install as
   `pdfxml.service`, `daemon-reload`, `enable --now`.
5. **nginx + TLS** -- edit `deploy/pdfxml.public.nginx.conf`
   (`pdfxml.example.com` -> real host), then
   `sudo certbot --nginx -d <host>`. The config already has the
   ACME-challenge carve-out, HTTP->HTTPS, HTTP/2, modern TLS, and
   `limit_req`/`limit_conn` as an edge backstop in front of the app's
   own limiter.
6. **Firewall** to 80/443 plus admin access.
7. Sanity-check the profile after first boot: `/process` should 404 and
   `/terms` should load.

## Maintenance

- Uploaded PDFs and their extraction results auto-sweep after 20
  minutes of inactivity (`UPLOAD_MAX_AGE_SECONDS` in
  `app/extensions.py`) -- nothing manual.
- Page content is Markdown in the repo, version-controlled, nothing
  separate to back up: `content/process/*.md` +
  `content/troubleshooting/*.md` (trusted), `content/process-public/*.md`
  + `content/legal/*.md` (public). See `content/README.md`. `uploads/`
  is disposable; `.secret_key` regenerates itself.
- Rate-limit counters (`app/ratelimit.py`) are per-process and
  in-memory -- they reset on restart, which is fine for a coarse abuse
  guard.
- Max upload size is 50MB (`MAX_UPLOAD_BYTES`), mirrored in both
  nginx configs' `client_max_body_size` -- keep them in sync.
- After editing `requirements.txt` or `requirements-server.txt`,
  regenerate `requirements.lock` (`uv pip compile
  requirements-server.txt --generate-hashes -o requirements.lock`).
