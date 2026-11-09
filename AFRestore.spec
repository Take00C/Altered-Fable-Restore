# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm src/AFRestore.spec   (Python 3.12, pyinstaller 6.x)
# Windows -> dist/AFRestore.exe; Linux -> dist/AFRestore (packed as AFRestore-linux-x86_64.tar.gz by the workflow).
# Every path is built from SPECPATH (the folder of this file), so the spec works from any checkout and on both OSes.
# Same content as app_src/AFRestore.spec, which uses absolute paths for the local build.
import os
import sys
WIN = sys.platform == 'win32'
SRC = SPECPATH


a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],
    binaries=[],
    # data/ holds the window icons too (afrestore.ico for Windows, afrestore.png elsewhere); the PNG is also named
    # explicitly so a missing icon file stops the build instead of shipping without it
    datas=[(os.path.join(SRC, 'data'), 'data'), (os.path.join(SRC, 'omsig_data.txt'), '.'),
           (os.path.join(SRC, 'data', 'afrestore.png'), 'data')],
    hiddenimports=['build_all', 'blocks', 'builder', 'scenes', 'align', 'objio', 'rsaparse', 'flow', 'crimp', 'oorparse', 'heapwriter', 'crsa', 'ruowrite', 'oscompat', 'entext', 'cgcrop', 'reencache', 'scenekit', 'scenetest_session'],
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
    upx=WIN,                 # UPX-packed .so files can break on Linux
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SRC, 'data', 'afrestore.ico') if WIN else None,     # exe icon: Windows only
)
