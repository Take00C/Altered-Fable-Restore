"""Altered Fable Restore - standalone app.

Rebuilds the cut Altered Fable content (18+ scenes, Marimo-chan route, ...) into Muv-Luv photonmelodies from the
user's OWN copies of both games, then lets the user turn it on/off and start the game through Steam.
The app contains no game data: scripts, images and voices are read from the user's installs at build time.

  AFRestore.exe / ./AFRestore                  -> GUI   (Windows / Linux incl. Steam Deck desktop mode)
  AFRestore --build PM AF OUT [EN_PKG]         -> (internal) extract + build the patch file OUT from the two installs;
                                                  EN_PKG = the player's afhook.pkg fan translation (optional English
                                                  text for restored lines; without it nothing changes)
  AFRestore --selftest                         -> smoke test of the frozen app (CI): imports and data files only, no
                                                  window; prints 'SELFTEST OK <version>' (exit 0) or the error (exit 3)
  AFRestore --selftest-scenetest [FIXTURE]     -> (tests only) the scene test end to end on fake folders in a temp
                                                  folder, no window; prints 'SCENETEST OK' (exit 0) or the error (3)

The Scene Tester (AFRestore Scene Tester.exe / ./AFRestoreSceneTester) is this same file started by scenetester.py in
tester mode (SCENE_TESTER): its window plays one restored scene and puts everything back; the flags above work there
too. The two programs share the settings folder (HOME) and are never open at the same time (take_lock).
"""
import sys

APP = 'Altered Fable Restore'
APP_VERSION = '0.1.0'                      # bump for every release; tag the GitHub release 'v' + APP_VERSION
TESTER = 'AFRestore Scene Tester'
# True when scenetester.py started this file (runpy init_globals): the window is the Scene Tester's
SCENE_TESTER = bool(globals().get('SCENE_TESTER'))
# --selftest is decided before anything else is imported, so that even a failing import or a missing data file ends
# in selftest_end() (message + exit code 3) instead of an uncaught exception, which the windowed Windows exe shows
# in an error box that nobody can close on a build machine
SELFTEST = __name__ == '__main__' and sys.argv[1:2] in (['--selftest'], ['--selftest-scenetest'])
if SELFTEST:
    sys.dont_write_bytecode = True         # a run from source leaves no __pycache__ behind


def selftest_end(error=None):
    """End a --selftest run: print 'SELFTEST OK <version>' and exit 0, or 'SELFTEST FAILED <error>' and exit 3.
    os._exit: nothing else of the app runs, so nothing can open a window or reach the windowed exe's error box."""
    import os
    line = 'SELFTEST OK %s' % APP_VERSION if error is None else 'SELFTEST FAILED %s' % error
    try:
        sys.stdout.write(line + '\n'); sys.stdout.flush()      # (windowed exe without a console: stdout is None)
    except Exception:
        pass
    os._exit(0 if error is None else 3)


def describe(e):
    """Exception -> text with its traceback (for --selftest output); never raises."""
    try:
        import traceback
        return ''.join(traceback.format_exception(type(e), e, e.__traceback__)).rstrip()
    except BaseException:
        return repr(e)


try:
    import os, json, hashlib, re, subprocess, shutil, threading, queue, time, ssl, http.client, urllib.request, urllib.error
    BASE = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, BASE)
    import oscompat as osc
    # the data files (required.json, heaps.json, ..., the icons): in the 'data' folder of the frozen app and of app_src;
    # next to app.py when it runs from the public repository, which keeps every file at its top level
    DATA = os.path.join(BASE, 'data')
    if not os.path.isfile(os.path.join(DATA, 'required.json')) and os.path.isfile(os.path.join(BASE, 'required.json')):
        DATA = BASE
    REQ = json.load(open(os.path.join(DATA, 'required.json'), encoding='utf-8'))
except BaseException as e:
    if not SELFTEST: raise
    selftest_end('loading the app: %s' % describe(e))

APP_ID = '889710'
PATCH = 'photonmelodies11.rio.ruo1'
HOME = osc.settings_home()                 # %LOCALAPPDATA%\AFRestore  |  ~/.local/share/AFRestore
SETTINGS = os.path.join(HOME, 'settings.json')
OLD_STASH = os.path.join(HOME, 'patch')    # stash used by earlier versions of this app
STASH_DIR = 'AFRestore-off'                # patch lives here (inside the game folder, same drive) while turned OFF;
                                           # a sub-folder, so the game's '<rio>.ruo*' search never sees it
REPO = 'Take00C/Altered-Fable-Restore'     # GitHub owner/name (release assets are verified by their sha256 digest)
RELEASE_API = 'https://api.github.com/repos/%s/releases/latest' % REPO
RELEASES_PAGE = 'https://github.com/%s/releases/latest' % REPO
# The release file a self-update installs: one archive per system holding both programs (PROGRAMS: this one first,
# then the Scene Tester), named after the release's own version (%s = '0.2.0'). No Linux build for other CPUs, no
# macOS build: those users get the releases page.
ASSET = 'AFRestore-v%s-win-x64.zip' if osc.IS_WIN else \
        'AFRestore-v%s-linux-x64.tar.gz' if osc.IS_LINUX and getattr(os, 'uname', None) and os.uname().machine == 'x86_64' \
        else None
PROGRAMS = ('AFRestore.exe', TESTER + '.exe') if osc.IS_WIN else ('AFRestore', 'AFRestoreSceneTester')
PROGRAM_SIZE = (1_000_000, 500_000_000)    # bytes: what a program in the archive may weigh
SUMS_ASSET = 'SHA256SUMS.txt'              # optional release file: '<sha256>  <file name>' lines; when it is there, the
                                           # archive's line must match too
REQUIRE_DIGEST = True                      # refuse a release asset without a 'sha256:' digest in the GitHub API
AUTO_CHECK_HOURS = 24                      # silent check at startup at most this often (0 = only on click)
NET_TIMEOUT = 20                           # seconds, per network operation
UPDATE_DIR = os.path.join(HOME, 'update')  # swap helper (Windows) + update.log
PYI_MAGIC = b'MEI\x0c\x0b\x0a\x0b\x0e'     # PyInstaller archive cookie, inside every AFRestore program
EN_PKG_NAME = 'afhook.pkg'                 # afhook fan translation package (the player's own copy, read in place)
EN_PKG_MAGIC = b'\xb6\x0a\x12\x8d'         # its first 4 bytes (uint32 0x8D120AB6)
# âge's official update of the 2007 game, next to altfable.rio. The builder takes the restored lines' corrected text,
# voices and staging from it, and builds without them when it is missing or another file: same size + SHA-1 of the
# whole file as build_all.AF_PATCH (--selftest checks that the two agree)
AF_PATCH_NAME = 'altfable.rio.ruo1'
AF_PATCH = (94323034, '17dbeb8aa5285f69833fb8f7a50745b8cbc7c1b5')
FONT = 'Segoe UI' if osc.IS_WIN else 'DejaVu Sans'    # Tk substitutes the nearest installed font
ICON_ICO = os.path.join(DATA, 'afrestore.ico')        # window icon (Windows)
ICON_PNG = os.path.join(DATA, 'afrestore.png')        # window icon (Linux / elsewhere)
# The scene test of the Scene Tester (scenekit.py: the kit and the patch file; scenetest_session.py: saves, session,
# Back to normal)
SCENE_HOME = os.path.join(HOME, 'scenetest')
KIT_NEW = os.path.join(SCENE_HOME, 'kit.new')        # written by a build (--build child); the kit once the patch is in place
STEAM_URL = 'steam://rungameid/' + APP_ID
SCENE_IN_GAME = ('Photonmelodies resumes your last session: go back to the title screen and press START.',
                 'After the short prologue and the opening movie (hold Ctrl to skip) the scene plays.',
                 'English text: set Options → Text Language to English.',
                 'When the scene ends, the opening carries on: just quit the game.')
ART_BOX = (260, 520)                       # the Scene Tester's side picture (data/afrestore.png) fits into this box
# Altered Fable Restore, while the Scene Tester's test is installed (status line, Build, Turn OFF / ON)
SCENE_BACK_HINT = 'To take it out, close this app, open %s and click "Back to normal".' % TESTER
# Held by the open program (Altered Fable Restore or the Scene Tester) for as long as it runs: both use HOME (settings,
# scene test session, kit), so only one of them may be open at a time. The holder's name is written at LOCK_WHO_AT
# (Windows locks byte 0 only, so the other program can still read it).
LOCK_FILE = os.path.join(HOME, 'running.lock')
LOCK_WHO_AT = 16


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
        p = osc.ci_join(folder, name)               # Linux file systems are case-sensitive
        if not os.path.exists(p): return 'missing %s' % name
        if fingerprint(p) != want: return '%s is a different version (game updated?)' % name
    return None


_af_patch_hashes = {}                          # (path, size, mtime) -> True when it is the official update


def check_af_patch(folder):
    """None if `folder` holds âge's official update (AF_PATCH) as the builder reads it, else 'missing' or 'different'.
    Only a note for the window: a build without it works, with the unpatched text, voices and staging."""
    if not folder or not os.path.isdir(folder): return 'missing'
    p = osc.ci_join(folder, AF_PATCH_NAME)
    try:
        if not os.path.isfile(p): return 'missing'
        s = os.stat(p)
        if s.st_size != AF_PATCH[0]: return 'different'
        key = (p, s.st_size, s.st_mtime_ns)
        if key not in _af_patch_hashes:            # 94 MB: hashed once, not on every refresh of the window
            h = hashlib.sha1()
            with open(p, 'rb') as f:
                for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
            _af_patch_hashes[key] = h.hexdigest() == AF_PATCH[1]
        return None if _af_patch_hashes[key] else 'different'
    except OSError:
        return 'missing'


def steam_libraries():
    return osc.steam_libraries()


def find_pm():
    return osc.find_steam_game(APP_ID, 'photonmelodies11.rio')


def find_af():
    """Look for altfable.rio in the usual places (DLsite/age installs have no registry entry we can rely on; on Linux:
    Wine/Proton/Lutris/Bottles prefixes, home folders, SD cards and USB drives)."""
    return osc.find_af('altfable.rio')


def is_en_pkg(path):
    """True if `path` is an afhook package (it starts with the package magic). Reads 4 bytes, nothing else."""
    try:
        with open(path, 'rb') as f: return f.read(4) == EN_PKG_MAGIC
    except (OSError, TypeError, ValueError):
        return False


def find_en_pkg(af, settings):
    """The fan translation to take English text from, or None (restored lines stay Japanese).
    settings['en_pkg']: a package the user picked (used while it is valid), '' = turned off with Clear; otherwise
    <Altered Fable folder>/afhook.pkg when present. The package is only ever read in place by the builder."""
    choice = settings.get('en_pkg')
    if choice == '': return None
    if choice and is_en_pkg(choice): return choice
    if af and os.path.isdir(af):
        p = osc.ci_join(af, EN_PKG_NAME)
        if is_en_pkg(p): return p
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
    return osc.game_running('Muv-Luv_PM.exe')


def same_path(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def scene_session():
    """The scene test state of this player (session file, kit, saves backups in HOME/scenetest)."""
    import scenetest_session as STS
    return STS.SceneTest(HOME, PATCH, game_running, osc.open_url, lambda: osc.steam_userdata_remotes(APP_ID))


def scene_label(test):
    """'Mikoto Yoroi (lead-in + scene)' for a session's 'test'."""
    if not isinstance(test, dict): return 'a test scene'
    return '%s (%s)' % (test.get('label') or test.get('item') or '?',
                        'lead-in + scene' if test.get('leadin') == 'with' else 'scene only')


def patch_state(pm, built):
    """Where the restored-content file of game folder `pm` is: dict(on, off, present, in_game, stashed). on: the file
    in the game folder is the one this app built (fingerprint `built`); off: the built file is stashed; present: any
    restored-content file is in the game folder."""
    in_game = os.path.join(pm, PATCH) if pm else ''
    stashed = stash_path(pm) if pm else ''
    if pm and not os.path.exists(stashed) and os.path.exists(os.path.join(OLD_STASH, PATCH)):
        stashed = os.path.join(OLD_STASH, PATCH)
    present = bool(pm) and os.path.isfile(in_game)
    on = present and bool(built) and fingerprint(in_game) == built
    off = bool(stashed) and os.path.exists(stashed) and bool(built) and fingerprint(stashed) == built
    return dict(on=on, off=off, present=present, in_game=in_game, stashed=stashed)


def in_restore(msg):
    """A scene test message for the Scene Tester: the "Rebuild & install" it names is Altered Fable Restore's."""
    return msg.replace('"Rebuild & install"', '"Rebuild & install" in Altered Fable Restore') if msg else msg


# ---------------------------------------------------------------- one program open at a time (HOME is shared)
def take_lock(who):
    """Lock LOCK_FILE for this process: Windows msvcrt.locking of byte 0, elsewhere fcntl.flock of the file; the OS lets
    go when the process ends, also after a crash. -> (lock, None): locked, `who` ('restore' or 'tester') written into
    the file; (None, holder): another process holds it, holder = the name it wrote ('' if none yet); (None, None): the
    file cannot be opened or locked here (e.g. a file system without locks): the program runs without the lock."""
    try:
        os.makedirs(HOME, exist_ok=True)
        f = os.fdopen(os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644), 'r+b', buffering=0)
    except OSError:
        return None, None
    try:
        if osc.IS_WIN:
            import msvcrt, errno
            try:
                f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)     # (locks from the file position)
            except OSError as e:
                if e.errno not in (errno.EACCES, errno.EDEADLOCK): raise
                return None, _lock_holder(f)
        else:
            import fcntl
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return None, _lock_holder(f)
    except OSError:
        f.close(); return None, None
    try:
        f.seek(LOCK_WHO_AT); f.write(who.encode('ascii').ljust(16))
    except OSError:
        pass
    return f, None


def _lock_holder(f):
    """The name the holder of the lock wrote ('' if none yet); closes f."""
    try:
        f.seek(LOCK_WHO_AT); return f.read(16).decode('ascii', 'replace').strip()
    except OSError:
        return ''
    finally:
        f.close()


def release_lock(lock):
    """Let go of take_lock()'s lock (None: nothing to do)."""
    if lock is None: return
    try:
        if osc.IS_WIN:
            import msvcrt
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    try: lock.close()
    except OSError: pass


def lock_message(holder):
    """What the program that did not get the lock tells the player before it closes."""
    me = TESTER if SCENE_TESTER else APP
    other = {'restore': APP, 'tester': TESTER}.get(holder)
    if other == me:
        return '%s is already open.' % me
    if other == APP:
        return 'Close Altered Fable Restore first: it and the Scene Tester cannot be open at the same time.'
    if other == TESTER:
        return 'Close the Scene Tester first: it and Altered Fable Restore cannot be open at the same time.'
    return 'Close Altered Fable Restore or its Scene Tester first: only one of them can be open at a time.'


def use_new_kit():
    """A build's patch is in place: its kit (kit.new) becomes the kit; the old kit goes either way (it was made for
    the old file)."""
    kit = os.path.join(SCENE_HOME, 'kit')
    if os.path.isdir(kit): shutil.rmtree(kit, ignore_errors=True)
    if os.path.isdir(KIT_NEW):
        try:
            os.replace(KIT_NEW, kit)
        except OSError:
            shutil.rmtree(KIT_NEW, ignore_errors=True)


def app_file():
    """The program file a self-update replaces (Linux: symlinks resolved, the replacement goes next to the real file;
    the Scene Tester's file is next to it: update_targets())."""
    return sys.executable if osc.IS_WIN else os.path.realpath(sys.executable)


# ---------------------------------------------------------------- self-update (latest GitHub release)
class UpdateError(Exception):
    """A problem to show to the user as it is."""


def version_tuple(s):
    """'v1.2.3' / 'Altered Fable Restore 1.2' -> (1, 2, 3) / (1, 2, 0); None when `s` holds no x.y number."""
    m = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', s or '')
    return tuple(int(g or 0) for g in m.groups()) if m else None


# Releases published before the 'v' + APP_VERSION tags: tag (lower case) -> version. The first public release has the
# tag 'Muv-LuvAlteredFable' and the title 'Altered Fable Restored', neither with a number: it counts as 0.0.0, below
# every numbered release (the first one is v0.1.0), so it is never offered as an update.
LEGACY_RELEASES = {'muv-luvalteredfable': (0, 0, 0)}


def release_version(tag, name):
    """Version of a GitHub release: from its tag, else the known legacy tags, else its title; None if none says."""
    return version_tuple(tag) or LEGACY_RELEASES.get((tag or '').strip().lower()) or version_tuple(name)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''): h.update(chunk)
    return h.hexdigest()


def _remove(path):
    try:
        if os.path.exists(path): os.remove(path)
    except OSError: pass


def _open_url(url, accept):
    hdr = {'User-Agent': 'AFRestore/' + APP_VERSION, 'Accept': accept}
    if url == RELEASE_API: hdr['X-GitHub-Api-Version'] = '2022-11-28'
    # Windows: the default context loads the system certificate store, so the frozen exe needs no certifi;
    # Linux: osc.ssl_context() also finds the distro's CA bundle for the frozen binary
    return urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=NET_TIMEOUT,
                                  context=osc.ssl_context())


def _net_error(e, doing):
    """urllib / socket / ssl exception -> UpdateError with a message for the user."""
    if isinstance(e, urllib.error.HTTPError):
        h = e.headers or {}
        if e.code in (403, 429) and (h.get('X-RateLimit-Remaining') == '0' or h.get('Retry-After')):
            when = ''
            try:
                if h.get('X-RateLimit-Reset'):
                    when = ' until %s' % time.strftime('%H:%M', time.localtime(int(h.get('X-RateLimit-Reset'))))
                elif h.get('Retry-After'):
                    when = ' for about %d minute(s)' % max(1, -(-int(h.get('Retry-After')) // 60))
            except ValueError: pass
            return UpdateError('GitHub is limiting requests from your internet connection%s. Try again later.' % when)
        if e.code == 404:
            return UpdateError('No release was found on GitHub (%s).' % REPO if doing == 'checking for updates' else
                               'The file is no longer on GitHub (it may have just been replaced). Try again.')
        return UpdateError('GitHub answered "%s %s" while %s. Try again later.' % (e.code, e.reason, doing))
    r = getattr(e, 'reason', None) or e
    if isinstance(r, ssl.SSLError):
        return UpdateError('The secure connection to GitHub failed while %s:\n%s' % (doing, r))
    if isinstance(r, TimeoutError):
        return UpdateError('GitHub did not answer in time while %s. Check your internet connection.' % doing)
    return UpdateError('Could not reach GitHub while %s. Check your internet connection.\n(%s)' % (doing, r))


def _asset_info(a):
    """A release asset of the GitHub API -> dict(name, url, size, sha256 (None without a valid digest), ready)."""
    d, url = str(a.get('digest') or '').lower(), str(a.get('browser_download_url') or '')
    return dict(name=str(a.get('name') or ''), url=url, size=int(a.get('size') or 0),
                sha256=d[7:] if re.fullmatch(r'sha256:[0-9a-f]{64}', d) else None,
                ready=a.get('state', 'uploaded') == 'uploaded' and bool(url))


def find_asset(assets, ver):
    """This system's archive among a release's assets: named ASSET with the release's own version `ver` (a tuple; the
    name may write it 'v0.2' or 'v0.2.0'). None when there is none or more than one, or no ASSET for this system."""
    if not ASSET or not ver: return None
    pre, post = (p.lower() for p in ASSET.split('%s'))
    found = []
    for a in assets:
        n = str(a.get('name') or '').lower()
        v = n[len(pre):len(n) - len(post)] if n.startswith(pre) and n.endswith(post) else ''
        if re.fullmatch(r'[0-9]+\.[0-9]+(?:\.[0-9]+)?', v) and version_tuple(v) == ver: found.append(a)
    return found[0] if len(found) == 1 else None


def check_latest():
    """Ask GitHub for the latest release -> dict (see below). Raises UpdateError. Runs in a worker thread."""
    try:
        with _open_url(RELEASE_API, 'application/vnd.github+json') as r: raw = r.read()
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise _net_error(e, 'checking for updates') from None
    try:
        rel = json.loads(raw.decode('utf-8'))
        tag = str(rel.get('tag_name') or '')
        assets = [a for a in list(rel.get('assets') or []) if isinstance(a, dict)]
        ver = release_version(tag, str(rel.get('name') or ''))
        a = find_asset(assets, ver)
        s = next((x for x in assets if str(x.get('name') or '').lower() == SUMS_ASSET.lower()), None)
        info = dict(tag=tag, version='.'.join(map(str, ver)) if ver else None, date=str(rel.get('published_at') or '')[:10],
                    notes=str(rel.get('body') or '').strip(), asset=a and _asset_info(a), sums=s and _asset_info(s),
                    newer=False, other_build=False)
    except (ValueError, AttributeError, TypeError):
        raise UpdateError('GitHub sent an unexpected answer. Try again later.') from None
    if info['asset'] and not info['asset']['ready']: info['asset'] = None        # (still being uploaded)
    # Only a release with a version number above APP_VERSION is an update (offered, downloaded, installed); one without
    # a number is only mentioned (other_build), never installed. The archive's digest says nothing about the running
    # program: download_update() refuses a release whose AFRestore is this very file.
    mine = version_tuple(APP_VERSION)
    info['newer'] = bool(ver and mine and ver > mine)
    info['other_build'] = ver is None
    return info


def update_targets():
    """The program files a self-update replaces: this program (app_file()) and the Scene Tester next to it."""
    main = app_file()
    return main, os.path.join(os.path.dirname(main), PROGRAMS[1])


def download_update(asset, sums, progress=None, again=True):
    """Download the release archive `asset` next to this program (as <program>.new.part) and check its size and sha256
    against GitHub's digest and, when the release has SHA256SUMS.txt (`sums`), against that file's line for it as well;
    then unpack both programs (unpack_programs) as <program>.new and <Scene Tester>.new and delete the archive.
    progress(percent) is called from the worker thread. -> [(program file, its new file)] for both programs, this one
    first: what start_swap_helper() / restart_updated() put in place. Raises UpdateError; nothing is left behind then.
    again: when SHA256SUMS.txt cannot be used, the release is looked at once more first (the release workflow rewrites
    that file right after a release is published, so it may have changed since check_latest())."""
    if REQUIRE_DIGEST and not asset['sha256']:
        raise UpdateError('The release on GitHub has no checksum, so the download cannot be verified. '
                          'Download %s from the releases page instead.' % asset['name'])
    if sums and not sums['ready']:
        raise UpdateError('The release on GitHub is still being uploaded. Try again in a few minutes.')
    main, tester = update_targets()
    if same_path(main, tester):
        raise UpdateError('This program is named like the Scene Tester (%s), so the update cannot replace both. '
                          'Download %s from the releases page instead.' % (PROGRAMS[1], asset['name']))
    if program_running(tester):                # (the shared lock keeps it closed while this program runs)
        raise UpdateError('Close %s first, then check for updates again.' % TESTER)
    size, part = asset['size'], main + '.new.part'
    if size < PROGRAM_SIZE[0]: raise UpdateError('The release file on GitHub is too small to hold the app (%d bytes).' % size)
    if shutil.disk_usage(os.path.dirname(main)).free < 2 * size + 50_000_000:
        raise UpdateError('Not enough free disk space next to the app for the update.')
    want = [asset['sha256']] if asset['sha256'] else []
    if sums:
        try:
            listed = sums_line(sums, asset['name'])
            if want and listed != want[0]:
                raise UpdateError('The checksum of %s in %s differs from the one GitHub published - not using it.'
                                  % (asset['name'], SUMS_ASSET))
        except UpdateError:
            fresh = _release_again(asset) if again else None
            if fresh is None: raise
            return download_update(fresh['asset'], fresh['sums'], progress, again=False)
        want.append(listed)
    staged = [(main, main + '.new'), (tester, tester + '.new')]
    try:
        got = _download(asset['url'], part, size, progress)
        if any(got != w for w in want):
            raise UpdateError('The downloaded file does not match the checksum published on GitHub - not using it.')
        unpack_programs(part, [(PROGRAMS[0], staged[0][1]), (PROGRAMS[1], staged[1][1])])
        if getattr(sys, 'frozen', False) and sha256_file(staged[0][1]) == sha256_file(main):
            raise UpdateError('The release on GitHub holds this same build of the app - nothing to update.')
    except UpdateError:
        for _, new in staged: _remove(new)
        raise
    except OSError as e:
        for _, new in staged: _remove(new)
        raise UpdateError('Could not save the download next to the app:\n%s' % e) from None
    finally:
        _remove(part)
    return staged


def _release_again(asset):
    """check_latest() once more for download_update(): the fresh release info when it still offers an archive named
    like `asset` (ready, with its SHA256SUMS.txt as it is now), else None."""
    try:
        info = check_latest()
    except UpdateError:
        return None
    a = info.get('asset')
    return info if a and a['name'] == asset['name'] else None


def _download(url, path, size, progress=None):
    """GET `url` into `path`: exactly `size` bytes (as GitHub announced) -> their sha256. Raises UpdateError (network,
    size) or OSError (writing)."""
    try:
        r = _open_url(url, 'application/octet-stream')
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise _net_error(e, 'downloading the update') from None
    h, done, shown = hashlib.sha256(), 0, -1
    with r, open(path, 'wb') as f:
        while True:
            try: chunk = r.read(1 << 16)
            except (http.client.HTTPException, OSError) as e: raise _net_error(e, 'downloading the update') from None
            if not chunk: break
            done += len(chunk)
            if done > size: raise UpdateError('The download is larger than GitHub announced - not using it.')
            f.write(chunk); h.update(chunk)
            if progress and done * 100 // size != shown: shown = done * 100 // size; progress(shown)
    if done != size: raise UpdateError('The download stopped early (%d of %d bytes). Try again.' % (done, size))
    return h.hexdigest()


def sums_line(sums, name):
    """The sha256 that the release's SHA256SUMS.txt (`sums`, checked against its own GitHub digest) gives for the file
    `name` ('<sha256>  <name>' lines, as sha256sum writes them). Raises UpdateError when the file cannot be read or does
    not give exactly one sha256 for `name`."""
    if REQUIRE_DIGEST and not sums['sha256']:
        raise UpdateError('%s of the release on GitHub has no checksum, so the download cannot be verified.' % SUMS_ASSET)
    if not 0 < sums['size'] <= 65536:
        raise UpdateError('%s of the release on GitHub has an unexpected size (%d bytes).' % (SUMS_ASSET, sums['size']))
    try:
        r = _open_url(sums['url'], 'application/octet-stream')
    except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
        raise _net_error(e, 'downloading the update') from None
    raw = b''
    try:
        with r:
            while len(raw) <= 65536:
                chunk = r.read(65537 - len(raw))
                if not chunk: break
                raw += chunk
    except (http.client.HTTPException, OSError) as e:
        raise _net_error(e, 'downloading the update') from None
    if len(raw) != sums['size'] or (sums['sha256'] and hashlib.sha256(raw).hexdigest() != sums['sha256']):
        raise UpdateError('%s does not match the checksum published on GitHub - not using the update.' % SUMS_ASSET)
    found = set()
    for line in raw.decode('utf-8', 'replace').lstrip('\ufeff').splitlines():
        mo = re.fullmatch(r'([0-9A-Fa-f]{64}) [ *](.+?)\s*', line)
        if mo and mo.group(2) == name: found.add(mo.group(1).lower())
    if len(found) != 1:
        raise UpdateError('%s of the release has %s line for %s - not using it.'
                          % (SUMS_ASSET, 'more than one' if found else 'no', name))
    return found.pop()


def unpack_programs(archive, wanted):
    """Release archive -> the programs: for each (name, dest) in `wanted`, the archive member called exactly `name` is
    copied to dest. Only these exact top-level names are used (other members are ignored, no path from the archive is
    ever used); each must be there once, as a plain file of a sane size (PROGRAM_SIZE). Windows (.zip): an exe ('MZ')
    with the PyInstaller marker near its end; Linux (.tar.gz): a 64-bit ELF file with the marker, made executable.
    Raises UpdateError; no dest is left behind then."""
    import zipfile, tarfile
    zipped = ASSET.endswith('.zip')
    dests = [d for _, d in wanted]
    try:
        with (zipfile.ZipFile(archive) if zipped else tarfile.open(archive, 'r:gz')) as arc:
            entries = arc.infolist() if zipped else arc.getmembers()
            picked = []
            for name, dest in wanted:
                same = [e for e in entries if (e.filename if zipped else e.name) == name]
                if len(same) != 1 or not (not same[0].is_dir() if zipped else same[0].isfile()):
                    raise UpdateError('The downloaded archive does not hold the %s program - not using it.' % name)
                size = same[0].file_size if zipped else same[0].size
                if not PROGRAM_SIZE[0] <= size <= PROGRAM_SIZE[1]:
                    raise UpdateError('%s in the downloaded archive has an unexpected size (%d bytes).' % (name, size))
                picked.append((same[0], size, name, dest))
            if shutil.disk_usage(os.path.dirname(dests[0])).free < sum(p[1] for p in picked) + 50_000_000:
                raise UpdateError('Not enough free disk space next to the app for the update.')
            for e, size, name, dest in picked:
                with (arc.open(e) if zipped else arc.extractfile(e)) as src:
                    _copy_program(src, dest, size, name, zipped)
        if not zipped:
            for d in dests: os.chmod(d, 0o755)
    except UpdateError:
        for d in dests: _remove(d)
        raise
    except Exception as e:                     # zip / tar / gzip / zlib errors, a CRC mismatch, OSError
        for d in dests: _remove(d)
        raise UpdateError('The downloaded archive could not be unpacked - not using it.\n(%s)' % e) from None


def _copy_program(src, dest, size, name, exe):
    """One program out of the archive (`size` bytes) -> dest, checked on the way: Windows (exe): 'MZ' and the
    PyInstaller marker in its last 64 KiB; Linux: a 64-bit ELF file with the marker. Raises UpdateError."""
    n, head, tail, found = 0, b'', b'', False
    with open(dest, 'wb') as f:
        while True:
            chunk = src.read(1 << 20)
            if not chunk: break
            if n == 0: head = chunk[:5]
            n += len(chunk)
            if n > size: break
            found = found or PYI_MAGIC in tail[-16:] + chunk
            tail = (tail + chunk)[-65536:]
            f.write(chunk)
    ok = (head[:2] == b'MZ' and PYI_MAGIC in tail) if exe else (head[:4] == b'\x7fELF' and head[4:5] == b'\x02' and found)
    if n != size or not ok:
        raise UpdateError('%s in the downloaded archive is not an AFRestore program for this system - not using it.' % name)


def restart_updated(staged):
    """Linux, called once the window is gone: put the downloaded, verified programs in place and replace this process by
    the new AFRestore. staged = download_update()'s [(program file, its new file)]: this program first, then the Scene
    Tester (one that is not there yet, e.g. after an older install, is simply added). Does not return unless starting a
    program failed.
    The swap waits until now because a PyInstaller one-file program keeps reading Python modules from its own file, by
    path, for as long as it runs: once the new file is in place this process imports nothing more. Everything execve
    needs is prepared before the swap, and from the first os.replace to os.execve there are only os calls. A running
    Scene Tester would read the new file the same way, so none may run from its file: the shared lock keeps it closed;
    this checks before the swap, and after it for one started in between.
    The old programs stay as <file>.old (hard links, else copies) until the new one has started (its update_leftovers()
    removes them). Any failure puts BOTH old programs back first (an added Scene Tester is taken out again), then notes
    the reason in update.log and starts the old program again, which reports it (the same as the Windows helper)."""
    target = staged[0][0]
    argv, env = [target, '--updated', APP_VERSION], osc.fresh_app_env()
    kept, placed = [], []                      # programs with a .old copy / whose new file is in place

    def undo(why):
        lost = []
        for t in reversed(placed):
            try:
                if t in kept: os.replace(t + '.old', t)
                else: os.remove(t)             # a Scene Tester this update added
            except OSError:
                lost.append(t)
        for t in kept:
            if t not in placed: _remove(t + '.old')        # (that program never moved)
        for _, new in staged: _remove(new)
        if lost:
            why += '; the old version could not be put back: it is %s' % ' and '.join(t + '.old' for t in lost)
        return _swap_failed(target, why)

    for t, _ in staged[1:]:
        if program_running(t): return undo('%s was open' % TESTER)
    for t, _ in staged:
        if not os.path.lexists(t): continue
        try:
            _remove(t + '.old')
            try: os.link(t, t + '.old')
            except OSError: shutil.copy2(t, t + '.old')    # file systems without hard links (FAT/exFAT)
        except OSError as e:
            _remove(t + '.old')
            return undo('could not keep a copy of the old version (%s)' % (e.strerror or e))
        kept.append(t)
    for t, new in staged:
        try:
            os.chmod(new, 0o755)
            os.replace(new, t)
        except OSError as e:                  # nothing of this program changed: undo() puts back the others
            return undo('could not put the new %s in place (%s)' % ('version' if t == target else TESTER,
                                                                     e.strerror or e))
        placed.append(t)
    for t, _ in staged[1:]:
        if t in kept and program_running(t + '.old'):
            return undo('%s was opened during the update' % TESTER)
    try:
        os.execve(target, argv, env)
    except OSError as e:
        return undo('the new version could not be started (%s)' % (e.strerror or e))


def _swap_failed(target, why):
    """Linux: a self-update failed with the old program (back) in place. Log it like the Windows helper does and start
    the old program again; at startup update_leftovers() turns the FAILED line into a message."""
    try:
        os.makedirs(UPDATE_DIR, exist_ok=True)
        with open(os.path.join(UPDATE_DIR, 'update.log'), 'w', encoding='ascii', errors='replace') as f:
            f.write('FAILED %s\n' % why)
    except OSError:
        pass
    argv, env = [target], osc.fresh_app_env()
    try:
        os.execve(target, argv, env)
    except OSError:
        try: subprocess.Popen(argv, env=env, start_new_session=True, stdin=subprocess.DEVNULL)
        except OSError: pass


def _image_of(pid):
    """Full path of the exe of process `pid`, or None."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        hp = k32.OpenProcess(0x1000, False, pid)              # PROCESS_QUERY_LIMITED_INFORMATION
        if not hp: return None
        try:
            buf = ctypes.create_unicode_buffer(32768); n = wintypes.DWORD(len(buf))
            return buf.value if k32.QueryFullProcessImageNameW(hp, 0, buf, ctypes.byref(n)) else None
        finally:
            k32.CloseHandle(hp)
    except Exception:
        return None


def _all_pids():
    """Windows: the ids of all processes (K32EnumProcesses); [] if they cannot be listed."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.K32EnumProcesses.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
        n = 1024
        while True:
            arr, got = (wintypes.DWORD * n)(), wintypes.DWORD()
            if not k32.K32EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(got)): return []
            if got.value < ctypes.sizeof(arr): return list(arr[:got.value // ctypes.sizeof(wintypes.DWORD)])
            n *= 4
    except Exception:
        return []


def program_running(path):
    """True when a process other than this one runs the program file `path`: Windows compares the image file of every
    process (QueryFullProcessImageNameW), Linux every /proc/<pid>/exe (the same file, also after it was renamed or
    replaced). False when `path` does not exist or nothing can be read. Only os calls on Linux (restart_updated())."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    me = os.getpid()
    if osc.IS_WIN:
        files = (_image_of(pid) for pid in _all_pids() if pid not in (0, 4, me))
    else:
        try:
            files = ['/proc/%s/exe' % p for p in os.listdir('/proc') if p.isdigit() and int(p) != me]
        except OSError:
            return False
    for f in files:
        try:
            s = os.stat(f) if f else None
        except OSError:
            continue
        if s and (s.st_dev, s.st_ino) == (st.st_dev, st.st_ino): return True
    return False


def app_pids():
    """Processes that keep the exe busy: this one, plus the PyInstaller one-file launcher (the parent, same exe)."""
    pids, ppid = [os.getpid()], os.getppid()
    img = _image_of(ppid)
    try:
        if img and os.path.samefile(img, sys.executable): pids.append(ppid)
    except OSError: pass
    return pids


# Windows: runs hidden after the app has exited. A running exe cannot be overwritten or deleted on Windows (it can be
# renamed, but the app must be gone before the new one starts), so: wait for the app's processes, and for no Scene
# Tester to run (by image name; the shared lock keeps it closed while the app runs), rename both old programs to .old
# (a .old left by an earlier update goes first, also a read-only one; a Scene Tester that is not there is simply
# added), check again for a Scene Tester started in between, move the downloaded ones into place, start the app. Any
# failure puts BOTH old programs back and starts the old app, which shows the FAILED line of update.log. Inputs come in
# environment variables, so no path is ever re-parsed by cmd.
UPDATE_HELPER = r'''@echo off
setlocal
set "SYS=%SystemRoot%\System32"
set "LOG=%~dp0update.log"
for %%f in ("%AFR_TESTER%") do set "TIMG=%%~nxf"
> "%LOG%" echo waiting
set /a N=0
:wait
set "BUSY="
for %%p in (%AFR_PIDS%) do (%SYS%\tasklist.exe /FI "PID eq %%p" /NH 2>nul | %SYS%\find.exe " %%p " >nul && set "BUSY=1")
if not defined BUSY goto tester
set /a N+=1
if %N% GEQ 120 goto stuck
%SYS%\ping.exe -n 2 127.0.0.1 >nul
goto wait
:stuck
>> "%LOG%" echo FAILED the old version did not close
del /f /q "%AFR_NEW%" "%AFR_TESTER_NEW%" >nul 2>&1
exit /b 1
:tester
set /a N=0
:twait
call :testerup || goto swap
set /a N+=1
if %N% GEQ 30 goto topen
%SYS%\ping.exe -n 2 127.0.0.1 >nul
goto twait
:topen
>> "%LOG%" echo FAILED AFRestore Scene Tester was open
goto restart
:swap
if exist "%AFR_TARGET%" del /f /q "%AFR_TARGET%.old" >nul 2>&1
set /a N=0
:retry
move /y "%AFR_TARGET%" "%AFR_TARGET%.old" >nul 2>&1 && goto tkeep
set /a N+=1
if %N% GEQ 30 goto locked
%SYS%\ping.exe -n 2 127.0.0.1 >nul
goto retry
:locked
>> "%LOG%" echo FAILED the app file stayed locked
goto restart
:tkeep
set "HADT="
if not exist "%AFR_TESTER%" goto check
del /f /q "%AFR_TESTER%.old" >nul 2>&1
set /a N=0
:tretry
move /y "%AFR_TESTER%" "%AFR_TESTER%.old" >nul 2>&1 && goto tkept
set /a N+=1
if %N% GEQ 30 goto tlocked
%SYS%\ping.exe -n 2 127.0.0.1 >nul
goto tretry
:tlocked
>> "%LOG%" echo FAILED the Scene Tester file stayed locked
goto rollback
:tkept
set "HADT=1"
:check
call :testerup || goto place
>> "%LOG%" echo FAILED AFRestore Scene Tester was opened during the update
goto rollback
:place
move /y "%AFR_NEW%" "%AFR_TARGET%" >nul 2>&1 || goto mfail
move /y "%AFR_TESTER_NEW%" "%AFR_TESTER%" >nul 2>&1 || goto tfail
>> "%LOG%" echo OK
start "" /b "%AFR_TARGET%" --updated %AFR_OLDVER% && >> "%LOG%" echo started
exit /b 0
:mfail
>> "%LOG%" echo FAILED could not put the new version in place
goto rollback
:tfail
>> "%LOG%" echo FAILED could not put the new Scene Tester in place
:rollback
set /a N=0
:rback
set "LOST="
if exist "%AFR_TARGET%.old" move /y "%AFR_TARGET%.old" "%AFR_TARGET%" >nul 2>&1 || set "LOST=1"
if defined HADT if exist "%AFR_TESTER%.old" move /y "%AFR_TESTER%.old" "%AFR_TESTER%" >nul 2>&1 || set "LOST=1"
if not defined LOST goto restart
set /a N+=1
if %N% GEQ 5 goto lost
%SYS%\ping.exe -n 2 127.0.0.1 >nul
goto rback
:lost
>> "%LOG%" echo FAILED the old version could not be put back completely
:restart
del /f /q "%AFR_NEW%" "%AFR_TESTER_NEW%" >nul 2>&1
start "" /b "%AFR_TARGET%"
exit /b 1
:testerup
%SYS%\tasklist.exe /FI "IMAGENAME eq %TIMG%" /FO CSV /NH 2>nul | %SYS%\find.exe /i "%TIMG%" >nul
exit /b
'''


def start_swap_helper(staged):
    """Windows: start the hidden helper that puts download_update()'s new programs (`staged`: this program, then the
    Scene Tester) in place once this app has exited, then restarts it. The caller must close the app right after this
    returns. Raises OSError."""
    (main, main_new), (tester, tester_new) = staged
    os.makedirs(UPDATE_DIR, exist_ok=True)
    helper = os.path.join(UPDATE_DIR, 'afr-update.cmd')
    with open(helper, 'w', encoding='ascii', newline='\r\n') as f: f.write(UPDATE_HELPER)
    _remove(os.path.join(UPDATE_DIR, 'update.log'))
    # The restarted exe must not inherit this run's PyInstaller state: with _PYI_* set it would take itself for the
    # child of a one-file launcher and look for files in this run's temp folder, which is deleted when we exit.
    mei = (getattr(sys, '_MEIPASS', '') or '').lower()
    env = {}
    for k, v in os.environ.items():
        if k.upper().startswith('_PYI_') or k.upper() in ('_MEIPASS2', 'PYINSTALLER_RESET_ENVIRONMENT'): continue
        if mei and mei in v.lower():
            if k.upper() != 'PATH': continue                 # TCL_LIBRARY, TK_LIBRARY, ... of this run
            v = os.pathsep.join(p for p in v.split(os.pathsep) if mei not in p.lower())
        env[k] = v
    env.update(PYINSTALLER_RESET_ENVIRONMENT='1', AFR_TARGET=main, AFR_NEW=main_new, AFR_TESTER=tester,
               AFR_TESTER_NEW=tester_new, AFR_PIDS=' '.join(map(str, app_pids())), AFR_OLDVER=APP_VERSION)
    # outer "" pair: cmd /c strips it, so the helper path stays quoted whatever characters it contains
    cmd = '"%s" /d /c ""%s""' % (os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'cmd.exe'), helper)
    flags = 0x08000000 | 0x00000200                          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    for extra in (0x01000000, 0):                            # + CREATE_BREAKAWAY_FROM_JOB where a job allows it
        try:
            subprocess.Popen(cmd, env=env, cwd=os.path.dirname(main), creationflags=flags | extra,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            if not extra: raise


def update_leftovers():
    """At startup: tidy up after an earlier update of both programs: the .new / .new.part files go, and the .old copies
    too, except one whose program is missing (a put-back that failed, e.g. of the Scene Tester): it is moved back.
    Returns the reason if the last swap failed, else None."""
    if getattr(sys, 'frozen', False):
        for exe in update_targets():
            for p in (exe + '.new', exe + '.new.part'): _remove(p)
            if os.path.lexists(exe) or not os.path.exists(exe + '.old'):
                if osc.IS_WIN:                 # a read-only program keeps that attribute as .old; os.remove refuses it
                    try: os.chmod(exe + '.old', 0o600)
                    except OSError: pass
                _remove(exe + '.old')
            else:
                try: os.replace(exe + '.old', exe)
                except OSError: pass           # (kept: it is the only copy)
    log = os.path.join(UPDATE_DIR, 'update.log')
    try:
        lines = open(log, encoding='ascii', errors='replace').read().split('\n')
    except OSError:
        return None
    _remove(log)
    failed = [l.strip()[7:] for l in lines if l.startswith('FAILED')]
    return failed[-1] if failed else None


# ---------------------------------------------------------------- build (runs in a child process: AFRestore.exe --build)
def do_build(pm, af, out_ruo, en_pkg=None):
    work = os.path.join(HOME, 'work')
    if os.path.isdir(work): shutil.rmtree(work)
    os.makedirs(work)
    os.environ['AFR_OUT'] = work
    os.environ['AFR_PM_RIO'] = osc.ci_join(pm, 'photonmelodies11.rio')
    os.environ['AFR_AF_RIO'] = osc.ci_join(af, 'altfable.rio')
    os.environ['AFR_EN_PKG'] = en_pkg or ''         # '' = no English text (the builder's default would look in AF)
    os.environ.setdefault('AFR_CACHE', os.path.join(HOME, 'cache'))   # picture re-encodes kept for the next build
    sys.path.insert(0, BASE)
    if os.path.isdir(KIT_NEW): shutil.rmtree(KIT_NEW, ignore_errors=True)
    for f in ('objmap.json', 'sound_pairs.json'):
        shutil.copy(os.path.join(DATA, f), os.path.join(work, f))
    from objio import read_at, AF_RIO, PM_RIO
    from crsa import decrypt_block
    heaps = json.load(open(os.path.join(DATA, 'heaps.json'), encoding='utf-8'))
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
    import runpy, scenekit
    scenekit.capture_hook(KIT_NEW)                 # the Scene Tester's kit, made at write time (patch bytes unchanged)
    sys.argv = ['build_all', out_ruo, 'all']
    runpy.run_module('build_all', run_name='__main__')
    shutil.rmtree(work, ignore_errors=True)
    print('DONE', flush=True)


# ---------------------------------------------------------------- GUI
def set_window_icon(root, tk):
    """Window icon from data/ (Windows: the .ico, elsewhere: the .png); silently nothing if missing or unsupported."""
    try:
        if osc.IS_WIN:
            if os.path.isfile(ICON_ICO): root.iconbitmap(default=ICON_ICO)
        elif os.path.isfile(ICON_PNG):
            img = tk.PhotoImage(master=root, file=ICON_PNG)
            root.iconphoto(True, img)
            root._afr_icon = img                    # keep a reference
    except Exception:
        pass


def gui():
    """The window of this program, Altered Fable Restore or (SCENE_TESTER) the Scene Tester, while it holds the lock;
    when the other program (or another copy of this one) is open: a message, then nothing else."""
    lock, holder = take_lock('tester' if SCENE_TESTER else 'restore')
    if lock is None and holder is not None:
        already_open(holder); return
    try:
        restart = tester_gui() if SCENE_TESTER else restore_gui()
    finally:
        release_lock(lock)
    if restart:
        restart_updated(restart)               # Linux self-update (both programs): the window is gone, the lock free


def already_open(holder):
    """The other program holds the lock: say so (a message box over a hidden window) and end."""
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk(); root.withdraw()
    name = TESTER if SCENE_TESTER else APP
    root.title(name)
    set_window_icon(root, tk)
    try:
        messagebox.showinfo(name, lock_message(holder), parent=root)
    finally:
        root.destroy()


def restore_gui():
    """Altered Fable Restore's window: the two game folders, the optional English text, Build & install, Turn OFF / ON,
    Play and Check for updates. A scene test the Scene Tester installed is shown in the status line and blocks Build and
    Turn OFF / ON until the Scene Tester's Back to normal took it out. Returns the downloaded programs (Linux
    self-update: download_update()'s list) that gui() puts in place once the window is gone, else None."""
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    st = load_settings()
    root = tk.Tk(); root.title('%s %s' % (APP, APP_VERSION)); root.resizable(False, False)
    set_window_icon(root, tk)
    pad = dict(padx=10, pady=3)
    tk.Label(root, text='Muv-Luv Altered Fable - restored content', font=(FONT, 14, 'bold')).grid(row=0, column=0, columnspan=4, pady=(10, 0))
    tk.Label(root, text='18+ scenes  ·  Marimo-chan route  ·  extra adult scenes  —  built from your own copies of both games',
             font=(FONT, 9)).grid(row=1, column=0, columnspan=4, pady=(0, 8))
    paths = {'pm': tk.StringVar(value=st.get('pm') or ''), 'af': tk.StringVar(value=st.get('af') or '')}
    marks = {}
    state = {}                      # building / updating: True while a build or an update runs
    locked = []                     # (widget, its state while busy): the folder rows and the English text row
    scene = scene_session()         # the Scene Tester's session (HOME/scenetest): only read here

    def busy():
        return bool(state.get('building') or state.get('updating'))

    rows = (('pm', 'Muv-Luv photonmelodies (Steam):', find_pm), ('af', 'Muv-Luv Altered Fable (2007):', find_af))
    for r, (k, label, finder) in enumerate(rows, start=2):
        tk.Label(root, text=label, anchor='w', width=30).grid(row=r, column=0, sticky='w', **pad)
        entry = tk.Entry(root, textvariable=paths[k], width=52)
        entry.grid(row=r, column=1, **pad)
        def auto(k=k, finder=finder):
            if busy(): return
            f = finder()
            if f: paths[k].set(f); refresh()
            else: messagebox.showinfo(APP, 'Not found automatically - use Browse to pick the game folder.')
        def browse(k=k):
            if busy(): return
            if osc.IS_WIN:
                f = filedialog.askdirectory(title='Select the game folder')
            else:
                start = paths[k].get() if os.path.isdir(paths[k].get()) else None
                f = osc.pick_folder('Select the game folder', start)       # kdialog / zenity on Linux desktops
                if f is None:
                    f = filedialog.askdirectory(title='Select the game folder', initialdir=start or os.path.expanduser('~'))
            if f: paths[k].set(os.path.normpath(f)); refresh()
        b_auto = tk.Button(root, text='Auto-find', command=auto); b_auto.grid(row=r, column=2, **pad)
        b_browse = tk.Button(root, text='Browse...', command=browse); b_browse.grid(row=r, column=3, **pad)
        locked += [(entry, 'readonly'), (b_auto, 'disabled'), (b_browse, 'disabled')]
        marks[k] = tk.Label(root, text='', anchor='w', justify='left', font=(FONT, 9))   # (2 lines with a note)
        marks[k].grid(row=r + 2, column=0, columnspan=4, sticky='w', padx=14)
    # optional English text: the player's own afhook.pkg fan translation, read in place by the builder
    en_path = tk.StringVar(value='')
    tk.Label(root, text='English text\n(fan translation, optional):', anchor='w', justify='left', width=30).grid(
        row=6, column=0, sticky='w', **pad)
    tk.Entry(root, textvariable=en_path, width=52, state='readonly').grid(row=6, column=1, **pad)

    def en_browse():
        if busy(): return
        cur = find_en_pkg(paths['af'].get(), st)
        start = os.path.dirname(cur) if cur else (paths['af'].get() if os.path.isdir(paths['af'].get()) else None)
        title = 'Select afhook.pkg (fan translation)'
        f = osc.pick_file(title, start, '*.pkg', 'afhook package')                  # Linux desktops
        if f is None:
            f = filedialog.askopenfilename(title=title, initialdir=start or os.path.expanduser('~'),
                                           filetypes=[('afhook package', '*.pkg'), ('All files', '*.*' if osc.IS_WIN else '*')])
        if not f: return
        f = os.path.normpath(f)
        if not is_en_pkg(f):
            messagebox.showerror(APP, 'This file is not an afhook fan translation package (afhook.pkg):\n%s' % f); return
        st['en_pkg'] = f; refresh()

    def en_clear():
        if busy(): return
        st['en_pkg'] = ''; refresh()

    b_en_clear = tk.Button(root, text='Clear', command=en_clear); b_en_clear.grid(row=6, column=2, **pad)
    b_en_browse = tk.Button(root, text='Browse...', command=en_browse); b_en_browse.grid(row=6, column=3, **pad)
    locked += [(b_en_clear, 'disabled'), (b_en_browse, 'disabled')]
    en_mark = tk.Label(root, text='', anchor='w', font=(FONT, 9))
    en_mark.grid(row=7, column=0, columnspan=4, sticky='w', padx=14)
    status = tk.Label(root, text='', font=(FONT, 10, 'bold'), wraplength=640, justify='left')
    status.grid(row=8, column=0, columnspan=4, sticky='w', padx=10, pady=(8, 2))
    bar = ttk.Progressbar(root, length=640, maximum=100)
    bar.grid(row=9, column=0, columnspan=4, padx=10, pady=4)
    btns = tk.Frame(root); btns.grid(row=10, column=0, columnspan=4, pady=10)
    b_build = tk.Button(btns, text='Build & install', width=18)
    b_toggle = tk.Button(btns, text='Turn OFF', width=18)

    def play():
        if not osc.open_url('steam://rungameid/' + APP_ID):
            messagebox.showinfo(APP, 'Start Muv-Luv photonmelodies from your Steam library.' + (
                '' if osc.IS_WIN else '\n\nSteam Deck: return to Gaming Mode and start it there - the restored '
                                      'content is inside the game folder, so Gaming Mode uses it too.'))
    b_play = tk.Button(btns, text='Play (via Steam)', width=18, command=play)
    for i, b in enumerate((b_build, b_toggle, b_play)): b.grid(row=0, column=i, padx=6)
    foot = tk.Frame(root); foot.grid(row=11, column=0, columnspan=4, sticky='we', padx=10, pady=(0, 8))
    tk.Label(foot, text='Version ' + APP_VERSION, font=(FONT, 8), fg='#666').pack(side='left')
    b_update = tk.Button(foot, text='Check for updates', font=(FONT, 8))
    b_update.pack(side='right')
    upd_fg = b_update.cget('fg')

    def lock():
        """A build or a self-update runs: every button and the folder rows stay off until it ends (refresh() keeps
        them off while busy(), so nothing a click or a dialog triggers can re-enable Build / Play / updates)."""
        for b in (b_build, b_toggle, b_play, b_update): b.config(state='disabled')
        for w, off in locked: w.config(state=off)

    def refresh():
        if busy():
            lock(); return                     # the build / update calls refresh() again when it is over
        for w, _ in locked: w.config(state='normal')
        st['pm'], st['af'] = paths['pm'].get(), paths['af'].get(); save_settings(st)
        ok = {}
        for k in ('pm', 'af'):
            why = check_install(paths[k].get(), k); ok[k] = why is None
            marks[k].config(text=('✓ found, correct version' if ok[k] else '✗ ' + why), fg='#070' if ok[k] else '#a00')
        patch_note = check_af_patch(paths['af'].get()) if ok['af'] else None       # a note only: building still works
        if patch_note:
            marks['af'].config(text='✓ found, correct version\n%s: restored lines use the unpatched text, voices and '
                                    'staging.' % ('Official update (%s) not found' % AF_PATCH_NAME if patch_note == 'missing'
                                                  else '%s is not the official update' % AF_PATCH_NAME), fg='#a60')
        pkg = find_en_pkg(paths['af'].get(), st)
        en_path.set(pkg or '')
        en_mark.config(text=('found: in the game, set Options → Text Language to English to see the restored lines in English' if pkg
                             else 'not used: restored lines are Japanese (Browse to pick afhook.pkg)'
                             if st.get('en_pkg') == '' else 'not found: restored lines are Japanese'),
                       fg='#070' if pkg else '#555')
        pm = paths['pm'].get()
        built = st.get('patch_fp')
        state.update(patch_state(pm, built))
        on, off, present = state['on'], state['off'], state['present']
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
        if (on or off) and ok['pm'] and ok['af']:
            if st.get('built_with') != APP_VERSION:          # none: built by the first release (it had no number)
                status.config(text=status.cget('text') + '  It was built by %s of this app: click "Rebuild & '
                                   'install" to update it.' % ('version %s' % st['built_with'] if st.get('built_with')
                                                               else 'an older version'))
            elif not same_path(pkg, st.get('built_en') or '') and (pkg or st.get('built_en')):
                status.config(text=status.cget('text') + '  The English text choice changed since it was built: '
                                   'click "Rebuild & install" to apply it.')
        both = ok['pm'] and ok['af']
        b_build.config(state='normal' if both else 'disabled', text='Rebuild & install' if (on or off) else 'Build & install')
        # turning OFF is always allowed (e.g. after a Steam update); turning ON needs the matching game version
        b_toggle.config(state='normal' if (present or (ok['pm'] and off)) else 'disabled',
                        text='Turn OFF' if present else 'Turn ON')
        b_play.config(state='normal' if ok['pm'] else 'disabled')
        b_update.config(state='normal')
        # a scene test of the Scene Tester: while it is installed the restored-content file is not the built one (its
        # end holds the test). The status says so; Build and Turn OFF / ON wait for the Scene Tester's Back to normal
        sst, sbad = scene.load()
        state.update(scene=sst, scene_bad=sbad)
        if sbad:
            status.config(text='Scene test: %s %s' % (sbad, SCENE_BACK_HINT), fg='#a00')
        elif sst:
            status.config(text='Scene test installed: %s. %s' % (scene_label(sst.get('test')), SCENE_BACK_HINT),
                          fg='#a60')
        if sst and list((sst.get('orig') or {}).get('fingerprint') or []) == list(built or []):
            b_build.config(text='Rebuild & install')        # the built file, with the test at its end

    def scene_installed():
        """A scene test is installed (or its record cannot be read): say that the Scene Tester takes it out first. The
        record is read again at the click, not taken from the last refresh()."""
        sst, sbad = scene.load()
        state.update(scene=sst, scene_bad=sbad)
        if not sst and not sbad: return False
        refresh()                                  # (the status line shows the test)
        messagebox.showinfo(APP, 'A scene test is installed. %s' % SCENE_BACK_HINT); return True

    def toggle():
        if scene_installed(): return
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
        if busy(): return
        if game_running(): messagebox.showwarning(APP, 'Close Muv-Luv photonmelodies first.'); return
        if scene_installed(): return
        pm, af = paths['pm'].get(), paths['af'].get()
        if not can_write(pm):
            messagebox.showerror(APP, 'This app cannot write to the Photonmelodies folder:\n%s\n\n%s'
                                 % (pm, osc.write_help()))
            return
        # ext4/btrfs/xfs keep the 1.34 GB leading gap of the patch sparse (~0.6 GB real); exFAT/FAT store it in full.
        # Windows keeps its earlier 2.5 GB rule (FSCTL_SET_SPARSE fails on FAT/exFAT drives).
        need = 2_500_000_000 if osc.IS_WIN or not osc.supports_holes(pm) else 1_000_000_000
        if shutil.disk_usage(pm).free < need:
            messagebox.showerror(APP, 'Not enough free disk space on the drive with Photonmelodies (%.1f GB needed).'
                                 % (need / 1e9))
            return
        if not osc.IS_WIN:
            os.makedirs(HOME, exist_ok=True)
            if shutil.disk_usage(HOME).free < 200_000_000:
                messagebox.showerror(APP, 'Not enough free disk space for the work folder:\n%s (0.2 GB needed).' % HOME)
                return
        # build next to the game (same drive -> instant move, sparse file stays small); a sub-folder keeps the
        # unfinished file away from the game's '<rio>.ruo*' search
        os.makedirs(os.path.join(pm, STASH_DIR), exist_ok=True)
        tmp = os.path.join(pm, STASH_DIR, 'build.tmp')
        pkg = find_en_pkg(af, st)
        cmd = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [os.path.abspath(__file__)]) + \
              ['--build', pm, af, tmp] + ([pkg] if pkg else [])
        state['building'] = True; lock()
        q = queue.Queue()

        def run():
            try:
                p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                     errors='replace', **osc.no_window())     # creationflags is Windows-only
            except OSError as e:
                q.put(('line', 'could not start the build: %s' % e, 0)); q.put(('end', -1, 0)); return
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
                        state['building'] = False          # (before refresh(), which keeps buttons off while busy)
                        try:
                            if val != 0 or not os.path.exists(tmp):
                                raise RuntimeError(last[0] or 'unknown error')
                            fp = fingerprint(tmp)
                            for old in (stash_path(pm), os.path.join(OLD_STASH, PATCH)):
                                if os.path.exists(old): os.remove(old)
                            os.replace(tmp, os.path.join(pm, PATCH)); st['patch_fp'] = fp
                            use_new_kit()           # the Scene Tester's data made by this build
                            st['built_with'] = APP_VERSION; st['built_en'] = pkg or ''; save_settings(st)
                            bar['value'] = 100; refresh()
                            messagebox.showinfo(APP, 'Restored content built and turned ON.')
                        except Exception as e:
                            try:
                                if os.path.exists(tmp): os.remove(tmp)
                            except OSError: pass
                            shutil.rmtree(KIT_NEW, ignore_errors=True)
                            bar['value'] = 0; refresh()
                            messagebox.showerror(APP, 'Build failed:\n%s' % e)
                        return
            except queue.Empty:
                pass
            root.after(200, poll)
        last = ['']
        poll()

    def in_background(work, done):
        """work(report) in a thread (report(percent) moves the bar), then done(result, error) on the GUI thread."""
        q = queue.Queue()

        def run():
            try: q.put(('ok', work(lambda p: q.put(('progress', p)))))
            except Exception as e: q.put(('error', e))
        threading.Thread(target=run, daemon=True).start()

        def poll():
            try:
                while True:
                    kind, val = q.get_nowait()
                    if kind == 'progress': bar['value'] = val
                    else: done(val if kind == 'ok' else None, val if kind == 'error' else None); return
            except queue.Empty:
                root.after(150, poll)
        poll()

    def update_busy(text):
        state['updating'] = True; lock()
        status.config(text=text, fg='#333')

    def update_idle():
        state['updating'] = False; bar['value'] = 0; refresh()

    def update_failed(err, what):
        update_idle()
        msg = str(err) if isinstance(err, UpdateError) else '%s failed:\n%s' % (what, err)
        if messagebox.askyesno(APP, msg + '\n\nOpen the releases page in your browser?', icon='warning'):
            osc.open_url(RELEASES_PAGE)

    def update(quiet=False):
        """'Check for updates': latest GitHub release -> download + verify the archive -> its two programs replace this
        one and the Scene Tester, and the new one starts (Windows: a helper swaps both exes after exit; Linux: swapped
        in and re-executed once the window is gone).
        Only a release whose version is above APP_VERSION counts as an update.
        quiet=True (startup check): no dialogs, only relabel the button when a new version is out."""
        if not quiet: update_busy('Checking GitHub for a new version...')
        in_background(lambda report: check_latest(), lambda info, err: update_checked(info, err, quiet))

    def update_checked(info, err, quiet):
        if quiet:
            if info and info['newer']:
                b_update.config(text='Update to %s...' % (info['version'] or 'new version'), fg='#070')
            return
        if err: update_failed(err, 'The update check'); return
        update_idle()
        new = info['version'] or info['tag'] or 'the latest release'
        if not info['newer']:
            b_update.config(text='Check for updates', fg=upd_fg)
            if info['other_build']:                # no version number to compare: mention it, never install it
                if messagebox.askyesno(APP, 'You have version %s. The latest release on GitHub (%s, published %s) has '
                                            'no version number, so it is not installed automatically.\n\nOpen the '
                                            'releases page in your browser?'
                                       % (APP_VERSION, info['tag'] or '?', info['date'] or '?')):
                    osc.open_url(RELEASES_PAGE)
            else:
                messagebox.showinfo(APP, 'You have the latest version (%s).' % APP_VERSION)
            return
        if not getattr(sys, 'frozen', False):
            messagebox.showinfo(APP, 'The latest release is %s (published %s); this is %s.\n\nYou are running the app '
                                     'from source: download the new source from the releases page (or update your '
                                     'copy with "git pull") and start it again.'
                                % (new, info['date'] or '?', APP_VERSION)); return
        if not ASSET:
            update_failed(UpdateError('The latest release is %s. There is no automatic update for this system.' % new),
                          ''); return
        name = ASSET % info['version']
        if not info['asset']:
            update_failed(UpdateError('The latest release (%s) has no %s to download.' % (new, name)), ''); return
        here = os.path.dirname(app_file())
        if not can_write(here):
            update_failed(UpdateError('The app cannot replace itself in this folder:\n%s\n\nDownload %s from the '
                                      'releases page and replace both programs with the ones in it.' % (here, name)),
                          ''); return
        notes = info['notes'][:600] + ('...' if len(info['notes']) > 600 else '')
        if not messagebox.askyesno(APP, 'Version %s is available (this is %s).\n\n%s%sDownload it (%.1f MB) and restart '
                                        'the app?' % (new, APP_VERSION, notes, '\n\n' if notes else '',
                                                      info['asset']['size'] / 1e6)): return
        update_busy('Downloading version %s...' % new)
        in_background(lambda report: download_update(info['asset'], info['sums'], report),
                      lambda staged, err: update_downloaded(err, staged, new))

    def update_downloaded(err, staged, new):
        if err: update_failed(err, 'The download'); return
        bar['value'] = 100
        # Windows: dialog BEFORE the helper starts (the helper gives the app 2 minutes to exit)
        messagebox.showinfo(APP, 'Version %s of %s and %s is downloaded and verified. The app restarts now.'
                            % (new, APP, TESTER))
        if osc.IS_WIN:
            try:
                start_swap_helper(staged)
            except OSError as e:
                for _, n in staged: _remove(n)
                update_failed(e, 'Starting the update'); return
        else:
            restart[0] = staged                    # swapped in by restart_updated() after mainloop, not now
        status.config(text='Restarting...', fg='#070')
        root.after(200, root.destroy)
    restart = [None]                               # Linux: the downloaded programs (.new) to swap in and start

    b_build.config(command=build); b_toggle.config(command=toggle); b_update.config(command=update)
    osc.tk_show_hidden(root)
    for k, finder in (('pm', find_pm), ('af', find_af)):
        if not paths[k].get():
            f = finder()
            if f: paths[k].set(f)
    refresh()
    # set for this program by the updater (both the new version and, after a failed update, the restarted old one):
    # later '--build' children share this run's files again
    os.environ.pop('PYINSTALLER_RESET_ENVIRONMENT', None)
    failed_update = update_leftovers()
    if failed_update:
        root.after(300, lambda: messagebox.showerror(APP, 'The last update could not be installed (%s).\n\nDownload the '
                                                          'new version from the releases page instead.' % failed_update))
    elif '--updated' in sys.argv:
        i = sys.argv.index('--updated'); old = sys.argv[i + 1] if len(sys.argv) > i + 1 else '?'

        def after_update():
            if st.get('patch_fp') and (state.get('scene') or state.get('scene_bad')):
                messagebox.showinfo(APP, 'Updated from version %s to %s.\n\nA new version can change the restored '
                                         'content: click "Rebuild & install" once the scene test is out. %s'
                                    % (old, APP_VERSION, SCENE_BACK_HINT))
            elif st.get('patch_fp') and str(b_build['state']) == 'normal':
                if messagebox.askyesno(APP, 'Updated from version %s to %s.\n\nA new version can change the restored '
                                            'content. Rebuild it now? (takes a few minutes%s; you can also do it later '
                                            'with "Rebuild & install")' % (old, APP_VERSION,
                                            '; it will be turned ON' if state.get('off') else '')):
                    build()
            else:
                messagebox.showinfo(APP, 'Updated from version %s to %s.' % (old, APP_VERSION))
        root.after(300, after_update)
    elif AUTO_CHECK_HOURS and time.time() - st.get('update_checked', 0) > AUTO_CHECK_HOURS * 3600:
        st['update_checked'] = time.time(); save_settings(st)
        root.after(1500, lambda: update(quiet=True))
    root.deiconify(); root.lift(); root.attributes('-topmost', True); root.after(300, lambda: root.attributes('-topmost', False))
    root.mainloop()
    return restart[0]


def fit_image(img, box):
    """Tk PhotoImage -> the same picture scaled by a whole factor to fit into box (w, h): zoomed when it fits twice or
    more, subsampled when it is larger, else as it is."""
    w, h = img.width(), img.height()
    if w <= 0 or h <= 0: return img
    up = min(box[0] // w, box[1] // h)
    if up >= 2: return img.zoom(up)
    down = max(-(-w // box[0]), -(-h // box[1]))
    return img.subsample(down) if down > 1 else img


def tester_gui():
    """The Scene Tester's window: play one restored scene, then Back to normal puts the restored-content file and the
    saves back (by itself after the game closes, when ticked). The restored content is Altered Fable Restore's: its
    game folder, built file and kit (shared settings, HOME/scenetest); this window says when that is missing, off,
    built by another version or changed, and points to Altered Fable Restore. Returns None (no self-update here)."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    import scenekit as SK
    st = load_settings()
    root = tk.Tk(); root.title('%s %s' % (TESTER, APP_VERSION)); root.resizable(False, False)
    set_window_icon(root, tk)
    scene = scene_session()         # the scene test: session, kit, saves (HOME/scenetest)
    state = {}                      # busy: a test is being put in; scene / scene_bad: the session; ok_pm, on, off, ...
    sstate = dict(seen=False, closed_at=None, checking=False)      # the game watcher
    try:
        kit = scene.kit()
    except Exception:
        kit = None
    kst = dict(items=(kit or {}).get('items') or {}, en=bool((kit or {}).get('en')))   # the kit shown (kit_changed)
    notes = {}

    def item_note(it):
        return ('%d lines%s' % (it.get('lines', 0), ' + %d lead-in' % it['lead_lines'] if it.get('leadins')
                                else '')) if it else ''
    left = tk.Frame(root); left.grid(row=0, column=0, sticky='nw', padx=(12, 6), pady=(10, 10))
    tk.Label(left, text=TESTER, font=(FONT, 14, 'bold')).grid(row=0, column=0, sticky='w')
    tk.Label(left, text='Play one restored scene. Your saves are backed up first; Back to normal puts them back.',
             font=(FONT, 9), fg='#555').grid(row=1, column=0, sticky='w', pady=(0, 6))
    # the game folder Altered Fable Restore builds into (shared settings): shown here, changed there
    pf = tk.Frame(left); pf.grid(row=2, column=0, sticky='we', pady=(0, 4))
    tk.Label(pf, text='Muv-Luv photonmelodies:', font=(FONT, 9)).grid(row=0, column=0, sticky='w')
    pm_var = tk.StringVar(value=st.get('pm') or '')
    tk.Entry(pf, textvariable=pm_var, width=50, state='readonly').grid(row=0, column=1, sticky='w', padx=(6, 0))
    tk.Label(pf, text='The folder Altered Fable Restore builds into (change it there).', font=(FONT, 8),
             fg='#777').grid(row=1, column=1, sticky='w', padx=(6, 0))
    sel = tk.StringVar(value=st.get('scenetest_item') if st.get('scenetest_item') in SK.LABEL else SK.PUBLIC[0][1])
    lead = tk.StringVar(value=st.get('scenetest_leadin') if st.get('scenetest_leadin') in ('with', 'skip') else 'with')
    radios = []
    row = 3
    for g in SK.GROUPS:
        names = [(n, l) for gg, n, l in SK.PUBLIC if gg == g]
        lf = tk.LabelFrame(left, text=g, font=(FONT, 9, 'bold'), padx=8, pady=3)
        lf.grid(row=row, column=0, sticky='we', pady=3); row += 1
        per = -(-len(names) // (2 if len(names) > 3 else 1))
        for i, (n, l) in enumerate(names):
            c, r = divmod(i, per)
            rb = tk.Radiobutton(lf, text=l, variable=sel, value=n, font=(FONT, 9), anchor='w',
                                command=lambda: controls())
            rb.grid(row=r, column=2 * c, sticky='w'); radios.append(rb)
            notes[n] = tk.Label(lf, text=item_note(kst['items'].get(n)), font=(FONT, 8), fg='#777')
            notes[n].grid(row=r, column=2 * c + 1, sticky='w', padx=(0, 18))
    of = tk.Frame(left); of.grid(row=row, column=0, sticky='w', pady=(4, 2)); row += 1
    tk.Label(of, text='Start:', font=(FONT, 9)).pack(side='left')
    rb_with = tk.Radiobutton(of, text='a little before the scene', variable=lead, value='with', font=(FONT, 9))
    rb_skip = tk.Radiobutton(of, text='at the scene', variable=lead, value='skip', font=(FONT, 9))
    rb_with.pack(side='left', padx=(6, 0)); rb_skip.pack(side='left', padx=(6, 0))
    auto_var = tk.BooleanVar(value=bool(st.get('scenetest_auto', True)))

    def auto_changed():
        st['scenetest_auto'] = bool(auto_var.get()); save_settings(st)
    tk.Checkbutton(left, text='Back to normal by itself when the game closes (while this app is open)',
                   variable=auto_var, font=(FONT, 9), command=auto_changed).grid(row=row, column=0, sticky='w')
    row += 1
    box = tk.LabelFrame(left, text='In the game', font=(FONT, 9, 'bold'), padx=8, pady=3)
    box.grid(row=row, column=0, sticky='we', pady=3); row += 1

    def game_line(i):
        return tk.Label(box, text='•  ' + SCENE_IN_GAME[i], font=(FONT, 9), anchor='w', justify='left',
                        wraplength=560)
    lines = [game_line(i) if i != 2 or kst['en'] else None for i in range(len(SCENE_IN_GAME))]   # [2]: English
    for w in lines:
        if w is not None: w.pack(anchor='w')
    note = tk.Label(left, text='', font=(FONT, 9), fg='#a00', anchor='w', justify='left', wraplength=560)
    note.grid(row=row, column=0, sticky='w', pady=(4, 0)); row += 1
    installed = tk.Label(left, text='', font=(FONT, 9, 'bold'), anchor='w', justify='left', wraplength=560)
    installed.grid(row=row, column=0, sticky='w', pady=(4, 2)); row += 1
    tbar = ttk.Progressbar(left, length=560, maximum=100, mode='determinate')
    tbar.grid(row=row, column=0, sticky='w', pady=2); row += 1
    bf = tk.Frame(left); bf.grid(row=row, column=0, sticky='we', pady=(6, 0))
    tk.Label(bf, text='Version ' + APP_VERSION, font=(FONT, 8), fg='#666').pack(side='left')
    b_go = tk.Button(bf, text='▶ Play this scene', width=18)
    b_back = tk.Button(bf, text='Back to normal', width=16, command=lambda: scene_back())
    b_go.pack(side='right', padx=(6, 0)); b_back.pack(side='right', padx=(6, 0))
    try:                                            # the side picture: the app's own art (data/), never a game file
        art = fit_image(tk.PhotoImage(master=root, file=ICON_PNG), ART_BOX)
        tk.Label(root, image=art, bd=0).grid(row=0, column=1, padx=(6, 14), pady=14)
        root._afr_art = art                         # keep a reference
    except Exception:
        pass

    def kit_changed():
        """The kit as it is now (a Rebuild & install in Altered Fable Restore makes a new one): the line counts, the
        Start choice and the English line follow it."""
        try:
            k = scene.kit()
        except Exception:
            k = None
        items, en = (k or {}).get('items') or {}, bool((k or {}).get('en'))
        if items == kst['items'] and en == kst['en']: return
        kst.update(items=items, en=en)
        for n, w in notes.items(): w.config(text=item_note(items.get(n)))
        if en and lines[2] is None:
            lines[2] = game_line(2); lines[2].pack(anchor='w', before=lines[3])
        elif not en and lines[2] is not None:
            lines[2].destroy(); lines[2] = None

    def content_problem():
        """Why no scene test can be played now (no game check), or None. Altered Fable Restore finds the game, builds
        the restored content and turns it on; the test must be made from content this same version built."""
        pm = st.get('pm') or ''
        test = state.get('scene') or state.get('scene_bad')
        if not pm:
            return ('Open Altered Fable Restore first: it finds Muv-Luv photonmelodies and builds the restored '
                    'content the scenes are played from.')
        if not os.path.isdir(pm):
            return ('The Photonmelodies folder is not available:\n%s\nIf it is on a drive or SD card that is not '
                    'connected, connect it. If the game moved, set its folder in Altered Fable Restore.' % pm)
        if not state.get('ok_pm'):
            return ('Photonmelodies is not the version the restored content is built for (Steam update?). Open '
                    'Altered Fable Restore to see what to do.')
        if not test and not state.get('on'):
            return ('The restored content is turned OFF. Open Altered Fable Restore and click "Turn ON".'
                    if state.get('off') else
                    'The restored content is not built yet. Open Altered Fable Restore and click "Build & install".')
        if st.get('built_with') != APP_VERSION:            # none: built by the first release (it had no number)
            built = version_tuple(st.get('built_with'))
            if built and built > version_tuple(APP_VERSION):
                # a rebuild cannot help: that Altered Fable Restore writes its own version again
                return ('The restored content was built by version %s of Altered Fable Restore, and this Scene Tester '
                        'is the older version %s. Use the Scene Tester that came with that Altered Fable Restore: '
                        'keep both programs from the same download in the same folder.'
                        % (st['built_with'], APP_VERSION))
            return ('The restored content was built by %s of Altered Fable Restore; this Scene Tester is version %s. '
                    '%s Altered Fable Restore and click "Rebuild & install". Both programs must be the same version: '
                    'keep them from the same download in the same folder.'
                    % ('version %s' % st['built_with'] if st.get('built_with') else 'an older version', APP_VERSION,
                       'Click "Back to normal", then open' if test else 'Open'))
        return in_restore(scene.can_test(pm, st.get('patch_fp')))

    def refresh():
        """Look again at the game folder, the restored-content file, the session and the kit, then the controls."""
        pm = st.get('pm') or ''
        pm_var.set(pm)
        sst, sbad = scene.load()
        state.update(patch_state(pm, st.get('patch_fp')), ok_pm=check_install(pm, 'pm') is None, scene=sst,
                     scene_bad=sbad)
        kit_changed()
        if sbad: installed.config(text='Installed now: unknown (%s)' % sbad, fg='#a00')
        elif sst: installed.config(text='Installed now: %s' % scene_label(sst.get('test')), fg='#a60')
        elif not state.get('busy'):
            installed.config(text='Installed now: nothing' + (' (your own restored content)' if state['on'] else ''),
                             fg='#070')
        note.config(text='' if sst or sbad else content_problem() or '')
        controls()

    def controls():
        """Buttons and choices: off while a test is being put in; Start only for a scene with a lead-in."""
        it = kst['items'].get(sel.get()) or {}
        has_lead = bool(it.get('leadins')) or not kst['items']
        free = not state.get('busy')
        for b in (rb_with, rb_skip): b.config(state='normal' if has_lead and free else 'disabled')
        for b in radios: b.config(state='normal' if free else 'disabled')
        b_go.config(state='normal' if free else 'disabled')
        b_back.config(state='normal' if free and (state.get('scene') or state.get('scene_bad')) else 'disabled')

    def scene_back(auto=False):
        """Back to normal (auto: by itself after the game closed, no questions unless needed): the test scene out of the
        restored-content file, the saves as before the first test. True when nothing is installed any more."""
        if state.get('busy'): return False
        sst, sbad = scene.load()
        if sbad:
            copies = scene.copies()
            if not copies:
                return set_aside(sbad)
            if not messagebox.askyesno(TESTER, '%s\n\nA copy of it is in the backup folder:\n%s\n\nUse that copy?'
                                       % (sbad, os.path.dirname(copies[0][0]))):
                return False
            try:
                scene.use_copy(copies[0][0])
            except Exception as e:
                messagebox.showerror(TESTER, 'The copy could not be used:\n%s' % e); refresh(); return False
            sst, sbad = scene.load()
            if sbad:
                messagebox.showerror(TESTER, sbad); refresh(); return False
        if not sst:
            refresh(); return True
        why = scene.busy_reason(sst)
        if why:
            if not auto: messagebox.showwarning(TESTER, why)
            return False
        import scenetest_session as STS
        nosaves = not sst.get('saves')             # nothing was backed up (no Steam saves folder at the first test)
        restore, q = True, scene.question(sst)
        if q:
            ans = messagebox.askyesnocancel(TESTER, '%s\n\nPut back the saves from before the test?\n\nYes: your saves '
                                                    'go back to how they were before the test (the newer ones are kept '
                                                    'in the backup folder).\nNo: only the test scene is taken out; '
                                                    'your saves stay as they are now.' % q)
            if ans is None: return False
            restore = bool(ans)
        elif not auto:
            if not messagebox.askokcancel(TESTER, 'Take the test scene out? (Your saves were not backed up for this '
                                                  'test, so they stay as they are.)' if nosaves else
                                          'Take the test scene out and put your saves back as they were before '
                                          'the test?'):
                return False

        def run_back(folder_gone):
            try:
                root.config(cursor='watch'); root.update()
                return scene.back(restore, folder_gone=folder_gone)
            finally:
                root.config(cursor='')
        try:
            try:
                rep = run_back(False)
            except STS.FolderMissing as e:         # a drive or SD card not connected: the test stays until it is back
                if auto:
                    messagebox.showwarning(TESTER, str(e)); return False
                if not messagebox.askyesno(TESTER, '%s\n\nOr is the game no longer installed there? Yes: forget the '
                                                   'test scene there%s. No: keep it for now.' % (
                                                       e, '' if nosaves or not restore else ' and put your saves back'),
                                           icon='warning', default='no'):
                    return False
                rep = run_back(True)
        except Exception as e:
            messagebox.showerror(TESTER, 'Back to normal failed:\n%s' % in_restore(str(e))); return False
        finally:
            refresh()
        if rep.get('patch') == 'left':
            msg = 'The restored-content file was left as it is: %s.' % in_restore(rep.get('note'))
        else:
            msg = '%sBack to normal: the test scene is out of the restored-content file.' % (
                'The game was closed. ' if auto else '')
        if isinstance(rep.get('saves'), dict):
            msg += ('\n\nYour saves are back as they were before the test. Saves made during the test are kept in:\n%s'
                    '\n\nIf Steam Cloud brings such a save back, loading it only shows an error: load another save.'
                    % rep['backup'])
        elif rep.get('saves') == 'none':
            msg += ('\n\nYour saves were not backed up for this test (no Steam saves folder was found), so they stay '
                    'as they are.')
        messagebox.showinfo(TESTER, msg)
        return True

    def set_aside(sbad):
        """Back to normal with an unreadable record and no copy of it: nothing can be put back automatically, and until
        the record is gone Altered Fable Restore refuses Rebuild and Turn OFF / ON. After a warning the record is set
        aside (kept as session.json.unreadable); a rebuild then writes a clean restored-content file, and the saves
        from before the test stay in the backup folder. True when the record was set aside."""
        import scenetest_session as STS
        if not messagebox.askyesno(TESTER, '%s\n\nNo copy of it was found, so nothing can be put back automatically. '
                                           'Your saves from before the test are in:\n%s\n\nSet the record aside? It is '
                                           'kept next to it as "session.json.unreadable". The test scene may still be '
                                           'in the restored-content file: Altered Fable Restore\'s "Build & install" '
                                           'then writes a clean one.' % (sbad, scene.backups),
                                   icon='warning', default='no'):
            refresh(); return False
        kept = STS.free_name(scene.session_path + '.unreadable')
        try:
            os.replace(scene.session_path, kept)
        except FileNotFoundError:                  # (gone meanwhile: nothing to set aside)
            refresh(); return True
        except OSError as e:
            messagebox.showerror(TESTER, 'The record could not be set aside:\n%s' % e); refresh(); return False
        refresh()
        clean = state.get('on') or not state.get('present')    # the file in the game folder is the built one, or none
        messagebox.showinfo(TESTER, 'The scene test record was set aside:\n%s\n\n%s' % (kept, (
            'The restored-content file is the one Altered Fable Restore built, so nothing else needs doing.' if clean else
            'The restored-content file is not the one Altered Fable Restore built (the test scene may still be in it). '
            'Close this app, open Altered Fable Restore and click "Build & install": it writes a clean one.')))
        return True

    def scene_watch():
        """Every 3 s while a scene test is installed: is the game running? (asked in a thread: tasklist takes a
        moment). SETTLE seconds after it closed, Back to normal runs by itself (when its check box is ticked)."""
        try:
            import scenetest_session as STS
            r = sstate.pop('result', None)
            if r is True:
                sstate['seen'] = True; sstate['closed_at'] = None
            elif r is False and sstate['seen']:
                if sstate['closed_at'] is None:
                    sstate['closed_at'] = time.time()
                elif time.time() - sstate['closed_at'] >= STS.SETTLE:
                    sstate['seen'] = False; sstate['closed_at'] = None
                    scene.game_closed()
                    if st.get('scenetest_auto', True) and state.get('scene') and not state.get('busy'):
                        scene_back(auto=True)
                    refresh()
            if (state.get('scene') or sstate['seen']) and not sstate['checking']:
                sstate['checking'] = True

                def look():
                    try: sstate['result'] = bool(game_running())
                    except Exception: pass
                    sstate['checking'] = False
                threading.Thread(target=look, daemon=True).start()
        except Exception:
            pass
        root.after(3000, scene_watch)

    def scene_refusal():
        """Why a scene test cannot be played now, or None."""
        return content_problem() or scene.busy_reason(state.get('scene'))

    def play_scene():
        if state.get('busy'): return
        refresh()                                   # (the game folder, the file or the session may have changed)
        why = scene_refusal()
        if why:
            messagebox.showwarning(TESTER, why); return
        nosaves = False                            # a first test with no Steam saves folder found: only by choice
        if not state.get('scene'):
            import scenetest_session as STS
            try: nosaves = not scene.remotes()
            except Exception: nosaves = True
            if nosaves and not messagebox.askyesno(TESTER, '%s\n\nPlay the test anyway? Your saves are then not '
                                                           'backed up, and Back to normal only takes the test scene '
                                                           'out.' % STS.NO_SAVES, icon='warning', default='no'):
                return
        item, leadin = sel.get(), lead.get()
        st['scenetest_item'], st['scenetest_leadin'] = item, leadin; save_settings(st)
        pm, fp = st.get('pm'), st.get('patch_fp')
        state['busy'] = True; refresh()
        tbar.config(mode='indeterminate'); tbar.start(15)
        q = queue.Queue()

        def work():
            try: q.put(('ok', scene.install(pm, fp, item, leadin, progress=lambda t: q.put(('phase', t)),
                                            without_saves=nosaves)))
            except Exception as e: q.put(('error', e))
        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                while True:
                    kind, val = q.get_nowait()
                    if kind == 'phase':
                        installed.config(text=val, fg='#333'); continue
                    tbar.stop(); tbar.config(mode='determinate', value=0)
                    state['busy'] = False
                    if kind == 'error':
                        refresh()
                        messagebox.showerror(TESTER, 'The test scene could not be installed:\n%s'
                                             % in_restore(str(val)))
                        return
                    tbar['value'] = 100
                    sstate['seen'] = False; sstate['closed_at'] = None
                    started = scene.launched(STEAM_URL)
                    refresh()
                    if not started:
                        messagebox.showinfo(TESTER, 'The test scene is installed. Start Muv-Luv photonmelodies from '
                                                    'your Steam library.' + (
                            '' if osc.IS_WIN else '\n\nSteam Deck: in Gaming Mode the test scene plays too; come '
                                                  'back to this app afterwards and click "Back to normal".'))
                    return
            except queue.Empty:
                pass
            root.after(150, poll)
        poll()

    def on_close():
        if state.get('busy'): return                # a test scene is being written (seconds): the file stays whole
        root.destroy()
    b_go.config(command=play_scene)
    root.protocol('WM_DELETE_WINDOW', on_close)
    refresh()
    root.after(2000, scene_watch)
    root.deiconify(); root.lift(); root.attributes('-topmost', True)
    root.after(300, lambda: root.attributes('-topmost', False))
    root.mainloop()
    return None


# ---------------------------------------------------------------- --selftest (CI smoke run of the frozen app)
# the builder modules bundled next to app.py (AFRestore.spec hiddenimports, minus build_all: importing it runs a build)
BUNDLED = ('oscompat', 'objio', 'ruowrite', 'crsa', 'rsaparse', 'builder', 'heapwriter', 'blocks', 'scenes', 'align',
           'flow', 'crimp', 'oorparse', 'entext', 'cgcrop', 'reencache', 'scenekit', 'scenetest_session')
# standard modules the app imports only inside functions (update download, Windows process lookup, the build)
LAZY_STDLIB = ('zipfile', 'tarfile', 'posixpath', 'gzip', 'zlib', 'struct', 'runpy', 'importlib.util', 'ast', 'traceback') + \
              (('ctypes', 'ctypes.wintypes', 'winreg') if os.name == 'nt' else ())


def selftest():
    """--selftest: import every bundled module (build_all only located, not run), the GUI toolkit's modules and a Tcl
    interpreter (no Tk, so no window), and load the data files. No window or message box, no network, no file written;
    the settings folder is not touched. Ends in selftest_end(): 'SELFTEST OK <version>' (0) or the error (3)."""
    step = 'starting'
    try:
        import importlib, importlib.util, ast
        for name in ('stdout', 'stderr'):          # windowed exe without a console: None, but the builder modules
            if getattr(sys, name) is None:         # reconfigure sys.stdout when they are imported
                setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
        for mod in BUNDLED + LAZY_STDLIB:
            step = 'importing ' + mod
            importlib.import_module(mod)
        step = 'locating build_all'
        spec = importlib.util.find_spec('build_all')
        if spec is None or spec.loader is None:
            raise ImportError('build_all is not bundled')
        code = spec.loader.get_code('build_all') if hasattr(spec.loader, 'get_code') else False   # compiled, not run
        if code is None:
            raise ImportError('build_all has no code')
        step = 'AF_PATCH = build_all.AF_PATCH'          # the window's official-update note checks what the build uses
        if code and AF_PATCH not in code.co_consts:
            raise ValueError('AF_PATCH %r differs from the builder\'s' % (AF_PATCH,))
        step = 'scenekit copies of build_all code'      # the scene test checks scripts with the builder's heap reader
        if code:
            import scenekit
            why = scenekit.builder_code_matches(code)
            if why: raise ValueError(why)
        step = 'tkinter'
        import tkinter, tkinter.ttk, tkinter.filedialog, tkinter.messagebox      # (modules only: no Tk, no window)
        tcl = tkinter.Tcl()                                 # Tcl without Tk: finds the bundled init.tcl
        tcl.eval('info patchlevel')
        step = 'TLS / hashes'
        osc.ssl_context(); hashlib.sha256(b'').hexdigest(); hashlib.sha1(b'').hexdigest()
        step = 'data/required.json'
        if not all(isinstance(REQ.get(k), dict) and REQ[k] for k in ('pm', 'af')):
            raise ValueError('required.json lacks the pm / af tables')
        step = 'data/heaps.json'
        heaps = json.load(open(os.path.join(DATA, 'heaps.json'), encoding='utf-8'))
        if not heaps.get('pm_rsa') or not all(isinstance(v, list) for v in heaps.values()):
            raise ValueError('heaps.json has no script list')
        for f in ('objmap.json', 'sound_pairs.json'):
            step = 'data/' + f
            if not json.load(open(os.path.join(DATA, f), encoding='utf-8')):
                raise ValueError('%s is empty' % f)
        step = 'omsig_data.txt'
        with open(os.path.join(BASE, 'omsig_data.txt'), encoding='utf-8') as f:
            if not ast.literal_eval(f.read()):
                raise ValueError('omsig_data.txt is empty')
        for path, magic in ((ICON_ICO, b'\0\0\1\0'), (ICON_PNG, b'\x89PNG\r\n\x1a\n')):
            step = 'icon ' + os.path.basename(path)
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    if f.read(len(magic)) != magic: raise ValueError('not an icon file')
        if SCENE_TESTER:                                    # the Scene Tester: its scene list and side picture
            step = 'scene tester'
            import scenekit
            if not scenekit.PUBLIC or sorted(set(g for g, _, _ in scenekit.PUBLIC)) != sorted(scenekit.GROUPS):
                raise ValueError('the scene list is empty or has a group without a frame')
            if not os.path.isfile(ICON_PNG): raise ValueError('data/afrestore.png (the side picture) is missing')
    except BaseException as e:
        selftest_end('%s: %s' % (step, describe(e)))
    selftest_end()


def selftest_scenetest(fixture=None):
    """--selftest-scenetest [FIXTURE] (tests only; no window, no game, no real folder): the scene test end to end on
    fake folders in a new temp folder (deleted afterwards): kit check, refusal while the game runs, first install with
    the saves backup, the wait after a Play, swap, a crash in the middle of an append, an unreadable session file and
    its copy, Back to normal (patch file and saves compared by sha1), a foreign patch file left alone, Back to normal
    refused while the game folder is not there (and forgotten on request), no Steam saves folder. FIXTURE: a folder
    made by the lab tests (pm/<patch> + kit/, from real data: the opening checks run on real scripts); without it a
    synthetic patch and kit are used and the opening check is replaced by a byte check. Prints 'SCENETEST OK' (exit 0)
    or ends in selftest_end() with the error (exit 3)."""
    import tempfile
    step = 'starting'
    tmp = tempfile.mkdtemp(prefix='afr-scenetest-')
    try:
        for name in ('stdout', 'stderr'):
            if getattr(sys, name) is None: setattr(sys, name, open(os.devnull, 'w', encoding='utf-8'))
        import scenekit as SK, scenetest_session as STS
        home, pm = os.path.join(tmp, 'home'), os.path.join(tmp, 'pm')
        remote = os.path.join(tmp, 'Steam', 'userdata', '42', APP_ID, 'remote')
        os.makedirs(remote); os.makedirs(pm); os.makedirs(os.path.join(home, 'scenetest'))
        live = os.path.join(pm, PATCH)
        kit_dir = os.path.join(home, 'scenetest', 'kit')
        if fixture:
            step = 'fixture'
            shutil.copyfile(os.path.join(fixture, 'pm', PATCH), live)
            shutil.copytree(os.path.join(fixture, 'kit'), kit_dir)
        else:
            step = 'synthetic kit'
            _synthetic_kit(live, kit_dir)
            SK.check_opening = lambda old, new, at, calls: (dict(calls=list(calls), lands=at + len(calls)), [])
            SK.last_kind = lambda obj: 'CVmRet'
        kit = SK.load_kit(kit_dir)
        items = list(kit['items'])
        fp = SK.fingerprint(live)
        orig = STS.sha1_file(live)
        with open(live, 'rb') as f: orig_bytes = f.read()
        for n, d in (('gdb.uuc', b'settings' * 64), ('q0000001.uux', b'save' * 99)):
            with open(os.path.join(remote, n), 'wb') as f: f.write(d)
        saves = dict((n, STS.sha1_file(os.path.join(remote, n))) for n in os.listdir(remote))
        running = [False]
        T = STS.SceneTest(home, PATCH, lambda: running[0], lambda url: True, lambda: [('42', remote)])
        step = 'can_test'
        why = T.can_test(pm, fp)
        if why: raise AssertionError(why)
        step = 'refused while the game runs'
        running[0] = True
        try:
            T.install(pm, fp, items[0], 'with'); raise AssertionError('installed while the game runs')
        except STS.SessionError:
            pass
        running[0] = False
        if T.load() != (None, None) or SK.fingerprint(live) != fp: raise AssertionError('a refused install changed something')
        step = 'install'
        s1 = T.install(pm, fp, items[0], 'with')
        if s1['step'] != 'installed' or len(s1['saves'][0]['manifest']) != 2: raise AssertionError(s1['step'])
        step = 'the wait after a Play'
        T.launched(STEAM_URL)
        if not T.busy_reason(T.load()[0]): raise AssertionError('no wait right after a Play')
        T.game_closed()
        if T.busy_reason(T.load()[0]): raise AssertionError('still waiting after the game closed')
        with open(os.path.join(remote, 'gdb.uuc'), 'wb') as f: f.write(b'changed in the test')
        step = 'swap'
        s2 = T.install(pm, fp, items[-1], 'skip')
        if s2['tests'] != 2 or s2['backup'] != s1['backup']: raise AssertionError('the swap made a new session')
        step = 'a crash in the middle of an append'
        st, _ = T.load()
        SK.undo_tail(live, st['orig'])                          # as the start of a swap does
        prep = SK.prepare(live, kit, items[0], 'skip')
        st['step'] = 'appending'; T.save(st)
        with open(live, 'r+b') as f:
            f.seek(0, 2); f.write(prep['tail'][:max(1, len(prep['tail']) // 2)])
        try:
            T.install(pm, fp, items[0], 'with'); raise AssertionError('swap over a half-written append')
        except STS.SessionError:
            pass
        step = 'an unreadable session file'
        with open(T.session_path, 'w') as f: f.write('{not json')
        st, bad = T.load()
        if not bad: raise AssertionError('an unreadable session file was not noticed')
        try:
            T.install(pm, fp, items[0], 'with'); raise AssertionError('installed over an unreadable session')
        except STS.SessionError:
            pass
        copies = T.copies()
        if not copies: raise AssertionError('no session copy in the backup folder')
        T.use_copy(copies[0][0])
        step = 'Back to normal'
        st, bad = T.load()
        if bad or not st: raise AssertionError('the copy is not usable')
        if T.question(st): raise AssertionError('asked although only gdb.uuc changed: %s' % T.question(st))
        rep = T.back(True)
        if STS.sha1_file(live) != orig or SK.fingerprint(live) != fp: raise AssertionError('patch not the original: %s' % rep)
        if dict((n, STS.sha1_file(os.path.join(remote, n))) for n in os.listdir(remote)) != saves:
            raise AssertionError('the saves are not as before')
        if not os.path.isfile(os.path.join(rep['backup'], 'changed-during-test', '42', 'gdb.uuc')):
            raise AssertionError('the changed gdb.uuc was not kept')
        if T.load() != (None, None): raise AssertionError('a session is left')
        step = 'a foreign patch file is left alone'
        s3 = T.install(pm, fp, items[0], 'skip')
        with open(live, 'r+b') as f:
            f.seek(s3['orig']['S'] - 8); f.write(b'XXXXXXXX')           # the old table changed: not our file any more
        r3 = T.back(True)
        if r3['patch'] != 'left' or os.path.getsize(live) != s3['planned']['size']:
            raise AssertionError('a foreign file was changed: %s' % r3)
        step = 'Back to normal while the game folder is not there'
        with open(live, 'wb') as f: f.write(orig_bytes)
        T.install(pm, fp, items[0], 'skip')
        os.rename(pm, pm + '-away')
        try:
            T.back(True); raise AssertionError('Back to normal went on without the game folder')
        except STS.FolderMissing:
            pass
        if T.load()[0] is None: raise AssertionError('the session was closed without the game folder')
        os.rename(pm + '-away', pm)
        r4 = T.back(True)
        if r4['patch'] != 'removed' or STS.sha1_file(live) != orig: raise AssertionError('not taken out: %s' % r4)
        step = 'the game folder gone for good'
        T.install(pm, fp, items[0], 'skip')
        os.rename(pm, pm + '-away')
        r5 = T.back(True, folder_gone=True)
        os.rename(pm + '-away', pm)
        if r5['patch'] != 'left' or not isinstance(r5['saves'], dict) or T.load() != (None, None):
            raise AssertionError(r5)
        with open(live, 'wb') as f: f.write(orig_bytes)
        step = 'no Steam saves folder'
        T0 = STS.SceneTest(home, PATCH, lambda: False, lambda url: True, lambda: [])
        try:
            T0.install(pm, fp, items[0], 'skip'); raise AssertionError('installed without the saves backup')
        except STS.NoSavesFolder:
            pass
        if T0.load() != (None, None) or STS.sha1_file(live) != orig: raise AssertionError('the refusal changed something')
        if T0.install(pm, fp, items[0], 'skip', without_saves=True)['saves'] != []: raise AssertionError('saves listed')
        r6 = T0.back(True)
        if r6['saves'] != 'none' or STS.sha1_file(live) != orig: raise AssertionError(r6)
    except BaseException as e:
        shutil.rmtree(tmp, ignore_errors=True)
        selftest_end('%s: %s' % (step, describe(e)))
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        sys.stdout.write('SCENETEST OK %s (%s)\n' % (APP_VERSION, 'fixture' if fixture else 'synthetic')); sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)


def _synthetic_kit(live, kit_dir):
    """A tiny patch file and a kit for it, random bytes only (--selftest-scenetest without a fixture)."""
    import scenekit as SK, struct, zlib, random
    from crsa import encrypt_block
    rnd = random.Random(7)
    K = 0xA2FB6AD1
    objs = [((K + 0x78000000 + 0x10 * i) & 0xFFFFFFFF, bytes(rnd.getrandbits(8) for _ in range(301 + i))) for i in range(4)]
    blob = bytearray(); table = []
    for key, data in objs:
        while len(blob) % 4: blob.append(0)
        table.append(struct.pack('<III', key, (K + ((4096 + len(blob)) >> 2)) & 0xFFFFFFFF, SK.enc_size(len(data))))
        blob += data
    while len(blob) % 4: blob.append(0)
    with open(live, 'wb') as f: f.write(bytes(4096) + bytes(blob) + b''.join(table) + struct.pack('<I', len(table)))
    hdr9 = bytes(range(9))
    orig = b'original opening' * 50
    files, items = {'open/original.z': zlib.compress(orig)}, {}
    for name, gf in (('one', False), ('two', True)):
        heap = (b'opening for ' + name.encode()) * 40
        files['open/%s-skip.z' % name] = zlib.compress(heap)
        obj = bytes([0, 5]) + hdr9 + encrypt_block(heap)
        it = dict(group=SK.G18, label=name.title(), lines=3, lead_lines=0, leadins=[], gf=None, openings={})
        calls = [[objs[1][0], SK.enc_size(len(objs[1][1]))]]
        if gf:
            g = bytes(rnd.getrandbits(8) for _ in range(777))
            files['gf/two.bin'] = g
            it['gf'] = dict(key=(K + 0x79000000) & 0xFFFFFFFF, file='gf/two.bin', size=len(g), sha1=SK.sha1(g), imports=[])
            calls = [[it['gf']['key'], SK.enc_size(len(g))]]
        it['openings']['skip'] = dict(file='open/%s-skip.z' % name, heap_size=len(heap), heap_sha1=SK.sha1(heap),
                                      size=len(obj), sha1=SK.sha1(obj), calls=calls, id_start=0, parts=[name], preds=[])
        items[name] = it
    kit = dict(format=SK.FORMAT, kind='scenekit', built='synthetic', K=K, entry=SK.ENTRY, at=SK.AT,
               entry_key=SK.entry_key(K), hdr9=hdr9.hex(), en=False, english_lines=0, release_objects=len(objs),
               original=dict(file='open/original.z', size=len(orig), sha1=SK.sha1(orig)), items=items)
    SK.write_kit(kit_dir, kit, files, live)
    return list(items)


if __name__ == '__main__':
    if SELFTEST and sys.argv[1] == '--selftest-scenetest':
        selftest_scenetest(sys.argv[2] if len(sys.argv) > 2 else None)
    elif SELFTEST:
        selftest()
    elif len(sys.argv) >= 5 and sys.argv[1] == '--build':
        do_build(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    else:
        gui()
