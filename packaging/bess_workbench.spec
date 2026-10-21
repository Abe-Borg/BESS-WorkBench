# -*- mode: python ; coding: utf-8 -*-
"""One-file Windows build. Run from the repo root: pyinstaller packaging/bess_workbench.spec"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent

datas = [
    (str(ROOT / "rules" / "ifc2024_nfpa855_2023.json"), "rules"),
    (str(ROOT / "samples" / "Sample - 4 Room UPS BESS.bessproj"), "samples"),
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "anthropic",
        "keyring.backends.Windows",
        "keyring.backends.SecretService",
        "keyring.backends.chainer",
    ],
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
    name="BESS-WorkBench",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
)
