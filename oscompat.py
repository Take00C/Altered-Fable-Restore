"""Platform-specific parts of Altered Fable Restore (Windows, Linux / Steam Deck; macOS best effort only).

Everything the GUI needs from the OS goes through here: settings folder, Steam libraries, finding both games,
detecting a running game, starting the game through Steam, file/folder pickers, child-process options, TLS
certificates for the update check. Pure standard library; importing it never fails on any OS.
On Windows every answer is the one earlier versions of the app gave (registry + drive letters, tasklist, startfile)."""
import os, sys, re, glob, shutil, subprocess

IS_WIN = os.name == 'nt'
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')
GAME_EXE = 'Muv-Luv_PM.exe'


# ---------------------------------------------------------------- folders
def settings_home():
    """Windows: %LOCALAPPDATA%\\AFRestore. Linux: $XDG_DATA_HOME/AFRestore (default ~/.local/share/AFRestore)."""
    if IS_WIN:
        return os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'AFRestore')
    if IS_MAC:
        return os.path.join(os.path.expanduser('~'), 'Library', 'Application Support', 'AFRestore')
    xdg = os.environ.get('XDG_DATA_HOME', '')
    if not os.path.isabs(xdg):                       # XDG spec: relative values are invalid -> default
        xdg = os.path.join(os.path.expanduser('~'), '.local', 'share')
    return os.path.join(xdg, 'AFRestore')


def ci_join(folder, name):
    """os.path.join(folder, name), but on case-sensitive file systems fall back to an entry whose name differs only in
    case (e.g. ALTFABLE.RIO copied from a CD or a FAT stick). Returns the exact-case path if nothing matches."""
    p = os.path.join(folder, name)
    if IS_WIN or os.path.exists(p):
        return p
    low = name.lower()
    try:
        for e in os.listdir(folder):
            if e.lower() == low:
                return os.path.join(folder, e)
    except OSError:
        pass
    return p


def _isdir(p):
    try: return os.path.isdir(p)
    except (OSError, ValueError): return False


def is_abs_path(p, windows=IS_WIN):
    """True for a full path: 'X:\\...' / 'X:/...' or '\\\\server\\share' on Windows, '/...' elsewhere. A relative path
    (or a Windows path rooted on the current drive, '\\x') would be resolved against the current folder: never used."""
    if not isinstance(p, str) or not p:
        return False
    if windows:
        return bool(re.match(r'[A-Za-z]:[\\/]|\\\\[^\\]', p))
    return p.startswith('/')


def _uniq_dirs(paths):
    out, seen = [], set()
    for p in paths:
        if not is_abs_path(p) or not _isdir(p): continue
        key = os.path.normcase(os.path.realpath(p))  # ~/.steam/steam is a symlink to ~/.local/share/Steam
        if key in seen: continue
        seen.add(key); out.append(p)
    return out


# ---------------------------------------------------------------- Steam
def steam_roots():
    roots = []
    if IS_WIN:
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
        # AFRestore.exe started through Proton/Wine: Steam passes its Linux paths in the environment; Z: is '/'
        for v in ('STEAM_COMPAT_CLIENT_INSTALL_PATH',):
            if os.environ.get(v, '').startswith('/'):
                roots.append('Z:' + os.environ[v].replace('/', '\\'))
        return _uniq_dirs(roots)
    h = os.path.expanduser('~')
    xdg = os.environ.get('XDG_DATA_HOME') or os.path.join(h, '.local', 'share')
    roots += [os.environ.get('STEAM_COMPAT_CLIENT_INSTALL_PATH'),           # set when started from Steam
              os.path.join(h, '.steam', 'steam'),                            # symlink, every native install (Deck too)
              os.path.join(h, '.steam', 'root'),
              os.path.join(xdg, 'Steam'),
              os.path.join(h, '.local', 'share', 'Steam'),                   # SteamOS / Arch / Fedora / Valve .deb
              os.path.join(h, '.steam', 'debian-installation'),              # Debian/Ubuntu 'steam-installer' package
              os.path.join(h, '.var', 'app', 'com.valvesoftware.Steam', '.local', 'share', 'Steam'),   # Flatpak
              os.path.join(h, '.var', 'app', 'com.valvesoftware.Steam', 'data', 'Steam'),             # Flatpak (old)
              os.path.join(h, 'snap', 'steam', 'common', '.local', 'share', 'Steam')]                  # Snap
    if IS_MAC:
        roots.append(os.path.join(h, 'Library', 'Application Support', 'Steam'))
    return _uniq_dirs(roots)


def _vdf_unescape(s):
    return re.sub(r'\\(.)', r'\1', s)


# KeyValues text: "quoted" (with \ escapes) | { | } | // comment | [$CONDITION] | bare token
_VDF_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*|\[[^\]\n]*\]|([^\s"{}]+)', re.S)


def _vdf_pairs(text):
    """(enclosing block keys, key, value) for every key/value pair of a KeyValues text (blocks themselves skipped)."""
    blocks, key = [], None
    for m in _VDF_TOKEN.finditer(text):
        quoted, brace, bare = m.groups()
        if brace == '{':
            blocks.append(key if key is not None else ''); key = None
        elif brace == '}':
            if blocks: blocks.pop()
            key = None
        elif quoted is not None or bare is not None:            # (comments and [$...] conditions are skipped)
            tok = _vdf_unescape(quoted) if quoted is not None else bare
            if key is None: key = tok
            else: yield tuple(blocks), key, tok; key = None


def library_paths_from_vdf(text, windows=IS_WIN):
    """Library folders listed in libraryfolders.vdf, full paths only:
    - current format: "path" "<folder>" (inside "libraryfolders" > "<n>"),
    - pre-2021 format: "<n>" "<folder>" directly inside "LibraryFolders".
    The current format's per-library "apps" block also holds "<appid>" "<size>" pairs: they are one level deeper and
    not paths, so they never count. Under Wine (Windows build started through Proton) the Linux client's file has
    '/...' paths: Wine's Z: drive is the Linux root."""
    out = []
    for blocks, key, value in _vdf_pairs(text):
        if key.lower() == 'path' or (key.isdigit() and len(blocks) == 1):
            if windows and value.startswith('/') and not value.startswith('//'):
                value = 'Z:' + value.replace('/', '\\')
            if is_abs_path(value, windows):
                out.append(value)
    return out


def steamapps(lib):
    return ci_join(lib, 'steamapps')                 # very old Linux clients used 'SteamApps'


def steam_libraries():
    libs = []
    for r in steam_roots():
        libs.append(r)
        for vdf in (os.path.join(steamapps(r), 'libraryfolders.vdf'), os.path.join(r, 'config', 'libraryfolders.vdf')):
            try:
                with open(vdf, encoding='utf-8', errors='replace') as f:
                    libs += library_paths_from_vdf(f.read())
            except OSError:
                pass
    return _uniq_dirs(libs)                          # unmounted SD cards / removed drives drop out here


def steam_userdata_remotes(app_id, roots=None):
    """[(account id, <Steam>/userdata/<account>/<app_id>/remote)] for every Steam account folder of every Steam root
    (the remote folder itself may not exist yet). Steam Cloud saves of the game live there: Windows; Linux and the
    Steam Deck (the native client's folder, also for Proton games); Flatpak / Snap Steam through steam_roots()."""
    out, seen = [], set()
    for r in (steam_roots() if roots is None else roots):
        ud = ci_join(r, 'userdata')
        try:
            ids = sorted(d for d in os.listdir(ud) if d.isdigit() and _isdir(os.path.join(ud, d)))
        except OSError:
            continue
        for i in ids:
            key = os.path.normcase(os.path.realpath(os.path.join(ud, i)))
            if key in seen: continue
            seen.add(key)
            out.append((i, os.path.join(ud, i, str(app_id), 'remote')))
    return out


def find_steam_game(app_id, rio_name):
    """Install folder of a Steam game from <library>/steamapps/appmanifest_<id>.acf. A folder that holds `rio_name`
    wins (a stale manifest on another library / SD card is skipped); otherwise the first existing folder, as before."""
    first = None
    for lib in steam_libraries():
        sa = steamapps(lib)
        man = os.path.join(sa, 'appmanifest_%s.acf' % app_id)
        try:
            with open(man, encoding='utf-8', errors='replace') as f:
                m = re.search(r'"installdir"\s+"((?:[^"\\]|\\.)*)"', f.read())
        except OSError:
            continue
        if m:
            d = ci_join(os.path.join(sa, 'common'), _vdf_unescape(m.group(1)))
            if os.path.isfile(ci_join(d, rio_name)):
                return d
            if first is None and _isdir(d):
                first = d
    return first


# ---------------------------------------------------------------- Altered Fable (DLsite / retail; not a Steam game)
def _wine_prefixes():
    h = os.path.expanduser('~')
    pfx = [os.environ.get('WINEPREFIX'), os.path.join(h, '.wine')]
    for lib in steam_libraries():                    # installer run through Proton as a non-Steam game
        pfx += glob.glob(os.path.join(steamapps(lib), 'compatdata', '*', 'pfx'))
    pfx += glob.glob(os.path.join(h, 'Games', '*'))                                           # Lutris default
    pfx += glob.glob(os.path.join(h, '.local', 'share', 'bottles', 'bottles', '*'))            # Bottles
    pfx += glob.glob(os.path.join(h, '.var', 'app', 'com.usebottles.bottles', 'data', 'bottles', 'bottles', '*'))
    pfx += glob.glob(os.path.join(h, '.PlayOnLinux', 'wineprefix', '*'))
    pfx += glob.glob(os.path.join(h, 'Games', 'Heroic', 'Prefixes', '*', '*'))
    return _uniq_dirs(pfx)


def _windows_style_bases(root):
    pf86, pf = os.path.join(root, 'Program Files (x86)'), os.path.join(root, 'Program Files')
    return [root, os.path.join(root, 'age'), pf86, pf, os.path.join(pf86, 'age'), os.path.join(pf, 'age'),
            os.path.join(root, 'Games')]


def af_search_bases():
    if IS_WIN:
        bases = []
        for d in 'CDEFGH':
            if os.path.exists(d + ':\\'): bases += _windows_style_bases(d + ':\\')
        return bases
    h = os.path.expanduser('~')
    bases = []
    for p in _wine_prefixes():
        bases += _windows_style_bases(ci_join(p, 'drive_c'))
    plain = [h, os.path.join(h, 'Games'), os.path.join(h, 'Desktop'), os.path.join(h, 'Downloads'),
             os.path.join(h, 'Documents')]
    for m in glob.glob('/run/media/*') + glob.glob('/run/media/*/*') + glob.glob('/media/*') + \
            glob.glob('/media/*/*') + glob.glob('/mnt/*'):
        plain += _windows_style_bases(m)             # SD cards / USB drives: /run/media/deck/<label>, /run/media/mmcblk0p1
    return bases + plain


def find_af(rio_name='altfable.rio'):
    """First folder holding altfable.rio, searched in each base and its direct sub-folders.
    Windows: drive letters C-H, exactly as earlier versions. Elsewhere: Wine/Proton/Lutris/Bottles prefixes, home
    folders, SD cards and USB drives, with the file name matched in any case."""
    if IS_WIN:
        cands = []
        for base in af_search_bases():
            try: subs = os.listdir(base)
            except OSError: continue
            cands.append(base)
            cands += [os.path.join(base, s) for s in subs]
        for c in cands:
            if os.path.exists(os.path.join(c, rio_name)): return c
        return None
    low = rio_name.lower()
    seen = set()
    for base in af_search_bases():
        try:
            subs = [e.path for e in os.scandir(base) if e.is_dir(follow_symlinks=True)]
        except OSError:
            continue
        for c in [base] + subs:
            k = os.path.realpath(c)
            if k in seen: continue
            seen.add(k)
            try:
                if any(n.lower() == low for n in os.listdir(c)):
                    return c
            except OSError:
                continue
    return None


# ---------------------------------------------------------------- processes
def no_window():
    """Popen kwargs that keep a console window from flashing up (Windows only; POSIX Popen rejects creationflags)."""
    return {'creationflags': 0x08000000} if IS_WIN else {}     # CREATE_NO_WINDOW


def external_env():
    """Environment for programs that are not this app (xdg-open, steam, kdialog): a PyInstaller one-file binary on
    Linux points LD_LIBRARY_PATH (and TCL/TK_LIBRARY) at its own temp folder, which breaks system programs."""
    env = dict(os.environ)
    if getattr(sys, 'frozen', False) and not IS_WIN:
        mei = getattr(sys, '_MEIPASS', '') or ''
        for var in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
            orig = env.pop(var + '_ORIG', None)
            if orig is not None: env[var] = orig
            else: env.pop(var, None)
        for k in list(env):
            if mei and mei in env[k] and k not in ('PATH',): env.pop(k)
    return env


def fresh_app_env():
    """POSIX: environment for starting a NEW copy of this app (after a self-update): no PyInstaller state of this run,
    so the new binary unpacks itself instead of taking this run's temp folder for its own."""
    env = external_env()
    for k in list(env):
        if k.upper().startswith('_PYI_') or k.upper() in ('_MEIPASS2', 'PYINSTALLER_RESET_ENVIRONMENT'):
            env.pop(k)
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def game_running(exe=GAME_EXE):
    low = exe.lower()
    if IS_WIN:
        try:
            out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s' % exe], capture_output=True, text=True,
                                 **no_window()).stdout
            return low in out.lower()
        except Exception:
            return False
    if os.path.isdir('/proc'):
        # Under Proton/Wine the game's comm is the exe name (kernel cuts it to 15 chars) and its cmdline holds the
        # Windows path of the exe; Steam's reaper/proton wrappers for the same launch carry the path too.
        me = os.getpid()
        for pid in os.listdir('/proc'):
            if not pid.isdigit() or int(pid) == me: continue
            try:
                with open('/proc/%s/comm' % pid, 'rb') as f:
                    comm = f.read().decode('utf-8', 'replace').strip().lower()
                if comm and low.startswith(comm) and len(comm) >= 10:
                    return True
                with open('/proc/%s/cmdline' % pid, 'rb') as f:
                    if low in f.read().replace(b'\0', b' ').decode('utf-8', 'replace').lower():
                        return True
            except OSError:
                continue
        return False
    try:                                             # macOS
        return subprocess.run(['pgrep', '-if', exe], capture_output=True).returncode == 0
    except OSError:
        return False


def open_url(url):
    """Hand a steam:// (or https://) URL to the desktop. True if some handler accepted it."""
    if IS_WIN:
        try: os.startfile(url); return True
        except OSError: return False
    cands = [['open', url]] if IS_MAC else [
        ['xdg-open', url], ['gio', 'open', url], ['kde-open5', url], ['kde-open', url],
        ['steam', url], ['flatpak', 'run', 'com.valvesoftware.Steam', url]]
    if IS_LINUX and not url.startswith('steam:'):
        cands = cands[:4]                            # a web page: only the desktop's handlers, not the Steam client
    env = external_env()
    for c in cands:
        if not shutil.which(c[0], path=env.get('PATH')): continue
        try:
            p = subprocess.Popen(c, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=env, start_new_session=True)
        except OSError:
            continue
        try:
            if p.wait(timeout=4) == 0: return True   # xdg-open exits 3/4 when no handler is registered
        except subprocess.TimeoutExpired:
            return True                              # still running (steam handing over to the running client)
    return False


def _run_picker(cands):
    env = external_env()
    for c in cands:
        if not shutil.which(c[0], path=env.get('PATH')): continue
        try:
            r = subprocess.run(c, capture_output=True, text=True, env=env)
        except OSError:
            continue
        return r.stdout.strip() if r.returncode == 0 else ''
    return None


def pick_folder(title, initial=None):
    """Native folder picker on Linux desktops (kdialog on KDE / Steam Deck desktop mode, zenity on GNOME).
    Returns a path, '' if the user cancelled, or None if no native picker exists (caller falls back to Tk)."""
    if IS_WIN or IS_MAC: return None
    start = initial or os.path.expanduser('~')
    return _run_picker((['kdialog', '--title', title, '--getexistingdirectory', start],
                        ['zenity', '--file-selection', '--directory', '--title=' + title,
                         '--filename=' + start.rstrip('/') + '/']))


def pick_file(title, initial=None, pattern='*', what='Files'):
    """Native file picker on Linux desktops, like pick_folder: a path, '' if cancelled, None if none exists."""
    if IS_WIN or IS_MAC: return None
    start = initial or os.path.expanduser('~')
    return _run_picker((['kdialog', '--title', title, '--getopenfilename', start, '%s (%s)' % (what, pattern)],
                        ['zenity', '--file-selection', '--title=' + title, '--filename=' + start.rstrip('/') + '/',
                         '--file-filter=%s | %s' % (what, pattern), '--file-filter=All files | *']))


def tk_show_hidden(root):
    """Tk's own Unix file dialog hides dot-folders (~/.local/share/Steam): add its 'show hidden' check box."""
    if IS_WIN or IS_MAC: return
    try:
        try: root.tk.call('tk_getOpenFile', '-foobarbaz')   # forces the dialog code to load; the bad option errors
        except Exception: pass
        root.tk.call('set', '::tk::dialog::file::showHiddenBtn', '1')
        root.tk.call('set', '::tk::dialog::file::showHiddenVar', '0')
    except Exception:
        pass


# ---------------------------------------------------------------- network
CA_BUNDLES = ('/etc/ssl/certs/ca-certificates.crt',                 # Debian, Ubuntu, Arch, SteamOS
              '/etc/pki/tls/certs/ca-bundle.crt',                   # Fedora, RHEL
              '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem',
              '/etc/ssl/ca-bundle.pem',                             # openSUSE
              '/etc/ssl/cert.pem')                                  # Arch, Alpine, macOS


def ssl_context():
    """TLS context for the update check. Windows/macOS: the default one (system store). Linux: the bundled OpenSSL of
    the frozen binary looks for certificates where its build distro keeps them, so fall back to the usual bundles."""
    import ssl
    ctx = ssl.create_default_context()
    if IS_LINUX:
        p = ssl.get_default_verify_paths()
        if not (p.cafile and os.path.isfile(p.cafile)) and not (p.capath and os.path.isdir(p.capath)):
            for f in CA_BUNDLES:
                if os.path.isfile(f):
                    try:
                        ctx.load_verify_locations(cafile=f); break
                    except (OSError, ssl.SSLError):
                        continue
    return ctx


# ---------------------------------------------------------------- disk
def supports_holes(folder):
    """True if files in `folder` can be sparse (ext4, btrfs, xfs, f2fs, NTFS via set_sparse); False on exFAT/FAT."""
    if IS_WIN: return True                           # ruowrite.set_sparse asks NTFS explicitly
    t = os.path.join(folder, 'AFRestore-sparse-test.tmp')
    try:
        with open(t, 'wb') as f:
            f.truncate(64 << 20)
        st = os.stat(t)
        return getattr(st, 'st_blocks', 1 << 30) * 512 < (1 << 20)
    except OSError:
        return False
    finally:
        try: os.remove(t)
        except OSError: pass


def write_help():
    if IS_WIN:
        return 'Run AFRestore.exe as administrator, or move the game to another Steam library.'
    return ('Check that this folder belongs to your user (Steam libraries normally do) and that the drive is not '
            'mounted read-only.')
