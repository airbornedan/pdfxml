# PyInstaller spec for the standalone desktop build (shape A).
# Run from the project root, on Windows:
#     pyinstaller deploy\windows\pdfxml.spec
# Output: dist\pdfxml.exe  (see deploy/windows/build_windows.bat)
import os

# this spec lives in deploy/windows/ -- everything it bundles is two levels up
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = [
    (os.path.join(ROOT, src), dst)
    for src, dst in [
        ("templates", "templates"),
        ("static", "static"),
        ("schema", "schema"),
        ("config.toml", "."),
        ("content", "content"),
    ]
]

a = Analysis(
    [os.path.join(ROOT, "desktop_launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="pdfxml",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
