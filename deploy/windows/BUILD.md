# Building `pdfxml.exe`

Cold-start runbook for rebuilding the standalone Windows executable after
a code change. Assumes you have not looked at this in weeks. Follow it
top to bottom; every command is literal.

The build **must** happen on Windows (PyInstaller does not cross-compile).
These steps use the Windows 8.1 x64 VM and the path
`C:\Users\Administrator\Desktop\PDFXML\` throughout — adjust the username
if yours differs, but keep it on the Desktop (a real local disk).

---

## One-time setup on the Windows machine

Skip this if `py -3.12 --version` already prints `Python 3.12.x` in a
Command Prompt.

1. Download the Python **3.12** installer (any 3.12.x) from
   <https://www.python.org/downloads/>. It must be 3.12 — **not 3.11,
   not 3.13, not 3.8.** The build script checks and refuses anything else.
2. Run the installer. On the **first screen**, tick
   **"Add python.exe to PATH"** before clicking Install.
3. Open a new Command Prompt (Start → type `cmd` → Enter) and check:
   ```
   py -3.12 --version
   ```
   It should print `Python 3.12.x`. If it says the version was not found,
   the PATH box was missed — re-run the installer and tick it.

Nothing else is needed. No Visual Studio, no build tools — every
dependency ships a prebuilt Windows wheel.

---

## Every rebuild

### 1. Refresh the shared copy — on the Linux/dev machine

Get `main` up to date and re-export it into the VM's shared folder:

```
cd /home/dan/PDFXML
git checkout main
git pull
DEST=/home/dan/vmware/Win81x642016v10/host-shared-dita/PDFXML
rm -rf "$DEST" && mkdir -p "$DEST"
git archive --format=tar main | tar -x -C "$DEST"
```

(If you build directly from a `git clone` on the Windows box instead,
just `git pull` there and skip to step 3.)

### 2. Copy the project onto the Windows Desktop

In the VM, open the shared folder — it shows up as
`\\vmware-host\Shared Folders\host-shared-dita\` (or a mapped drive such
as `Z:\host-shared-dita\`, depending on VMware Tools).

Copy the whole **`PDFXML`** folder from there onto the **Desktop**. You
should end up with:

```
C:\Users\Administrator\Desktop\PDFXML\
```

Do **not** build straight from the shared folder — PyInstaller is slow
and unreliable over it, and the script will stop you.

If a `PDFXML` folder is already on the Desktop from last time, delete it
first, then copy the fresh one. (Or keep it and let the copy overwrite —
but a `dist\` or `.venv-build\` left inside from last time is fine, the
script cleans up `dist\` itself.)

### 3. Open a Command Prompt in the project folder

Start → type `cmd` → Enter, then:

```
cd C:\Users\Administrator\Desktop\PDFXML
```

### 4. Run the build

```
deploy\windows\build_windows.bat
```

You can also just double-click that file in Explorer — it finds its own
way to the project root either way.

What it does, in order (5–10 minutes total, mostly the first time):

| Step | First run | Later runs |
|---|---|---|
| create `.venv-build\` | ~1 min | skipped (reused) |
| install PyInstaller + app deps | ~2 min | ~15 s (already cached) |
| run PyInstaller | 2–4 min | 2–4 min |

On success it prints:

```
Done.  ->  C:\Users\Administrator\Desktop\PDFXML\dist\pdfxml.exe
```

then waits — press any key to close the window. On failure it prints the
error and also pauses, so nothing scrolls away.

### 5. The output

```
C:\Users\Administrator\Desktop\PDFXML\dist\pdfxml.exe
```

One self-contained file, ~45 MB. Everything (templates, static assets,
schema, content, `config.toml`) is baked in.

### 6. Test it before handing it out

Double-click `dist\pdfxml.exe`.

- A black console window opens (that is the app running — leave it open).
- Your browser opens to <http://127.0.0.1:5000>.
- Upload a PDF, extract some text, extract an image, do a crop. Confirm
  each works.
- Close the black window to stop it.

### 7. Distribute

Copy **just** `pdfxml.exe` to the target machine — nothing else, no
Python needed there. Send `deploy\windows\windows_readme.txt` along with
it as the end-user note.

First launch on a fresh machine: Windows SmartScreen shows "Windows
protected your PC / unknown publisher" → **More info** → **Run anyway**.
A one-time Firewall prompt → **Allow access** (it only listens on
localhost).

---

## If it breaks

| Symptom | Fix |
|---|---|
| `Python 3.12 was not found` | 3.12 not installed or not on PATH. Redo the one-time setup. Having 3.13 or 3.8 also installed is fine — the script asks for 3.12 by name (`py -3.12`). |
| `This folder is on a network or VMware shared folder` | You ran it from the share. Copy `PDFXML` to the Desktop (step 2) and run it from there. |
| Build fails right after you changed `requirements.txt` or `deploy/windows/requirements-desktop.txt`, or errors look like a half-broken environment | Delete `C:\Users\Administrator\Desktop\PDFXML\.venv-build\` and run the script again — it rebuilds the environment from scratch. |
| `Could not find deploy\windows\pdfxml.spec` | The copied folder is incomplete. Re-copy from the share. |
| PyInstaller error naming a missing module (e.g. `fitz`) | Add `--collect-all pymupdf` to the `PyInstaller` line in `deploy/windows/build_windows.bat`, or `--collect-all <module>` for whatever it named. Rare with the pinned versions. |
| `pdfxml.exe` runs but a page 500s / an asset 404s | A bundled data dir is missing. Check the `datas` list in `deploy/windows/pdfxml.spec` against what the error references. |
| The exe won't start on an older Windows than the build machine | Build on the **oldest** Windows you need to support. Win8.1-built runs on 10/11; the reverse may not. |

## Notes

- The runtime `.venv` (if you ever made one for local dev) and the
  build's `.venv-build\` are separate on purpose — don't point the build
  at the former.
- `.venv-build\`, `build\`, and `dist\` are all git-ignored; they never
  get committed or exported.
- One-file exe re-unpacks to `%TEMP%` on every launch (a few seconds) and
  draws more AV attention. For a faster start / less friction, switch the
  spec to one-directory output (add a `COLLECT()` block in
  `deploy/windows/pdfxml.spec`) and ship the resulting `dist\pdfxml\`
  folder instead of a lone file.
