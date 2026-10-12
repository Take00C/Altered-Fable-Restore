# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm src/AFRestore.spec   (Python 3.12, pyinstaller 6.x)
import os

SRC = SPECPATH

a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],
    binaries=[],
    datas=[(os.path.join(SRC, 'data'), 'data'), (os.path.join(SRC, 'omsig_data.txt'), '.')],
    hiddenimports=['build_all', 'blocks', 'builder', 'scenes', 'align', 'objio', 'rsaparse', 'flow', 'crimp', 'oorparse', 'heapwriter', 'crsa', 'ruowrite'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AFRestore',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
