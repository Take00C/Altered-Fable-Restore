"""Build the restoration patch (.ruo) for Muv-Luv photonmelodies: the cut Altered Fable H scenes (with the lead-in /
aftermath PM cut together with them) re-encoded as PM-native scripts and called from PM's route scripts.
usage: build_all.py <output .ruo path> [scene,scene,...]
Never removes or reorders PM instructions: each site gets ONE inserted CVmCall whose next pointer may bypass PM's
all-ages stand-in lines (landing before PM's own closing transition, the achievement call and the chapter jump)."""
import sys, os, json, struct, glob, collections, time, math, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from rsaparse import Heap
from builder import Builder, Src, BuildError
from heapwriter import Slicer
from crsa import encrypt_block
from objio import read_at, AF_RIO, PM_RIO, af_object, pm_object, af_header, enc_size, dec_size_raw, parts, K, sibling
from oorparse import read_stream
import entext
import cgcrop
import reencache          # disk cache of the picture re-encodes (same bytes; see reencache.py)
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
# objmap's vote picked these wrongly (lab-tools/out/research/helper-audit/CONFIRMED.json, each checked against the code of
# both helpers and PM's own ports of the same AF lines)
HELPER_OVERRIDE = {0x1afbc71: 0x672040dd,   # AF sprite helper -> PM successor (same 8 args; PM extras optional)
                   0x236d4ed: 0x676dcc71,   # AF screen-shake helper -> PM successor (drops AF's unused 3rd arg, see SHAKE_HELPER)
                   # AF colour flash layer (CLayerSimpleFlush, 6 args) -> PM's identical copy (same 12 instructions, PM
                   # calls it 16 times with 6 args; its own port of yuuhi_a's opening uses it with the same values).
                   # objmap's 2/4 tie had picked the 2-arg transition 27e9379d, which plays no flash.
                   0x318c15: 0xc6f08841,
                   # AF 8-arg camera -> PM's 8-arg port (42 PM calls, all 8 args): P5..P7 = camera position (OM_SetWorldCamera
                   # +0x0c..+0x14). objmap had picked the 6-arg 27e92e99, which never sets them, so the position reset to 0.
                   0x1c54b13f: 0x8a8b0e89}
SHAKE_HELPER = 0x236d4ed  # AF (posture, wait flag, unused): OM_AddPostureMomentum to the BG box, store the posture in var 319679,
                          # and when the 2nd arg is 0, CVmSync(var, b=16) = wait until the shake ends; the 3rd arg is never
                          # read. PM's 676dcc71 only sends the OM (PM's own AF-scene ports pass (posture, 1)), and no PM heap
                          # ever stores into PM's copy of the var (27b4f043), so a restored CVmSync on it returns at once.
                          # Restored waits therefore become timed waits of the shake's own length (SHAKE_WAIT_PM).
                          # In AF the shake starts at the call; in PM it starts only at the next apply (SHAKE_APPLY_PM).
SHAKE_VAR = 0x319679      # AF var holding the running shake (PM 27b4f043)
# PM's timed wait CVmSync(null, b=16, v ms) (its standard form, 4,036 in PM's heaps), copied with v = the length of the
# shake's posture: its longest curve, CMoveAcsOngen +0x48 when +0x44 != -1 (pm.exe FUN_005772c0 / FUN_004831e0). Used after
# a shake call whose wait flag is 0 and in place of a b=16 CVmSync on SHAKE_VAR right after a shake call. (AF's own form,
# storing the posture and syncing on it, would need the inline posture shared by two instructions, which PM never does.)
SHAKE_WAIT_PM = ('01ad9ce956', 29)
# PM's 0-ms apply 27e9379d(0, 0) (= 27e99af5(0,0,0,0,0) -> OM_BecomeCompositionToCurrent), emitted right after every
# restored shake call, before its timed wait. PM's CParseBgBox queues OM_AddPostureMomentum (receipt map 0x621570 ->
# FUN_004d7e00 -> FUN_00499d70, queue entry marker 0) and dispatches it only at the next BecomeCompositionToCurrent or
# ParseScreenTrigger (FUN_0049a120, marker 1; drain FUN_00498c20); CVmSync(null, b=16) is a pure timer. Without the apply a
# restored shake played only at the next background / camera apply, after its wait and possibly several lines. PM's own
# scripts apply after 502 of their 503 calls to 676dcc71 before any line or wait (the other ends a helper), 241 times with
# exactly this instruction (67 of them followed by a timed wait, e.g. 01ad9ce956 #28-29 itself). At every restored shake
# call nothing but shakes is queued since the previous apply, so this apply starts only the shake.
SHAKE_APPLY_PM = ('01ad9ce956', 28)
# CAMERA_KEEP. AF keeps ONE camera per screen across picture calls: its picture helpers 39b5f9d / c93a57 send no camera
# message, and the camera (box+0x8c8) is written only by the camera code (Vm60 FUN_100381d0 / FUN_10043a20). PM gives
# every picture call a new CComposition (FUN_004d7f70 -> FUN_004d61a0) whose constructor FUN_00493fc0 sets its camera
# to position 0, angles 0, zoom 720; FUN_004948e0 copies no camera from the shown one. So an AF shot whose picture call
# has no camera set of its own before the apply showed the KEPT camera in 2007 and PM's default view in PM (a billboard
# at depth D: the whole picture at 720/D inside black bars; a background: a wider view), and a shot whose first camera
# call is a move ran from the kept camera in 2007 but from (0, 0, 0, 720) in PM. The builder tracks AF's camera through
# each part (from AF's script before the part, through patch staging and lead-in replays) and, per picture call:
#  - no camera call before the closing apply: right after the picture call, an instant set to the kept camera in PM's
#    idiom (PM follows 9,379 of its 9,628 picture calls with a mode-1 camera call first): 27e92e99(x, y, rot, dist, 1,
#    0), or 8a8b0e89(x, y, rot, dist, 1, cx, cy, cz) when the kept camera has a 3D position;
#  - first camera call a move (not mode 1/3, not a 64-95 start) under an apply longer than 0 ms: right before the
#    move, a start store 8a8b0e89(x, y, rot, dist, 64, cx, cy, cz). Flag 0x800: FUN_004dc210 keeps it as the move's
#    start and FUN_004dfde0 writes it into the new composition's camera when the apply starts, so the move runs from
#    the kept camera while the picture fades in, as in 2007 (PM's own scripts: picture -> 64/65 start -> move -> apply,
#    192 times). A mode-1 set would not do: a second call on the same composition before the apply replaces its target
#    and takes the start from the composition's (default) camera again (FUN_004dc210). 8a8b0e89 rather than
#    27e92e99(.., 65, ..): the same messages as AF's own start stores (AsScreen + SetWorldCamera with 0x800; the
#    transition is not read on the 0x800 path); 27e92e99's 64-95 also sends SetCpsObPropertyEx4(17, 1.325), a lighting
#    slot AF never sends.
# PM's own ports of these AF shots do the same: 01ab8c3d66@5409-5410 follows the billboard with a mode-1 set to AF's
# kept camera (18, 81, -37, 1560), 01b8c7a482@4442-4444 sends AF's 64 start + 32 move on PM's copy at AF's values.
# The distance follows the shot's picture rule (camera loop below). Inserted instructions take ids from their own range,
# KEEP_ID_BASE, so the ids of the 1.1.0 additions (ADD_ID_BASE) and of lead-in replays (LEAD_ID_BASE) do not move; the
# inserts are numbered in build order, so a part's insert ids depend on how many inserts the parts before it got.
# Scope: the default build inserts in every part (65 inserts: 6 instant sets, 59 start stores), the same engine-proven
# fix in every scene, as the owner asked ("make sure it's not just her scenes facing the same issues"). The owner saw it
# in game in Mikoto's scene (KEEP_PARTS: the "whole picture inside black bars" lines, shots 31, 32, 56), first with the
# pre-exact zoom rule (2026-11-07 evening, "fixed"), then with the 2007 camera values (~21:15, "It's perfect").
# AFR_TEST keepmikoto inserts only in KEEP_PARTS (the build of those checks), nokeep in none. The analysis runs for
# every part and build_manifest.json lists every shot that needs the kept camera (camera_keep), with the action taken.
KEEP_PARTS = ('mikoto',)
CAM_SET_PM = ('004fd086ba', 10)       # PM CVmCall 27e92e99(0, 0, 0, 720, 1, 0): 6 plain int args, no extras
CAM8_PM = ('00ce1abaf2', 4000)        # PM CVmCall 8a8b0e89(2057, -154, 0, 2700, 1, 0, 760, 640): 8 plain int args
FADE_HELPER = 0x2f9782f   # AF screen effect (case, ms) -> PM 674ed45d
# Its case 25 (screen shock) points at two blank curves in PM's 674ed45d (no shake at all). Such calls become PM's own port of
# the effect: OM_AddPostureMomentumEx2 with its inline shake curve (500 ms), then CVmCall 27e99af5(0, 0, 0, 0, 200).
SHOCK_PM = ('01ad9ce956', 2148, 2150)
CAMERA_HELPER = 0xd13d87  # AF camera (x, y, rotation, distance, mode, ms) -> PM 27e92e99
# AF camera values that do not fit PM's copies of the pictures, by (AF heap, instruction): new (x, y, rot, dist, mode, ms).
# Marimo chapter: the ceiling billboard (helper 39b5f9d, depth 1000) at AF's distance 168 came out at 21% of the screen.
# On PM's billboard the picture size scales with distance (0.905 of the screen at 720); the 2007 game shows this shot as
# a close-up ~1.25x a full fill (measured from 2007 screenshots), hence 1020. AF's tilt is kept (rotation 45 -> 4 over
# the 600 ms transition); at this zoom the rotated picture still covers the screen. Matched directly to the 2007
# screenshots and checked live on 2026-10-11 (MODLOG); the picture is a CBg2d background, not a Cr6Ti CG, so the zoom
# rule below never applied to it, and the exact framing leaves this override as it is.
CAMERA_FIX = {('000054cf59', 402): (0, 0, 45, 1020, 1, 0), ('000054cf59', 406): (0, 0, 4, 1020, 0, 0)}
BG_HELPER = 0xc93a57      # AF background (obj, mode) -> PM 27e92633
BILLBOARD_HELPER = 0x39b5f9d                  # AF picture placed in 3D (billboard) -> PM 86697a41
CAMERA_HELPERS = (0xd13d87, 0x1c54b13f)       # AF camera calls (distance is the 4th argument) -> PM 27e92e99 / 8a8b0e89
CAMERA_HELPER8 = 0x1c54b13f                   # ... the 8-arg one: P5..P7 = camera position (OM_SetWorldCamera +0x0c..)
# Zoom rule. DEFAULT = THE EXACT 2007 FRAMING: every camera on a CG shot keeps the 2007 game's own values (x, y,
# rotation, distance), on imported AF pictures and on PM's copies alike; no fill floor (FILL_FLOOR applies only under
# the pre-exact rule: AFR_TEST zoom12 and the switches that imply it). Evidence:
#  - code, both engines (framing below): the camera screen is 1024x600 in both (AF's box body; PM's init heap 004fd064ca
#    sends OM_SetWorldSXY(512, 300) and body size 1024 x 600; PM frames its own 1280x750 widenings at 576 = exactly
#    1024x600; research/framing2/review-camera), 'dist' is a focal length in screen pixels, a picture at depth D is
#    drawn at dist / D, at canvas x Cr6Ti scale, the same for an import and its byte-identical PM copy;
#  - PM's own ports of these AF shots keep AF's exact values on the same pictures (01b8c7a482@4442-4444 = Mikoto shot
#    41, 01ab8c3d66@5409-5410 = yuuhi_a shot 0);
#  - the owner's in-game comparison with the 2007 game, 2026-11-07 ~21:15, scene tester AFR_TEST=exact (these values,
#    the kept camera in Mikoto's scene): Mikoto's scene framed exactly like 2007 ("It's perfect"); the pre-exact rule
#    (x1.2 on imports + FILL_FLOOR) had framed it 1.2-1.25x closer.
# The x1.2 came from an in-game measurement in October that matched PM's 16:9 remakes (1566 wide) rather than the 2007
# pictures, FILL_FLOOR from the wrong belief that PM's camera screen is 1280x720. Both stay as AFR_TEST zoom12 (the
# pre-exact rule: x1.2 on cameras framing an imported AF picture, AF's values on PM's copies, FILL_FLOOR), with nozoom
# (FILL_FLOOR only) and zoomall (zoom12 plus x1.2 on PM's copies) as its old variants; framerule: FRAME_RULE below.
IMPORTED_IMAGE_ZOOM = 1.0
_zoomed = [0]
# AFR_TEST bb2bg only. Patched staging whose 3D billboard shots become plain background shots, (AF heap + '@patch') ->
# restored part: the official patch re-staged Mikoto's scene as billboard close-ups (depth 1440); on 2026-10-11 those
# stayed a small whole picture inside black bars in PM, which was PM's default camera (a picture call starts at zoom
# 720, see CAMERA_KEEP), and the 1.1.0 release drew them as backgrounds. Converted: helper -> PM's background helper,
# args (picture, 2) (bb21: (picture, 21)), the following camera distances x 1000/depth (measured; the code-exact
# equivalent is x 720/depth, so these framed 1.39x tighter: the owner's 'zooms in super close', 2026-11-07), and the
# fill floor below over the scene. Her 8-arg cameras keep their 8 args (PM 8a8b0e89; P5..P7 are 0). bb2bg / bb21 imply
# the pre-exact zoom rule they were made with (zoom12).
BB_TO_BG = {'00004f4791@patch': 'mikoto'}
_bb2bg = [0]
# Pre-exact zoom rule only (AFR_TEST zoom12, nozoom, zoomall, bb2bg, bb21; inside bb2bg's converted range too): minimum
# camera distance on CG shots inside a restored range, AF heap -> (lo, hi, distance in AF units): whole CG at 720,
# centred, where the 2007 script frames it at 576 / 600 (Mikoto's backgrounds). Native billboards are not floored.
# Kept-camera inserts follow it too (keep_spec). By the 1024x600 model this framed 1.25x / 1.2x closer than 2007, which
# the owner saw in game (2026-11-07). FILL_FLOOR is this table under the pre-exact rule and {} otherwise (set below).
FILL_FLOOR_RULE = {'00004f4791': (1802, 2279, 720)}
_floored = [0]
_floor_of = {}          # heap key -> FILL_FLOOR range in that heap's indices (set by type_name_repl), for keep_spec

# ---------------------------------------------------------------- framing (camera distance on CG pictures)
# Both engines project a picture the same way (traced from pm.exe and the 2007 Vm60.dll; lab-tools/out/research/
# framing2: pm-projection, af-projection and their verifications). 'dist' (the camera's 4th argument, OM_SetWorldCamera-
# AsScreen +0x14) is a focal length in screen pixels; a picture at depth D is drawn at dist / D.
#  2D path (exclusive id bit 0x10 clear: the background helper's id 2): x_screen = centre + dist * ((u - cx) / Zp
#     - x / 512), Zp = 720 for a background (HumanIn2 z 0 with flag 0x200; PM FUN_004d87b0, AF FUN_1003ce10); the
#     rotation is not read; with id bit 0x01 clear the pans are clamped so the view stays inside the picture (PM
#     FUN_004dc4d0, AF FUN_1003efc0): black bars only where the picture is smaller than the view. PM adds a near plane:
#     Zp = max(Zp, clamp(trunc(dist/7 + 6/7), 180, 1440)) (FUN_00496bc0).
#  3D path (bit 0x10: the billboard helper's id 0x15): v = Rx(y) Ry(-x) Rz(rot) (corner + P - C) (4096 units per turn),
#     x_screen = centre + dist * vx / vz (PM FUN_0046f390 / FUN_0046db80, AF FUN_10066700 / FUN_10065850); no clamp.
# Drawn picture size: canvas w x h times the Cr6Ti scale (when > 0), W = ceil(w*s), half = floor(w*s/2), the same in
# both engines; an imported picture and its byte-identical PM copy are drawn alike.
# The 2007 screen is 1024x600 (centre 512,300: AF's CParseBgBox body, set by OM_SetWorldSXY(512,300)).
# FRAME_RULE (AFR_TEST framerule only, rejected) assumes PM's camera screen is 1280x720 (inferred from PM's 1566-wide
# remakes of 1302-wide CGs and the measured fill at 864). PM's own code and data say 1024x600 instead (see
# IMPORTED_IMAGE_ZOOM): on 1280x720, 1,752 of 2,749 camera states on PM's own Cr6Ti backgrounds would show black areas,
# 2 on 1024x600 (review-camera/pmown.txt); and the owner saw the 2007 values frame exactly like 2007 (2026-11-07).
# FRAME_RULE, every camera on a Cr6Ti CG picture (background or billboard, imported or PM copy, patch staging, lead-in
# replays, kept-camera inserts): dist x 720/600 shows the 2007 height (and 4.2% more width); where PM's view then still
# reaches past the picture (black bars), the distance is raised to the smallest value that covers PM's screen, at most
# to dist x 1280/1024 (the 2007 width: PM's view then lies inside the 2007 view). For a 2007 view inside the picture
# that limit always covers; where the 2007 view itself reaches past the picture (a few tilted billboards), the limit is
# used and PM shows no more of the outside than 2007 did. Pans and rotation are unchanged (the view centre on the
# picture does not depend on dist). Other pictures (PM's remastered CBg2d backgrounds) keep AF's values, as PM's own
# ports do; CAMERA_FIX stays an override.
SCR_AF, SCR_PM = (1024, 600), (1280, 720)
SCREEN_ZOOM = SCR_PM[1] / SCR_AF[1]        # 1.2 (2007 height)
FRAME_MAX = SCR_PM[0] / SCR_AF[0]          # 1.25 (2007 width): the most a camera is raised
_frame_log = collections.Counter()
_geom = {}


def pic_geom(img):
    """Drawn size (W, H, half W, half H) of the AF picture object img = (cls, off, size), Cr6Ti only, else None."""
    if not img or img[0][0] != 'Cr6Ti': return None
    if img[1] not in _geom:
        raw = read_at(AF_RIO, img[1] - 3, min(img[2] + 3, 8192))
        n = af_header(raw)[0]; body = raw[n:]; blen = img[2] + 3 - n
        w, h = struct.unpack_from('<HH', body, 12)
        s = next((struct.unpack_from('<f', body, p + 4)[0] for p in range(26, min(len(body) - 11, 8192))
                  if struct.unpack_from('<I', body, p)[0] <= blen
                  and p + 12 + ((struct.unpack_from('<I', body, p)[0] + 1) & ~1) + 2 == blen), None)
        if s is None: raise BuildError('picture %x: Cr6Ti scale not found' % img[1])
        if not s > 0: s = 1.0                   # FUN_004d87b0 applies the scale only when > 0
        _geom[img[1]] = (math.ceil(w * s), math.ceil(h * s), math.floor(w * s * 0.5), math.floor(h * s * 0.5))
    return _geom[img[1]]


def _rot3(x, y, rot):
    k = 2 * math.pi / 4096
    a, b, c = y * k, -x * k, rot * k
    sa, ca, sb, cb, sc, cc = math.sin(a), math.cos(a), math.sin(b), math.cos(b), math.sin(c), math.cos(c)
    return ((cc * cb, -sc * cb, sb), (sc * ca + cc * sb * sa, cc * ca - sc * sb * sa, -cb * sa),
            (sc * sa - cc * sb * ca, cc * sa + sc * sb * ca, cb * ca))


def covers(cam, dist, g, scr, pm):
    """True when the picture covers the whole screen scr for camera cam = (x, y, rot, cx, cy, cz) at distance dist.
    g: dict(W, H, hw, hh, px, py, path, depth) of the engine (depth: Zp on the 2D path, plane z on the 3D path)."""
    x, y, rot, cx, cy, cz = cam
    W, H, hw, hh = g['W'], g['H'], g['hw'], g['hh']
    if g['path'] == '2D':                      # clamped pans: only the view size matters
        D = g['depth'] - cz
        if pm: D = max(D, min(1440, max(180, int(dist * 0.14285715 + 0.85714287))))
        return scr[0] * D / dist <= W and scr[1] * D / dist <= H
    f = int(dist) if pm else dist
    R = _rot3(x, y, rot); sx, sy = scr[0] // 2, scr[1] // 2
    for (u, v) in ((0, 0), (scr[0], 0), (scr[0], scr[1]), (0, scr[1])):
        q = ((u - sx) / f, (v - sy) / f, 1.0)
        d = [R[0][k] * q[0] + R[1][k] * q[1] + R[2][k] * q[2] for k in range(3)]     # R^T q
        if d[2] <= 1e-9: return False
        t = (g['depth'] - cz) / d[2]
        if t < 64: return False                 # PM's near clip (vz <= 64)
        X = cx + t * d[0] - g['px']; Y = cy + t * d[1] - g['py']
        if not (-hw <= X <= W - hw and -hh <= Y <= H - hh): return False
    return True


def frame_rule(cam, dist, pic):
    """PM distance for the AF camera (x, y, rot, cx, cy, cz) at AF distance dist on picture pic (pic_info dict)."""
    if not pic or not pic.get('geo'): return dist, 'kept (not a Cr6Ti CG)'
    ga, gp = pic['af'], pic['pm']
    da, dp = ga['depth'] - cam[5], gp['depth'] - cam[5]
    if da <= 0 or dp <= 0: return dist, 'kept (camera behind the picture)'
    base = max(1, round(dist * SCREEN_ZOOM * dp / da))
    if covers(cam, base, gp, SCR_PM, True): return base, 'x1.2'
    af_ok = covers(cam, dist, ga, SCR_AF, False)
    top = max(base, round(dist * FRAME_MAX * dp / da))
    if not covers(cam, top, gp, SCR_PM, True):      # (only where the 2007 view itself reaches past the picture)
        return top, 'x%.2f (the 2007 width): %s' % (FRAME_MAX, 'the 2007 view reaches past the picture too; PM shows '
                                                    'no more of that than 2007' if not af_ok else 'bars left')
    lo, hi = base, top
    while hi - lo > 1:
        m = (lo + hi) // 2
        if covers(cam, m, gp, SCR_PM, True): hi = m
        else: lo = m
    return hi, 'x%.4f to cover the screen%s' % (hi / (dist * SCREEN_ZOOM * dp / da),
                                                 '' if af_ok else ' (2007 view past the picture edge)')


def frame_kind(note):
    if note == 'x1.2': return 'x1.2'
    if 'to cover' in note: return 'raised to cover' + (' (2007 past the edge)' if '2007' in note else '')
    if 'bars left' in note: return 'bars left'
    if 'reaches past' in note: return 'x1.25 (2007 view past the picture edge)'
    return note


# Near-plane correction (default; AFR_TEST nonearplane leaves it out; not yet seen in game). PM's 2D path
# (FUN_00496bc0, pm.c 118536-118566) uses D = max(Zp, clamp(trunc(dist/7 + 6/7), 180, 1440)):
# x_screen = s + dist * ((u - cx) / D - 16 x / 8192). AF has no near plane (D = Zp). The picture term is divided by D,
# the pan term is not, so above dist 7*Zp (5040 for a background) PM shows a wider view whose centre on the picture sits
# D/Zp further out (x = 16 x D / 8192). From dist 10074 up D is 1440, so the camera (x, y, dist) on D = Zp is reproduced
# by (x Zp/1440, y Zp/1440, dist 1440/Zp): the same view size, the view centre off only by the rounding of the pans to
# whole units (at most half a unit: 1440 x 16 / 8192 / 2 = 1.4 picture pixels). Refused (BuildError) when the pan clamp
# (FUN_004dc4d0 / AF FUN_1003efc0, on Zp) would move the new pans (checked on PM's 1024x600 screen and, as before, on
# 1280x720) or had already moved the camera being reproduced (1024x600). No other distance reproduces the view: below
# 10074 D grows faster than the distance. One camera in the parts needs it: marimo_chapter shot 18 (default build #523,
# #522 without the kept-camera inserts; its 2007 value (-110, 195, 0, 5592) gives D = 799 > Zp 720 -> (-55, 98, 0,
# 11184): the view centre on the picture 1.4 picture pixels lower than 2007 (y 195 x 720/1440 = 97.5 rounds to 98), the
# view size equal; the pre-exact rule's 6710 gave (-55, 98, 0, 13420); review-camera/s18.txt: without it the 2007
# close-up lies wholly outside PM's view). Applied to instant sets (mode 1) only, kept-camera inserts included; a move
# would bend its path. No other camera in the parts (moves and start stores included) lies above the near plane
# (research/framing2/exact-default/shots_exact_summary.txt).
_near_log = []
NEAR_SCREENS = ((1024, 600), (1280, 720))     # PM's camera screen by its code; the 1280x720 belief, kept as a 2nd check


def _pan_range(scr, d, zp, full, half, p, c):
    """16 x pan range that PM's / AF's 2D pan clamp (on Zp) leaves alone for one axis (screen side scr)."""
    edge = p - half - c
    return 8192.0 * scr / d + 8192.0 * edge / int(zp), -8192.0 * scr / d + 8192.0 * (edge + full) / int(zp)


def near_plane(new, pos, pic):
    """(x, y, rot, dist) for PM's 2D near plane (see above), or new unchanged."""
    x, y, rot, d = new
    if not (pic and pic.get('geo') and pic['pm']['path'] == '2D'): return new
    zp = pic['pm']['depth'] - pos[2]
    if not 0 < zp <= 1440 or min(1440, max(180, int(d * 0.14285715 + 0.85714287))) <= zp: return new
    x2, y2, d2 = round(x * zp / 1440), round(y * zp / 1440), round(d * 1440 / zp)
    if min(1440, max(180, int(d2 * 0.14285715 + 0.85714287))) != 1440: raise BuildError('near plane: %r' % (new,))
    W, H, hw, hh = pic['geo']; g = pic['pm']
    for scr in NEAR_SCREENS:            # the pan clamp (on Zp) must not move the new pans
        for a, s, full, half, p, c in ((x2, scr[0] // 2, W, hw, g['px'], pos[0]), (y2, scr[1] // 2, H, hh, g['py'], pos[1])):
            lo, hi = _pan_range(s, d2, zp, full, half, p, c)
            if not lo <= 16 * a <= hi: raise BuildError('near plane: the pan clamp would move %r' % (new,))
    scr = NEAR_SCREENS[0]               # ... nor have moved the camera reproduced (its view on D = Zp)
    for a, s, full, half, p, c in ((x, scr[0] // 2, W, hw, g['px'], pos[0]), (y, scr[1] // 2, H, hh, g['py'], pos[1])):
        lo, hi = _pan_range(s, d, zp, full, half, p, c)
        if not lo <= 16 * a <= hi: raise BuildError('near plane: the pan clamp moves the camera reproduced %r' % (new,))
    return [x2, y2, rot, d2]


# AF's two "special" hut backgrounds carry their foreground (tree trunk, canopy bed, plant, post) inside the background
# object. PM converted them to plain backgrounds and draws the foreground as three overlay layers right after every
# background call (helper 67fb353f + OM_SetVarData depth per layer box; the next background call replaces them).
# Restored shots get PM's own overlay instructions, copied from a PM scene showing the same background.
BG_OVERLAYS = {0x7696d25b: ('01b30e953a', 1856, 1862),     # night hut -> dc1cabef
               0x6deb814f: ('0192586282', 18, 24)}         # day hut -> c9258e0f
# F10 (C4): AF's layered hut 70e8902b (kasumi_h lines 226-264, the canopy bed in front; trunk and plant are off screen at
# every kasumi_h camera). PM shows its flat copy cb4f93ad (objmap) and, in its own scene with that copy, the copy's own
# overlay set: 0192586282 #2916 = 27e92633(cb4f93ad), #2917-#2922 = 3x 67fb353f + OM_SetVarData on the same three boxes
# with the same values as the day hut's #18-#23 (checked at startup). Added after 1.0.0: the copies take OVL ids.
BG_OVERLAYS_C4 = {0x70e8902b: ('0192586282', 2917, 2923)}
# F19 HUTDEPTH (opt-in: AFR_TEST hutdepth, a test build for the owner's in-game comparison). In meiya's hut shot (lines
# 265-282) the 8-argument cameras carry a camera position; 2007 draws the night hut's base layer at depth 18000 (layer
# loop, Vm60 FUN_1003ce10), PM its flat copy dc1cabef at rect z 5000, so under a moved camera the base is framed
# differently (origin cameras, every other hut shot, are equal: PM's b8 rule b8 = b8_af * rect_z / (8 * 720)). The test
# build gives meiya's call of AF 7696d25b (its only one) a copy of dc1cabef with rect z 18000 and b8 = 0.69 * 18000 /
# 5760 (0x400A0000), at HUTDEPTH_KEY; BG_OVERLAYS still follows it. Not the default: the overlays stay at PM's depth, so
# their parallax under these cameras is not 2007's (restore-audit FIXPLAN still_unproven), and base and overlays would
# no longer move together as PM designed them.
HUTDEPTH_PART, HUTDEPTH_AF, HUTDEPTH_PM, HUTDEPTH_PMSIZE = 'meiya', 0x7696d25b, 0xdc1cabef, 568409


def hutdepth_key_alloc(af_off, cls, size):
    """F19: the re-framed copy of PM dc1cabef for AF 7696d25b (one object at HUTDEPTH_KEY); else key_alloc."""
    if af_off != HUTDEPTH_AF: return key_alloc(af_off, cls, size)
    if HUTDEPTH_KEY not in hutdepth_objs:
        raw = bytearray(pm_object(HUTDEPTH_PM, HUTDEPTH_PMSIZE))           # 568412 bytes, header 00 06
        if not (len(raw) == HUTDEPTH_PMSIZE + 3 and raw[:2] == b'\x00\x06' and struct.unpack_from('<i', raw, 26)[0] == 5000
                and struct.unpack_from('<I', raw, 568402)[0] == 0x3F195555):   # 0.598958 = 0.69 * 5000 / 5760
            raise BuildError('hutdepth: PM dc1cabef layout changed')
        struct.pack_into('<i', raw, 26, 18000)                   # rect z = AF's base layer depth
        struct.pack_into('<I', raw, 568402, 0x400A0000)          # b8 = 0.69 * 18000 / (8 * 720) = 2.15625
        hutdepth_objs[HUTDEPTH_KEY] = bytes(raw)
    return HUTDEPTH_KEY, enc_size(len(hutdepth_objs[HUTDEPTH_KEY]))


# Restored parts whose first lines play over a CG that PM put on screen and the 2007 game did not (camera inventory,
# lab-tools/out/research/camera-inventory ranks 1-10: another picture, a PM crop of it, or PM's copy framed by cameras
# rewritten for the imported AF picture). Such a part starts by re-issuing AF's own last picture call before the part and
# the last camera call pair after it, so the 2007 picture and framing are on screen from its first line. The Kashiwagi
# lead-ins (3eab17 4957-4977) are left alone: there PM shows another background for the whole conversation, and its own
# lines between the restored ones would switch back and forth.
LEAD_IN = ('x_45d98b_7366', 'x_45d98b_7384', 'x_45d98b_7477', 'x_45d98b_7593', 'x_45d98b_7601', 'x_6b9fa1_2244')
CAMERA_UPDATE = 0xd14fbb       # AF camera apply (follows every 0xd13d87 call)
# F18 FADETIME (opt-in: AFR_TEST fadetime, a test build for the owner's in-game comparison). AF's apply d14fbb runs the
# transition types 15 / 16 / 22 / 24 as two blocking blits of fixed length (AF d14fbb: 15 = CFadeMulHorz 500 +
# CFadeOverStretchAnti ms; 16 = CFadeQubeStretchAnti 400 + 500; 22 = CFadeOverStretchAnti 360 + 400, ms ignored; 24 = two
# CFadeOverStretchAnti of min(ms, 500)); PM's 27e99af5 runs v = min(ms / 2, 500) per phase for 22 / 24 (ms / 2 for 15 /
# 16), so these transitions came out much shorter. The rewrite gives PM's apply the ms that makes its total equal 2007's.
# Not the default: by the two helpers' own code only type 24 becomes equal per phase; 15 / 16 / 22 become equal in total
# but PM splits them evenly (22: 380 + 380 against 360 + 400), and the sequential running of PM's two phases is not
# proven (restore-audit FIXPLAN still_unproven; impl/I4 F18 entry). The LEAD_IN / ENTRY 0-ms applies set their own
# raw_repl entry and restore it, so they still win.
FADE_TIME = {15: lambda ms: 500 + ms, 16: lambda ms: 900, 22: lambda ms: 760, 24: lambda ms: 2 * min(ms, 500)}
_fadetime_log = {}             # (heap key, index) -> (type, AF ms, new ms) of every apply rewritten (F18)


def lead_in(A, bl):
    """AF instruction indices to replay at the start of a part: the last picture call before it, then the last camera
    call + apply pair between that call and the part."""
    lo = min(bl['lo'], bl['keep'][0])

    def tgt(i):
        r = A.ins_res[i] or []
        return r[0][1] if A.instrs[i][2] == 'CVmCall' and r and r[0] and isinstance(r[0][0], tuple) else None
    pic = next((i for i in range(lo - 1, -1, -1) if tgt(i) in (BG_HELPER, BILLBOARD_HELPER)), None)
    if pic is None: raise BuildError('lead-in: no picture before %s' % bl['name'])
    cams = [i for i in range(pic + 1, lo) if tgt(i) == CAMERA_HELPER and i + 1 < lo and tgt(i + 1) == CAMERA_UPDATE]
    return [pic] + ([cams[-1], cams[-1] + 1] if cams else [])


# DEFAULT BUILD (no AFR_TEST) = the exact 2007 framing + the kept 2007 camera in every part + PM's near plane corrected:
#  - every camera on a CG shot keeps the 2007 game's own values (IMPORTED_IMAGE_ZOOM 1.0, no FILL_FLOOR; zoom rule
#    above), PM's own CBg2d backgrounds keep AF's values as before, CAMERA_FIX (the Marimo ceiling, matched directly to
#    2007 screenshots on 2026-10-11) stays;
#  - CAMERA_KEEP in every part (65 inserts: 6 instant sets, 59 start stores);
#  - near_plane (marimo_chapter shot 18, AF 5592 -> (-55, 98, 0, 11184));
#  - Mikoto's patched billboards stay PM billboards (86697a41, 3D path); billboard pictures over BB_SHRINK_LIMIT bytes
#    were re-encoded smaller (in every build the owner checked); since F22 (bbexact) the default keeps their exact AF
#    bytes (by pm.exe's code no path depends on a picture's byte size, research/billboard-re).
# Evidence: both engines' code (framing, CAMERA_KEEP and near_plane above; research/framing2) and the owner's in-game
# comparison with the 2007 game on 2026-11-07 ~21:15: the scene tester's AFR_TEST=exact (this framing, the kept camera in
# Mikoto's scene only; as a full build sha1 ae69796c) framed Mikoto's scene exactly like 2007 ("It's perfect"), where
# the pre-exact rule (zoom12) had framed it 1.2-1.25x closer. The kept camera in the other scenes and the near-plane
# correction are the same engine-proven fixes (PM's own ports do the first), checked by code and review, not yet seen in
# game. The default is byte-identical to AFR_TEST=exact,keepall,nearplane on the builder before this change.
# Test builds only (env AFR_TEST, comma-separated), for comparing in game with the scene tester:
#   zoom12      the pre-exact zoom rule: x1.2 on cameras framing an imported AF picture, FILL_FLOOR on Mikoto's range
#               (whole CG at 720, centred). zoom12,keepmikoto,nonearplane = the default of 2026-11-07 evening (v11,
#               sha1 f85c4b64: the owner's "Mikoto fixed" check); zoom12,nokeep,nonearplane = the build the owner
#               checked that afternoon (88ca03a8)
#   keepmikoto  CAMERA_KEEP only in KEEP_PARTS (Mikoto: 3 inserts)
#   nokeep      no CAMERA_KEEP inserts at all
#   nonearplane no near-plane correction: marimo_chapter shot 18 keeps its 2007 value, which PM shows as a wider view
#               whose centre lies further out (the 2007 close-up wholly outside it)
#   nozoom      the pre-exact rule without the x1.2 (FILL_FLOOR only), as before: nozoom,keepmikoto,nonearplane = the
#               nozoom build of 2026-11-07 (24a706c0)
#   zoomall     zoom12 plus the x1.2 on PM's copies (every Cr6Ti CG shot), as before: zoomall,keepmikoto,nonearplane =
#               the zoomall build of 2026-11-07 (c671c53e). Its question (yuuhi_a shots 61 / 62: the same 2007 camera on
#               a PM copy and on an import) is settled: an import and its PM copy are drawn alike
#   framerule   FRAME_RULE (x1.2 on every CG camera, raised to cover a 1280x720 screen, no FILL_FLOOR) in place of the
#               zoom rule; rejected (PM's camera screen is 1024x600). framerule,nonearplane = the framerule,keepall build
#               of 2026-11-07 (d3b564df)
#   bb2bg       the 1.1.0 release form of Mikoto's scene: BB_TO_BG turns her patched billboards into background calls,
#               with the 1.1.0 camera rewrites in that range (distance x 1000/depth, FILL_FLOOR, x1.2 on imported
#               pictures); implies the pre-exact rule it was made with (zoom12); no re-encode unless bbsmall is given
#               too. bb2bg,nokeep,nonearplane = the 1.1.0 release (sha1 bbc1ac7a)
#   bb21        = bb2bg, keeping AF's 2nd argument (21): 27e92633(picture, 21), so PM's background helper draws through
#               its 3D path with the cameras' tilt; with code 2 the 2D path ignores it (helper-audit CONFIRMED finding
#               5). bb21,keepmikoto,nonearplane = the bb21 build of 2026-11-07 (b6b14ba7)
#   bbsmall     with bb2bg: re-encode the oversized billboard pictures anyway (default build: always on)
# Old names, still accepted and kept in AFR_TEST as given (the scene tester checks its build summary,
# ','.join(sorted(AFR_TEST)), against the version it chose); no-ops now, each with the switches that rebuild its old build:
#   exact       no-op (the default framing). Its build of 2026-11-07 (the owner-confirmed one) = keepmikoto,nonearplane
#   keepall     no-op (the default keeps the camera in every part). Old keepall (0c38039f) = zoom12,nonearplane
#   nearplane   no-op (the default corrects the near plane). Old nearplane (850d1515) = zoom12,keepmikoto
#   bbnative    no-op: native billboards are the default build
#   cam8        no-op: AF's 8-arg camera -> PM 8a8b0e89 is the default build
#   hdr4        = nozoom: its header part (00 04) is proven to change nothing (research/billboard-re SYNTHESIS.json)
# Restore-audit fixes (lab-tools/out/research/restore-audit: deep/FIXPLAN.json F01-F23, implementation record
# impl/LEDGER.json): the 2007 game with its official update, exactly. A default-on fix is guarded by fix_on('<tok>') and
# left out by AFR_TEST no<tok>, which rebuilds the build from before that fix; an opt-in fix (a test build for the
# owner's in-game comparison, until the engine code proves it equals 2007) by '<tok>' in AFR_TEST. AFR_TEST v11 leaves
# every fix out: it rebuilds lab-tools/out/v11.ruo1 byte for byte (sha1 ea97eb32; with afhook.pkg b03eb13f), and with
# 'v11' added the older switch sets rebuild their old builds (v11,zoom12,keepmikoto,nonearplane = f85c4b64,
# v11,bb2bg,nokeep,nonearplane = bbc1ac7a, v11,nokeep = ba6e47a3, v11,nonearplane = 8321ad2d).
#   default-on, AFR_TEST off-switch: noc10 F01, not3d F02, noc3 F03, noc7 F04, noc5 F05, nopmsnd F06, noland F07,
#     noc11 F08, noc15 F09, noc4 F10, noc6 F11, nofixwin F12, noexcl F13, noc2 F14, noentry F15, noc8 F16, noc1 F17,
#     nobbexact / nosprexact F22, nokashi F23 (the owner's decision for exactness: F22 and F23 are default-on);
#     the review fixes: noretid F24, nokashipm F25, nowinshow F26
#   opt-in, AFR_TEST token: fadetime F18, hutdepth F19, pmexit F21 (the engine code does not prove them equal to 2007;
#     the scene tester's 'Test: extra fixes' Version builds them together)
#   F20 (posture) is dropped, no token: PM's CrelicUnitedGameProject settings dword [0x12] (+0x48, pm.exe FUN_00433230 ->
#     DAT_006c3e94) reads 100 in photonmelodies11.rio (restore-audit impl/I4 probe p3_project.py), and with 100 PM's
#     HumanIn (FUN_0048c290) keeps a posture set before the sprite call (FUN_00492900 marks it with bit 4), so AF's order
#     (posture first) already shows the 2007 posture.
FIX_OFF = {'noc10', 'not3d', 'noc3', 'noc7', 'noc5', 'nopmsnd', 'noland', 'noc11', 'noc15', 'noc4', 'noc6',
           'nofixwin', 'noexcl', 'noc2', 'noentry', 'noc8', 'noc1', 'nobbexact', 'nosprexact', 'nokashi', 'noretid',
           'nokashipm', 'nowinshow'}
FIX_OPTIN = {'fadetime', 'hutdepth', 'pmexit'}
AFR_TEST = set(filter(None, os.environ.get('AFR_TEST', '').split(',')))
assert AFR_TEST <= {'zoom12', 'keepmikoto', 'nokeep', 'nonearplane', 'nozoom', 'zoomall', 'framerule', 'bb2bg', 'bb21',
                    'bbsmall', 'exact', 'keepall', 'nearplane', 'bbnative', 'cam8', 'hdr4'} | FIX_OFF | FIX_OPTIN | {'v11'}, \
    AFR_TEST
assert not ('v11' in AFR_TEST and AFR_TEST & FIX_OPTIN), 'AFR_TEST v11 rebuilds the audited build (no opt-in fix with it)'


def fix_on(tok):
    """A default-on restore-audit fix is in this build: not left out by AFR_TEST no<tok>, nor by v11."""
    return ('no' + tok) not in AFR_TEST and 'v11' not in AFR_TEST

NO_ZOOM = bool(AFR_TEST & {'nozoom', 'hdr4'})
assert not ('exact' in AFR_TEST and AFR_TEST & {'zoom12', 'nozoom', 'hdr4', 'zoomall', 'framerule', 'bb2bg', 'bb21'}), \
    'AFR_TEST exact (the 2007 values, the default) excludes zoom12, nozoom (hdr4), zoomall, framerule and bb2bg / bb21'
assert not (NO_ZOOM and AFR_TEST & {'zoom12', 'zoomall'}), 'AFR_TEST nozoom (hdr4) excludes zoom12 and zoomall (x1.2)'
assert not ('framerule' in AFR_TEST and AFR_TEST & {'zoom12', 'nozoom', 'hdr4', 'zoomall'}), \
    'AFR_TEST framerule replaces the zoom rule that zoom12 / nozoom (hdr4) / zoomall vary'
assert len(AFR_TEST & {'keepall', 'keepmikoto', 'nokeep'}) <= 1, \
    'AFR_TEST keepall, keepmikoto and nokeep exclude each other'
assert not {'nearplane', 'nonearplane'} <= AFR_TEST, 'AFR_TEST nearplane and nonearplane exclude each other'
BB_CONVERT = bool(AFR_TEST & {'bb2bg', 'bb21'})
assert not (BB_CONVERT and 'bbnative' in AFR_TEST), 'AFR_TEST bbnative and bb2bg / bb21 exclude each other'
BB_KEEP21 = 'bb21' in AFR_TEST
ZOOM_ALL = 'zoomall' in AFR_TEST
PRE_EXACT = bool(AFR_TEST & {'zoom12', 'nozoom', 'hdr4', 'zoomall', 'bb2bg', 'bb21'})   # the pre-exact zoom rule
OLD_ZOOM = 'framerule' not in AFR_TEST       # the zoom rule (exact, or pre-exact), not FRAME_RULE
CAMERA_KEEP = 'nokeep' not in AFR_TEST
CAMERA_KEEP_ALL = 'keepmikoto' not in AFR_TEST
NEAR_PLANE_ON = 'nonearplane' not in AFR_TEST
# F22 (C13) bbexact: the 13 oversized billboard pictures keep their exact AF bytes (2007's), no re-encode; AFR_TEST
# nobbexact (or v11) re-encodes them as before, bbsmall re-encodes them in any build. pm.exe reads a picture's size from its
# ruo entry and no path depends on the byte size below 8 MiB (research/billboard-re); 1.0.0 shipped Yuuhi B's 2.14 MB
# billboards unchanged and the owner checked them.
BB_SHRINK_LIMIT = 2000000 if ((not BB_CONVERT and not fix_on('bbexact')) or 'bbsmall' in AFR_TEST) else None
BB_SHRINK = set()             # AF picture offsets to re-encode (filled before the parts are converted)
IMPORTED_IMAGE_ZOOM = 1.2 if PRE_EXACT and not NO_ZOOM else 1.0
FILL_FLOOR = FILL_FLOOR_RULE if PRE_EXACT else {}
RULE_NAME = 'FRAME_RULE (AFR_TEST framerule)' if not OLD_ZOOM else 'pre-exact rule' if PRE_EXACT else 'exact'


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


def _check_pm_templates():
    """The PM instructions copied into restored parts are what their constants say."""
    def tgt(H, j):
        r = H.ins_res[j][0] if H.ins_res[j] else None
        return r[1] if r and isinstance(r[0], tuple) else r
    h, j0, j1 = SHOCK_PM; H = pm_srcs[h].h
    if not (j1 - j0 == 2 and H.instrs[j0][2] == 'CVmGenericMsg' and tgt(H, j0) == 0x4547d
            and H.instrs[j0 + 1][2] == 'CVmCall' and tgt(H, j0 + 1) == 0x27e99af5):
        raise BuildError('SHOCK_PM %s %d-%d is not Ex2 + 27e99af5' % SHOCK_PM)
    h, j = SHAKE_WAIT_PM; H = pm_srcs[h].h
    if not (H.instrs[j][2] == 'CVmSync' and tgt(H, j) == ('null',) and H.d[H.instrs[j][1] - 5] == 16):
        raise BuildError('SHAKE_WAIT_PM %s %d is not CVmSync(null, b=16)' % SHAKE_WAIT_PM)
    h, j = SHAKE_APPLY_PM; H = pm_srcs[h].h      # ... ends in 2 args (int 0, int 0) and no extras: 02 00 | 2x 02000000 | 00
    if not (H.instrs[j][2] == 'CVmCall' and tgt(H, j) == 0x27e9379d
            and H.d[H.instrs[j][1] - 11:H.instrs[j][1]] == bytes.fromhex('0200020000000200000000')):
        raise BuildError('SHAKE_APPLY_PM %s %d is not CVmCall 27e9379d(0, 0)' % SHAKE_APPLY_PM)
    for (h, j), helper, n in ((CAM_SET_PM, 0x27e92e99, 6), (CAM8_PM, 0x8a8b0e89, 8)):
        H = pm_srcs[h].h; e = H.instrs[j][1]          # ... n (u16) | n plain int args | 00 (no extras)
        if not (H.instrs[j][2] == 'CVmCall' and tgt(H, j) == helper and H.d[e - 1] == 0
                and struct.unpack_from('<H', H.d, e - 3 - 4 * n)[0] == n
                and all(struct.unpack_from('<I', H.d, e - 1 - 4 * (n - k))[0] & 3 == 2 for k in range(n))):
            raise BuildError('camera template %s %d is not CVmCall %x with %d plain int args' % (h, j, helper, n))


_check_pm_templates()

# Optional English text (the player's own afhook.pkg fan translation, read in place; see entext.py). AFR_EN_PKG = path,
# '' = off; unset = <Altered Fable folder>/afhook.pkg when present. Without it restored lines carry Japanese in both
# text slots exactly as before; with it, translated lines get English in PM's English slot (text language setting).
_p = os.environ.get('AFR_EN_PKG')
EN_PKG = sibling(os.path.join(os.path.dirname(AF_RIO), ''), 'afhook.pkg') if _p is None else _p
EN_DATA = entext.load_pkg(EN_PKG) if EN_PKG and os.path.isfile(EN_PKG) else {}
EN_NAMES = entext.pm_name_map([s_.h for s_ in pm_srcs.values()]) if EN_DATA else {}
say('English text package: %s' % ('%d translated lines' % len(EN_DATA) if EN_DATA else 'not used'))


def mapped(off):
    m = objmap.get(str(off))
    return m['pm'] if m and m['votes'] / m['total'] >= 0.5 else None


def pm_cls(off):
    """(class, offset, size) of the PM object off, from the PM heap that references it (restore-audit helper)."""
    if off not in templates: raise BuildError('PM object %x is in no PM heap' % off)
    s_, k_ = templates[off]; ev = s_.h.ev[k_]
    return ev[5], ev[6], ev[7]


_ident = {}


def _differ_at_most(a, b, limit, chunk=1 << 16):
    """True when the equal-length byte strings a and b differ in at most `limit` positions (compared chunk by chunk,
    stopping as soon as more differ: the same answer as counting every differing byte)."""
    n = 0
    for o in range(0, len(a), chunk):
        x = a[o:o + chunk]; y = b[o:o + chunk]
        if x != y:
            n += sum(1 for p, q in zip(x, y) if p != q)
            if n > limit: return False
    return True


def image_identical(af_off, af_size, pm_off):
    """AF and PM images hold the same picture: same body length, <= 16 differing bytes (version/metadata)."""
    key = (af_off, pm_off)
    if key not in _ident:
        m = objmap[str(af_off)]
        s, body, raw, _ = af_object(af_off, af_size)
        pr = pm_object(pm_off, m['pmc'][2])
        ok = False
        if len(pr) >= len(body) and len(pr) - len(body) <= 4:
            ok = _differ_at_most(body, pr[len(pr) - len(body):], 16)
        _ident[key] = ok
    return _ident[key]


# ---------------------------------------------------------------- imports
new_objs = {}        # af_off -> dict(cls, enc_off, data)
next_x = [NEW_KEY_BASE]


def alloc_key(lead=False):
    """Next key of the import mode lead: False = main range, True = LEAD_IN copies, or a restore-audit mode name."""
    c = {'entry': entry_x, 'exit': exit_x, 'x45': x45_x, 'kashi': kashi_x, 'spr': spr_x}.get(lead, lead_x if lead else next_x)
    x = c[0]; c[0] += 0x10
    return (K + x) & 0xFFFFFFFF


# LEAD_IN imports: own copies in their own key range, so every key 1.0.0 allocated stays the same (resumed sessions
# refer to objects by key). Range NEW_KEY_BASE + 0x7000000 .. + 0x8000000: above every main-range key, below PM's.
new_objs_lead = {}
lead_x = [NEW_KEY_BASE + 0x07000000]
_lead_mode = [False]           # import mode: False (main), True (LEAD_IN) or a restore-audit mode name (below)
# Restore-audit fixes (FIXPLAN key_ranges): imports a fix makes go to a key range of its own, one dict per mode, so no
# main / LEAD key moves and each fix toggles alone. Offsets above NEW_KEY_BASE: LEAD 0x07000000 (4 used), SPR
# 0x07400000 (F22 sprexact), X45 0x07800000 (F16), KASHI 0x07900000 (F23), OVLPIX 0x07A00000 (reserved), ENTRY
# 0x07C00000 (F15), EXIT 0x07D00000 (F21), HUTDEPTH 0x07E00000 (F19, one object), SCENE 0x07F00000 (F17's scene object) and
# 0x07F00010 (F23's start scene).
spr_x, x45_x, kashi_x = [NEW_KEY_BASE + 0x07400000], [NEW_KEY_BASE + 0x07800000], [NEW_KEY_BASE + 0x07900000]
entry_x, exit_x = [NEW_KEY_BASE + 0x07C00000], [NEW_KEY_BASE + 0x07D00000]
HUTDEPTH_KEY = (K + NEW_KEY_BASE + 0x07E00000) & 0xFFFFFFFF
YCONT_SCENE_KEY = (K + NEW_KEY_BASE + 0x07F00000) & 0xFFFFFFFF
KASHI_SCENE_KEY = (K + NEW_KEY_BASE + 0x07F00010) & 0xFFFFFFFF     # F23: the Kashiwagi conversation's start scene
new_objs_spr, new_objs_x45, new_objs_kashi, new_objs_entry, new_objs_exit = {}, {}, {}, {}, {}
hutdepth_objs = {}             # HUTDEPTH_KEY -> object bytes (F19)
KEY_RANGES = (('main', 0x78000000, 0x7F000000), ('LEAD', 0x7F000000, 0x7F400000), ('SPR', 0x7F400000, 0x7F800000),
              ('X45', 0x7F800000, 0x7F900000), ('KASHI', 0x7F900000, 0x7FA00000), ('ENTRY', 0x7FC00000, 0x7FD00000),
              ('EXIT', 0x7FD00000, 0x7FE00000), ('HUTDEPTH', 0x7FE00000, 0x7FE00010),
              ('SCENE', 0x7FF00000, 0x80000000))


def af_raw(off, size):
    return read_at(AF_RIO, off - 3, size + 3)


def oor_end(raw):
    """End of the naked OOR sound stream raw (pages from offset 0, at least 2, the last one an end page), or None.
    F05 (C5): AF's Marimo BGM stream 65b7add7 has 42 bytes after its end page; the stream is the bytes up to that end
    (fewer than 64 trailing bytes accepted), so it is imported as a stream (it was stored with an object header that PM
    cannot parse, and its CVmSound got no stream ref: a silent song)."""
    try:
        pages, end = read_stream(raw, 0)
        if len(pages) >= 2 and pages[-1]['flags'] & 1 and (end == len(raw) or (fix_on('c5') and len(raw) - end < 64)):
            return end
    except Exception:
        pass
    return None


def is_naked_oor(raw):
    return oor_end(raw) is not None


_oor_tail = set()        # F05: AF streams accepted only through the trailing-bytes rule


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
        if m['af'][0] in IMG_CLASSES and image_identical(off, size, pm) or (
                m['af'][0] not in IMG_CLASSES and _lead_mode[0] != 'spr'):     # F22 sprexact: AF's own frames / pieces
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
bb_shrunk = []


def key_alloc(af_off, cls, size):
    if (_lead_mode[0] != 'spr' and cls and cls[0] == 'CRmt' and fix_on('sprexact') and mapped(af_off) is not None):
        # F22 sprexact: an AF sprite with a PM pair (see remap) and everything nested in it go to the SPR key range
        saved = _lead_mode[0]; _lead_mode[0] = 'spr'
        try:
            return key_alloc(af_off, cls, size)
        finally:
            _lead_mode[0] = saved
    lead = _lead_mode[0]
    new_objs = {'entry': new_objs_entry, 'exit': new_objs_exit, 'x45': new_objs_x45, 'kashi': new_objs_kashi,
                'spr': new_objs_spr}.get(lead, new_objs_lead if lead else globals()['new_objs'])
    if lead == 'kashi' and af_off in globals()['new_objs']:      # F23: an object the main range already holds
        new_objs = globals()['new_objs']
    if af_off not in new_objs:
        raw = af_raw(af_off, size)
        if (cls and cls[0] == 'COptimizedObs') or (cls is None and is_naked_oor(raw)):
            e = oor_end(raw)            # F05: a stream with trailing bytes is stored up to its end page
            data = raw[:e] if e is not None else raw; cname = 'COptimizedObs'
            if e is not None and e != len(raw): _oor_tail.add(af_off)
        else:
            n, schema, mode, extra = af_header(raw)
            if mode not in (0,):
                raise BuildError('import %x: AF header mode %d not handled' % (af_off, mode))
            body = bytearray(raw[n:])
            cname = cls[0] if cls else '?'
            new_objs[af_off] = dict(cls=cname, enc_off=alloc_key(lead), data=None)    # reserve (cycles)
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
            if cname == 'Cr6Ti' and af_off in BB_SHRINK:          # oversized billboard picture (BB_SHRINK_LIMIT)
                small, used = reencache.shrink(bytes(body), BB_SHRINK_LIMIT)
                if small is None: raise BuildError('bbsmall: %x does not fit' % af_off)
                body = bytearray(small); bb_shrunk.append((hex(af_off), len(raw), len(small), used))
            data = bytes([0x00, schema & 0xff]) + bytes(body)
            new_objs[af_off]['data'] = data
            return new_objs[af_off]['enc_off'], enc_size(len(data))
        new_objs[af_off] = dict(cls=cname, enc_off=alloc_key(lead), data=data)
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
        if off == BILLBOARD_HELPER and src.name in BB_TO_BG and BB_CONVERT: return ('PM', mapped(BG_HELPER))
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
    # F22 (C13) sprexact: an AF sprite (CRmt) with a PM pair is imported instead: PM's copies are lossy re-encodes of the
    # same sprite (restore-audit verify-sprites f2_pixels.json: the 32 Marimo pairs, same mip levels and sizes, alpha
    # exact, colour off by 2-8/255), 2007 shows the AF bytes; AFR_TEST nosprexact (or v11) keeps PM's copies.
    if pm is not None:
        if name == 'CRmt' and fix_on('sprexact'): return ('NEW', off)
        return ('PM', pm)
    if name in IMPORT_OK:
        return ('NEW', off)
    raise BuildError('no mapping for %s %x' % (cls, off))


# F04 (C7): per-part sound remap, (part, AF sound) -> PM object. 2007 re-plays the song already playing (AF
# FUN_10062440 returns 0xf001 for the same CPmBgm in a playing slot: it continues); PM restarts a song when the object
# differs (FUN_0042ea00 ignores only the same object; another one stops the slot, FUN_0042fba0, and starts from the
# beginning). Meiya line 1: PM already plays d9118cad, the part played the import of AF 13fd949b (the same recording,
# decoded 133.99 s vs 134.00 s); x_4f4791_185: the part starts the import of AF 305c1e39 and PM's own staging after its
# line 6 plays PM's copy 881b067f (01b8c7a482 #2555). The remapped calls play PM's object, so the song carries on as in
# 2007. The AF object is still allocated at the same point (key_alloc), so no key moves (miki still uses its import).
SOUND_REMAP = {('meiya', 0x13fd949b): 0xd9118cad, ('x_4f4791_185', 0x305c1e39): 0x881b067f}
if not all(v in sound_pairs for v in SOUND_REMAP.values()):
    raise BuildError('SOUND_REMAP: a PM object without a stream in sound_pairs')
# F06: (part, AF instruction) -> PM's own port of that instruction, emitted in its place. chizuru AF 7736 (typ 5 fade,
# w (2373, 0, 2000)) fades AF's loop 6ddd35c7, started before the part; in PM that loop is PM's c8e1149f (started at
# 01b8c7a482 #2190), so the restored fade of the import (not playing) left PM's loop running under chizuru lines 10-168.
# PM's port 01b8c7a482 #2232 (same id 16fb, same typ and words) fades c8e1149f, as 2007 fades its loop before line 10.
PM_PORT_SOUND = {('chizuru', 7736): ('01b8c7a482', 2232)}
PM_PORT_EFFECT = {('01b8c7a482', 2232): 0xc8e1149f}
# F07 (LAND): part -> new PM landing. 2007 goes straight from the part's last line to the next line (the update's
# script has no staging between them); PM's instructions between the part's old landing and these are its own copy of
# staging the part already played (calls / syncs / sounds only, no line, branch target or ACH; checked at startup):
# x_3eab17_1598 / 2453 a 1-s camera move (01ab8c3d66 5208-5209 / 5370-5371), x_3eab17_7449 the background re-shown +
# camera + 600 ms (01ad9ce956 4934-4936), x_45d98b_1809 the billboard jump-back and its 3-s sweep (01b30e953a
# 1906-1909), x_4cfd31_2031 the sound twice more with waits (01bef7a5ca 2215-2218), x_3eab17_4970 AF 4970's sound
# effect again (01ad9ce956 2472). Only the inserted calls' next pointers change.
LAND_FIX = {'x_3eab17_1598': 5210, 'x_3eab17_2453': 5372, 'x_3eab17_7449': 4937, 'x_45d98b_1809': 1910,
            'x_4cfd31_2031': 2219, 'x_3eab17_4970': 2473}
# F23 (C12 option b, the owner's decision for exactness; AFR_TEST nokashi leaves it out): the Kashiwagi lead-in
# conversation as 2007 shows it. 2007 (AF 3eab17 4877-4976 with the update's staging): background 724abae7 (PM copy
# d79d8a51), the CRmt sprite 70c09ab7 in box 3c9191 and no music (AF 4865 stopped it; kashiwagi starts the H BGM at
# 4981). PM kept 53 of its 62 lines (PM 01ad9ce956 2308-2477, AF's message ids) over its own staging: background c86fc08d,
# its CAC7Ti composite d7a8874b and BGM c6f089ff (#2369), so the three restored parts x_3eab17_4957 / 4963 / 4970 (lines
# 1-3, 1-4, 1-2) played between PM's lines in PM's picture with music. Now the three parts carry the whole conversation,
# chained like F16's parts: each runs on to the next part's first AF instruction (the added AF instructions take KASHI ids
# with their extras and CAMERA_KEEP inserts, their imports KASHI keys; the part's own instructions keep their ids and keys)
# and its call lands on the next part's call (patch_pm's land-on-call, F16); x_3eab17_4957's call moves from PM 2449 to
# PM 2308 (PM's background call; 2297-2307 = AF 4866-4876 by message id stay PM's) and the part first calls the
# conversation's start, AF [4877, 4957), a scene of its own (KASHI_PRE, like F17's continuation: KASHI ids, KASHI keys,
# scene key KASHI_SCENE_KEY in the SCENE range); x_3eab17_4970 runs to AF 4976 (= PM 2477, kashiwagi's anchor line) and
# lands on kashiwagi's call at PM 2478. PM 2308-2477 holds no FlagOp / jump / label / Ret / ACH (checked at startup).
# Every PM-insert id stays (the inserts keep their order), every main key stays (the parts allocate their own imports at
# the same points), no 1.0.0 id or key disappears. PM's own English for its 53 lines is kept on the restored copies of
# those lines (same message id, PM's English slot), so PM's English text mode shows what it showed before.
# (FIXPLAN F23 planned one merged scene from AF [4866, 4976) with one insert, two retired PM inserts and two unused scene
# keys; by PM's message ids AF 4866-4876 are PM 2297-2307, before the insert, and AF 4976 is PM 2477, inside the bypassed
# range: the range is [4877, 4977), and the chained form keeps every id and key. Recorded in impl/LEDGER.json F23.)
# x_3eab17_4970's LAND_FIX entry (F07) does not apply while F23 is in. Without the official update F23 is left out (no
# 2007 staging to rebuild).
# F25 KASHIPM (review integrity R1; AFR_TEST nokashipm leaves it out, which rebuilds F23 as above): moving x_3eab17_4957's
# call from PM 2449 to 2308 moved an existing PM-insert id (0x325c0) to another place in PM's script, against the rule that
# no 1.0.0 id moves, and a save made with 1.0.0 / v11 on PM's own lead-in lines 2308-2448 then went on past 2448 to PM
# 2449 and skipped x_3eab17_4957. Now x_3eab17_4957's call stays before PM 2449 (KASHI_OLD) and the start scene is called
# by an inserted call of its own before PM 2308 (KASHI_PM_CALL), which lands on x_3eab17_4957's call (land-on-call, as
# the chain): the same play order (start scene, x_3eab17_4957, 4963, 4970, kashiwagi), x_3eab17_4957 without its first
# instruction (the call that moved here), and that call keeps the id it had there (KASHI, taken at the same point of
# the build). PM 01ad9ce956 = 1.0.0's id list + that one id; a 1.0.0 / v11 save on PM's lead-in lines resumes on them
# and reaches x_3eab17_4957's call after PM 2448, as before.
KASHI_PM_CALL = (2308, 2449)   # F25: the start scene's own inserted call (PM insert, landing = x_3eab17_4957's call)
KASHI_AF, KASHI_PM, KASHI_PM_SPAN, KASHI_HOST = '00003eab17', '01ad9ce956', (2308, 2478), 'x_3eab17_4957'
KASHI_PRE = ('x_3eab17_4877', 4877, 4957)                     # the conversation's start: its own scene, called first
KASHI_EXTEND = {'x_3eab17_4957': (4957, 4963, 4960, 2308, 2458), 'x_3eab17_4963': (4963, 4970, 4967, 2458, 2472),
                'x_3eab17_4970': (4970, 4977, 4974, 2472, 2478)}   # (lo, hi, first added AF index, PM insert, landing)
KASHI_OLD = {'x_3eab17_4957': (4957, 4960, 2449), 'x_3eab17_4963': (4963, 4967, 2458), 'x_3eab17_4970': (4970, 4974, 2472)}
KASHI_PARTS = ()               # set in the main loop: tuple(KASHI_EXTEND) when F23 is in (fix_on('kashi') + the update)
_kashi = {}                    # F23 build state: the start scene's object / stats, PM English of the bypassed lines
# F11 (C6): 2007 stops every sound before the next chapter's first line (null typ 255 at 54cf59@3035 and at the update's
# 5caf15 P0); PM's chapter end and its next chapter's first lines stop none (670d5aaf, 670bd70d, 01acfa2412 #0-29 hold no
# sound command), so mikoto's BGM, kasumi_h's BGM and meiya's three loops ran on. mikoto / meiya end with PM's own null
# CVmSound typ 255 (01acfa2412 #101: CSoundManEx FUN_0042c370 -> FUN_0042eda0 stops every slot); kasumi_h ends with the
# update's end stretch after its last line, which the part did not have: P4440 b03fad(600) (white fade) + P4441 null
# typ 255 (checked at startup: exactly these two; mikoto / meiya: the update's end stretch is the part's own).
FIXEND_STOP = ('mikoto', 'meiya')
FIXEND_STOP_PM = ('01acfa2412', 101)
FIXEND_STRETCH = {'kasumi_h': (4440, 4441)}
# F12 (C14): 2007's white fade AF b03fad starts with OM_Invisible on the message box, so the text window is hidden for the
# whole fade; PM's 67191469 never hides it, and PM's OM_ParseScreenTrigger blocks until the fade ends, so a hiding helper
# after the call comes too late. Before an AF white fade emitted while the window is shown (no hider since the last
# line that shows text), PM's bare OM_Invisible on its message box (FIXWIN_TPL below, checked at startup) is emitted
# (FIXWIN ids). Hiders: PM helpers that hide the window (PM_WIN_HIDERS: picture / camera / sprite / effect / overlay helpers, as
# the window topic's v1_hiders.py lists), camera inserts, an OM_Invisible on the box; a line shows the window again only
# when its text has a code unit > 0x20 (PM FUN_004be740 @004be8a6).
# The copy is PM's 00ba6ba08e #218. FIXPLAN named 004fd25d2e #0, the same instruction (checked at startup: OM, target,
# flags, operand and trailing bytes equal), but every instruction #0 of a PM heap carries that heap's owner-chain pad
# inside its first object slot, and Builder._replay leaves the pad's skip count pending when that slot is a ref it
# renders itself, so the copy's own load-array entry went uncounted (load array 243, builder 241). None of PM's six
# OM_Invisible copies outside an instruction #0 has a pad.
FIXWIN_TPL = ('00ba6ba08e', 218)
FIXWIN_PLAN = ('004fd25d2e', 0)
# F26 WINSHOW (review exactness W1; AFR_TEST nowinshow leaves it out). 2007 shows the text window at every line: AF's
# CVmMsg (Vm60 FUN_1006cee0 @1006cf35-1006cf54), when the box style +0x3c has bit 2 set, calls the box's vfunc +0x34
# with style & ~2. PM's CVmMsg3 (FUN_004be740 @004be893-004be8ca) makes the same call only when the Japanese text has a
# code unit > 0x20, so a restored line of U+0005 alone or empty text after a hiding helper played with the window hidden:
# F14's three update-only lines sumika 274, mikoto 315 (click waits) and kasumi_h 39 (voiced, auto-advance). Before such
# a line, while the window is hidden (F12's tracking), PM's OM_Visible on its message box is emitted (WINSHOW ids). Its
# handler is CUI's 0x518eb0 (bytes 8b 41 34 8b 11 50 83 e0 fd 50 ff 52 3c: vfunc 0x3c(style & ~2, style), the call PM's
# CVmMsg3 makes; CMsgSelBox -> CMessBox -> CTextBox -> CBox -> CUI resolves OM_Visible to it, restore-audit
# deep/window/p5_omh.json; PM's own OM_Invisible on this box resolves to CUI 0x518e90 the same way). No PM script sends
# OM_Visible to this box (PM shows it with a line), so the instruction is FIXWIN_TPL (PM's OM_Invisible on the box) with
# PM's own '&-OM_Visible' class as its OM (WINSHOW_OM: PM's class definition, from 004fd064ca #30, OM_Visible on CParseBgBox;
# both OMs take no argument): the same instruction form PM uses for OM_Visible on its other boxes.
WINSHOW_OM = ('004fd064ca', 30)
PM_WIN_HIDERS = {0x27e92633, 0x27e92e99, 0x6715dbe7, 0x672040dd, 0x672bd7eb, 0x674ed45d, 0x67fb353f, 0x68d95167,
                 0x86697a41, 0x8a8b0e89}
AF_WHITE_FADE = 0xb03fad
# F13: Mikoto's box (AF 3c9575 = PM 46321) is in exclusive-camera mode in 2007 from AF 4f4791@1391 to @2276 (fixed
# camera 0,0,0,720); the parts restored inside that span (x_4f4791_1674, x_4f4791_1762) ran with PM's mode 0, so under
# PM's own camera (x_4f4791_1762 lines 2-3: (-86,40,0,960)) she was drawn 1.33x larger and shifted. Each of those parts
# starts with OM_SetExclusiveCamera(1) and ends with OM_SetExclusiveCamera(0) on her box, copied from PM's own ports of
# AF @1391 / @2276 (004fd07466 #37 / #112: same ids 5b2e / 4a95, the same box and value; checked at startup). EXCL ids.
EXCL_CAM_PM = {1: ('004fd07466', 37), 0: ('004fd07466', 112)}
EXCL_PARTS = ('x_4f4791_1674', 'x_4f4791_1762')
# F14 (C2 + limits L2): the update's staging inside three split lines. The update split sumika b1fe (line 273) and
# mikoto 2275 / 2278 (lines 313-314) into timed pieces: the first piece lost its trailing click 0x01 and carries dw2
# 0x01000000 (auto-advance, no voice wait: PM FUN_004be740 / AF FUN_1006cee0), staging follows, and an update-only line
# continues the page (04ae5 / 014a2: text U+0005 alone, dw2 0x60); kasumi_h gets an update-only voiced line with no text
# after b3ab (cb73, dw2 0x61, the form of its restored c51d / c52e) after a 500 ms wait, billboard 3d225c8b, camera move
# and shake. staging_segments files each segment under the line that ends it and these ids do not exist in the unpatched
# script, so the restored parts had a click and none of the staging. Now:
#  (a) every update-only line id between the update twins of two consecutive kept lines is folded into the next kept
#      line's segment: pseg[next] = pseg[id] + [id] + pseg[next] (exactly 3; asserted in a full build);
#  (b) a kept line whose update twin lost its trailing 0x01 and differs from the AF line's flags by 0x01000000 only
#      takes the update's text and flags (C2_SPLIT; English through to_pm_english, which drops the 0x01 too);
#  (c) the folded line is a CVmMsg3 with its update text (U+0005 or empty) in both slots, the update's flags and voices
#      (F09 rules);
#  (d) inside the folded items: C2_DROP (the two CVmBlt, OM_VramAgesImageIn - a PM stub - and, by limits L2, the
#      identity camera reset P8553 d13d87(0,0,0,720,1,0) + P8554 d14fbb(0,0) that in 2007 acted only on the frozen frame
#      and in PM would cut the live billboard from 1.72x to 0.5x; kasumi P3962, the FlagOp 0x50 assignment read only by a
#      b=33 sync), CVmSync(319679, b=1, v=0) dropped (AF Vm60 FUN_10070f50: (b & 0x30) == 0 with v == 0 returns at once),
#      CVmSync(319679, b=1, v>0) -> SHAKE_WAIT_PM(v) (the same path with v != 0 is a timed wait); shakes get
#      SHAKE_APPLY_PM as everywhere; the b=33 syncs stay (no-ops in both);
#  (e) the folded items, their extras and the CAMERA_KEEP inserts planned at them take PATCH ids. Every object they use is
#      used by the same part too (no new key); one of them, mikoto's background 4ce2cdeb, only later in that part, so its
#      key is allocated where the build without F14 allocates it (deferred key, convert_block: c2_defer).
C2_DROP = {('00003eab17', 8548)} | {('00003eab17', p_) for p_ in range(8551, 8556)} | {('0000514e5d', 3962)}
C2_FOLD = {('sumika', 0x4ae5), ('mikoto', 0x14a2), ('kasumi_h', 0xcb73)}      # (a), full-build assert
C2_SPLIT = {('sumika', 0xb1fe), ('mikoto', 0x2275), ('mikoto', 0x2278)}     # (b), full-build assert
C2_LINE_FLAGS = {0x4ae5: 0x60000000, 0x14a2: 0x60000000, 0xcb73: 0x61000000}  # (c), dw2 flags as FIXPLAN states
_c2_done = collections.defaultdict(set)     # 'fold' / 'split' -> (part, message id) done in this build
# F16 (C8): in the Myun x Chizuru scene PM kept 11 of its own lines between the four restored parts (AF 7382-7383,
# 7475-7476, 7588-7592, 7596-7600) and shows its own 16:9 crops on them (dea8df9b / deb5c25d / dec2a7e5: another picture
# after 7384, deb5c25d under 7600 where 2007 already shows 46a130f1), until the next part's LEAD_IN switches back; 2007
# keeps the part's AF CG. Each part runs on to the next part's first AF instruction, (lo, hi, PM insert, new landing):
# the added AF instructions (index >= the old hi) import into their own key range (X45, 0x7F800000; their tail voices
# too) and take X45 ids with their extras and CAMERA_KEEP inserts; no line number moves. The new landing is the next
# part's insertion point: patch_pm lands the call ON the call inserted there (the parts chain), where a landing always
# meant the original instruction after any call inserted at it. The PM instructions bypassed between the old and the new
# landing are lines, PM's crop staging and (2094-2100) a PM-only sound effect, no branch target (checked at startup).
X45_EXTEND = {'x_45d98b_7366': (7366, 7384, 2050, 2058), 'x_45d98b_7384': (7384, 7477, 2058, 2068),
              'x_45d98b_7477': (7477, 7593, 2068, 2084), 'x_45d98b_7593': (7593, 7601, 2084, 2101)}
X45_NEXT = {'x_45d98b_7366': 'x_45d98b_7384', 'x_45d98b_7384': 'x_45d98b_7477', 'x_45d98b_7477': 'x_45d98b_7593',
            'x_45d98b_7593': 'x_45d98b_7601'}   # the part inserted at each new landing (checked at startup)
_x45_done = []
# F17 (C1): yuuhi_a's route-A aftermath. 2007 route A (5cab65 == 2) plays AF 3eab17 1516-2339, then FlagOp 2340 (op
# 0x43, 5cab65 != 2, target 2915; PM / AF jump on a false compare) jumps to the aftermath it shares with route B, AF
# 2915-3200: 150 lines, 20 picture calls of 11 pictures, 3 sound effects, the white fade b03fad(600) and the stop of the
# scene's BGM 6f83821d (started by yuuhi_a at AF 1658) at 3189-3190. blocks.block drops 2340 and only yuuhi_b [2508,
# 3201) holds 2915-3200, so yuuhi_a ended after 2339 and its BGM played on over PM's end card and the next chapter.
# Appending the range to yuuhi_a would move every later id and yuuhi_b's keys; it is a scene of its own instead,
# 'yuuhi_a_cont': blocks.block's rules over [2915, 3201) (drops: the replay check 3192 and its path 3193-3196, the
# FlagOps 3197 / 3199, the AccessWrites 3198 / 3200; equal to yuuhi_b's keep there), the update's staging as in yuuhi_b's
# tail (the update's span P2932-3217 has AF 2915-3200's staging and message ids instruction for instruction; all checked
# at startup), converted after the 73 parts. Every object it uses is already imported by yuuhi_b (no key is allocated:
# asserted); its scene object has the reserved key YCONT_SCENE_KEY (SCENE range, listed after the F16 imports); its
# instructions take YCONT ids (its white fade's FIXWIN insert a FIXWIN id). yuuhi_a calls it right before its closing
# CVmRet: one argument-less CVmCall in patch_pm's inserted-call form (YCONT id), whose reference gets the scene object's
# size once that is built (yuuhi_a's heap keeps its length). Its CAMERA_KEEP starts from AF's camera before 2340 (route
# A arrives from 2339), not 2914, and its text-window state from yuuhi_a's at the call.
YCONT_PART, YCONT_HOST = 'yuuhi_a_cont', 'yuuhi_a'
YCONT_AF, YCONT_LO, YCONT_HI, YCONT_FROM = '00003eab17', 2915, 3201, 2340
YCONT_DROPS = {3192: 'replay check', 3193: 'replay-only path', 3194: 'replay-only path', 3195: 'replay-only path',
               3196: 'replay-only path', 3197: 'branch', 3198: 'AccessWrite', 3199: 'branch', 3200: 'AccessWrite'}
YCONT_PATCH_LO = 2932          # the update's twin of AF 2915 (its span P2932-3217 = AF 2915-3200 + 17)
YCONT_ROUTE_VAR = 0x5cab65     # AF CInt tested by the route-A jump 2340
YCONT_ENC_PH = 0xFEDC1700      # placeholder size in yuuhi_a's call until the scene object is built (replaced, checked)
_ycont = {}                    # F17 build state: 'win' (window hidden at the call), 'host' (yuuhi_a's heap / key / index)


def kashi_pre_block():
    """F23: the conversation's start AF KASHI_AF [4877, 4957) under range_block's rules, at x_3eab17_4957's PM site."""
    A_ = af_heap(KASHI_AF); inv_ = {o: k for k, o in enumerate(af_offsets_of(A_))}
    nm, lo_, hi_ = KASHI_PRE; keep_, drop_ = [], {}; skip_until = None
    for i in range(lo_, hi_):
        ins = A_.instrs[i]
        if skip_until is not None and i < skip_until:
            drop_[i] = 'replay-only path'; continue
        skip_until = None
        r = [x for x in A_.ins_res[i] if x and isinstance(x[0], tuple)]
        if ins[2] == 'CVmFlagOp' and r and r[0][1] == BL.REPLAY_BOOL:
            t = inv_.get(struct.unpack_from('<I', A_.d, ins[1] - 4)[0])
            if t is not None and t > i:
                skip_until = t; drop_[i] = 'replay check'; continue
        if ins[2] == 'CVmJump': drop_[i] = 'jump'; continue
        if ins[2] in ('CVmLabel', 'CVmRet'): drop_[i] = ins[2]; continue
        if ins[2] == 'CVmGenericMsg' and ins[3] and 'AccessWrite' in str(ins[3][0]): drop_[i] = 'AccessWrite'; continue
        keep_.append(i)
    lo2, hi2, kf, pi_, land_ = KASHI_EXTEND[KASHI_HOST]
    return dict(name=nm, af=KASHI_AF, lo=lo_, hi=hi_, keep=keep_, drop=drop_, pm=KASHI_PM, pm_before=pi_ - 1,
                land=land_, full_heap=True, kashi_scene=True, import_mode='kashi')


def pm_en_kashi():
    """F23: {message id: PM's English slot text} of PM's own lines in KASHI_PM [KASHI_PM_SPAN) (ids that occur once,
    English slot not the Japanese one)."""
    if 'en' not in _kashi:
        H = pm_srcs[KASHI_PM].h; t0 = H.tail['text_start']; seen = collections.Counter(); txt = {}
        for j in range(*KASHI_PM_SPAN):
            if H.instrs[j][2] != 'CVmMsg3': continue
            p = base_pos(H.d, H.instrs[j][0]); mid = struct.unpack_from('<I', H.d, p + 4)[0] & 0xFFFFF; seen[mid] += 1
            if H.d[p + 12] < 2: continue
            o0, o1 = struct.unpack_from('<I', H.d, p + 14)[0], struct.unpack_from('<I', H.d, p + 26)[0]
            if o1 == o0: continue
            q = e = t0 + 2 * o1
            while H.d[e:e + 2] != b'\x00\x00': e += 2
            txt[mid] = H.d[q:e].decode('utf-16le')
        _kashi['en'] = {m: t for m, t in txt.items() if seen[m] == 1}
    return _kashi['en']


def ycont_block():
    """F17: blocks.block's rules (every FlagOp, jump, label, Ret and AccessWrite dropped, a replay check skips its path)
    over AF YCONT_AF [YCONT_LO, YCONT_HI); yuuhi_a's PM site (host heap, pad count)."""
    A_ = af_heap(YCONT_AF); inv_ = {o: k for k, o in enumerate(af_offsets_of(A_))}
    keep_, drop_ = [], {}; skip_until = None
    for i in range(YCONT_LO, YCONT_HI):
        ins = A_.instrs[i]
        if skip_until is not None and i < skip_until:
            drop_[i] = 'replay-only path'; continue
        skip_until = None
        r = [x for x in A_.ins_res[i] if x and isinstance(x[0], tuple)]
        if ins[2] == 'CVmFlagOp':
            ti = inv_.get(struct.unpack_from('<I', A_.d, ins[1] - 4)[0])
            if r and r[0][1] == BL.REPLAY_BOOL and ti is not None and ti > i:
                skip_until = ti; drop_[i] = 'replay check'
            else:
                drop_[i] = 'branch'
            continue
        if ins[2] == 'CVmJump': drop_[i] = 'jump'; continue
        if ins[2] in ('CVmLabel', 'CVmRet'): drop_[i] = ins[2]; continue
        if ins[2] == 'CVmGenericMsg' and ins[3] and 'AccessWrite' in str(ins[3][0]): drop_[i] = 'AccessWrite'; continue
        keep_.append(i)
    host = BL.block(YCONT_HOST)
    return dict(name=YCONT_PART, af=YCONT_AF, lo=YCONT_LO, hi=YCONT_HI, keep=keep_, drop=drop_, pm=host['pm'],
                pm_before=host['pm_before'], land=host['land'], ycont=True, cam_from=YCONT_FROM)
# F09 (C15): the speaker of every restored voice. 2007: each voiced line animates its speaker's mouth while the voice
# plays (AF CSoundManEx slot 0x94 -> FUN_1005f3a0 / FUN_1005f6b0: the box is the voice's ocean +0xc) and obeys the
# player's per-character voice setting (FUN_1005f0f0, through the ocean's registration). PM finds the speaker through
# the voice's parent ocean and its registration (FUN_0042a8f0 / FUN_0042a360); every restored voice was an import
# parented to the scene pad, so PM found no speaker on any restored line and applied '$NoCharAssigned' to all of them.
# (1) a voice whose AF ocean has a registration is parented to PM's ocean of the same box and registration
#     (VOICE_OCEAN_PM; restore-audit verify-window v6_oceanmap.json / v22_tail.py), as PM's own voice refs are
#     (19,507 PM voice refs: flag 0xC108, parent CCharVoiceOcean, trailing 00);
# (2) a voice whose AF ocean has none (PM has no ocean for it) keeps the pad parent, and its line names the speaker
#     explicitly: voice entry 0's u16 #2 = the tail index of PM's box (VOICE_SPK_BOX = objmap of the AF ocean's box),
#     PM's own port form (01b8c7a482 #2223 / #2224); the update's 0x04000000 links (69 lines) name exactly that box.
# Checked at the first use of each AF ocean (_c15_ocean_check): the ocean's first body ref (its box) maps to the PM
# ocean's first body ref (1), or to the VOICE_SPK_BOX value, a CCharBox2 (2); a full build uses every entry.
VOICE_OCEAN_PM = {0x6dabeac1: 0x8ac82e69, 0x7027947b: 0x8ac82e69, 0x713e0319: 0x8b0e712d, 0xbcd478fd: 0x8b0e712d,
                  0x6eb6eb41: 0xd2f158d7, 0xbcbf1c9b: 0xd2f158d7, 0x6e078e49: 0xd5d75f4f, 0x717be631: 0xd9b19221,
                  0x717b81ff: 0xb8d4dfd1, 0x717b100f: 0xd8bc48cf, 0x6ea6de01: 0x8ac7f6cd, 0x71853c5d: 0xd8bc817b,
                  0x6e250a79: 0xd6d34045, 0x70c70c09: 0xd8bc7343, 0x78db516f: 0xc9401b01, 0x7fbe3911: 0xcc3ec71f,
                  0x7ffeb4e3: 0xcc101ba9, 0x7fbc46cd: 0xcc3f4735, 0x6e9ce7d9: 0xd5cbbb19, 0x69e15d39: 0x9e20c3af,
                  0x3132667f: 0x8aeb87e3}
VOICE_SPK_BOX = {0x71ecef27: 0x45991, 0x71ebde07: 0x45949, 0x71ed0f89: 0x459d9, 0x71ebb049: 0x45901,
                 0x6ea4db9b: 0x27e5f977}       # AF oceans without a registration -> PM box (3a761d, 3a7577, 3a76c3, 5b309, 5cae23)
_ref_idx = {}           # id(heap) -> (first 'ref' event per object offset, 'ref' event per start position, ocean sizes)
_voice_ocean = {}       # (AF heap, voice offset) -> AF ocean (cls, off, size)
_c15_checked = {}       # AF ocean offset -> 'pm' | 'spk' (checked)
_c15_stats = collections.Counter()


def af_voice_ocean(af, voff):
    """F09: the AF ocean (cls, off, size) that is the parent of voice voff (the update's heap first, else the AF heap):
    the nested parent ref after the voice ref's enc pair, or the object its back-index names (as deep/verify-window/py/
    v18_parent.py, 2162/2162 restored voices)."""
    if (af, voff) in _voice_ocean: return _voice_ocean[(af, voff)]
    hs = [H for H in (af_patch_heap(af), af_heap(af)) if H is not None]
    for H in hs:
        if id(H) not in _ref_idx:
            sz = {}
            for r_ in H.refs:
                if r_[1][0] == 'CCharVoiceOcean': sz[r_[2]] = max(r_[3], sz.get(r_[2], 0))
            _ref_idx[id(H)] = ({ev[6]: ev for ev in reversed(H.ev) if ev[0] == 'ref'},
                               {ev[1]: ev for ev in H.ev if ev[0] == 'ref'}, sz)
    for H in hs:
        first, at, _ = _ref_idx[id(H)]; ev = first.get(voff)
        if ev is None: continue
        p = ev[4] + 8; nested = at.get(p)
        par = (nested[5], nested[6], nested[7]) if nested else H.objinfo.get(struct.unpack_from('<H', H.d, p)[0])
        if par and par[0][0] == 'CCharVoiceOcean':
            # the ocean's size for the check: the largest any ref of these heaps gives (some refs carry a smaller
            # size field, as deep/window/py/p12_oceans.py found)
            size = max([par[2]] + [_ref_idx[id(H2)][2].get(par[1], 0) for H2 in hs])
            _voice_ocean[(af, voff)] = par; _c15_ocean_check((par[0], par[1], size)); return par
    raise BuildError('C15: voice %x has no CCharVoiceOcean parent' % voff)


def _c15_ocean_check(oc):
    """F09: the AF ocean's box (its first body ref, +0xc) maps to the box of the PM ocean it is given (VOICE_OCEAN_PM),
    or to its VOICE_SPK_BOX value (a CCharBox2 that PM templates have)."""
    if oc[1] in _c15_checked: return
    body = af_object(oc[1], oc[2])[1]; refs = body_refs(body)
    if not refs: raise BuildError('C15: AF ocean %x has no body ref' % oc[1])
    box = mapped(refs[0][1])
    if oc[1] in VOICE_OCEAN_PM:
        pm_oc = VOICE_OCEAN_PM[oc[1]]; c_ = pm_cls(pm_oc)
        if c_[0][0] != 'CCharVoiceOcean': raise BuildError('C15: PM %x is a %s' % (pm_oc, c_[0]))
        prefs = pm_body_refs(pm_object(pm_oc, c_[2]))
        if box is None or not prefs or prefs[0][0] != box:
            raise BuildError('C15: AF ocean %x box %x -> %s, PM ocean %x box %s' % (
                oc[1], refs[0][1], box and hex(box), pm_oc, prefs and hex(prefs[0][0])))
        _c15_checked[oc[1]] = 'pm'
    elif oc[1] in VOICE_SPK_BOX:
        if box != VOICE_SPK_BOX[oc[1]] or pm_cls(box)[0][0] != 'CCharBox2':
            raise BuildError('C15: AF ocean %x box %x -> %s, not the CCharBox2 %x' % (
                oc[1], refs[0][1], box and hex(box), VOICE_SPK_BOX[oc[1]]))
        _c15_checked[oc[1]] = 'spk'
    else:
        raise BuildError('C15: AF ocean %x not covered' % oc[1])


class VoiceBuilder(Builder):
    """F09: a voice import whose AF ocean has a registration gets PM's ocean as its parent (template replay, as PM's own
    voice refs) instead of the scene pad. Everything else as Builder (same key allocation point, same flag)."""
    voice_parent = {}      # AF voice offset (used take) -> PM ocean

    def object_slot(self, src, cls, off, size, R=None):
        pm_oc = self.voice_parent.get(off) if cls[0] == 'COptimizedObs' else None
        target = self.remap(src, (cls, off, size)) if pm_oc is not None else None
        if pm_oc is None or target[0] != 'NEW' or target in self.objs:
            return Builder.object_slot(self, src, cls, off, size, R)
        self.ensure_pad(); enc_off, enc_sz = self.key_alloc(off, cls, size)
        self.emit_class(cls[0], cls[1], 'cdef')
        flag = struct.unpack_from('<H', src.h.d, R[4] - 2)[0] if (R is not None and src is not None) else 0xC108
        self.out += struct.pack('<HII', flag, enc_off, enc_sz)
        self.object_slot(None, *pm_cls(pm_oc))           # parent slot: PM's ocean (template replay), not pad 0
        self.out += b'\x00' if (flag & 3) == 0 else b'\x00\x00\x00\x00'
        self.imports[off] = (cls, size); idx = self.alloc(); self.objs[target] = idx
        _c15_stats['voice_parent_pm'] += 1
        return idx


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
# LEAD_IN replays get ids from their own range, so every instruction keeps the id 1.0.0 gave it (read marks, resumed
# sessions); above every restored / inserted id (0x30000-0x3260e), below 0x3ffff (warning flag)
LEAD_ID_BASE = 0x3F000
lead_id = [LEAD_ID_BASE]
# Instructions ADDED to a restored part after 1.0.0 (the 2nd instruction of a case-25 shock port, a shake wait after a
# waiting shake call) take ids from their own range too; an instruction that replaces one 1:1 keeps that one's id
ADD_ID_BASE = 0x3F100
add_id = [ADD_ID_BASE]
# CAMERA_KEEP inserts take ids from a range of their own (also inside a lead-in replay), so turning them on or off in a
# part (default: every part; AFR_TEST keepmikoto / nokeep) moves no other id: the 38 additions of 1.1.0 stay
# 0x3F100-0x3F125
KEEP_ID_BASE = 0x3F200
keep_id = [KEEP_ID_BASE]
# Restore-audit fixes (FIXPLAN id_ranges): the instructions a fix adds take ids from a range of their own, so turning one
# fix off moves no other id (no KEEP / ADD / LEAD / main counter ever moves). Every set below holds the fix's
# instructions, the extras emit_staging adds after them and the CAMERA_KEEP inserts attached to them. ENTRY and EXIT are
# fixed 16-id slots per part (base + 0x10 * index in ENTRY_ORDER / EXIT_ORDER), not counters, so one part's replay can be
# dropped without moving another's. LEAD2 0x3F700-0x3F7FF stays reserved and unused.
OVL_ID_BASE, PATCH_ID_BASE, FIXEND_ID_BASE, FIXWIN_ID_BASE = 0x3F280, 0x3F2C0, 0x3F300, 0x3F320   # F10, F14, F11, F12
YCONT_ID_BASE, X45_ID_BASE, KASHI_ID_BASE, EXCL_ID_BASE = 0x3F400, 0x3F600, 0x3F800, 0x3F900      # F17, F16, F23, F13
ovl_id, patch_id, fixend_id, fixwin_id = [OVL_ID_BASE], [PATCH_ID_BASE], [FIXEND_ID_BASE], [FIXWIN_ID_BASE]
ycont_id, x45_id, kashi_id, excl_id = [YCONT_ID_BASE], [X45_ID_BASE], [KASHI_ID_BASE], [EXCL_ID_BASE]
ENTRY_ID_BASE, EXIT_ID_BASE = 0x3FC00, 0x3FE00                                                    # F15, F21
# F24 RETID (review compat C1 / C2; AFR_TEST noretid leaves it out). A VM frame stores the instruction its CVmCall
# returns to, call->next (pm.exe CVmCall FUN_004c1b80 sets frame+0xc = [call+4]; CVmRet FUN_004c2010 resumes there), and
# a save writes that instruction by its id: CVmStackFrame::Serialize FUN_00443e10 (vftable 00629b48 slot 0x14), store
# branch, takes [[frame+0xc]+8] & 0xfffff and calls 0041f3f0 (AfxThrowNotSupportedException) when it is 0 (00443e9a-
# 00443ea4; the load branch the same at 00443f20). Every scene's closing CVmRet had id 0, so a save made while a call
# right before it was running failed: inside F17's whole 150-line continuation (yuuhi_a calls it last), and inside the
# last helper of ayamine / sumika / x_7cea05_1276 / yuuhi_b (1.0.0 already). The same SaveError(246) the inserted PM
# calls had until they got ids (MODLOG 2026-10-10). Such a closing CVmRet now carries an id of its own in PM's form for
# a Ret after a call (dw2 = id, flags 0: all 42 PM CVmRet right after a CVmCall carry a nonzero id); RETID ids, in build
# order. A closing CVmRet after anything else keeps id 0, as PM's 241 heap-closing Rets.
RETID_ID_BASE = 0x3F910
retid_id = [RETID_ID_BASE]
WINSHOW_ID_BASE = 0x3F340      # F26 (see WINSHOW_OM)
winshow_id = [WINSHOW_ID_BASE]
ENTRY_ORDER = ('marimo_65a0db_b', 'x_3eab17_3683', 'x_3eab17_4548', 'x_3eab17_7099', 'x_3eab17_7397', 'x_3eab17_7414',
               'x_45d98b_1809', 'x_45d98b_5704', 'x_45d98b_5726', 'x_45d98b_7302', 'x_45d98b_7644', 'x_45d98b_7674',
               'x_4cfd31_1620', 'x_4cfd31_2142', 'x_4cfd31_2165', 'x_4cfd31_2169', 'x_4f4791_332', 'x_4f4791_1762')
EXIT_ORDER = ('x_45d98b_3736', 'x_45d98b_4678', 'x_45d98b_5704', 'x_45d98b_7302')
# F21 PMEXIT (opt-in: AFR_TEST pmexit, a test build for the owner's in-game comparison). After these four parts PM's own
# next lines re-stage the next shot with PM's values (x_45d98b_5704: sprite (-505,1514) against 2007's (-497,1314);
# 4678: camera (0,45,0,1704) against (0,81,0,1704); 3736: two sprites with PM's OM_SetRmtInfoScaling, (116,694,1,664)
# against (-4,614,1,-280); 7302: 2007 moves the camera to (-332,24,0,3552), PM does not; restore-audit deep/entry
# EXIT-PMOWN). The test build ends each part with the update's own staging of that shot, (update indices, new PM
# landing or None = keep): PM's re-staging between the old and the new landing is calls / OMs only (checked at startup).
# Ids from the part's EXIT slot, imports in the EXIT key range. Not the default: these are PM's own lines, and PM's values
# (with its scaling OMs) belong to PM's remastered sprites; the engine code cannot show that 2007's values on PM's
# pictures, followed by PM's own staging, give 2007's picture.
EXIT_EXTEND = {'x_45d98b_5704': ((5806, 5807), 263), 'x_45d98b_4678': ((4790, 4791, 4792), 4377),
               'x_45d98b_3736': ((3816, 3817, 3818), 3383), 'x_45d98b_7302': ((7413, 7414), None)}
if set(EXIT_EXTEND) != set(EXIT_ORDER): raise BuildError('EXIT_EXTEND and EXIT_ORDER differ')
# F15 (ENTRY, includes C9): parts whose first lines play over PM's own staging of the lines before them (another camera,
# sprite positions, sprites or faces; restore-audit deep/entry ENTRY-MECH + 18 items, corrected by verify-entry). Each
# starts by replaying the 2007 state, from the official update's script: 'P' = an update instruction emitted as staging
# (a hut picture brings its BG_OVERLAYS), 'Z' = the update's apply after it with both arguments forced to int 0 (an
# instant cut: 2007 already showed this state on its previous lines). Placed before the part's first kept instruction
# (after a Marimo route guard, and after F13's exclusive-camera insert); imports in their own key range (ENTRY,
# 0x7FC00000; the part's own references use the main-range objects, as LEAD_IN); ids from the part's fixed ENTRY slot.
# Order inside a list = PM's / 2007's (x_45d98b_1809: sprite before posture; x_3eab17_4548: the scaling OM first, no
# picture; x_3eab17_7099: no picture, so the shown composition's rain / alpha stay). C12's three Kashiwagi lead-in parts
# are F23's, not replays. Without the official update there is no 2007 state to replay: the replays are left out.
ENTRY_REPLAY = {'marimo_65a0db_b': [('P', 642), ('P', 656), ('P', 659), ('P', 643), ('Z', 660)],
                'x_3eab17_3683': [('P', 3820), ('Z', 3821)],
                'x_3eab17_4548': [('P', 4972), ('P', 4973), ('Z', 4974)],
                'x_3eab17_7099': [('P', 7747), ('Z', 7748)],
                'x_3eab17_7397': [('P', 8044), ('Z', 8045)],
                'x_3eab17_7414': [('P', 8054), ('Z', 8055)],
                'x_45d98b_1809': [('P', 1785), ('P', 1811), ('P', 1810), ('P', 1814), ('Z', 1815)],
                'x_45d98b_5704': [('P', 5783), ('P', 5801), ('P', 5788), ('Z', 5802)],
                'x_45d98b_5726': [('P', 5823), ('Z', 5825)],
                'x_45d98b_7302': [('P', 7353), ('P', 7354), ('P', 7356), ('P', 7391), ('P', 7405), ('Z', 7406)],
                'x_45d98b_7644': [('P', 7739), ('P', 7740), ('P', 7741), ('P', 7742), ('Z', 7743)],
                'x_45d98b_7674': [('P', 7739), ('P', 7764), ('P', 7778), ('Z', 7779)],
                'x_4cfd31_1620': [('P', 1681), ('Z', 1687)],
                'x_4cfd31_2142': [('P', 2190), ('Z', 2215)],
                'x_4cfd31_2165': [('P', 2242), ('Z', 2243)],
                'x_4cfd31_2169': [('P', 2242), ('Z', 2243)],
                'x_4f4791_332': [('P', 330), ('Z', 331)],
                'x_4f4791_1762': [('P', 1746), ('P', 1808), ('P', 1747), ('Z', 1809)]}
if set(ENTRY_REPLAY) != set(ENTRY_ORDER): raise BuildError('ENTRY_REPLAY and ENTRY_ORDER differ')
_slot_used = collections.defaultdict(list)     # ('entry' | 'exit', part) -> ids handed out in that part's slot
_lead_typed = {}                 # AF heap -> TypedArgHeap (argument positions of the lead-in camera apply)


def slot_end(h, ev_lo, ev_hi, start):
    for k in range(ev_lo, ev_hi):
        ev = h.ev[k]
        if ev[0] == 'ref' and ev[1] == start: return ev[2]
    return start + 2


TYPE_NAMES = {'低精度実数'.encode('cp932'): b'_float', '色'.encode('cp932'): b'_VCOLOR'}   # AF -> PM type names


class TypedArgHeap(Heap):
    """Records the byte span of every typed-constant (d==4) CVmCall argument's type name: (len_pos, name_end, name),
    of every non-ASCII ANSI CString (call / OM arguments) in self.ansi: (start, end, bytes), and of every inline
    CMoveAcsOngen body in self.acs: (start, end)."""
    def string(self):
        a = self.p; s = Heap.string(self)
        if self.d[a] != 0xff and any(b >= 0x80 for b in s):
            self.ansi.append((a, self.p, s))
        return s

    def parse(self):
        self.ansi = []; self.acs = []; return Heap.parse(self)

    def io_moveacs(self, cls):
        a = self.p; Heap.io_moveacs(self, cls); self.acs.append((a, self.p))

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
    # env AFR_AF_PATCH: a copy of the official patch to read instead of the one next to altfable.rio (lab builds made
    # while the scene tester has a jump patch installed in the 2007 folder); size and sha1 are checked either way
    ruo = os.environ.get('AFR_AF_PATCH') or sibling(AF_RIO, '.ruo1')
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
        dw2_ = struct.unpack_from('<I', H.d, base_pos(H.d, ins[0]) + 4)[0]; mid = dw2_ & 0xFFFFF
        if mid in out: dup.add(mid)
        # [2] (F09): the update's speaker link (flag 0x04000000: the box ref read after the voice slot), else None
        r2 = (H.ins_res[i] or [None, None, None])[2] if dw2_ & 0x04000000 and len(H.ins_res[i] or ()) > 2 else None
        link = r2 if r2 and isinstance(r2[0], tuple) and r2[0][0] in ('CCharBox', 'CCharBox2') else None
        out[mid] = (ins[5][0][1], [r for r in (H.ins_res[i] or [])[1:]
                                   if r and isinstance(r[0], tuple) and r[0][0] == 'COptimizedObs'], link)
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


class CanonHeap(Heap):
    """F08 (C11), copied from restore-audit/verify-sprites/f1_sim.py: a heap that records the position of every argument
    dword whose low 2 bits are 0 (object argument): its upper 30 bits are a stale in-memory value (they differ between
    the 2007 scripts and the update's for the same object)."""
    def parse(self):
        self.objd = set(); return Heap.parse(self)

    def _d(self):
        p = self.p; d = struct.unpack_from('<I', self.d, p)[0]
        if d != 4 and d & 3 == 0: self.objd.add(p)
        return d

    def sub1(self):
        self._d(); return Heap.sub1(self)

    def sub1_om(self):
        self._d(); return Heap.sub1_om(self)

    def vm_call(self):
        self.u32(); self.u32(); self.read_class_list(); n = self.u16()
        for _ in range(n):
            self._d(); d = self.u32()
            if d == 4:
                w = self.u16()
                if w == 0x1e57: self.read_class()
                elif w == 0x369e: self.read_raw_class()
                elif w in (0x2d6b, 0x2f1a): self.u16(); k = self.u16(); self.skip(k)
                self.skip(4)
            else:
                k = d & 3
                if k == 0: self.read_class_list()
                elif k == 1: self.string()
                elif k == 3:
                    t1 = self.u32()
                    if t1 == 0x137: self.u32()
        if self.cur_schema > 0x12:
            k = self.u8()
            if k == 0xff: k = self.u16()
            for _ in range(k):
                w = self.u16()
                if w & 0x8000: self.string()
                else: self.read_class_list()


def canon(H, i):
    """F08 (C11), copied from verify-sprites/f1_sim.py: class + dw2 flag bits + every operand byte after the base, with
    class / object tokens replaced by meaning ('<cls@off>') and the stale upper 30 bits of object-argument dwords
    (CanonHeap.objd) zeroed"""
    s, e = H.instrs[i][0], H.instrs[i][1]
    lo, hi = H.ins_ev[i]
    bp = base_pos(H.d, s)
    b = bytearray(H.d[s:e])
    for q in getattr(H, 'objd', ()):
        if s <= q < e: b[q - s:q - s + 4] = bytes(4)
    D = lambda a, z: bytes(b[a - s:z - s]).hex()
    out = [H.instrs[i][2], '%08x' % (struct.unpack_from('<I', H.d, bp + 4)[0] & 0xFFF00000)]; p = bp + 8
    pri = {'pad': 0, 'ref': 1, 'cdef': 2, 'rdef': 2, 'adef': 2, 'cidx': 3, 'oidx': 3, 'null': 3}
    evs = sorted((ev for ev in H.ev[lo:hi] if ev[0] in pri), key=lambda ev: (ev[1], pri[ev[0]]))
    for ev in evs:
        if ev[1] < p: continue
        out.append(D(p, ev[1]))
        if ev[0] == 'ref': out.append('<%s@%x>' % (ev[5][0], ev[6])); p = ev[2]
        elif ev[0] in ('cdef', 'rdef', 'adef'): out.append('<c %s>' % (ev[4][0],)); p = ev[2]
        elif ev[0] == 'cidx':
            c = H.cache[ev[2]] if ev[2] < len(H.cache) else None
            out.append('<c %s>' % (c[0] if c else ev[2],)); p = ev[1] + 2
        elif ev[0] == 'oidx':
            w = ev[2]; oi = H.objinfo.get(w)
            out.append('<%s@%x>' % (oi[0][0], oi[1]) if oi else '<o %s>' % w); p = ev[1] + 2
        elif ev[0] == 'null': out.append('<null>'); p = ev[1] + 2
        elif ev[0] == 'pad': out.append('<pad>'); p = ev[1] + 1
    out.append(D(p, e))
    return '|'.join(out)


_canon = {}             # F08: heap key -> CanonHeap of the same bytes


def operand_sig(H, key, i):
    """F08 (C11): stage_sig plus every operand (canon) of instruction i of heap H (key: its _canon key)."""
    if key not in _canon:
        _canon[key] = CanonHeap(H.d, 2); _canon[key].parse()
        if _canon[key].count != H.count: raise BuildError('C11: %s parses to %d instructions, not %d' % (key, _canon[key].count, H.count))
    return stage_sig(H, i), canon(_canon[key], i)


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
_targ = {}              # heap key -> TypedArgHeap (argument positions)
_keep_report = {}       # part -> CAMERA_KEEP rows and the output index of every picture / camera call
_pic_info = {}          # (heap key, index) -> picture call: picture, imported / CG, drawn size, projection inputs
_cam_info = {}          # (heap key, index) -> camera call: AF values, mode, position, PM values, owner-tested values
_shock25 = set()       # (heap key, instruction index) of AF case-25 screen-effect calls, emitted as SHOCK_PM
_shake_wait = {}        # (heap key, instruction index) -> ('after' | 'replace', ms), see SHAKE_WAIT_PM
_shake_calls = set()    # (heap key, instruction index) of every AF shake call: SHAKE_APPLY_PM follows each one
_shake_unpaired = set()  # b=16 CVmSyncs on SHAKE_VAR without a shake call right before them (left as they are)
_shake_unpaired_out = []  # ... of those, the ones a part emits
_shock25_done = [0]
_shake_wait_done = collections.Counter()
_shake_apply_done = [0]


def curve_ms(body):
    """Length (ms) of a CMoveAcsOngen body (layout as rsaparse.io_moveacs): +0x48 when +0x44 != -1 (pm.exe FUN_005772c0;
    the tail is +0x44, +0x48, +0x4c, +0x40, +0x42 per its reader FUN_00577770). None for a looping curve (+0x42 & 2)."""
    q = 12
    while body[q] != 0x70:
        b = body[q + 1]; q += 6 + (12 if b & 1 else 8)
        n = struct.unpack_from('<H', body, q)[0]; q += 2 + 12 * n
        if b & 2: raise BuildError('shake curve: archive object in a segment')
    i44, i48 = struct.unpack_from('<ii', body, q + 1)
    if struct.unpack_from('<H', body, q + 14)[0] & 2: return None
    if i44 == -1: raise BuildError('shake curve without an explicit length')
    return i48


def shake_ms(T, i):
    """Length (ms) of the posture passed by shake call i: its longest curve (FUN_004831e0), inline or referenced."""
    s, e = T.instrs[i][0], T.instrs[i][1]
    bodies = [T.d[a:b] for (a, b) in T.acs if s <= a < e]
    bodies += [af_object(off, size)[1] for (_, cls, off, size) in T.instrs[i][4] if cls[0] == 'CMoveAcsOngen']
    lens = [curve_ms(b) for b in bodies]
    if not lens or None in lens or not all(0 < x <= 10000 for x in lens):
        raise BuildError('shake call %d: no usable curve length %s' % (i, lens))
    return max(lens)


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
        def call_to(j, helper):
            r = T.ins_res[j][0] if T.ins_res[j] else None
            return T.instrs[j][2] == 'CVmCall' and bool(r and isinstance(r[0], tuple) and r[1] == helper)

        def shake_sync16(j):            # CVmSync(SHAKE_VAR, b=16): wait until the stored shake ends
            r = T.ins_res[j][0] if T.ins_res[j] else None
            return (T.instrs[j][2] == 'CVmSync' and bool(r and isinstance(r[0], tuple) and r[1] == SHAKE_VAR)
                    and T.d[T.instrs[j][1] - 5] == 16)

        for i, ins in enumerate(T.instrs):
            if ins[2] != 'CVmCall': continue
            L = ins[3]; ap = L['argpos']
            if 'fadetime' in AFR_TEST and call_to(i, CAMERA_UPDATE) and len(ap) >= 3:     # F18 (opt-in, see FADE_TIME)
                a0, a1 = (struct.unpack_from('<I', T.d, ap[q])[0] for q in (0, 1))
                if a0 & 3 == 2 and a1 & 3 == 2 and (a0 >> 2) in FADE_TIME:
                    ms_new = FADE_TIME[a0 >> 2](a1 >> 2)
                    repl[ap[1]] = (ap[1] + 4, struct.pack('<I', ((ms_new << 2) | 2) & 0xFFFFFFFF))
                    _fadetime_log[(af, i)] = (a0 >> 2, a1 >> 2, ms_new)
            if call_to(i, FADE_HELPER):     # case 25 (screen shock) -> SHOCK_PM; the other cases match PM's 674ed45d
                if len(ap) >= 2 and struct.unpack_from('<I', T.d, ap[0])[0] == (25 << 2) | 2: _shock25.add((af, i))
                continue
            if not call_to(i, SHAKE_HELPER): continue     # AF shake call (posture, wait flag, unused) -> PM (posture, int)
            if (len(ap) != 4 or struct.unpack_from('<I', T.d, ap[1])[0] & 3 != 2
                    or struct.unpack_from('<I', T.d, ap[2])[0] & 3 != 2 or ap[3] - ap[2] != 4):
                raise BuildError('shake call %d: unexpected args' % i)
            repl[L['npos']] = (L['npos'] + 2, struct.pack('<H', 2))
            repl[ap[2]] = (ap[3], b'')
            _shake_calls.add((af, i))           # PM starts the shake only at an apply: SHAKE_APPLY_PM right after it
            try: ms = shake_ms(T, i)
            except BuildError as e: ms = e      # raised only if a part emits this wait
            if struct.unpack_from('<I', T.d, ap[1])[0] >> 2 == 0:       # AF's helper waits for the shake itself
                _shake_wait[(af, i)] = ('after', ms)
            elif i + 1 < T.count and shake_sync16(i + 1):              # the script waits for it right after the call
                _shake_wait[(af, i + 1)] = ('replace', ms)
        for j in range(T.count):   # other b=16 waits on the shake var (none in the default build): left as they are
            if shake_sync16(j) and (af, j) not in _shake_wait and not (j and call_to(j - 1, SHAKE_HELPER)):
                _shake_unpaired.add((af, j))
        for (a, end, sb) in T.ansi:          # PM is a Unicode build: AF cp932 strings become UTF-16 CStrings
            repl[a] = (end, write_cstring_utf16(sb.decode('cp932')))
        # cameras: the zoom rule (default: the exact 2007 values; AFR_TEST zoom12 etc.: the pre-exact rule with
        # IMPORTED_IMAGE_ZOOM and FILL_FLOOR, always inside bb2bg's converted range) or FRAME_RULE (AFR_TEST
        # framerule); every picture and camera call is recorded for CAMERA_KEEP (_pic_info / _cam_info, keyed (heap
        # key, index))
        _targ[af] = T
        fixed = {i for (h_, i) in camera_fix() if data is None and af.endswith(h_)}
        conv = BB_TO_BG.get(af)
        if conv:      # the scene starts after its anchor line (found by message id in the patched script)
            blc = BL.block(conv); Au = af_heap(blc['af'])
            mid0 = struct.unpack_from('<I', Au.d, base_pos(Au.d, Au.instrs[blc['lo'] - 1][0]) + 4)[0] & 0xFFFFF
            lo_p = next(j + 1 for j, t in enumerate(T.instrs) if t[2] == 'CVmMsg' and
                        struct.unpack_from('<I', T.d, base_pos(T.d, t[0]) + 4)[0] & 0xFFFFF == mid0)

        def floor_range(table):          # FILL_FLOOR range of this heap (patched heap: the scene after its anchor)
            if conv: return (lo_p, T.count, table[blc['af']][2]) if blc['af'] in table else None
            return table.get(af) if data is None else None
        floor = floor_range(FILL_FLOOR)                 # the rule's ({} unless the pre-exact rule)
        floor_t = floor_range(FILL_FLOOR_RULE)          # for the 'tested' values (pre-exact rule)
        _floor_of[af] = floor

        def cut_args(L, a, b, n):        # keep the first n args: drop bytes [a, b) and any replacement inside them
            for k in [k for k in repl if a <= k < b]: del repl[k]
            repl[L['npos']] = (L['npos'] + 2, struct.pack('<H', n))
            return a

        def ival(ap, k):                 # plain int argument k, else None
            w = struct.unpack_from('<I', T.d, ap[k])[0]
            return None if w & 3 != 2 else ((w >> 2) - (1 << 30) if w >> 2 >= 1 << 29 else w >> 2)

        def old_rule(i, cam4, last, depth, convert, mult, zall, fr):
            """the pre-exact (1.1.0) rewrite: BB_TO_BG x1000/depth, FILL_FLOOR range fr, x mult on imported (zall: on
            every Cr6Ti CG)"""
            new = list(cam4); fl = zm = False
            if depth: new[3] = round(cam4[3] * 1000 / depth)
            cg = bool(last and last['cg']); bbn = bool(last and last['bb'] and not convert)
            if fr and cg and not bbn and fr[0] <= i < fr[1] and new[3] < fr[2]:
                new = [0, 0, 0, fr[2]]; fl = True           # whole CG, filling the screen, centred
            if (last and last['imported']) or (zall and cg):
                new[3] = round(new[3] * mult); zm = True
            return new, fl, zm

        last = None; depth = None        # last picture call (heap order) and, under bb2bg, its billboard depth
        for i, ins in enumerate(T.instrs):
            r0 = T.ins_res[i][0] if T.ins_res[i] else None
            if ins[2] != 'CVmCall' or not (r0 and isinstance(r0[0], tuple)): continue
            if r0[1] in (BG_HELPER, BILLBOARD_HELPER):
                img = next((x for x in T.ins_res[i][1:] if x and isinstance(x[0], tuple)), None)
                bb = r0[1] == BILLBOARD_HELPER
                L = ins[3]; ap = L['argpos']
                cnv = bool(conv and BB_CONVERT and bb and i >= lo_p)
                last = dict(key=(af, i), bb=bb, conv=cnv, img=[img[0][0], hex(img[1])] if img else None,
                            imported=bool(img and img[0][0] in IMG_CLASSES and not (
                                mapped(img[1]) is not None and image_identical(img[1], img[2], mapped(img[1])))),
                            cg=bool(img and img[0][0] == 'Cr6Ti'), geo=pic_geom(img))
                depth = None
                if cnv:
                    d4 = struct.unpack_from('<I', T.d, ap[4])[0]
                    if len(ap) != 7 or d4 & 3 != 2: raise BuildError('billboard call %d: unexpected args' % i)
                    depth = (d4 >> 2) or 1000
                    if BB_KEEP21:       # AFR_TEST bb21: (picture, AF's 21)
                        repl[cut_args(L, ap[2], ap[-1], 2)] = (ap[-1], b'')
                    else:               # (picture, 2)
                        repl[cut_args(L, ap[1], ap[-1], 2)] = (ap[-1], struct.pack('<I', (2 << 2) | 2))
                    _bb2bg[0] += 1
                if last['geo']:         # projection inputs of both engines (see FRAME_RULE)
                    W, H, hw, hh = last['geo']
                    eid = ival(ap, 1) if len(ap) > 2 else None
                    if eid is None: raise BuildError('picture call %d: exclusive id is not a plain int' % i)
                    path = '3D' if eid & 0x10 else '2D'
                    if bb:              # 39b5f9d(picture, id, X, Y, depth, scale): AF corner z = depth (2D: 720 + depth),
                        if len(ap) != 7 or None in [ival(ap, k) for k in (2, 3, 4)]:  # PM HumanIn Z = depth (0 -> 720)
                            raise BuildError('billboard call %d: unexpected args' % i)
                        px, py, dz = ival(ap, 2), ival(ap, 3), ival(ap, 4)
                        g_af = dict(path=path, depth=dz if path == '3D' else 720 + dz, px=px, py=py)
                        g_pm = dict(path=path, depth=dz or 720, px=px, py=py)
                        last['depth'] = dz
                    else:               # background: z 0 + flag 0x200 -> 720 in both
                        g_af = dict(path=path, depth=720 if path == '2D' else 0, px=0, py=0)
                        g_pm = dict(path=path, depth=720, px=0, py=0)
                    if cnv:             # bb2bg: PM background helper, id 2 (bb21: 21)
                        g_pm = dict(path='3D' if BB_KEEP21 else '2D', depth=720, px=0, py=0)
                    for g in (g_af, g_pm): g.update(W=W, H=H, hw=hw, hh=hh)
                    last.update(af=g_af, pm=g_pm)
                _pic_info[(af, i)] = last
            elif r0[1] in CAMERA_HELPERS:
                ap = ins[3]['argpos']; n = len(ap) - 1
                if n < 4: continue
                vals = [ival(ap, k) for k in range(n)]
                if None in vals[:4]: continue
                x, y, rot, v = vals[:4]
                mode = vals[4] if n > 4 else None
                pos = tuple(vals[5:8]) if r0[1] == CAMERA_HELPER8 and n >= 8 and None not in vals[5:8] else (0, 0, 0)
                # 'tested': the pre-exact rule's values (x1.2 on imports, FILL_FLOOR), as in the builds the owner
                # checked on 2026-11-07 afternoon / evening before the exact framing (88ca03a8 / f85c4b64)
                tested = old_rule(i, (x, y, rot, v), last, None, False, 1.2, False, floor_t)[0]
                info = dict(af=(x, y, rot, v), pos=pos, mode=mode, pm_mode=mode, helper=r0[1], tested=tuple(tested),
                            pic=last['key'] if last else None,
                            ms=vals[5] if r0[1] == CAMERA_HELPER and n > 5 else None)
                _cam_info[(af, i)] = info
                if i in fixed:          # CAMERA_FIX (written below)
                    fv = next(vv for (h_, ii), vv in camera_fix().items() if ii == i and af.endswith(h_))
                    info.update(new=tuple(fv[:4]), pm_mode=fv[4], note='CAMERA_FIX'); continue
                if OLD_ZOOM and not PRE_EXACT:  # the exact framing: the 2007 values (bb2bg implies PRE_EXACT)
                    new = [x, y, rot, v]
                    note = 'exact: 2007 value' + (' (imported)' if last and last['imported'] else
                                                  ' (PM copy)' if last and last['cg'] else '')
                elif OLD_ZOOM or (BB_CONVERT and floor is not None and floor[0] <= i < floor[1]):
                    new, fl, zm = old_rule(i, (x, y, rot, v), last, depth, BB_CONVERT, IMPORTED_IMAGE_ZOOM, ZOOM_ALL,
                                           floor)
                    _floored[0] += fl; _zoomed[0] += zm
                    note = 'pre-exact rule: ' + ' + '.join(
                        (['x1000/depth (bb2bg)'] if depth else []) + (['FILL_FLOOR'] if fl else [])
                        + (['x%g (%s)' % (IMPORTED_IMAGE_ZOOM, 'imported' if last['imported'] else 'PM copy')]
                           if zm else []) or ['AF value' + (' (PM copy)' if last and last['cg'] else '')])
                else:
                    nd, note = frame_rule((x, y, rot) + pos, v, last)
                    new = [x, y, rot, nd]
                if NEAR_PLANE_ON and mode == 1:
                    nn = near_plane(list(new), pos, last)
                    if nn != list(new):
                        _near_log.append(('%s@%d' % (af, i), tuple(new), tuple(nn))); note += ' + nearplane'; new = nn
                info.update(new=tuple(new), note=note)
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


# ---------------------------------------------------------------- CAMERA_KEEP analysis
COMMITS = {CAMERA_UPDATE: 'apply', FADE_HELPER: 'screen effect', SHAKE_HELPER: 'shake apply'}   # commit pending pictures


def _msg_id(H, j):
    return struct.unpack_from('<I', H.d, base_pos(H.d, H.instrs[j][0]) + 4)[0] & 0xFFFFF


def _is_start(c):
    return c['mode'] is not None and 64 <= c['mode'] < 96


def _cam_state(c, key):
    return dict(cam=tuple(c['af'][:3]) + tuple(c['pos']), dist=c['af'][3], src='%s@%d' % key)


def _cam_triggers(c):
    """camera call that triggers the screen itself: d13d87 / 27e92e99 mode 3, or remainder r with r % 4 == 2
    (+ OM_ParseScreenTrigger(P5); camera-modes modes.json)"""
    m = c['pm_mode']
    if m is None or m == 1 or 64 <= m < 96 or c['helper'] != CAMERA_HELPER: return False
    if m == 3: return True
    r = m - 128 if m >= 128 else m
    r = r - 96 if r >= 96 else (r - 32 if r >= 32 else r)
    return r % 4 == 2


def _arg_int(key, i, k):
    ap = _targ[key].instrs[i][3]['argpos']
    if len(ap) < k + 2: return None
    w = struct.unpack_from('<I', _targ[key].d, ap[k])[0]
    return None if w & 3 != 2 else ((w >> 2) - (1 << 30) if w >> 2 >= 1 << 29 else w >> 2)


def af_state_before(bl, lo):
    """AF's camera right before AF instruction lo of the part's heap: the last camera call before it that is not a
    64-95 start store (a store is followed by its move, whose target is the state). The official patch's script is
    used where it has the last line before lo (the 2007 game the restoration follows is the patched one) and no camera
    call lies between that line and lo. Returns (state, unpatched state, patched state)."""
    name = bl['af']; A = af_heap(name)

    def walk(key, j0):
        for j in range(j0, -1, -1):
            c = _cam_info.get((key, j))
            if c and not _is_start(c): return _cam_state(c, (key, j))
        return None
    sa = walk(name, lo - 1); sp = None
    Pp = af_patch_heap(name)
    m = next((j for j in range(lo - 1, -1, -1) if A.instrs[j][2] == 'CVmMsg'), None)
    if Pp is not None and m is not None and name + '@patch' in _targ and not any(
            (name, j) in _cam_info for j in range(m + 1, lo)):
        mid = _msg_id(A, m)
        tw = [j for j, t in enumerate(Pp.instrs) if t[2] == 'CVmMsg' and _msg_id(Pp, j) == mid]
        if len(tw) == 1: sp = walk(name + '@patch', tw[0] - 1)
    return (sp or sa), sa, sp


def keep_spec(st, pic, mode):
    """(template, args, rule note) of an inserted camera call: AF camera state st on picture pic, mode 1 or 64"""
    x, y, rot, cx, cy, cz = st['cam']
    if OLD_ZOOM and not PRE_EXACT:             # the exact framing: the kept 2007 camera as it was
        d = st['dist']
        note = 'exact: 2007 value' + (' (imported)' if pic and pic['imported'] else ' (PM copy)' if pic and pic['cg']
                                      else '')
    elif OLD_ZOOM or (pic and pic['conv']):    # the pre-exact rule, as old_rule applies it to a camera call on pic
        d = st['dist']; note = []
        if pic and pic['conv']: d = round(d * 1000 / (pic.get('depth') or 1000)); note.append('x1000/depth (bb2bg)')
        fl = _floor_of.get(pic['key'][0]) if pic else None
        if (fl and pic['cg'] and not (pic['bb'] and not BB_CONVERT) and fl[0] <= pic['key'][1] < fl[1]
                and d < fl[2]):
            x = y = rot = 0; d = fl[2]; note.append('FILL_FLOOR')
        if pic and (pic['imported'] or (ZOOM_ALL and pic['cg'])):
            d = round(d * IMPORTED_IMAGE_ZOOM)
            note.append('x%g (%s)' % (IMPORTED_IMAGE_ZOOM, 'imported' if pic['imported'] else 'PM copy'))
        note = 'pre-exact rule: ' + (' + '.join(note) or 'AF value' + (' (PM copy)' if pic and pic['cg'] else ''))
    else:
        d, note = frame_rule(st['cam'], st['dist'], pic)
    if NEAR_PLANE_ON and mode == 1:
        nn = near_plane([x, y, rot, d], (cx, cy, cz), pic)
        if nn != [x, y, rot, d]:
            _near_log.append(('kept camera (planned insert) on %s@%d' % pic['key'], (x, y, rot, d), tuple(nn)))
        if nn != [x, y, rot, d]: x, y, rot, d = nn; note += ' + nearplane'
    if mode == 1 and (cx, cy, cz) == (0, 0, 0): return CAM_SET_PM, [x, y, rot, d, 1, 0], note
    return CAM8_PM, [x, y, rot, d, mode, cx, cy, cz], note


def camera_keep(bl, plan):
    """Kept-camera inserts of one part. plan: [(role, k, H, src, i)] in output order. Returns (before, after, rows):
    plan index -> [(template, args, row)] emitted right before / after that instruction; rows: one per shot that needs
    the kept camera (inserted or not, with the reason)."""
    lo = min([bl['lo']] + list(bl.get('lead', ())))
    if bl.get('cam_from') is not None: lo = bl['cam_from']     # F17: the continuation starts from route A's camera
    state, sa, sp = af_state_before(bl, lo)
    before, after, rows = {}, {}, []
    start_rows = dict(part_start=state, unpatched=sa, patched=sp)
    shot = [None]

    def close(why, ms):
        s = shot[0]; shot[0] = None
        if s is None: return
        row = dict(pic='%s@%d' % s['key'], plan=s['p'], closed=why, ms=ms)
        if s['first'] is None:
            row['kind'] = 'A'; st = s['state']
            if why.startswith('superseded'): row['action'] = 'none (picture replaced before any apply)'
            elif why == 'part end': row['action'] = 'none (no apply before the part ends)'
            elif st is None: row['action'] = 'none (no AF camera before it in this script)'
            else:
                t, vals, note = keep_spec(st, s['pic'], 1)
                after.setdefault(s['p'], []).append((t, vals, row))
                row.update(action='set after the picture call', kept=st, pm=vals, rule=note)
        else:
            pf, c, st = s['first']
            m = c['pm_mode']
            if m is None or m in (1, 3) or 64 <= m < 96: return
            row.update(kind='B', move='%s@%d' % c['key'], move_mode=m)
            if why.startswith('superseded') or why == 'part end': row['action'] = 'none (%s)' % why
            elif ms == 0: row['action'] = 'none (0 ms apply: the move is instant)'
            elif st is None: row['action'] = 'none (no AF camera before it in this script)'
            else:
                t, vals, note = keep_spec(st, s['pic'], 64)
                before.setdefault(pf, []).append((t, vals, row))
                row.update(action='start store before the move', kept=st, pm=vals, rule=note)
        rows.append(row)

    for p, (role, k, H, src, i) in enumerate(plan):
        key = (src.name, i)
        if key in _pic_info:
            if shot[0]: close('superseded by the next picture call', None)
            shot[0] = dict(p=p, key=key, pic=_pic_info[key], first=None, state=state)
            continue
        c = _cam_info.get(key)
        if c:
            c['key'] = key
            if shot[0] and shot[0]['first'] is None: shot[0]['first'] = (p, c, state)
            if not _is_start(c): state = _cam_state(c, key)
            if _cam_triggers(c): close('camera trigger', c['ms'])
            continue
        if H.instrs[i][2] == 'CVmCall':
            r = H.ins_res[i][0] if H.ins_res[i] else None
            t = r[1] if r and isinstance(r[0], tuple) else None
            if t in COMMITS:        # (F15: an entry replay's 'Z' apply is emitted with 0 ms)
                ms = 0 if ((role == 'lead' and k == 2) or (role == 'entry' and bl['entry'][k][0] == 'Z')
                           or t == SHAKE_HELPER) else _arg_int(src.name, i, 1)
                close(COMMITS[t], ms)
    if shot[0]: close('part end', None)
    return before, after, rows, start_rows


PREWRAP_MAX = 28  # verified live: unbroken lines up to 28 full-width chars fit PM's English text layout
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

    def rm(src, obj):        # F04 (C7): SOUND_REMAP, keeping the AF object's key allocation point
        if fix_on('c7') and src is not None and src.archive == 'AF' and (bl['name'], obj[1]) in SOUND_REMAP:
            key_alloc(obj[1], obj[0], obj[2])
            return ('PM', SOUND_REMAP[(bl['name'], obj[1])])
        return remap(src, obj)
    rm_, ka_ = rm, key_alloc
    if 'hutdepth' in AFR_TEST and bl['name'] == HUTDEPTH_PART:     # F19 (opt-in): AF 7696d25b -> the re-framed copy
        rm_ = lambda s, o: ('NEW', HUTDEPTH_AF) if (o[1] == HUTDEPTH_AF and s is not None and s.archive == 'AF') else rm(s, o)
        ka_ = hutdepth_key_alloc
    B = (VoiceBuilder if fix_on('c15') else Builder)(pad_count, rm_, templates, packed, ka_)    # F09
    B.schema_override = dict(pm_schema); B.schema_override.update({n: PM_SCHEMA for n in VM_CLASSES})
    B.constructed[MSGBOX_PM['off']] = dict(cls=MSGBOX_PM['cls'], enc_size=enc_size(MSGBOX_PM['size'] + 3),
                                           parent=MSGBOX_PM['parent'])
    table = ['\x00']; tlen = [1]
    tail = [('null',), ('msgbox',)]; vidx = {}; tail_x45 = set()   # (F16: tail indices rendered in X45 import mode)
    tail_kashi = set()       # F23: tail indices first used by an added (KASHI) line, rendered in KASHI import mode
    base_mode = bl.get('import_mode', False)      # import mode outside lead-in / entry / added stretches (F23's start: KASHI)
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
    added = set()            # output instructions added after 1.0.0 (ids from ADD_ID_BASE)
    keep_added = set()       # CAMERA_KEEP inserts (ids from KEEP_ID_BASE)
    # restore-audit fixes: output instructions each fix adds (ids from its own range; see OVL_ID_BASE .. EXIT_ID_BASE)
    patch_added, fixwin_added, x45_added, kashi_added = set(), set(), set(), set()     # F14, F12, F16, F23
    entry_out, exit_out, excl_added, ovl_added = set(), set(), set(), set()            # F15, F21, F13, F10
    fixend_added, ycont_call = set(), set()                                             # F11, F17
    winshow_added = set()                                                               # F26

    def c3_emptied(patched, unp):
        """F03 (C3): the update's twin of this line has 0 text bytes and no voice, the unpatched line has text."""
        return bool(fix_on('c3') and patched and not patched[0] and not patched[1] and unp)
    c3_en = {}               # F03 English: kept line index -> unpatched bytes of the emptied line right after it
    if fix_on('c3') and EN_DATA:
        prev = None
        for i in bl['keep']:
            if A.instrs[i][2] != 'CVmMsg': continue
            u = A.instrs[i][5][0][1]
            if c3_emptied(af_patch_msgs(bl['af']).get(_msg_id(A, i)), u) and prev is not None: c3_en[prev] = u
            prev = i

    def emit_pm(h, j0, j1, v=None):
        """Copy PM instructions [j0, j1) of PM heap h (fresh index map per copy, see below); v: new value of a CVmSync."""
        s = Src(pm_srcs[h].h, 'PM', h)
        if v is not None:
            e = s.h.instrs[j0][1]; s.raw_repl = {e - 4: (e, struct.pack('<I', v))}
        B.emit_instructions(s, j0, j1)

    def emit_pm_at(h, j):
        """Copy the one PM instruction j of PM heap h (restore-audit helper)."""
        emit_pm(h, j, j + 1)

    # F12: the text window is hidden at this point of the output (linear, in output order); F17's continuation starts
    # with yuuhi_a's state at its call
    win_hidden = [bool(bl.get('win_start'))]

    def note_hide(H, src, i):
        """F12: after emitting instruction i of H: a hiding helper or an OM_Invisible on the message box hides it."""
        r = H.ins_res[i][0] if H.ins_res[i] else None
        if H.instrs[i][2] == 'CVmCall' and r and isinstance(r[0], tuple):
            if (B.remap(src, r)[1] if src.archive == 'AF' else r[1]) in PM_WIN_HIDERS: win_hidden[0] = True
        elif (H.instrs[i][2] == 'CVmGenericMsg' and 'OM_Invisible' in str(H.instrs[i][3]) and r
              and isinstance(r[0], tuple) and r[1] in (MSGBOX_AF, MSGBOX_PM['off'])):
            win_hidden[0] = True

    def fixwin(H, src, i, at):
        """F12: before AF white fade i of H while the window is shown: PM's OM_Invisible as output `at` (FIXWIN id).
        Returns the number of instructions emitted (0 or 1)."""
        r = H.ins_res[i][0] if H.ins_res[i] else None
        if not (fix_on('fixwin') and not win_hidden[0] and src.archive == 'AF' and H.instrs[i][2] == 'CVmCall'
                and r and isinstance(r[0], tuple) and r[1] == AF_WHITE_FADE): return 0
        emit_pm_at(*FIXWIN_TPL); fixwin_added.add(at); win_hidden[0] = True; stats['fixwin'] += 1
        return 1

    def winshow(text, at):
        """F26: before a line whose text has no code unit > 0x20 while the window is hidden: PM's OM_Visible on its
        message box as output `at` (WINSHOW id). Returns the number of instructions emitted (0 or 1)."""
        if not (fix_on('winshow') and win_hidden[0] and not any(ord(c_) > 0x20 for c_ in text)): return 0
        _ec = B.emit_class

        def ec(name, schema, kind, defbytes=None):      # FIXWIN_TPL's OM class -> PM's '&-OM_Visible' (WINSHOW_OM's)
            if kind == 'rdef' and name == '&-OM_Invisible': return _ec(*_winshow_om())
            return _ec(name, schema, kind, defbytes)
        B.emit_class = ec
        try: emit_pm_at(*FIXWIN_TPL)
        finally: del B.emit_class
        winshow_added.add(at); win_hidden[0] = False; stats['winshow'] += 1
        return 1

    def emit_scene_call(key, size):
        """A scene of this build called as one output instruction (F17, F23): patch_pm's inserted-call form - CVmCall,
        one CRsa ref (flag 0xC108, parent = the route-folder pad) to `key` with enc size `size`, no arguments, no
        extras."""
        P_ = pm_heaps[bl['pm']]; crsa_ = next(ev for ev in P_.ev if ev[0] == 'cdef' and ev[4][0] == 'CRsa')
        B.emit_class('CVmCall', PM_SCHEMA, 'cdef'); B.out += struct.pack('<II', 0, 0)
        B.ensure_pad(); B.emit_class('CRsa', crsa_[4][1], 'cdef', P_.d[crsa_[1]:crsa_[2]])
        B.out += struct.pack('<HII', 0xC108, key, size) + struct.pack('<H', B.pad_first) + b'\x00'
        B.alloc()                        # the scene object's load-array entry
        B.out += struct.pack('<H', 0) + b'\x00'

    def emit_inserts(lst, at):
        """CAMERA_KEEP: emit camera calls copied from a PM template with new int args, as output instructions at...;
        returns their number"""
        for k, (tpl, vals, row) in enumerate(lst or ()):
            h, j = tpl; s = Src(pm_srcs[h].h, 'PM', h); e = s.h.instrs[j][1]; n = len(vals)
            s.raw_repl = {e - 1 - 4 * (n - q): (e + 3 - 4 * (n - q), struct.pack('<I', ((v << 2) | 2) & 0xFFFFFFFF))
                          for q, v in enumerate(vals)}
            B.emit_instructions(s, j, j + 1)
            keep_added.add(at + k); row['out'] = at + k
            stats['camera_keep_' + ('set' if vals[4] == 1 else 'start')] += 1
            win_hidden[0] = True                # F12: a camera insert (27e92e99 / 8a8b0e89) hides the window
        return len(lst or ())

    def emit_staging(H, src, i, at):
        """Emit one call / sync / message / sound instruction of source heap H as output instruction `at`. Returns the
        number of extra output instructions: PM overlay layers inserted after a special hut background (1.0.0 has them,
        main ids), the 2nd instruction of a shock port, the apply after a shake call and a shake wait (added after 1.0.0:
        listed in `added`)."""
        ins = H.instrs[i]; name = ins[2]; lo, hi = H.ins_ev[i]
        if (src.name, i) in _shock25:           # AF case-25 screen shock -> PM's port pair (the first keeps the id)
            h, j0, j1 = SHOCK_PM
            emit_pm(h, j0, j1)
            added.update(range(at + 1, at + j1 - j0))
            stats['shock25'] += 1; _shock25_done[0] += 1
            return j1 - j0 - 1
        sw = _shake_wait.get((src.name, i))
        if sw and isinstance(sw[1], BuildError): raise BuildError('%s %s@%d: %s' % (bl['name'], src.name, i, sw[1]))
        if sw and sw[0] == 'replace':          # b=16 wait on the shake var -> timed wait (same id)
            emit_pm(SHAKE_WAIT_PM[0], SHAKE_WAIT_PM[1], SHAKE_WAIT_PM[1] + 1, sw[1])
            stats['shake_wait'] += 1; _shake_wait_done['replace'] += 1
            return 0
        if name in ('CVmCall', 'CVmSync', 'CVmGenericMsg'):
            if (src.name, i) in _shake_unpaired: _shake_unpaired_out.append((src.name, i))
            B.emit_instructions(src, i, i + 1)
            if name == 'CVmCall': B.out += b'\x00'
            note_hide(H, src, i)                # F12
            extra = 0
            if (src.name, i) in _shake_calls:   # start the queued shake now (PM dispatches it only at an apply)
                emit_pm(SHAKE_APPLY_PM[0], SHAKE_APPLY_PM[1], SHAKE_APPLY_PM[1] + 1)
                added.add(at + 1); extra = 1
                stats['shake_apply'] += 1; _shake_apply_done[0] += 1
            if sw:                              # shake call whose wait flag is 0: AF's helper waits for the shake
                emit_pm(SHAKE_WAIT_PM[0], SHAKE_WAIT_PM[1], SHAKE_WAIT_PM[1] + 1, sw[1])
                added.add(at + 1 + extra)
                stats['shake_wait'] += 1; _shake_wait_done['after'] += 1
                return extra + 1
            if extra: return extra
            res = H.ins_res[i] or []
            bg = (res[1][1] if name == 'CVmCall' and res and isinstance(res[0][0], tuple) and res[0][1] == BG_HELPER
                  and len(res) > 1 and res[1] and isinstance(res[1][0], tuple) else None)
            if bg in BG_OVERLAYS or (fix_on('c4') and bg in BG_OVERLAYS_C4):     # F10: the kasumi hut's set (OVL ids)
                hname, j0, j1 = BG_OVERLAYS[bg] if bg in BG_OVERLAYS else BG_OVERLAYS_C4[bg]
                # fresh index map per copy: each OM_SetVarData message appends a load-array entry every time it
                # appears, so a map reused from an earlier copy would skip those entries (index drift -> bad heap)
                B.emit_instructions(Src(pm_srcs[hname].h, 'PM', hname), j0, j1)
                if bg in BG_OVERLAYS: stats['bg_overlay_calls'] += 1
                else: ovl_added.update(range(at + 1, at + 1 + j1 - j0)); stats['bg_overlay_c4'] += 1
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
                t = B.remap(src, (ecls, eoff, esize))      # the part's remap (F04 SOUND_REMAP), as the effect slot
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
    twin = {}                # F01 (C10): unpatched FlagOp index -> its update twin (stretches with branches)
    c2_fold, c2_lines, c2_wait = set(), set(), {}   # F14: folded update items, the update-only lines, timed waits (ms)
    p_line = {}              # F14: update message id -> its update CVmMsg indices
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
        if fix_on('c2'):
            # F14 (a): fold the update-only lines between the update twins of two consecutive kept lines into the next
            # kept line's segment, (d) dropping C2_DROP and the b=1 shake-var syncs on the way
            for j, t in enumerate(Pp.instrs):
                if t[2] == 'CVmMsg': p_line.setdefault(_msg_id(Pp, j), []).append(j)
            af_mids = {_msg_id(A, i) for i, t in enumerate(A.instrs) if t[2] == 'CVmMsg'}

            def c2_keep(j):
                if (bl['af'], j) in C2_DROP: return False
                t = Pp.instrs[j]; r = Pp.ins_res[j][0] if Pp.ins_res[j] else None
                if (t[2] == 'CVmSync' and r and isinstance(r[0], tuple) and r[1] == SHAKE_VAR
                        and Pp.d[t[1] - 5] == 1):
                    v = struct.unpack_from('<i', Pp.d, t[1] - 4)[0]
                    if v == 0: return False
                    c2_wait[j] = v
                return True
            for a, b in zip(mids, mids[1:]):
                if useg[b] is None or pseg.get(b) is None or len(p_line.get(a, ())) != 1 or len(p_line.get(b, ())) != 1:
                    continue
                ja, jb = p_line[a][0], p_line[b][0]
                between = sorted((p_line[m][0], m) for m in pseg if m != 'end' and m not in af_mids
                                 and len(p_line.get(m, ())) == 1 and ja < p_line[m][0] < jb)
                if not between: continue
                fold = []
                for jm, m in between:
                    if pseg[m] is None: raise BuildError('C2 %s: update line %x has no unique segment' % (bl['name'], m))
                    fold += [j for j in pseg[m] if c2_keep(j)] + [jm]; c2_lines.add(jm); _c2_done['fold'].add((bl['name'], m))
                bad = [j for j in fold if Pp.instrs[j][2] not in ('CVmCall', 'CVmSync', 'CVmSound', 'CVmGenericMsg')
                       and j not in c2_lines or 'OM_VramAgesImageIn' in str(Pp.instrs[j][3])]
                if bad: raise BuildError('C2 %s: folded items %s' % (bl['name'], [(j, Pp.instrs[j][2]) for j in bad]))
                pseg[b] = fold + pseg[b]; c2_fold.update(fold); stats['c2_fold'] += len(between)

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
            same = [stage_sig(A, i) for i in u_non] == [stage_sig(Pp, j) for j in p_non]
            if same and fix_on('c11'):
                # F08 (C11): a stretch whose only change is an operand stage_sig does not see (an object argument's
                # inline data, e.g. the update's shake data, or a sprite call's arguments after an object argument) is
                # the update's too: 2007 runs the update's values (marimo_5caf15_a lines 16 / 21, marimo_chapter 329,
                # 401, 405). Only this 'unchanged' test; the first-stretch anchor keeps stage_sig.
                same = [operand_sig(A, bl['af'], i) for i in u_non] == [operand_sig(Pp, bl['af'] + '@patch', j)
                                                                       for j in p_non]
                if not same: stats['patch_stretch_c11'] += 1
            if same: return
            # branches must form one contiguous block of the same size in both versions; patched staging before it is
            # emitted at the unpatched branch block, staging after it right before the line
            def contiguous(lst, flow):
                return not flow or lst[lst.index(flow[0]):lst.index(flow[0]) + len(flow)] == flow
            if (any(Pp.instrs[j][2] not in ('CVmCall', 'CVmSync', 'CVmSound', 'CVmGenericMsg') and j not in c2_lines
                    for j in p_non)     # (F14: a folded update-only line is emitted by emit_c2_line)
                    or len(p_flow) != len(u_flow) or not contiguous(p_keep, p_flow) or not contiguous(u_all, u_flow)):
                stats['patch_staging_kept_flow'] += 1; return
            if p_flow:
                k0 = p_keep.index(p_flow[0])
                hooks[u_flow[0]] = p_keep[:k0]; hooks[msg_at[mid]] = p_keep[k0 + len(p_flow):]
                if fix_on('c10'): twin.update(zip(u_flow, p_flow))
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

    # F15: the entry replay (ENTRY_REPLAY), planned and emitted before the part's first kept instruction, or after its
    # Marimo route guard (that FlagOp stays the first instruction)
    if bl.get('entry') and Pp is None: raise BuildError('entry replay %s: no update heap' % bl['name'])
    ent = [('entry', k, Pp, srcP, j) for k, (_, j) in enumerate(bl.get('entry', ()))]
    guard = bool(ent) and A.instrs[bl['keep'][0]][2] == 'CVmFlagOp'
    ent_done = [False]

    def due(i):
        return bool(ent) and not ent_done[0] and not (guard and i == bl['keep'][0])

    def emit_entry(n_out, pk):
        """F15: emit the part's entry replay as output n_out.. (plan items pk..); returns (n_out, pk) after it."""
        objs_e = set(B.objs); _lead_mode[0] = 'entry'
        try:
            for kind, j in bl['entry']:
                at = n_out; saved = {}          # the item with the CAMERA_KEEP inserts planned at it (ENTRY slot ids)
                n_out += emit_inserts(keep_before.get(pk), n_out); plan_out[pk] = n_out
                if kind == 'Z':         # the apply: both arguments (transition, ms) -> int 0
                    ap = _targ[bl['af'] + '@patch'].instrs[j][3]['argpos']
                    if (Pp.instrs[j][2] != 'CVmCall' or len(ap) < 3
                            or any(struct.unpack_from('<I', Pp.d, ap[q])[0] & 3 != 2 for q in (0, 1))):
                        raise BuildError('entry %s: apply %d has unexpected args' % (bl['name'], j))
                    for q in (0, 1):
                        saved[ap[q]] = srcP.raw_repl.get(ap[q]); srcP.raw_repl[ap[q]] = (ap[q] + 4, struct.pack('<I', 2))
                try:
                    n_out += 1 + emit_staging(Pp, srcP, j, n_out)    # a hut picture brings its BG_OVERLAYS
                finally:
                    for p_, v_ in saved.items():
                        if v_ is None: del srcP.raw_repl[p_]
                        else: srcP.raw_repl[p_] = v_
                n_out += emit_inserts(keep_after.get(pk), n_out); pk += 1; stats['entry_replay_instrs'] += 1
                eo = set(range(at, n_out)); entry_out.update(eo); keep_added.difference_update(eo)
        finally:
            _lead_mode[0] = False
        for t in [t for t in B.objs if t not in objs_e and t[0] == 'NEW']:
            del B.objs[t]                # the part's own references import (or reuse) the main-range object
        return n_out, pk

    # F14 (e): keys. A folded item may use an import that the build without F14 allocates only later in the part
    # (mikoto P2390 / P2395: background 4ce2cdeb, first used there at the hook after 227c, after 4d040e3f): allocating it
    # at the fold would swap two main-range keys. Such an import (plain body: no nested ref, no stream, no CRimp / re-
    # encode) gets a placeholder enc_off at the fold; its key is allocated at the first use outside the folded items, the
    # allocation point of the build without F14, and the placeholder is patched (one object, the same key). An import
    # that only the folded items use is refused.
    c2_defer = {}            # import target -> (AF offset, class, size, placeholder, enc_size)
    c2_emitting = [False]
    if c2_fold:
        _ka, _slot = B.key_alloc, B.object_slot

        def ka_c2(af_off, cls, size):
            if not c2_emitting[0] or af_off in new_objs or _lead_mode[0]: return _ka(af_off, cls, size)
            raw = af_raw(af_off, size); n_ = af_header(raw)[0]
            if (not cls or cls[0] in ('COptimizedObs', 'CRimp') or af_off in BB_SHRINK or is_naked_oor(raw)
                    or body_refs(bytes(raw[n_:]))):
                raise BuildError('C2 %s: folded item needs import %x (%s) before its allocation point' % (bl['name'], af_off, cls))
            ph = 0xFEDC0000 + len(c2_defer); es = enc_size(2 + len(raw) - n_)
            c2_defer[('NEW', af_off)] = (af_off, cls, size, ph, es)
            return ph, es

        def slot_c2(src, cls, off, size, R=None):
            if c2_defer and not c2_emitting[0]:
                t = B.remap(src, (cls, off, size))
                if t in c2_defer:
                    af_off, cls_, size_, ph, es = c2_defer.pop(t)
                    eo, es2 = _ka(af_off, cls_, size_)          # the allocation point of the build without F14
                    pat = struct.pack('<I', ph)
                    if es2 != es or B.out.count(pat) != 1:
                        raise BuildError('C2 %s: deferred key of %x (size %s / %s, placeholder seen %d times)' % (
                            bl['name'], af_off, es, es2, B.out.count(pat)))
                    q = B.out.find(pat); B.out[q:q + 4] = struct.pack('<I', eo); stats['c2_deferred_key'] += 1
            return _slot(src, cls, off, size, R)
        B.key_alloc, B.object_slot = ka_c2, slot_c2

    def emit_c2_line(j, at):
        """F14 (c): update-only line j of the update heap, folded into a hook: a CVmMsg3 with the update's text (U+0005
        alone or empty, checked) in both slots, the update's dw2 flags (C2_LINE_FLAGS) and its voices, each with the F09
        speaker rules (its tail entry renders from the update heap's own ref)."""
        ins = Pp.instrs[j]; lo_, hi_ = Pp.ins_ev[j]
        dw2_ = struct.unpack_from('<I', Pp.d, base_pos(Pp.d, ins[0]) + 4)[0]
        raw = ins[5][0][1]
        if raw not in (b'', b'\x05') or dw2_ & 0x04200000 or C2_LINE_FLAGS.get(dw2_ & 0xFFFFF) != dw2_ & 0xFFC00000:
            raise BuildError('C2 %s: update line %d (%x) is not a U+0005 / empty line with the planned flags' % (
                bl['name'], j, dw2_ & 0xFFFFF))
        res = Pp.ins_res[j]
        if not (res[0][0][0] == 'CMsgSelBox' and res[0][1] == MSGBOX_AF):
            raise BuildError('C2 %s: update line %d uses message box %s' % (bl['name'], j, res[0]))
        voices = []; spk_box = None
        for n_v, v in enumerate([v for v in res[1:] if v and v[0] != 'null']):
            if v[0][0] != 'COptimizedObs': raise BuildError('C2 voice class %s' % (v,))
            if fix_on('c15'):           # F09
                oc = af_voice_ocean(bl['af'], v[1])[1]
                if oc in VOICE_OCEAN_PM: VoiceBuilder.voice_parent[v[1]] = VOICE_OCEAN_PM[oc]
                elif oc in VOICE_SPK_BOX and n_v == 0: spk_box = VOICE_SPK_BOX[oc]
                else: raise BuildError('C15: voice %x (entry %d) in AF ocean %x not covered' % (v[1], n_v, oc))
            if v[1] not in vidx:
                R = next((Pp.ev[k] for k in range(lo_, hi_) if Pp.ev[k][0] == 'ref' and Pp.ev[k][6] == v[1]), None)
                vidx[v[1]] = len(tail); tail.append(('voice', v, R, srcP))
            voices.append(vidx[v[1]])
        spk = 0
        if spk_box is not None:
            if ('spk', spk_box) not in vidx:
                vidx[('spk', spk_box)] = len(tail); tail.append(('spk', spk_box, None))
            spk = vidx[('spk', spk_box)]; stats['c15_speaker'] += 1
        text = raw.decode('cp932'); toff = add_text(text)     # the same text in both slots
        if any(ord(c_) > 0x20 for c_ in text): win_hidden[0] = False      # F12 (never: U+0005 / empty)
        ws = winshow(text, at)                                            # F26: 2007 shows the window here
        B.emit_class('CVmMsg3', PM_SCHEMA, 'cdef')
        B.out += struct.pack('<IIHHBB', 0, dw2_ & 0xFFC00000, 1, 0, 2, len(voices))
        B.out += struct.pack('<III', toff, 0, 0) * 2
        for n_v, vi in enumerate(voices):
            B.out += struct.pack('<HHHHBB', vi, spk if n_v == 0 else 0, 0, 0, 0, 0)
        stats['CVmMsg'] += 1; stats['c2_line'] += 1      # (the header's message count)
        return ws

    # output order of the source instructions (lead-in replays, patch staging, kept AF instructions) for CAMERA_KEEP
    plan = [('lead', k, A, srcA, j) for k, j in enumerate(bl.get('lead', ()))]
    for i in bl['keep']:
        if due(i): plan += ent; ent_done[0] = True          # F15
        if i in skip: continue
        plan += [('hook', 0, Pp, srcP, j) for j in hooks.get(i, ())] + [('keep', 0, A, srcA, i)]
    if bl.get('exit') and Pp is None: raise BuildError('exit staging %s: no update heap' % bl['name'])
    plan += [('exit', k, Pp, srcP, j) for k, j in enumerate(bl.get('exit', ()))]     # F21 (opt-in): after the last
    if ent and not ent_done[0]: raise BuildError('entry replay %s: not placed' % bl['name'])
    keep_before, keep_after, keep_rows, keep_start = camera_keep(bl, plan)
    ent_done[0] = False
    if not (CAMERA_KEEP and (CAMERA_KEEP_ALL or bl['name'] in KEEP_PARTS)):    # analysed and reported, not emitted
        keep_before, keep_after = {}, {}
        for r in keep_rows:
            if 'pm' in r:
                r['action'] = 'not emitted (%s): %s' % ('AFR_TEST nokeep' if not CAMERA_KEEP else
                                                        'AFR_TEST keepmikoto: part not in KEEP_PARTS', r['action'])
    plan_out = {}            # plan index -> output index of that instruction
    pk = 0
    flag_jobs = []           # (output instruction index, AF target instruction index or None for -1, AF FlagOp index)
    out_of_keep = []         # output instruction index of each kept AF instruction (PM overlay calls are inserted)
    n_out = 0
    if fix_on('excl') and bl['name'] in EXCL_PARTS:     # F13: Mikoto's exclusive camera on (the part's first instruction)
        emit_pm_at(*EXCL_CAM_PM[1]); excl_added.add(n_out); n_out += 1; stats['excl_cam'] += 1
    if bl.get('kashi_call'):
        # F23: x_3eab17_4957 first calls the conversation's start (KASHI_SCENE_KEY); KASHI id
        emit_scene_call(*bl['kashi_call'])
        kashi_added.add(n_out); n_out += 1; stats['kashi_call'] += 1
    objs_before = set(B.objs); _lead_mode[0] = bool(bl.get('lead')) or base_mode
    for k, j in enumerate(bl.get('lead', ())):   # LEAD_IN: AF's picture and framing before the part's first line
        n_out += emit_inserts(keep_before.get(pk), n_out); n_out += fixwin(A, srcA, j, n_out); plan_out[pk] = n_out
        if k == 2:      # the camera apply: duration 0 (AF's timed move had ended before the part's first line)
            if bl['af'] not in _lead_typed:
                _lead_typed[bl['af']] = TypedArgHeap(open(af_path(bl['af']), 'rb').read(), 2); _lead_typed[bl['af']].parse()
            Tl = _lead_typed[bl['af']]
            if Tl.d != A.d: raise BuildError('lead-in %s: typed heap differs from the AF heap' % bl['name'])
            ap = Tl.instrs[j][3]['argpos']
            if len(ap) < 2 or struct.unpack_from('<I', A.d, ap[1])[0] & 3 != 2:
                raise BuildError('lead-in %s: camera apply %d has unexpected args' % (bl['name'], j))
            old = srcA.raw_repl.get(ap[1])
            srcA.raw_repl[ap[1]] = (ap[1] + 4, struct.pack('<I', (0 << 2) | 2))
            try:
                n_out += 1 + emit_staging(A, srcA, j, n_out)
            finally:
                if old is None: del srcA.raw_repl[ap[1]]
                else: srcA.raw_repl[ap[1]] = old
        else:
            n_out += 1 + emit_staging(A, srcA, j, n_out)
        n_out += emit_inserts(keep_after.get(pk), n_out); pk += 1
        stats['lead_in_instrs'] += 1
    _lead_mode[0] = base_mode
    for t in [t for t in B.objs if t not in objs_before and t[0] == 'NEW']:
        del B.objs[t]                    # the part's own references import (or reuse) the main-range object
    n_lead = n_out                       # output instructions of the lead-in (ids from LEAD_ID_BASE)
    # F16: the AF instructions X45_EXTEND added (index >= the old hi): X45 import mode while each emits (its hook items,
    # extras and CAMERA_KEEP inserts included), and those outputs take X45 ids
    x45 = {i for i in bl['keep'] if i >= bl['x45_from']} if bl.get('x45_from') is not None else set()
    x45_at = None
    # F23: the AF instructions KASHI_EXTEND added (index >= the part's old hi): KASHI import mode while each emits (its
    # hook items, extras and CAMERA_KEEP inserts included), and those outputs take KASHI ids
    kx = {i for i in bl['keep'] if i >= bl['kashi_from']} if bl.get('kashi_from') is not None else set()
    kx_at = None
    for i in bl['keep']:
        if x45_at is not None:           # F16: the previous added instruction's outputs
            x45_added.update(k for k in range(x45_at, n_out) if k not in fixwin_added | winshow_added); x45_at = None
            _lead_mode[0] = False
        if kx_at is not None:            # F23: the previous added instruction's outputs
            kashi_added.update(k for k in range(kx_at, n_out) if k not in fixwin_added | winshow_added); kx_at = None
            _lead_mode[0] = base_mode
        if due(i): n_out, pk = emit_entry(n_out, pk); ent_done[0] = True     # F15: the 2007 entry state
        if i in skip:        # replaced by the patch's staging (emitted at the stretch's branch or line)
            out_of_keep.append(n_out); continue
        if i in x45: x45_at = n_out; _lead_mode[0] = 'x45'; stats['x45_instrs'] += 1
        if i in kx: kx_at = n_out; _lead_mode[0] = 'kashi'; stats['kashi_instrs'] += 1
        if i in hooks:
            for j in hooks[i]:
                at_c2 = n_out; c2_emitting[0] = j in c2_fold      # F14 (e): deferred keys while a folded item emits
                n_out += emit_inserts(keep_before.get(pk), n_out); n_out += fixwin(Pp, srcP, j, n_out); plan_out[pk] = n_out
                if j in c2_lines:                # F14 (c): the folded update-only line
                    n_out += 1 + emit_c2_line(j, n_out)     # (F26: an OM_Visible first, then the line)
                elif j in c2_wait:               # F14 (d): CVmSync(319679, b=1, v>0) -> PM's timed wait of v ms
                    emit_pm(SHAKE_WAIT_PM[0], SHAKE_WAIT_PM[1], SHAKE_WAIT_PM[1] + 1, c2_wait[j]); n_out += 1
                    stats['c2_wait'] += 1
                else:
                    n_out += 1 + emit_staging(Pp, srcP, j, n_out)
                stats['patch_staging_instrs'] += 1
                n_out += emit_inserts(keep_after.get(pk), n_out); pk += 1
                if j in c2_fold:                 # F14 (e): the item, its extras and its CAMERA_KEEP inserts: PATCH ids
                    patch_added.update(k for k in range(at_c2, n_out) if k not in fixwin_added | winshow_added)
                c2_emitting[0] = False
            stats['patch_staging_segments'] += 1
        ins = A.instrs[i]; name = ins[2]
        first_i = n_out                  # a branch to this AF instruction lands on its kept-camera insert, if any
        n_out += emit_inserts(keep_before.get(pk), n_out)
        n_out += fixwin(A, srcA, i, n_out)   # F12 (between first_i and the fade: a branch to the fade passes the hide)
        out_i = n_out; out_of_keep.append(first_i); n_out += 1; plan_out[pk] = out_i
        pk_i = pk; pk += 1
        lo, hi = A.ins_ev[i]
        stats[name] += 1
        if fix_on('pmsnd') and (bl['name'], i) in PM_PORT_SOUND:
            # F06: PM's own port of this sound instruction in its place (same output index, same main id); the AF
            # effect is still allocated here when it is an import, so every later key stays
            eff = next(x for x in A.ins_res[i] if x and isinstance(x[0], tuple))
            if remap(srcA, eff)[0] == 'NEW': key_alloc(eff[1], eff[0], eff[2])
            emit_pm_at(*PM_PORT_SOUND[(bl['name'], i)]); stats['pm_port_sound'] += 1
            n_out += emit_inserts(keep_after.get(pk_i), n_out)
            continue
        if name == 'CVmFlagOp':
            # kept only when the block wants internal branches; the target (last dword) is patched after layout
            t = struct.unpack_from('<I', A.d, ins[1] - 4)[0]
            flag_jobs.append((out_i, None if t == 0xFFFFFFFF else af_inv[t], i))
            B.emit_instructions(srcA, i, i + 1)
            continue
        if name in ('CVmCall', 'CVmSync', 'CVmGenericMsg', 'CVmSound'):
            n_out += emit_staging(A, srcA, i, out_i)
            n_out += emit_inserts(keep_after.get(pk_i), n_out)
        elif name == 'CVmMsg':
            p = base_pos(A.d, ins[0]); dw1, dw2 = struct.unpack_from('<II', A.d, p)
            if dw2 & 0x04000000: raise BuildError('CVmMsg %d flag 0x4000000' % i)
            unp = ins[5][0][1]; text = unp.decode('cp932')
            patched = af_patch_msgs(bl['af']).get(dw2 & 0xFFFFF)
            if c3_emptied(patched, unp):
                # F03 (C3): the update emptied this line (0 text bytes, no voice; it merged the text into the line
                # before): PM's empty-line form (242 PM lines), so 2007's empty line is not shown as repeated text
                toff = add_text('')
                ws = winshow('', out_i)                 # F26 (the line moves one on)
                n_out += ws; plan_out[pk_i] = out_i + ws
                B.emit_class('CVmMsg3', PM_SCHEMA, 'cdef')
                B.out += struct.pack('<IIHHBB', 0, 0x60000000, 1, 0, 2, 0) + struct.pack('<III', toff, 0, 0) * 2
                stats['patch_emptied'] += 1; continue           # the id loop gives it its own (unchanged) id
            praw = patched[0] if patched else None          # patch text, also a lookup key for the English text
            mflags = dw2 & 0xFFC00000 & ~0x04000000         # the line's dw2 flags (F14 (b): the update's)
            if patched and patched[0].endswith(b'\x01') != ins[5][0][1].endswith(b'\x01'):
                pj = p_line.get(dw2 & 0xFFFFF, ())
                pdw = struct.unpack_from('<I', Pp.d, base_pos(Pp.d, Pp.instrs[pj[0]][0]) + 4)[0] if len(pj) == 1 else None
                if (fix_on('c2') and patched[0] and unp.endswith(b'\x01') and pdw is not None
                        and pdw & 0xFFC00000 == (dw2 & 0xFFC00000) | 0x01000000):
                    # F14 (b): the first piece of a line the update split (its staging and continuation follow in
                    # the hook before the next kept line): the update's text without the click and its flags
                    mflags = pdw & 0xFFC00000 & ~0x04000000; stats['c2_split'] += 1
                    _c2_done['split'].add((bl['name'], dw2 & 0xFFFFF))
                else:
                    # the patch split this line into timed pieces (text, sync, continuation line): the restored block
                    # keeps the unpatched structure, so keep the complete unpatched line and its voice
                    patched = None; stats['patch_restructured_kept'] += 1
            used = unp
            if patched and patched[0] != ins[5][0][1]:
                used = patched[0]; text = used.decode('cp932'); stats['patch_text'] += 1
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
            spk_box = None
            for n_v, (v, use) in enumerate(zip(vs, pv)):  # main voice, then the extension's extra voices (multi-speaker lines)
                if v[0][0] != 'COptimizedObs' or use[0][0] != 'COptimizedObs': raise BuildError('voice class %s' % (v,))
                if fix_on('c15'):       # F09: the voice's speaker (see VOICE_OCEAN_PM)
                    oc = af_voice_ocean(bl['af'], use[1])[1]
                    if oc in VOICE_OCEAN_PM: VoiceBuilder.voice_parent[use[1]] = VOICE_OCEAN_PM[oc]
                    elif oc in VOICE_SPK_BOX and n_v == 0: spk_box = VOICE_SPK_BOX[oc]
                    else: raise BuildError('C15: voice %x (entry %d) in AF ocean %x not covered' % (use[1], n_v, oc))
                if use[1] not in vidx:
                    # ref flags come from the unpatched line's own voice ref (same class, same slot)
                    R = next((A.ev[k] for k in range(lo, hi) if A.ev[k][0] == 'ref' and A.ev[k][6] == v[1]), None)
                    vidx[use[1]] = len(tail); tail.append(('voice', use, R))
                    if i in x45: tail_x45.add(len(tail) - 1)    # F16: a voice first used by an added line
                    if i in kx: tail_kashi.add(len(tail) - 1)   # F23: ... by a KASHI line
                voices.append(vidx[use[1]])
            spk = 0
            if fix_on('c15'):
                plink = (af_patch_msgs(bl['af']).get(dw2 & 0xFFFFF) or (None, None, None))[2]
                if plink is not None:   # the update's own speaker link names the same PM box (69 lines)
                    if spk_box is None or mapped(plink[1]) != spk_box:
                        raise BuildError('C15: %s line %d: update link %x -> %s, speaker %s' % (
                            bl['name'], i, plink[1], mapped(plink[1]), spk_box and hex(spk_box)))
                    stats['c15_link'] += 1; stats['c15_link_x45'] += i in x45
                    stats['c15_link_kashi'] += i in kx or bool(bl.get('kashi_scene'))
                if spk_box is not None:
                    if ('spk', spk_box) not in vidx:
                        vidx[('spk', spk_box)] = len(tail); tail.append(('spk', spk_box, None))
                    spk = vidx[('spk', spk_box)]; stats['c15_speaker'] += 1; stats['c15_speaker_x45'] += i in x45
                    stats['c15_speaker_kashi'] += i in kx or bool(bl.get('kashi_scene'))
            if ext and ext['extra']: stats['extra_voice'] += ext['extra']
            toff = add_text(text)
            if any(ord(c_) > 0x20 for c_ in text): win_hidden[0] = False      # F12: this line shows the window
            # second-language slot: PM's own multi-part lines never carry \x03 pauses there (3,200+ lines checked);
            # with pauses the engine renders that copy as a second, paused text column next to the normal box.
            # English from the player's afhook.pkg when it has the line (exact match, builder's text first); otherwise
            # the Japanese copy, pre-wrapped for the English layout. English is never pre-wrapped (PM wraps at spaces).
            en = None
            if EN_DATA and used:
                tr = EN_DATA.get(used) or EN_DATA.get(unp) or (EN_DATA.get(praw) if praw else None)
                en = entext.to_pm_english(tr, used, EN_NAMES) if tr else None
                if en is not None and i in c3_en and used != unp and EN_DATA.get(used) is None and EN_DATA.get(unp):
                    # F03 English: this merged line found only its unpatched translation; the emptied line after it
                    # (empty in both slots now) brings its own, joined by one space (the trailing 0x01 stays last)
                    tr2 = EN_DATA.get(c3_en[i]); e2 = entext.to_pm_english(tr2, c3_en[i], EN_NAMES) if tr2 else None
                    if e2:
                        cut = en.endswith('\x01')
                        en = (en[:-1] if cut else en) + ' ' + e2.rstrip('\x01') + ('\x01' if cut else '')
                        stats['en_c3_joined'] += 1
            pm_en = None
            if (i in kx or bl.get('kashi_scene')) and fix_on('kashi'):
                # F23: a line PM kept (same message id in PM's bypassed lines) keeps PM's own English slot text
                pm_en = pm_en_kashi().get(dw2 & 0xFFFFF)
            if pm_en is not None:
                etext = pm_en; en = pm_en; stats['en_pm_kept'] += 1
                if pm_en.endswith('\x01') != text.endswith('\x01'): stats['en_pm_click_differs'] += 1
            elif en is not None:
                etext = en; stats['en_text'] += 1
            else:
                etext = prewrap(text.replace('\x03', ''))
                if EN_DATA and used: stats['en_missing'] += 1
            eoff = add_text(etext) if etext != text else toff
            roff = 0                    # ruby ('base:reading;...') lives in the item's second dword, as in PM
            if ext and ext['ruby']:
                roff = add_text(ext['ruby'].decode('cp932')); stats['ruby'] += 1
            en_roff = 0 if en is not None else roff     # the ruby belongs to the Japanese base text
            # F02 (T3d): a 2-voice line (AF extension w & 2 with extra entries = more voices) keeps w & 3 in PM's w2:
            # PM FUN_004be740 queues the entries after the first only when n2 >= 2 and (w2 & 3) != 0 (PM's own 2-voice
            # lines carry w2 = 2); 2007 plays both clips (AF FUN_1006cee0)
            w2 = (ext['w'] & 3) if (fix_on('t3d') and ext and ext['extra']) else 0
            if w2 not in (0, 2): raise BuildError('CVmMsg %d: extension w %r' % (i, ext))
            ws = winshow(text, out_i)                   # F26: an OM_Visible first (the line moves one on)
            n_out += ws; plan_out[pk_i] = out_i + ws
            B.emit_class('CVmMsg3', PM_SCHEMA, 'cdef')
            B.out += struct.pack('<IIHHBB', 0, mflags, 1, w2, 2, len(voices))
            B.out += struct.pack('<III', toff, roff, 0) + struct.pack('<III', eoff, en_roff, 0)
            for n_v, vi in enumerate(voices):      # F09: entry 0's u16 #2 = the explicit speaker (PM reads only that one)
                B.out += struct.pack('<HHHHBB', vi, spk if n_v == 0 else 0, 0, 0, 0, 0)
        else:
            raise BuildError('instruction %s not handled' % name)
    if x45_at is not None:               # F16: the last added instruction's outputs
        x45_added.update(k for k in range(x45_at, n_out) if k not in fixwin_added | winshow_added); x45_at = None
        _lead_mode[0] = False
    if kx_at is not None:                # F23: the last added instruction's outputs
        kashi_added.update(k for k in range(kx_at, n_out) if k not in fixwin_added | winshow_added); kx_at = None
        _lead_mode[0] = base_mode
    if bl.get('exit'):
        # F21 (opt-in): the update's staging of the next shot after the part's last instruction, emitted like the hook
        # items (EXIT ids with their extras and CAMERA_KEEP inserts, EXIT-range imports)
        objs_x = set(B.objs); _lead_mode[0] = 'exit'
        try:
            for j in bl['exit']:
                at = n_out
                n_out += emit_inserts(keep_before.get(pk), n_out); n_out += fixwin(Pp, srcP, j, n_out); plan_out[pk] = n_out
                n_out += 1 + emit_staging(Pp, srcP, j, n_out)
                n_out += emit_inserts(keep_after.get(pk), n_out); pk += 1
                xo = {k for k in range(at, n_out) if k not in fixwin_added}
                exit_out.update(xo); keep_added.difference_update(xo); stats['exit_instrs'] += 1
        finally:
            _lead_mode[0] = False
        for t in [t for t in B.objs if t not in objs_x and t[0] == 'NEW']:
            del B.objs[t]                # the tail's own references import (or reuse) the main-range object
    if pk != len(plan): raise BuildError('%s: emitted %d planned instructions of %d' % (bl['name'], pk, len(plan)))
    # report (build_manifest.json): kept-camera inserts, and the output index of every picture / camera call
    for r in keep_rows: r['pic_out'] = plan_out[r.pop('plan')]
    _keep_report[bl['name']] = dict(start=keep_start, shots=keep_rows, calls=[
        [plan_out[q], role, '%s@%d' % (src.name, i), 'pic' if (src.name, i) in _pic_info else 'cam']
        for q, (role, k, H, src, i) in enumerate(plan) if (src.name, i) in _pic_info or (src.name, i) in _cam_info])
    # F11 (C6): no sound past the chapter end (FIX_END ids)
    if fix_on('c6') and bl['name'] in FIXEND_STOP:
        emit_pm_at(*FIXEND_STOP_PM); fixend_added.add(n_out); n_out += 1; stats['fixend'] += 1
    if fix_on('c6') and bl['name'] in FIXEND_STRETCH and Pp is not None:
        for j in FIXEND_STRETCH[bl['name']]:         # the update's end stretch after the part's last line
            n_out += fixwin(Pp, srcP, j, n_out)      # F12 (its white fade P4440)
            at = n_out; n_out += 1 + emit_staging(Pp, srcP, j, n_out); fixend_added.update(range(at, n_out))
            stats['fixend'] += 1
    if fix_on('excl') and bl['name'] in EXCL_PARTS:     # F13: ... and off again (the last instruction before the Ret)
        emit_pm_at(*EXCL_CAM_PM[0]); excl_added.add(n_out); n_out += 1; stats['excl_cam'] += 1
    if bl.get('ycont_call'):
        # F17: yuuhi_a calls its route-A continuation (YCONT_SCENE_KEY) as its last instruction: patch_pm's inserted
        # call (CVmCall, CRsa ref flag 0xC108 with the route-folder pad as parent, no arguments, no extras), the size
        # written once the continuation is built (YCONT_ENC_PH until then); YCONT id
        _ycont['win'] = win_hidden[0]
        emit_scene_call(YCONT_SCENE_KEY, YCONT_ENC_PH)
        ycont_call.add(n_out); n_out += 1; stats['ycont_call'] += 1
    # closing CVmRet
    B.emit_class('CVmRet', PM_SCHEMA, 'cdef'); B.out += struct.pack('<II', 0xFFFFFFFF, 0)
    count = n_out + 1
    # tail: text table + object list
    B.out += struct.pack('<I', tlen[0]) + ''.join(table).encode('utf-16le')
    B.out += struct.pack('<H', len(tail))
    for ti, r in enumerate(tail):
        _lead_mode[0] = 'x45' if ti in tail_x45 else 'kashi' if ti in tail_kashi else base_mode    # F16 / F23
        if r[0] == 'null': B.ensure_pad(); B.out += b'\x00\x00'   # the pad precedes the first object slot
        elif r[0] == 'msgbox': B.object_slot(srcA, MSGBOX_PM['cls'], MSGBOX_AF, MSGBOX_PM['size'] + 3)
        elif r[0] == 'spk': B.object_slot(None, *pm_cls(r[1]))      # F09: PM's speaker box (template replay)
        else:       # (a 4th element: the source heap of R, for a voice first used by an F14 update-only line)
            (cls, off, size), R = r[1], r[2]; B.object_slot(r[3] if len(r) > 3 else srcA, cls, off, size, R)
    _lead_mode[0] = False
    if c2_defer: raise BuildError('C2 %s: imports used only by folded items: %s' % (bl['name'], [hex(v[0]) for v in c2_defer.values()]))
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

    slot_seq = collections.Counter()

    def slot_id(kind, base, order):         # F15 ENTRY / F21 EXIT: the part's fixed 16-id slot (per conversion)
        if bl['name'] not in order or slot_seq[kind] >= 0x10:
            raise BuildError('%s: %s slot (%s)' % (bl['name'], kind, 'no slot' if bl['name'] not in order else 'full'))
        ident = base + 0x10 * order.index(bl['name']) + slot_seq[kind]; slot_seq[kind] += 1
        _slot_used[(kind, bl['name'])] = list(range(base + 0x10 * order.index(bl['name']), ident + 1))
        return ident
    if entry_out & keep_added: raise BuildError('%s: an ENTRY instruction is also a CAMERA_KEEP insert' % bl['name'])
    for j in range(count):
        p = base_pos(heap, g.instrs[j][0])
        nxt = offs[j + 1] if j + 1 < count else 0xFFFFFFFF
        flags = struct.unpack_from('<I', heap, p + 4)[0] & 0xFFF00000
        # first match wins (FIXPLAN F00 (4)); the restore-audit sets are empty when their fix is off
        if j in winshow_added:
            ident = winshow_id[0]; winshow_id[0] += 1
        elif j in patch_added:
            ident = patch_id[0]; patch_id[0] += 1
        elif j in fixwin_added:
            ident = fixwin_id[0]; fixwin_id[0] += 1
        elif bl.get('ycont') and j != count - 1:
            ident = ycont_id[0]; ycont_id[0] += 1
        elif bl.get('kashi_scene') and j != count - 1:     # F23: the conversation's start scene, every instruction
            ident = kashi_id[0]; kashi_id[0] += 1
        elif j in x45_added:
            ident = x45_id[0]; x45_id[0] += 1
        elif j in kashi_added:
            ident = kashi_id[0]; kashi_id[0] += 1
        elif j in keep_added:
            ident = keep_id[0]; keep_id[0] += 1
        elif j in entry_out:
            ident = slot_id('entry', ENTRY_ID_BASE, ENTRY_ORDER)
        elif j in exit_out:
            ident = slot_id('exit', EXIT_ID_BASE, EXIT_ORDER)
        elif j in excl_added:
            ident = excl_id[0]; excl_id[0] += 1
        elif j in ovl_added:
            ident = ovl_id[0]; ovl_id[0] += 1
        elif j in fixend_added:
            ident = fixend_id[0]; fixend_id[0] += 1
        elif j in ycont_call:
            ident = ycont_id[0]; ycont_id[0] += 1
        elif j < n_lead:
            ident = lead_id[0]; lead_id[0] += 1
        elif j in added:
            ident = add_id[0]; add_id[0] += 1
        elif j == count - 1:             # the closing CVmRet: id 0, or a RETID id when a CVmCall returns to it (F24)
            ident = 0
            if fix_on('retid') and count > 1 and g.instrs[count - 2][2] == 'CVmCall':
                ident = retid_id[0]; retid_id[0] += 1; stats['retid'] += 1
        else:
            ident = next_id[0]; next_id[0] += 1
        struct.pack_into('<II', heap, p, nxt, flags | ident)
    # branch targets: AF instruction -> first kept instruction at/after it (inside the block), else the closing CVmRet
    # F01 (C10): a FlagOp whose AF target was replaced by the update's staging branches where its update twin branches
    # (the output of the hook item that emits the twin's target; first on its kept-camera insert, if any). 2007 takes
    # the update's branch: marimo_chapter #987 / #1261 jump to the update's stop-all P1483 (#1514), not to #1512.
    kept = bl['keep']; p_inv = None
    for out_i, af_t, src_i in flag_jobs:
        if af_t is None:
            tgt = 0xFFFFFFFF
        elif fix_on('c10') and af_t in skip and src_i in twin:
            p_inv = p_inv or {o: k for k, o in enumerate(af_offsets_of(Pp))}
            p_t = p_inv[struct.unpack_from('<I', Pp.d, Pp.instrs[twin[src_i]][1] - 4)[0]]
            q = next(q for q, e in enumerate(plan) if e[0] == 'hook' and e[4] == p_t)
            if plan_out[q] - 1 in fixwin_added: raise BuildError('C10: a FIXWIN insert before the twin target %d' % p_t)
            tgt = offs[plan_out[q] - len(keep_before.get(q, ()))]; stats['branch_twin'] += 1
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
    """inserts: list of (p_ins, land, scene_enc[, id]) - id: the inserted call's id (F25: a fix-range id), else the next
    main-range id. Returns new heap bytes."""
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

    for ins_ in inserts:
        p_ins, land, enc = ins_[:3]
        mid = P.ins_ev[p_ins][0]
        S._emit_events(P.ins_ev[0][0] if ev_pos == 0 else ev_pos, mid, P.instrs[p_ins][0])
        # unique nonzero id: saves (incl. the auto q-save) serialize each VM frame's current instruction by id,
        # and the engine refuses id 0 (AfxThrowNotSupportedException in FUN_00443e10)
        if len(ins_) > 3:
            S.out += cls_tag(call_cls) + struct.pack('<II', 0, ins_[3])
        else:
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
            elif land_k != p_k and land_k in pins:
                # F16: the landing is another part's insertion point: land on that part's call (the first one inserted
                # there), so the two parts chain; new_off would land after it and skip that part
                if not (fix_on('c8') or KASHI_PARTS):         # (F16's and F23's chained parts)
                    raise BuildError('%s: the call at %d would skip the call inserted at %d' % (name, p_k, land_k))
                struct.pack_into('<I', newP, pos, old_off[land_k] + S_CALL * sum(1 for q in pins if q < land_k))
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


def _sound_words(H, src, j):
    """(typ, f, w1, w2, w3) of CVmSound j of heap H (emit_staging's walk to the end of the effect slot)."""
    ins = H.instrs[j]; lo, hi = H.ins_ev[j]
    s0 = base_pos(H.d, ins[0]) + 8
    if src.pad is not None and src.pad[1] == s0: s0 += 1
    se = slot_end(H, lo, hi, s0)
    return (H.d[se], H.d[se + 1]) + struct.unpack_from('<HHH', H.d, se + 2)


def _winshow_om():
    """F26: (name, schema, kind, definition bytes) of PM's own '&-OM_Visible' class (WINSHOW_OM's raw class)."""
    H = pm_srcs[WINSHOW_OM[0]].h; lo, hi = H.ins_ev[WINSHOW_OM[1]]
    ev = next(e for e in H.ev[lo:hi] if e[0] == 'rdef')
    return ev[4][0], ev[4][1], 'rdef', bytes(H.d[ev[1]:ev[2]])


def _check_fix_templates():
    """The PM instructions the restore-audit fixes copy are what their constants say (startup check)."""
    for (part, i), (h, j) in PM_PORT_SOUND.items():           # F06: PM's port of the same AF sound instruction
        H = pm_srcs[h].h; r = H.ins_res[j][0] if H.ins_res[j] else None
        if not (H.instrs[j][2] == 'CVmSound' and r and isinstance(r[0], tuple) and r[0][0] in ('CPmEffect', 'CPmBgm')
                and r[1] == PM_PORT_EFFECT[(h, j)] and _sound_words(H, pm_srcs[h], j)[0] == 5):
            raise BuildError('PM_PORT_SOUND %s %d is not a CVmSound typ 5 on %x' % (h, j, PM_PORT_EFFECT[(h, j)]))
        blk_ = BL.block(part) if part in BL.SITES else BL.range_block(part)
        A_ = af_heap(blk_['af'])
        if not (i in blk_['keep'] and A_.instrs[i][2] == 'CVmSound'
                and _sound_words(A_, Src(A_, 'AF', blk_['af']), i) == _sound_words(H, pm_srcs[h], j)):
            raise BuildError('PM_PORT_SOUND %s@%d: not the same sound instruction as PM %s %d' % (part, i, h, j))
    # F10: PM's overlay set copied for AF's hut 70e8902b follows PM's call of its flat copy (= objmap of the AF hut) and
    # is the day hut's set #18-#23 of the same heap except for the overlay pictures (same classes, helper, boxes, args)
    for af_bg, (h, j0, j1) in BG_OVERLAYS_C4.items():
        H = pm_srcs[h].h; r0 = H.ins_res[j0 - 1] or []
        if not (H.instrs[j0 - 1][2] == 'CVmCall' and r0 and isinstance(r0[0][0], tuple) and r0[0][1] == mapped(BG_HELPER)
                and len(r0) > 1 and r0[1] and isinstance(r0[1][0], tuple) and r0[1][1] == mapped(af_bg)):
            raise BuildError('BG_OVERLAYS_C4 %x: %s %d is not the background call of %s' % (af_bg, h, j0 - 1, mapped(af_bg)))
        hd, d0, d1 = BG_OVERLAYS[0x6deb814f]
        if hd != h or d1 - d0 != j1 - j0: raise BuildError('BG_OVERLAYS_C4 %x: no day-hut set to compare' % af_bg)
        if 'pm:' + h not in _canon:
            _canon['pm:' + h] = CanonHeap(H.d, 2); _canon['pm:' + h].parse()
        CH = _canon['pm:' + h]
        import re as _re
        for k in range(j1 - j0):
            a_ = _re.sub(r'<CAC7Ti@[0-9a-f]+>', '<CAC7Ti>', canon(CH, j0 + k))
            b_ = _re.sub(r'<CAC7Ti@[0-9a-f]+>', '<CAC7Ti>', canon(CH, d0 + k))
            if a_ != b_: raise BuildError('BG_OVERLAYS_C4 %x: %s #%d differs from #%d' % (af_bg, h, j0 + k, d0 + k))
    # F07: the PM instructions a new landing bypasses are calls / syncs / sounds only, no FlagOp of that heap branches
    # into them, and no other part inserts its call inside them or at the new landing (it would be skipped)
    all_parts = list(BL.SITES) + list(BL.MARIMO_PARTS) + list(BL.EXTRA_PARTS)
    blks = {p_: (BL.block(p_) if p_ in BL.SITES else BL.range_block(p_)) for p_ in all_parts}
    for part, new_land in LAND_FIX.items():
        b_ = blks[part]; H = pm_srcs[b_['pm']].h; old = b_['land']
        if not old < new_land < H.count:
            raise BuildError('LAND_FIX %s: new landing %d not after the old one %d' % (part, new_land, old))
        bad = [j for j in range(old, new_land) if H.instrs[j][2] not in ('CVmCall', 'CVmSync', 'CVmSound')]
        offs_ = af_offsets_of(H); inv_ = {o: k for k, o in enumerate(offs_)}
        tg = [j for j in range(H.count) if H.instrs[j][2] == 'CVmFlagOp'
              and old <= inv_.get(struct.unpack_from('<I', H.d, H.instrs[j][1] - 4)[0], -1) < new_land]
        ins_ = [p_ for p_, o_ in blks.items() if p_ != part and o_['pm'] == b_['pm']
                and old <= o_['pm_before'] + 1 <= new_land]
        if bad or tg or ins_:
            raise BuildError('LAND_FIX %s: PM %s [%d, %d) holds %s, branch targets from %s, inserts of %s' % (
                part, b_['pm'], old, new_land, [(j, H.instrs[j][2]) for j in bad], tg, ins_))
    # F16: each extension stops at the next part's first AF instruction; the PM instructions it newly bypasses
    # [old landing, new landing) are lines / calls / syncs / sounds, no FlagOp of that heap branches into them, no part
    # inserts its call inside them, and exactly the next part (X45_NEXT) inserts its call at the new landing
    for part, (lo_, hi_, pi_, land_) in X45_EXTEND.items():
        b_ = blks[part]; nx = blks[X45_NEXT[part]]; H = pm_srcs[b_['pm']].h; old = b_['land']
        if not (b_['lo'] == lo_ and b_['hi'] < hi_ == nx['lo'] and b_['pm_before'] + 1 == pi_ and old < land_
                and nx['pm'] == b_['pm'] and nx['pm_before'] + 1 == land_):
            raise BuildError('X45_EXTEND %s: %s does not meet %s' % (part, (lo_, hi_, pi_, land_), X45_NEXT[part]))
        bad = [j for j in range(old, land_) if H.instrs[j][2] not in ('CVmMsg3', 'CVmCall', 'CVmSync', 'CVmSound')]
        offs_ = af_offsets_of(H); inv_ = {o: k for k, o in enumerate(offs_)}
        tg = [j for j in range(H.count) if H.instrs[j][2] == 'CVmFlagOp'
              and old <= inv_.get(struct.unpack_from('<I', H.d, H.instrs[j][1] - 4)[0], -1) < land_]
        ins_ = [p_ for p_, o_ in blks.items() if p_ != part and o_['pm'] == b_['pm'] and old <= o_['pm_before'] + 1 <= land_]
        if bad or tg or ins_ != [X45_NEXT[part]]:
            raise BuildError('X45_EXTEND %s: PM %s [%d, %d) holds %s, branch targets from %s, inserts of %s' % (
                part, b_['pm'], old, land_, [(j, H.instrs[j][2]) for j in bad], tg, ins_))
    # F21 (opt-in): the update instructions each exit adds are staging (calls / syncs / sounds / OMs), and the PM
    # instructions a new landing bypasses are calls / OMs only, no FlagOp branches into them, no other part inserts there
    if 'pmexit' in AFR_TEST:
        for part, (js, new_land) in EXIT_EXTEND.items():
            b_ = blks[part]; P_ = af_patch_heap(b_['af'])
            if P_ is None: continue
            bad = [j for j in js if P_.instrs[j][2] not in ('CVmCall', 'CVmSync', 'CVmSound', 'CVmGenericMsg')]
            if bad: raise BuildError('EXIT_EXTEND %s: update %s are %s' % (part, bad, [P_.instrs[j][2] for j in bad]))
            if new_land is None: continue
            H = pm_srcs[b_['pm']].h; old = b_['land']
            if not old < new_land < H.count: raise BuildError('EXIT_EXTEND %s: landing %d not after %d' % (part, new_land, old))
            bad = [j for j in range(old, new_land) if H.instrs[j][2] not in ('CVmCall', 'CVmGenericMsg')]
            offs_ = af_offsets_of(H); inv_ = {o: k for k, o in enumerate(offs_)}
            tg = [j for j in range(H.count) if H.instrs[j][2] == 'CVmFlagOp'
                  and old <= inv_.get(struct.unpack_from('<I', H.d, H.instrs[j][1] - 4)[0], -1) < new_land]
            ins_ = [p_ for p_, o_ in blks.items() if p_ != part and o_['pm'] == b_['pm'] and old <= o_['pm_before'] + 1 <= new_land]
            if bad or tg or ins_:
                raise BuildError('EXIT_EXTEND %s: PM %s [%d, %d) holds %s, branch targets from %s, inserts of %s' % (
                    part, b_['pm'], old, new_land, [(j, H.instrs[j][2]) for j in bad], tg, ins_))
    # F17: AF 2340 is the route-A jump (FlagOp on 5cab65 to 2915) that yuuhi_a drops after its last kept instruction 2339;
    # the continuation's keep is yuuhi_b's keep in [2915, 3201) and its drops are YCONT_DROPS; the update's span
    # P2932-3217 has the same staging (stage_sig) and message ids as AF 2915-3200, instruction for instruction
    A_ = af_heap(YCONT_AF); ya, yb = blks[YCONT_HOST], blks['yuuhi_b']; yc = ycont_block()
    ins_ = A_.instrs[YCONT_FROM]; r_ = A_.ins_res[YCONT_FROM][0] if A_.ins_res[YCONT_FROM] else None
    t_ = struct.unpack_from('<I', A_.d, ins_[1] - 4)[0] if ins_[2] == 'CVmFlagOp' else None
    offs_ = af_offsets_of(A_)
    if not (ins_[2] == 'CVmFlagOp' and r_ and isinstance(r_[0], tuple) and r_[1] == YCONT_ROUTE_VAR
            and t_ in offs_ and offs_.index(t_) == YCONT_LO and ya['af'] == yb['af'] == YCONT_AF
            and ya['hi'] == YCONT_FROM + 1 and ya['keep'][-1] == YCONT_FROM - 1 and YCONT_FROM in ya['drop']
            and yb['lo'] < YCONT_LO and yb['hi'] == YCONT_HI):
        raise BuildError('YCONT: AF %s %d is not the route-A jump to %d after %s' % (YCONT_AF, YCONT_FROM, YCONT_LO, YCONT_HOST))
    if yc['keep'] != [i for i in yb['keep'] if YCONT_LO <= i < YCONT_HI] or yc['drop'] != YCONT_DROPS:
        raise BuildError('YCONT: keep / drops differ from yuuhi_b / YCONT_DROPS (drops %s)' % yc['drop'])
    P_ = af_patch_heap(YCONT_AF)
    if P_ is not None:
        d_ = YCONT_PATCH_LO - YCONT_LO
        sg = lambda H, j: (stage_sig(H, j), _msg_id(H, j) if H.instrs[j][2] == 'CVmMsg' else None)
        bad = [i for i in range(YCONT_LO, YCONT_HI) if sg(A_, i) != sg(P_, i + d_)]
        if bad: raise BuildError('YCONT: the update span differs from AF %s at %s' % (YCONT_AF, bad[:8]))
    # F23: the three lead-in parts are consecutive in the build order and chain: each new range ends where the next one
    # starts, the start scene ends where x_3eab17_4957 starts, x_3eab17_4970 ends where kashiwagi's block starts (its
    # anchor line AF 4976 = PM 2477 by message id), each new landing is the next part's insertion point (the last
    # kashiwagi's), and x_3eab17_4957's new insertion point is PM's background call after AF 4866-4876's PM twins
    # (2297-2307, same message ids). AF [4877, 4977) holds no FlagOp / jump / label / Ret / AccessWrite; PM [2308, 2478)
    # no FlagOp / jump / label / Ret / ACH, no FlagOp branches into it and no other part inserts inside it; every PM line
    # there carries one of the conversation's AF message ids or is a PM-only line (counted)
    if fix_on('kashi') and af_patch_heap(KASHI_AF) is not None:
        names = list(KASHI_EXTEND); order = [p_ for p_ in all_parts if p_ in KASHI_EXTEND]
        A_ = af_heap(KASHI_AF); H = pm_srcs[KASHI_PM].h; kw = blks['kashiwagi']
        if order != names or [all_parts.index(p_) for p_ in names] != list(range(all_parts.index(names[0]), all_parts.index(names[0]) + 3)):
            raise BuildError('KASHI: the lead-in parts are not consecutive in the build order')
        ranges = [(KASHI_PRE[1], KASHI_PRE[2])] + [KASHI_EXTEND[p_][:2] for p_ in names]
        if any(a[1] != b[0] for a, b in zip(ranges, ranges[1:])) or ranges[-1][1] != kw['lo'] or kw['af'] != KASHI_AF:
            raise BuildError('KASHI: ranges %s do not chain up to kashiwagi (%d)' % (ranges, kw['lo']))
        ins = [KASHI_EXTEND[p_][3] for p_ in names] + [kw['pm_before'] + 1]
        if [KASHI_EXTEND[p_][4] for p_ in names] != ins[1:] or kw['pm'] != KASHI_PM or ins[0] != KASHI_PM_SPAN[0] \
                or ins[-1] != KASHI_PM_SPAN[1] or any(KASHI_EXTEND[p_][3] != KASHI_OLD[p_][2] for p_ in names[1:]):
            raise BuildError('KASHI: insertion points / landings %s do not chain' % ins)
        if KASHI_PM_CALL != (KASHI_PM_SPAN[0], KASHI_OLD[names[0]][2]) or not ins[0] < KASHI_PM_CALL[1] < ins[1]:
            raise BuildError('KASHI_PM_CALL %s: not PM %d landing on %s at %d' % (KASHI_PM_CALL, ins[0], names[0], KASHI_OLD[names[0]][2]))
        bad = [i for i in range(KASHI_PRE[1], ranges[-1][1]) if A_.instrs[i][2] in ('CVmFlagOp', 'CVmJump', 'CVmLabel', 'CVmRet')
               or (A_.instrs[i][2] == 'CVmGenericMsg' and A_.instrs[i][3] and 'AccessWrite' in str(A_.instrs[i][3][0]))]
        lo_, hi_ = KASHI_PM_SPAN
        badp = [j for j in range(lo_, hi_) if H.instrs[j][2] in ('CVmFlagOp', 'CVmJump', 'CVmLabel', 'CVmRet')
                or BL.is_ach(H, j)]
        offs_ = af_offsets_of(H); inv_ = {o: k for k, o in enumerate(offs_)}
        tg = [j for j in range(H.count) if H.instrs[j][2] == 'CVmFlagOp'
              and lo_ < inv_.get(struct.unpack_from('<I', H.d, H.instrs[j][1] - 4)[0], -1) < hi_]
        ins_ = [p_ for p_, o_ in blks.items() if p_ not in KASHI_EXTEND and o_['pm'] == KASHI_PM
                and lo_ <= o_['pm_before'] + 1 < hi_]
        if bad or badp or tg or ins_:
            raise BuildError('KASHI: AF control %s, PM control / ACH %s, branch targets %s, other inserts %s' % (bad, badp, tg, ins_))
        af_ids = {_msg_id(A_, i) for i in range(KASHI_PRE[1], ranges[-1][1]) if A_.instrs[i][2] == 'CVmMsg'}
        pm_ids = [struct.unpack_from('<I', H.d, base_pos(H.d, H.instrs[j][0]) + 4)[0] & 0xFFFFF
                  for j in range(lo_, hi_) if H.instrs[j][2] == 'CVmMsg3']
        before = [struct.unpack_from('<I', H.d, base_pos(H.d, H.instrs[j][0]) + 4)[0] & 0xFFFFF
                  for j in range(lo_ - 11, lo_) if H.instrs[j][2] == 'CVmMsg3']
        af_before = [_msg_id(A_, i) for i in range(KASHI_PRE[1] - 11, KASHI_PRE[1]) if A_.instrs[i][2] == 'CVmMsg']
        pm_only = [m for m in pm_ids if m not in af_ids]
        if before != af_before[-len(before):] or not before or pm_ids[-1] != _msg_id(A_, ranges[-1][1] - 1) \
                or len(pm_only) > 2 or any(b_ in af_ids for b_ in before):
            raise BuildError('KASHI: PM lines before the insert %s (AF %s), last %x, PM-only %s' % (
                [hex(x) for x in before], [hex(x) for x in af_before], pm_ids[-1], [hex(x) for x in pm_only]))
    # F13: PM's OM_SetExclusiveCamera(v) on Mikoto's box 46321 (= objmap of AF 3c9575), without a pad
    for v, (h, j) in EXCL_CAM_PM.items():
        H = pm_srcs[h].h; r = H.ins_res[j][0] if H.ins_res[j] else None; lo_, hi_ = H.ins_ev[j]
        if not (H.instrs[j][2] == 'CVmGenericMsg' and H.instrs[j][3]
                and str(H.instrs[j][3][0]).endswith('OM_SetExclusiveCamera') and r and isinstance(r[0], tuple)
                and r[1] == 0x46321 == mapped(0x3c9575) and struct.unpack_from('<I', H.d, H.instrs[j][1] - 10)[0] == v
                and not any(ev[0] == 'pad' for ev in H.ev[lo_:hi_])):
            raise BuildError('EXCL_CAM_PM %d: %s %d is not OM_SetExclusiveCamera(%d) on 46321' % (v, h, j, v))
    # F12: the FIXWIN template is PM's bare OM_Invisible on its message box, the same instruction as FIXPLAN's
    # 004fd25d2e #0 (OM, sole object = the box, dw2 flags, operand dword and trailing bytes), without a pad
    def _inv(hj):
        h_, j_ = hj; H_ = pm_srcs[h_].h; res_ = H_.ins_res[j_] or []; bp_ = base_pos(H_.d, H_.instrs[j_][0])
        if not (H_.instrs[j_][2] == 'CVmGenericMsg' and H_.instrs[j_][3] and str(H_.instrs[j_][3][0]).endswith('OM_Invisible')
                and len(res_) == 1 and isinstance(res_[0][0], tuple) and res_[0][1] == MSGBOX_PM['off']):
            raise BuildError('FIXWIN %s %d is not OM_Invisible on the message box' % hj)
        return (struct.unpack_from('<I', H_.d, bp_ + 4)[0] & 0xFFF00000, H_.d[bp_ + 8:bp_ + 12],
                H_.d[H_.instrs[j_][1] - 4:H_.instrs[j_][1]])
    if _inv(FIXWIN_TPL) != _inv(FIXWIN_PLAN): raise BuildError('FIXWIN_TPL differs from %s %d' % FIXWIN_PLAN)
    # F26: WINSHOW_OM is a CVmGenericMsg '&-OM_Visible' (a definition of PM's class, schema 0) with no OM argument and
    # one object, like FIXWIN_TPL's '&-OM_Invisible' (OMSIG: both 'None')
    H_ = pm_srcs[WINSHOW_OM[0]].h; j_ = WINSHOW_OM[1]; nm_, sc_, _, db_ = _winshow_om()
    if not (H_.instrs[j_][2] == 'CVmGenericMsg' and str(H_.instrs[j_][3][0]) == '&-OM_Visible' == nm_ and sc_ == 0
            and db_ == b'\xff\xff\x00' + bytes([len(nm_)]) + nm_.encode('ascii') and len(H_.ins_res[j_] or []) == 1
            and H_.d[H_.instrs[j_][1] - 4:H_.instrs[j_][1]] == bytes(4)
            and _inv(FIXWIN_TPL)[2] == bytes(4)):
        raise BuildError('WINSHOW_OM %s %d is not an argument-less OM_Visible on one object' % WINSHOW_OM)
    lo_, hi_ = pm_srcs[FIXWIN_TPL[0]].h.ins_ev[FIXWIN_TPL[1]]
    if any(ev[0] == 'pad' for ev in pm_srcs[FIXWIN_TPL[0]].h.ev[lo_:hi_]): raise BuildError('FIXWIN_TPL carries a pad')
    # F14: the update instructions C2_DROP leaves out are the ones the audit (C2) and limits L2 name: the two CVmBlt, the
    # OM_VramAgesImageIn of the frame buffer, the b=1 v=0 sync, the identity camera reset d13d87(0,0,0,720,1,0) +
    # d14fbb(0,0), and kasumi's FlagOp on the shake var
    def _ints(H, j):                   # plain int args of CVmCall j (stage_sig's argument bytes), else None
        a_ = stage_sig(H, j)[2]
        if a_ is None: return None
        w_ = [struct.unpack_from('<I', a_, 2 + 4 * k)[0] for k in range(struct.unpack_from('<H', a_, 0)[0])]
        return None if any(x & 3 != 2 for x in w_) else [(x >> 2) - (1 << 30) if x >> 2 >= 1 << 29 else x >> 2 for x in w_]
    for af_, j in sorted(C2_DROP):
        H = af_patch_heap(af_)
        if H is None: continue
        t = H.instrs[j]; refs = [x[1] for x in (H.ins_res[j] or []) if x and isinstance(x[0], tuple)]
        ok = {8548: t[2] == 'CVmBlt', 8555: t[2] == 'CVmBlt',
              8551: t[2] == 'CVmGenericMsg' and 'OM_VramAgesImageIn' in str(t[3]) and 0x44617 in refs,
              8552: t[2] == 'CVmSync' and refs == [SHAKE_VAR] and H.d[t[1] - 5] == 1 and H.d[t[1] - 4:t[1]] == bytes(4),
              8553: t[2] == 'CVmCall' and refs[:1] == [CAMERA_HELPER] and _ints(H, j) == [0, 0, 0, 720, 1, 0],
              8554: t[2] == 'CVmCall' and refs[:1] == [CAMERA_UPDATE] and _ints(H, j) == [0, 0],
              3962: t[2] == 'CVmFlagOp' and refs == [SHAKE_VAR, 0x3cad5f]}.get(j, False)
        if not ok: raise BuildError('C2_DROP %s %d is not the planned %s' % (af_, j, t[2]))
    # F11: PM's stop-all, and the update's end stretches (instructions after the part's last line, up to the first
    # control instruction): kasumi_h's is exactly FIXEND_STRETCH, mikoto's / meiya's equal the part's own (nothing to add)
    h, j = FIXEND_STOP_PM; H = pm_srcs[h].h
    if not (H.instrs[j][2] == 'CVmSound' and (H.ins_res[j] or [None])[0] == ('null',)
            and _sound_words(H, pm_srcs[h], j)[0] == 255):
        raise BuildError('FIXEND_STOP_PM %s %d is not a null CVmSound typ 255' % FIXEND_STOP_PM)
    for part in FIXEND_STOP + tuple(FIXEND_STRETCH):
        b_ = blks[part]; A_ = af_heap(b_['af']); P_ = af_patch_heap(b_['af'])
        if P_ is None: continue                 # no official update: nothing to compare (kasumi_h's stretch is skipped)
        last = [i for i in b_['keep'] if A_.instrs[i][2] == 'CVmMsg'][-1]
        tw = [j for j in range(P_.count) if P_.instrs[j][2] == 'CVmMsg' and _msg_id(P_, j) == _msg_id(A_, last)]
        if len(tw) != 1: raise BuildError('FIXEND %s: last line has %d update twins' % (part, len(tw)))
        ctl = ('CVmJump', 'CVmLabel', 'CVmRet', 'CVmFlagOp', 'CVmMsg')
        p_end = list(itertools.takewhile(lambda j: P_.instrs[j][2] not in ctl, range(tw[0] + 1, P_.count)))
        a_end = list(itertools.takewhile(lambda i: A_.instrs[i][2] not in ctl, range(last + 1, A_.count)))
        if part in FIXEND_STRETCH:
            if p_end != list(FIXEND_STRETCH[part]) or a_end:
                raise BuildError('FIXEND %s: update end stretch %s, AF %s' % (part, p_end, a_end))
        elif [stage_sig(P_, j) for j in p_end] != [stage_sig(A_, i) for i in a_end] or any(i not in b_['keep'] for i in a_end):
            raise BuildError('FIXEND %s: the update adds end staging %s (AF %s)' % (part, p_end, a_end))


# ---------------------------------------------------------------- main
_check_fix_templates()
learn_nested()
if BB_SHRINK_LIMIT:          # billboard pictures over the limit in the parts (and their patch heaps); off under bb2bg
    for n in scenes:
        blk = BL.block(n) if n in BL.SITES else BL.range_block(n)
        for H_, idx in ((af_heap(blk['af']), blk['keep']), (af_patch_heap(blk['af']), None)):
            if H_ is None: continue
            for i in (idx if idx is not None else range(H_.count)):
                r = H_.ins_res[i] or []
                if (H_.instrs[i][2] == 'CVmCall' and r and r[0] and isinstance(r[0][0], tuple)
                        and r[0][1] == BILLBOARD_HELPER):
                    img = next((x for x in r[1:] if x and isinstance(x[0], tuple)), None)
                    if img and img[0][0] == 'Cr6Ti' and img[2] > BB_SHRINK_LIMIT: BB_SHRINK.add(img[1])
    say('billboard re-encode (BB_SHRINK_LIMIT): %d billboard pictures over %d bytes' % (len(BB_SHRINK), BB_SHRINK_LIMIT))
if AFR_TEST: say('AFR_TEST: %s' % ','.join(sorted(AFR_TEST)))
# a full release-form build: every part, no debug entry, no test part (the exact-count checks at the end apply to it)
FULL_BUILD = not DEBUG and not TEST_NAMES and set(scenes) == set(BL.SITES) | set(BL.MARIMO_PARTS) | set(BL.EXTRA_PARTS)
# the official 2007 update is read (AF_PATCH): without it the build restores the unpatched lines and staging, and the
# fixes that rebuild the update's staging (F11's kasumi_h end, F14, F15, F21, F23) are left out
HAVE_UPDATE = af_patch_heap(BL.block('sumika')['af']) is not None
by_heap = collections.defaultdict(list)
scene_objs = []
ycont_objs = []              # F17: the yuuhi_a_cont scene object (after the F16 imports in the table, see below)
kashi_scene_objs = []        # F23: the Kashiwagi conversation's start scene (after every other object, see below)
manifest = {}
stats_land = []              # F07: parts landed at their LAND_FIX point
if fix_on('kashi') and af_patch_heap(KASHI_AF) is not None and all(n_ in scenes for n_ in KASHI_EXTEND):
    KASHI_PARTS = tuple(KASHI_EXTEND)                         # F23 is in (see KASHI_EXTEND)
elif fix_on('kashi'):
    say('F23: left out (%s)' % ('no official update' if af_patch_heap(KASHI_AF) is None else 'not every lead-in part built'))
for n in scenes:
    _x45_from = None
    _kashi_from = None
    if n in KASHI_PARTS:                        # F23: the part runs on to the next part's first AF instruction
        _t = BL.EXTRA_PARTS[n]; _lo, _hi, _kf, _pi, _land = KASHI_EXTEND[n]; _olo, _ohi, _opi = KASHI_OLD[n]
        if (_t[0], _t[1], _t[2], _t[3], _t[4]) != (KASHI_AF, _olo, _ohi, KASHI_PM, _opi) or _kf != _ohi or _lo != _olo:
            raise BuildError('KASHI_EXTEND %s does not extend %s' % (n, _t))
        if n == KASHI_HOST and fix_on('kashipm'):
            _pi = _opi                          # F25: x_3eab17_4957's call stays at its 1.0.0 point
        BL.EXTRA_PARTS[n] = (_t[0], _lo, _hi, _t[3], _pi, _land); _kashi_from = _kf
    if fix_on('c8') and n in X45_EXTEND:        # F16: the part runs on to the next part's first AF instruction
        _t = BL.EXTRA_PARTS[n]; _lo, _hi, _pi, _land = X45_EXTEND[n]
        if (_t[1], _t[4]) != (_lo, _pi) or not _t[2] < _hi or not _t[5] < _land:
            raise BuildError('X45_EXTEND %s does not extend %s' % (n, _t))
        BL.EXTRA_PARTS[n] = (_t[0], _lo, _hi, _t[3], _pi, _land); _x45_from = _t[2]; _x45_done.append(n)
    bl = BL.block(n) if n in BL.SITES else BL.range_block(n)
    if _x45_from is not None: bl = dict(bl, x45_from=_x45_from)
    if _kashi_from is not None: bl = dict(bl, kashi_from=_kashi_from)
    if (DEBUG and n in BL.MARIMO_PARTS and bl['keep'] and af_heap(bl['af']).instrs[bl['keep'][0]][2] == 'CVmFlagOp'
            and n not in ('marimo_rung1', 'marimo_rung2', 'marimo_plus1', 'marimo_ending')):
        bl = dict(bl, keep=bl['keep'][1:]); say('   (debug) %s: route guard removed' % n)
    if n in LEAD_IN:
        bl = dict(bl, lead=lead_in(af_heap(bl['af']), dict(bl, name=n)))
    if fix_on('entry') and n in ENTRY_REPLAY and af_patch_heap(bl['af']) is not None:    # F15: the 2007 entry state
        if n in LEAD_IN: raise BuildError('%s: ENTRY_REPLAY and LEAD_IN' % n)
        bl = dict(bl, entry=ENTRY_REPLAY[n])
    if 'pmexit' in AFR_TEST and n in EXIT_EXTEND and af_patch_heap(bl['af']) is not None:    # F21 (opt-in)
        bl = dict(bl, exit=list(EXIT_EXTEND[n][0]), land=EXIT_EXTEND[n][1] or bl['land'])
    if fix_on('land') and n in LAND_FIX and n not in KASHI_PARTS:    # F07: no PM re-stage between the part and its next line
        bl = dict(bl, land=LAND_FIX[n]); stats_land.append(n)
    if fix_on('c1') and n == YCONT_HOST:         # F17: yuuhi_a ends by calling its route-A continuation
        bl = dict(bl, ycont_call=True)
    P = pm_heaps[bl['pm']]
    pad_count = P.ev[[e[0] for e in P.ev].index('pad')][3]
    if n == KASHI_HOST and n in KASHI_PARTS:
        # F23: the conversation's start AF [4877, 4957) first, as a scene of its own (KASHI ids and keys; no main key
        # allocated: asserted), then x_3eab17_4957 with its call to it as the first instruction
        _kb = kashi_pre_block()
        _k0 = (next_x[0], len(new_objs), keep_id[0], fixwin_id[0], add_id[0], next_id[0])
        _kheap, _kstats, _kmsize = convert_block(_kb, pad_count)
        if (next_x[0], len(new_objs), keep_id[0], fixwin_id[0], add_id[0], next_id[0]) != _k0:
            raise BuildError('KASHI: the start scene moved a main / KEEP / FIXWIN / ADD counter')
        if os.environ.get('DUMP_HEAPS'):
            os.makedirs(os.path.join(OUT, 'built'), exist_ok=True)
            open(os.path.join(OUT, 'built', KASHI_PRE[0] + '.bin'), 'wb').write(_kheap)
        _kobj = bytes([0x00, 0x05]) + CRSA_HDR9 + encrypt_block(_kheap)
        kashi_scene_objs.append((KASHI_SCENE_KEY, _kobj))
        _kr = _keep_report.get(KASHI_PRE[0], {})
        _kashi['pre'] = dict(name=KASHI_PRE[0], af=_kb['af'], af_range=[_kb['lo'], _kb['hi']], instrs=len(_kb['keep']) + 1,
                             heap_bytes=len(_kheap), stats=_kstats, scene_key=hex(KASHI_SCENE_KEY),
                             camera_keep=dict(start=_kr.get('start'), shots=_kr.get('shots', [])),
                             camera_calls=_kr.get('calls', []))
        say('%s (F23, called first by %s) AF %s [%d,%d) -> %d instrs, %d bytes heap, mem %d | %s | key %08x' % (
            KASHI_PRE[0], KASHI_HOST, _kb['af'], _kb['lo'], _kb['hi'], len(_kb['keep']) + 1, len(_kheap), _kmsize,
            _kstats, KASHI_SCENE_KEY))
        if fix_on('kashipm'):
            # F25: the start scene is called from PM's script (its own inserted call before KASHI_PM_CALL[0], landing on
            # x_3eab17_4957's call); that call takes the KASHI id x_3eab17_4957's first instruction takes without F25
            _kashi['pm_call'] = (KASHI_PM_CALL[0], KASHI_PM_CALL[1], (KASHI_SCENE_KEY, enc_size(len(_kobj))), kashi_id[0])
            kashi_id[0] += 1
            by_heap[KASHI_PM].append(_kashi['pm_call'])
        else:
            bl = dict(bl, kashi_call=(KASHI_SCENE_KEY, enc_size(len(_kobj))))
    heap, stats, msize = convert_block(bl, pad_count)
    if os.environ.get('DUMP_HEAPS'):
        os.makedirs(os.path.join(OUT, 'built'), exist_ok=True)
        open(os.path.join(OUT, 'built', n + '.bin'), 'wb').write(heap)
    obj = bytes([0x00, 0x05]) + CRSA_HDR9 + encrypt_block(heap)
    key = alloc_key()
    enc = (key, enc_size(len(obj)))
    scene_objs.append((key, obj))
    if bl.get('ycont_call'): _ycont['host'] = dict(heap=heap, key=key, idx=len(scene_objs) - 1)   # F17 (see below)
    if n not in TEST_NAMES: by_heap[bl['pm']].append((bl['pm_before'] + 1, bl['land'], enc))
    if DEBUG: by_heap[DEBUG_HEAP].append((DEBUG_AT, DEBUG_AT, enc))
    manifest[n] = dict(pm=bl['pm'], insert_before=bl['pm_before'] + 1, land=bl['land'], af=bl['af'],
                       af_range=[bl['lo'], bl['hi']], instrs=len(bl['keep']) + 1, heap_bytes=len(heap), stats=stats,
                       scene_key=hex(key))
    if n in KASHI_PARTS:                # F23: the AF instructions added from kashi_from on (+ the start scene)
        manifest[n]['kashi'] = dict(kashi_from=bl['kashi_from'], old_af_range=list(KASHI_OLD[n][:2]),
                                    old_insert_before=KASHI_OLD[n][2])
        if n == KASHI_HOST:
            manifest[n]['kashi']['pre'] = _kashi['pre']
            if _kashi.get('pm_call'):       # F25: called from PM's script, right before this part's call
                _pc = _kashi['pm_call']
                manifest[n]['kashi']['pre']['pm_call'] = dict(pm=KASHI_PM, insert_before=_pc[0], land=_pc[1], id=hex(_pc[3]))
    kr = _keep_report.get(n, {})
    manifest[n]['camera_keep'] = dict(start=kr.get('start'), shots=kr.get('shots', []))
    manifest[n]['camera_calls'] = kr.get('calls', [])
    manifest[n]['camera_info'] = {
        c[2]: dict((k_, v_) for k_, v_ in (_pic_info if c[3] == 'pic' else _cam_info)[
            (c[2].rsplit('@', 1)[0], int(c[2].rsplit('@', 1)[1]))].items() if k_ != 'key')
        for c in kr.get('calls', [])}
    say('%-9s AF %s [%d,%d) -> %d instrs, %d bytes heap, mem %d | %s | PM %s insert@%d land@%d' % (
        n, bl['af'], bl['lo'], bl['hi'], len(bl['keep']) + 1, len(heap), msize, stats, bl['pm'],
        bl['pm_before'] + 1, bl['land']))
# F17 (C1): yuuhi_a's route-A continuation, after the 73 parts (YCONT ids after yuuhi_a's call; no key allocated: every
# object it uses is yuuhi_b's import), then its size into yuuhi_a's call (the same length: yuuhi_a's object and its
# PM insert keep their sizes). Recorded in yuuhi_a's manifest entry (the manifest lists the parts PM calls).
if _ycont.get('host'):
    _yb = ycont_block()
    _P = pm_heaps[_yb['pm']]
    _keys0 = (next_x[0], lead_x[0], spr_x[0], x45_x[0], kashi_x[0], entry_x[0], exit_x[0]) + tuple(
        len(d_) for d_ in (new_objs, new_objs_lead, new_objs_spr, new_objs_x45, new_objs_kashi, new_objs_entry,
                           new_objs_exit))
    _yheap, _ystats, _ymsize = convert_block(dict(_yb, win_start=_ycont['win']), _P.ev[[e[0] for e in _P.ev].index('pad')][3])
    _keys1 = (next_x[0], lead_x[0], spr_x[0], x45_x[0], kashi_x[0], entry_x[0], exit_x[0]) + tuple(
        len(d_) for d_ in (new_objs, new_objs_lead, new_objs_spr, new_objs_x45, new_objs_kashi, new_objs_entry,
                           new_objs_exit))
    if 'yuuhi_b' in scenes and _keys1 != _keys0:
        raise BuildError('YCONT: the continuation allocated keys (%s -> %s)' % (_keys0, _keys1))
    if FULL_BUILD and (_ystats.get('CVmMsg') != 150 or _ystats.get('fixwin', 0) != int(fix_on('fixwin'))):
        raise BuildError('YCONT: %s lines, %s FIXWIN inserts' % (_ystats.get('CVmMsg'), _ystats.get('fixwin', 0)))
    if os.environ.get('DUMP_HEAPS'):
        open(os.path.join(OUT, 'built', YCONT_PART + '.bin'), 'wb').write(_yheap)
    _obj = bytes([0x00, 0x05]) + CRSA_HDR9 + encrypt_block(_yheap)
    ycont_objs.append((YCONT_SCENE_KEY, _obj))
    _h = _ycont['host']; _ph = struct.pack('<II', YCONT_SCENE_KEY, YCONT_ENC_PH)
    if _h['heap'].count(_ph) != 1: raise BuildError('YCONT: the call in %s found %d times' % (YCONT_HOST, _h['heap'].count(_ph)))
    _hh = _h['heap'].replace(_ph, struct.pack('<II', YCONT_SCENE_KEY, enc_size(len(_obj))))
    _ho = bytes([0x00, 0x05]) + CRSA_HDR9 + encrypt_block(_hh)
    if scene_objs[_h['idx']][0] != _h['key'] or len(_ho) != len(scene_objs[_h['idx']][1]):
        raise BuildError('YCONT: %s object changed size' % YCONT_HOST)
    scene_objs[_h['idx']] = (_h['key'], _ho)
    if os.environ.get('DUMP_HEAPS'):
        open(os.path.join(OUT, 'built', YCONT_HOST + '.bin'), 'wb').write(_hh)
    _kr = _keep_report.get(YCONT_PART, {})
    manifest[YCONT_HOST]['ycont'] = dict(
        name=YCONT_PART, af=_yb['af'], af_range=[_yb['lo'], _yb['hi']], route_from=YCONT_FROM,
        instrs=len(_yb['keep']) + 1, heap_bytes=len(_yheap), stats=_ystats, scene_key=hex(YCONT_SCENE_KEY),
        camera_keep=dict(start=_kr.get('start'), shots=_kr.get('shots', [])), camera_calls=_kr.get('calls', []))
    say('%s (F17, called by %s before its CVmRet) AF %s [%d,%d) -> %d instrs, %d bytes heap, mem %d | %s | key %08x' % (
        YCONT_PART, YCONT_HOST, _yb['af'], _yb['lo'], _yb['hi'], len(_yb['keep']) + 1, len(_yheap), _ymsize,
        _ystats, YCONT_SCENE_KEY))
pm_objs = []
for name, ins in by_heap.items():
    newP = patch_pm(name, ins)
    pos = int(name, 16) - 2
    hdr9 = read_at(PM_RIO, pos + 2, 9); assert hdr9 == CRSA_HDR9, hdr9.hex()
    pm_objs.append(((K + pos // 4) & 0xFFFFFFFF, bytes([0x00, 0x05]) + hdr9 + encrypt_block(newP)))
    say('patched %s: +%d calls' % (name, len(ins)))
# The ruo table lists objects in this order. The restore-audit fixes' objects come after the main / LEAD imports in fix
# order (F15 ENTRY, F16 X45, F17's scene object (ycont_objs), F19 HUTDEPTH, F21 EXIT, F22 SPR, F23 KASHI, F23's start
# scene (kashi_scene_objs)), so a fix appends its objects and every object of the build before it keeps its key and its
# relative table order. Absolute table positions are not kept: an object a fix removes moves every later one down (F22
# bbexact drops the BB_SHRINK override of PM 8fca8611, table index 41, which comes before every scene object and
# import), and the opt-in F19 / F21 objects (fix_objs_late) come before F22 / F23's. PM reads the table into a key map
# (pm.exe FUN_005de150) and finds objects by key (FUN_005df070); nothing depends on a table position.
imports = [(o['enc_off'], o['data']) for o in list(new_objs.values()) + list(new_objs_lead.values())
           + list(new_objs_entry.values()) + list(new_objs_x45.values())]
fix_objs_late = (list(hutdepth_objs.items()) + [(o['enc_off'], o['data']) for o in list(new_objs_exit.values())
                 + list(new_objs_spr.values()) + list(new_objs_kashi.values())])
say('lead-in copies (own key range): %d objects, %.1f MB' % (len(new_objs_lead), sum(len(o['data']) for o in new_objs_lead.values()) / 1e6))
assert all(d is not None for _, d in imports + fix_objs_late)
cls_count = collections.Counter(o['cls'] for o in new_objs.values())
say('imports: %d objects, %.1f MB  %s' % (len(imports + fix_objs_late), sum(len(d) for _, d in imports + fix_objs_late) / 1e6, dict(cls_count)))
# PM ships edited copies of some AF CGs in its own (kept) scenes. Found by decoding both pictures: one connected region
# brightened, everything else identical, and PM holds no copy of the AF original (2026-11-07 asset sweep). The patch
# file overrides those PM objects with the AF original: same key, body = PM header 00 04 + AF body, the form PM uses
# for its 202 byte-identical AF pictures. The engine takes position and size from the ruo entry (FUN_005d9de0), so
# references that still carry PM's size are fine. PM object -> (PM size, AF object, AF size); sizes as rsaparse reports.
CG_OVERRIDES = {
    # AF 7098a5 [5824..6243] / PM 017b6114d2 [6521..6931]
    0x903d179b: (863343, 0x4e732d29, 864980),
    0x900a1c8f: (750869, 0x4a59be5f, 857604),
    0x8e85a1df: (1062525, 0x39bd0a19, 1478080),
    0xbf8b21f1: (1063657, 0x3c5c5d69, 1480550),
    0xbf933f67: (1062623, 0x3c72f4d3, 1478050),
    0xbfab91d7: (1062917, 0x3c898279, 1478344),
    0xbfa376cf: (1062413, 0x3ca01145, 1479284),
    0xbf9b5ad9: (1062889, 0x3cb6a3bd, 1479658),
    0xbfb4e099: (1060217, 0x3ccd37ab, 1476432),
    0xbfcb5c7f: (825425, 0x4f4342d7, 809970),
    # AF 6b9fa1 [1928..2580] / PM 01715ad2b6 [2066..2711]
    0x904d1063: (1126655, 0x4ee1d5f1, 1438686),
    0x9055a8e5: (1144281, 0x4ef7c9d3, 1509418),
    # gallery CG, smaller brightened region
    0x8f874231: (1982227, 0x4557dbf3, 1954476),
    # found by the whole-game sweep (lab-tools/out/research/asset-sweep): same picture, PM changed a region; the display
    # size (stored size x scale) matches the AF original's within 0.25 px, except the two gallery CGs (PM's 2/3-scale
    # copies are 1-2 px larger: 1302.75 x 1516.5 / 1173 x 1374.75 against AF's 1302 x 1515 / 1172 x 1374)
    0x8ed31363: (1027555, 0x3ea33af3, 1153012),     # PM 017faf9266@1307, lower-left region
    0x90e4b04f: (479993, 0x534b4439, 481952),       # PM 01603030ae@2194/3407, small region
    0x8f48daa7: (1064051, 0x42565d89, 1886362),     # gallery CG, PM 0185cdd1de@1582-1626, 01ab8c3d66@3647
    0x8fc2711d: (1059299, 0x4980f293, 2135192),     # gallery CG, PM 019e6f962e@380-407, brightened right side
}
# PM pictures that are crops / rescales of an edited CG (no AF object has their geometry): rebuilt from the AF original
# at patch time (cgcrop: resample into PM's window, re-encode with PM's coder, PM's header kept).
# pm_off: (pm_size, af_off, af_size, (k = PM px per AF px, x, y = AF position of the window))
CG_RECROPS = {
    # close-ups cut from the edited hot-spring CG 900a1c8f (= AF 4a59be5f), PM 017b6114d2@6764-6899
    0xbfbf1ad7: (302687, 0x4a59be5f, 857604, (1.051655, 1114.488281, 54.474609)),
    0xbfbcf757: (280315, 0x4a59be5f, 857604, (1.177599, -0.250000, 113.697266)),
    0xbfc8b419: (324751, 0x4a59be5f, 857604, (1.575044, 1314.396484, 85.210938)),
    0xbfc16a09: (329475, 0x4a59be5f, 857604, (2.170558, 975.550781, 407.312500)),
    0xbfc3ed8d: (329053, 0x4a59be5f, 857604, (1.853449, 344.341797, 348.089844)),
    0xbf887125: (352659, 0x4a59be5f, 857604, (2.508623, 565.490234, 448.292969)),
    0xbfc6703d: (296883, 0x4a59be5f, 857604, (2.249424, 815.375000, 563.990234)),
    # 16:9 cuts of the tall 45d98b CGs, PM 01b8c7a482@2039-2115 (deb5c25d stands for AF 4575aea3 and 46f6f13b; the
    # closer one is used)
    0x8f9661bd: (1690943, 0x4620f395, 2798134, (0.901536, 2.085938, 220.78125)),
    0xdeb5c25d: (1690379, 0x4575aea3, 2810464, (0.901536, 2.085938, 220.78125)),
    0xdec2a7e5: (1689435, 0x46a130f1, 2809958, (0.901536, 2.085938, 220.78125)),
}
cg_objs = []
for pm_off, (pm_size, af_off, af_size) in CG_OVERRIDES.items():
    schema_, body_, raw_, (n_, mode_, extra_) = af_object(af_off, af_size)
    if mode_ != 0 or schema_ != 3 or body_[28:30] != b'\x00\x00':
        raise BuildError('CG override %x <- %x: unexpected AF header' % (pm_off, af_off))
    if pm_object(pm_off, pm_size)[:2] != b'\x00\x04':
        raise BuildError('CG override %x: unexpected PM header' % pm_off)
    cg_objs.append(((K + (pm_off - 3) // 2) & 0xFFFFFFFF, b'\x00\x04' + body_))
say('CG overrides (AF originals of edited PM pictures): %d, %.1f MB' % (len(cg_objs), sum(len(d) for _, d in cg_objs) / 1e6))
_srcs = {}
_t0 = time.time()
_recrops = []
for pm_off, (pm_size, af_off, af_size, crop_) in sorted(CG_RECROPS.items(), key=lambda kv: kv[1][1]):
    schema_, body_, raw_, (n_, mode_, extra_) = af_object(af_off, af_size)
    pm_raw_ = pm_object(pm_off, pm_size)
    if mode_ != 0 or schema_ != 3 or pm_raw_[:2] != b'\x00\x04':
        raise BuildError('CG re-crop %x <- %x: unexpected header' % (pm_off, af_off))
    need_ = cgcrop.rows_needed(cgcrop.header(body_)['h'], crop_[0], crop_[2], cgcrop.header(pm_raw_[2:])['h'])
    _recrops.append((pm_off, af_off, body_, pm_raw_, crop_, need_))
# each AF picture is decoded once, for the most rows any of its crops needs; a crop gets the first rows it needs
# (resample reads only those: the same bytes as decoding exactly that many). A cached crop needs no decode at all.
_rows_max = {}
for pm_off, af_off, body_, pm_raw_, crop_, need_ in _recrops:
    _rows_max[af_off] = max(_rows_max.get(af_off, 0), need_)
for pm_off, af_off, body_, pm_raw_, crop_, need_ in _recrops:
    def _source(af_off=af_off, body_=body_, need_=need_):
        if af_off not in _srcs:
            _srcs.clear(); _srcs[af_off] = cgcrop.decode(body_, _rows_max[af_off])
        W_, H_, rows_ = _srcs[af_off]
        return W_, H_, rows_[:need_]
    new_ = reencache.recrop(pm_raw_[2:], body_, crop_, _source)
    cg_objs.append(((K + (pm_off - 3) // 2) & 0xFFFFFFFF, b'\x00\x04' + new_))
_srcs.clear(); del _recrops
say('CG crops rebuilt from AF originals: %d (%.0fs)' % (len(CG_RECROPS), time.time() - _t0))
# BB_SHRINK: an oversized billboard picture that PM also has byte for byte stays PM's object (gallery unlocks,
# saves) and that object is overridden with the smaller re-encode (the engine reads the size from the ruo entry)
for af_off in sorted(BB_SHRINK):
    pm_ = mapped(af_off)
    if pm_ is None: continue                         # imported (re-encoded in key_alloc)
    sz_ = objmap[str(af_off)]['af'][2]
    if not image_identical(af_off, sz_, pm_): continue
    schema_, body_, raw_, (n_, mode_, extra_) = af_object(af_off, sz_)
    small_, used_ = reencache.shrink(body_, BB_SHRINK_LIMIT)
    if small_ is None: raise BuildError('bbsmall: %x does not fit' % af_off)
    cg_objs.append(((K + (pm_ - 3) // 2) & 0xFFFFFFFF, b'\x00\x04' + small_))
    bb_shrunk.append(('PM %x' % pm_, len(raw_), len(small_), used_))
# Id and key ranges (FIXPLAN id_ranges / key_ranges): every counter and slot inside its own range, every import key
# inside its mode's range; one log line per range. A full release-form build (every part, no debug entry) uses exactly
# the counts of 1.0.0 in the ranges 1.0.0 had (checked below); a debug / test-part build may use more in the main range.
ID_RANGES = (('main', ID_BASE, ID_BASE + 0x25FD if FULL_BUILD else LEAD_ID_BASE, next_id),
             ('LEAD', LEAD_ID_BASE, ADD_ID_BASE, lead_id), ('ADD', ADD_ID_BASE, KEEP_ID_BASE, add_id),
             ('KEEP', KEEP_ID_BASE, OVL_ID_BASE, keep_id), ('OVL', OVL_ID_BASE, PATCH_ID_BASE, ovl_id),
             ('PATCH', PATCH_ID_BASE, FIXEND_ID_BASE, patch_id), ('FIX_END', FIXEND_ID_BASE, FIXWIN_ID_BASE, fixend_id),
             ('FIXWIN', FIXWIN_ID_BASE, 0x3F340, fixwin_id), ('YCONT', YCONT_ID_BASE, X45_ID_BASE, ycont_id),
             ('X45', X45_ID_BASE, 0x3F700, x45_id), ('KASHI', KASHI_ID_BASE, EXCL_ID_BASE, kashi_id),
             ('EXCL', EXCL_ID_BASE, 0x3F910, excl_id), ('RETID', RETID_ID_BASE, 0x3F920, retid_id),
             ('WINSHOW', WINSHOW_ID_BASE, 0x3F360, winshow_id))
for _nm, _lo, _hi, _c in ID_RANGES:
    if not _lo <= _c[0] <= _hi: raise BuildError('instruction id range %s overflows: next %#x, range %#x-%#x' % (_nm, _c[0], _lo, _hi))
    say('ids %-8s %#x-%#x: %s' % (_nm, _lo, _hi - 1, '%#x-%#x (%d)' % (_lo, _c[0] - 1, _c[0] - _lo) if _c[0] > _lo else 'none'))
# A full build uses exactly 1.0.0's counts where 1.0.0 allocated: main ids (the 9,652 part ids + the 73 PM-insert ids),
# LEAD ids 18, ADD ids 38, main keys 5,171 (73 scene objects + 5,098 imports); without the official update 1.0.0's
# builder (b0286e68) makes 9,217 + 73, 18, 22 and 5,046. A fix that dropped or added an instruction or an import there
# would move every later id or key: refused.
_exact = (('main ids', next_id[0] - ID_BASE, 0x25FD if HAVE_UPDATE else 9290),
          ('LEAD ids', lead_id[0] - LEAD_ID_BASE, 18), ('ADD ids', add_id[0] - ADD_ID_BASE, 38 if HAVE_UPDATE else 22),
          ('main keys', (next_x[0] - NEW_KEY_BASE) // 0x10, 5171 if HAVE_UPDATE else 5046))
if FULL_BUILD and any(h_ != w_ for _, h_, w_ in _exact):
    raise BuildError('full build counts (have, want): %s' % [(n_, h_, w_) for n_, h_, w_ in _exact if h_ != w_])
for _kind, _base, _order in (('ENTRY', ENTRY_ID_BASE, ENTRY_ORDER), ('EXIT', EXIT_ID_BASE, EXIT_ORDER)):
    _u = sorted(x for (k_, n_), v_ in _slot_used.items() if k_ == _kind.lower() for x in v_)
    if any(not _base <= x < _base + 0x10 * len(_order) for x in _u): raise BuildError('%s slot ids out of range' % _kind)
    say('ids %-8s %#x-%#x: %s' % (_kind, _base, _base + 0x10 * len(_order) - 1,
                                  '%#x-%#x (%d)' % (_u[0], _u[-1], len(_u)) if _u else 'none'))
for _nm, _lo, _hi in KEY_RANGES:
    _ks = sorted(((k_ - K) & 0xFFFFFFFF) for k_, _ in imports + fix_objs_late + scene_objs + ycont_objs + kashi_scene_objs
                 if _lo <= ((k_ - K) & 0xFFFFFFFF) < _hi)
    say('keys %-8s %#x-%#x: %s' % (_nm, _lo, _hi - 1, '%#x-%#x (%d)' % (_ks[0], _ks[-1], len(_ks)) if _ks else 'none'))
for _nm, _d, _lo, _hi in (('main', new_objs, 0x78000000, 0x7F000000), ('LEAD', new_objs_lead, 0x7F000000, 0x7F400000),
                          ('SPR', new_objs_spr, 0x7F400000, 0x7F800000), ('X45', new_objs_x45, 0x7F800000, 0x7F900000),
                          ('KASHI', new_objs_kashi, 0x7F900000, 0x7FA00000),
                          ('ENTRY', new_objs_entry, 0x7FC00000, 0x7FD00000),
                          ('EXIT', new_objs_exit, 0x7FD00000, 0x7FE00000)):
    _bad = [hex(o_['enc_off']) for o_ in _d.values() if not _lo <= ((o_['enc_off'] - K) & 0xFFFFFFFF) < _hi]
    if _bad: raise BuildError('%s imports outside their key range: %s' % (_nm, _bad[:5]))
if any(k_ != HUTDEPTH_KEY for k_ in hutdepth_objs): raise BuildError('hutdepth object key')
if [k_ for k_, _ in ycont_objs] not in ([], [YCONT_SCENE_KEY]): raise BuildError('F17 scene object key')
if [k_ for k_, _ in kashi_scene_objs] not in ([], [KASHI_SCENE_KEY]): raise BuildError('F23 scene object key')
if any(not 0x78000000 <= ((k_ - K) & 0xFFFFFFFF) < 0x7F000000 for k_, _ in scene_objs):
    raise BuildError('scene keys outside the main key range')
# F05 (C5): only Marimo's BGM stream 65b7add7 (of every import) needs the trailing-bytes rule, and its stored stream
# parses from offset 0 to exactly its length
if fix_on('c5'):
    if not (_oor_tail == {0x65b7add7} if FULL_BUILD else _oor_tail <= {0x65b7add7}):
        raise BuildError('C5: streams with trailing bytes %s' % [hex(x) for x in _oor_tail])
    for _af in _oor_tail:
        _d = next(d_[_af]['data'] for d_ in (new_objs, new_objs_lead, new_objs_spr, new_objs_x45, new_objs_kashi,
                                             new_objs_entry, new_objs_exit) if _af in d_)
        if read_stream(_d, 0)[1] != len(_d): raise BuildError('C5: stream %x does not end at its length' % _af)
    say('C5 streams stored up to their end page: %s' % [hex(x) for x in sorted(_oor_tail)])
# F06: exactly one PM port sound emitted (chizuru AF 7736 -> 01b8c7a482 #2232)
if fix_on('pmsnd') and FULL_BUILD and sum(v['stats'].get('pm_port_sound', 0) for v in manifest.values()) != 1:
    raise BuildError('PM_PORT_SOUND: %d emitted, not 1' % sum(v['stats'].get('pm_port_sound', 0) for v in manifest.values()))
# F07: every LAND_FIX part landed at its new point (x_3eab17_4970 only while F23 does not merge it)
if fix_on('land'):
    if FULL_BUILD and sorted(stats_land) != sorted(p_ for p_ in LAND_FIX if p_ not in KASHI_PARTS):
        raise BuildError('LAND_FIX: landed %s' % sorted(stats_land))
    say('F07 landings moved: %s' % ', '.join('%s %d' % (p_, LAND_FIX[p_]) for p_ in stats_land))
# F11: mikoto / meiya end on PM's stop-all, kasumi_h on the update's white fade + stop-all (FIX_END 0x3F300-0x3F303)
if fix_on('c6'):
    _fe = {n_: v['stats'].get('fixend', 0) for n_, v in manifest.items() if v['stats'].get('fixend')}
    if FULL_BUILD and af_patch_heap(BL.range_block('kasumi_h')['af']) is not None and _fe != {'meiya': 1, 'mikoto': 1, 'kasumi_h': 2}:
        raise BuildError('FIXEND: %s' % _fe)
    say('C6 chapter-end stops: %s' % _fe)
# F12: the window hidden before every white fade that found it shown (8 sites; + kasumi_h's end fade with F11)
if fix_on('fixwin'):
    _fw = {n_: v['stats'].get('fixwin', 0) for n_, v in manifest.items() if v['stats'].get('fixwin')}
    _fw_want = {'yuuhi_a': 2, 'yuuhi_b': 2, 'meiya': 3, 'marimo_chapter': 1}
    if fix_on('c6') and af_patch_heap(BL.range_block('kasumi_h')['af']) is not None: _fw_want['kasumi_h'] = 1
    if FULL_BUILD and _fw != _fw_want: raise BuildError('FIXWIN: %s, expected %s' % (_fw, _fw_want))
    say('C14 window hidden before white fades: %s' % _fw)
# F13: x_4f4791_1674 / x_4f4791_1762 start and end with Mikoto's exclusive camera (EXCL 0x3F900-0x3F903)
if fix_on('excl'):
    _ex = {n_: v['stats'].get('excl_cam', 0) for n_, v in manifest.items() if v['stats'].get('excl_cam')}
    if FULL_BUILD and _ex != {p_: 2 for p_ in EXCL_PARTS}: raise BuildError('EXCL: %s' % _ex)
    say('F13 exclusive camera on / off: %s' % _ex)
# F14: exactly the 3 update-only lines folded and emitted, the 3 split first pieces take the update's form, one timed wait
if fix_on('c2'):
    _c2n = {n_: v['stats'].get('c2_line', 0) for n_, v in manifest.items() if v['stats'].get('c2_line')}
    _c2w = sum(v['stats'].get('c2_wait', 0) for v in manifest.values())
    if FULL_BUILD and af_patch_heap(BL.block('sumika')['af']) is not None and (
            _c2_done['fold'] != C2_FOLD or _c2_done['split'] != C2_SPLIT or _c2w != 1
            or _c2n != {'sumika': 1, 'mikoto': 1, 'kasumi_h': 1}):
        raise BuildError('C2: folded %s, split %s, lines %s, timed waits %d' % (
            sorted(_c2_done['fold']), sorted(_c2_done['split']), _c2n, _c2w))
    say('C2 split lines: update-only lines folded %s, first pieces in the update form %s, timed waits %d' % (
        ', '.join('%s %05x' % x for x in sorted(_c2_done['fold'])), ', '.join('%s %05x' % x for x in sorted(_c2_done['split'])),
        _c2w))
# F15: every ENTRY_REPLAY part replayed its whole list (ids from its ENTRY slot; the 'ids ENTRY' line above)
if fix_on('entry'):
    _en = {n_: v['stats'].get('entry_replay_instrs', 0) for n_, v in manifest.items() if v['stats'].get('entry_replay_instrs')}
    if FULL_BUILD and af_patch_heap(BL.block('sumika')['af']) is not None and _en != {p_: len(v_) for p_, v_ in ENTRY_REPLAY.items()}:
        raise BuildError('ENTRY: replayed %s' % _en)
    say('F15 entry replays (items per part): %s' % _en)
# F16: the four Myun x Chizuru parts run on to the next part (X45 ids / keys)
if fix_on('c8'):
    _xn = {n_: v['stats'].get('x45_instrs', 0) for n_, v in manifest.items() if v['stats'].get('x45_instrs')}
    if FULL_BUILD and (sorted(_x45_done) != sorted(X45_EXTEND) or sorted(_xn) != sorted(X45_EXTEND)):
        raise BuildError('X45: extended %s, added instructions %s' % (_x45_done, _xn))
    say('C8 parts run on to the next part (added AF instructions): %s' % _xn)
# F09: every AF ocean of the tables was used and checked; 72 lines name their speaker, 69 of them = the update's link
if fix_on('c15'):
    _spk_n = sum(v['stats'].get('c15_speaker', 0) for v in manifest.values())
    _lnk_n = sum(v['stats'].get('c15_link', 0) for v in manifest.values())
    # (lines F16 and F23 add are counted apart: the 72 / 69 are the parts' own lines)
    _spk_x = sum(v['stats'].get('c15_speaker_x45', 0) + v['stats'].get('c15_speaker_kashi', 0) for v in manifest.values())
    _lnk_x = sum(v['stats'].get('c15_link_x45', 0) + v['stats'].get('c15_link_kashi', 0) for v in manifest.values())
    if FULL_BUILD and (set(_c15_checked) != set(VOICE_OCEAN_PM) | set(VOICE_SPK_BOX) or _spk_n - _spk_x != 72
                       or _lnk_n - _lnk_x != (69 if HAVE_UPDATE else 0)):     # (the links are the update's)
        raise BuildError('C15: oceans checked %d of %d, speaker lines %d (72), update links %d (69)' % (
            len(_c15_checked), len(VOICE_OCEAN_PM) + len(VOICE_SPK_BOX), _spk_n - _spk_x, _lnk_n - _lnk_x))
    say('C15 voices: %d imports parented to their PM ocean (per part), %d lines with an explicit speaker (%d = the '
        "update's link), %d AF oceans checked" % (_c15_stats['voice_parent_pm'], _spk_n, _lnk_n, len(_c15_checked))
        + (' (of these on F16 / F23 lines: %d speakers, %d links)' % (_spk_x, _lnk_x) if _spk_x or _lnk_x else ''))
# F18 (opt-in): the applies rewritten (every heap pass; the parts emit those inside their ranges)
if 'fadetime' in AFR_TEST:
    say('F18 fadetime: %d applies rewritten in the AF / update heaps, by (type, AF ms -> ms): %s' % (
        len(_fadetime_log), dict(collections.Counter((t, a, b) for t, a, b in _fadetime_log.values()))))
# F19 (opt-in): meiya's call of AF 7696d25b draws the re-framed copy (one object, HUTDEPTH_KEY)
if 'hutdepth' in AFR_TEST:
    if FULL_BUILD and list(hutdepth_objs) != [HUTDEPTH_KEY]: raise BuildError('hutdepth: %d objects' % len(hutdepth_objs))
    say('F19 hutdepth: %s' % ['%08x (%d bytes, from PM %x: rect z 18000, b8 2.15625)' % (k_, len(v_), HUTDEPTH_PM)
                              for k_, v_ in hutdepth_objs.items()])
# F21 (opt-in): the four parts end with the update's staging of the next shot (EXIT slots)
if 'pmexit' in AFR_TEST:
    _xe = {n_: v['stats'].get('exit_instrs', 0) for n_, v in manifest.items() if v['stats'].get('exit_instrs')}
    if FULL_BUILD and af_patch_heap(BL.block('sumika')['af']) is not None and _xe != {p_: len(v_[0]) for p_, v_ in EXIT_EXTEND.items()}:
        raise BuildError('EXIT: %s' % _xe)
    say('F21 pmexit (update staging after the part, items per part): %s' % _xe)
# F23: the three lead-in parts carry the whole conversation (KASHI ids / keys), the start scene is called first
if KASHI_PARTS:
    _ka_ = {n_: manifest[n_]['stats'].get('kashi_instrs', 0) for n_ in KASHI_PARTS}
    _kw = {n_: KASHI_EXTEND[n_][1] - KASHI_EXTEND[n_][2] for n_ in KASHI_PARTS}
    _kp = _kashi['pre']['stats']
    _kenp = sum(manifest[n_]['stats'].get('en_pm_kept', 0) for n_ in KASHI_PARTS) + _kp.get('en_pm_kept', 0)
    _kpm = fix_on('kashipm')             # F25: the start scene's call is PM's inserted call, not the part's first instruction
    if (_ka_ != _kw or manifest[KASHI_HOST]['stats'].get('kashi_call', 0) != (0 if _kpm else 1) or _kp.get('fixwin', 0)
            or len(_kashi['pre']['af_range']) != 2 or bool(_kashi.get('pm_call')) != _kpm
            or (_kpm and manifest[KASHI_HOST]['insert_before'] != KASHI_OLD[KASHI_HOST][2])):
        raise BuildError('KASHI: added %s (want %s), start scene %s' % (_ka_, _kw, _kp))
    say('F23 Kashiwagi lead-in as 2007: start scene %s %d lines, added AF instructions %s, lines with PM English kept %d of '
        '%d PM lines (%d with another trailing click), %s' % (
            KASHI_PRE[0], _kp.get('CVmMsg', 0), _ka_, _kenp, len(pm_en_kashi()),
            sum(manifest[n_]['stats'].get('en_pm_click_differs', 0) for n_ in KASHI_PARTS) + _kp.get('en_pm_click_differs', 0),
            'F25: the start scene called from PM before %d (id %#x, landing on %s\'s call at %d)' % (
                _kashi['pm_call'][0], _kashi['pm_call'][3], KASHI_HOST, _kashi['pm_call'][1]) if _kpm else
            'PM insert %d -> %d' % (KASHI_OLD[KASHI_HOST][2], KASHI_EXTEND[KASHI_HOST][3])))
# F26: the window shown before a line without a visible code unit that found it hidden: F14's three update-only lines
if fix_on('winshow'):
    _ws = {n_: v['stats'].get('winshow', 0) for n_, v in manifest.items() if v['stats'].get('winshow')}
    for v in manifest.values():
        for x_ in (v.get('ycont'), (v.get('kashi') or {}).get('pre')):
            if isinstance(x_, dict) and x_.get('stats', {}).get('winshow'): _ws[x_['name']] = x_['stats']['winshow']
    _ws_want = {'sumika': 1, 'mikoto': 1, 'kasumi_h': 1} if (fix_on('c2') and HAVE_UPDATE) else {}
    if FULL_BUILD and _ws != _ws_want: raise BuildError('WINSHOW: %s, expected %s' % (_ws, _ws_want))
    say('F26 window shown before a line without visible text that found it hidden: %s' % _ws)
# F24: the closing CVmRet a CVmCall returns to carries a RETID id (saves inside that call)
if fix_on('retid'):
    _rt = [n_ for n_, v in manifest.items() if v['stats'].get('retid')]
    _rt += [x_['name'] for v in manifest.values() for x_ in (v.get('ycont'), (v.get('kashi') or {}).get('pre'))
            if isinstance(x_, dict) and x_.get('stats', {}).get('retid')]
    say('F24 closing CVmRet with an id (a CVmCall returns to it): %s' % ', '.join(_rt))
# F22 (C13): exact copies. bbexact: no billboard re-encode (BB_SHRINK empty); sprexact: the AF sprites with a PM pair
# and their nested objects imported in the SPR key range
if fix_on('bbexact') and not BB_CONVERT:
    say('F22 bbexact: billboard pictures keep their AF bytes (re-encode %s)' % ('on: AFR_TEST bbsmall' if BB_SHRINK_LIMIT else 'off'))
if fix_on('sprexact'):
    _sp = [a_ for a_, o_ in new_objs_spr.items() if o_['cls'] == 'CRmt' and mapped(a_) is not None]
    say('F22 sprexact: %d SPR imports (%s), of them %d AF sprites with a PM pair' % (
        len(new_objs_spr), dict(collections.Counter(o_['cls'] for o_ in new_objs_spr.values())), len(_sp)))
# CAMERA_KEEP: the default-family build (every part, the exact framing, kept camera in every part) keeps its 65 inserts
# (KEEP ids; the inserts attached to fix-added instructions take the fix's ids); 60 without the official update (the
# unpatched staging: 1.0.0's builder b0286e68 makes the same 60)
_keep_want = 65 if HAVE_UPDATE else 60
if (FULL_BUILD and OLD_ZOOM and not PRE_EXACT and CAMERA_KEEP and CAMERA_KEEP_ALL
        and keep_id[0] - KEEP_ID_BASE != _keep_want):
    raise BuildError('CAMERA_KEEP: %d inserts (KEEP ids), not %d' % (keep_id[0] - KEEP_ID_BASE, _keep_want))
from ruowrite import write_ruo
objs = pm_objs + cg_objs + scene_objs + imports + ycont_objs + fix_objs_late + kashi_scene_objs
res = write_ruo(sys.argv[1], objs)
say('wrote %s %s, %d objects' % (sys.argv[1], res, len(objs)))
json.dump(manifest, open(os.path.join(OUT, 'build_manifest.json'), 'w'), indent=1)
if os.environ.get('DUMP_HEAPS'):    # built/ holds exactly this build's part heaps (validate_built.py checks every file there)
    for _p in sorted(glob.glob(os.path.join(OUT, 'built', '*.bin'))):     # (+ F17's continuation when built)
        if os.path.basename(_p)[:-4] not in manifest and not (ycont_objs and os.path.basename(_p)[:-4] == YCONT_PART) \
                and not (kashi_scene_objs and os.path.basename(_p)[:-4] == KASHI_PRE[0]):
            os.remove(_p); say('removed stale heap built/%s (not a part of this build)' % os.path.basename(_p))
c = collections.Counter((k, sz <= 200) for (k, _, sz, _) in nested_log)
say('nested refs: %s' % dict(c))
for e in nested_log:
    if e[0] == 'import' and e[2] <= 200: say('   small nested import (shared object?) %s size %d' % (e[1], e[2]))
say('CRimp sprite sets converted: %d' % len(crimp_done))
for _n in manifest:                 # emitted camera calls only (the heap pass also sees calls outside the parts)
    for _c in manifest[_n]['camera_calls']:
        if _c[3] == 'cam': _frame_log[frame_kind(manifest[_n]['camera_info'][_c[2]].get('note', 'not rewritten'))] += 1
say('camera calls in the parts by rule (%s%s): %s' % (RULE_NAME, ' unless noted' if not OLD_ZOOM else '',
                                                     dict(_frame_log)))
if PRE_EXACT:
    say('pre-exact rule (and bb2bg range), all heap passes: cameras zoomed x%s: %d, CG shots raised to fill the screen '
        '(FILL_FLOOR): %d' % (IMPORTED_IMAGE_ZOOM, _zoomed[0], _floored[0]))
say("near plane (instant sets on the 2D path above PM's near-plane distance): %s" % (
    _near_log if NEAR_PLANE_ON else 'off: AFR_TEST nonearplane'))
say('billboard shots drawn as backgrounds: %d' % _bb2bg[0])
_kc = collections.Counter((r['kind'], r['action']) for v in _keep_report.values() for r in v['shots'])
say('CAMERA_KEEP (%s): %s' % ('off: AFR_TEST nokeep' if not CAMERA_KEEP else 'every part' if CAMERA_KEEP_ALL else
                              'parts %s: AFR_TEST keepmikoto' % ', '.join(KEEP_PARTS), dict(_kc)))
for _n, _v in _keep_report.items():
    for _r in _v['shots']:
        if 'out' in _r:
            say('   %-15s #%-5d %s after picture #%d (%s): kept AF camera %s from %s -> %s' % (
                _n, _r['out'], _r['kind'], _r['pic_out'], _r['pic'], list(_r['kept']['cam'][:3]) + [_r['kept']['dist']]
                + list(_r['kept']['cam'][3:]), _r['kept']['src'], _r['pm']))
say('case-25 screen shocks -> PM port Ex2 + 27e99af5: %d' % _shock25_done[0])
say('shake calls followed by PM\'s 0-ms apply 27e9379d(0, 0): %d' % _shake_apply_done[0])
say('shake waits timed: %d after a waiting shake call, %d in place of a b=16 sync on the shake var; %d such syncs left '
    'unpaired %s' % (_shake_wait_done['after'], _shake_wait_done['replace'], len(_shake_unpaired_out), _shake_unpaired_out[:8]))
say('instruction ids: main %#x-%#x, lead-in %#x-%#x, added %#x-%#x, kept-camera inserts %#x-%#x' % (
    ID_BASE, next_id[0] - 1, LEAD_ID_BASE, lead_id[0] - 1, ADD_ID_BASE, add_id[0] - 1, KEEP_ID_BASE, keep_id[0] - 1))
if bb_shrunk: say('billboard pictures re-encoded (BB_SHRINK_LIMIT): %s' % bb_shrunk)
reencache.finish(say)
log.close()          # the whole log is on disk when the build returns (an in-process caller copies it next)
