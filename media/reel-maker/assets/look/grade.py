"""grade.py - the "ember" colour look (3D LUT with skin protection) + per-shot matching to a per-reel target.

Pipeline per shot (drop-in for the engine's `color_chain(...)`, same slot in the decode chain):

    [hqdn3d denoise]  ->  curves (per-shot WB + black point + percentile tone match, pchip)  ->  lut3d ember.cube  ->  cas  [-> grain]

API
    configure(lut_dir, name="ember")          where the .cube files live (default: $REEL_BUILD_DIR/look, i.e. ./build/look); call before first use
    LUT_PATH / LUT_FOOD_PATH                  <name>.cube + <name>_food.cube (33^3; written on first use if missing)
    build_lut(n=33) / write_cube(path)        regenerate the LUT (see make_lut.py for the CLI)
    reel_target(shots)            -> dict     look target of one reel; shots = [(path, opts, crop, t0, t1), ...] (or dicts)
    shot_filter(path, opts, crop, t0, t1, reel_target, **kw) -> str    ffmpeg filter chain (no leading/trailing comma)
    shot_filter_parts(...)        -> (pre, post)   same chain split so `pre` (denoise) can go BEFORE scale
    image_filter(img_rgb, reel_target, **kw) -> str   same for a still (numpy RGB uint8)
"""
import math, os, subprocess, json
from pathlib import Path
import numpy as np
import cv2
from scipy.interpolate import PchipInterpolator

from cmx import rgb2lab, lab2rgb, lab2lch, lch2lab, luma, s2l, l2s
import faces as FC

HERE = Path(__file__).parent
DEFAULT_DIR = Path(os.environ.get("REEL_BUILD_DIR", "./build")) / "look"   # never the skill folder: LUTs are generated files
LUT_PATH = DEFAULT_DIR / "ember.cube"
LUT_NAME = "ember"

# ============================================================================ the look (analytic) -> 33^3 LUT
LUT_FOOD_PATH = DEFAULT_DIR / "ember_food.cube"   # same look, warmer/richer for food footage (no skin protection)
PARAMS = dict(
    # tone: control points of a monotone cubic through (encoded luma in -> out); soft toe, gentle S, long shoulder, 1.0 -> 0.975
    tone_x=[0.00, 0.04, 0.10, 0.20, 0.32, 0.45, 0.58, 0.70, 0.82, 0.92, 1.00],
    tone_y=[0.000, 0.025, 0.067, 0.152, 0.271, 0.440, 0.617, 0.750, 0.857, 0.927, 0.965],
    luma_mix=0.65,                  # share of the hue-preserving (luma-ratio) tone mapping vs per-channel S
    # split tone (Lab a/b offsets)
    shadow_ab=(-2.6, -1.8), shadow_L=(10, 48),      # cool teal, weight 1 at L<=10 fading out by L=48
    high_ab=(1.0, 3.4), high_L=(62, 92),            # warm amber, 0 at L<=62 -> 1 at L>=92
    # skin: hue band of Lab h_ab; natural skin sits around h 44-52, C 30-36 in warm evening light
    skin_hue=(36, 62, 20), skin_C0=31.0, skin_Cslope=0.55, attract=(42, 58), attract_k=0.55, attract_band=(22, 75, 22),
    sat=1.11, vibrance=0.15, fire=0.20, food=0.22, magenta=0.22,
    food_band=(22, 70, 12), food_C=(28, 48), food_L=(38, 58),
    skin_on=True, mid_ab=(0.0, 0.0), mid_L=(15, 35, 70, 90),
    shadow_chroma_floor=0.6, high_chroma_cut=0.45,
)

FOOD_PARAMS = {**PARAMS, "skin_on": False, "vibrance": 0.30, "fire": 0.25, "food": 0.42, "food_band": (24, 80, 12), "food_C": (8, 28),
               "food_L": (55, 80), "mid_ab": (2.0, 5.5), "sat": 1.08}


def _sm(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _hue_band(h, lo, hi, feather):
    c, half = (lo + hi) / 2, (hi - lo) / 2
    d = np.abs((h - c + 180) % 360 - 180)
    return 1 - _sm(d, half, half + feather)


def ember_look(rgb, P=PARAMS):
    """The look: (...,3) encoded sRGB floats in [0,1] -> same. All maths float64."""
    rgb = np.clip(np.asarray(rgb, np.float64), 0, 1)
    tone = PchipInterpolator(P["tone_x"], P["tone_y"])
    y = luma(rgb)
    ratio = np.where(y > 1e-3, tone(y) / np.maximum(y, 1e-3), float(tone(1e-3)) / 1e-3)
    t = P["luma_mix"] * rgb * ratio[..., None] + (1 - P["luma_mix"]) * tone(rgb)
    t = np.clip(t, 0, 1.2)
    lab = rgb2lab(t)
    lch = lab2lch(lab)
    L, C, h = lch[..., 0], lch[..., 1], lch[..., 2]
    # --- skin weight (Lab hue band x moderate chroma x mid/high lightness)
    wc = _sm(C, 6, 14) * (1 - _sm(C, 44, 62))
    wl = _sm(L, 22, 40) * (1 - _sm(L, 88, 97))
    w_skin = _hue_band(h, *P["skin_hue"][:2], P["skin_hue"][2]) * wc * wl
    w_attr = _hue_band(h, *P["attract_band"]) * wc * wl
    if not P["skin_on"]:
        w_skin, w_attr = w_skin * 0, w_attr * 0
    # --- chroma
    gain = P["sat"] + P["vibrance"] * (1 - _sm(C, 0, 70))
    w_fire = _hue_band(h, 38, 78, 14) * _sm(C, 42, 72) * _sm(L, 30, 55)
    w_food = _hue_band(h, *P["food_band"]) * _sm(C, *P["food_C"]) * (1 - _sm(L, *P["food_L"]))
    w_mag = _hue_band(h, 290, 355, 15) * _sm(C, 28, 55)
    gain = gain * (1 + P["fire"] * w_fire) * (1 + P["food"] * w_food) * (1 - P["magenta"] * w_mag)
    C0 = P["skin_C0"]
    c_skin = np.where(C > C0, C0 + (C - C0) * P["skin_Cslope"], C)
    C2 = C * gain * (1 - w_skin) + c_skin * w_skin
    C2 = C2 * (P["shadow_chroma_floor"] + (1 - P["shadow_chroma_floor"]) * _sm(L, 2, 22)) * (1 - P["high_chroma_cut"] * _sm(L, 86, 99))
    # --- hue attractor toward the natural skin band
    ht = np.clip(h, *P["attract"])
    dh = np.where(h > 200, 0.0, ht - h)  # only the 0..~100 deg warm side
    h2 = h + P["attract_k"] * w_attr * dh
    L2 = L - 2.0 * w_food
    lab2 = lch2lab(np.stack([L2, C2, h2], -1))
    # --- split tone (protected on skin)
    ws = (1 - _sm(L2, *P["shadow_L"])) * _sm(L2, 0.5, 16)  # no tint on pure black (tiny L steps are big RGB steps)
    wh = _sm(L2, *P["high_L"])
    prot = 1 - 0.7 * w_skin
    wm = _sm(L2, *P["mid_L"][:2]) * (1 - _sm(L2, *P["mid_L"][2:]))
    lab2[..., 1] += prot * (ws * P["shadow_ab"][0] + wh * P["high_ab"][0]) + wm * P["mid_ab"][0]
    lab2[..., 2] += prot * (ws * P["shadow_ab"][1] + wh * P["high_ab"][1]) + wm * P["mid_ab"][1]
    return _gamut_fit(lab2)


def _gamut_fit(lab):
    """Lab -> encoded RGB; out-of-gamut colours are desaturated toward the same-lightness neutral (hue/lightness kept)."""
    rgb = lab2rgb(lab, clip=False)
    bad = (rgb.min(-1) < -1e-4) | (rgb.max(-1) > 1 + 1e-4)
    if bad.any():
        lo, hi = np.zeros(lab.shape[:-1]), np.ones(lab.shape[:-1])
        lb = lab[bad]
        l0, hi_, lo_ = lb[:, 0], np.ones(len(lb)), np.zeros(len(lb))
        for _ in range(14):
            mid = (hi_ + lo_) / 2
            t = np.stack([l0, lb[:, 1] * mid, lb[:, 2] * mid], -1)
            ok = (lab2rgb(t, clip=False).min(-1) >= -1e-4) & (lab2rgb(t, clip=False).max(-1) <= 1 + 1e-4)
            lo_ = np.where(ok, mid, lo_); hi_ = np.where(ok, hi_, mid)
        rgb[bad] = lab2rgb(np.stack([l0, lb[:, 1] * lo_, lb[:, 2] * lo_], -1), clip=False)
    return np.clip(rgb, 0, 1)


def build_lut(n=33, P=PARAMS):
    """(n,n,n,3) with index [b][g][r] -> output RGB (the .cube order: red varies fastest)."""
    g = np.linspace(0, 1, n)
    B, G, R = np.meshgrid(g, g, g, indexing="ij")
    return ember_look(np.stack([R, G, B], -1).reshape(-1, 3), P).reshape(n, n, n, 3)


def write_cube(path=LUT_PATH, n=33, P=PARAMS):
    lut = build_lut(n, P)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('TITLE "%s"\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\nLUT_3D_SIZE %d\n' % (LUT_NAME, n))
        for row in lut.reshape(-1, 3):
            f.write("%.6f %.6f %.6f\n" % tuple(row))
    return path


def apply_lut(img, lut):
    """Trilinear application of a (n,n,n,3)[b][g][r] LUT to a uint8/float RGB image (numpy mirror of ffmpeg's lut3d)."""
    n = lut.shape[0]
    x = (img.astype(np.float64) / (255.0 if img.dtype == np.uint8 else 1.0)) * (n - 1)
    i0 = np.clip(np.floor(x).astype(int), 0, n - 2)
    f = x - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    out = 0
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = (f[..., 0] if dr else 1 - f[..., 0]) * (f[..., 1] if dg else 1 - f[..., 1]) * (f[..., 2] if db else 1 - f[..., 2])
                out = out + lut[b0 + db, g0 + dg, r0 + dr] * w[..., None]
    return out


def configure(lut_dir=None, name="ember"):
    """Point the LUT files at `lut_dir` (created if missing) and name them <name>.cube / <name>_food.cube.
    Pass a different name per parameter set so a changed look never reuses a stale file."""
    global LUT_PATH, LUT_FOOD_PATH, LUT_NAME
    d = Path(lut_dir) if lut_dir else DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    LUT_NAME, LUT_PATH, LUT_FOOD_PATH = name, d / f"{name}.cube", d / f"{name}_food.cube"
    _LUT.clear()


# ============================================================================ shot analysis
AN_W, AN_H = 540, 960          # analysis frame size (vertical output geometry)
_STATS = {}
_LUT = {}


def _norm_shot(s):
    if isinstance(s, dict):
        return s["path"], s.get("opts", []), s.get("crop"), s["t0"], s["t1"]
    return tuple(s)


def decode_frames(path, opts, crop, t0, t1, n=6, w=AN_W, h=AN_H):
    """n frames spread over [t0, t1) through crop + scale (same geometry as the engine), RGB uint8 (n,h,w,3)."""
    d = max(t1 - t0, 0.1)
    vf = ",".join(x for x in [f"fps={n / d:.5f}", crop, f"scale={w}:{h}:flags=area", "format=rgb24"] if x)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", f"{t0:.3f}", "-t", f"{d:.3f}", "-i", str(path), "-vf", vf,
                                   "-frames:v", str(n), "-f", "rawvideo", "-"])
    a = np.frombuffer(raw, np.uint8)
    k = a.size // (w * h * 3)
    assert k >= 1, f"no frames decoded from {path} {t0}-{t1}"
    return a[:k * w * h * 3].reshape(k, h, w, 3)


def noise_sigma(frames, shadow=(0.03, 0.30)):
    """Luma noise in flat shadow regions, in 8-bit levels of the given frames (Immerkaer 3x3 operator, clipped-RMS: the
    operator's response to white noise has std 6*sigma; edges are excluded by a gradient mask and by clipping at 3 s0)."""
    k = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    vals = []
    for f in frames:
        y = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32)
        r = np.abs(cv2.filter2D(y, -1, k))
        yb = cv2.GaussianBlur(y, (0, 0), 1.5)
        flat = np.hypot(cv2.Sobel(yb, cv2.CV_32F, 1, 0), cv2.Sobel(yb, cv2.CV_32F, 0, 1)) < 6.0
        m = (y > shadow[0] * 255) & (y < shadow[1] * 255) & flat
        if m.sum() > 2000:
            v = r[m]
            s0 = max(np.median(v) / 0.6745, 1.0)
            vals.append(math.sqrt(np.mean(np.minimum(v, 3 * s0) ** 2) / 0.97) / 6)
    return float(np.median(vals)) if vals else float("nan")


def face_skin(frames, min_frac=0.10):
    """Skin pixels inside validated Haar faces -> (rgb float pixels (n,3), mean face-area fraction) or (None, 0)."""
    px, area = [], 0.0
    for f in frames:
        for (x, y, w, h) in FC.detect(f, width=f.shape[1], min_frac=min_frac, skin_min=0.5):
            sl = (slice(y + int(h * .3), y + int(h * .8)), slice(x + int(w * .2), x + int(w * .8)))
            reg = f[sl]
            m = FC.skin_mask(reg)
            if m.mean() > .3:
                px.append(reg[m][::3] / 255.0); area += w * h / (f.shape[0] * f.shape[1])
    if not px:
        return None, 0.0
    return np.concatenate(px), area / len(frames)


def shot_stats(frames, hi=None):
    """Look statistics of a shot from its sample frames (uint8 RGB, 540x960). `hi`: 1-2 frames at 1080x1920 for the noise probe."""
    small = np.stack([cv2.resize(f, (180, 320), interpolation=cv2.INTER_AREA) for f in frames]).reshape(-1, 3) / 255.0
    mx = small.max(1)
    keep = (mx > 0.04) & (mx < 0.97)
    lab = rgb2lab(small)
    Lall = lab[:, 0]
    C = np.hypot(lab[:, 1], lab[:, 2])
    st = dict(L=[float(np.percentile(Lall, p)) for p in (1, 5, 25, 50, 75, 95, 99)],
              mean_lab=[float(v) for v in lab.mean(0)],
              clip=float((mx >= 0.985).mean()), crush=float((luma(small) < 4 / 255).mean()))
    # near-neutral pixels (white-ish surfaces, tableware, lamp shades): their Lab (a,b) is the illuminant cast
    neu = keep & (C < 18) & (Lall > 28) & (Lall < 92)
    w = np.exp(-(C[neu] / 10.0) ** 2) * (Lall[neu] / 100)
    st["nn"] = float(neu.mean())
    st["cast"] = [float((lab[neu, 1] * w).sum() / w.sum()), float((lab[neu, 2] * w).sum() / w.sum())] if neu.sum() > 300 else [0.0, 0.0]
    st["conf"] = float(np.clip((neu.mean() - 0.02) / 0.10, 0, 1))
    sk, area = face_skin(frames)
    st["skin"] = None
    if sk is not None and len(sk) > 600 and area > 0.02:
        m = np.median(rgb2lab(sk), 0)
        h = math.degrees(math.atan2(m[2], m[1])) % 360
        if 15 <= math.hypot(m[1], m[2]) <= 48 and 25 <= h <= 80:      # a plausible skin colour, not a lookalike
            st["skin"] = dict(L=float(m[0]), a=float(m[1]), b=float(m[2]), area=float(area), n=int(len(sk)))
    st["noise"] = noise_sigma(hi if hi is not None else frames)
    st["_px"] = small[::3].astype(np.float32)                                  # subsample for the exposure fit (not JSON)
    st["_skin_px"] = sk[::max(1, len(sk) // 3000)].astype(np.float32) if st["skin"] else None
    return st


def stats_for(shot, n=6):
    path, opts, crop, t0, t1 = _norm_shot(shot)
    key = (str(path), tuple(opts), crop, round(t0, 3), round(t1, 3), n)
    if key not in _STATS:
        fr = decode_frames(path, opts, crop, t0, t1, n)
        hi = decode_frames(path, opts, crop, t0 + 0.3 * (t1 - t0), t1, 2, 1080, 1920)
        _STATS[key] = shot_stats(fr, hi)
    return _STATS[key]


# ============================================================================ reel target + per-shot correction
IDEAL_L50, IDEAL_SKIN_L = 30.0, 52.0     # low-key evening brief: mid-grey L* ~30-36 (readable, still moody), faces ~L* 52


def _lut(food=False):
    k = "food" if food else "lut"
    if k not in _LUT:
        path, P = (LUT_FOOD_PATH, FOOD_PARAMS) if food else (LUT_PATH, PARAMS)
        if not path.exists():
            write_cube(path, 33, P)
        _LUT[k] = build_lut(33, P)
    return _LUT[k]


def load_cache(path):
    """Optional: reuse shot statistics between engine runs (a pickle you wrote yourself; never load one you did not)."""
    import pickle
    if Path(path).exists():
        _STATS.update(pickle.load(open(path, "rb")))


def save_cache(path):
    import pickle
    pickle.dump(_STATS, open(path, "wb"))


def reel_target(shots, ideal_L50=IDEAL_L50, ideal_skin_L=IDEAL_SKIN_L, pull=0.5):
    """Look target of one reel from its shots [(path, opts, crop, t0, t1), ...] (or dicts with those keys).
    L50 / p5 / p95 = median over the best-exposed half of the shots, pulled `pull` of the way to the brief's ideal
    mid-grey; cast = confidence-weighted median white-balance cast; skin_L = ideal skin lightness for face shots."""
    sts = [stats_for(s) for s in shots]
    score = [abs(s["L"][3] - ideal_L50) + 400 * max(s["clip"] - 0.01, 0) + 100 * s["crush"] for s in sts]
    best = [sts[i] for i in np.argsort(score)[:max(1, (len(sts) + 1) // 2)]]
    med = lambda k: float(np.median([b["L"][k] for b in best]))
    w = np.array([s["conf"] for s in sts]) + 1e-3
    cast = [float(np.average([s["cast"][j] for s in sts], weights=w)) for j in (0, 1)]
    return dict(L50=(1 - pull) * med(3) + pull * ideal_L50, L5=med(1), L95=med(5), cast=cast, skin_L=ideal_skin_L,
                n=len(sts), best_L50=med(3))


def _wb_gains(da, db, L=60.0):
    """Encoded-domain per-channel gains (max = 1, so highlights never clip) that move a mid grey's Lab (a,b) by (da,db)."""
    c0 = lab2rgb(np.array([L, 0.0, 0.0]), clip=False)
    c1 = lab2rgb(np.array([L, da, db]), clip=False)
    g = c1 / c0                                    # encoded gains turning the grey into the target colour
    g = np.clip(g, 0.7, 1.45)
    return g / g.max()


def _l2v(L):
    """Neutral grey of lightness L* -> encoded value (sRGB OETF of Y)."""
    L = np.asarray(L, np.float64)
    Y = np.where(L > 8, ((L + 16) / 116) ** 3, L / 903.3)
    return l2s(Y)


def _v2l(v):
    Y = s2l(np.asarray(v, np.float64))
    return np.where(Y > 216 / 24389, 116 * np.cbrt(Y) - 16, Y * 903.3)


_XS = np.array([0, .02, .04, .07, .10, .14, .19, .25, .32, .40, .50, .60, .70, .80, .88, .94, 1.0])   # points handed to ffmpeg `curves`


def _pre_lut_L(Lpost):
    """L* wanted AFTER the LUT -> L* needed BEFORE it, inverting the LUT's own tone curve on the neutral axis."""
    tx, ty = np.array(PARAMS["tone_x"]), np.array(PARAMS["tone_y"])
    v_post = _l2v(Lpost)
    return _v2l(np.interp(v_post, ty, tx))


def tone_anchors(P, T50, tg, max_lift, max_cut, hl_cut=0.0):
    """Percentile matching: shot L* percentiles P=[p1,p5,p25,p50,p75,p95,p99] -> target L* (after the LUT).
    Black end deep-but-not-crushed (p1 -> 2.5, p5 -> <= 8.5), median -> T50, highlight end follows the median lift at 40 %
    and the reel's p95 at 35 %, every segment slope kept in [0.5, 2.2] (no flat regions, no noise-amplifying cliffs)."""
    p1, p5, p50, p95, p99 = P[0], P[1], P[3], P[5], P[6]
    d = T50 - p50
    t5 = min(p5, 8.5) if p5 <= 8.5 else 8.5 + 0.35 * (p5 - 8.5)
    t1 = min(p1, 2.5)
    t95 = float(np.clip(0.65 * (p95 + 0.4 * d) + 0.35 * tg["L95"], p95 - 8, 84)) - hl_cut
    t99 = float(np.clip(p99 + 0.25 * d, p99 - 6, 94)) - hl_cut
    src = np.array([0.0, p1, p5, p50, p95, p99, 100.0])
    dst = np.array([0.0, t1, t5, T50, t95, t99, 100.0])
    keep = [0]
    for i in range(1, len(src)):          # drop anchors closer than 0.7 L* to the previous one (duplicate percentiles)
        if src[i] - src[keep[-1]] >= 0.7:
            keep.append(i)
    src, dst = src[keep], dst[keep]
    mi = int(np.argmin(np.abs(src - p50)))
    for i in range(mi + 1, len(src)):     # enforce slopes outward from the median
        ds = src[i] - src[i - 1]
        dst[i] = np.clip(dst[i], dst[i - 1] + 0.5 * ds, dst[i - 1] + 2.2 * ds)
    for i in range(mi - 1, -1, -1):
        ds = src[i + 1] - src[i]
        dst[i] = np.clip(dst[i], dst[i + 1] - 2.2 * ds, dst[i + 1] - 0.5 * ds)
    dst = np.clip(dst, 0, 100)
    return src, dst


def correction(st, tg, strength=0.7, max_lift=8.0, max_cut=10.0, food=False):
    """Corrective transform of one shot toward the reel target. Returns dict(gain(3), off(3), pts(3, N) curve ordinates at _XS,
    shift(2), target_L50, pred, anchors)."""
    px = st["_px"].astype(np.float64)
    skin = st["skin"]
    # ---- white balance: neutral-surface cast -> reel cast (reel cast is only 60 % trusted: keeps the warm room ambience)
    tcast = np.array(tg["cast"]) * 0.6 + (np.array([2.0, 8.0]) if food else 0.0)
    shift = strength * st["conf"] * (tcast - np.array(st["cast"]))
    shift = np.clip(shift, -9, 9)
    if skin:   # skin guard: after the shift, skin hue must stay inside the natural 42-58 deg band
        sab = np.array([skin["a"], skin["b"]]) + shift
        h = math.degrees(math.atan2(sab[1], sab[0])) % 360
        ht = min(max(h, 42.0), 58.0)
        c = float(np.hypot(*sab))
        want = c * np.array([math.cos(math.radians(ht)), math.sin(math.radians(ht))])
        shift = shift + 0.8 * (want - sab)
    shift = np.clip(shift, -10, 10)
    gain = _wb_gains(*shift)
    # ---- black point per channel: removes the phone's lifted-black veil and any shadow tint (never below 0, never above 0.10)
    p1 = np.percentile(px, 1, axis=0)
    off = np.clip(0.85 * p1, 0, 0.10)
    v = np.clip((px * gain - off) / (1 - off), 0, 1)
    # ---- exposure/contrast: L* percentile matching on the corrected signal
    Lv = rgb2lab(v)[:, 0]
    P = [float(np.percentile(Lv, q)) for q in (1, 5, 25, 50, 75, 95, 99)]
    T = tg["L50"]
    if skin:
        sk = np.clip((st["_skin_px"].astype(np.float64) * gain - off) / (1 - off), 0, 1)
        Ls = float(np.median(rgb2lab(sk)[:, 0]))
        T = 0.35 * T + 0.65 * (P[3] + (tg["skin_L"] - Ls))          # make the FACE land at skin_L
    L50o = st["L"][3]
    T = float(np.clip(T, L50o - max_cut, L50o + max_lift))
    lut = _lut(food)
    allowed = st["clip"] + 0.003                                         # highlight guard: never clip (>= 252/255) more than the source does (+0.3 %)
    for hl_cut in (0.0, 2.0, 4.0, 6.0, 8.0, 11.0):
        src, dst = tone_anchors(P, T, tg, max_lift, max_cut, hl_cut)
        f = PchipInterpolator(src, _pre_lut_L(dst), extrapolate=True)   # L*(corrected) -> L* wanted before the LUT
        xv = _l2v(np.linspace(0, 100, 401))
        g_of_v = PchipInterpolator(xv, _l2v(np.clip(f(np.linspace(0, 100, 401)), 0, 100)))   # encoded -> encoded, same curve for R, G, B
        out = apply_lut(_curve_apply(v, g_of_v), lut)
        if float((out.max(-1) >= 252 / 255).mean()) <= allowed:
            break
    pts = []
    for c in range(3):
        vin = np.clip((_XS * gain[c] - off[c]) / (1 - off[c]), 0, 1)
        pts.append(np.clip(g_of_v(vin), 0, 1))
    pts = np.array(pts)
    pred = dict(L50=float(np.median(rgb2lab(out)[:, 0])), hl_cut=hl_cut)
    return dict(gain=gain, off=off, g=g_of_v, pts=pts, shift=shift, target_L50=T, pred=pred, anchors=(src, dst), P=P)


def _curve_apply(v, g):
    return np.clip(g(np.clip(v, 0, 1)), 0, 1)


def _lut_arg(food=False):
    return str(LUT_FOOD_PATH if food else LUT_PATH).replace("\\", "/").replace(":", "\\:")


def _fmt(corr, sigma, denoise, food=False):
    pts = corr["pts"]
    cv = lambda c: " ".join(f"{x:.4f}/{y:.4f}" for x, y in zip(_XS, pts[c]))
    pre = ""
    if denoise:
        # the lift amplifies shadow noise by the curve slope near 0.1-0.2: denoise in proportion to (noise x lift)
        s = (sigma if sigma == sigma else 0.5) * max(1.0, float(corr["g"](0.15)) / 0.15)
        ls = float(np.clip(0.8 + 1.4 * s, 0.8, 2.2))
        lt = min(1.0 + 1.4 * ls, 4.0)            # temporal strength capped: talking heads move their hands
        pre = f"hqdn3d={ls:.2f}:{ls * 0.8:.2f}:{lt:.2f}:{lt:.2f}" if s > 0.3 else ""
    body = (f"format=gbrp16le,curves=interp=pchip:r='{cv(0)}':g='{cv(1)}':b='{cv(2)}',"
            f"lut3d=file='{_lut_arg(food)}':interp=tetrahedral")
    return pre, body


def shot_filter_parts(path, opts, crop, t0, t1, reel_target, grain=False, local=0.35, denoise=True, food=False, strength=0.7):
    """(pre, post): `pre` (denoise, may be '') belongs BEFORE the engine's scale (source resolution), `post` is the colour
    chain + local contrast + optional grain and replaces the engine's `color_chain(...)` (after scale)."""
    st = stats_for((path, opts, crop, t0, t1))
    co = correction(st, reel_target, strength=strength, food=food)
    _lut(food)                                         # makes sure the .cube file exists
    pre, body = _fmt(co, st["noise"], denoise, food)
    post = [body]
    if local:
        post.append(f"cas=strength={local:.2f}")
    if grain:
        post.append(f"format=rgb24,noise=alls={2 if grain is True else grain}:allf=t")
    return pre, ",".join(post)


def shot_filter(path, opts, crop, t0, t1, reel_target, **kw):
    """One filter chain (drop-in for the engine's `color_chain(gains)`, placed after `scale`). Includes the denoise."""
    pre, post = shot_filter_parts(path, opts, crop, t0, t1, reel_target, **kw)
    return f"{pre},{post}" if pre else post


def image_filter(img, reel_target, local=0.35, food=False, strength=0.7):
    """Same chain for a still (numpy RGB uint8, any size)."""
    fr = cv2.resize(img, (AN_W, AN_H), interpolation=cv2.INTER_AREA)[None]
    st = shot_stats(fr)
    co = correction(st, reel_target, strength=strength, food=food)
    _, body = _fmt(co, st["noise"], False, food)
    return body + (f",cas=strength={local:.2f}" if local else "")
