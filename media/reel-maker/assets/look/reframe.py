"""reframe.py - subject-aware landscape -> 9:16 crop paths and tight talking-head boxes.

API
    crop_path(path, opts, t0, t1, fps=60, out_w_ratio=9/16, **kw) -> [(t, x0), ...]
        x0 = left edge of the full-height 9:16 window in SOURCE pixels of the displayed (auto-rotated unless opts has
        -noautorotate) frame; t = seconds from t0 in SOURCE time, `fps` samples per second.
    crop_filter(path, opts, t0, t1, speed=1.0, **kw) -> str
        `crop=...:x='<piecewise-linear in t>':y=0` ready for the decode chain (t = OUTPUT time after setpts/speed). Static
        shots return a plain constant crop.
    tight_box(path, t0, t1, zoom=1.22) -> (x, y, w, h)
        tight framing of a VERTICAL talking head (eyes ~37 % down, >= 6 % headroom) in source pixels; w:h stays 9:16.
    plan_info(...)  -> dict with the per-frame evidence (faces/people/saliency) and the chosen path (for the harness)
"""
import math, os, subprocess, pickle, hashlib, json
from pathlib import Path
import numpy as np
import cv2

import faces as FC

HERE = Path(__file__).parent
CACHE = Path(os.environ.get("REEL_BUILD_DIR", "./build")) / "cache"  # analysis cache (pickles written by this module); the engine points it at <build>/cache
WA = 1280                      # analysis width (landscape sources are 16:9 -> 1280x720)
_HOG = None
_MEM = {}


def configure(cache_dir=None):
    """Directory for the per-shot analysis cache (created on first write)."""
    global CACHE
    CACHE = Path(cache_dir) if cache_dir else Path(os.environ.get("REEL_BUILD_DIR", "./build")) / "cache"


# ============================================================================ analysis
def _decode(path, opts, t0, t1, fps, w=WA):
    d = max(t1 - t0, 0.05)
    h = int(round(w * 9 / 16 / 2)) * 2
    vf = f"fps={fps},scale={w}:{h}:flags=area,format=rgb24"
    raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", f"{t0:.3f}", "-t", f"{d:.3f}", "-i", str(path), "-vf", vf,
                                   "-f", "rawvideo", "-"])
    a = np.frombuffer(raw, np.uint8)
    n = a.size // (w * h * 3)
    return a[:n * w * h * 3].reshape(n, h, w, 3), [t0 + i / fps for i in range(n)]


def _hog():
    global _HOG
    if _HOG is None:
        _HOG = cv2.HOGDescriptor()
        _HOG.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return _HOG


def people(rgb, up=1.5):
    """HOG pedestrian boxes (x,y,w,h) in rgb's pixels. Seated people are mostly missed (the model is trained on standing pedestrians)."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if up != 1:
        g = cv2.resize(g, None, fx=up, fy=up, interpolation=cv2.INTER_LINEAR)
    r, wts = _hog().detectMultiScale(g, winStride=(8, 8), padding=(8, 8), scale=1.06, hitThreshold=0.2)
    out = []
    for (x, y, w, h), s in zip(r, np.ravel(wts)):
        if s >= 0.6:
            out.append((int(x / up), int(y / up), int(w / up), int(h / up), float(s)))
    return out


def spectral_residual(gray, size=(128, 72)):
    g = cv2.resize(gray, size, interpolation=cv2.INTER_AREA).astype(np.float32)
    F = np.fft.fft2(g)
    L = np.log(np.abs(F) + 1e-8)
    R = L - cv2.blur(L, (3, 3))
    S = np.abs(np.fft.ifft2(np.exp(R + 1j * np.angle(F)))) ** 2
    S = cv2.GaussianBlur(S.astype(np.float32), (0, 0), 2.0)
    return S / (S.max() + 1e-9)


def saliency_map(rgb):
    """Detail/attention map (h,w) in [0,1]: spectral residual of luma + saturation, plus gradient energy; bright specular lights are
    clipped so a string of bulbs does not outweigh people/food; the ceiling band counts less than the table band."""
    h, w = rgb.shape[:2]
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    sat = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)[..., 1]
    sr = 0.6 * spectral_residual(g) + 0.4 * spectral_residual(sat)
    sr = cv2.resize(sr, (w, h), interpolation=cv2.INTER_CUBIC)
    gm = cv2.GaussianBlur(g, (0, 0), 1.2).astype(np.float32)
    ge = np.hypot(cv2.Sobel(gm, cv2.CV_32F, 1, 0), cv2.Sobel(gm, cv2.CV_32F, 0, 1))
    ge = cv2.GaussianBlur(ge, (0, 0), 6)
    ge /= np.percentile(ge, 99) + 1e-6
    s = 0.65 * np.clip(sr / (np.percentile(sr, 98) + 1e-6), 0, 1) + 0.35 * np.clip(ge, 0, 1)
    bright = cv2.GaussianBlur((g > 245).astype(np.float32), (0, 0), 4)                # blown lights are not content
    s *= (1 - 0.7 * np.clip(bright * 3, 0, 1))
    y = np.linspace(0, 1, h)[:, None]
    s *= 0.35 + 0.65 * np.exp(-((y - 0.62) / 0.30) ** 2)
    return s


def analyze(path, opts, t0, t1, fps=5, use_hog=True):
    """Per analysis frame: faces, people boxes, skin and saliency column profiles (all in WA x WA*9/16 pixels)."""
    key = hashlib.md5(f"{path}|{opts}|{t0:.3f}|{t1:.3f}|{fps}|{use_hog}|v3".encode()).hexdigest()[:16]
    if key in _MEM:
        return _MEM[key]
    pk = CACHE / f"rf_{key}.pkl"
    if pk.exists():
        _MEM[key] = pickle.load(open(pk, "rb"))
        return _MEM[key]
    frames, times = _decode(path, opts, t0, t1, fps)
    h, w = frames.shape[1:3]
    out = dict(times=times, W=w, H=h, faces=[], people=[], sal=[], skin=[])
    for f in frames:
        out["faces"].append(FC.detect(f, width=w, min_frac=0.016, profile=True, skin_min=0.40))
        out["people"].append(people(f) if use_hog else [])
        out["sal"].append(saliency_map(f).mean(0).astype(np.float32))
        sk = FC.skin_mask(f).astype(np.float32)
        sk = cv2.morphologyEx(sk, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        out["skin"].append(sk.mean(0).astype(np.float32))
    CACHE.mkdir(parents=True, exist_ok=True)
    pickle.dump(out, open(pk, "wb"))
    _MEM[key] = out
    return out


# ============================================================================ window scoring + path planning
def _face_mass(faces, W):
    """Interest mass of each face: grows with size (a big talking head outweighs a table of tiny background people); a clearly dominant face is boosted."""
    if not faces:
        return []
    m = [0.25 + 5.0 * f[2] / W for f in faces]
    areas = sorted((f[2] * f[3] for f in faces), reverse=True)
    if len(areas) > 1 and areas[0] > 1.8 * areas[1]:
        j = int(np.argmax([f[2] * f[3] for f in faces])); m[j] *= 1.8
    return m


def _profile(an, i, W):
    """Column interest profile of analysis frame i (saliency part has mass ~1; faces/people/skin add mass)."""
    s = an["sal"][i].astype(np.float64)
    s = cv2.GaussianBlur(s[None, :], (0, 0), W * 0.012)[0]
    prof = s / (s.sum() + 1e-9)
    sk = an["skin"][i].astype(np.float64)
    prof = prof + 0.5 * sk / (sk.sum() + 1e-9) * min(1.0, sk.sum() / (0.02 * W))      # skin mass only when there is a real amount
    xs = np.arange(W)
    for (x, y, bw, bh, sc) in an["people"][i]:
        sg = bw * 0.5 + 1
        prof += 0.8 * np.exp(-0.5 * ((xs - (x + bw / 2)) / sg) ** 2) / (sg * 2.5066)
    for (x, y, bw, bh), m in zip(an["faces"][i], _face_mass(an["faces"][i], W)):
        sg = bw * 0.9 + 1
        prof += m * np.exp(-0.5 * ((xs - (x + bw / 2)) / sg) ** 2) / (sg * 2.5066)
    return prof


def _window_scores(an, i, win, pos, side_margin=0.06, kappa=0.30, cut_k=1.5):
    """Score of every candidate window left edge `pos` (array) for analysis frame i."""
    W = an["W"]
    prof = _profile(an, i, W)
    cs = np.concatenate([[0], np.cumsum(prof)])
    pos = np.asarray(pos)
    E = cs[np.minimum(pos + win, W)] - cs[pos]
    faces = an["faces"][i]
    pen = np.zeros(len(pos))
    bonus = np.zeros(len(pos))
    m = side_margin * win
    for (x, y, bw, bh), fm in zip(faces, _face_mass(faces, W)):     # never cut a head: partial overlap with the safe window is penalised
        lo, hi = pos + m, pos + win - m
        inside = np.clip(np.minimum(x + bw, hi) - np.maximum(x, lo), 0, bw) / bw
        cut = (inside > 0.05) & (inside < 0.97)
        pen += cut * fm * (0.6 + 0.4 * (1 - inside))
    # composition: dominant subject (largest face, else people/skin mass centroid) on a third / the centre line
    cx = None
    if faces:
        f = max(faces, key=lambda b: b[2] * b[3]); cx = f[0] + f[2] / 2
        thirds = (0.5, 0.5)                                         # a single big face sits best centred
    else:
        pp = an["people"][i]
        if pp:
            b = max(pp, key=lambda b: b[2] * b[3]); cx = b[0] + b[2] / 2
        else:
            idx = np.argsort(prof)[-max(3, W // 40):]; cx = float(np.average(idx, weights=prof[idx]))
        thirds = (1 / 3, 0.5, 2 / 3)
    if cx is not None:
        rel = (cx - pos) / win
        d = np.min([np.abs(rel - t) for t in thirds], axis=0)
        bonus += 0.06 * np.exp(-(d / 0.12) ** 2)
        bonus -= 0.20 * np.clip(np.abs(rel - 0.5) - 0.36, 0, 1)      # subject well inside the frame
    bonus -= kappa * np.abs(pos - (W - win) / 2) / win             # centre prior: leave the operator's framing unless there is a gain
    return E - cut_k * pen + bonus


def plan_info(path, opts, t0, t1, out_w_ratio=9 / 16, fps_a=5, lam=0.6, vmax=0.40, static_frac=0.10, use_hog=True,
              safe_margin=0.08, kappa=0.30):
    """Plan the crop window for a shot; returns dict(an, win (analysis px), pos (analysis px per frame), path60 ...)."""
    an = analyze(path, opts, t0, t1, fps_a, use_hog)
    W, H = an["W"], an["H"]
    win = int(round(H * out_w_ratio))
    step = 4
    pos = np.arange(0, W - win + 1, step)
    n = len(an["times"])
    L = np.stack([_window_scores(an, i, win, pos, safe_margin, kappa) for i in range(n)])         # (n, K)
    # dynamic programming: maximise sum score - lam * |dx|/win
    K = len(pos)
    D = np.abs(pos[:, None] - pos[None, :]) / win
    maxstep = 1.1 * vmax * win / fps_a                                  # hard speed limit between analysis samples: no jumps between subjects
    cost = lam * D + np.where(np.abs(pos[:, None] - pos[None, :]) > maxstep, 1e6, 0.0)
    acc = L[0].copy(); back = np.zeros((n, K), int)
    for i in range(1, n):
        tot = acc[None, :] - cost                                      # [to, from]
        back[i] = np.argmax(tot, axis=1)
        acc = L[i] + tot[np.arange(K), back[i]]
    k = int(np.argmax(acc)); idx = [k]
    for i in range(n - 1, 0, -1):
        k = back[i][k]; idx.append(k)
    raw = pos[idx[::-1]].astype(float)
    return dict(an=an, win=win, pos=pos, L=L, raw=raw, W=W, H=H, params=dict(vmax=vmax, static_frac=static_frac))


def _crit_damped(target, dt, omega):
    """Critically damped follower x'' = w^2 (target - x) - 2 w x'  (semi-implicit Euler, sub-stepped)."""
    x, v = float(target[0]), 0.0
    out = np.empty(len(target))
    sub = 4
    h = dt / sub
    for i, tg in enumerate(target):
        for _ in range(sub):
            a = omega * omega * (tg - x) - 2 * omega * v
            v += a * h; x += v * h
        out[i] = x
    return out


def smooth_path(raw, times, win, fps=60, omega=7.0, vmax=0.55, static_frac=0.10, W=None):
    """raw: per-analysis-frame window positions. -> dense (t, x) at `fps`: linear resample, zero-lag critically damped smoothing
    (forward + backward pass), speed limit vmax (window widths / s), static crop when the path hardly moves."""
    t = np.asarray(times) - times[0]
    T = max(t[-1], 1.0 / fps)
    tt = np.arange(0, T + 0.5 / fps, 1.0 / fps)
    if np.ptp(raw) < static_frac * win or len(raw) < 2:
        return tt, np.full(len(tt), float(np.median(raw)))
    tgt = np.interp(tt, t, raw)
    pad = int(fps * 0.5)                                                   # hold the ends so the smoother starts at rest
    tg = np.concatenate([np.full(pad, tgt[0]), tgt, np.full(pad, tgt[-1])])
    f = _crit_damped(tg, 1 / fps, omega)
    b = _crit_damped(f[::-1], 1 / fps, omega)[::-1]
    x = b[pad:pad + len(tt)]
    dv = vmax * win / fps                                                  # max displacement per frame
    for _ in range(3):                                                     # forward/backward speed clamp
        for i in range(1, len(x)):
            x[i] = x[i - 1] + np.clip(x[i] - x[i - 1], -dv, dv)
        for i in range(len(x) - 2, -1, -1):
            x[i] = x[i + 1] + np.clip(x[i] - x[i + 1], -dv, dv)
    return tt, x


def _src_dims(path, opts):
    """(width, height) of the frame ffmpeg delivers: stored size, swapped for +-90 deg rotation unless -noautorotate."""
    st = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                             "stream=width,height:stream_side_data=rotation", "-of", "json", str(path)]))["streams"][0]
    w, h = st["width"], st["height"]
    rot = next((int(d["rotation"]) for d in st.get("side_data_list", []) if "rotation" in d), 0)
    if abs(rot) in (90, 270) and "-noautorotate" not in opts:
        w, h = h, w
    return w, h


def crop_path(path, opts, t0, t1, fps=60, out_w_ratio=9 / 16, **kw):
    """-> [(t, x0)] with t seconds from t0 (source time) and x0 in source pixels of the (displayed) frame."""
    info = plan_info(path, opts, t0, t1, out_w_ratio, **{k: v for k, v in kw.items() if k in ("fps_a", "lam", "vmax", "static_frac", "use_hog", "safe_margin", "kappa")})
    sw, sh = _src_dims(path, opts)
    k = sw / info["W"]
    P = info["params"]
    tt, x = smooth_path(info["raw"], info["an"]["times"], info["win"], fps, kw.get("omega", 7.0), P["vmax"], P["static_frac"], info["W"])
    wsrc = sh * out_w_ratio
    xs = np.clip(x * k, 0, sw - wsrc)
    return [(float(a), float(b)) for a, b in zip(tt, xs)]


def crop_filter(path, opts, t0, t1, speed=1.0, out_w_ratio=9 / 16, knots_per_s=4.0, **kw):
    """Drop-in for the engine's `crop=ih*9/16:ih`: x follows the planned path. Placed right after setpts/fps (t = output time)."""
    pts = crop_path(path, opts, t0, t1, 60, out_w_ratio, **kw)
    t = np.array([p[0] for p in pts]) / speed
    x = np.array([p[1] for p in pts])
    base = "crop=ih*9/16:ih"
    if np.ptp(x) < 1.0:
        return f"{base}:{int(round(x.mean()))}:0"
    nk = max(2, int(math.ceil(t[-1] * knots_per_s)) + 1)
    kt = np.linspace(0, t[-1], nk)
    kx = np.interp(kt, t, x)
    terms = "".join(f"+{(kx[i + 1] - kx[i]) / (kt[i + 1] - kt[i]):.3f}*clip(t-{kt[i]:.3f},0,{kt[i + 1] - kt[i]:.3f})" for i in range(nk - 1))
    return f"{base}:x='{kx[0]:.2f}{terms}':y=0"


def stats_crop(path, opts, t0, t1, **kw):
    """Static `crop=...` string at the time-mean planned x: hand it to grade_v4 as the shot's crop so its colour statistics describe
    the window that is actually shown (instead of the centre crop)."""
    xs = [p[1] for p in crop_path(path, opts, t0, t1, 10, **kw)]
    return f"crop=ih*9/16:ih:{int(round(float(np.mean(xs))))}:0"


# ============================================================================ vertical talking heads
_EYE = None


def _eyes(gray, box):
    global _EYE
    if _EYE is None:
        _EYE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")
    x, y, w, h = box
    roi = gray[y:y + int(h * 0.62), x:x + w]
    es = _EYE.detectMultiScale(roi, 1.1, 4, minSize=(max(8, w // 10), max(8, w // 10)))
    es = [e for e in es if e[1] + e[3] / 2 < h * 0.5]
    if len(es) >= 2:
        es = sorted(es, key=lambda e: -e[2] * e[3])[:2]
        return float(np.mean([y + e[1] + e[3] / 2 for e in es]))
    return None


def face_track(path, opts, t0, t1, fps=3, width=540):
    """Largest validated face per sampled frame of a vertical clip: list of (t, (x,y,w,h), eye_y or None) in analysis pixels + frame size."""
    d = max(t1 - t0, 0.1)
    h = int(round(width * 16 / 9 / 2)) * 2
    raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", f"{t0:.3f}", "-t", f"{d:.3f}", "-i", str(path), "-vf",
                                   f"fps={fps},scale={width}:{h}:flags=area,format=rgb24", "-f", "rawvideo", "-"])
    fr = np.frombuffer(raw, np.uint8)
    n = fr.size // (width * h * 3)
    fr = fr[:n * width * h * 3].reshape(n, h, width, 3)
    out = []
    for i, f in enumerate(fr):
        fs = FC.detect(f, width=width, min_frac=0.12, profile=False, skin_min=0.4)
        if fs:
            b = max(fs, key=lambda b: b[2] * b[3])
            out.append((t0 + i / fps, b, _eyes(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), b)))
    return out, width, h


def tight_box(path, t0, t1, zoom=1.22, opts=(), eye_at=0.37, min_headroom=0.06):
    """Tight 9:16 box (x, y, w, h) in source pixels of a vertical talking head over [t0, t1]: size = frame/zoom (zoom limited by
    the engine's upscale tolerance), eyes on the `eye_at` line, hair-top headroom >= min_headroom, face centred; clamped to the frame."""
    opts = list(opts)
    sw, sh = _src_dims(path, opts)
    tr, aw, ah = face_track(path, opts, t0, t1)
    if not tr:
        w = sw / zoom; h = sh / zoom
        return (int(round((sw - w) / 2)), 0, int(round(w)), int(round(h)))
    k = sh / ah
    fx = np.median([(b[0] + b[2] / 2) for _, b, _ in tr]) * k
    fh = np.median([b[3] for _, b, _ in tr]) * k
    fy = np.median([b[1] for _, b, _ in tr]) * k
    eyes = [e for _, _, e in tr if e is not None]
    eye_y = (np.median(eyes) * k) if eyes else fy + 0.40 * fh
    head_top = fy - 0.28 * fh                                           # Haar box starts at the brow: hair/forehead above it
    h = sh / zoom
    w = h * 9 / 16
    y0 = eye_y - eye_at * h
    if head_top - y0 < min_headroom * h:                                # more headroom if the eye rule would leave less than 6 %
        y0 = head_top - min_headroom * h
    y0 = float(np.clip(y0, 0, sh - h))
    x0 = float(np.clip(fx - w / 2, 0, sw - w))
    return (int(round(x0)), int(round(y0)), int(round(w)), int(round(h)))
