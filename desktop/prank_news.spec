# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

desktop_dir = Path(SPECPATH)
template_dir = desktop_dir.parent / "pwa_template"
if not template_dir.is_dir():
    raise FileNotFoundError(f"找不到 PWA 範本：{template_dir}")

# Match builder.default_template_dir(): sys._MEIPASS / "pwa_template".
template_data = []
for source in sorted(template_dir.rglob("*")):
    relative = source.relative_to(template_dir)
    if not source.is_file() or any(
        part in {"tests", "README.md", ".git", ".vercel", "node_modules", "__pycache__", ".pytest_cache"}
        for part in relative.parts
    ):
        continue
    template_data.append((str(source), str(Path("pwa_template") / relative.parent)))

datas = template_data + collect_data_files("certifi") + collect_data_files("edge_tts")
hiddenimports = ["PIL.ImageTk", "PIL._tkinter_finder", "PIL.PngImagePlugin", "certifi"]
for package in ("edge_tts", "qrcode", "mutagen"):
    hiddenimports += collect_submodules(package)

a = Analysis(
    [str(desktop_dir / "run_gui.py")],
    pathex=[str(desktop_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="PrankNews",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
)
