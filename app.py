"""Altered Fable Restore - standalone app.

Rebuilds the cut Altered Fable content (18+ scenes, Marimo-chan route, ...) into Muv-Luv photonmelodies from the
user's OWN copies of both games, then lets the user turn it on/off and start the game through Steam.
The app contains no game data: scripts, images and voices are read from the user's installs at build time.

  AFRestore.exe                      -> GUI
  AFRestore.exe --build PM AF OUT    -> (internal) extract + build the patch file OUT from the two installs
"""
import os, sys, json, hashlib, re, subprocess, shutil, threading, queue

APP = 'Altered Fable Restore'
APP_ID = '889710'
PATCH = 'photonmelodies11.rio.ruo1'
BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, 'data')
HOME = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'AFRestore')
SETTINGS = os.path.join(HOME, 'settings.json')
OLD_STASH = os.path.join(HOME, 'patch')    # stash used by earlier versions of this app
STASH_DIR = 'AFRestore-off'                # patch lives here (inside the game folder, same drive) while turned OFF;
                                           # a sub-folder, so the game's '<rio>.ruo*' search never sees it
REQ = json.load(open(os.path.join(DATA, 'required.json')))


# ---------------------------------------------------------------- helpers
def fingerprint(path):
    s = os.path.getsize(path); h = hashlib.sha1()
    with open(path, 'rb') as f:
        h.update(f.read(1 << 20)); f.seek(max(0, s - (1 << 20))); h.update(f.read(1 << 20))
    return [s, h.hexdigest()]


def check_install(folder, which):
    """None if `folder` holds the exact game version the restoration is built for, else a reason."""
    if not folder or not os.path.isdir(folder): return 'folder not set'
    for name, want in REQ[which].items():
        p = os.path.join(folder, name)
        if not os.path.exists(p): return 'missing %s' % name
        if fingerprint(p) != want: return '%s is a different version (game updated?)' % name
    return None


def steam_libraries():
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam'),
                          (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam')):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ('SteamPath', 'InstallPath'):
                        try: roots.append(winreg.QueryValueEx(k, name)[0].replace('/', '\\'))
                        except OSError: pass
            except OSError: pass
    except ImportError: pass
    roots.append(r'C:\Program Files (x86)\Steam')
    libs = []
    for r in roots:
        libs.append(r)
        vdf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        if os.path.exists(vdf):
            libs += [p.replace('\\\\', '\\') for p in re.findall(r'"path"\s+"([^"]+)"',
                                                                  open(vdf, encoding='utf-8', errors='replace').read())]
    return list(dict.fromkeys(libs))


def find_pm():
    for lib in steam_libraries():
        man = os.path.join(lib, 'steamapps', 'appmanifest_%s.acf' % APP_ID)
        if os.path.exists(man):
            m = re.search(r'"installdir"\s+"([^"]+)"', open(man, encoding='utf-8', errors='replace').read())
            if m:
                f = os.path.join(lib, 'steamapps', 'common', m.group(1))
                if os.path.isdir(f): return f
    return None


def find_af():
    """Look for altfable.rio in the usual places (DLsite/age installs have no registry entry we can rely on)."""
    cands = []
    for d in 'CDEFGH':
        root = d + ':\\'
        if not os.path.exists(root): continue
        for base in (root, os.path.join(root, 'age'), os.path.join(root, 'Program Files (x86)'), os.path.join(root, 'Program Files'),
                     os.path.join(root, 'Program Files (x86)', 'age'), os.path.join(root, 'Program Files', 'age'), os.path.join(root, 'Games')):
            try: subs = os.listdir(base)
            except OSError: continue
            cands.append(base)
            cands += [os.path.join(base, s) for s in subs]
    for c in cands:
        if os.path.exists(os.path.join(c, 'altfable.rio')): return c
    return None


def load_settings():
    try: return json.load(open(SETTINGS, encoding='utf-8'))
    except Exception: return {}


def save_settings(s):
    os.makedirs(HOME, exist_ok=True)
    json.dump(s, open(SETTINGS, 'w', encoding='utf-8'), indent=1)


def stash_path(pm):
    return os.path.join(pm, STASH_DIR, PATCH)


def can_write(folder):
    t = os.path.join(folder, 'AFRestore-write-test.tmp')
    try:
        open(t, 'wb').close(); os.remove(t); return True
    except OSError:
        return False


def game_running():
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq Muv-Luv_PM.exe'], capture_output=True, text=True,
                             creationflags=0x08000000).stdout
        return 'Muv-Luv_PM.exe' in out
    except Exception:
        return False


# ---------------------------------------------------------------- build (runs in a child process: AFRestore.exe --build)
def do_build(pm, af, out_ruo):
    work = os.path.join(HOME, 'work')
    if os.path.isdir(work): shutil.rmtree(work)
    os.makedirs(work)
    os.environ['AFR_OUT'] = work
    os.environ['AFR_PM_RIO'] = os.path.join(pm, 'photonmelodies11.rio')
    os.environ['AFR_AF_RIO'] = os.path.join(af, 'altfable.rio')
    sys.path.insert(0, BASE)
    for f in ('objmap.json', 'sound_pairs.json'):
        shutil.copy(os.path.join(DATA, f), os.path.join(work, f))
    from objio import read_at, AF_RIO, PM_RIO
    from crsa import decrypt_block
    heaps = json.load(open(os.path.join(DATA, 'heaps.json')))
    total = sum(len(v) for v in heaps.values()); done = 0
    print('STEP Reading scripts from your game files...', flush=True)
    for kind, names in heaps.items():
        rio = PM_RIO if kind == 'pm_rsa' else AF_RIO
        os.makedirs(os.path.join(work, kind))
        for n in names:
            v = int(n, 16)
            for c in ([v, v - 2] if kind == 'pm_rsa' else [v - 3 + k for k in range(8)]):
                if read_at(rio, c, 2) == b'\x6e\x03':
                    a, b = __import__('struct').unpack('<II', read_at(rio, c + 9, 8))
                    size = ((b ^ 0xC92E568F) & 0xFFFFFFFF) >> 3
                    heap, _ = decrypt_block(read_at(rio, c + 9, size + size // 32 * 2 + 64))
                    open(os.path.join(work, kind, n + '.bin'), 'wb').write(heap)
                    break
            else:
                raise SystemExit('script %s %s not found - unexpected game version' % (kind, n))
            done += 1
            if done % 40 == 0: print('PROGRESS %d' % (done * 20 // total), flush=True)
    print('STEP Building the restored content (this takes a few minutes)...', flush=True)
    import runpy
    sys.argv = ['build_all', out_ruo, 'all']
    runpy.run_module('build_all', run_name='__main__')
    shutil.rmtree(work, ignore_errors=True)
    print('DONE', flush=True)


# ---------------------------------------------------------------- GUI
def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    st = load_settings()
    root = tk.Tk(); root.title(APP); root.resizable(False, False)
    pad = dict(padx=10, pady=3)
    tk.Label(root, text='Muv-Luv Altered Fable - restored content', font=('Segoe UI', 14, 'bold')).grid(row=0, column=0, columnspan=4, pady=(10, 0))
    tk.Label(root, text='18+ scenes  ·  Marimo-chan route  ·  extra adult scenes  —  built from your own copies of both games',
             font=('Segoe UI', 9)).grid(row=1, column=0, columnspan=4, pady=(0, 8))
    paths = {'pm': tk.StringVar(value=st.get('pm') or ''), 'af': tk.StringVar(value=st.get('af') or '')}
    marks = {}
    rows = (('pm', 'Muv-Luv photonmelodies (Steam):', find_pm), ('af', 'Muv-Luv Altered Fable (2007):', find_af))
    for r, (k, label, finder) in enumerate(rows, start=2):
        tk.Label(root, text=label, anchor='w', width=30).grid(row=r, column=0, sticky='w', **pad)
        tk.Entry(root, textvariable=paths[k], width=52).grid(row=r, column=1, **pad)
        def auto(k=k, finder=finder):
            f = finder()
            if f: paths[k].set(f); refresh()
            else: messagebox.showinfo(APP, 'Not found automatically - use Browse to pick the game folder.')
        def browse(k=k):
            f = filedialog.askdirectory(title='Select the game folder')
            if f: paths[k].set(os.path.normpath(f)); refresh()
        tk.Button(root, text='Auto-find', command=auto).grid(row=r, column=2, **pad)
        tk.Button(root, text='Browse...', command=browse).grid(row=r, column=3, **pad)
        marks[k] = tk.Label(root, text='', anchor='w', font=('Segoe UI', 9))
        marks[k].grid(row=r + 2, column=0, columnspan=4, sticky='w', padx=14)
    status = tk.Label(root, text='', font=('Segoe UI', 10, 'bold'), wraplength=640, justify='left')
    status.grid(row=6, column=0, columnspan=4, sticky='w', padx=10, pady=(8, 2))
    bar = ttk.Progressbar(root, length=640, maximum=100)
    bar.grid(row=7, column=0, columnspan=4, padx=10, pady=4)
    btns = tk.Frame(root); btns.grid(row=8, column=0, columnspan=4, pady=10)
    b_build = tk.Button(btns, text='Build & install', width=18)
    b_toggle = tk.Button(btns, text='Turn OFF', width=18)
    b_play = tk.Button(btns, text='Play (via Steam)', width=18, command=lambda: os.startfile('steam://rungameid/' + APP_ID))
    for i, b in enumerate((b_build, b_toggle, b_play)): b.grid(row=0, column=i, padx=6)
    state = {}

    def refresh():
        st['pm'], st['af'] = paths['pm'].get(), paths['af'].get(); save_settings(st)
        ok = {}
        for k in ('pm', 'af'):
            why = check_install(paths[k].get(), k); ok[k] = why is None
            marks[k].config(text=('✓ found, correct version' if ok[k] else '✗ ' + why), fg='#070' if ok[k] else '#a00')
        pm = paths['pm'].get()
        in_game = os.path.join(pm, PATCH) if pm else ''
        stashed = stash_path(pm) if pm else ''
        if pm and not os.path.exists(stashed) and os.path.exists(os.path.join(OLD_STASH, PATCH)):
            stashed = os.path.join(OLD_STASH, PATCH)
        built = st.get('patch_fp')
        present = bool(pm) and os.path.isfile(in_game)       # any restored-content file in the game folder
        on = present and bool(built) and fingerprint(in_game) == built
        off = bool(stashed) and os.path.exists(stashed) and bool(built) and fingerprint(stashed) == built
        state.update(on=on, off=off, present=present, in_game=in_game, stashed=stashed)
        if present and not ok['pm'] and os.path.isdir(pm):
            status.config(text='Photonmelodies has changed (Steam update?) while the restored content is ON. '
                               'Click "Turn OFF" before playing.', fg='#a00')
        elif not ok['pm']:
            status.config(text='Photonmelodies is required (installed through Steam).', fg='#a00')
        elif not ok['af']:
            status.config(text='Your copy of Muv-Luv Altered Fable is required - the restored content is built from it.', fg='#a00')
        elif on: status.config(text='Restored content is ON. Have fun!', fg='#070')
        elif off: status.config(text='Restored content is built but turned OFF.', fg='#333')
        else: status.config(text='Ready to build the restored content.', fg='#333')
        both = ok['pm'] and ok['af']
        b_build.config(state='normal' if both else 'disabled', text='Rebuild & install' if (on or off) else 'Build & install')
        # turning OFF is always allowed (e.g. after a Steam update); turning ON needs the matching game version
        b_toggle.config(state='normal' if (present or (ok['pm'] and off)) else 'disabled',
                        text='Turn OFF' if present else 'Turn ON')
        b_play.config(state='normal' if ok['pm'] else 'disabled')

    def toggle():
        if game_running(): messagebox.showwarning(APP, 'Close Muv-Luv photonmelodies first.'); return
        pm = paths['pm'].get()
        try:
            root.config(cursor='watch'); root.update()
            if state['present']:
                if not messagebox.askokcancel(APP, 'Saves made while the content is ON (especially inside restored '
                                              'scenes) may not load while it is OFF. If the game shows an error right '
                                              'after starting, it is resuming such a save: go back to the title screen '
                                              'and load an earlier save.\n\nTurn it off?'): return
                dest = stash_path(pm)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if os.path.exists(dest): os.remove(dest)
                shutil.move(state['in_game'], dest)
            else:
                shutil.move(state['stashed'], state['in_game'])
        except OSError as e:
            messagebox.showerror(APP, 'Could not move the restored-content file:\n%s\n\n'
                                      'Close the game and try again.' % e)
        finally:
            root.config(cursor='')
            refresh()

    def build():
        if game_running(): messagebox.showwarning(APP, 'Close Muv-Luv photonmelodies first.'); return
        pm, af = paths['pm'].get(), paths['af'].get()
        if not can_write(pm):
            messagebox.showerror(APP, 'This app cannot write to the Photonmelodies folder:\n%s\n\n'
                                      'Run AFRestore.exe as administrator, or move the game to another Steam library.' % pm)
            return
        if shutil.disk_usage(pm).free < 2_500_000_000:
            messagebox.showerror(APP, 'Not enough free disk space on the drive with Photonmelodies (2.5 GB needed).')
            return
        # build next to the game (same drive -> instant move, sparse file stays small); a sub-folder keeps the
        # unfinished file away from the game's '<rio>.ruo*' search
        os.makedirs(os.path.join(pm, STASH_DIR), exist_ok=True)
        tmp = os.path.join(pm, STASH_DIR, 'build.tmp')
        cmd = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [os.path.abspath(__file__)]) + ['--build', pm, af, tmp]
        for b in (b_build, b_toggle, b_play): b.config(state='disabled')
        q = queue.Queue()

        def run():
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                 errors='replace', creationflags=0x08000000)
            n = 0
            for line in p.stdout:
                n += 1; q.put(('line', line.rstrip(), n))
            q.put(('end', p.wait(), n))
        threading.Thread(target=run, daemon=True).start()

        def poll():
            try:
                while True:
                    kind, val, n = q.get_nowait()
                    if kind == 'line':
                        if val.startswith('STEP '): status.config(text=val[5:], fg='#333')
                        elif val.startswith('PROGRESS '): bar['value'] = int(val.split()[1])
                        else: bar['value'] = min(98, 20 + n // 3)
                        last[0] = val
                    else:
                        try:
                            if val != 0 or not os.path.exists(tmp):
                                raise RuntimeError(last[0] or 'unknown error')
                            fp = fingerprint(tmp)
                            for old in (stash_path(pm), os.path.join(OLD_STASH, PATCH)):
                                if os.path.exists(old): os.remove(old)
                            os.replace(tmp, os.path.join(pm, PATCH)); st['patch_fp'] = fp; save_settings(st)
                            bar['value'] = 100; refresh()
                            messagebox.showinfo(APP, 'Restored content built and turned ON.')
                        except Exception as e:
                            try:
                                if os.path.exists(tmp): os.remove(tmp)
                            except OSError: pass
                            bar['value'] = 0; refresh()
                            messagebox.showerror(APP, 'Build failed:\n%s' % e)
                        return
            except queue.Empty:
                pass
            root.after(200, poll)
        last = ['']
        poll()

    b_build.config(command=build); b_toggle.config(command=toggle)
    for k, finder in (('pm', find_pm), ('af', find_af)):
        if not paths[k].get():
            f = finder()
            if f: paths[k].set(f)
    refresh()
    root.deiconify(); root.lift(); root.attributes('-topmost', True); root.after(300, lambda: root.attributes('-topmost', False))
    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) >= 5 and sys.argv[1] == '--build':
        do_build(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        gui()
