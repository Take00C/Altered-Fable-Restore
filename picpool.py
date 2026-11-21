"""Picture workers for the build's re-encodes (build_all's picture pass, reencache's misses). Pure Python, stdlib only.

A cold build (empty re-encode cache) re-encodes about 300 pictures. build_all plans them at the start of its main
section (picture_items: one item per AF original with every output made from it in both picture passes, each copy with
the thumbnails made from it), prefetch() works out which are not in the cache yet and computes them in worker
processes while the main process converts the scenes. The main process stays the only one that writes: reencache asks
take(key) on a cache miss and puts the result exactly as it puts its own (same key, meta, payload, counter), in the
build's own order, so the cache and the patch are the same bytes as a serial build. A result never consumed is dropped.

Workers are copies of the program itself: [sys.executable, '--afr-picworker'] frozen (app.py dispatches the flag before
anything else), [sys.executable, <interpreter flags>, '-c', <import picpool from this folder>, '--afr-picworker'] from
source. stdin / stdout are pipes (frames: 8-byte length + marshal), stderr is devnull, no window (CREATE_NO_WINDOW),
below-normal priority (Windows: BELOW_NORMAL_PRIORITY_CLASS; elsewhere os.nice to at least 10). A worker never writes
a file, never prints and exits at once when its stdin closes (the build ended or died). Before any work each worker
must report the main's coder identities (reencache._code_id / _gal_code_id, picfast's and this module's code, Python
version, executable) and compute the same bytes as the main on a small synthetic picture (known-answer test); every
reply echoes the digests of the inputs it was given.

Any failure falls back to the serial path, never to a broken picture: no worker started, a failed handshake, a worker
that dies or sends a bad frame (the pool stops; results already received and checked are kept), an item that raises
(that key is computed in the main as before, so a real BuildError reads the same).

Worker count: env AFR_JOBS ('' / auto = the default; a number up to 1 = serial, no worker; N = N workers, at most 64),
default min(logical CPUs - 2 (- 1 below 6), free memory less 1 GB / WORKER_MB, 16, items)."""
import os, sys, struct, marshal, threading, subprocess, hashlib, time

FLAG = '--afr-picworker'
PROTO = 1
WORKER_MB = 300             # memory allowance per worker for the default count (measured peak: impl RESULTS.json)
RESERVE_MB = 1024           # kept free for the main process
MAX_DEFAULT = 16
MAX_JOBS = 64
HANDSHAKE_S = 60
CREATE_NO_WINDOW, BELOW_NORMAL_PRIORITY_CLASS = 0x08000000, 0x00004000


# ---------------------------------------------------------------- worker count
def logical_cpus():
    try:
        return len(os.sched_getaffinity(0)) or 1
    except (AttributeError, OSError):
        return os.cpu_count() or 1


def avail_mb():
    """Free physical memory in MB, or None."""
    try:
        if os.name == 'nt':
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [('dwLength', ctypes.c_ulong), ('dwMemoryLoad', ctypes.c_ulong),
                            ('ullTotalPhys', ctypes.c_ulonglong), ('ullAvailPhys', ctypes.c_ulonglong),
                            ('ullTotalPageFile', ctypes.c_ulonglong), ('ullAvailPageFile', ctypes.c_ulonglong),
                            ('ullTotalVirtual', ctypes.c_ulonglong), ('ullAvailVirtual', ctypes.c_ulonglong),
                            ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
            m = MS(); m.dwLength = ctypes.sizeof(MS)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)): return None
            return m.ullAvailPhys // (1 << 20)
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemAvailable:'): return int(line.split()[1]) // 1024
    except Exception:
        pass
    return None


def worker_count(items):
    """(workers, note): 0 = serial."""
    v = (os.environ.get('AFR_JOBS') or '').strip().lower()
    note = ''
    if v not in ('', 'auto'):
        try:
            n = int(v)
            if n < 0: raise ValueError(v)
        except ValueError:
            note = 'AFR_JOBS=%r not understood, default count; ' % v
        else:
            if n <= 1: return 0, 'AFR_JOBS=%d: serial' % n          # (the number, as given: '01' is 1 too)
            return max(0, min(n, MAX_JOBS, items)), 'AFR_JOBS=%d' % n
    L = logical_cpus()
    cpu = max(1, L - 2 if L >= 6 else L - 1)
    a = avail_mb()
    mem = 4 if a is None else max(0, (a - RESERVE_MB) // WORKER_MB)
    n = max(0, min(cpu, mem, MAX_DEFAULT, items))
    return n, note + '%d logical CPUs, %s MB free' % (L, '?' if a is None else a)


# ---------------------------------------------------------------- the work (workers; the main for the known-answer test)
def _err(e):
    return (type(e).__name__, str(e))


def run_item(spec):
    """One item -> list of output results, in spec['outs'] order: ('ok', body, [thumb results]) / ('err', type, text,
    []); a thumbnail result is ('ok', body) / ('err', type, text). Kinds as reencache's: recrop (cgcrop.rebuild),
    galcopy / recut2 / galadd (galcg.rebuild_copy), galthumb / galaddthumb (galcg.rebuild_thumb), shrink
    (cgcrop.shrink: ('ok', small or None, used or None, []))."""
    import picfast
    res = []
    src = None
    if spec.get('af') is not None:
        try:
            src = picfast.decode(spec['af'], spec['rows'])
        except Exception as e:
            return [('err',) + _err(e) + ([],) for _ in spec['outs']]
    for o in spec['outs']:
        try:
            k = o['kind']
            back = None
            if k == 'shrink':
                small, used = picfast.shrink(o['body'], o['limit'])
                res.append(('ok', small, list(used) if used else None, []))
                continue
            if k == 'recrop':
                W, H, rows = src
                body = picfast.rebuild(o['pm'], (W, H, rows[:o['need']]), tuple(o['win']))[0]
            elif k in ('galcopy', 'recut2', 'galadd'):
                W, H, rows = src
                body, tgt, back = picfast.rebuild_copy(o['pm'], (W, H, rows[:o['need']]), tuple(o['win']), o['what'])
                del tgt
            elif k == 'copy':                         # a cached copy: only its thumbnails are made here
                body = o['body']
            else:
                raise ValueError('picture item kind %r' % k)
        except Exception as e:
            res.append(('err',) + _err(e) + ([],))
            continue
        th = []
        for t in o.get('thumbs', ()):
            try:
                th.append(('ok', picfast.rebuild_thumb(t['pm'], body, tuple(t['win']), t['what'], copy_rows=back)))
            except Exception as e:
                th.append(('err',) + _err(e))
        res.append(('ok', body if k != 'copy' else None, th))
        back = None
    return res


def _mod_id(name):
    """sha1 of a module's source file, else of its compiled code (the frozen app) and the Python version."""
    import importlib, importlib.util
    m = importlib.import_module(name)
    h = hashlib.sha1(b'picpool id|')
    src = getattr(m, '__file__', None) or ''
    try:
        if not src.endswith('.py'): raise OSError
        with open(src, 'rb') as f: h.update(b'src|' + f.read())
    except OSError:
        spec = importlib.util.find_spec(name)
        code = spec.loader.get_code(name) if spec and hasattr(spec.loader, 'get_code') else None
        h.update(b'code|' + sys.version.encode() + b'|' + (marshal.dumps(code) if code is not None else os.urandom(16)))
    return h.hexdigest()


def identity():
    import reencache
    return dict(code=reencache._code_id(), gal=reencache._gal_code_id(), fast=_mod_id('picfast'), pool=_mod_id('picpool'),
                version=sys.version, exe=os.path.normcase(os.path.abspath(sys.executable)), proto=PROTO)


def kat_spec():
    """A small synthetic item (a 97 x 61 Opaque1 'AF' picture, a copy with its thumbnail and a crop) for the handshake."""
    import cgcrop, galcg
    W, H = 97, 61
    s = 12345; rows = []
    for y in range(H):
        r = bytearray(3 * W)
        for i in range(3 * W):
            s = (s * 1103515245 + 12345) & 0x7FFFFFFF
            r[i] = (((i // 3) * 5 + y * 3) & 0xFF) if s & 0x300 else (s >> 16) & 0xFF
        rows.append(r)

    def body(w, h, flag, data):
        b = (b'\x45\x00\x00\x00' + struct.pack('<HH', w, h) + bytes(4) + struct.pack('<HH', w, h)
             + struct.pack('<II', flag, galcg.DEPTH) + bytes.fromhex('000800060000') + struct.pack('<I', len(data))
             + bytes(8) + data + bytes(len(data) & 1) + bytes(2))
        if cgcrop.header(b)['size_pos'] != 30: raise ValueError('kat header')
        return b
    af = body(W, H, galcg.COPY_FLAG, cgcrop.encode(W, H, rows))
    pc = body(40, 26, galcg.COPY_FLAG, b'')
    pt = body(21, 12, galcg.THUMB_FLAG, b'')
    return dict(af=af, rows=H, outs=[
        dict(kind='galcopy', pm=pc, win=(40 / 97, 26 / 61, 0.0, 0.0), need=H, what='kat copy',
             thumbs=[dict(pm=pt, win=(0.5, 0.45, 0.25, 0.5), what='kat thumbnail', kind='galthumb')]),
        dict(kind='recrop', pm=pc, win=(0.75, 3.5, 2.25), need=H, what='kat crop')])


# ---------------------------------------------------------------- frames
def _send(f, obj):
    d = marshal.dumps(obj)
    f.write(struct.pack('<Q', len(d)) + d); f.flush()


def _recv(f):
    h = f.read(8)
    if len(h) != 8: raise EOFError('worker closed')
    n = struct.unpack('<Q', h)[0]
    d = f.read(n)
    if len(d) != n: raise EOFError('worker closed mid-frame')
    return marshal.loads(d)


# ---------------------------------------------------------------- worker process
def worker_main():
    """--afr-picworker: serve items until stdin closes. Never returns; never raises past here."""
    try:
        _worker()
    except BaseException:
        pass
    os._exit(3)


def _worker():
    import queue
    rfd = os.dup(0); wfd = os.dup(1)
    nul = os.open(os.devnull, os.O_RDWR)
    os.dup2(nul, 1); os.dup2(nul, 2)
    sys.stdout = sys.stderr = open(os.devnull, 'w')
    if os.name != 'nt':
        try:
            n = os.nice(0)
            if n < 10: os.nice(10 - n)
        except OSError:
            pass
    rf = os.fdopen(rfd, 'rb'); wf = os.fdopen(wfd, 'wb')
    q = queue.Queue()

    def reader():
        try:
            while True:
                q.put(_recv(rf))
        except BaseException:
            pass
        os._exit(0)                     # stdin closed (the build ended or died) or unreadable: stop now, even mid-item
    threading.Thread(target=reader, daemon=True).start()
    while True:
        m = q.get()
        if m[0] == 'hello':
            info = dict(identity(), pid=os.getpid(), frozen=bool(getattr(sys, 'frozen', False)),
                        meipass=getattr(sys, '_MEIPASS', None))
            if os.name == 'nt':
                try:
                    import ctypes
                    k = ctypes.windll.kernel32
                    k.GetCurrentProcess.restype = ctypes.c_void_p; k.GetPriorityClass.argtypes = [ctypes.c_void_p]
                    k.GetConsoleWindow.restype = ctypes.c_void_p
                    info.update(priority=k.GetPriorityClass(k.GetCurrentProcess()), console=int(k.GetConsoleWindow() or 0))
                except Exception:
                    pass
            else:
                try: info.update(nice=os.nice(0))
                except OSError: pass
            try:
                kat = run_item(m[1])
            except Exception as e:
                kat = ('err',) + _err(e)
            _send(wf, ('hello', info, kat))
        elif m[0] == 'item':
            jid, spec = m[1], m[2]
            dig = _digests(spec)
            try:
                out = run_item(spec)
                _send(wf, ('ok', jid, dig, out))
            except Exception as e:
                _send(wf, ('err', jid, dig) + _err(e))
        elif m[0] == 'bye':
            os._exit(0)


def _digests(spec):
    h = [hashlib.sha1(spec['af']).hexdigest() if spec.get('af') is not None else None]
    for o in spec['outs']:
        h.append(hashlib.sha1(o.get('pm') or o.get('body') or b'').hexdigest())
    return h


# ---------------------------------------------------------------- the pool (main process)
def worker_cmd():
    if getattr(sys, 'frozen', False):
        return [sys.executable, FLAG]
    here = os.path.dirname(os.path.abspath(__file__))
    code = 'import sys; sys.path.insert(0, %r); import picpool; picpool.worker_main()' % here
    return [sys.executable] + subprocess._args_from_interpreter_flags() + ['-c', code, FLAG]


STALL_S = 300               # no reply from any worker for this long while the main waits: the pool is stopped


class Prefetch:
    """The build's picture prefetch: planning (keys, cache check: build_all's plan_fn in a background thread), the
    workers, the results. One per build; only the main thread calls take() / close(). While the main thread waits for
    a picture it makes queued items itself (it would only be idle)."""

    def __init__(self, plan_fn, log=None):
        self.plan_fn = plan_fn; self.log = log or (lambda *a: None)
        self.cv = threading.Condition()
        self.state = {}             # key -> 'wait' (planned, not received), 'ok', 'fail', 'taken'
        self.result = {}            # key -> payload (body; shrink: (small, used))
        self.count = {}             # key -> takes left (a key planned twice is computed once)
        self.items = []             # not sent yet, largest first
        self.where = {}             # key -> its item (while queued)
        self.workers = []; self.dead = False; self.planned = False; self.closed = False
        self.n_items = 0; self.n_out = 0; self.n_ok = 0; self.n_thumbs = 0; self.n_workers_done = 0; self.n_main = 0
        self.t_last_result = None
        self.fallback = []          # keys planned but made in the main process
        rc = sys.modules.get('reencache')        # reencache's counters at the start (made_in_main counts from here)
        self.base = (rc._state['new'], rc._state['pool']) if rc is not None else None
        self.t0 = time.time(); self.t_ready = None; self.t_end = None; self.t_last = time.time(); self.t_plan = None
        self.note = ''; self.errors = []
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    # ---- dispatcher thread
    def _run(self):
        """Planning: plan_fn() -> a list of items, or of thunks that each read and key one item (None: nothing to
        make); resolved in order, each item queued as soon as it is known; the workers start at the first one."""
        try:
            raw = list(self.plan_fn())
        except Exception as e:
            with self.cv:
                self.errors.append('planning: %s: %s' % _err(e)); self.planned = True; self.dead = True
                self.t_plan = time.time(); self.cv.notify_all()
            return
        first = {}; started = False
        try:
            for i, x in enumerate(raw):
                try:
                    it = x() if callable(x) else x
                except Exception as e:      # this item only (its pictures are made in the main process); planning goes on
                    with self.cv:
                        if len(self.errors) < 20: self.errors.append('planning: %s: %s' % _err(e))
                    continue
                if it is None: continue
                keep = []
                with self.cv:
                    if self.closed or self.dead: break
                    for k, o in zip(it['keys'], it['spec']['outs']):
                        if k is not None and k in first:           # a key planned twice: computed once
                            self.count[k] += 1
                            f = first[k]
                            for t in o.get('thumbs', ()):
                                if not any(t['pm'] == u['pm'] and t['win'] == u['win'] and t['kind'] == u['kind']
                                           for u in f.get('thumbs', ())):
                                    f.setdefault('thumbs', []).append(t)
                            continue
                        if k is not None: first[k] = o; self.count[k] = 1
                        keep.append((k, o))
                if not keep: continue
                spec = dict(it['spec'], outs=[o for _, o in keep])
                item = dict(spec=spec, keys=[k for k, _ in keep], cost=it['cost'], digests=_digests(spec))
                with self.cv:
                    if self.closed or self.dead: break
                    for k in item['keys']:
                        if k is not None: self.state[k] = 'wait'; self.where[k] = item
                    j = 0
                    while j < len(self.items) and self.items[j]['cost'] >= item['cost']: j += 1
                    self.items.insert(j, item)                    # (largest first)
                    self.n_items += 1; self.n_out += sum(1 for k in item['keys'] if k is not None)
                    self.n_thumbs += sum(len(o.get('thumbs', ())) for o in spec['outs'])
                    if self.t_ready is not None:
                        for w in self.workers:
                            while w['ok'] and len(w['busy']) < 2 and self.items and not self.dead: self._feed(w)
                    self.cv.notify_all()
                if not started:
                    started = True
                    n, self.note = worker_count(len(raw) - i)
                    if n < 1:
                        with self.cv: self._fail_locked('serial (%s)' % self.note)
                        break
                    threading.Thread(target=self._start_safe, args=(n,), daemon=True).start()
        except Exception as e:
            with self.cv: self.errors.append('planning: %s: %s' % _err(e))
        with self.cv:
            if not started and not self.note: self.note = 'nothing to make'
            self.planned = True; self.t_plan = time.time()
            self.cv.notify_all()

    def _start_safe(self, n):
        try:
            self._start(n)
        except Exception as e:
            with self.cv: self._fail_locked('workers not started: %s: %s' % _err(e))

    def _start(self, n):
        kat = kat_spec()
        want = identity()
        want_kat = run_item(kat)
        cmd = worker_cmd()
        env = dict(os.environ); env.pop('PYINSTALLER_RESET_ENVIRONMENT', None)
        flags = (CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0
        ws = []
        try:
            for i in range(n):
                with self.cv:
                    if self.closed: break
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=env, creationflags=flags, close_fds=True)
                ws.append(dict(p=p, busy={}, ok=False, info=None, hello=None))
        finally:
            with self.cv:
                self.workers = list(ws)
                if self.closed:
                    for w in ws: self._kill(w)
        if not ws: return
        for w in ws:
            try: _send(w['p'].stdin, ('hello', kat))
            except OSError: pass

        def hello(w):
            try: w['hello'] = _recv(w['p'].stdout)
            except Exception as e: w['hello'] = ('bad', repr(e))
        ts = [threading.Thread(target=hello, args=(w,), daemon=True) for w in ws]
        for t in ts: t.start()
        t_end = time.time() + HANDSHAKE_S
        for t in ts: t.join(max(0.0, t_end - time.time()))
        bad = []
        for w in ws:
            m = w['hello']
            if not m or m[0] != 'hello': bad.append('no hello (%s)' % (m[1] if m else 'timeout')); continue
            info, kat_got = m[1], m[2]
            diff = [k for k in want if info.get(k) != want[k]]
            if diff: bad.append('identity differs (%s)' % ', '.join(diff)); continue
            if kat_got != want_kat: bad.append('known-answer test differs'); continue
            w['ok'] = True; w['info'] = info
        with self.cv:
            if bad:
                self._fail_locked('handshake: %s' % '; '.join(sorted(set(bad)))); return
            if self.closed or self.dead: return
            self.t_ready = time.time(); self.t_last = time.time()
            for w in ws:
                threading.Thread(target=self._reader, args=(w,), daemon=True).start()
            for w in ws: self._feed(w)
            for w in ws: self._feed(w)                     # two in flight: the next item waits in the pipe
            self.cv.notify_all()

    def _feed(self, w):
        """(lock held) send the next queued item to worker w."""
        if self.dead or self.closed or not self.items: return
        it = self.items.pop(0)
        for k in it['keys']: self.where.pop(k, None)
        jid = id(it)
        w['busy'][jid] = it
        try:
            _send(w['p'].stdin, ('item', jid, it['spec']))
        except OSError as e:
            self._die_locked('a worker stopped taking items (%s)' % e)

    def _reader(self, w):
        p = w['p']
        while True:
            try:
                m = _recv(p.stdout)
            except Exception as e:
                with self.cv:
                    if not self.closed: self._die_locked('worker %d: %s' % (p.pid, e))
                    self.cv.notify_all()
                return
            with self.cv:
                try:
                    self._reply(w, m)
                except Exception as e:
                    self._die_locked('bad reply: %s: %s' % _err(e)); self.cv.notify_all(); return
                self.t_last = self.t_last_result = time.time()
                self._feed(w)
                self.cv.notify_all()

    def _reply(self, w, m):
        """(lock held) one reply of worker w."""
        it = w['busy'].pop(m[1])
        self.n_workers_done += 1
        self._store(it, m)

    def _store(self, it, m):
        """(lock held) store the results of item it from reply m: an output is used only when the reply echoes the
        digests of exactly the inputs it was sent."""
        import reencache
        if m[0] != 'ok' or m[2] != it['digests'] or len(m[3]) != len(it['keys']):
            why = ('item error %s: %s' % (m[3], m[4])) if m[0] == 'err' else 'reply does not match its item'
            for k in it['keys']:
                if k is not None: self._set(k, 'fail', None, why)
            return
        for k, o, r in zip(it['keys'], it['spec']['outs'], m[3]):
            if r[0] != 'ok':
                if k is not None: self._set(k, 'fail', None, 'item error %s: %s' % (r[1], r[2]))
                continue
            if o['kind'] == 'shrink':
                self._set(k, 'ok', (r[1], tuple(r[2]) if r[2] else None)); continue
            body = o['body'] if o['kind'] == 'copy' else r[1]
            if k is not None: self._set(k, 'ok', body)
            ths = r[2]
            if len(ths) != len(o.get('thumbs', ())): continue
            for t, tr in zip(o.get('thumbs', ()), ths):
                tk = reencache.galthumb_key(t['pm'], body, t['win'], t['kind'])
                if tk in self.state and self.state[tk] != 'wait':
                    self.count[tk] = self.count.get(tk, 0) + 1; continue     # (the same thumbnail twice)
                self.count.setdefault(tk, 1)
                if tr[0] == 'ok': self._set(tk, 'ok', tr[1])
                else: self._set(tk, 'fail', None, 'item error %s: %s' % (tr[1], tr[2]))

    def _set(self, k, st, val, why=None):
        if self.state.get(k) in ('ok', 'taken'): return
        self.state[k] = st
        if st == 'ok': self.result[k] = val; self.n_ok += 1
        elif why and len(self.errors) < 20: self.errors.append('%s: %s' % (k[:12], why))

    def _fail_locked(self, why):
        """(lock held) no more pool: every planned picture not received yet is made in the main process."""
        self.dead = True
        if why: self.note = why
        for k, s in self.state.items():
            if s == 'wait': self.state[k] = 'fail'
        self.items = []; self.where.clear()
        for w in self.workers: self._kill(w)
        self.cv.notify_all()

    def _die_locked(self, why):
        if self.dead: return
        self.errors.append('pool stopped: %s (the rest is made in the main process)' % why)
        self._fail_locked(None)

    def _kill(self, w):
        p = w['p']
        try: p.stdin.close()
        except Exception: pass
        try: p.kill()
        except Exception: pass

    # ---- main thread
    def take(self, key):
        """The result for key (body; shrink: (small, used)), or None: not planned, failed or no pool (the caller
        computes it, as a serial build does)."""
        if self.closed: return None
        last = 0.0
        with self.cv:
            while not self.planned:
                self.cv.wait(0.5)
            while True:
                st = self.state.get(key)
                if st is None or st == 'taken': return None
                if st == 'ok':
                    v = self.result[key]
                    self.count[key] = self.count.get(key, 1) - 1
                    if self.count[key] <= 0: self.result.pop(key, None); self.state[key] = 'taken'
                    return v
                if st == 'fail':
                    self.fallback.append(key); return None
                # 'wait': while the workers run, this process (idle until it gets the picture) makes a queued item itself:
                # the one it waits for if it is still queued, else the smallest one left (its results are stored as a
                # worker's are; the item is taken off the queue, so no worker makes it too)
                it = None
                if self.t_ready is not None and not self.dead and self.items:
                    it = self.where.get(key) or self.items[-1]
                    self.items.remove(it)
                    for k in it['keys']: self.where.pop(k, None)
                if it is not None:
                    self.cv.release()
                    try:
                        try:
                            m = ('ok', None, it['digests'], run_item(it['spec']))
                        except Exception as e:
                            m = ('err', None, it['digests']) + _err(e)
                    finally:
                        self.cv.acquire()
                    self._store(it, m); self.n_main += 1; self.t_last = self.t_last_result = time.time()
                    self.cv.notify_all()
                    continue
                now = time.time()
                if now - self.t_last > STALL_S:
                    self._die_locked('no reply for %d s' % STALL_S); continue
                if now - last >= 1.0:
                    last = now
                    try: print('pictures: %d of %d ready' % (self.n_ok, self.n_out + self.n_thumbs), flush=True)
                    except Exception: pass
                self.cv.wait(0.5)

    def close(self):
        """Stop the workers (results not taken are dropped). Returns the summary line."""
        with self.cv:
            if self.closed: return self.summary()
            self.closed = True; self.t_end = time.time()
            for w in self.workers:
                try: _send(w['p'].stdin, ('bye',))
                except Exception: pass
                try: w['p'].stdin.close()
                except Exception: pass
            self.cv.notify_all()
        for w in self.workers:
            try: w['p'].wait(5)
            except Exception:
                try: w['p'].kill()
                except Exception: pass
        return self.summary()

    def made_in_main(self):
        """Pictures the build made in its own process instead of taking them from here, since this prefetch started:
        reencache's new entries less those it took from here (planned or not, thumbnails included); without reencache
        the planned keys that failed."""
        rc = sys.modules.get('reencache')
        if rc is None or self.base is None: return len(self.fallback)
        return (rc._state['new'] - self.base[0]) - (rc._state['pool'] - self.base[1])

    def summary(self):
        t = (self.t_end or time.time()) - self.t0
        at = lambda x: ('%.1f' % (x - self.t0)) if x else '-'
        return ('parallel pictures: %d workers (%s), %d items, %d pictures planned, %d made ahead (%d items by workers, '
                '%d by the build process while it waited), %.0fs (planned at %s s, workers ready at %s s, last result at '
                '%s s); %d made in the main process instead%s' % (
                    sum(1 for w in self.workers if w['ok']), self.note, self.n_items, self.n_out + self.n_thumbs,
                    self.n_ok, self.n_workers_done, self.n_main, t, at(self.t_plan), at(self.t_ready),
                    at(self.t_last_result), self.made_in_main(), (' (%s)' % '; '.join(self.errors[:3])) if self.errors else ''))


_active = [None]


def prefetch(plan_fn, log=None):
    """Start the build's prefetch (plan_fn() -> items, run in a background thread); a previous one is closed first.
    Nothing happens with AFR_JOBS 0 / 1 (serial: today's path)."""
    close(log)
    if worker_count(1)[0] < 1: return None
    _active[0] = Prefetch(plan_fn, log)
    return _active[0]


def take(key):
    p = _active[0]
    return p.take(key) if p is not None else None


def close(log=None):
    p = _active[0]
    if p is None: return None
    _active[0] = None
    line = p.close()
    if log: log(line)
    return line
