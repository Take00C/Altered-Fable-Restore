"""AFRestore Scene Tester: the scene tester of Altered Fable Restore as a program of its own (AFRestore Scene Tester.exe
on Windows, AFRestoreSceneTester on Linux). It is app.py itself, started in tester mode, so the two programs always
match: same version, same settings folder, same scene test code. The flags are app.py's (--selftest prints
'SELFTEST OK <version>').
"""
import os
import runpy
import sys

if __name__ == '__main__':
    sys.path.insert(0, getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))))   # app.py's folder
    try:
        runpy.run_module('app', run_name='__main__', alter_sys=True, init_globals={'SCENE_TESTER': True})
    except Exception as e:
        # app.py ends every --selftest run itself; this only reports an app module that is missing or does not load,
        # which the windowed exe would otherwise show in an error box
        if sys.argv[1:2] not in (['--selftest'], ['--selftest-scenetest']): raise
        try:
            sys.stdout.write('SELFTEST FAILED starting the app: %r\n' % e); sys.stdout.flush()
        except Exception:
            pass
        os._exit(3)
