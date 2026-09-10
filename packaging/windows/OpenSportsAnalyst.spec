from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata


ROOT = Path(SPEC).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src"
FRONTEND = ROOT / "frontend" / "dist"
ICON = ROOT / "packaging" / "windows" / "OpenSportsAnalyst.ico"

if not FRONTEND.joinpath("index.html").exists():
    raise SystemExit("frontend/dist is missing; run `npm run build` in frontend first")

datas = [(str(FRONTEND), "frontend/dist")]
for distribution in ("open-sports-analyst", "nflreadpy", "sportsdataverse", "keyring", "pywebview"):
    try:
        datas += copy_metadata(distribution)
    except Exception:
        pass

a = Analysis(
    [str(PACKAGE_ROOT / "sports_analyst" / "desktop.py")],
    pathex=[str(PACKAGE_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=["keyring.backends.Windows"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OpenSportsAnalyst",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(ICON) if ICON.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="OpenSportsAnalyst",
)
