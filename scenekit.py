"""Test a scene (shipped with Altered Fable Restore): the kit made during Build & install, and putting one scene test into
the installed patch file and taking it out again.

A scene test is the installed patch (photonmelodies11.rio.ruo1) plus 1-3 objects added at its end: the Altered Fable
opening 00ce1abaf2 with the scene's calls inserted before its instruction 16 (each call returns and falls through to
the next; the last one lands on instruction 16, so the opening carries on afterwards), for a route-guarded Marimo part
its copy without the route guard, and any picture that copy needs. These are the objects the developer scene tester
proved in game (same keys, same bytes); only the file layout differs.

How Photonmelodies reads the patch (Muv-Luv_PM.exe FUN_005de150): the last 4 bytes are the entry count N, the 12*N bytes
right before them the key -> (position, size) table; nothing else is read except the objects the table points to. So a
test is APPENDED: new objects, then a full new table (the old entries, then the new ones) and the new count. The old
table stays behind as unused bytes, and cutting the file back to its old size gives back the original byte for byte.
No byte of the player's file is ever rewritten, it needs less than 1 MB of free space and takes milliseconds.

The kit (capture_hook, run by app.do_build before build_all): at build_all's write_ruo the build's own state is used to
make, for every item of PUBLIC, the patched opening with and without the lead-in parts (build_all's patch_pm, the
instruction ids the developer tester uses), each checked with walk_direct; route-guarded items also get their guard-free
copy (build_all's debug-build conversion) and its imports. The build state is put back after each, then the real
write_ruo writes exactly the objects it was given. The kit goes into <kit dir>/ : kit.json, open/*.z (zlib heaps),
gf/*.bin. It records the patch file it belongs to (size, entry count, sha1 of the table): a test is only ever put into
that very file.

Install (install_tail): checks the file is the kit's (size, table), appends the tail, flushes it to disk, reads it back
(old entries unchanged, new objects byte-equal, sha1 of the tail, walk_direct on the opening as read from the file, every
called script ends in CVmRet). Undo (undo_tail): cut back to the old size when the old table and count are still in
place right before it (the planned tail or a half-written one); any other file is left alone.
Nothing here reads or shows story text."""
import os, sys, json, struct, hashlib, zlib, time

FORMAT = 1
ENTRY, AT = '00ce1abaf2', 16             # the Altered Fable opening; the calls go in before instruction 16
SHIFT = 2                                # ruo table positions: K + (file position >> 2)
M32 = 0xFFFFFFFF
KIT_JSON = 'kit.json'
# Only scenes the owner has played through a test (developer tester) are offered. group, item, label (the dev tester's
# names, lab-tools/scripts/scenetest/catalog.NAMES)
G18, GMARIMO = '18+ scenes', 'Marimo-chan route'
PUBLIC = ((G18, 'yuuhi_a', 'Yuuhi — first'), (G18, 'yuuhi_b', 'Yuuhi — second'),
          (G18, 'kashiwagi', 'Haruko Kashiwagi'), (G18, 'sumika', 'Sumika Kagami'),
          (G18, 'meiya', 'Meiya Mitsurugi'), (G18, 'ayamine', 'Kei Ayamine'), (G18, 'chizuru', 'Myun × Chizuru'),
          (G18, 'miki', 'Miki Tamase'), (G18, 'mikoto', 'Mikoto Yoroi'), (G18, 'kasumi_h', 'Kasumi Yashiro'),
          (GMARIMO, 'marimo_chapter', 'Marimo-chan chapter'))
GROUPS = (G18, GMARIMO)
LABEL = dict((n, l) for _, n, l in PUBLIC)
# Lead-in rule (copy of the developer tester's scenemenu.leadins; a lab test checks both give the same parts): walking
# back from the scene's first AF instruction, an x_ part belongs to the lead-in when it comes from the same AF script,
# is inserted into the same PM script before the scene's site and ends within LEADIN_GAP AF instructions of the next
# part already taken. Only the 18+ scenes have lead-ins.
LEADIN_GAP = 150
LEADIN_OVERRIDE = {}
# Marimo parts that only set route flags (catalog.ROUTE_FLAG_PARTS)
ROUTE_FLAG_PARTS = ('marimo_rung1', 'marimo_rung2', 'marimo_plus1', 'marimo_ending')


class KitError(RuntimeError):
    """A kit cannot be made or used (shown to the player as it is)."""


def sha1(b):
    return hashlib.sha1(b).hexdigest()


# ---------------------------------------------------------------- parts (blocks.py data)
def part_span(BL, name):
    """AF heap, AF range [lo, hi) (hi None = to the heap end), PM heap, PM instruction it is inserted before."""
    if name in BL.SITES:
        import scenes
        b, end, pn, pb = BL.SITES[name]
        return dict(af=scenes.RAW[name][0], lo=b + 1, hi=end, pm=pn, ins=pb + 1)
    af, lo, hi, pn, ins, land = BL.part(name)
    return dict(af=af, lo=lo, hi=hi, pm=pn, ins=ins)


def leadins(BL, scene, gap=LEADIN_GAP):
    """x_ lead-in parts of `scene` in play order (see LEADIN_GAP)."""
    if scene in LEADIN_OVERRIDE:
        return list(LEADIN_OVERRIDE[scene])
    s = part_span(BL, scene)
    xs = [(x, part_span(BL, x)) for x in BL.EXTRA_PARTS if x.startswith('x_')]
    xs.sort(key=lambda t: -t[1]['lo'])
    out, edge = [], s['lo']
    for x, p in xs:
        if p['af'] != s['af'] or p['pm'] != s['pm'] or p['hi'] is None or p['hi'] > edge or p['ins'] >= s['ins']:
            continue
        if edge - p['hi'] > gap:
            break
        out.append(x); edge = p['lo']
    return out[::-1]


def called_first(man):
    """{part: scene}: a scene of the build that PM's script calls by an inserted call of its own right before the
    part's call (the Kashiwagi conversation's start before x_3eab17_4957; build manifest 'kashi' 'pre' with 'pm_call').
    A test with the lead-in calls it right before that part, as the game does."""
    out = {}
    for n, m in man.items():
        k = m.get('kashi') if isinstance(m, dict) else None
        pre = k.get('pre') if isinstance(k, dict) else None
        if isinstance(pre, dict) and pre.get('pm_call') and pre.get('name'): out[n] = pre['name']
    return out


def called_scenes(ns):
    """{scene: (key, object bytes, lines)} of the scenes the build's parts or PM call that are not parts (yuuhi_a's
    route-A continuation, the Kashiwagi conversation's start)."""
    objs = dict(list(ns.get('ycont_objs') or []) + list(ns.get('kashi_scene_objs') or []))
    out = {}
    for n, m in ns['manifest'].items():
        k = m.get('kashi') if isinstance(m.get('kashi'), dict) else {}
        for sub in (m.get('ycont'), k.get('pre')):
            if isinstance(sub, dict) and int(sub['scene_key'], 16) in objs:
                key = int(sub['scene_key'], 16)
                out[sub['name']] = (key, objs[key], int((sub.get('stats') or {}).get('CVmMsg') or 0))
    return out


def part_lines(man, called, name):
    """Lines played with a part: its own (build manifest stats.CVmMsg) plus those of the scene that comes with it,
    whether the part calls it (yuuhi_a's route-A continuation after its last line, manifest 'ycont') or PM calls it
    right before the part (the Kashiwagi conversation's start before x_3eab17_4957, 'kashi' 'pre'). The developer
    tester's catalog counts the same way (catalog.part_lines)."""
    m = man[name]
    k = m.get('kashi') if isinstance(m.get('kashi'), dict) else {}
    return int((m.get('stats') or {}).get('CVmMsg') or 0) + sum(
        called[s['name']][2] for s in (m.get('ycont'), k.get('pre')) if isinstance(s, dict) and s.get('name') in called)


def route_guarded(BL, name, af_heap):
    """build_all's debug-build rule: a Marimo part (not a route-flag piece) whose first kept instruction is a CVmFlagOp
    (its route guard) is played without it."""
    if name not in BL.MARIMO_PARTS or name in ROUTE_FLAG_PARTS: return False
    bl = BL.block(name) if name in BL.SITES else BL.range_block(name)
    A = af_heap(bl['af'])
    return bool(bl['keep']) and A.instrs[bl['keep'][0]][2] == 'CVmFlagOp'


# ---------------------------------------------------------------- build_all's heap helpers (copies; a lab test and
# AFRestore --selftest check they are the same code as the bundled builder's)
from rsaparse import Heap
from builder import BuildError


class CountHeap(Heap):
    """Parser returning in-memory size inputs for CVmCall and CVmSound."""
    def vm_call(self):
        self.u32(); self.u32(); self.read_class_list(); n = self.u16()
        for _ in range(n):
            d = self.u32()
            if d == 4:
                w = self.u16()
                if w == 0x1e57: self.read_class()
                elif w == 0x369e: self.read_raw_class()
                elif w in (0x2d6b, 0x2f1a): self.u16(); k = self.u16(); self.skip(k)
                else: raise BuildError('call w=%x' % w)
                self.skip(4)
            else:
                k = d & 3
                if k == 0: self.read_class_list()
                elif k == 1: self.string()
                elif k == 3:
                    t1 = self.u32()
                    if t1 == 0x137: self.u32()
        k = 0
        if self.cur_schema > 0x12:
            k = self.u8()
            if k == 0xff: k = self.u16()
            for _ in range(k):
                w = self.u16()
                if w & 0x8000: self.string()
                else: self.read_class_list()
        return n, k

    def vm_sound(self):
        self.u32(); self.u32(); self.read_class_list(); typ = self.u8()
        f = self.u8(); self.u16(); self.u16(); self.u16()
        if self.cur_schema >= 0x13 and typ in (2, 4):
            self.read_class_list()
        extra = 0
        if f & 4:
            if f & 8: self.read_class_list(); extra = 4
            else:
                self.skip(8); extra = 8
                if not f & 0x10: self.skip(6); extra = 16
        return extra


def base_pos(d, s):
    tag = struct.unpack_from('<H', d, s)[0]; p = s + 2
    if tag == 0xffff: p += 2; n = d[p]; p += 1 + n
    return p


FIXED = {'CVmRet': 12, 'CVmSync': 24, 'CVmGenericMsg': 28, 'CVmJump': 16, 'CVmLabel': 16, 'CVmFlagOp': 32}


def mem_size(h, i):
    name = h.instrs[i][2]
    if name == 'CVmCall':
        na, ne = h.instrs[i][3]; return 20 + 12 * na + 8 * ne
    if name == 'CVmMsg3':
        p = base_pos(h.d, h.instrs[i][0]); n1, n2 = h.d[p + 12], h.d[p + 13]
        return (20 + 12 * n1 + 10 * n2 + 3) & ~3
    if name == 'CVmSound':
        return 28 + h.instrs[i][3]
    return FIXED[name]


COPIED = ('CountHeap', 'base_pos', 'mem_size')          # same code as build_all's (checked)


def same_code(a, b):
    """True when two code objects are the same code (instructions, names, constants; line numbers ignored)."""
    import types
    if a.co_code != b.co_code or a.co_names != b.co_names or a.co_varnames != b.co_varnames or \
            a.co_freevars != b.co_freevars or a.co_cellvars != b.co_cellvars or len(a.co_consts) != len(b.co_consts):
        return False
    for x, y in zip(a.co_consts, b.co_consts):
        if isinstance(x, types.CodeType) or isinstance(y, types.CodeType):
            if not (isinstance(x, types.CodeType) and isinstance(y, types.CodeType) and same_code(x, y)): return False
        elif type(x) is not type(y) or x != y:
            return False
    return True


def builder_code_matches(module_code):
    """None when the copies above are the same code as the definitions in build_all's compiled module code (the frozen
    app's check), else what differs."""
    import types
    mine = {'base_pos': base_pos.__code__, 'mem_size': mem_size.__code__}
    theirs = {}
    for c in module_code.co_consts:
        if isinstance(c, types.CodeType) and c.co_name in COPIED: theirs.setdefault(c.co_name, []).append(c)
    bad = []
    for name in ('base_pos', 'mem_size'):
        if len(theirs.get(name, ())) != 1 or not same_code(mine[name], theirs[name][0]): bad.append(name)
    # the class body: compiled the same way here from this module's own code
    here = [c for c in _own_code().co_consts if isinstance(c, types.CodeType) and c.co_name == 'CountHeap']
    if len(theirs.get('CountHeap', ())) != 1 or len(here) != 1 or not same_class_body(here[0], theirs['CountHeap'][0]):
        bad.append('CountHeap')
    return ('scenekit copies differ from build_all: %s' % ', '.join(bad)) if bad else None


def same_class_body(a, b):
    """True when two class bodies define the same names, the same methods (same_code) and the same other constants.
    The body's own bytecode is not compared: from Python 3.13 on it stores the class's line (__firstlineno__), as a
    constant or, for a small line number on 3.14, inside the instruction, so equal classes on different lines differ
    there (both copies here are checked on 3.12, the exes' and CI's Python, and on newer ones from source)."""
    import types

    def parts(c):
        meths = dict((x.co_name, x) for x in c.co_consts if isinstance(x, types.CodeType))
        other = [x for x in c.co_consts if not isinstance(x, types.CodeType) and
                 not (type(x) is int and x == c.co_firstlineno)]
        return meths, other
    (ma, oa), (mb, ob) = parts(a), parts(b)
    if a.co_names != b.co_names or sorted(ma) != sorted(mb) or len(oa) != len(ob): return False
    if any(type(x) is not type(y) or x != y for x, y in zip(oa, ob)): return False
    return all(same_code(ma[k], mb[k]) for k in ma)


def _own_code():
    spec = __spec__
    if spec is None or spec.loader is None or not hasattr(spec.loader, 'get_code'): raise KitError('no module code')
    return spec.loader.get_code(spec.name)


# ---------------------------------------------------------------- ruo table
def enc_size(x):
    """objio.enc_size (the ruo table's encoded size)."""
    return ((((x >> 19) & 0xfff) + (x & 0xfff) | (x << 13)) + 0xE7B5D9F8) & M32


def dec_size(v):
    a = (v - 0xE7B5D9F8) & M32; c = a >> 13; d = c & 0xFFF; a2 = (a - d) & M32
    return ((a2 << 19) & M32) | c


def key_dec(K, key):
    """The decoded object offset a CRsa reference with this ruo key resolves to (what ins_res reports for it)."""
    return 3 + 2 * ((key - K) & M32)


def entry_key(K):
    return (K + (int(ENTRY, 16) - 2) // 4) & M32


def read_table(path, size=None):
    """(count N, table bytes, table start, file size) of a .ruo file: table + u32 count at the very end."""
    with open(path, 'rb') as f:
        f.seek(0, 2); end = f.tell() if size is None else size
        if end < 4: raise KitError('%s is too small to be a patch file' % os.path.basename(path))
        f.seek(end - 4); n = struct.unpack('<I', f.read(4))[0]
        start = end - 4 - 12 * n
        if n > 0x1FFFF or start < 0: raise KitError('%s has no patch table at its end' % os.path.basename(path))
        f.seek(start); t = f.read(12 * n)
    if len(t) != 12 * n: raise KitError('%s: short read of its table' % os.path.basename(path))
    return n, t, start, end


def entries(table, K):
    """[(key, file position, raw size)] of table bytes."""
    out = []
    for i in range(len(table) // 12):
        key, loc, es = struct.unpack_from('<III', table, 12 * i)
        out.append((key, ((loc - K) & M32) << SHIFT, dec_size(es)))
    return out


def fingerprint(path):
    """app.fingerprint: [size, sha1 of the first and the last MiB]."""
    s = os.path.getsize(path); h = hashlib.sha1()
    with open(path, 'rb') as f:
        h.update(f.read(1 << 20)); f.seek(max(0, s - (1 << 20))); h.update(f.read(1 << 20))
    return [s, h.hexdigest()]


def patch_id(path):
    """What identifies a patch file for a kit: size, entry count, sha1 of the table + count (the file's last bytes)."""
    n, t, start, size = read_table(path)
    return dict(size=size, count=n, table_sha1=sha1(t + struct.pack('<I', n)))


# ---------------------------------------------------------------- walk_direct (copy of scenemenu.walk_direct)
def walk_direct(old, new, at):
    """Follow the patched opening `new` (heap bytes) against the original `old`, with the VM rule 'next pointer; a
    FlagOp also branches to its target': preds = original instructions whose pointer led to `at` (now: to the first
    call), calls = what the inserted calls call in order (decoded CRsa offsets, compare with key_dec), lands = where the
    heap goes after the last call (the original instruction `at`, new index). Every original instruction must be
    unchanged with each pointer remapped to the same original target. Returns (flow, problems)."""
    O = CountHeap(bytes(old), 2); O.parse()
    G = CountHeap(bytes(new), 2); G.parse()
    n = G.count - O.count
    flow = dict(preds=[], calls=[], lands=None, inserted=n)
    if n < 1: return flow, ['no inserted calls']
    if not 0 < at < O.count: return flow, ['insertion point %d outside the heap (1..%d)' % (at, O.count - 1)]

    def ptrs(h, j):
        v = [struct.unpack_from('<I', h.d, base_pos(h.d, h.instrs[j][0]))[0]]
        if h.instrs[j][2] == 'CVmFlagOp': v.append(struct.unpack_from('<I', h.d, h.instrs[j][1] - 4)[0])
        return v
    problems = []
    oo = [0] + [ptrs(O, j)[0] for j in range(O.count - 1)]
    if any(b <= a for a, b in zip(oo, oo[1:])) or oo[-1] >= O.size:
        return flow, ['original next chain is not linear']
    osz = [b - a for a, b in zip(oo, oo[1:])] + [O.size - oo[-1]]
    for j in range(O.count):
        try:
            if mem_size(O, j) != osz[j]: problems.append('original instruction %d: size %d, chain %d' % (
                j, mem_size(O, j), osz[j]))
        except KeyError:
            pass
    new_of = lambda j: j if j < at else j + n
    nsz = [osz[j] for j in range(at)] + [mem_size(G, at + k) if G.instrs[at + k][2] == 'CVmCall' else 0
                                         for k in range(n)] + [osz[j] for j in range(at, O.count)]
    no, o = [], 0
    for s in nsz:
        no.append(o); o += s
    if sum(nsz) != G.size:
        problems.append('memory size: patched heap %d, original %d + calls %d' % (G.size, O.size, sum(nsz) - O.size))
    at_o = {x: j for j, x in enumerate(oo)}
    norm = lambda res: [('pad',) if x and x[0] == 'pad' else x for x in (res or [])]
    for j in range(O.count):
        t = new_of(j)
        if O.instrs[j][2] != G.instrs[t][2] or norm(O.ins_res[j]) != norm(G.ins_res[t]):
            problems.append('original instruction %d changed' % j); continue
        for vo, vn in zip(ptrs(O, j), ptrs(G, t)):
            if vo == 0xFFFFFFFF or vo not in at_o:
                if vn != vo: problems.append('instruction %d: pointer %x became %x' % (j, vo, vn))
                continue
            i = at_o[vo]
            if i == at: flow['preds'].append(j)
            want = no[at] if i == at else no[new_of(i)]
            if vn != want: problems.append('instruction %d points to %x, expected %x' % (j, vn, want))
    for k in range(n):
        t = at + k
        if G.instrs[t][2] != 'CVmCall':
            problems.append('inserted instruction %d is %s' % (k, G.instrs[t][2])); break
        r = [x for x in G.ins_res[t] if x and isinstance(x[0], tuple) and x[0][0] == 'CRsa']
        flow['calls'].append(r[0][1] if len(r) == 1 else None)
        if ptrs(G, t)[0] != no[t + 1]:
            problems.append('call %d continues at %x, expected %x' % (k, ptrs(G, t)[0], no[t + 1]))
    if not flow['preds']: problems.append('nothing leads to instruction %d: the calls are unreachable' % at)
    flow['lands'] = new_of(at)
    return flow, problems


def last_kind(obj):
    """Last instruction kind of a CRsa object (2-byte header + 9-byte CRsa header + encrypted heap)."""
    from crsa import decrypt_block
    h = CountHeap(decrypt_block(obj[11:])[0], 2); h.parse()
    return h.instrs[h.count - 1][2]


def check_opening(old, new, at, calls_dec):
    """Problems of a patched opening (empty = it calls exactly calls_dec in order, then carries on at `at`)."""
    flow, problems = walk_direct(old, new, at)
    problems = list(problems)
    if flow['calls'] != list(calls_dec):
        problems.append('calls %s, planned %s' % (['%x' % c for c in flow['calls'] if c is not None],
                                                 ['%x' % c for c in calls_dec]))
    if flow['lands'] != at + len(calls_dec): problems.append('lands on %s, not %d' % (flow['lands'], at + len(calls_dec)))
    return flow, problems


# ---------------------------------------------------------------- build state (fastplay._counters / _restore copies)
REPORT_STATE = ('_keep_report', '_near_log', '_pic_info', '_cam_info', 'nested_log', 'crmt_swaps', 'crimp_done',
                'bb_shrunk')       # build_all's report tables: put back too, so its log is the same as without a kit


def _counters(ns):
    snap = {}
    for k, v in ns.items():
        if isinstance(v, list) and 0 < len(v) <= 8 and all(type(x) is int for x in v): snap[k] = ('list', list(v))
        elif k in ('new_objs', 'new_objs_lead', '_shake_wait_done') and isinstance(v, dict): snap[k] = ('dict', dict(v))
    for k in REPORT_STATE:
        v = ns.get(k)
        if isinstance(v, dict) and k not in snap: snap[k] = ('dict', dict(v))
        elif isinstance(v, list) and k not in snap: snap[k] = ('list', list(v))
    return snap


def _restore(ns, snap):
    for k, (kind, v) in snap.items():
        cur = ns[k]
        if kind == 'list': cur[:] = v
        else: cur.clear(); cur.update(v)


def _same_state(ns, snap):
    for k, (kind, v) in snap.items():
        cur = ns[k]
        if (list(cur) if kind == 'list' else dict(cur)) != v: return False
    return True


def _guard_free_copy(ns, BL, n):
    """(heap, object bytes) of part n converted without its leading route-guard FlagOp (build_menu.guard_free_copy:
    build_all's debug-build conversion)."""
    bl = BL.block(n) if n in BL.SITES else BL.range_block(n)
    if not (bl['keep'] and ns['af_heap'](bl['af']).instrs[bl['keep'][0]][2] == 'CVmFlagOp'):
        raise KitError('%s: no leading route guard to remove' % n)
    bl = dict(bl, keep=bl['keep'][1:])
    if n in ns.get('LEAD_IN', ()):
        bl = dict(bl, lead=ns['lead_in'](ns['af_heap'](bl['af']), dict(bl, name=n)))
    P = ns['pm_heaps'][bl['pm']]
    pad = P.ev[[e[0] for e in P.ev].index('pad')][3]
    heap, stats, msize = ns['convert_block'](bl, pad)
    return heap, bytes([0x00, 0x05]) + ns['CRSA_HDR9'] + ns['encrypt_block'](heap)


# ---------------------------------------------------------------- the kit (in the build process)
def capture_hook(kit_dir, log=None):
    """Replace ruowrite.write_ruo for the coming build_all run (app.do_build, before runpy). At write time the kit is
    made from build_all's state into kit_dir (removed first); then the real write_ruo writes exactly the objects it was
    given. A kit that cannot be made only leaves kit_dir/failed.txt: the patch is written all the same."""
    import ruowrite
    real = ruowrite.write_ruo
    say = log or (lambda *a: print(*a, flush=True))

    def hook(path, objs):
        ruowrite.write_ruo = real                    # once
        ns = sys._getframe(1).f_globals              # build_all's module namespace (its main section calls us)
        release = list(objs)
        _rmtree(kit_dir)
        kit, files, err = None, {}, None
        t0 = time.time()
        try:
            kit, files = make_kit(ns, release)
        except Exception as e:
            err = '%s: %s' % (e.__class__.__name__, e)
        res = real(path, release)
        try:
            if err is None:
                write_kit(kit_dir, kit, files, path)
                say('scene test kit: %d scenes, %d openings, %.1f s -> %s' % (
                    len(kit['items']), sum(len(it['openings']) for it in kit['items'].values()), time.time() - t0,
                    kit_dir))
        except Exception as e:
            err = 'writing the kit: %s: %s' % (e.__class__.__name__, e)
        if err is not None:
            _rmtree(kit_dir)
            try:
                os.makedirs(kit_dir, exist_ok=True)
                with open(os.path.join(kit_dir, 'failed.txt'), 'w', encoding='utf-8') as f: f.write(err + '\n')
            except OSError:
                pass
            say('scene test kit not made: %s' % err)
        return res

    ruowrite.write_ruo = hook
    return hook


def _rmtree(d):
    import shutil
    if os.path.isdir(d): shutil.rmtree(d, ignore_errors=True)


def make_kit(ns, release):
    """(kit dict, {relative file: bytes}) from build_all's namespace at write time. The namespace is put back exactly
    (counters, import tables, report tables) before this returns, also on an error."""
    from crsa import decrypt_block
    BL, K, es = ns['BL'], ns['K'], ns['enc_size']
    man, sobj = ns['manifest'], dict(ns['scene_objs'])
    rkeys = set(k for k, _ in release)
    if len(rkeys) != len(release): raise KitError('release objects: duplicate keys')
    if ENTRY in ns['by_heap']: raise KitError('the opening %s is a release site script' % ENTRY)
    enc_of = {n: (int(m['scene_key'], 16), es(len(sobj[int(m['scene_key'], 16)]))) for n, m in man.items()}
    called = called_scenes(ns); cf = called_first(man)
    sobj.update((k, o) for k, o, _ in called.values()); enc_of.update((n, (k, es(len(o)))) for n, (k, o, _) in called.items())
    hdr9 = ns['read_at'](ns['PM_RIO'], int(ENTRY, 16) - 2 + 2, 9)
    if hdr9 != ns['CRSA_HDR9']: raise KitError('opening header %s' % hdr9.hex())
    P = ns['pm_srcs'][ENTRY].h
    old = bytes(P.d)
    snap = _counters(ns)
    imports_before = set(ns['new_objs'])
    files, items = {}, {}
    say0 = ns['say']
    ns['say'] = lambda *a: None                      # the kit's conversions stay out of the build's output and log
    ekey = entry_key(K)
    if ekey in rkeys: raise KitError('the opening key is a release key')
    try:
        for group, name, label in PUBLIC:
            if name not in man: raise KitError('%s is not in this build' % name)
            leads = leadins(BL, name) if group == G18 else []
            seq = [y for x in leads for y in ([cf[x]] if x in cf else []) + [x]]     # (the scene PM calls first)
            miss = [x for x in seq if x not in enc_of]
            if miss: raise KitError('%s: lead-in parts not in this build: %s' % (name, ', '.join(miss)))
            it = dict(group=group, label=label, lines=part_lines(man, called, name),     # (+ the scene it comes with)
                      lead_lines=sum(part_lines(man, called, x) for x in leads),
                      leadins=leads, gf=None, openings={})
            last = enc_of[name]; id_start = snap['next_id'][1][0]; extra = []
            if route_guarded(BL, name, ns['af_heap']):
                heap, obj = _guard_free_copy(ns, BL, name)
                key = ns['alloc_key']()
                imps = [(o['enc_off'], o['data']) for x, o in ns['new_objs'].items() if x not in imports_before]
                if any(d is None for _, d in imps): raise KitError('%s: import without data' % name)
                id_start = ns['next_id'][0]
                _restore(ns, snap)
                if not _same_state(ns, snap): raise KitError('build state not put back after %s' % name)
                gfo = [(key, obj)] + imps
                if any(k in rkeys or k == ekey for k, _ in gfo) or len(set(k for k, _ in gfo)) != len(gfo):
                    raise KitError('%s: guard-free copy key collides' % name)
                it['gf'] = dict(key=key, file='gf/%s.bin' % name, size=len(obj), sha1=sha1(obj),
                                imports=[dict(key=k, file='gf/%s.imp%d.bin' % (name, i), size=len(d), sha1=sha1(d))
                                         for i, (k, d) in enumerate(imps)])
                files[it['gf']['file']] = obj
                for i, (k, d) in enumerate(imps): files[it['gf']['imports'][i]['file']] = d
                last = (key, es(len(obj))); extra = [heap]
                sobj_gf = obj
            else:
                sobj_gf = None
            ns['pm_heaps'][ENTRY] = P               # registered as build_menu does (not a site script)
            try:
                for leadin in (('skip', 'with') if leads else ('skip',)):
                    names = (seq if leadin == 'with' else []) + [name]
                    encs = [enc_of[x] for x in names[:-1]] + [last]
                    ns['next_id'][0] = id_start
                    newP = ns['patch_pm'](ENTRY, [(AT, AT, e) for e in encs])
                    used = ns['next_id'][0] - id_start
                    _restore(ns, snap)
                    if used != len(encs): raise KitError('%s: patch_pm used %d ids for %d calls' % (name, used, len(encs)))
                    calls = [key_dec(K, e[0]) for e in encs]
                    flow, problems = check_opening(old, newP, AT, calls)
                    if problems: raise KitError('%s %s: the opening does not check: %s' % (name, leadin, problems[:3]))
                    ends = [last_kind(sobj[e[0]]) if e[0] in sobj else last_kind(sobj_gf) for e in encs]
                    if ends != ['CVmRet'] * len(encs): raise KitError('%s: called scripts end in %s' % (name, ends))
                    obj = bytes([0x00, 0x05]) + hdr9 + ns['encrypt_block'](newP)
                    f = 'open/%s-%s.z' % (name, leadin)
                    files[f] = zlib.compress(newP, 9)
                    it['openings'][leadin] = dict(file=f, heap_size=len(newP), heap_sha1=sha1(newP), size=len(obj),
                                                  sha1=sha1(obj), calls=[[e[0], e[1]] for e in encs], id_start=id_start,
                                                  parts=names, preds=flow['preds'])
            finally:
                ns['pm_heaps'].pop(ENTRY, None)
                _restore(ns, snap)
            items[name] = it
    finally:
        _restore(ns, snap)
        ns['pm_heaps'].pop(ENTRY, None)
        ns['say'] = say0
    if not _same_state(ns, snap): raise KitError('build state not put back')
    files['open/original.z'] = zlib.compress(old, 9)
    kit = dict(format=FORMAT, kind='scenekit', built=time.strftime('%Y-%m-%d %H:%M:%S'), K=K, entry=ENTRY, at=AT,
               entry_key=ekey, hdr9=hdr9.hex(), original=dict(file='open/original.z', size=len(old), sha1=sha1(old)),
               en=bool(ns.get('EN_DATA')), english_lines=len(ns.get('EN_DATA') or {}), release_objects=len(release),
               items=items)
    return kit, files


def write_kit(kit_dir, kit, files, patch_path):
    """Files, then kit.json with the patch file's identity (read back from the file just written)."""
    os.makedirs(kit_dir, exist_ok=True)
    for rel, data in sorted(files.items()):
        p = os.path.join(kit_dir, *rel.split('/'))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, 'wb') as f: f.write(data)
    kit = dict(kit, patch=dict(patch_id(patch_path), fingerprint=fingerprint(patch_path)),
               files={rel: [len(d), sha1(d)] for rel, d in files.items()})
    if kit['patch']['count'] != kit['release_objects']:
        raise KitError('the patch file has %d entries, the build wrote %d' % (kit['patch']['count'],
                                                                             kit['release_objects']))
    tmp = os.path.join(kit_dir, KIT_JSON + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(kit, f, indent=1, ensure_ascii=False); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, os.path.join(kit_dir, KIT_JSON))


# ---------------------------------------------------------------- using a kit
def load_kit(kit_dir):
    """kit.json of a complete kit (format, every file's size and sha1), else KitError."""
    p = os.path.join(kit_dir, KIT_JSON)
    try:
        with open(p, encoding='utf-8') as f: kit = json.load(f)
    except (OSError, ValueError):
        why = ''
        try:
            with open(os.path.join(kit_dir, 'failed.txt'), encoding='utf-8') as f: why = f.read().strip()
        except OSError:
            pass
        raise KitError('No scene test data for this build%s. Click "Rebuild & install" once.' % (
            ' (%s)' % why if why else ''))
    if not isinstance(kit, dict) or kit.get('format') != FORMAT or kit.get('kind') != 'scenekit' or \
            not isinstance(kit.get('items'), dict) or not isinstance(kit.get('patch'), dict):
        raise KitError('The scene test data was made by another version of the app. Click "Rebuild & install" once.')
    for rel, (n, h) in kit.get('files', {}).items():
        q = os.path.join(kit_dir, *rel.split('/'))
        try:
            if os.path.getsize(q) != n: raise OSError('size')
        except OSError:
            raise KitError('The scene test data is incomplete (%s). Click "Rebuild & install" once.' % rel)
    kit['_dir'] = kit_dir
    return kit


def _kit_file(kit, rel):
    n, h = kit['files'][rel]
    with open(os.path.join(kit['_dir'], *rel.split('/')), 'rb') as f: d = f.read()
    if len(d) != n or sha1(d) != h: raise KitError('The scene test data is damaged (%s). Click "Rebuild & install".' % rel)
    return d


def original_opening(kit):
    d = zlib.decompress(_kit_file(kit, kit['original']['file']))
    if len(d) != kit['original']['size'] or sha1(d) != kit['original']['sha1']: raise KitError('original opening damaged')
    return d


def plan(kit, item, leadin):
    """What a test of (item, leadin) adds: dict(objs=[(key, bytes)] in order (guard-free copy, opening, its imports),
    opening=heap bytes, calls=[(key, enc size)], item, leadin, label)."""
    it = kit['items'].get(item)
    if not it: raise KitError('%s is not in the scene test data of this build' % item)
    if leadin == 'with' and not it['leadins']: leadin = 'skip'
    o = it['openings'].get(leadin)
    if not o: raise KitError('%s: no opening for %s' % (item, leadin))
    from crsa import encrypt_block
    heap = zlib.decompress(_kit_file(kit, o['file']))
    if len(heap) != o['heap_size'] or sha1(heap) != o['heap_sha1']: raise KitError('%s: opening damaged' % item)
    obj = bytes([0x00, 0x05]) + bytes.fromhex(kit['hdr9']) + encrypt_block(heap)
    if len(obj) != o['size'] or sha1(obj) != o['sha1']: raise KitError('%s: opening does not encode as recorded' % item)
    objs = []
    g = it.get('gf')
    if g: objs.append((g['key'], _kit_file(kit, g['file'])))
    objs.append((kit['entry_key'], obj))
    if g: objs += [(i['key'], _kit_file(kit, i['file'])) for i in g['imports']]
    return dict(item=item, leadin=leadin, label=it['label'], objs=objs, opening=heap,
                calls=[tuple(c) for c in o['calls']], parts=o['parts'])


def check_patch(path, kit):
    """None when `path` is the patch file the kit was made for (size, entry count, table), else why not."""
    if not os.path.isfile(path): return 'the restored-content file is not in the game folder'
    try:
        now = patch_id(path)
    except (OSError, KitError) as e:
        return 'the restored-content file cannot be read (%s)' % e
    want = kit['patch']
    if (now['size'], now['count'], now['table_sha1']) != (want['size'], want['count'], want['table_sha1']):
        return 'the restored-content file is not the one this scene test data was made for'
    return None


def make_tail(S, n, table, objs, K):
    """Bytes appended at file position S: the new objects (4-aligned), the old table, the new entries, the new count.
    Returns (tail bytes, new table entries bytes, [(key, position, size)])."""
    if S % 4: raise KitError('the patch file size is not a multiple of 4')
    blob = bytearray(); new_tab = []; placed = []
    for key, data in objs:
        while (S + len(blob)) % 4: blob.append(0)
        pos = S + len(blob)
        new_tab.append(struct.pack('<III', key, (K + (pos >> SHIFT)) & M32, enc_size(len(data))))
        placed.append((key, pos, len(data)))
        blob += data
    while (S + len(blob)) % 4: blob.append(0)
    tab = b''.join(new_tab)
    return bytes(blob) + table + tab + struct.pack('<I', n + len(objs)), tab, placed


def _open_rw(path, tries=40, wait=0.1):
    """open(path, 'r+b'), tried again for about 4 s while Windows refuses it (a scanner holding the file; the running
    game holds it for good, then the PermissionError is raised)."""
    for i in range(tries):
        try:
            return open(path, 'r+b')
        except PermissionError:
            if i == tries - 1: raise
            time.sleep(wait)


def prepare(path, kit, item, leadin):
    """Everything an install writes, computed and checked before the file is touched: dict(plan, S, n, table, tail,
    tail_sha1, placed, size_after)."""
    why = check_patch(path, kit)
    if why: raise KitError(why[0].upper() + why[1:] + '.')
    p = plan(kit, item, leadin)
    n, table, tstart, S = read_table(path)
    keys = set(k for k, _, _ in entries(table, kit['K']))
    clash = [k for k, _ in p['objs'] if k in keys]
    if clash: raise KitError('the scene test objects collide with the patch (%s)' % ', '.join('%08x' % k for k in clash))
    tail, tab, placed = make_tail(S, n, table, p['objs'], kit['K'])
    return dict(plan=p, S=S, n=n, table=table, tail=tail, tail_sha1=sha1(tail), placed=placed, size_after=S + len(tail),
                orig_tail_sha1=sha1(table + struct.pack('<I', n)))


def write_tail(path, prep, before_write=None):
    """Append prep's tail at its S (the file must still be S bytes long) and flush it to the disk. before_write():
    a last check right before the file is opened for writing (raises to stop)."""
    if before_write: before_write()
    with _open_rw(path) as f:
        f.seek(0, 2)
        if f.tell() != prep['S']: raise KitError('the restored-content file changed size: nothing was written')
        f.write(prep['tail']); f.flush(); os.fsync(f.fileno())


def verify_tail(path, kit, prep):
    """Problems of the file as read back (empty = the test is installed exactly as planned)."""
    from crsa import decrypt_block
    bad = []
    n2, t2, ts2, size2 = read_table(path)
    if size2 != prep['size_after']: return ['size %d, planned %d' % (size2, prep['size_after'])]
    n = prep['n']
    if n2 != n + len(prep['placed']): bad.append('entry count %d' % n2)
    if t2[:12 * n] != prep['table']: bad.append('the old entries changed')
    with open(path, 'rb') as f:
        f.seek(prep['S']); tail = f.read()
        if sha1(tail) != prep['tail_sha1']: bad.append('the appended bytes differ')
        back = []
        for (key, pos, size), (k2, d) in zip(prep['placed'], prep['plan']['objs']):
            f.seek(pos); b = f.read(size); back.append(b)
            if b != d: bad.append('object %08x reads back different' % key)
        if bad: return bad
        ents = dict((k, (p, s)) for k, p, s in entries(t2, kit['K']))
        for (key, pos, size) in prep['placed']:
            if ents.get(key) != (pos, size): bad.append('table entry %08x' % key)
        op = back[[k for k, _ in prep['plan']['objs']].index(kit['entry_key'])]
        heap = decrypt_block(op[11:])[0]
        calls = [key_dec(kit['K'], c[0]) for c in prep['plan']['calls']]
        flow, problems = check_opening(original_opening(kit), heap, kit['at'], calls)
        bad += ['opening: %s' % x for x in problems[:3]]
        for key, _ in prep['plan']['calls']:
            if key not in ents: bad.append('called object %08x is not in the table' % key); continue
            pos, size = ents[key]; f.seek(pos)
            if last_kind(f.read(size)) != 'CVmRet': bad.append('called object %08x does not end in CVmRet' % key)
    return bad


def undo_tail(path, orig, settle=None):
    """Cut the file back to orig['S'] when the original table and count are still right before it. Returns
    'clean' (already the original), 'removed' (cut back; size and table checked), or raises KitError (any other file:
    left alone). settle(): a last check right before the file is opened for writing."""
    S, n = orig['S'], orig['n']
    try:
        size = os.path.getsize(path)
    except OSError:
        raise KitError('the restored-content file is not in the game folder any more: nothing to take out')
    if size < S: raise KitError('the restored-content file is shorter than before the test (replaced?): left as it is')
    with open(path, 'rb') as f:
        f.seek(S - 4 - 12 * n); at = f.read(12 * n + 4)
    if sha1(at) != orig['tail_sha1']:
        raise KitError('the restored-content file is not the one the test was put into (rebuilt?): left as it is')
    if size == S: return 'clean'
    if settle: settle()
    with _open_rw(path) as f:
        f.truncate(S); f.flush(); os.fsync(f.fileno())
    if os.path.getsize(path) != S or sha1(read_table(path)[1] + struct.pack('<I', n)) != orig['tail_sha1']:
        raise KitError('the restored-content file did not read back as before the test')
    return 'removed'
