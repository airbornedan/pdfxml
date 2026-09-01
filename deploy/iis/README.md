# PDFXML on fatwxsweb1 (IIS, Windows Server 2022)

Live at **http://fatwxsweb1:5055** — Windows Authentication (HTTP 401
challenge), no anonymous access. Any authenticated domain user gets in.

## How it's hosted

```
Browser ── :5055 ──> IIS site "PDFXML" (Windows Auth)
                        └─ HttpPlatformHandler ──> .venv python + waitress
                           (web.config)             deploy/iis/serve_iis.py
                                                    127.0.0.1:%HTTP_PLATFORM_PORT%
```

- App root: `E:\PDFXML` (share: `\\fatwxsweb1\PDFXML`)
- Profile: internal/AD-gated — `PDFXML_TRUSTED_NETWORK=1`, sandbox
  auto-disabled on Windows, `PDFXML_BEHIND_PROXY` unset (plain HTTP)
- Logs: `E:\PDFXML\logs\pdfxml*.log` (stdout/stderr of the python process)

## Deploys (no server admin needed)

Push to `main` → `.github/workflows/deploy.yml` runs on the self-hosted
runner on fatwxsweb1 (service `actions.runner.*`, NETWORK SERVICE):
stop app (rename `web.config` away) → robocopy sync → pip install →
restore `web.config` → smoke test. Re-run manually from the repo's
Actions tab (workflow_dispatch).

## Manual restart (no admin)

Create or re-save `E:\PDFXML\deploy\iis\restart.trigger` — IIS recycles the
python process on any change to that file (`recycleOnFileChange`).

## One-time server setup

`deploy/iis/setup-server.ps1` as Administrator on the server. Installs
Python 3.12 / Git / HttpPlatformHandler, builds the venv, creates the IIS
site with Windows Auth on port 5055, opens the firewall, and registers the
Actions runner (pass `-RunnerToken` from repo Settings → Actions → Runners →
New self-hosted runner).

## Notes

- `web.config` (repo root) pins absolute `E:\PDFXML` paths on purpose.
- Dependencies for this host: `deploy/iis/requirements-iis.txt`
  (core + waitress; gunicorn doesn't run on Windows).
- Keep `requestLimits maxAllowedContentLength` in `web.config` in sync with
  the app's `MAX_UPLOAD_BYTES` (50MB).
