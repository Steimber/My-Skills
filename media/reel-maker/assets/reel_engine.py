"""Beat-synced branded 4K vertical reel compositor (engine v4): punch-ins, whip pans, flashes, zoom-through, shake,
embers/sparks, letter-in titles, word-timed subtitles, multi-piece voice tracks with B-roll inserts and a cold-open voice
hook, an instrumental bed under speech, per-shot LUT grading and subject-aware 9:16 crops. All project data lives in a
config module (see project_example.py); nothing about a client is hard-coded here.

Usage (paths default to the current directory layout; override with flags or REEL_* env vars):
    python reel_engine.py --config my_project.py --preview [reel names...]   # 540x960 -> <build>/preview/<name>.mp4
    python reel_engine.py --config my_project.py [reel names...]             # 2160x3840 finals -> <out>/<name>.mp4
    python reel_engine.py --config my_project.py --table                     # source-range table + overlap check across reels
    python reel_engine.py --config my_project.py --notext --preview          # caption-free renders (<build>/notext) for repeat checks

Needs <build>/songs.json (tools/analyze_songs.py) and, for `end_card(...)` without a length, <build>/phrases.json
(tools/phrases.py). Voice stems come from voice/ (or any isolated-voice wav), instrumental beds from tools/make_bed.py.
Other scripts reuse this module: `import reel_engine as E; reels = E.init(config=..., build_dir=..., videos=..., music=...)`.
"""
import argparse, bisect, hashlib, importlib.util, json, math, os, re, subprocess, sys, time
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
# Directories: replaced by init() / main().
BUILD, VID, MUSIC, ASSETS, OUT = Path("build"), Path("clips"), Path("music"), Path("assets"), Path("out")
FPS = 60
# Palette: text color, accent (keywords), ember/fire color, background. Overridden by PALETTE in the config.
TEXT, ACCENT, FIRE, BG = (251, 245, 231), (255, 176, 102), (244, 108, 39), (12, 14, 18)
FONT_DISPLAY = FONT_KICKER = FONT_BODY = None  # set from FONTS in the config
SONGS, PHRASES = {}, {}  # beat grids from <build>/songs.json, phrase/bar boundaries from <build>/phrases.json
W = H = S = 0  # set by configure()
OVERWRITE = False
NOTEXT = False  # review aid: render without captions / subtitles (visual repeat checks)


def configure(preview):
    global W, H, S
    S = 0.25 if preview else 1.0
    W, H = round(2160 * S), round(3840 * S)


# ----------------------------------------------------------------------------- project settings (overridable in the config)
# Per-project data, filled by load_config():
CLIPS = {}            # name -> (file in --videos, ffmpeg input opts, ffmpeg crop filter or None, allowed source windows)
FOOD_CLIPS = set()    # clips that get the extra appetizing warmth
AMBIENCE_CLIP = None  # CLIPS key whose real sound is the ambience bed when cfg["sfx"] is on
UPSCALED = set()      # clips upscaled > 2.5x (e.g. Full-HD sources at 4K): luma-only unsharp after the scale
HERO = None           # hero/logo video on black, resolved against --assets
LOGO = (800, 1640, 130, 1190)  # stable logo content bbox (x0, x1, y0, y1) in the 2560x1440 hero source
LOGO_W, GROUP_CY, GROUP_BOTTOM = 0.72, 0.375, 0.70  # logo width / frame width; group centre; text must end above 70 % (platform UI)
END_TITLE = ""        # end-card title (markup allowed); empty = skipped
END_GAP = 0.035       # space between the logo and the end-card title (fraction of H)
END_LINES = []        # call-to-action lines under the title: dict(text, cap=0.032, strong=False, gap=0.012, spacing=0.04)
END_MIN_CAP = 0.029   # CTA lines must stay >= 3 % of the frame height (legibility); 0 disables the check
ACCENT_WORDS = set()  # subtitle words (lower case) rendered in the accent color
FUNC_WORDS = {"the", "a", "an", "of", "to", "and", "in", "on", "at", "for", "is", "it", "that", "with", "my", "our", "i"}  # never end a chunk
SUB_PX = 210          # subtitle size at 4K
BEAT_LAG = 0.020      # cuts land this much BEFORE the json beat (measured perceptual lag of a librosa grid)
GRADE = "lut"         # "lut": v4 per-shot LUT grade (look/grade.py), "legacy": gains + ffmpeg LOOK chain
REFRAME = True        # subject-aware 9:16 crops / tight talking-head boxes (look/reframe.py); False = plain center crops
TIGHT = 1.22          # tight talking-head zoom
V4_PARAMS = dict(sat=1.8, luma_mix=0.4, shadow_chroma_floor=1.0, vibrance=0.25)  # tuned so non-skin chroma stays punchy
V4_FOOD = dict(mid_ab=(10.0, 28.0), sat=1.5, food=1.0, skin_on=True, skin_C0=40.0, skin_Cslope=0.8)  # skin guard stays on for food shots
SHADOW_LIFT = "eq=gamma=1.18"  # about +0.5 stop at 10 % luma, 0 and 1 stay put: dark stills without clipped lights
SHARPEN_4K = "unsharp=5:5:0.5:5:5:0"
CENTER = "crop=ih*9/16:ih"
# Audio chain (all overridable). VOICE_EQ is mono-fold safe (L=R), takes a little mud out (300 Hz) and adds presence (2.8 kHz).
# A compressor (VOICE_DYN) and a treble shelf LOWERED ASR recall on separated voices (94 % -> 87 %): both off by default.
VOICE_DYN = "anull"
VOICE_EQ = "pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1,equalizer=f=300:t=q:w=1:g=-2,equalizer=f=2800:t=q:w=1:g=2.5"
FADE_OUT = 0.4                               # final music fade (the end card is cut at a phrase end)
LIMITER = "alimiter=limit=0.79:level=false"  # about -2 dBFS sample peak: true peak stays below -1 dBTP
BED_DB = -7.0                                # instrumental level under speech, relative to the song's normal level
_CONFIG_KEYS = ("CLIPS", "FOOD_CLIPS", "AMBIENCE_CLIP", "UPSCALED", "LOGO", "LOGO_W", "GROUP_CY", "GROUP_BOTTOM", "END_TITLE", "END_GAP",
                "END_LINES", "END_MIN_CAP", "ACCENT_WORDS", "FUNC_WORDS", "SUB_PX", "BEAT_LAG", "GRADE", "REFRAME", "TIGHT", "V4_PARAMS",
                "V4_FOOD", "SHADOW_LIFT", "SHARPEN_4K", "VOICE_DYN", "VOICE_EQ", "FADE_OUT", "LIMITER", "BED_DB", "LOOK", "FOOD_WARM")


# ----------------------------------------------------------------------------- helpers
def clip01(x): return min(1.0, max(0.0, x))
def ease_out(x): x = clip01(x); return 1 - (1 - x) ** 3
def ease_in(x): x = clip01(x); return x ** 3


def affine(img, z=1.0, dx=0.0, dy=0.0, border=cv2.BORDER_REFLECT101, pivot=None):
    px, py = pivot if pivot else (W / 2, H / 2)
    M = np.float32([[z, 0, px * (1 - z) + dx], [0, z, py * (1 - z) + dy]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=border)


def blit(dst, spr, x, y, a=1.0):
    """Alpha-composite a straight-alpha RGBA sprite onto an RGB frame, clipped to the frame."""
    h, w = spr.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    s = spr[y0 - y:y1 - y, x0 - x:x1 - x]
    al = s[..., 3:4].astype(np.float32) * (a / 255.0)
    reg = dst[y0:y1, x0:x1]
    reg[:] = (reg * (1 - al) + s[..., :3] * al).astype(np.uint8)


_vig = {}
def vignette():
    if (W, H) not in _vig:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / math.sqrt(2)
        v = np.clip(1 - 0.30 * r ** 2.4, 0, 1)
        _vig[(W, H)] = np.repeat((v * 255).astype(np.uint8)[..., None], 3, 2)
    return _vig[(W, H)]


def grade(img):
    """Gentle vignette only; color is graded in the ffmpeg decode chain (see LOOK / look/grade.py)."""
    return cv2.multiply(img, vignette(), scale=1 / 255)


# ----------------------------------------------------------------------------- legacy color (GRADE = "legacy")
# Warm look: gentle S curve with deep blacks, teal shadows / warm highlights, smart saturation (vibrance protects skin),
# adaptive sharpening. Override LOOK / FOOD_WARM in the config.
LOOK = ",".join([
    "curves=master='0/0 0.06/0.03 0.25/0.22 0.5/0.52 0.8/0.83 0.95/0.94 1/0.98'",  # soft highlight roll-off
    "colorbalance=rs=-0.04:bs=0.05:rm=0.03:bm=-0.02:rh=0.07:gh=0.02:bh=-0.06",
    "vibrance=intensity=0.28",
    "eq=contrast=1.04:saturation=1.05",
    "cas=strength=0.45",
])
FOOD_WARM = "colorbalance=rm=0.05:gm=0.01:bm=-0.05:rh=0.04:bh=-0.04,vibrance=intensity=0.10"  # appetizing food
_gains = {}


def match_gains(img):
    """Per-shot match: 50 % gray-world white balance + 50 % pull toward mid exposure -> RGB gains.
    img may be one frame (H,W,3) or several stacked (N,H,W,3); the highlight guard uses the brightest."""
    frames = img if img.ndim == 4 else img[None]
    f = frames.astype(np.float32) / 255
    mx = f.max(-1)
    mask = (mx < 0.95) & (mx > 0.04)  # ignore clipped lights and pure black
    m = f[mask].mean(0)
    wb = (m.mean() / m) ** 0.5
    exp = (0.36 / max(float((f[mask] * wb).mean()), 1e-3)) ** 0.5
    g = np.clip(wb * exp, 0.75, 1.45)
    hi = max(float(np.percentile((fr * g).max(2), 99.5)) for fr in f)  # guard: brightest frame must not clip
    if hi > 0.92:
        g *= max(0.92 / hi, 0.75 / g.min())
    return g


def color_chain(gains, food=False):
    r, g, b = gains
    return f"colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f},{LOOK}" + (f",{FOOD_WARM}" if food else "")


def ffgrade(img, chain):
    h, w = img.shape[:2]
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-i", "-",
                        "-vf", f"{chain},format=rgb24", "-f", "rawvideo", "-"], input=img.tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(h, w, 3).copy()


def clip_gains(key, path, opts, crop, ranges):
    """Gains measured per (reel, clip) on 3 frames (10 %, 50 %, 90 %) of EVERY range of that clip used in the reel,
    so two shots of the same clip in one reel share one grade; pans still change exposure inside a range."""
    if key not in _gains:
        vf = ",".join(x for x in [crop, "scale=540:960", "format=rgb24"] if x)
        frames = []
        for t0, t1 in ranges:
            for t in (t0 + 0.1 * (t1 - t0), (t0 + t1) / 2, t0 + 0.9 * (t1 - t0)):
                raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", f"{t:.3f}", "-i", str(path),
                                               "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"])
                frames.append(np.frombuffer(raw, np.uint8).reshape(960, 540, 3))
        _gains[key] = match_gains(np.stack(frames))
    return _gains[key]


# ----------------------------------------------------------------------------- v4 grade + reframe (look/)
_look = {}


def look_modules():
    """Import look/grade.py and look/reframe.py once; LUTs and caches live in <build> (the skill folder stays clean)."""
    if "GV" not in _look:
        lv = str(HERE / "look")
        if lv not in sys.path:
            sys.path.insert(0, lv)
        import grade as GV, reframe as RF
        GV.PARAMS.update(V4_PARAMS)
        GV.FOOD_PARAMS.update(V4_FOOD)
        tag = hashlib.md5(json.dumps([GV.PARAMS, GV.FOOD_PARAMS], sort_keys=True, default=list).encode()).hexdigest()[:8]
        GV.configure(BUILD / "look", f"ember_{tag}")  # a changed parameter set gets its own .cube, never a stale one
        RF.configure(BUILD / "cache")
        GV.load_cache(BUILD / "cache" / "grade_stats.pkl")
        _look.update(GV=GV, RF=RF)
    return _look["GV"], _look["RF"]


def tight_crop(base_crop):
    """Static tight framing for clips with a fixed crop: TIGHT x zoom about the top centre (the face stays where it was)."""
    t = TIGHT
    return ",".join(x for x in [base_crop, f"crop=iw/{t}:ih/{t}:(iw-iw/{t})/2:0"] if x)


def grade_prepare(plan_):
    """Per-shot crop chains (always) and the per-reel look target (GRADE == "lut" and at least one video shot).
    Crop rules: vertical clip (no crop) + tight -> face-based tight box; fixed crop + tight -> static tight crop; spec zoom -> bottom-anchored
    zoom; plain center crop on landscape -> subject-aware path (REFRAME) ; anything else -> the clip's own crop."""
    RF = look_modules()[1] if REFRAME else None
    items = []
    for sp, a, b in plan_:
        if sp["kind"] != "video":
            continue
        f, opts, base_crop, good = CLIPS[sp["clip"]]
        path = VID / f
        speed = sp.get("speed", 1.0)
        t0 = sp["start"]
        t1 = t0 + (b - a) / FPS * speed
        if sp.get("tight") and base_crop is None and RF:
            x, y, w, h = RF.tight_box(path, t0, t1, zoom=TIGHT, opts=opts)
            chain = stats = f"crop={w}:{h}:{x}:{y}"
        elif sp.get("tight") and (base_crop != CENTER or not RF):
            chain = stats = tight_crop(base_crop)
        elif sp.get("zoom"):
            z = sp["zoom"]
            chain = stats = f"crop=iw/{z}:ih/{z}:(iw-iw/{z})/2:ih-ih/{z}"
        elif base_crop == CENTER and RF:
            chain = RF.crop_filter(path, opts, t0, t1, speed=speed)
            stats = RF.stats_crop(path, opts, t0, t1)
        else:
            chain = stats = base_crop or ""
        sp["_chain"], sp["_stats"] = chain, (stats or None)
        items.append((str(path), opts, stats or None, t0, t1))
    if GRADE != "lut" or not items:
        return None
    return look_modules()[0].reel_target(items)


# ----------------------------------------------------------------------------- effects
def saturate(img, s):
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    return cv2.addWeighted(cv2.merge([g, g, g]), 1 - s, img, s, 0)


def flare(img, a):
    """Flash flare: brightness 1.55 / saturation 1.35 easing back to normal."""
    img = saturate(img, 1 + 0.35 * a)
    return cv2.convertScaleAbs(img, alpha=1 + 0.55 * a)


def zoom_blur(img, s0, s1, K=6):
    acc = np.zeros(img.shape, np.float32)
    for k in range(K):
        cv2.accumulate(affine(img, s0 + (s1 - s0) * k / (K - 1)), acc)
    return (acc / K).astype(np.uint8)


def whip(A, B, j, N, d):
    """Strip whip pan: A leaves / B arrives sideways, horizontal box blur proportional to speed."""
    u = (j + 0.5) / N
    P = 4 * u ** 3 if u < .5 else 1 - (2 - 2 * u) ** 3 / 2
    vel = (12 * u * u if u < .5 else 12 * (1 - u) ** 2) * W / N  # px per frame
    strip = np.concatenate([A, B] if d > 0 else [B, A], 1)
    off = int(P * W) if d > 0 else int((1 - P) * W)
    out = np.ascontiguousarray(strip[:, off:off + W])
    k = int(vel * 0.7) | 1
    return cv2.blur(out, (k, 1)) if k > 2 else out


# ----------------------------------------------------------------------------- particles
class Embers:
    """Stateless rising ember particles."""
    def __init__(self, n, seed):
        r = np.random.default_rng(seed)
        self.n = n
        self.x0, self.ph = r.random(n), r.random(n)
        self.T, self.rise = r.uniform(2.6, 5.2, n), r.uniform(0.5, 1.05, n)
        self.drift, self.wf, self.wp = r.uniform(-.15, .15, n), r.uniform(1, 2.5, n), r.uniform(0, 6.28, n)
        self.r, self.mix, self.amp = r.uniform(.0030, .0075, n) * W, r.random(n), r.uniform(.5, 1, n)

    def draw(self, ov, t):
        u = (t / self.T + self.ph) % 1.0
        xs = (self.x0 + self.drift * u) * W + np.sin(t * self.wf + self.wp) * 0.02 * W
        ys = H * (1.04 - u * self.rise)
        al = np.sin(np.pi * u) ** 1.2 * self.amp
        rs = self.r * (1 - 0.55 * u)
        for i in range(self.n):
            c = np.array(FIRE) * (1 - self.mix[i]) + np.array((255, 214, 120)) * self.mix[i]
            cv2.circle(ov, (int(xs[i]), int(ys[i])), max(1, int(rs[i])), tuple(int(v * al[i]) for v in c), -1, cv2.LINE_AA)


def composite_particles(img, ov):
    small = cv2.resize(ov, (W // 4, H // 4), interpolation=cv2.INTER_AREA)
    glow = cv2.GaussianBlur(small, (0, 0), max(1.2, 0.0037 * W))
    glow = cv2.convertScaleAbs(cv2.resize(glow, (W, H)), alpha=1.8)
    return cv2.add(cv2.add(img, ov), glow)


# ----------------------------------------------------------------------------- text
def parse_markup(text):
    """'A {B C} D' -> [(word, is_accent)]: {braces} mark accent words."""
    words, cur, acc, cur_acc = [], "", False, False
    for ch in text:
        if ch == "{": acc = True; continue
        if ch == "}": acc = False; continue
        if ch == " ":
            if cur: words.append((cur, cur_acc)); cur = ""
            continue
        if not cur: cur_acc = acc
        cur += ch
    if cur: words.append((cur, cur_acc))
    return words


def font(path, size): return ImageFont.truetype(str(path), max(4, int(round(size))))


class Caption:
    """Per-letter rise-in text with baked soft shadow, optional spark burst."""
    def __init__(self, text, fpath, size_frac, yc, t0, t_exit=1e9, color=None, accent=None, stagger=0.035,
                 spacing_em=0.0, dur=0.40, rise_em=0.28, max_w=0.88, min_frac=0.92, sparks=0, seed=0, exit_dur=0.22,
                 cap_frac=None, top=None, fill=None, word_times=None):
        """size: size_frac*W px, or cap height = cap_frac*H (max). yc centers the block, `top` pins its cap-top instead.
        fill: grow the widest line to fill*W (one line for <=10 chars, else a balanced two-line split).
        word_times: one start time per word (letters of a word follow it): the text appears with the spoken words."""
        color, accent = color or TEXT, accent or ACCENT
        self.t0, self.t_exit, self.stagger, self.dur, self.rise_em, self.exit_dur = t0, t_exit, stagger, dur, rise_em, exit_dur
        words = parse_markup(text)
        f100 = font(fpath, 100)
        ratio = -f100.getbbox("H", anchor="ls")[1] / 100
        s_max = cap_frac * H / ratio if cap_frac else size_frac * W

        def wl(ws): return (sum(f100.getlength(c) + spacing_em * 100 for c in " ".join(w for w, _ in ws)) - spacing_em * 100) * s_max / 100
        def split2():
            k = min(range(1, len(words)), key=lambda k: max(wl(words[:k]), wl(words[k:])))
            return [words[:k], words[k:]]
        limit, one = (fill or max_w) * W, wl(words)
        if fill:
            lines = [words] if len(words) < 2 or len(" ".join(w for w, _ in words)) <= 10 else split2()
            size = s_max * min(1.0 if cap_frac else 9, limit / max(wl(l) for l in lines))
        elif one <= limit:
            lines, size = [words], s_max
        elif len(words) > 1 and limit / one < min_frac:
            lines = split2()
            size = s_max * min(1.0, limit / max(wl(l) for l in lines))
        else:
            lines, size = [words], s_max * limit / one

        def wlen(f, ws, sp): return sum(f.getlength(c) + sp for c in " ".join(w for w, _ in ws)) - sp
        self.size = size
        f = font(fpath, size)
        sp = spacing_em * size
        asc, desc = f.getmetrics()
        cap = f.getbbox("H", anchor="ls")
        cap_h = -cap[1]
        pitch = cap_h * 1.30
        block = (len(lines) - 1) * pitch + cap_h
        top_base = (top + cap_h) if top is not None else yc - block / 2 + cap_h
        pad = int(0.14 * size)
        self.pad, self.cap_h = pad, cap_h
        self.letters, idx, xl, xr, gw = [], 0, W, 0, 0
        for li, ws in enumerate(lines):
            lw = wlen(f, ws, sp)
            x = (W - lw) / 2
            by = top_base + li * pitch
            xl, xr = min(xl, x), max(xr, x + lw)
            for wi, (w, acc) in enumerate(ws):
                for kk, c in enumerate(w):
                    adv = f.getlength(c)
                    delay = (word_times[gw] + kk * stagger) if word_times else (t0 + idx * stagger)
                    self.letters.append((self._sprite(f, c, accent if acc else color, size, pad, asc, desc), x, by, delay))
                    x += adv + sp
                    idx += 1
                gw += 1
                x += f.getlength(" ") + sp
        self.asc, self.n = asc, idx
        self.top, self.bottom = top_base - cap_h, top_base + (len(lines) - 1) * pitch
        self.span = (xl, xr)
        r = np.random.default_rng(seed + 7)
        self.t_first = min(l[3] for l in self.letters)
        self.t_land = max(l[3] for l in self.letters) + 0.22
        self.sparks = [(self.t_land + r.uniform(0, .18), r.uniform(xl, xr), r.uniform(self.top, self.bottom),
                        r.normal(0, .06) * W, -r.uniform(.03, .12) * H, r.uniform(.55, 1.0), r.uniform(.006, .011) * W)
                       for _ in range(sparks)]

    def shift(self, dy):
        self.letters = [(s, x, by + dy, i) for s, x, by, i in self.letters]
        self.top += dy; self.bottom += dy
        self.sparks = [(tb, x, y + dy, *r) for tb, x, y, *r in self.sparks]

    @staticmethod
    def _sprite(f, ch, col, size, pad, asc, desc):
        adv = int(math.ceil(f.getlength(ch)))
        w, h = adv + 2 * pad, asc + desc + 2 * pad
        sh = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sh).text((pad, pad + 0.035 * size), ch, font=f, fill=255)
        sh = sh.filter(ImageFilter.GaussianBlur(0.04 * size)).point(lambda v: int(v * 0.75))
        out = Image.new("RGBA", (w, h), (8, 6, 5, 0))
        out.putalpha(sh)
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(g).text((pad, pad), ch, font=f, fill=tuple(col) + (255,))
        return np.array(Image.alpha_composite(out, g))

    def draw(self, img, tl):
        if tl < self.t_first or tl > self.t_exit + self.exit_dur + 0.05:
            return
        e = clip01((tl - self.t_exit) / self.exit_dur)
        for spr, x, by, delay in self.letters:
            a = ease_out((tl - delay) / self.dur)
            alpha = a * (1 - e)
            if alpha <= 0.004:
                continue
            ty = (1 - a) * self.rise_em * self.size - e * 0.35 * self.size
            blit(img, spr, int(x - self.pad), int(by - self.pad - self.asc + ty), alpha)

    def draw_sparks(self, ov, tl):
        for tb, x, y, vx, vy, life, R in self.sparks:
            u = (tl - tb) / life
            if not 0 <= u < 1:
                continue
            r = R * (0.05 + 0.29 * u / 0.35) if u < 0.35 else R * (0.34 + 2.06 * (u - 0.35) / 0.65)
            al = 1.0 if u < 0.35 else (1 - (u - 0.35) / 0.65) ** 1.5
            col = tuple(int(v * al) for v in (255, 205, 110))
            cv2.circle(ov, (int(x + vx * (tl - tb)), int(y + vy * (tl - tb))), max(1, int(r)), col, -1, cv2.LINE_AA)


class Subs:
    """Subtitle chunks: kicker font, text color + accent keywords, thick outline, pop-in 1.15 -> 1.0.
    chunks = [(start s, end s, text[, y as a fraction of H])]; chunks wider than 0.78 W shrink (down to 0.85x) to fit."""
    POP = 1.15

    def __init__(self, chunks, src_start, yc, size_px=None):
        size0 = (size_px or SUB_PX) * S * self.POP
        self.chunks = []
        for ch_ in chunks:
            a, b, text = ch_[:3]
            ych = ch_[3] * H if len(ch_) > 3 else None  # optional per-chunk vertical position (fraction of H)
            words = parse_markup(text)
            f = font(FONT_KICKER, size0)
            tw0 = sum(f.getlength(w) for w, _ in words) + f.getlength(" ") * (len(words) - 1)
            tw0 += 2 * max(2, round(12 * S * self.POP))  # outline
            size = size0 * min(1.0, 0.78 * W * self.POP / tw0)
            assert size >= 0.85 * size0, f"subtitle '{text}' needs {size / size0:.2f}x of the nominal size: split it into shorter chunks"
            f = font(FONT_KICKER, size)
            sw, pad = max(2, int(round(12 * S * self.POP * size / size0))), int(0.25 * size)
            asc, desc = f.getmetrics()
            sp = f.getlength(" ")
            ws = [f.getlength(w) for w, _ in words]
            tw = sum(ws) + sp * (len(words) - 1)
            cw, ch = int(tw + 2 * pad), asc + desc + 2 * pad
            assert (tw + 2 * sw) / self.POP <= 0.795 * W, f"subtitle '{text}' too wide: {tw / self.POP / W:.2f}W"
            shadow = Image.new("L", (cw, ch), 0)
            sd, outl, fill = ImageDraw.Draw(shadow), Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            od, fd = ImageDraw.Draw(outl), ImageDraw.Draw(fill)
            x = pad
            for (w, acc), wl in zip(words, ws):
                sd.text((x, pad + 0.04 * size), w, font=f, fill=200, stroke_width=sw)
                od.text((x, pad), w, font=f, fill=(14, 10, 8, 255), stroke_width=sw, stroke_fill=(14, 10, 8, 255))
                fd.text((x, pad), w, font=f, fill=tuple(ACCENT if acc else TEXT) + (255,))
                x += wl + sp
            base = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            base.putalpha(shadow.filter(ImageFilter.GaussianBlur(0.03 * size)))
            spr = np.array(Image.alpha_composite(Image.alpha_composite(base, outl), fill))
            self.chunks.append((a - src_start, b - src_start, spr, ych))
        self.yc = yc

    def draw(self, img, tl):
        for ta, tb, spr, ych in self.chunks:
            if ta <= tl < tb:
                k = (1 + (self.POP - 1) * (1 - ease_out((tl - ta) / 0.12))) / self.POP
                h, w = spr.shape[:2]
                s = cv2.resize(spr, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
                blit(img, s, int(W / 2 - s.shape[1] / 2), int((ych if ych else self.yc) - s.shape[0] / 2))
                return


# ----------------------------------------------------------------------------- sources
class Reader:
    def __init__(self, cmd, need):
        self.cmd, self.need, self.proc, self.pos, self.cur, self.fs = cmd, need, None, -1, None, W * H * 3

    def get(self, i):
        i = max(i, 0)
        while self.pos < i:
            if self.proc is None:
                self.proc = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=self.fs * 4)
            buf = self.proc.stdout.read(self.fs)
            if len(buf) < self.fs:  # EOF: tolerate rounding of <=2 frames, hold last frame; otherwise fail loudly
                assert self.pos + 1 >= self.need - 2, f"source ended after {self.pos + 1} frames, need {self.need}: {' '.join(self.cmd)}"
                self.pos = i
                break
            self.cur = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            self.pos += 1
        return self.cur

    def close(self):
        if self.proc:
            self.proc.kill(); self.proc.wait(); self.proc = None


class Still:
    def __init__(self, path, crop, lift=False, target=None):
        im = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
        assert im is not None, f"cannot read image {path}"
        ih, iw = im.shape[:2]
        if crop is None:
            cw = round(ih * 9 / 16); crop = ((iw - cw) // 2, 0, cw, ih)
        x, y, w, h = crop
        assert x >= 0 and y >= 0 and x + w <= iw and y + h <= ih, f"{path}: crop {crop} outside {iw}x{ih}"
        im = cv2.cvtColor(im[y:y + h, x:x + w], cv2.COLOR_BGR2RGB)
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA if w > W else cv2.INTER_CUBIC)
        small = cv2.resize(im, (540, 960), interpolation=cv2.INTER_AREA)
        if target is not None:
            self.img = ffgrade(im, look_modules()[0].image_filter(im, target))
        else:
            self.img = ffgrade(im, (SHADOW_LIFT + "," if lift else "") + color_chain(match_gains(small)))

    def get(self, i): return self.img
    def close(self): pass


def probe_duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


def media(name):
    """Resolve a photo name: absolute path as-is, else the clips dir, else the build dir."""
    p = Path(name)
    if p.is_absolute():
        return p
    return next((b / p for b in (VID, BUILD) if (b / p).exists()), VID / p)


def build_path(p):
    """Path given in a config: absolute as-is, else relative to --build-dir."""
    p = Path(p)
    return p if p.is_absolute() else BUILD / p


class Shot:
    def __init__(self, spec, F0, n, text_only=False):
        """text_only: build the captions / subtitles but no picture source (tools/textzone.py measures text without decoding video)."""
        self.spec, self.F0, self.n = spec, F0, n
        self.src = None
        self.kind = spec["kind"]
        self.speed = spec.get("speed", 1.0)
        self.push = spec.get("push", 0.06)
        self.drift = spec.get("drift", 0.0)
        self.grade = self.kind != "hero"
        self.trans, self.shake = spec.get("trans", "hard"), spec.get("shake", False)
        self.caps, self.sub, self.embers = [], None, None
        if self.kind == "photo":
            if not text_only:
                self.src = Still(media(spec["file"]), spec.get("crop"), spec.get("lift", False), spec.get("_target"))
            self.push = spec.get("push", 0.08)
        elif self.kind == "hero":
            ytop, cw, x0 = self.hero_layout(spec)
            M, hh = round(600 * S), round(1440 * W / cw / 2) * 2
            chain = (f"crop={cw}:1440:{x0}:0,scale={W}:{hh}:flags=lanczos,{SHARPEN_4K + ',' if S == 1 else ''}"
                     f"pad={W}:{H + 2 * M}:0:{ytop + M}:black,crop={W}:{H}:0:{M}")
            if not text_only:
                self.src = self._ffmpeg(HERO, [], chain, spec["start"], [(0, 6.0)], 1.0)
            self.push = spec.get("push", 0.03)
        elif text_only:
            pass
        else:
            f, opts, crop, good = CLIPS[spec["clip"]]
            t1 = spec["start"] + self.n / FPS * self.speed  # this shot's own source range, not the clip's
            scale = f"scale={W}:{H}:flags={'lanczos' if S == 1 else 'area'}"
            sharp = SHARPEN_4K if S == 1 and spec["clip"] in UPSCALED else ""
            base = spec.get("_chain", crop or "")
            food = spec["clip"] in FOOD_CLIPS
            if spec.get("_target") is not None:
                pre, post = look_modules()[0].shot_filter_parts(str(VID / f), opts, spec.get("_stats"), spec["start"], t1, spec["_target"], food=food)
                chain = ",".join(x for x in [base, pre, scale, sharp, post] if x)  # denoise at source res, colour after the sharpen
            else:
                stat_crop = spec["_stats"] if "_stats" in spec else crop  # a static crop: the animated path would be sampled at t=0
                gains = clip_gains((spec.get("_reel"), spec["clip"]), VID / f, opts, stat_crop, spec.get("_ranges") or [(spec["start"], t1)])
                chain = ",".join(x for x in [base, scale, sharp, color_chain(gains, food=food)] if x)
            self.src = self._ffmpeg(VID / f, opts, chain, spec["start"], good, self.speed)
        self.setup_text(spec, n)
        if spec.get("embers"):
            self.embers = Embers(spec["embers"], seed=F0 + 1)

    def _ffmpeg(self, path, opts, chain, start, windows, speed):
        need_src = self.n / FPS * speed
        win = [w for w in windows if w[0] - 1e-3 <= start and start + need_src <= w[1] + 5e-3]
        assert win, f"{path.name}: source range {start:.3f}-{start + need_src:.3f} not inside good windows {windows}"
        assert start + need_src <= probe_duration(path) + 5e-3, f"{path.name}: range exceeds file duration"
        avail = win[0][1] - start
        length = min(avail, (self.n + 1) / FPS * speed)  # own range only (+1 frame); whip/zoom post-roll holds the last frame
        vf = f"setpts=(PTS-STARTPTS)/{speed},fps={FPS},{chain},format=rgb24"
        cmd = ["ffmpeg", "-v", "error", *opts, "-ss", f"{start:.4f}", "-t", f"{length:.4f}", "-i", str(path), "-an", "-vf", vf,
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        return Reader(cmd, self.n)

    def hero_layout(self, spec):
        """Logo + text lines as one group centred at GROUP_CY, ending above GROUP_BOTTOM (the logo shrinks if it must).
        Returns (logo y offset, crop width, crop x) for the hero source."""
        x0s, x1s, y0s, y1s = LOGO
        caps = [Caption(text, kw.pop("font", FONT_DISPLAY), 0.15, 0, t0, seed=self.F0 + j, top=0.0, **kw)
                for j, (t0, text, kw) in enumerate((t0, tx, dict(kw)) for t0, tx, kw in spec["hero_texts"])]
        gaps = [g * H for g in spec.get("hero_gaps", [0.035, 0.02, 0.012])][:len(caps)]
        lw = LOGO_W
        while True:
            cw = round((x1s - x0s) / lw)
            k = W / cw
            h_logo = (y1s - y0s) * k
            gh = h_logo + sum(g + (c.bottom - c.top) for g, c in zip(gaps, caps))
            gt = max(GROUP_CY * H - gh / 2, 0.03 * H)
            if gt + gh <= GROUP_BOTTOM * H or lw <= 0.5:
                break
            lw -= 0.01
        x0 = round((x0s + x1s) / 2 - cw / 2)
        y = gt + h_logo
        for g, c in zip(gaps, caps):
            c.shift(y + g - c.top)
            y = c.bottom
        for c in caps[1:]:
            assert c.cap_h >= spec.get("hero_min_cap", 0) * H, f"text line is only {c.cap_h / H * 100:.2f}% tall"
        self.caps += caps
        self.group = (gt / H, y / H, lw)  # group top, text bottom (baseline), logo width fraction
        return round(gt - y0s * k), cw, x0

    def setup_text(self, spec, n):
        dur = n / FPS
        t_exit = dur - 0.30
        if spec.get("title"):
            t0 = spec.get("tdelay", 0.15)
            top = 0.205 if spec.get("kicker") else 0.18  # title cap-top; kicker sits above, all inside the 15%-72% safe zone
            nlet = sum(ch.isalpha() for ch in spec["title"])
            stag = 0.02 if nlet > 14 else 0.035  # long titles fill in faster
            c = Caption(spec["title"], FONT_DISPLAY, 0.15, 0, t0, t_exit=t_exit, sparks=16, seed=self.F0, fill=0.85, cap_frac=0.115,
                        top=top * H, stagger=stag)
            self.caps.append(c)
            read = t_exit - (t0 + stag * nlet + c.dur)  # fully on screen before it starts to leave
            assert read >= 1.0, f"title '{spec['title']}' is fully visible for only {read:.2f}s (needs >= 1.0): lengthen the shot or shorten the title"
            self.title_read = read
            if spec.get("kicker"):
                k = Caption(spec["kicker"], FONT_KICKER, spec.get("kicker_size", 0.066), 0, t0 - 0.08, t_exit=t_exit - spec.get("kicker_early", 0.6),
                            color=ACCENT, top=c.top - spec.get("kicker_gap", 0.09) * W, stagger=0.012, spacing_em=0.12, dur=0.3, rise_em=0.4)
                self.caps.append(k)
                assert k.top >= 0.15 * H - 1, f"kicker top {k.top / H:.3f}H above safe zone"
            assert c.top >= 0.15 * H - 1 and c.bottom <= 0.72 * H, f"title {spec['title']}: {c.top / H:.3f}-{c.bottom / H:.3f}H outside 15%-72%"
            if not self.embers:
                self.spec["embers"] = 14
        if spec.get("subs"):
            self.sub = Subs(spec["subs"], spec["start"], spec.get("sub_y", 0.61) * H)

    def render(self, i, f, pulse):
        ic = max(i, 0)
        base = self.src.get(ic)
        t = f / FPS
        z = 1 + self.push * ic / self.n + 0.12 * (1 - ease_out(ic / 15)) + pulse
        dx = self.drift * W * (ic / self.n - 0.5)
        img = affine(base, z, dx) if (abs(z - 1) > 1e-4 or dx) else base.copy()
        if self.grade:
            img = grade(img)
        if self.kind == "hero":
            img = cv2.max(img, HERO_BG)
        tl = i / FPS
        if self.embers or any(c.sparks for c in self.caps):
            ov = np.zeros_like(img)
            if self.embers: self.embers.draw(ov, t)
            for c in self.caps:
                if c.sparks: c.draw_sparks(ov, tl)
            img = composite_particles(img, ov)
        if not NOTEXT:
            for c in self.caps:
                c.draw(img, tl)
            if self.sub:
                self.sub.draw(img, tl)
        return img

    def close(self):
        if self.src:
            self.src.close()


HERO_BG = None


# ----------------------------------------------------------------------------- timeline
TRANS_WIN = {"hard": (0, 0), "flash": (0, 0), "whip": (4, 4), "zoom": (5, 5)}


def plan_core(cfg):
    key, _, st = cfg["song"]
    rel = [b - st - BEAT_LAG for b in SONGS[key]["beats"] if b >= st - 0.05]
    rel[0] = max(rel[0], 0.0)
    shots, a, bi = [], 0, 0
    for sp in cfg["shots"]:
        if sp.get("kind") == "voice_track":
            ents, cfg["_vt"] = expand_voice_track(sp, a, rel)
            shots += ents
            a = ents[-1][2]
            continue
        if "frames" in sp:
            b = sp["frames"][1]
        elif "beats" in sp:
            bi += sp["beats"]; b = round(rel[bi] * FPS)
        elif "until_abs" in sp:  # cut on the beat nearest to an absolute song time (a drop / accent)
            tgt = sp["until_abs"] - st
            bi = min(range(len(rel)), key=lambda i: abs(rel[i] - tgt)); b = round(rel[bi] * FPS)
            assert b > a, f"until_abs {sp['until_abs']} is not after the shot start"
        elif "dur" in sp:
            b = a + round(sp["dur"] * FPS)
        elif sp.get("end_auto"):  # end card runs to a musical phrase end (bar end as fallback) giving 2.5-3.5 s
            b = round(end_beat(key, st, rel, a / FPS) * FPS)
        else:  # "after": END card running until the first beat >= start + after
            b = round(rel[bisect.bisect_left(rel, a / FPS + sp["after"])] * FPS)
        if sp.get("src_end"):  # speed derived so the shot consumes exactly its allotted source range
            sp["speed"] = (sp["src_end"] - sp["start"]) / ((b - a) / FPS)
        shots.append((sp, a, b))
        a = b
    return rel, shots


def plan(cfg):
    """-> (beat times relative to the reel start, [(shot spec, first frame, end frame)]) with the branding captions injected."""
    rel, p = plan_core(cfg)
    add_branding_text(rel, p, cfg)
    return rel, p


def end_beat(key, st, rel, card_start):
    """End time (a json beat) of the end card: the phrase/bar boundary whose card length is closest to 2.5-3.5 s;
    bar ends pay a small penalty so a true phrase end wins when both are about as good."""
    if key not in PHRASES:
        raise SystemExit(f"end_card without beats/after needs phrase boundaries for '{key}': run tools/phrases.py (writes <build>/phrases.json)")
    best = None
    for kind, lst in (("phrase", PHRASES[key]["phr"]), ("bar", PHRASES[key]["bars"])):
        for ab in lst:
            L = ab - st - card_start
            if not 1.8 <= L <= 4.6:
                continue
            score = max(0.0, 2.5 - L, L - 3.5) + (0.35 if kind == "bar" else 0.0)
            if best is None or score < best[0]:
                best = (score, ab - st, kind)
    assert best, f"no phrase/bar boundary for an end card starting at {card_start:.2f}s"
    t = min(rel, key=lambda x: abs(x - best[1]))
    print(f"   end card: {best[2]} end at reel {t:.2f}s (card {t - card_start:.2f}s)", flush=True)
    return t


# ----------------------------------------------------------------------------- voice track (testimonial / talking-head sections)
# One isolated-voice wav + ordered source pieces. Pieces are laid back to back (gap of real silence); the picture is
# talking-head shots lip-synced to the piece being heard (same source time), overridden by B-roll inserts anchored to
# source times (J/L-cut: the voice never stops). Spec (a "voice_track" entry in a reel's shots):
#   clip=<talking-head clip>, words=[(source s, word)], pieces=[(src start, src end)], inserts=[dict(at, until, kind, ...)],
#   framing=[(src s, "tight"|"wide")], hook=dict(src=(s, e), at=reel s, words=[source s per tagline word]), av=audio lead/lag.
def snap_beat(t, rel, tol=0.20, bounds=()):
    """Nearest beat within tol that leaves no sliver (< 0.4 s) next to a piece boundary; else the raw time."""
    for b in sorted((x for x in rel if abs(x - t) <= tol), key=lambda x: abs(x - t)):
        if all(abs(b - e) < 1e-3 or abs(b - e) >= 0.4 for e in bounds):
            return b
    return t


def expand_voice_track(sp, a, rel):
    P, gap = sp["pieces"], sp.get("gap", 0.12)
    av, hook = sp.get("av", 0.0), sp.get("hook")
    n, T, t = len(P), [], a / FPS
    for s0, e0 in P:  # frame-aligned piece start times on the reel timeline
        tf = round(t * FPS) / FPS
        T.append(tf); t = tf + (e0 - s0) + gap
    v_end = T[-1] + P[-1][1] - P[-1][0]
    nb = [x for x in rel if v_end + 0.08 <= x <= v_end + 0.40]  # the end card starts on a beat after the last word
    Fend = round((nb[0] if nb else v_end + sp.get("tail", 0.15)) * FPS)
    E = [T[i + 1] if i + 1 < n else Fend / FPS for i in range(n)]  # picture segment of piece i includes its trailing gap

    def to_t(src, end=False):
        for i, (s0, e0) in enumerate(P):
            if s0 - 1e-6 <= src <= e0 + 1e-6:
                return T[i + 1] if end and abs(src - e0) < 1e-6 and i + 1 < n else T[i] + src - s0
        raise AssertionError(f"anchor {src} is not inside any voice piece {P}")

    bounds = [x for x in T] + [x for x in E]
    ins = sorted(((snap_beat(to_t(i["at"]), rel, bounds=bounds), snap_beat(to_t(i["until"], True), rel, bounds=bounds), i)
                  for i in sp.get("inserts", [])), key=lambda x: x[0])
    out, pos = [], a

    changes = sorted(sp.get("framing", []))  # [(source time, "tight"|"wide")]: framing switches (jump-cut hiding)

    def framing(src):
        cur = "wide"
        for t0_, mode in changes:
            if t0_ <= src + 1e-6:
                cur = mode
        return cur

    def heads(fa, fb):
        for i, (s0, e0) in enumerate(P):
            x, y = max(fa, round(T[i] * FPS)), min(fb, round(E[i] * FPS))
            if y <= x:
                continue
            cuts = [x] + sorted(c for c in (round((T[i] + t0_ - s0) * FPS) for t0_, _ in changes) if x + 24 <= c <= y - 24) + [y]
            for x1, y1 in zip(cuts, cuts[1:]):
                assert y1 - x1 >= 12, f"talking-head shot of piece {i} is only {y1 - x1} frames"
                src0 = s0 + av + x1 / FPS - T[i]  # picture time of this voice position (audio may start later than the video)
                mode = framing(src0 + min(0.5, (y1 - x1) / FPS / 2))  # framing in force for most of this shot
                out.append((dict(kind="video", clip=sp["clip"], start=src0, speed=1.0, trans="hard", frames=(x1, y1), role="head",
                                 tight=mode == "tight"), x1, y1))

    for t0, t1, i in ins:
        f0, f1 = round(t0 * FPS), round(t1 * FPS)
        assert f0 >= pos and f1 - f0 >= 20, f"insert {i} overlaps or is too short ({f0}-{f1}, previous end {pos})"
        if f0 > pos:
            heads(pos, f0)
        if i["kind"] == "video":
            speed = (i["src"][1] - i["src"][0]) / ((f1 - f0) / FPS)
            assert 0.5 <= speed <= 2.2, f"insert {i['clip']} {i['src']} would need speed {speed:.2f}"
            spec = dict(kind="video", clip=i["clip"], start=i["src"][0], speed=speed)
        else:
            spec = dict(kind="photo", file=i["file"], crop=i.get("crop"), drift=i.get("drift", 0.02))
        out.append((dict(spec, trans=i.get("trans", "hard"), shake=i.get("shake", False), frames=(f0, f1), role="insert"), f0, f1))
        pos = f1
    if Fend > pos:
        heads(pos, Fend)
    out[0][0]["trans"] = sp.get("first_trans", "whip")
    pieces, Ts, v0 = P, T, T[0]
    if hook:  # cold-open: the payoff line plays under the logo intro, before the first body piece
        hs, he = hook["src"]
        assert hook["at"] + (he - hs) <= T[0] - 0.25, f"hook ends at {hook['at'] + he - hs:.2f}s, body starts at {T[0]:.2f}s"
        pieces, Ts, v0 = [hook["src"]] + list(P), [hook["at"]] + list(T), hook["at"]
    return out, dict(pieces=pieces, T=Ts, v_start=v0, v_end=v_end, subs=vt_subs(sp, T), hook=hook, body_start=T[0])


_subfont = {}


def text_w(text):
    """Width (as a fraction of the frame) of a subtitle at its nominal size (SUB_PX at 2160 px)."""
    key = (str(FONT_KICKER), SUB_PX)
    if key not in _subfont:
        _subfont[key] = ImageFont.truetype(str(FONT_KICKER), SUB_PX)
    return _subfont[key].getlength(text) / 2160


def vt_subs(sp, T):
    """Subtitle chunks (<= 4 words, <= 0.78 W) from per-word source timings, mapped to the reel timeline.
    A chunk never ends on a dangling function word (it moves to the next chunk) and stays >= 0.5 s on screen."""
    chunks = []
    for i, (s0, e0) in enumerate(sp["pieces"]):
        ws = [(t, w) for t, w in sp.get("words", []) if s0 - 0.02 <= t < e0 and t not in sp.get("skip", ())]
        if not ws:
            continue
        groups, cur = [], []

        def fits(g): return len(g) <= 4 and text_w(" ".join(x.upper() for _, x in g)) <= 0.78

        for t, w in ws:
            pause = bool(cur) and (t - cur[-1][0] > 0.9 or t in sp.get("break_before", ()))
            if cur and (pause or not fits(cur + [(t, w)])):
                carry = []
                while len(cur) > 1 and cur[-1][1].lower() in FUNC_WORDS:
                    carry.insert(0, cur.pop())
                groups.append(cur); cur = carry
            cur.append((t, w))
        groups.append(cur)
        for gi, g in enumerate(groups):
            ta = T[i] + g[0][0] - s0 - 0.03
            last = T[i] + g[-1][0] - s0
            nxt = T[i] + groups[gi + 1][0][0] - s0 - 0.03 if gi + 1 < len(groups) else None
            tb = min(nxt if (nxt is not None and nxt - last < 0.9) else last + 0.8, T[i] + e0 - s0)
            toks = [w.upper() for _, w in g]
            marked = ["{" + tk + "}" if tk.lower() in ACCENT_WORDS else tk for tk in toks]
            chunks.append((ta, tb, " ".join(marked)))
    chunks.sort()
    for k in range(len(chunks)):  # minimum read time 0.5 s: a short chunk stays up, the next one appears up to ~0.1 s late
        a1, b1, t1 = chunks[k]
        if b1 - a1 < 0.5:
            b1 = a1 + 0.5
            chunks[k] = (a1, b1, t1)
            if k + 1 < len(chunks) and chunks[k + 1][0] < b1:
                a2, b2, t2 = chunks[k + 1]
                chunks[k + 1] = (b1, max(b2, b1 + 0.4), t2)
    for (a1, b1, t1) in chunks:
        if b1 - a1 < 0.5 - 1e-6:
            print(f"   WARNING subtitle '{t1}' is on screen only {b1 - a1:.2f}s", flush=True)
    return chunks


# ----------------------------------------------------------------------------- audio
def voice_graph(vt, idx, gain, silence=True):
    """Filters turning the isolated-voice input #idx into [vpad]: pieces with 20 ms fades, real silence between."""
    P, T, n = vt["pieces"], vt["T"], len(vt["pieces"])
    f = [f"[{idx}:a]asplit={n}" + "".join(f"[s{i}]" for i in range(n))]
    labels, t_prev = [], 0.0
    for i, (s0, e0) in enumerate(P):
        L = e0 - s0
        fo = 0.06 if i == n - 1 else 0.02  # last piece of the reel fades a little longer
        f.append(f"[s{i}]atrim={s0:.4f}:{e0:.4f},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,highpass=f=90,"
                 f"afade=t=in:d=0.02,afade=t=out:st={L - fo:.4f}:d={fo}[p{i}]")
        if silence:
            d = T[i] - t_prev
            if d > 1e-4:
                f.append(f"anullsrc=r=48000:cl=stereo:d={d:.4f}[z{i}]"); labels.append(f"[z{i}]")
            t_prev = T[i] + L
        labels.append(f"[p{i}]")
    f.append("".join(labels) + f"concat=n={len(labels)}:v=0:a=1[vcat];[vcat]{VOICE_DYN},{VOICE_EQ},volume={gain:.2f}dB[vpad]")
    return f


def lufs(args, graph, label):
    r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", *args, "-filter_complex", graph + f";[{label}]ebur128=peak=true[o]",
                        "-map", "[o]", "-f", "null", "-"], capture_output=True, text=True, check=True)
    return float(re.findall(r"I:\s+(-?\d+\.\d) LUFS", r.stderr)[-1])


def voice_gain_db(vt, cfg):
    """Gain that brings the assembled voice (after highpass) to ~-16 LUFS before mixing."""
    m = lufs(["-i", str(build_path(cfg["voice"]))], ";".join(voice_graph(vt, 0, 0.0, silence=False)), "vpad")
    return cfg.get("voice_lufs", -16.0) - m


def ramps(aw, a1, from_start=False):
    """Speech window: the bed fades in over 0.3 s starting 0.45 s BEFORE the first spoken word, and comes back over 0.35 s
    starting 0.2 s before the last word ends (no hole after the speech)."""
    A, B = (-0.4 if from_start else aw - 0.45), a1 - 0.2   # from_start: the intro already plays on the instrumental bed
    return A, B, f"(min(1,max(0,(t-{A:.3f})/0.3))-min(1,max(0,(t-{B:.3f})/0.35)))"


def duck_carve(aw, a1):
    """Fallback without a bed: -16 dB duck + 8 dB cut of the 1-4 kHz speech band while someone talks."""
    A, B, k = ramps(aw, a1)
    duck = f"volume='1-0.84*{k}':eval=frame"
    carve = f"equalizer=f=2200:t=q:w=0.8:g=-8:enable='between(t,{A + 0.1:.3f},{B + 0.45:.3f})'"
    return f"{duck},{carve}"


def bed_path(cfg):
    """Instrumental stem of the song section that starts at the reel's song start (tools/make_bed.py writes it), if prepared.
    cfg["bed"] = explicit path (relative to --build-dir); cfg["bed"] = False disables the bed (plain duck + carve)."""
    if cfg.get("bed") is False:
        return None
    key, _, st = cfg["song"]
    p = build_path(cfg["bed"]) if cfg.get("bed") else BUILD / "beds" / f"{key}_{float(st)}" / "no_vocals.wav"
    return p if p.exists() else None


def music_under_speech(full_idx, bed_idx, base, aw, a1, fade, out="mus", bed_db=None, carve_db=-4.0, from_start=False):
    """While someone talks, crossfade the full song into its own instrumental stem (same section, phase-aligned):
    the beat keeps the bed full but no sung vocals compete with the words. Light 1-4 kHz carve on the bed.
    aw = first spoken word, a1 = end of the speech."""
    A, B, k = ramps(aw, a1, from_start)
    bed = 10 ** ((BED_DB if bed_db is None else bed_db) / 20)
    carve = f"equalizer=f=2200:t=q:w=0.8:g={carve_db}:enable='between(t,{A + 0.1:.3f},{B + 0.45:.3f})'"
    return [f"[{full_idx}:a]{base},volume='1-{k}':eval=frame[mfull]",
            f"[{bed_idx}:a]{base},volume='{bed:.4f}*{k}':eval=frame,{carve}[mbed]",
            f"[mfull][mbed]amix=inputs=2:normalize=0:duration=first,{fade}[{out}]"]


def music_base(cfg, total):
    fx = ("," + cfg["music_fx"]) if cfg.get("music_fx") else ""  # e.g. bass trim / glue compressor on the music bus
    return f"aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},volume={cfg['gain_db']}dB{fx}"


def audio_buses(cfg, total, v_start=0.0, v_end=0.0, sfx_wav=None):
    """Input args + filter list that build the buses of a reel BEFORE the master limiter: music [mus] (ducked / bed under speech),
    voice [vpad] (if the reel has speech) and [fx] (opt-in SFX). Returns (ffmpeg input args, filters, bus labels).
    Shared by build_audio and tools/audio_buses.py. v_start/v_end: speech window of an old-style voice_shot (voice track: from the plan)."""
    key, song_file, st = cfg["song"]
    args = ["-ss", f"{st}", "-t", f"{total + 0.5:.3f}", "-i", str(MUSIC / song_file)]
    n_in = 1
    fade = f"afade=t=out:st={total - FADE_OUT:.3f}:d={FADE_OUT}"
    base = music_base(cfg, total)
    vt = cfg.get("_vt")
    vf, labels = [], ["[mus]"]
    if cfg.get("voice"):
        args += ["-i", str(build_path(cfg["voice"]))]
        n_in += 1
        bed = bed_path(cfg)
        if bed:
            args += ["-i", str(bed)]
            n_in += 1
        else:
            print("   (no instrumental bed found: falling back to duck + carve; run tools/make_bed.py for a fuller mix)", flush=True)
        if vt:
            g = voice_gain_db(vt, cfg)
            print(f"   voice gain {g:+.1f} dB (to {cfg.get('voice_lufs', -16.0)} LUFS)", flush=True)
            aw, a1, from_start = vt["v_start"], vt["v_end"], bool(vt.get("hook"))
        else:
            aw, a1, from_start = v_start + cfg.get("first_word_offset", 0.0), v_end, False
        if bed:
            vf += music_under_speech(0, 2, base, aw, a1, fade, bed_db=cfg.get("bed_db"), carve_db=cfg.get("carve_db", -4.0), from_start=from_start)
        else:
            vf.append(f"[0:a]{base},{duck_carve(aw, a1)},{fade}[mus]")
        if vt:
            vf += voice_graph(vt, 1, g)
        else:
            vs = cfg["_voice_src_start"] - cfg.get("voice_t0", 0.0) - cfg.get("av", 0.0)  # position of the picture start inside the voice file
            vf.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=start={vs:.4f}:end={vs + v_end - v_start:.4f},asetpts=PTS-STARTPTS,"
                      f"highpass=f=90,{VOICE_DYN},{VOICE_EQ},"
                      f"volume={cfg['voice_gain_db']}dB,afade=t=in:d=0.08,afade=t=out:st={v_end - v_start - 0.25:.3f}:d=0.25[vo]")
            vf.append(f"anullsrc=r=48000:cl=stereo:d={v_start:.3f}[sil];[sil][vo]concat=n=2:v=0:a=1[vpad]")
        labels.append("[vpad]")
    else:
        vf.append(f"[0:a]{base},{fade}[mus]")
    if sfx_wav:
        args += ["-i", str(sfx_wav)]
        vf.append(f"[{n_in}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f}[fx]")
        labels.append("[fx]")
    return args, vf, labels


def voice_window(cfg, plan_):
    """Speech window (s) of an old-style voice_shot reel (0, 0 without one); records where the picture starts inside the voice file."""
    sp_last = [p for p in plan_ if p[0].get("voice_shot")]
    cfg["_voice_src_start"] = min((p[0]["start"] for p in sp_last), default=0.0)
    return (min(p[1] for p in sp_last) / FPS, max(p[2] for p in sp_last) / FPS) if sp_last else (0.0, 0.0)


def build_audio(out, cfg, total, v_start, v_end, sfx_wav):
    args, vf, labels = audio_buses(cfg, total, v_start, v_end, sfx_wav)
    mix = "".join(labels) + (f"amix=inputs={len(labels)}:normalize=0:duration=first," if len(labels) > 1 else "")
    vf.append(f"{mix}{LIMITER},asetpts=N/SR/TB,atrim=0:{total:.3f}[a]")
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args, "-filter_complex", ";".join(vf), "-map", "[a]",
                    "-c:a", "aac", "-b:a", "256k", str(out)], check=True)


# ----------------------------------------------------------------------------- render
def render_reel(name, cfg, preview, audio_only=False):
    global HERO_BG
    HERO_BG = np.full((H, W, 3), BG, np.uint8)
    rel, plan_ = plan(cfg)
    total = plan_[-1][2]
    tsec = total / FPS
    out_dir = (BUILD / "notext") if NOTEXT else BUILD / "preview" if preview else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = "n" if NOTEXT else "p" if preview else "f"  # temp files per kind of render: a preview never clobbers a running final
    final, tmp_v, tmp_a = out_dir / f"{name}.mp4", BUILD / f"_{name}_{tag}_v.mp4", BUILD / f"_{name}_{tag}_a.m4a"
    assert preview or NOTEXT or OVERWRITE or not final.exists(), f"{final} exists; pass --overwrite to replace it"
    v_start, v_end = voice_window(cfg, plan_)
    ranges = {}  # clip -> every source range the reel uses (shared colour gains per clip, legacy grade)
    for sp, a, b in plan_:
        if sp["kind"] == "video":
            ranges.setdefault(sp["clip"], []).append((sp["start"], sp["start"] + (b - a) / FPS * sp.get("speed", 1.0)))
    for sp, a, b in plan_:
        sp["_reel"], sp["_ranges"] = name, ranges.get(sp.get("clip"))
    vt = cfg.get("_vt")
    print(f"== {name}: {tsec:.3f}s ({total} frames) W={W}x{H}", flush=True)
    for sp, a, b in plan_:
        print(f"   {a / FPS:7.3f}s  {sp['kind']:5s} {sp.get('clip') or Path(str(sp.get('file', 'hero'))).name:26s} "
              f"{(b - a) / FPS:5.2f}s  trans={sp.get('trans', '-')}{'+shake' if sp.get('shake') else ''}"
              f"{'  ' + sp['role'] if sp.get('role') else ''}{('  src %.2f x%.2f' % (sp['start'], sp.get('speed', 1))) if sp['kind'] == 'video' else ''}", flush=True)
    # SFX are opt-in (cfg["sfx"]=True): generic synthesized effects tend to clash with music-driven reels.
    sfx_wav = None
    if cfg.get("sfx"):
        sys.path.insert(0, str(HERE))
        from sfx import build_sfx  # lazy: needs scipy
        amb = (AMBIENCE_CLIP, CLIPS[AMBIENCE_CLIP][0]) if AMBIENCE_CLIP else None
        sfx_wav = build_sfx(plan_, FPS, tsec, BUILD / f"_{name}_{tag}_sfx.wav", VID, (v_start, v_end), amb)
    build_audio(tmp_a, cfg, tsec, v_start, v_end, sfx_wav)
    if audio_only:
        return
    tgt = grade_prepare(plan_)
    for sp, a, b in plan_:
        sp["_target"] = tgt
    shots = [Shot(sp, a, b - a) for sp, a, b in plan_]
    if "GV" in _look:
        _look["GV"].save_cache(BUILD / "cache" / "grade_stats.pkl")
    if tgt is not None:
        print(f"   look target: L50 {tgt['L50']:.1f} cast {tgt['cast'][0]:+.1f},{tgt['cast'][1]:+.1f} ({tgt['n']} shots)", flush=True)
    gsubs = None if NOTEXT else reel_subtitles(plan_, vt)
    F = [s.F0 for s in shots] + [total]
    beat_f = [round(b * FPS) for b in rel]
    q = "-crf 23 -preset veryfast" if preview else "-crf 16 -preset medium"
    enc = subprocess.Popen(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", *q.split(), "-c:v", "libx264", "-profile:v", "high", "-level", "5.2",
         "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(tmp_v)],
        stdin=subprocess.PIPE)
    white = np.full((H, W, 3), 255, np.uint8)
    rng = np.random.default_rng(5)
    wdir, t_start, cur = 1, time.time(), 0
    bwin = {}  # boundary index -> (type, F, pre, post, dir)
    for k in range(1, len(shots)):
        ty = shots[k].trans
        pre, post = TRANS_WIN[ty]
        bwin[k] = (ty, F[k], pre, post, wdir)
        if ty == "whip": wdir = -wdir
    try:
        for f in range(total):
            while f >= F[cur + 1]: cur += 1
            pulse = 0.0
            bi = bisect.bisect_right(beat_f, f) - 1
            if bi >= 0: pulse = 0.015 * math.exp(-(f - beat_f[bi]) / FPS / 0.09)
            win = next((k for k, (ty, Fk, pre, post, d) in bwin.items() if Fk - pre <= f < Fk + post and (pre or post)), None)
            if win is None:
                img = shots[cur].render(f - shots[cur].F0, f, pulse)
            else:
                ty, Fk, pre, post, d = bwin[win]
                A, B = shots[win - 1], shots[win]
                if ty == "whip":
                    img = whip(A.render(f - A.F0, f, pulse), B.render(f - B.F0, f, pulse), f - (Fk - pre), pre + post, d)
                elif f < Fk:  # zoom-through, outgoing half
                    s1 = 1 + 0.5 * ease_in((f - (Fk - pre) + 1) / pre)
                    img = zoom_blur(A.render(f - A.F0, f, pulse), 1 + (s1 - 1) * 0.55, s1)
                else:  # incoming half settles from ~1.35
                    e = 1 + 0.35 * (1 - ease_out((f - Fk + 0.5) / post))
                    img = zoom_blur(B.render(f - B.F0, f, pulse), e, 1 + (e - 1) * 0.55)
            if gsubs:
                gsubs.draw(img, f / FPS)
            # boundary effects (global): flash+flare, shake
            for k, (ty, Fk, pre, post, d) in bwin.items():
                j = f - Fk
                if 0 <= j < 18 and ty == "flash":
                    img = flare(img, (1 - j / 18) ** 2)
                    if j < 6: img = cv2.addWeighted(img, 1 - 0.85 * (1 - j / 6), white, 0.85 * (1 - j / 6), 0)
                if 0 <= j < 6 and shots[k].shake:
                    amp = 0.02 * W * (1 - j / 6)
                    img = affine(img, 1.0, rng.uniform(-amp, amp), rng.uniform(-amp, amp))
            if 1 <= f < 19:  # intro: flare + soft flash on beat 0 (frame 0 itself stays clean: no grey wash on the thumbnail)
                j = f - 1
                img = flare(img, (1 - j / 18) ** 2)
                if j < 8: img = cv2.addWeighted(img, 1 - 0.5 * (1 - j / 8), white, 0.5 * (1 - j / 8), 0)
            enc.stdin.write(img.data)
            for k in range(cur):
                if f >= F[k + 1] + 8: shots[k].close()
            if f % 300 == 0:
                print(f"   frame {f}/{total}  {time.time() - t_start:.0f}s", flush=True)
    finally:
        enc.stdin.close(); enc.wait()
        for s in shots: s.close()
    assert enc.returncode == 0, "encoder failed"
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(tmp_v), "-i", str(tmp_a), "-map", "0:v", "-map", "1:a",
                    "-c", "copy", "-movflags", "+faststart", str(final)], check=True)
    tmp_v.unlink(); tmp_a.unlink()
    print(f"   -> {final}  ({time.time() - t_start:.0f}s)", flush=True)


def reel_subtitles(plan_, vt):
    """Reel-level Subs of a voice track (they stay on top of the B-roll inserts); None without a voice track or words.
    Chunks over inserts sit lower (0.685 H): people shot at table height would otherwise sit under the text."""
    if not vt or not vt["subs"]:
        return None
    ins = [(a / FPS, b / FPS) for sp, a, b in plan_ if sp.get("role") == "insert"]
    chunks = [(a, b, tx, 0.685) if any(i0 <= (a + b) / 2 < i1 for i0, i1 in ins) else (a, b, tx) for a, b, tx in vt["subs"]]
    return Subs(chunks, 0.0, 0.61 * H)


# ----------------------------------------------------------------------------- branding text, uniqueness table
def add_branding_text(rel, plan_, cfg=None):
    """Intro tagline on beat `tag_beat` (or, with a voice hook, letter by letter with the spoken words); end card = title + call to action."""
    vt = (cfg or {}).get("_vt") or {}
    for sp, a, b in plan_:
        if sp.get("tagline"):
            plain = "".join(ch for ch in sp["tagline"] if ch not in "{}")
            cap = 0.06 if len(plain) <= 12 else 0.05  # two-line taglines are a touch smaller
            kw = dict(sparks=22, cap_frac=cap, min_frac=0.8)
            t0 = rel[sp["tag_beat"]] - a / FPS
            if sp.get("hook_sync") and vt.get("hook"):
                hk = vt["hook"]
                wt = [hk["at"] + (w - hk["src"][0]) - a / FPS for w in hk["words"]]
                assert len(wt) == len(plain.split()), f"{len(wt)} hook word times for {len(plain.split())} tagline words"
                kw["word_times"] = wt
                kw["stagger"] = 0.03
                t0 = wt[0]
            sp["hero_texts"] = [(t0, sp["tagline"], kw)]
            sp["hero_gaps"] = [0.035]
        if sp.get("end"):
            texts, gaps, t = [], [END_GAP], 0.30
            if END_TITLE:
                texts.append((t, END_TITLE, dict(sparks=22, cap_frac=0.05, min_frac=0.7)))
            for ln in END_LINES:
                t += 0.30
                kw = dict(font=FONT_KICKER if ln.get("strong") else FONT_BODY, cap_frac=ln.get("cap", 0.032), stagger=0.012,
                          spacing_em=ln.get("spacing", 0.04), color=TEXT, max_w=0.94, min_frac=0.3)
                texts.append((t, ln["text"], kw))
                gaps.append(ln.get("gap", 0.012))
            sp["hero_texts"], sp["hero_gaps"] = texts, gaps
            sp["hero_min_cap"] = END_MIN_CAP if END_LINES else 0


def source_table(reels, names):
    """Every source range used by the named reels -> reel, and an overlap check across reels (no repeated footage)."""
    use = []  # (source key, start, end, reel, what)
    for name in names:
        _, p = plan(reels[name])
        for sp, a, b in p:
            n = (b - a) / FPS
            if sp["kind"] == "video":
                use.append((sp["clip"], sp["start"], sp["start"] + n * sp.get("speed", 1.0), name, sp.get("role", "")))
            elif sp["kind"] == "photo":
                use.append((Path(str(sp["file"])).name + str(sp.get("crop") or ""), 0, 0, name, "photo"))
    use.sort()
    for u in use:
        print(f"{u[0]:42s} {u[1]:7.2f} - {u[2]:7.2f}  {u[3]}  {u[4]}")
    bad = []
    for i, x in enumerate(use):
        for y in use[i + 1:]:
            if x[0] == y[0] and x[3] != y[3] and (x[1] < y[2] - 1e-3 and y[1] < x[2] - 1e-3 or (x[2] == 0 and y[2] == 0)):
                bad.append((x, y))
            if x[0] == y[0] and x[3] == y[3] and x[2] > 0 and x[1] < y[2] - 1e-3 and y[1] < x[2] - 1e-3 and x[4] != "head":
                bad.append((x, y))
    # the same photo file with a different crop inside one reel is fine (split crops); across reels it is a repeat
    print("OVERLAPS:", bad if bad else "none")


# ----------------------------------------------------------------------------- project config
def load_config(path):
    """Import the project config module and copy its settings into this module. Returns its REELS dict."""
    spec = importlib.util.spec_from_file_location("reel_project", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    g = globals()
    for k in _CONFIG_KEYS:
        if hasattr(mod, k):
            g[k] = getattr(mod, k)
    if getattr(mod, "DOMAIN", "") and not g["END_LINES"]:  # v1.1 shorthand: a single domain line under the end title
        g["END_LINES"] = [dict(text=mod.DOMAIN, cap=0.025, spacing=0.1, gap=0.03)]
    pal = getattr(mod, "PALETTE", {})
    for k, name in (("text", "TEXT"), ("accent", "ACCENT"), ("fire", "FIRE"), ("bg", "BG")):
        if k in pal:
            g[name] = tuple(pal[k])
    fonts = mod.FONTS  # relative names resolve against the assets dir; absolute paths pass through
    g["FONT_DISPLAY"], g["FONT_KICKER"], g["FONT_BODY"] = (ASSETS / fonts[k] for k in ("display", "kicker", "body"))
    g["HERO"] = ASSETS / mod.HERO if getattr(mod, "HERO", None) else None
    return mod.REELS


def init(config=None, build_dir="./build", videos="./clips", music="./music", assets="./assets", out="./out", preview=True):
    """Set the directories, load <build>/songs.json (+ phrases.json) and the project config, size the canvas.
    Returns the REELS dict. Used by main() and by the tools/ scripts that need the cut plan."""
    global BUILD, VID, MUSIC, ASSETS, OUT
    BUILD, VID, MUSIC, ASSETS, OUT = (Path(x) for x in (build_dir, videos, music, assets, out))
    songs = BUILD / "songs.json"
    if not songs.exists():
        sys.exit(f"{songs} not found: run tools/analyze_songs.py first")
    SONGS.update(json.load(open(songs, encoding="utf-8")))
    ph = BUILD / "phrases.json"
    if ph.exists():
        PHRASES.update(json.load(open(ph, encoding="utf-8")))
    reels = load_config(config or HERE / "project_example.py")
    configure(preview)
    return reels


def main():
    global OVERWRITE, NOTEXT, GRADE, REFRAME
    env = os.environ.get
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Render beat-synced branded vertical reels from a project config.")
    ap.add_argument("names", nargs="*", help="reel names from the config (default: all)")
    ap.add_argument("--config", default=env("REEL_CONFIG", str(HERE / "project_example.py")),
                    help="project config module (default: project_example.py next to this script)")
    ap.add_argument("--build-dir", default=env("REEL_BUILD_DIR", "./build"), help="scratch dir with songs.json, voice stems, beds; previews go to <build>/preview")
    ap.add_argument("--videos", default=env("REEL_VIDEOS", "./clips"), help="dir with the source clips and photos")
    ap.add_argument("--music", default=env("REEL_MUSIC", "./music"), help="dir with the song files you provide")
    ap.add_argument("--assets", default=env("REEL_ASSETS", "./assets"), help="dir with fonts and the hero video")
    ap.add_argument("--out", default=env("REEL_OUT", "./out"), help="dir for the 4K finals")
    ap.add_argument("--preview", action="store_true", help="540x960 fast preview instead of 4K")
    ap.add_argument("--audio-only", action="store_true", help="only build the audio track")
    ap.add_argument("--overwrite", action="store_true", help="allow replacing an existing final in --out")
    ap.add_argument("--notext", action="store_true", help="review aid: render captions/subtitles off into <build>/notext")
    ap.add_argument("--table", action="store_true", help="print the source-range table of the named reels and exit")
    ap.add_argument("--list", action="store_true", help="list the reel names of the config and exit")
    ap.add_argument("--grade", choices=["lut", "legacy"], help="override GRADE from the config")
    ap.add_argument("--no-reframe", action="store_true", help="plain center crops instead of subject-aware ones")
    a = ap.parse_args()
    OVERWRITE, NOTEXT = a.overwrite, a.notext
    reels = init(a.config, a.build_dir, a.videos, a.music, a.assets, a.out, a.preview)
    if a.grade:
        GRADE = a.grade
    if a.no_reframe:
        REFRAME = False
    if a.list:
        print("\n".join(reels)); return
    names = a.names or list(reels)
    if a.table:
        source_table(reels, names); return
    for n in names:
        render_reel(n, reels[n], a.preview, a.audio_only)


if __name__ == "__main__":
    main()
