"""Haar face detection with skin validation (shared by grade.py and reframe.py).
Boxes are (x, y, w, h) in the image's own pixels. Needs opencv-python < 5 (OpenCV 5 dropped CascadeClassifier)."""
import cv2, numpy as np

_C = {}


def _casc(name):
    if name not in _C:
        _C[name] = cv2.CascadeClassifier(cv2.data.haarcascades + f"haarcascade_{name}.xml")
    return _C[name]


def skin_mask(rgb):
    """Permissive skin-colour mask (YCrCb box, widened for warm/neon light) -> bool (h,w)."""
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    cr, cb, y = ycc[..., 1], ycc[..., 2], ycc[..., 0]
    return (cr >= 133) & (cr <= 178) & (cb >= 72) & (cb <= 130) & (y > 30)


def _iou(a, b):
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    i = ix * iy
    return i / (aw * ah + bw * bh - i + 1e-9)


def detect(rgb, width=540, min_frac=0.035, profile=False, skin_min=0.40):
    """Validated faces: alt2 or default cascade hit whose box holds enough skin-like pixels. Works on a downscaled copy
    (analysis width `width`), returns boxes in the ORIGINAL pixel grid, sorted by area. min_frac = min face width / image width."""
    h0, w0 = rgb.shape[:2]
    k = width / w0
    small = cv2.resize(rgb, (width, round(h0 * k)), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    k = small.shape[1] / w0
    g = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY))
    ms = max(16, int(min_frac * small.shape[1]))
    cand = []
    for name, nb in (("frontalface_alt2", 4), ("frontalface_default", 6)):
        for b in _casc(name).detectMultiScale(g, 1.1, nb, minSize=(ms, ms)):
            cand.append((tuple(int(v) for v in b), name))
    if profile:
        for b in _casc("profileface").detectMultiScale(g, 1.1, 5, minSize=(ms, ms)):
            cand.append((tuple(int(v) for v in b), "profileface"))
    sk = skin_mask(small)
    out = []
    for b, name in sorted(cand, key=lambda c: -c[0][2] * c[0][3]):
        x, y, w, h = b
        if any(_iou(b, o) > 0.35 for o in out):
            continue
        cx0, cx1, cy0, cy1 = x + int(w * .2), x + int(w * .8), y + int(h * .25), y + int(h * .85)
        frac = sk[cy0:cy1, cx0:cx1].mean() if cx1 > cx0 and cy1 > cy0 else 0
        if frac >= skin_min:
            out.append(b)
    return [tuple(int(round(v / k)) for v in b) for b in out]
