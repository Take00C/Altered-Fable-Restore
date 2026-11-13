# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller --noconfirm AFRestore.spec   (Python 3.12, PyInstaller 6.22.3)
# Windows -> dist/AFRestore.exe; Linux -> dist/AFRestore. The release workflow packs it together with the Scene Tester
# (AFRestoreSceneTester.spec) into AFRestore-v<version>-win-x64.zip / AFRestore-v<version>-linux-x64.tar.gz.
# The repository is flat: this spec, app.py, the builder modules and the data files sit side by side. Every path is
# built from SPECPATH (the folder of this file), so the spec works from any checkout and on both OSes. The data files go
# into the bundle's 'data' folder, where the frozen app reads them: the same bundle as app_src/AFRestore.spec, which
# uses absolute paths for the local build. Keep AFRestoreSceneTester.spec in step.
import os
import sys
WIN = sys.platform == 'win32'
SRC = SPECPATH
# The app's data files, bundled into 'data' (afrestore.ico: the Windows icon; afrestore.png: the window icon elsewhere
# and the Scene Tester's side picture). Each one is named, so a missing file stops the build.
DATA_FILES = ['heaps.json', 'objmap.json', 'required.json', 'sound_pairs.json', 'afrestore.ico', 'afrestore.png']


a = Analysis(
    [os.path.join(SRC, 'app.py')],
    pathex=[SRC],
    binaries=[],
    datas=[(os.path.join(SRC, f), 'data') for f in DATA_FILES] + [(os.path.join(SRC, 'omsig_data.txt'), '.')],
    hiddenimports=['build_all', 'blocks', 'builder', 'scenes', 'align', 'objio', 'rsaparse', 'flow', 'crimp', 'oorparse', 'heapwriter', 'crsa', 'ruowrite', 'oscompat', 'entext', 'cgcrop', 'galcg', 'reencache', 'scenekit', 'scenetest_session'],
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
    icon=os.path.join(SRC, 'afrestore.ico') if WIN else None,     # exe icon: Windows only
)
