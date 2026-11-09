"""Disk cache for the builder's picture re-encodes (cgcrop.shrink of oversized billboard pictures, the CG re-crops).

They are most of a build's time (pure-Python Opaque1 decode / encode: about 6-11 s per billboard picture, 3-4 s per
re-crop) and their result depends only on their inputs. An entry is keyed by the sha1 of: the kind ('shrink' /
'recrop'), its parameters, the sha1 of every input body, and the coder's identity (the sha1 of cgcrop.py's source;
where no source file exists, e.g. inside the frozen app, the sha1 of cgcrop's compiled code and the Python version).
So a hit returns exactly the bytes cgcrop would compute now, and the patch stays byte-identical with or without the
cache (checked: no cache, cold cache and warm cache builds give the same sha1).

Entries are written atomically (temp file + os.replace) and checked on every read (magic, format, payload sha1); a bad
or unreadable entry is computed again and rewritten. finish() (end of a build) removes entries this build did not use
that were last used more than PRUNE_AFTER seconds ago (a build running in parallel keeps its entries).

Location: env AFR_CACHE (a folder; '' or 'off' = no cache). Unset: <AFR_OUT or lab-tools/out>/cache/reencode for the
lab; the app sets <settings folder>/cache. A frozen program without AFR_CACHE uses no cache."""
import os, sys, json, time, struct, hashlib

FORMAT = 1
MAGIC = b'AFRC'
PRUNE_AFTER = 3600                  # seconds: entries unused by this build and older than this are removed by finish()
_state = dict(hits=0, new=0, bad=0, used=set(), dir=None, code=None)


def cache_dir():
    """The cache folder, or None for no cache (decided once per process)."""
    if _state['dir'] is None:
        v = os.environ.get('AFR_CACHE')
        if v is None:
            if getattr(sys, 'frozen', False):
                d = ''
            else:
                out = os.environ.get('AFR_OUT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out')
                d = os.path.join(out, 'cache', 'reencode')
        else:
            d = '' if v.strip().lower() in ('', 'off', '0', 'none') else v
        _state['dir'] = os.path.abspath(d) if d else ''
    return _state['dir'] or None


def _code_id():
    """Identity of the coder whose output is cached: sha1 of cgcrop.py's source, else of its compiled code."""
    if _state['code'] is None:
        import cgcrop
        h = hashlib.sha1(b'reencache %d|' % FORMAT)
        src = getattr(cgcrop, '__file__', None) or ''
        try:
            if not src.endswith('.py'): raise OSError('no source')
            with open(src, 'rb') as f: h.update(b'src|' + f.read())
        except OSError:
            import marshal, types
            h.update(b'code|' + sys.version.encode())
            for name in sorted(vars(cgcrop)):
                v = getattr(cgcrop, name)
                if isinstance(v, types.FunctionType) and v.__module__ == cgcrop.__name__:
                    h.update(name.encode() + b'|' + marshal.dumps(v.__code__) + repr(v.__defaults__).encode())
        _state['code'] = h.hexdigest()
    return _state['code']


def key_of(kind, params, inputs):
    h = hashlib.sha1()
    h.update(('%s|%d|%s|%s|' % (kind, FORMAT, json.dumps(params, sort_keys=True), _code_id())).encode())
    for b in inputs:
        h.update(hashlib.sha1(b).digest())
    return h.hexdigest()


def _path(key):
    return os.path.join(cache_dir(), key[:2], key + '.bin')


def get(key):
    """(meta dict, payload bytes) of a valid entry, else None (missing, unreadable or damaged: computed again)."""
    if not cache_dir(): return None
    p = _path(key)
    try:
        with open(p, 'rb') as f: raw = f.read()
    except OSError:
        return None
    try:
        if raw[:4] != MAGIC or struct.unpack_from('<I', raw, 4)[0] != FORMAT: raise ValueError('header')
        digest = raw[8:28]
        n = struct.unpack_from('<I', raw, 28)[0]
        meta = json.loads(raw[32:32 + n].decode('utf-8'))
        data = raw[32 + n:]
        if hashlib.sha1(data).digest() != digest or meta.get('key') != key: raise ValueError('checksum')
    except (ValueError, struct.error, UnicodeDecodeError):
        _state['bad'] += 1
        return None
    try: os.utime(p)                                 # last use (finish() keeps recently used entries)
    except OSError: pass
    return meta, data


def put(key, meta, data):
    """Store an entry (atomic); a failure to write only means no cache for it."""
    if not cache_dir(): return
    p = _path(key)
    meta = dict(meta, key=key)
    m = json.dumps(meta, sort_keys=True).encode('utf-8')
    blob = MAGIC + struct.pack('<I', FORMAT) + hashlib.sha1(data).digest() + struct.pack('<I', len(m)) + m + data
    tmp = '%s.%d.tmp' % (p, os.getpid())
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(tmp, 'wb') as f:
            f.write(blob); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, p)
    except OSError:
        try: os.remove(tmp)
        except OSError: pass


def shrink(body, limit):
    """cgcrop.shrink(body, limit), cached. Same result: (body, (tol, rtol)) or (None, None)."""
    import cgcrop
    body = bytes(body)
    key = key_of('shrink', dict(limit=limit), [body])
    _state['used'].add(key)
    hit = get(key)
    if hit is not None:
        meta, data = hit
        if meta.get('fits') is False: _state['hits'] += 1; return None, None
        if meta.get('fits') is True and isinstance(meta.get('used'), list):
            _state['hits'] += 1
            return data, tuple(meta['used'])
    small, used = cgcrop.shrink(body, limit)
    put(key, dict(kind='shrink', fits=small is not None, used=list(used) if used else None), small or b'')
    _state['new'] += 1
    return small, used


def recrop(pm_body, af_body, crop, source):
    """cgcrop.rebuild(pm_body, source(), crop)[0], cached; source() decodes the AF picture (only on a miss)."""
    import cgcrop
    pm_body, af_body = bytes(pm_body), bytes(af_body)
    key = key_of('recrop', dict(crop=[float(c) for c in crop]), [pm_body, af_body])
    _state['used'].add(key)
    hit = get(key)
    if hit is not None and hit[0].get('kind') == 'recrop':
        _state['hits'] += 1
        return hit[1]
    new, _ = cgcrop.rebuild(pm_body, source(), crop)
    put(key, dict(kind='recrop'), new)
    _state['new'] += 1
    return new


def finish(log=None):
    """End of a build: remove entries this build did not use and nobody used for PRUNE_AFTER seconds. Returns a
    summary line (also passed to log)."""
    removed = 0
    d = cache_dir()
    if d and os.path.isdir(d):
        now = time.time()
        for sub in os.listdir(d):
            sd = os.path.join(d, sub)
            if not os.path.isdir(sd): continue
            for f in os.listdir(sd):
                p = os.path.join(sd, f)
                k = f[:-4] if f.endswith('.bin') else None
                try:
                    if k in _state['used']: continue
                    if now - os.path.getmtime(p) > (PRUNE_AFTER if k else 600):    # leftover .tmp: 10 minutes
                        os.remove(p); removed += 1
                except OSError:
                    pass
            try: os.rmdir(sd)
            except OSError: pass
    line = 're-encode cache (%s): %d reused, %d made, %d damaged entries made again, %d unused removed' % (
        d or 'off', _state['hits'], _state['new'], _state['bad'], removed)
    if log: log(line)
    return line
