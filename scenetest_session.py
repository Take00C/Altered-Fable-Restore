"""Test a scene: the session around one scene test (shipped with Altered Fable Restore; scenekit.py does the patch file).

  install(pm_dir, fp, item, leadin)   first test: the Steam saves of every account are backed up, then the test is
                                      appended to the installed patch (scenekit); a later test only takes the old one
                                      out and puts the new one in (the first backup stays the one Back to normal uses).
                                      No Steam saves folder found: refused (NoSavesFolder) unless the player chose to
                                      go on without the backup (without_saves=True)
  launched()                          a Play started the game: changes are refused for LAUNCH_GRACE seconds
  back(restore_saves)                 the test is taken out of the patch (cut back to its old size: the file is the
                                      original again byte for byte) and the saves are put back as they were before the
                                      first test; saves made or changed meanwhile are kept in the backup folder
                                      (created-during-test, changed-during-test), never deleted. The game folder not
                                      there (a drive or SD card not connected): refused (FolderMissing), the session
                                      stays, unless the player says the game is gone from there (folder_gone=True)

The session file <home>/scenetest/session.json is written (flushed to the disk, through a temp file) before every
step, with a copy in the backup folder: a closed launcher, a crash or a power cut leaves a session the next start can
finish (a half-written append is cut off too). An unreadable session file stops every change until the copy is put
back (use_copy). Every change is refused while the game runs (on Windows the running game also locks the patch file).

Saves (Muv-Luv_PM.exe: gdb.uuc settings / read flags / gallery, vmr%05d.uuc, q%07u.uux) live in Steam's
userdata/<account>/889710/remote. Restored files get the current time (copyfile), so Steam treats them as a local change
(inferred). Everything that touches the system (game detection, starting the game, the Steam folders) is passed in,
so tests run on fake folders only."""
import os, sys, json, time, shutil, hashlib

import scenekit as SK

FORMAT = 1
LAUNCH_GRACE = 120          # seconds after a Play in which nothing is changed (Steam may still be starting the game)
FORGOTTEN = 24 * 3600       # a test older than this: Back to normal asks before it puts the saves back
SETTLE = 15                 # seconds the game must be closed before the automatic Back to normal
SYSTEM_SAVE = 'gdb.uuc'     # written by every START (settings, read flags): put back without asking


class SessionError(RuntimeError):
    """Refused or failed (shown to the player as it is)."""


class FolderMissing(SessionError):
    """Back to normal: the game folder the test was put into is not there (a drive or SD card not connected?). The
    session stays; back(folder_gone=True) closes it without touching the patch file."""


class NoSavesFolder(SessionError):
    """A first install: no Steam saves folder was found, so the saves cannot be backed up. install(without_saves=True)
    goes on without the backup (the player's choice)."""


NO_SAVES = 'No Steam saves folder (Steam/userdata) was found, so your saves cannot be backed up before the test.'


def sha1_file(p):
    h = hashlib.sha1()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()


def write_json(p, data):
    """JSON through p.tmp, flushed to the disk before it replaces p (a crash leaves the old file or the new one)."""
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    for i in range(40):
        try:
            os.replace(tmp, p); return
        except PermissionError:
            if i == 39: raise
            time.sleep(0.1)


def free_name(q):
    """q, or q.<n> when q exists (a kept file is never overwritten)."""
    if not os.path.exists(q): return q
    k = 1
    while os.path.exists('%s.%d' % (q, k)): k += 1
    return '%s.%d' % (q, k)


def snapshot_dir(src, dst):
    """Copy folder src into dst; {relative path ('/'-separated): sha1} of every file, checked on the copy."""
    man = {}
    os.makedirs(dst, exist_ok=True)
    for base, dirs, files in os.walk(src):
        for f in files:
            p = os.path.join(base, f); rel = os.path.relpath(p, src).replace(os.sep, '/')
            q = os.path.join(dst, *rel.split('/')); os.makedirs(os.path.dirname(q), exist_ok=True)
            shutil.copy2(p, q)
            h = sha1_file(p)
            if sha1_file(q) != h: raise SessionError('The save backup copy differs: %s' % q)
            man[rel] = h
    return man


def changes(live, man):
    """(created, changed) relative paths of folder `live` against a snapshot manifest."""
    created, changed = [], []
    if os.path.isdir(live):
        for base, dirs, files in os.walk(live):
            for f in files:
                p = os.path.join(base, f); rel = os.path.relpath(p, live).replace(os.sep, '/')
                if rel not in man: created.append(rel)
                elif sha1_file(p) != man[rel]: changed.append(rel)
    return sorted(created), sorted(changed)


def restore_dir(live, snap, man, created_dir, changed_dir):
    """Make folder `live` equal to the snapshot: files not in it are MOVED into created_dir; a file that differs is
    first copied into changed_dir (sha1-checked), then the snapshot's version is copied back (current time: copyfile);
    missing files are copied back. Nothing is deleted. Returns (put back, moved aside, changed versions kept)."""
    restored = moved = kept = 0
    if os.path.isdir(live):
        for base, dirs, files in os.walk(live):
            for f in files:
                p = os.path.join(base, f); rel = os.path.relpath(p, live).replace(os.sep, '/')
                if rel in man: continue
                q = os.path.join(created_dir, *rel.split('/')); os.makedirs(os.path.dirname(q), exist_ok=True)
                shutil.move(p, free_name(q)); moved += 1
    for rel, h in sorted(man.items()):
        p = os.path.join(live, *rel.split('/'))
        if os.path.isfile(p):
            cur = sha1_file(p)
            if cur == h: continue
            q = free_name(os.path.join(changed_dir, *rel.split('/'))); os.makedirs(os.path.dirname(q), exist_ok=True)
            shutil.copy2(p, q)
            if sha1_file(q) != cur: raise SessionError('Copy check failed: %s' % q)
            kept += 1
        os.makedirs(os.path.dirname(p), exist_ok=True)
        shutil.copyfile(os.path.join(snap, *rel.split('/')), p)
        if sha1_file(p) != h: raise SessionError('A save did not read back as backed up: %s' % p)
        restored += 1
    return restored, moved, kept


class SceneTest:
    """One player's scene test state. home: the app's settings folder; patch_name: photonmelodies11.rio.ruo1;
    game_running() -> bool; open_url(url) -> bool; remotes() -> [(account, remote folder)] (osc.steam_userdata_remotes);
    clock() -> seconds."""

    def __init__(self, home, patch_name, game_running, open_url=None, remotes=None, log=None, clock=time.time):
        self.root = os.path.join(home, 'scenetest')
        self.session_path = os.path.join(self.root, 'session.json')
        self.kit_dir = os.path.join(self.root, 'kit')
        self.backups = os.path.join(self.root, 'backups')
        self.patch_name = patch_name
        self.game_running = game_running
        self.open_url = open_url or (lambda url: False)
        self.remotes = remotes or (lambda: [])
        self.log = log or (lambda *a: None)
        self.clock = clock

    # ---- the session file
    def load(self):
        """(session dict or None, problem or None). A file that exists but cannot be read is a problem: every change
        is refused until use_copy() puts its copy back."""
        try:
            with open(self.session_path, encoding='utf-8') as f: st = json.load(f)
        except FileNotFoundError:
            return None, None
        except (OSError, ValueError) as e:
            return None, 'The scene test record cannot be read (%s).' % e.__class__.__name__
        if not isinstance(st, dict) or st.get('format') != FORMAT or not st.get('backup'):
            return None, 'The scene test record is not one this version of the app understands.'
        return st, None

    def save(self, st):
        st['saved'] = self.clock()
        write_json(self.session_path, st)
        try: write_json(os.path.join(st['backup'], 'session.json'), st)
        except OSError: pass

    def copies(self):
        """Readable session copies in the backup folders, newest first: [(path, session)]."""
        out = []
        try: names = sorted(os.listdir(self.backups), reverse=True)
        except OSError: return out
        for n in names:
            p = os.path.join(self.backups, n, 'session.json')
            try:
                with open(p, encoding='utf-8') as f: st = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(st, dict) and st.get('format') == FORMAT and st.get('step') != 'done': out.append((p, st))
        return out

    def use_copy(self, path):
        """Put a session copy back in place of an unreadable session file (that file is kept, renamed)."""
        with open(path, encoding='utf-8') as f: st = json.load(f)
        if os.path.exists(self.session_path):
            os.replace(self.session_path, free_name(self.session_path + '.unreadable'))
        write_json(self.session_path, st)
        return st

    def _close(self, st, how):
        st['step'] = 'done'; st['closed'] = how; st['closed_at'] = time.strftime('%Y-%m-%d %H:%M:%S')
        try: write_json(os.path.join(st['backup'], 'session.json'), st)
        except OSError: pass
        try: os.remove(self.session_path)
        except FileNotFoundError: pass

    # ---- state for the window
    def kit(self):
        return SK.load_kit(self.kit_dir)

    def status(self):
        """(session, problem) for the window; a session's 'test' says what is installed."""
        return self.load()

    def busy_reason(self, st=None):
        """Why nothing may change now, or None: the game runs, or a Play started it less than LAUNCH_GRACE s ago."""
        if self.game_running(): return 'Close Muv-Luv photonmelodies first.'
        if st and st.get('launched_at'):
            left = LAUNCH_GRACE - (self.clock() - st['launched_at'])
            if 0 < left <= LAUNCH_GRACE:
                return ('The game was started %d seconds ago and may still be starting. Close it if it is open, or '
                        'try again in %d seconds.' % (self.clock() - st['launched_at'], left + 1))
        return None

    def can_test(self, pm_dir, patch_fp):
        """None when a scene test can be installed now, else why not (for the window)."""
        try:
            kit = self.kit()
        except SK.KitError as e:
            return str(e)
        live = os.path.join(pm_dir, self.patch_name)
        st, bad = self.load()
        if bad: return bad
        if st: return None                         # a swap checks the original size and table itself
        why = SK.check_patch(live, kit)
        if why: return why[0].upper() + why[1:] + '. Click "Rebuild & install" once.'
        if patch_fp and SK.fingerprint(live) != list(patch_fp):
            return 'The restored-content file is not the one this app built. Click "Rebuild & install" once.'
        return None

    # ---- install / swap
    def install(self, pm_dir, patch_fp, item, leadin, progress=None, without_saves=False):
        """Put the test (item, leadin) into the installed patch. Returns the session. A first install with no Steam
        saves folder found raises NoSavesFolder unless without_saves (the player chose to go on without the backup)."""
        say = progress or (lambda *a: None)
        st, bad = self.load()
        if bad: raise SessionError(bad + ' Use Back to normal: it offers the copy from the backup folder.')
        why = self.busy_reason(st)
        if why: raise SessionError(why)
        kit = self.kit()
        live = os.path.join(pm_dir, self.patch_name)
        if st:
            if os.path.normcase(os.path.abspath(st['patch'])) != os.path.normcase(os.path.abspath(live)):
                raise SessionError('A scene test is installed in another game folder: use Back to normal first.')
            if st.get('step') not in ('installed', 'running'):
                raise SessionError('The last scene test stopped half-way: use Back to normal first.')
            say('Taking the current test scene out…')
            st['step'] = 'removing'; self.save(st)
            SK.undo_tail(live, st['orig'], self._settle)
            prep = SK.prepare(live, kit, item, leadin)
            fresh = False
        else:
            why = SK.check_patch(live, kit)
            if why: raise SessionError(why[0].upper() + why[1:] + '. Click "Rebuild & install" once.')
            if patch_fp and SK.fingerprint(live) != list(patch_fp):
                raise SessionError('The restored-content file is not the one this app built. Click "Rebuild & '
                                   'install" once.')
            prep = SK.prepare(live, kit, item, leadin)          # everything checked before the saves are backed up
            remotes = list(self.remotes())
            if not remotes and not without_saves: raise NoSavesFolder(NO_SAVES)
            st = self._new_session(live, kit, say, remotes)
            fresh = True
        say('Adding the test scene…')
        if (prep['S'], prep['n'], prep['orig_tail_sha1']) != (st['orig']['S'], st['orig']['n'], st['orig']['tail_sha1']):
            raise SessionError('The restored-content file is not the one the test began with: use Back to normal.')
        p = prep['plan']
        st.update(step='appending', planned=dict(tail_sha1=prep['tail_sha1'], size=prep['size_after']),
                  test=dict(item=item, leadin=p['leadin'], label=p['label'], parts=p['parts'], en=kit.get('en', False)))
        self.save(st)
        try:
            SK.write_tail(live, prep, self._settle)
        except BaseException as e:
            if os.path.getsize(live) == prep['S'] and fresh:
                self._close(st, 'nothing installed: %s' % e)     # nothing was written: no session to put back
            if isinstance(e, PermissionError):
                raise SessionError('The restored-content file is in use. Close Muv-Luv photonmelodies and try again.')
            raise
        say('Checking the patch file…')
        bad = SK.verify_tail(live, kit, prep)
        if bad:
            SK.undo_tail(live, st['orig'])
            st['step'] = 'installed-none'; st.pop('test', None); self.save(st)
            raise SessionError('The test scene did not read back as written (%s); it was taken out again. Use Back '
                               'to normal.' % '; '.join(bad[:3]))
        st['step'] = 'installed'; st['installed_at'] = self.clock(); st['tests'] = st.get('tests', 0) + 1
        st.pop('launched_at', None)
        self.save(st)
        self.log('scene test installed: %s (%s)' % (item, p['leadin']))
        return st

    def _settle(self):
        """Right before the patch file is opened for writing: the game must not run (Linux does not lock the file)."""
        if self.game_running(): raise SessionError('Close Muv-Luv photonmelodies first.')

    def _new_session(self, live, kit, say, remotes):
        n, table, tstart, S = SK.read_table(live)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        bk = free_name(os.path.join(self.backups, stamp))
        os.makedirs(bk)
        import struct
        st = dict(format=FORMAT, kind='scenetest', step='start', started=time.strftime('%Y-%m-%d %H:%M:%S'),
                  started_ts=self.clock(), backup=bk, patch=live, pm_dir=os.path.dirname(live),
                  orig=dict(S=S, n=n, tail_sha1=SK.sha1(table + struct.pack('<I', n)), fingerprint=SK.fingerprint(live)),
                  saves=[])
        self.save(st)
        say('Backing up your saves…')
        for acc, remote in remotes:
            ent = dict(account=str(acc), remote=remote, existed=os.path.isdir(remote), manifest={})
            if ent['existed']:
                ent['manifest'] = snapshot_dir(remote, os.path.join(bk, 'saves', str(acc)))
            cache = os.path.join(os.path.dirname(remote), 'remotecache.vdf')
            if os.path.isfile(cache):
                os.makedirs(os.path.join(bk, 'saves'), exist_ok=True)
                shutil.copy2(cache, os.path.join(bk, 'saves', '%s-remotecache.vdf' % acc))    # reference only
            st['saves'].append(ent)
        st['step'] = 'saves'; self.save(st)
        self.log('saves backed up: %s' % ', '.join('%s: %d files' % (e['account'], len(e['manifest']))
                                                   for e in st['saves']))
        return st

    # ---- Play
    def launched(self, url):
        """Start the game (url: steam://rungameid/...) and remember when; True when a handler took the URL."""
        st, bad = self.load()
        ok = bool(self.open_url(url))
        if st and not bad:
            st['launched_at'] = self.clock(); st['step'] = 'running' if st.get('step') == 'installed' else st['step']
            self.save(st)
        return ok

    def game_closed(self):
        """The game was seen running and is closed now: the LAUNCH_GRACE wait after a Play no longer applies."""
        st, bad = self.load()
        if st and not bad and st.get('launched_at'):
            st.pop('launched_at')
            if st.get('step') == 'running': st['step'] = 'installed'
            self.save(st)

    # ---- Back to normal
    def saves_changed(self, st):
        """[(account, relative path, 'created' | 'changed')] of save files other than gdb.uuc made or changed since the
        backup."""
        out = []
        for e in st.get('saves', []):
            c, ch = changes(e['remote'], e.get('manifest') or {})
            out += [(e['account'], r, 'created') for r in c if os.path.basename(r).lower() != SYSTEM_SAVE]
            out += [(e['account'], r, 'changed') for r in ch if os.path.basename(r).lower() != SYSTEM_SAVE]
        return out

    def question(self, st):
        """None when Back to normal can put the saves back without asking, else why it should ask: the test is older
        than FORGOTTEN, or save files other than gdb.uuc were made or changed meanwhile."""
        if st.get('step') in ('start',): return None
        age = self.clock() - (st.get('started_ts') or self.clock())
        if age > FORGOTTEN:
            return 'The scene test was installed %d days ago.' % max(1, age // 86400) if age >= 86400 * 2 else \
                'The scene test was installed more than a day ago.'
        ch = self.saves_changed(st)
        if ch:
            return '%d save file%s %s made or changed since the test began.' % (len(ch), '' if len(ch) == 1 else 's',
                                                                               'was' if len(ch) == 1 else 'were')
        return None

    def back(self, restore_saves=True, progress=None, folder_gone=False):
        """Take the test out and (restore_saves) put the saves back. Returns a report dict(patch, saves, backup).
        The game folder not there: FolderMissing (nothing changed, the session stays), unless folder_gone (the player
        says the game is no longer installed there): the patch file is left, the saves are put back, the session ends.
        report['saves']: dict(put_back, moved_aside, changed_kept), 'kept' (not restored) or 'none' (no saves folder
        was backed up at the first install)."""
        say = progress or (lambda *a: None)
        st, bad = self.load()
        if bad: raise SessionError(bad)
        if not st: return dict(patch='none', saves=None, backup=None)
        why = self.busy_reason(st)
        if why: raise SessionError(why)
        rep = dict(backup=st['backup'], patch=None, saves=None, note=None)
        folder = st.get('pm_dir') or os.path.dirname(st['patch'])
        if st.get('step') in ('start', 'saves'):
            rep['patch'] = 'untouched'                 # stopped before anything was appended
        elif not os.path.isdir(folder):
            # a drive or SD card that is not connected: the test is still in the file there, so the session stays
            # (closing it would leave the test in the patch with nothing to take it out later)
            if not folder_gone:
                raise FolderMissing('The game folder of the scene test is not available:\n%s\n\nIf it is on a drive '
                                    'or SD card that is not connected, connect it and try again.' % folder)
            rep['patch'] = 'left'
            rep['note'] = ('its folder is not available (%s). If the game is there again later, click "Rebuild & '
                           'install" once' % folder)
        else:
            say('Taking the test scene out…')
            st['step_before_back'] = st.get('step'); st['back'] = 'patch'; self.save(st)
            try:
                rep['patch'] = SK.undo_tail(st['patch'], st['orig'], self._settle)
            except SK.KitError as e:
                rep['patch'] = 'left'; rep['note'] = str(e)
            except PermissionError:
                raise SessionError('The restored-content file is in use. Close Muv-Luv photonmelodies and try again.')
            if rep['patch'] in ('clean', 'removed') and os.path.isfile(st['patch']):
                fp = st['orig'].get('fingerprint')
                if fp and SK.fingerprint(st['patch']) != list(fp):
                    raise SessionError('The restored-content file does not read back as before the test.')
        if restore_saves and st.get('step') != 'start' and st.get('saves'):
            say('Putting your saves back…')
            st['back'] = 'saves'; self.save(st)
            r = m = k = 0
            for e in st.get('saves', []):
                a = e['account']
                rr, mm, kk = restore_dir(e['remote'], os.path.join(st['backup'], 'saves', a), e.get('manifest') or {},
                                         os.path.join(st['backup'], 'created-during-test', a),
                                         os.path.join(st['backup'], 'changed-during-test', a))
                r += rr; m += mm; k += kk
            rep['saves'] = dict(put_back=r, moved_aside=m, changed_kept=k)
        elif restore_saves and st.get('step') != 'start':
            rep['saves'] = 'none'                      # no Steam saves folder was found at the first install
        else:
            rep['saves'] = 'kept'
        self._close(st, 'back to normal (%s, saves %s)' % (rep['patch'], 'restored' if isinstance(rep['saves'], dict)
                                                           else rep['saves']))
        self.log('back to normal: %s' % rep)
        return rep
