from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata


ROOT = Path(SPEC).resolve().parents[2]
PACKAGE_ROOT = ROOT / "src"
FRONTEND = ROOT / "frontend" / "dist"
ICON = ROOT / "packaging" / "windows" / "OpenSportsAnalyst.ico"
sys.path.insert(0, str(ROOT / "packaging" / "windows"))
from native_dependencies import collect_provider_resources, collect_runtime_dlls, desktop_distributions

if not FRONTEND.joinpath("index.html").exists():
    raise SystemExit("frontend/dist is missing; run `npm run build` in frontend first")

datas = [(str(FRONTEND), "frontend/dist")]
distributions = desktop_distributions()
binaries = collect_runtime_dlls(distributions)
datas += collect_provider_resources(distributions)
for distribution in distributions:
    datas += copy_metadata(distribution)
print(f"Desktop native dependencies: collected {len(binaries)} DLLs from {len(distributions)} runtime distributions")

a = Analysis(
    [str(PACKAGE_ROOT / "sports_analyst" / "desktop" / "app.py")],
    pathex=[str(PACKAGE_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "keyring.backends.Windows",
        "sports_analyst.worker",
        # Provider imports are intentionally lazy; keep them available in the
        # frozen build without importing them during normal app startup.
        "nflreadpy",
        "sportsdataverse.nba.nba_loaders",
        "sportsdataverse.soccer",
        "sportsdataverse.dl_utils",
        "sportsdataverse.errors",
    ],
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
    upx=False,
    console=False,
    icon=str(ICON) if ICON.exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OpenSportsAnalyst",
)
