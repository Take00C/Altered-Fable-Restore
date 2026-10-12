"""Build the restoration patch (.ruo) for Muv-Luv photonmelodies: the cut Altered Fable H scenes (with the lead-in /
aftermath PM cut together with them) re-encoded as PM-native scripts and called from PM's route scripts.
usage: build_all.py <output .ruo path> [scene,scene,...]
Never removes or reorders PM instructions: each site gets ONE inserted CVmCall whose next pointer may bypass PM's
all-ages stand-in lines (landing before PM's own closing transition, the achievement call and the chapter jump)."""
import sys, os, json, struct, glob, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rsaparse import Heap
from builder import Builder, Src, BuildError
from heapwriter import Slicer
from crsa import encrypt_block
from objio import read_at, AF_RIO, PM_RIO, af_object, pm_object, af_header, enc_size, dec_size_raw, parts, K
from oorparse import read_stream
from crimp import convert as crimp_convert, write_cstring_utf16
import blocks as BL
from scenes import heap as _scene_heap
_afh = {}


def af_heap(name):
    if name not in _afh:
        p1 = os.path.join(os.environ.get('AFR_OUT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out'), 'af_rsa', name + '.bin')
        if os.path.exists(p1):
            _afh[name] = _scene_heap(name)
        else:
            h = Heap(open(os.path.join(os.environ.get('AFR_OUT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out'), 'af_rsa_all', name + '.bin'), 'rb').read(), 2)
            h.parse(); _afh[name] = h
    return _afh[name]


def af_path(name):
    p1 = os.path.join(os.environ.get('AFR_OUT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out'), 'af_rsa', name + '.bin')
    return p1 if os.path.exists(p1) else os.path.join(os.environ.get('AFR_OUT') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'out'), 'af_rsa_all', name + '.bin')

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.environ.get('AFR_OUT') or os.path.join(HERE, '..', 'out')
NEW_KEY_BASE = 0x78000000
ID_BASE = int(os.environ.get("ID_BASE", "0x30000"), 16)   # test builds may move it so earlier read-flags do not apply
PM_SCHEMA = 0x15
VM_CLASSES = ('CVmCall', 'CVmRet', 'CVmMsg3', 'CVmJump', 'CVmFlagOp', 'CVmSync', 'CVmSound', 'CVmGenericMsg',
              'CVmLabel', 'CVmDirectionSync')
CRSA_HDR9 = bytes.fromhex('6e0301000000000000')
MSGBOX_AF = 0x44861
MSGBOX_PM = dict(off=0x4553d, size=300, cls=('CMsgSelBox', 17), parent=(('CBoxOcean', 8), 0x452b5, 535))
HELPER_OVERRIDE = {0x1afbc71: 0x672040dd,   # AF sprite helper -> PM successor (same 8 args; PM extras optional)
                   0x236d4ed: 0x676dcc71}   # AF screen-shake helper -> PM successor (drops AF's 3rd arg, see SHAKE_HELPER)
SHAKE_HELPER = 0x236d4ed  # AF (posture, int, wait): both send OM_AddPostureMomentum to the BG box; PM's takes (posture, int)
                          # and never waits (AF's 3rd arg only adds a CVmSync). PM's own AF-scene ports pass (posture, 1).
CAMERA_HELPER = 0xd13d87  # AF camera (x, y, rotation, distance, mode, ms) -> PM 27e92e99
# AF camera values that do not fit PM's copies of the pictures, by (AF heap, instruction): new (x, y, rot, dist, mode, ms).
# Marimo chapter: the ceiling billboard (helper 39b5f9d, depth 1000) at AF's distance 168 came out at 21% of the screen.
# On PM's billboard the picture size scales with distance (0.905 of the screen at 720); the 2007 game shows this shot as
# a close-up ~1.25x a full fill (measured from 2007 screenshots), hence 1020. AF's tilt is kept (rotation 45 -> 4 over
# the 600 ms transition); at this zoom the rotated picture still covers the screen.
CAMERA_FIX = {('000054cf59', 402): (0, 0, 45, 1020, 1, 0), ('000054cf59', 406): (0, 0, 4, 1020, 0, 0)}
BG_HELPER = 0xc93a57      # AF background (obj, mode) -> PM 27e92633
BILLBOARD_HELPER = 0x39b5f9d                  # AF picture placed in 3D (billboard) -> PM 86697a41
CAMERA_HELPERS = (0xd13d87, 0x1c54b13f)       # AF camera calls (distance is the 4th argument) -> PM 27e92e99
IMPORTED_IMAGE_ZOOM = 1.2
_zoomed = [0]
# Patched staging whose 3D billboard shots become plain background shots, (AF heap + '@patch') -> restored part: the
# official patch re-staged Mikoto's scene as billboard close-ups (depth 1440), and in PM those stayed a small whole
# picture inside black bars whatever the camera call said (2026-10-11). The patch's other shots (its forest background
# lines, transitions, shakes) stay. Converted: helper -> PM's background helper, args (picture, 2), the following camera
# distances x 1000/depth (a billboard at depth D frames like a background zoomed by 1000/D), 8-arg cameras cut to PM's
# 6 (its own ports drop the last two), and the fill floor below over the scene.
BB_TO_BG = {'00004f4791@patch': 'mikoto'}
_bb2bg = [0]
# Minimum camera distance on CG shots inside a restored range, AF heap -> (lo, hi, distance in AF units): a CG needs
# >= 720 to fill PM's 16:9 screen (measured in game: an imported CG at 720 x1.2 fills it edge to edge); the 2007 script
# frames some of Mikoto's CGs at 600 (a 4:3 screen showed them whole), which in PM left black bars. Such shots show the
# whole CG at 720, centred (the user asked for no black bars over the original camera moves, 2026-10-11).
FILL_FLOOR = {'00004f4791': (1802, 2279, 720)}
_floored = [0]
# AF's two "special" hut backgrounds carry their foreground (tree trunk, canopy bed, plant, post) inside the background
# object. PM converted them to plain backgrounds and draws the foreground as three overlay layers right after every
# background call (helper 67fb353f + OM_SetVarData depth per layer box; the next background call replaces them).
# Restored shots get PM's own overlay instructions, copied from a PM scene showing the same background.
BG_OVERLAYS = {0x7696d25b: ('01b30e953a', 1856, 1862),     # night hut -> dc1cabef
               0x6deb814f: ('0192586282', 18, 24)}         # day hut -> c9258e0f


def camera_fix():
    return CAMERA_FIX


DROP_SPRITES = os.environ.get("DROP_SPRITES") == "1"
DROP_HELPERS = set()
IMG_CLASSES = ('Cr6Ti', 'CAC7Ti')
IMPORT_OK = ('COptimizedObs', 'Cr6Ti', 'CAC7Ti', 'CRmt', 'CPmBgm', 'CPmEffect', 'CMoveAcsOngen', 'CBg2d')   # shake patterns / backgrounds: same schema in both
S_CALL = 20
AF_TOTAL = sum(os.path.getsize(p) for p in parts(AF_RIO))

scenes = sys.argv[2].split(',') if len(sys.argv) > 2 and sys.argv[2] != 'all' else list(BL.SITES) + list(BL.MARIMO_PARTS) + list(BL.EXTRA_PARTS)
DEBUG = len(sys.argv) > 3 and sys.argv[3] == 'debug'   # also call the scene(s) from the AF story opening
DEBUG_HEAP, DEBUG_AT = '00ce1abaf2', 16   # before the opening's ambient loop (instr 16..19) - test scenes ran with it playing
# test-only parts (debug builds): TEST_PARTS="name:afheap:lo:hi,..." -> AF range called only from the debug entry point
for _t in filter(None, os.environ.get('TEST_PARTS', '').split(',')):
    _n, _af, _lo, _hi = _t.split(':')
    BL.MARIMO_PARTS[_n] = (_af, int(_lo), int(_hi), DEBUG_HEAP, DEBUG_AT, DEBUG_AT)
    assert DEBUG and _n in scenes, 'TEST_PARTS need a debug build that names them'
TEST_NAMES = {t.split(':')[0] for t in filter(None, os.environ.get('TEST_PARTS', '').split(','))}
log = open(os.path.join(OUT, 'build_all.log'), 'w', encoding='utf-8')


def say(*a):
    print(*a); print(*a, file=log)


# ---------------------------------------------------------------- PM registries
objmap = json.load(open(os.path.join(OUT, 'objmap.json')))
# objmap pairs the vote got wrong, checked against PM's own port of the same AF scene. AF 7696d25b (1440x1200 special
# background) won PM c2c5cf29 on 1 of 2 votes, but c2c5cf29 is a 1400x820 picture (the 5/5 pair of AF b6f2a731) and comes
# out small; PM shows AF 45d98b@1777 (this background + CAM 21,45,0,864) as dc1cabef with the same camera (01b30e953a@1855).
OBJMAP_FIX = {0x7696d25b: (0xdc1cabef, ['CBg2d', 6, 568409])}
for _af, (_pm, _pmc) in OBJMAP_FIX.items():
    objmap[str(_af)].update(pm=_pm, pmc=_pmc, votes=1, total=1)
sound_pairs = {int(k): v for k, v in json.load(open(os.path.join(OUT, 'sound_pairs.json'))).items()}
packed, pm_schema, rdef_schema = {}, {}, {}
templates = {}
pm_heaps = {}
pm_srcs = {}
site_heaps = sorted(set((BL.SITES[n][2] if n in BL.SITES else BL.part(n)[3]) for n in scenes) | ({DEBUG_HEAP} if DEBUG else set()))
paths = sorted(glob.glob(os.path.join(OUT, 'pm_rsa', '*.bin')))
order = [os.path.join(OUT, 'pm_rsa', n + '.bin') for n in site_heaps] + [p for p in paths if os.path.basename(p)[:-4] not in site_heaps]
for p in order:
    h = Heap(open(p, 'rb').read(), 2)
    try: h.parse()
    except Exception: continue
    name = os.path.basename(p)[:-4]
    if name in site_heaps: pm_heaps[name] = h
    s = Src(h, 'PM', name); pm_srcs[name] = s
    for k, ev in enumerate(h.ev):
        if ev[0] == 'cdef':
            packed.setdefault(ev[4][0], h.d[ev[1] + 5:ev[2]]); pm_schema.setdefault(ev[4][0], ev[4][1])
        elif ev[0] == 'rdef':
            rdef_schema.setdefault(ev[4][0], ev[4][1])
        elif ev[0] == 'ref' and ev[6] not in templates:
            templates[ev[6]] = (s, k)
say('PM registries: %d class names, %d templates' % (len(packed), len(templates)))


def mapped(off):
    m = objmap.get(str(off))
    return m['pm'] if m and m['votes'] / m['total'] >= 0.5 else None


_ident = {}


def image_identical(af_off, af_size, pm_off):
    """AF and PM images hold the same picture: same body length, <= 16 differing bytes (version/metadata)."""
    key = (af_off, pm_off)
    if key not in _ident:
        m = objmap[str(af_off)]
        s, body, raw, _ = af_object(af_off, af_size)
        pr = pm_object(pm_off, m['pmc'][2])
        ok = False
        if len(pr) >= len(body) and len(pr) - len(body) <= 4:
            tail = pr[len(pr) - len(body):]
            ok = sum(1 for a, b in zip(body, tail) if a != b) <= 16
        _ident[key] = ok
    return _ident[key]


# ---------------------------------------------------------------- imports
new_objs = {}        # af_off -> dict(cls, enc_off, data)
next_x = [NEW_KEY_BASE]


def alloc_key():
    x = next_x[0]; next_x[0] += 0x10
    return (K + x) & 0xFFFFFFFF


def af_raw(off, size):
    return read_at(AF_RIO, off - 3, size + 3)


def is_naked_oor(raw):
    try:
        pages, end = read_stream(raw, 0)
        return end == len(raw) and len(pages) >= 2 and (pages[-1]['flags'] & 1)
    except Exception:
        return False


def has_class_tag(b, k):
    """The 2 bytes before a 0xC108 flag are a class index, or a class definition ends right there."""
    tag = struct.unpack_from('<H', b, k - 2)[0]
    if tag & 0x8000 and 1 < (tag & 0x7fff) < 0x1000:
        return True
    for q in range(max(0, k - 40), k - 4):          # 0xFFFF + schema word + len byte + packed name, ending at k
        if b[q:q + 2] == b'\xff\xff' and q + 5 + b[q + 4] == k:
            return True
    return False


def body_refs(body):
    """Validated embedded MFC object refs: (pos_of_enc_pair, af_dec_off, af_size). Flags 0xC108 and 0xC118 (the
    official patch's own objects); targets in the base archive or, with the patch, in its mapped region."""
    import objio as _objio
    pmap = _objio._patch_map.get(AF_RIO)
    out = []; k = 0
    while True:
        k1 = body.find(b'\x08\xc1', k); k2 = body.find(b'\x18\xc1', k)
        k = min(x for x in (k1, k2) if x >= 0) if max(k1, k2) >= 0 else -1
        if k < 0: break
        if k >= 2 and k + 10 <= len(body) and has_class_tag(body, k):
            eo, es = struct.unpack_from('<II', body, k + 2)
            pos = 2 * ((eo - K) & 0xFFFFFFFF); size = dec_size_raw(es) - 3      # parser convention: size = raw extent - 3
            if (0 < pos < AF_TOTAL or (pmap and pos >= pmap[1])) and 0 <= size < 50_000_000:
                try:
                    af_header(read_at(AF_RIO, pos, 8))
                    out.append((k + 2, pos + 3, size))
                except Exception:
                    pass
        k += 1
    return out


nested_map = {}


def pm_body_refs(pr):
    out = []; q = 0
    while True:
        q = pr.find(b'\x08\xc1', q)
        if q < 0: break
        if q >= 2 and q + 10 <= len(pr) and has_class_tag(pr, q):
            eo, es = struct.unpack_from('<II', pr, q + 2)
            out.append((3 + 2 * ((eo - K) & 0xFFFFFFFF), dec_size_raw(es) - 3))
        q += 1
    return out


def learn_nested():
    """AF->PM pairs for SHARED objects referenced from inside sound/sprite objects (CObjectOcean, CRimp), learned
    by zipping the embedded refs of objmap-paired AF/PM objects."""
    cls_of = {t_off: tsrc.h.ev[tk][5][0] for t_off, (tsrc, tk) in templates.items()}
    votes = collections.defaultdict(collections.Counter)
    for k, v in objmap.items():
        if v['af'][0] not in ('CRmt', 'CPmBgm', 'CPmEffect') or v['votes'] / v['total'] < 0.5: continue
        try:
            s_, body, raw, _ = af_object(int(k), v['af'][2]); pr = pm_object(v['pm'], v['pmc'][2])
        except Exception:
            continue
        ra = [(off, sz) for (_, off, sz) in body_refs(body)]
        rp = pm_body_refs(pr)
        if len(ra) != len(rp): continue
        for (ao, asz), (po, psz) in zip(ra, rp):
            if cls_of.get(po) in ('CObjectOcean', 'CRimp'):
                votes[ao][(po, psz)] += 1
    for ao, c in votes.items():
        (po, psz), n = c.most_common(1)[0]
        if n / sum(c.values()) >= 0.75: nested_map[ao] = (po, psz)
    say('learned %d shared nested-object mappings' % len(nested_map))


def nested_target(off, size, cls_hint=None):
    """enc pair for an object referenced from inside an imported body."""
    if off in nested_map:
        po, psz = nested_map[off]
        nested_log.append(('shared->PM', hex(off), size, hex(po)))
        return ((K + (po - 3) // 2) & 0xFFFFFFFF, enc_size(psz + 3))
    pm = mapped(off)
    if pm is not None:
        m = objmap[str(off)]
        if m['af'][0] not in IMG_CLASSES or image_identical(off, size, pm):
            nested_log.append(('mapped->PM', hex(off), size, hex(pm)))
            return ((K + (pm - 3) // 2) & 0xFFFFFFFF, enc_size(m['pmc'][2] + 3))
    nested_log.append(('import', hex(off), size, None))
    return key_alloc(off, cls_hint, size)


nested_log = []


def crmt_swap_tags(body):
    """Make an AF CRmt body readable by PM's CRmt reader. Measured (debugger, load array at the CRimp read): PM numbers
    the archive [2 CRmt, 3 self, 4 owner, 5 CRmti, 6 CRimp, 7 Cr6Ti]; AF's tags imply [.., 5 image class, 6 CRimp, 7 ?].
    -> image class index 5 -> 7 at object slots (flag 0xC040 inline / 0xC108 ref), and the three registration version
    words (AF order image, CRimp, ? ; PM order CRmti, CRimp, Cr6Ti) are reordered [w1,w2,w3] -> [w3,w2,w1]."""
    w1, w2, w3 = struct.unpack_from('<HHH', body, 0)
    struct.pack_into('<HHH', body, 0, w3, w2, w1)
    k = 6; n = 0
    while k < len(body) - 4:
        if body[k + 1] == 0x80 and body[k] == 5 and struct.unpack_from('<H', body, k + 2)[0] in (0xC040, 0xC108):
            body[k] = 7; n += 1; k += 4
        else:
            k += 1
    crmt_swaps.append(n)


crmt_swaps = []
crimp_done = []


def key_alloc(af_off, cls, size):
    if af_off not in new_objs:
        raw = af_raw(af_off, size)
        if (cls and cls[0] == 'COptimizedObs') or (cls is None and is_naked_oor(raw)):
            data = raw; cname = 'COptimizedObs'
        else:
            n, schema, mode, extra = af_header(raw)
            if mode not in (0,):
                raise BuildError('import %x: AF header mode %d not handled' % (af_off, mode))
            body = bytearray(raw[n:])
            cname = cls[0] if cls else '?'
            new_objs[af_off] = dict(cls=cname, enc_off=alloc_key(), data=None)    # reserve (cycles)
            for (p, noff, nsize) in body_refs(bytes(body)):
                hint = None
                if cname == 'CRmt':
                    tag = struct.unpack_from('<H', body, p - 4)[0]
                    if tag == 0x8002: hint = ('CRmt', 4)      # class index 2 inside a CRmt archive = CRmt itself
                    elif tag == 0x8006: hint = ('CRimp', 3)   # the sprite set (property map)
                eo, es = nested_target(noff, nsize, hint)
                struct.pack_into('<II', body, p, eo, es)
            if cname == 'CRimp':
                # AF property map: cp932 keys + Japanese type names -> UTF-16 keys + PM type names
                body = bytearray(crimp_convert(bytes(body))[0]); crimp_done.append(af_off)
            data = bytes([0x00, schema & 0xff]) + bytes(body)
            new_objs[af_off]['data'] = data
            return new_objs[af_off]['enc_off'], enc_size(len(data))
        new_objs[af_off] = dict(cls=cname, enc_off=alloc_key(), data=data)
    o = new_objs[af_off]
    if o['data'] is None:   # cycle: size unknown yet -> recompute from source (header length is constant)
        raw = af_raw(af_off, size); n = af_header(raw)[0]
        return o['enc_off'], enc_size(2 + len(raw) - n)
    return o['enc_off'], enc_size(len(o['data']))


_audio = {}


def audio_packets(data):
    """Number of audio packets of a sound stream (OOR pages; PM streams may carry a small header)."""
    for st in range(0, 24):
        try:
            pages, end = read_stream(data, st)
            if end == len(data) and len(pages) >= 2:
                return sum(len(p['pktlens']) for p in pages)
        except Exception:
            pass
    return None


# PM re-encoded its audio: the same recording comes out with 1-2.3% fewer packets (every restored BGM pair: 0.977-0.990),
# while the wrong pairings are far off (x0.66, x0.78, x1.5, x16). Requiring equal counts sent every BGM to AF's own clip,
# so each scene restarted the song PM was already playing before it (2026-10-11).
AUDIO_TOLERANCE = 0.03


def same_audio(af_off, af_size, pm_off):
    key = (af_off, pm_off)
    if key not in _audio:
        a = p = None
        raw = af_raw(af_off, af_size)
        for (_, t, sz) in body_refs(raw[af_header(raw)[0]:]):
            s = af_raw(t, sz)
            if is_naked_oor(s): a = audio_packets(s); break
        sp = sound_pairs.get(pm_off)
        if sp: p = audio_packets(pm_object(sp[1], sp[2]))
        _audio[key] = a is not None and p is not None and abs(a - p) <= max(2, AUDIO_TOLERANCE * a)
    return _audio[key]


def remap(src, obj):
    cls, off, size = obj
    if src is None or src.archive == 'PM':
        return ('PM', off)
    name = cls[0]
    if name == 'CMsgSelBox' and off == MSGBOX_AF:
        return ('PM', MSGBOX_PM['off'])
    if name == 'CRsa':
        if off == BILLBOARD_HELPER and src.name in BB_TO_BG: return ('PM', mapped(BG_HELPER))
        if off in HELPER_OVERRIDE: return ('PM', HELPER_OVERRIDE[off])
        pm = mapped(off)
        if pm is None: raise BuildError('helper CRsa %x not mapped' % off)
        return ('PM', pm)
    pm = mapped(off)
    if name in IMG_CLASSES:
        if pm is not None and image_identical(off, size, pm): return ('PM', pm)
        return ('NEW', off)
    # Sound effects / BGM: PM's clip only when it is provably the same recording (audio packet count within
    # AUDIO_TOLERANCE; PM re-encoded its audio, so bytes never match). objmap paired several restored sounds with other
    # clips (votes 1/2, lengths x0.5..x16), so anything unproven plays AF's own clip.
    if name in ('CPmEffect', 'CPmBgm') and pm is not None and not same_audio(off, size, pm):
        return ('NEW', off)
    # Backgrounds / sprites stay on the PM mapping even when the bytes differ: PM remastered them for its screen layout
    # (an AF background imported instead rendered small and skewed in game, 2026-10-11).
    if pm is not None:
        return ('PM', pm)
    if name in IMPORT_OK:
        return ('NEW', off)
    raise BuildError('no mapping for %s %x' % (cls, off))


# ---------------------------------------------------------------- scene conversion
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


def af_offsets_of(h):
    """AF in-memory instruction offsets from the dw1 next chain (AF branch targets are such offsets)."""
    return [0] + [struct.unpack_from('<I', h.d, base_pos(h.d, h.instrs[i][0]))[0] for i in range(h.count - 1)]


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


next_id = [ID_BASE]


def slot_end(h, ev_lo, ev_hi, start):
    for k in range(ev_lo, ev_hi):
        ev = h.ev[k]
        if ev[0] == 'ref' and ev[1] == start: return ev[2]
    return start + 2


TYPE_NAMES = {'低精度実数'.encode('cp932'): b'_float', '色'.encode('cp932'): b'_VCOLOR'}   # AF -> PM type names


class TypedArgHeap(Heap):
    """Records the byte span of every typed-constant (d==4) CVmCall argument's type name: (len_pos, name_end, name),
    and of every non-ASCII ANSI CString (call / OM arguments) in self.ansi: (start, end, bytes)."""
    def string(self):
        a = self.p; s = Heap.string(self)
        if self.d[a] != 0xff and any(b >= 0x80 for b in s):
            self.ansi.append((a, self.p, s))
        return s

    def parse(self):
        self.ansi = []; return Heap.parse(self)

    def vm_call(self):
        self.u32(); self.u32(); self.read_class_list(); npos = self.p; n = self.u16(); spans = []; argpos = []
        for _ in range(n):
            argpos.append(self.p)
            d = self.u32()
            if d == 4:
                w = self.u16()
                if w in (0x2d6b, 0x2f1a):
                    self.u16(); kp = self.p; k = self.u16(); nm = self.d[self.p:self.p + k]; self.skip(k)
                    spans.append((kp, self.p, nm)); self.skip(4)
                elif w == 0x1e57: self.read_class(); self.skip(4)
                elif w == 0x369e: self.read_raw_class(); self.skip(4)
                else: raise BuildError('call w=%x' % w)
            else:
                k = d & 3
                if k == 0: self.read_class_list()
                elif k == 1: self.string()
                elif k == 3:
                    t1 = self.u32()
                    if t1 == 0x137: self.u32()
        argpos.append(self.p)
        return dict(spans=spans, npos=npos, argpos=argpos)


class MsgExtHeap(Heap):
    """Records each CVmMsg's flag-0x200000 extension, keyed by the text position:
    w bit 4 = ruby string ('base:reading;...', same format PM keeps in the CVmMsg3 item's 2nd dword),
    w bits 0-1 = extra entries (extra voices, played after the main one), 0x40 string, 0x20 dword, 8 per-entry word."""
    def parse(self):
        self.msg_ext = {}; return Heap.parse(self)

    def vm_msg(self):
        self.u32(); flag = self.u32(); self.read_class_list()
        n = self.u8()
        if n == 0xff: n = self.u16()
        tp = self.p
        self.strings.append((self.p, self.d[self.p:self.p + n])); self.p += n
        self.read_class_list()
        if flag & 0x4000000: self.read_class_list()
        if flag & 0x200000:
            w = self.u16(); e = dict(w=w, ruby=None, s40=None, d20=None, extra=0)
            if w & 4: e['ruby'] = self.string()
            if w & 0x40: e['s40'] = self.string()
            if w & 0x20: e['d20'] = self.u32()
            if w & 3:
                k = self.u16(); e['extra'] = k
                for _ in range(k):
                    if w & 8: self.u16()
                    self.read_class_list()
                    if (w & 3) == 3: self.read_class_list()
            self.msg_ext[tp] = e


_msgext = {}


def msg_ext(af):
    if af not in _msgext:
        T = MsgExtHeap(open(af_path(af), 'rb').read(), 2); T.parse(); _msgext[af] = T.msg_ext
    return _msgext[af]


# ---------------------------------------------------------------- AF official patch (altfable.rio.ruo1)
# The patch overrides every AF script. The scripts in altfable.rio are the unpatched release: on 459 lines they play the
# wrong voice take (the old clip is often reused on another line; the patch gives each line its own clip of the same
# speaker) and some lines have typos. Restored lines take text + voice from the patched script, matched by message id
# (dw2 low 20 bits); structure/staging stays on the unpatched script the parts were mapped and live-tested on.
AF_PATCH = (94323034, '17dbeb8aa5285f69833fb8f7a50745b8cbc7c1b5')
_afp = {}


def af_patch_msgs(name):
    """{message id: (text bytes, [voice refs (cls, off, size)])} from the patched script, or {} without the patch."""
    if name in _afp: return _afp[name]
    _afp[name] = {}
    ruo = AF_RIO + '.ruo1'
    if '_ruo' not in _afp:
        _afp['_ruo'] = None
        if os.path.isfile(ruo) and os.path.getsize(ruo) == AF_PATCH[0]:
            import hashlib
            d = open(ruo, 'rb').read()
            if hashlib.sha1(d).hexdigest() == AF_PATCH[1]:
                n = struct.unpack_from('<I', d, len(d) - 4)[0]
                tab = d[len(d) - 4 - 12 * n:len(d) - 4]
                ents = {}
                for i in range(n):
                    key, loc, _ = struct.unpack_from('<III', tab, 12 * i)
                    ents[3 + 2 * ((key - K) & 0xFFFFFFFF)] = 2 * ((loc - K) & 0xFFFFFFFF)
                _afp['_ruo'] = (d, ents)
                import objio as _objio     # objects that exist only in the patch file (staging taken from it)
                _objio.map_patch(AF_RIO, ruo, 0xD0000000)
        say('AF official patch: %s' % ('used for restored text/voices' if _afp['_ruo'] else 'not found - unpatched text/voices'))
    H = af_patch_heap(name) if name else None
    if H is None: return {}
    out, dup = {}, set()
    for i, ins in enumerate(H.instrs):
        if ins[2] != 'CVmMsg' or not ins[5]: continue
        mid = struct.unpack_from('<I', H.d, base_pos(H.d, ins[0]) + 4)[0] & 0xFFFFF
        if mid in out: dup.add(mid)
        out[mid] = (ins[5][0][1], [r for r in (H.ins_res[i] or [])[1:]
                                   if r and isinstance(r[0], tuple) and r[0][0] == 'COptimizedObs'])
    for mid in dup: del out[mid]        # ambiguous ids: keep the unpatched line
    _afp[name] = out
    return out


def af_patch_heap(name):
    """The official patch's version of an AF script (parsed), or None without the patch / when it lacks the script."""
    key = '@heap:' + name
    if key in _afp: return _afp[key]
    _afp[key] = None
    af_patch_msgs('')                           # loads / checks the patch file once
    if not _afp.get('_ruo'): return None
    d, ents = _afp['_ruo']
    v = int(name, 16)
    fp = next((ents[p] for p in range(v - 8, v + 9) if p in ents), None)
    if fp is None: return None
    c = next((c for c in range(fp - 4, fp + 12) if d[c:c + 2] == b'\x6e\x03'), None)
    if c is None: raise BuildError('AF patch: script %s not found in the patch file' % name)
    b = struct.unpack_from('<I', d, c + 13)[0]
    size = ((b ^ 0xC92E568F) & 0xFFFFFFFF) >> 3
    from crsa import decrypt_block
    heap, _ = decrypt_block(d[c + 9:c + 9 + size + size // 32 * 2 + 64])
    H = Heap(heap, 2); H.parse()
    _afp[key] = H
    return H


def stage_sig(H, i):
    """Comparable signature of a staging instruction: class, referenced objects, plain int call arguments."""
    ins = H.instrs[i]
    objs = tuple((x[0][0], x[1]) for x in (H.ins_res[i] or []) if x and isinstance(x[0], tuple))
    args = None
    if ins[2] == 'CVmCall':
        raw = H.d[ins[0]:ins[1]]
        for n in range(1, 14):
            q = len(raw) - 4 * n - 2
            if q < 0: break
            if struct.unpack_from('<H', raw, q)[0] == n:
                args = raw[q:]; break
    return ins[2], objs, args


def staging_segments(H, idxs):
    """{line message id: [instruction indices between the previous line and this one]}, 'end': [after the last]."""
    out = collections.OrderedDict(); cur = []; seen = collections.Counter()
    for i in idxs:
        ins = H.instrs[i]
        if ins[2] == 'CVmMsg':
            mid = struct.unpack_from('<I', H.d, base_pos(H.d, ins[0]) + 4)[0] & 0xFFFFF
            seen[mid] += 1; out[mid] = cur; cur = []
        elif ins[2] != 'CVmRet':
            cur.append(i)
    out['end'] = cur
    for mid, n in seen.items():
        if n > 1: out[mid] = None              # ambiguous id: never substituted
    return out


_typed = {}


def type_name_repl(af, data=None):
    """raw_repl entries translating AF typed-argument type names to PM's (PM >= archive 0x16 looks them up by name).
    data: heap bytes of the official patch's version (key af + '@patch'); camera fixes apply to the unpatched script."""
    if af not in _typed:
        T = TypedArgHeap(data if data is not None else open(af_path(af), 'rb').read(), 2); T.parse()
        repl = {}
        for ins in T.instrs:
            if ins[2] != 'CVmCall': continue
            for (kp, end, nm) in ins[3]['spans']:
                if nm not in TYPE_NAMES: raise BuildError('unknown typed-argument type %r' % nm)
                new = TYPE_NAMES[nm]
                repl[kp] = (end, struct.pack('<H', len(new)) + new)
        for i, ins in enumerate(T.instrs):     # AF shake call (posture, int, wait) -> PM (posture, int)
            r0 = T.ins_res[i][0] if T.ins_res[i] else None
            if ins[2] != 'CVmCall' or not (r0 and isinstance(r0[0], tuple) and r0[1] == SHAKE_HELPER): continue
            L = ins[3]; ap = L['argpos']
            if len(ap) != 4 or struct.unpack_from('<I', T.d, ap[2])[0] & 3 != 2 or ap[3] - ap[2] != 4:
                raise BuildError('shake call %d: unexpected args' % i)
            repl[L['npos']] = (L['npos'] + 2, struct.pack('<H', 2))
            repl[ap[2]] = (ap[3], b'')
        for (a, end, sb) in T.ansi:          # PM is a Unicode build: AF cp932 strings become UTF-16 CStrings
            repl[a] = (end, write_cstring_utf16(sb.decode('cp932')))
        # cameras framing an imported AF picture (raw Cr6Ti without an identical PM copy): PM draws such pictures at
        # 1/1.2 of AF's size, so AF's camera zoom (the 'distance' word; picture size scales with it) times 1.2 gives
        # AF's framing. PM's own copies are drawn for its world and keep AF's values (checked against the 2007 game).
        fixed = {i for (h_, i) in camera_fix() if data is None and af.endswith(h_)}
        floor = FILL_FLOOR.get(af) if data is None else None
        conv = BB_TO_BG.get(af)
        if conv:      # the scene starts after its anchor line (found by message id in the patched script)
            blc = BL.block(conv); Au = af_heap(blc['af'])
            mid0 = struct.unpack_from('<I', Au.d, base_pos(Au.d, Au.instrs[blc['lo'] - 1][0]) + 4)[0] & 0xFFFFF
            lo_p = next(j + 1 for j, t in enumerate(T.instrs) if t[2] == 'CVmMsg' and
                        struct.unpack_from('<I', T.d, base_pos(T.d, t[0]) + 4)[0] & 0xFFFFF == mid0)
            floor = (lo_p, T.count, FILL_FLOOR[blc['af']][2])

        def cut_args(L, a, b, n):        # keep the first n args: drop bytes [a, b) and any replacement inside them
            for k in [k for k in repl if a <= k < b]: del repl[k]
            repl[L['npos']] = (L['npos'] + 2, struct.pack('<H', n))
            return a

        last_imported = last_cg = False; depth = None
        for i, ins in enumerate(T.instrs):
            r0 = T.ins_res[i][0] if T.ins_res[i] else None
            if ins[2] != 'CVmCall' or not (r0 and isinstance(r0[0], tuple)): continue
            if r0[1] in (BG_HELPER, BILLBOARD_HELPER):
                img = next((x for x in T.ins_res[i][1:] if x and isinstance(x[0], tuple)), None)
                last_imported = bool(img and img[0][0] in IMG_CLASSES and not (
                    mapped(img[1]) is not None and image_identical(img[1], img[2], mapped(img[1]))))
                last_cg = bool(img and img[0][0] == 'Cr6Ti')
                depth = None
                if conv and r0[1] == BILLBOARD_HELPER and i >= floor[0]:
                    L = ins[3]; ap = L['argpos']
                    d4 = struct.unpack_from('<I', T.d, ap[4])[0]
                    if len(ap) != 7 or d4 & 3 != 2: raise BuildError('billboard call %d: unexpected args' % i)
                    depth = (d4 >> 2) or 1000
                    repl[cut_args(L, ap[1], ap[-1], 2)] = (ap[-1], struct.pack('<I', (2 << 2) | 2))   # (picture, 2)
                    _bb2bg[0] += 1
            elif r0[1] in CAMERA_HELPERS and i not in fixed:
                ap = ins[3]['argpos']
                if len(ap) < 5: continue
                if conv and i >= floor[0] and len(ap) == 9:
                    repl[cut_args(ins[3], ap[6], ap[8], 6)] = (ap[8], b'')
                w = [struct.unpack_from('<I', T.d, ap[k])[0] for k in range(4)]
                if any(x & 3 != 2 for x in w): continue
                x, y, rot, v = [(x >> 2) - (1 << 30) if x >> 2 >= 1 << 29 else x >> 2 for x in w]
                new = [x, y, rot, v]
                if depth: new[3] = round(v * 1000 / depth)
                if floor and last_cg and floor[0] <= i < floor[1] and new[3] < floor[2]:
                    new = [0, 0, 0, floor[2]]; _floored[0] += 1      # whole CG, filling the screen, centred
                if last_imported:
                    new[3] = round(new[3] * IMPORTED_IMAGE_ZOOM); _zoomed[0] += 1
                for k in range(4):
                    if new[k] != [x, y, rot, v][k]:
                        repl[ap[k]] = (ap[k] + 4, struct.pack('<I', ((new[k] << 2) | 2) & 0xFFFFFFFF))
        for (h_, i), vals in camera_fix().items():
            if data is not None or not af.endswith(h_): continue
            r0 = T.ins_res[i][0] if T.ins_res[i] else None
            ap = T.instrs[i][3]['argpos']
            if not (r0 and isinstance(r0[0], tuple) and r0[1] == CAMERA_HELPER) or len(ap) < len(vals):
                raise BuildError('camera fix %s@%d: not a camera call' % (h_, i))
            for k, v in enumerate(vals):
                if struct.unpack_from('<I', T.d, ap[k])[0] & 3 != 2: raise BuildError('camera fix %s@%d arg %d' % (h_, i, k))
                repl[ap[k]] = (ap[k] + 4, struct.pack('<I', ((v << 2) | 2) & 0xFFFFFFFF))
        _typed[af] = repl
    return _typed[af]


PREWRAP_MAX = 28   # verified live: unbroken lines up to 28 full-width chars fit PM's English text layout
_BREAK_AFTER = set('、。，．！？!?…」』）―')


def prewrap(t):
    """Break a Japanese line with explicit newlines for PM's English text layout (text language = English), which
    only wraps at spaces: an unbroken line wider than the box comes out as a few 2-5 character lines plus one overlong
    line. Each piece stays <= PREWRAP_MAX characters, preferring breaks after punctuation; shorter lines are unchanged."""
    out = []
    for para in t.split('\n'):
        while len(para.rstrip('\x01')) > PREWRAP_MAX:
            cut = max((k + 1 for k in range(PREWRAP_MAX // 2, PREWRAP_MAX) if para[k] in _BREAK_AFTER), default=PREWRAP_MAX)
            while cut < len(para) and para[cut] in _BREAK_AFTER:   # keep runs like '……' or '」' together
                cut += 1
            out.append(para[:cut]); para = para[cut:]
        out.append(para)
    return '\n'.join(out)


def convert_block(bl, pad_count):
    # template sources map their indices into ONE output heap: reset them per block, or a previous block's pad /
    # class / object numbering leaks in (a text-only block puts its pad one index later -> wrong parent refs -> crash)
    for tsrc in {t[0] for t in templates.values()}:
        tsrc.map = {0: 0, 1: 1}
    A = af_heap(bl['af']); srcA = Src(A, 'AF', bl['af'])
    srcA.raw_repl = type_name_repl(bl['af'])
    B = Builder(pad_count, remap, templates, packed, key_alloc)
    B.schema_override = dict(pm_schema); B.schema_override.update({n: PM_SCHEMA for n in VM_CLASSES})
    B.constructed[MSGBOX_PM['off']] = dict(cls=MSGBOX_PM['cls'], enc_size=enc_size(MSGBOX_PM['size'] + 3),
                                           parent=MSGBOX_PM['parent'])
    table = ['\x00']; tlen = [1]
    tail = [('null',), ('msgbox',)]; vidx = {}
    stats = collections.Counter()

    def add_text(t):
        off = tlen[0]; table.append(t + '\x00'); tlen[0] += len(t) + 1; return off

    keep = []
    for i in bl['keep']:
        # optionally drop instructions that display AF-only sprite objects (CRmt) (env DROP_SPRITES=1)
        if DROP_SPRITES and A.instrs[i][2] in ('CVmCall', 'CVmGenericMsg') and any(
                x and isinstance(x[0], tuple) and x[0][0] == 'CRmt' and mapped(x[1]) is None for x in A.ins_res[i]):
            stats['dropped_unmapped_sprite'] += 1; continue
        t0 = A.ins_res[i][0] if A.ins_res[i] else None
        if A.instrs[i][2] == 'CVmCall' and t0 and isinstance(t0[0], tuple) and t0[1] in DROP_HELPERS:
            stats['dropped_screen_effect'] += 1; continue
        keep.append(i)
    bl = dict(bl, keep=keep)
    af_offs = af_offsets_of(A)
    af_inv = {o: k for k, o in enumerate(af_offs)}

    def emit_staging(H, src, i):
        """Emit one call / sync / message / sound instruction of source heap H. Returns the number of extra output
        instructions (PM overlay layers inserted after a special hut background)."""
        ins = H.instrs[i]; name = ins[2]; lo, hi = H.ins_ev[i]
        if name in ('CVmCall', 'CVmSync', 'CVmGenericMsg'):
            B.emit_instructions(src, i, i + 1)
            if name == 'CVmCall': B.out += b'\x00'
            res = H.ins_res[i] or []
            if (name == 'CVmCall' and res and isinstance(res[0][0], tuple) and res[0][1] == BG_HELPER and len(res) > 1
                    and res[1] and isinstance(res[1][0], tuple) and res[1][1] in BG_OVERLAYS):
                hname, j0, j1 = BG_OVERLAYS[res[1][1]]
                # fresh index map per copy: each OM_SetVarData message appends a load-array entry every time it
                # appears, so a map reused from an earlier copy would skip those entries (index drift -> bad heap)
                B.emit_instructions(Src(pm_srcs[hname].h, 'PM', hname), j0, j1)
                stats['bg_overlay_calls'] += 1
                return j1 - j0
            return 0
        if name != 'CVmSound':
            raise BuildError('staging instruction %s not handled' % name)
        # find the first object slot (effect) to splice PM's extra stream ref after the 6-byte words
        p_base = base_pos(H.d, ins[0]); s0 = p_base + 8
        if src.pad is not None and src.pad[1] == s0: s0 += 1
        se = slot_end(H, lo, hi, s0)
        typ, f = H.d[se], H.d[se + 1]
        P = se + 8
        k = next((k for k in range(lo, hi) if H.ev[k][1] >= P), hi)
        B._replay(src, lo, k, ins[0], P)
        if typ in (2, 4):
            eff = [x for x in H.ins_res[i] if x and x[0] != 'null'][:1]
            stream = None
            if eff and isinstance(eff[0][0], tuple):
                ecls, eoff, esize = eff[0]
                t = remap(src, (ecls, eoff, esize))
                if t[0] == 'PM' and t[1] in sound_pairs:
                    sc, so, ss = sound_pairs[t[1]]; stream = ('PM', tuple(sc), so, ss)
                elif t[0] == 'NEW':
                    raw = af_raw(eoff, esize); n = af_header(raw)[0]
                    refs = body_refs(raw[n:])
                    for (_, noff, nsize) in refs:
                        if is_naked_oor(af_raw(noff, nsize)):
                            stream = ('NEW', ('COptimizedObs', 1), noff, nsize); break
            if stream is None:
                B.ensure_pad(); B.out += b'\x00\x00'; stats['sound_null_stream'] += 1
                say('   note: %s instr %d CVmSound typ %d effect %s -> no stream ref' % (bl['name'], i, typ, eff))
            elif stream[0] == 'PM':
                B.object_slot(None, stream[1], stream[2], stream[3])
            else:
                B.object_slot(src, stream[1], stream[2], stream[3])
        B._replay(src, k, hi, P, ins[1])
        return 0

    # Staging from AF's official patch (when present): the patch re-staged stretches of restored scenes (camera moves,
    # billboard close-ups, transitions, shakes). Between two lines, when the patched script's staging differs and holds
    # only calls / syncs / sounds / messages, the patched instructions replace the unpatched ones there. Lines, voices
    # and stretches the patch left alone keep the unpatched script (camera fixes apply there).
    hooks, skip = {}, set()  # kept AF index -> patched staging emitted right before it; unpatched staging replaced
    Pp = af_patch_heap(bl['af'])
    if Pp is not None:
        srcP = Src(Pp, 'AF', bl['af'] + '@patch'); srcP.raw_repl = type_name_repl(bl['af'] + '@patch', Pp.d)
        useg = staging_segments(A, bl['keep']); pseg = staging_segments(Pp, range(Pp.count))
        msg_at = {}
        for i in bl['keep']:
            if A.instrs[i][2] == 'CVmMsg':
                msg_at.setdefault(struct.unpack_from('<I', A.d, base_pos(A.d, A.instrs[i][0]) + 4)[0] & 0xFFFFF, i)
        is_flag = lambda H, j: H.instrs[j][2] == 'CVmFlagOp'
        mids = [m for m in useg if m != 'end']

        def patched_stretch(mid, p_seg):
            """Plan one stretch: p_seg = patched instruction indices that correspond to the unpatched stretch."""
            # the patched stretch under the block's own rules: no replay-return path, jumps, labels or system writes;
            # branches only in parts that keep internal branches
            p_keep, skipping = [], False
            for j in p_seg:
                ins = Pp.instrs[j]; r = Pp.ins_res[j] or []
                if (ins[2] == 'CVmFlagOp' and r and r[0] and isinstance(r[0][0], tuple)
                        and r[0][1] == BL.REPLAY_BOOL):
                    skipping = True; continue
                if skipping:
                    if ins[2] == 'CVmJump': skipping = False
                    continue
                if ins[2] in ('CVmJump', 'CVmLabel', 'CVmRet'): continue
                if ins[2] == 'CVmGenericMsg' and ins[3] and 'AccessWrite' in str(ins[3][0]): continue
                if ins[2] == 'CVmFlagOp' and not bl.get('full_heap'): continue
                p_keep.append(j)
            if skipping:
                stats['patch_staging_kept_flow'] += 1; return
            u_all = useg[mid]
            p_flow = [j for j in p_keep if is_flag(Pp, j)]; p_non = [j for j in p_keep if not is_flag(Pp, j)]
            u_flow = [i for i in u_all if is_flag(A, i)]; u_non = [i for i in u_all if not is_flag(A, i)]
            if [stage_sig(A, i) for i in u_non] == [stage_sig(Pp, j) for j in p_non]: return
            # branches must form one contiguous block of the same size in both versions; patched staging before it is
            # emitted at the unpatched branch block, staging after it right before the line
            def contiguous(lst, flow):
                return not flow or lst[lst.index(flow[0]):lst.index(flow[0]) + len(flow)] == flow
            if (any(Pp.instrs[j][2] not in ('CVmCall', 'CVmSync', 'CVmSound', 'CVmGenericMsg') for j in p_non)
                    or len(p_flow) != len(u_flow) or not contiguous(p_keep, p_flow) or not contiguous(u_all, u_flow)):
                stats['patch_staging_kept_flow'] += 1; return
            if p_flow:
                k0 = p_keep.index(p_flow[0])
                hooks[u_flow[0]] = p_keep[:k0]; hooks[msg_at[mid]] = p_keep[k0 + len(p_flow):]
            else:
                hooks[msg_at[mid]] = p_non
            skip.update(u_non)

        for mid in mids[1:]:
            if useg[mid] is not None and pseg.get(mid) is not None:
                patched_stretch(mid, pseg[mid])
        # the stretch before the block's first line: anchor where the block starts. A block that starts at a line or
        # right after one owns the whole patched stretch; otherwise it starts at the patched twin of its first instr.
        if mids and useg[mids[0]] is not None and pseg.get(mids[0]) is not None:
            p_seg = pseg[mids[0]]; lo = bl['lo']
            if lo >= msg_at[mids[0]] or A.instrs[lo - 1][2] == 'CVmMsg':
                patched_stretch(mids[0], p_seg)
            else:
                want = stage_sig(A, lo)
                ks = [k for k, j in enumerate(p_seg) if stage_sig(Pp, j) == want]
                if ks: patched_stretch(mids[0], p_seg[ks[-1]:])
                else: stats['patch_staging_first_unanchored'] += 1

    flag_jobs = []           # (output instruction index, AF target instruction index or None for -1)
    out_of_keep = []         # output instruction index of each kept AF instruction (PM overlay calls are inserted)
    n_out = 0
    for i in bl['keep']:
        if i in skip:        # replaced by the patch's staging (emitted at the stretch's branch or line)
            out_of_keep.append(n_out); continue
        if i in hooks:
            for j in hooks[i]:
                n_out += 1 + emit_staging(Pp, srcP, j); stats['patch_staging_instrs'] += 1
            stats['patch_staging_segments'] += 1
        ins = A.instrs[i]; name = ins[2]
        out_i = n_out; out_of_keep.append(out_i); n_out += 1
        lo, hi = A.ins_ev[i]
        stats[name] += 1
        if name == 'CVmFlagOp':
            # kept only when the block wants internal branches; the target (last dword) is patched after layout
            t = struct.unpack_from('<I', A.d, ins[1] - 4)[0]
            flag_jobs.append((out_i, None if t == 0xFFFFFFFF else af_inv[t]))
            B.emit_instructions(srcA, i, i + 1)
            continue
        if name in ('CVmCall', 'CVmSync', 'CVmGenericMsg', 'CVmSound'):
            n_out += emit_staging(A, srcA, i)
        elif name == 'CVmMsg':
            p = base_pos(A.d, ins[0]); dw1, dw2 = struct.unpack_from('<II', A.d, p)
            if dw2 & 0x04000000: raise BuildError('CVmMsg %d flag 0x4000000' % i)
            text = ins[5][0][1].decode('cp932')
            patched = af_patch_msgs(bl['af']).get(dw2 & 0xFFFFF)
            if patched and patched[0].endswith(b'\x01') != ins[5][0][1].endswith(b'\x01'):
                # the patch split this line into timed pieces (text, sync, continuation line): the restored block keeps
                # the unpatched structure, so keep the complete unpatched line and its voice
                patched = None; stats['patch_restructured_kept'] += 1
            if patched and patched[0] != ins[5][0][1]:
                text = patched[0].decode('cp932'); stats['patch_text'] += 1
            ext = msg_ext(bl['af']).get(ins[5][0][0]) if dw2 & 0x00200000 else None
            if dw2 & 0x00200000 and ext is None: raise BuildError('CVmMsg %d: extension not parsed' % i)
            if ext and (ext['w'] & 0x68 or (ext['w'] & 3) == 3):
                raise BuildError('CVmMsg %d: unsupported extension %r' % (i, ext))
            res = A.ins_res[i]
            if not (res[0][0][0] == 'CMsgSelBox' and res[0][1] == MSGBOX_AF):
                raise BuildError('CVmMsg %d uses message box %s' % (i, res[0]))
            voices = []
            vs = [v for v in res[1:] if v and v[0] != 'null']
            pv = patched[1] if patched and len(patched[1]) == len(vs) else vs     # the patch's corrected takes
            if [x[1] for x in pv] != [x[1] for x in vs]: stats['patch_voice'] += 1
            for v, use in zip(vs, pv):  # main voice, then the extension's extra voices (multi-speaker lines)
                if v[0][0] != 'COptimizedObs' or use[0][0] != 'COptimizedObs': raise BuildError('voice class %s' % (v,))
                if use[1] not in vidx:
                    # ref flags come from the unpatched line's own voice ref (same class, same slot)
                    R = next((A.ev[k] for k in range(lo, hi) if A.ev[k][0] == 'ref' and A.ev[k][6] == v[1]), None)
                    vidx[use[1]] = len(tail); tail.append(('voice', use, R))
                voices.append(vidx[use[1]])
            if ext and ext['extra']: stats['extra_voice'] += ext['extra']
            toff = add_text(text)
            # second-language slot: PM's own multi-part lines never carry \x03 pauses there (3,200+ lines checked);
            # with pauses the engine renders that copy as a second, paused text column next to the normal box
            # (restored text is Japanese only; English-text players see this copy, pre-wrapped for the English layout)
            etext = prewrap(text.replace('\x03', ''))
            eoff = add_text(etext) if etext != text else toff
            roff = 0                    # ruby ('base:reading;...') lives in the item's second dword, as in PM
            if ext and ext['ruby']:
                roff = add_text(ext['ruby'].decode('cp932')); stats['ruby'] += 1
            B.emit_class('CVmMsg3', PM_SCHEMA, 'cdef')
            B.out += struct.pack('<IIHHBB', 0, dw2 & 0xFFC00000 & ~0x04000000, 1, 0, 2, len(voices))
            B.out += struct.pack('<III', toff, roff, 0) + struct.pack('<III', eoff, roff, 0)
            for vi in voices:
                B.out += struct.pack('<HHHHBB', vi, 0, 0, 0, 0, 0)
        else:
            raise BuildError('instruction %s not handled' % name)
    # closing CVmRet
    B.emit_class('CVmRet', PM_SCHEMA, 'cdef'); B.out += struct.pack('<II', 0xFFFFFFFF, 0)
    count = n_out + 1
    # tail: text table + object list
    B.out += struct.pack('<I', tlen[0]) + ''.join(table).encode('utf-16le')
    B.out += struct.pack('<H', len(tail))
    for r in tail:
        if r[0] == 'null': B.ensure_pad(); B.out += b'\x00\x00'   # the pad precedes the first object slot
        elif r[0] == 'msgbox': B.object_slot(srcA, MSGBOX_PM['cls'], MSGBOX_AF, MSGBOX_PM['size'] + 3)
        else:
            _, (cls, off, size), R = r; B.object_slot(srcA, cls, off, size, R)
    nmsg3 = stats['CVmMsg']
    for (_, pos, ob) in B.repl_used:
        stats['raw_repl'] += 1
        if ob[0] != 0xff and len(ob) == ob[0] + 1: say('   ansi->utf16 @%x %s' % (pos, ob[1:].decode('cp932', 'replace')))
    heap = bytearray(B.heap_bytes(struct.pack('<HH', 0x30, 1), 0x12, 0, count, nmsg3))
    g = CountHeap(bytes(heap), 2); g.parse()
    if g.count != count or not g.tail or g.tail['end'] != len(heap):
        raise BuildError('%s: generated heap does not re-parse exactly' % bl['name'])
    if len(g.cache) != B.next:     # load-array drift: later index references would hit the wrong class/object
        raise BuildError('%s: load array %d entries, builder allocated %d' % (bl['name'], len(g.cache), B.next))
    offs = []; o = 0
    for j in range(count):
        offs.append(o); o += mem_size(g, j)
    for j in range(count):
        p = base_pos(heap, g.instrs[j][0])
        nxt = offs[j + 1] if j + 1 < count else 0xFFFFFFFF
        flags = struct.unpack_from('<I', heap, p + 4)[0] & 0xFFF00000
        ident = 0 if j == count - 1 else next_id[0]
        if j != count - 1: next_id[0] += 1
        struct.pack_into('<II', heap, p, nxt, flags | ident)
    # branch targets: AF instruction -> first kept instruction at/after it (inside the block), else the closing CVmRet
    kept = bl['keep']
    for out_i, af_t in flag_jobs:
        if af_t is None:
            tgt = 0xFFFFFFFF
        else:
            later = [k for k, ai in enumerate(kept) if ai >= af_t]
            tgt = offs[out_of_keep[later[0]]] if later else offs[count - 1]
            stats['branch_internal' if later else 'branch_to_end'] += 1
        struct.pack_into('<I', heap, g.instrs[out_i][1] - 4, tgt)
    struct.pack_into('<I', heap, 12, o)
    heap = bytes(heap)
    g = CountHeap(heap, 2); g.parse()
    assert g.count == count and g.tail['end'] == len(heap) and g.size == o and g.extra == nmsg3
    bad = {ev[4] for ev in g.ev if ev[0] == 'cdef' and ev[4][0] in VM_CLASSES and ev[4][1] != PM_SCHEMA}
    assert not bad, bad
    return heap, dict(stats), o


# ---------------------------------------------------------------- PM heap patching
def patch_pm(name, inserts):
    """inserts: list of (p_ins, land, scene_enc). Returns new heap bytes."""
    P = pm_heaps[name]
    S = Slicer(P)
    call_cls = next(ev for ev in P.ev if ev[0] == 'cdef' and ev[4][0] == 'CVmCall')
    crsa_cls = next(ev for ev in P.ev if ev[0] == 'cdef' and ev[4][0] == 'CRsa')
    inserts = sorted(inserts, key=lambda t: t[0])
    pad_ev = P.ev[[e[0] for e in P.ev].index('pad')]
    pad0 = pad_ev[2]
    assert pad_ev[1] < P.instrs[inserts[0][0]][0], 'insertion before the owner-chain pad'
    S.out = bytearray(); S.map = {0: 0, 1: 1}; S.next = 2; S.pending = set(); S.pad_emitted = False
    ev_pos = 0; byte_pos = P.instrs[0][0]
    S.cur = byte_pos

    def cls_tag(ev):
        """Class tag for an inserted instruction: index if the class is already in the output, else define it here
        (pre-registered so the original definition later becomes an index reference)."""
        e = ev[3]
        if S.map.get(e) is not None:
            return struct.pack('<H', 0x8000 | S.map[e])
        S.map[e] = S.next; S.next += 1
        return P.d[ev[1]:ev[2]]

    for (p_ins, land, enc) in inserts:
        mid = P.ins_ev[p_ins][0]
        S._emit_events(P.ins_ev[0][0] if ev_pos == 0 else ev_pos, mid, P.instrs[p_ins][0])
        # unique nonzero id: saves (incl. the auto q-save) serialize each VM frame's current instruction by id,
        # and the engine refuses id 0 (AfxThrowNotSupportedException in FUN_00443e10)
        S.out += cls_tag(call_cls) + struct.pack('<II', 0, next_id[0]); next_id[0] += 1
        S.out += (cls_tag(crsa_cls) + struct.pack('<H', 0xC108) + struct.pack('<II', *enc) +
                  struct.pack('<H', pad0) + b'\x00' + struct.pack('<H', 0) + b'\x00')
        S.next += 1
        S.cur = P.instrs[p_ins][0]; ev_pos = mid
    S._emit_events(ev_pos, P.ins_ev[P.count - 1][1], P.instrs[P.count - 1][1])
    S.cur = P.tail['start']
    S._emit_events(P.tail['ev'][0], P.tail['ev'][1], P.tail['end'])
    n_ins = len(inserts)
    newP = bytearray(P.d[0:4] + struct.pack('<IIIII', 0xffff0000, P.version, P.size + S_CALL * n_ins,
                                            P.count + n_ins, P.extra) + bytes(S.out))
    old_off = [0] + [struct.unpack_from('<I', P.d, base_pos(P.d, P.instrs[i][0]))[0] for i in range(P.count - 1)]
    inv = {o: i for i, o in enumerate(old_off)}
    pins = [x[0] for x in inserts]

    def new_off(j):          # new offset of ORIGINAL instruction j
        return old_off[j] + S_CALL * sum(1 for p in pins if p <= j)

    def target(v):           # remap an old offset used as next/branch target (insertion at j captures it)
        if v == 0xFFFFFFFF: return v
        j = inv[v]
        return old_off[j] + S_CALL * sum(1 for p in pins if p < j)

    q0 = Heap(bytes(newP), 2); q0.parse()
    assert q0.count == P.count + n_ins
    # map new instruction index -> ('orig', j) or ('call', k)
    kinds = []; j = 0; k = 0
    while len(kinds) < q0.count:
        if k < n_ins and inserts[k][0] == j and (not kinds or kinds[-1] != ('call', k)):
            kinds.append(('call', k)); k += 1
        else:
            kinds.append(('orig', j)); j += 1
    for t, (kind, idx) in enumerate(kinds):
        pos = base_pos(newP, q0.instrs[t][0])
        if kind == 'call':
            p_k, land_k = inserts[idx][0], inserts[idx][1]
            same = [j for j in range(n_ins) if inserts[j][0] == p_k]
            if land_k == p_k and same[-1] != idx:
                # several calls inserted at one point (debug chains): fall through to the next inserted call
                nxt = old_off[p_k] + S_CALL * (sum(1 for q in pins if q < p_k) + same.index(idx) + 1)
                struct.pack_into('<I', newP, pos, nxt)
            else:
                struct.pack_into('<I', newP, pos, new_off(land_k))
        else:
            v = struct.unpack_from('<I', newP, pos)[0]
            struct.pack_into('<I', newP, pos, target(v))
            if q0.instrs[t][2] == 'CVmFlagOp':
                tpos = q0.instrs[t][1] - 4
                struct.pack_into('<I', newP, tpos, target(struct.unpack_from('<I', newP, tpos)[0]))
    newP = bytes(newP)
    q = Heap(newP, 2); q.parse()
    assert q.count == P.count + n_ins and q.tail and q.tail['end'] == len(newP)
    starts = set()
    o = 0
    # every next pointer must land on an instruction start of the new layout
    new_starts = [0]
    for t in range(q.count - 1):
        new_starts.append(None)
    # recompute starts from known sizes: original instr sizes unchanged, calls are S_CALL
    o = 0; start_list = []
    for t, (kind, idx) in enumerate(kinds):
        start_list.append(o)
        if kind == 'call': o += S_CALL
        else:
            jj = idx
            o += (old_off[jj + 1] if jj + 1 < P.count else P.size) - old_off[jj]
    assert o == P.size + S_CALL * n_ins
    sset = set(start_list)
    for t in range(q.count):
        v = struct.unpack_from('<I', newP, base_pos(newP, q.instrs[t][0]))[0]
        assert v == 0xFFFFFFFF or v in sset, ('dangling next', name, t, v)
    for i in range(P.count):
        t = kinds.index(('orig', i))
        na = [('pad',) if x and x[0] == 'pad' else x for x in P.ins_res[i]]
        nb = [('pad',) if x and x[0] == 'pad' else x for x in q.ins_res[t]]
        assert na == nb and P.instrs[i][2] == q.instrs[t][2], ('mismatch', name, i)
    assert [('pad',) if x and x[0] == 'pad' else x for x in P.tail['res']] == \
           [('pad',) if x and x[0] == 'pad' else x for x in q.tail['res']], 'tail refs changed'
    return newP


# ---------------------------------------------------------------- main
learn_nested()
by_heap = collections.defaultdict(list)
scene_objs = []
manifest = {}
for n in scenes:
    bl = BL.block(n) if n in BL.SITES else BL.range_block(n)
    if (DEBUG and n in BL.MARIMO_PARTS and bl['keep'] and af_heap(bl['af']).instrs[bl['keep'][0]][2] == 'CVmFlagOp'
            and n not in ('marimo_rung1', 'marimo_rung2', 'marimo_plus1', 'marimo_ending')):
        bl = dict(bl, keep=bl['keep'][1:]); say('   (debug) %s: route guard removed' % n)
    P = pm_heaps[bl['pm']]
    pad_count = P.ev[[e[0] for e in P.ev].index('pad')][3]
    heap, stats, msize = convert_block(bl, pad_count)
    if os.environ.get('DUMP_HEAPS'):
        os.makedirs(os.path.join(OUT, 'built'), exist_ok=True)
        open(os.path.join(OUT, 'built', n + '.bin'), 'wb').write(heap)
    obj = bytes([0x00, 0x05]) + CRSA_HDR9 + encrypt_block(heap)
    key = alloc_key()
    enc = (key, enc_size(len(obj)))
    scene_objs.append((key, obj))
    if n not in TEST_NAMES: by_heap[bl['pm']].append((bl['pm_before'] + 1, bl['land'], enc))
    if DEBUG: by_heap[DEBUG_HEAP].append((DEBUG_AT, DEBUG_AT, enc))
    manifest[n] = dict(pm=bl['pm'], insert_before=bl['pm_before'] + 1, land=bl['land'], af=bl['af'],
                       af_range=[bl['lo'], bl['hi']], instrs=len(bl['keep']) + 1, heap_bytes=len(heap), stats=stats,
                       scene_key=hex(key))
    say('%-9s AF %s [%d,%d) -> %d instrs, %d bytes heap, mem %d | %s | PM %s insert@%d land@%d' % (
        n, bl['af'], bl['lo'], bl['hi'], len(bl['keep']) + 1, len(heap), msize, stats, bl['pm'],
        bl['pm_before'] + 1, bl['land']))
pm_objs = []
for name, ins in by_heap.items():
    newP = patch_pm(name, ins)
    pos = int(name, 16) - 2
    hdr9 = read_at(PM_RIO, pos + 2, 9); assert hdr9 == CRSA_HDR9, hdr9.hex()
    pm_objs.append(((K + pos // 4) & 0xFFFFFFFF, bytes([0x00, 0x05]) + hdr9 + encrypt_block(newP)))
    say('patched %s: +%d calls' % (name, len(ins)))
imports = [(o['enc_off'], o['data']) for o in new_objs.values()]
assert all(d is not None for _, d in imports)
cls_count = collections.Counter(o['cls'] for o in new_objs.values())
say('imports: %d objects, %.1f MB  %s' % (len(imports), sum(len(d) for _, d in imports) / 1e6, dict(cls_count)))
from ruowrite import write_ruo
objs = pm_objs + scene_objs + imports
res = write_ruo(sys.argv[1], objs)
say('wrote %s %s, %d objects' % (sys.argv[1], res, len(objs)))
json.dump(manifest, open(os.path.join(OUT, 'build_manifest.json'), 'w'), indent=1)
c = collections.Counter((k, sz <= 200) for (k, _, sz, _) in nested_log)
say('nested refs: %s' % dict(c))
for e in nested_log:
    if e[0] == 'import' and e[2] <= 200: say('   small nested import (shared object?) %s size %d' % (e[1], e[2]))
say('CRimp sprite sets converted: %d' % len(crimp_done))
say('cameras zoomed x%s for imported AF pictures: %d' % (IMPORTED_IMAGE_ZOOM, _zoomed[0]))
say('CG shots raised to fill the screen: %d' % _floored[0])
say('billboard shots drawn as backgrounds: %d' % _bb2bg[0])
