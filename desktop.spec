# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH)

hiddenimports = []
hiddenimports += collect_submodules("pydantic")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("fastapi")

a = Analysis(
    [str(project_root / "scripts" / "desktop_app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "app"), "app"),
        (str(project_root / "worker"), "worker"),
        (str(project_root / "datasets"), "datasets"),
        (str(project_root / "docs"), "docs"),
        (str(project_root / ".env.example"), "."),
        (str(project_root / "30_run_api.bat"), "."),
        (str(project_root / "101_stop_app.bat"), "."),
        (str(project_root / "40_smoke_test.bat"), "."),
        (str(project_root / "50_eval.bat"), "."),
        (str(project_root / "60_demo_flow.bat"), "."),
        (str(project_root / "99_full_pipeline.bat"), "."),
    ],
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
    [],
    exclude_binaries=True,
    name="BISTAgenticRAGDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="BISTAgenticRAGDesktop",
)
