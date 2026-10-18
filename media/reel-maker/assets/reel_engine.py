"""Beat-synced branded 4K vertical reel compositor: punch-ins, whip pans, flashes, zoom-through, shake,
embers/sparks and letter-in titles, driven by a per-project config module.

Usage (all paths default to the current directory layout; override with flags or REEL_* env vars):
    python reel_engine.py --config my_project.py --preview [reel names...]   # 540x960 -> <build>/preview/<name>.mp4
    python reel_engine.py --config my_project.py [reel names...]             # 2160x3840 finals -> <out>/<name>.mp4

The config module (see project_example.py) holds everything project-specific: clip table, reel cut lists,
songs, titles, subtitles, palette, fonts, hero/logo video and brand text. <build>/songs.json comes from
analyze_songs.py.
"""
import argparse, bisect, importlib.util, json, math, os, re, subprocess, sys, time
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Directories: replaced from the CLI in main().
BUILD, VID, MUSIC, ASSETS, OUT = Path("build"), Path("clips"), Path("music"), Path("assets"), Path("out")
FPS = 60
# Palette: text color, accent (keywords), ember/fire color, background. Overridden by PALETTE in the config.
TEXT, ACCENT, FIRE, BG = (251, 245, 231), (255, 176, 102), (244, 108, 39), (12, 14, 18)
FONT_DISPLAY = FONT_KICKER = FONT_BODY = None  # set from FONTS in the config
SONGS = {}  # beat grids from <build>/songs.json
W = H = S = 0  # set by configure()


def configure(preview):
    global W, H, S
    S = 0.25 if preview else 1.0
    W, H = round(2160 * S), round(3840 * S)


# ----------------------------------------------------------------------------- helpers
def clip01(x): return min(1.0, max(0.0, x))
def ease_out(x): x = clip01(x); return 1 - (1 - x) ** 3
def ease_in(x): x = clip01(x); return x ** 3


def affine(img, z=1.0, dx=0.0, dy=0.0, border=cv2.BORDER_REFLECT101):
    M = np.float32([[z, 0, W / 2 * (1 - z) + dx], [0, z, H / 2 * (1 - z) + dy]])
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
    """Gentle vignette only; color is graded in the ffmpeg decode chain (see LOOK)."""
    return cv2.multiply(img, vignette(), scale=1 / 255)


# Warm "fire" look (default; override LOOK in the config): gentle S curve with deep blacks, teal shadows / fire highlights,
# smart saturation (vibrance protects skin), adaptive sharpening.
LOOK = ",".join([
    "curves=master='0/0 0.06/0.03 0.25/0.22 0.5/0.52 0.8/0.83 0.95/0.94 1/0.98'",  # soft highlight roll-off
    "colorbalance=rs=-0.04:bs=0.05:rm=0.03:bm=-0.02:rh=0.07:gh=0.02:bh=-0.06",
    "vibrance=intensity=0.28",
    "eq=contrast=1.04:saturation=1.05",
    "cas=strength=0.45",
])
FOOD_WARM = "colorbalance=rm=0.05:gm=0.01:bm=-0.05:rh=0.04:bh=-0.04,vibrance=intensity=0.10"  # appetizing grill
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


def clip_gains(key, path, opts, crop, t0, t1):
    """Gains measured per shot on 3 frames of its own source range (10 %, 50 %, 90 %): pans change exposure."""
    if key not in _gains:
        vf = ",".join(x for x in [crop, "scale=540:960", "format=rgb24"] if x)
        frames = []
        for t in (t0 + 0.1 * (t1 - t0), (t0 + t1) / 2, t0 + 0.9 * (t1 - t0)):
            raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", f"{t:.3f}", "-i", str(path),
                                           "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"])
            frames.append(np.frombuffer(raw, np.uint8).reshape(960, 540, 3))
        _gains[key] = match_gains(np.stack(frames))
    return _gains[key]


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
                 cap_frac=None, top=None, fill=None):
        """size: size_frac*W px, or cap height = cap_frac*H (max). yc centers the block, `top` pins its cap-top instead.
        fill: grow the widest line to fill*W (one line for <=10 chars, else a balanced two-line split)."""
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
        self.letters, idx, xl, xr = [], 0, W, 0
        for li, ws in enumerate(lines):
            lw = wlen(f, ws, sp)
            x = (W - lw) / 2
            by = top_base + li * pitch
            xl, xr = min(xl, x), max(xr, x + lw)
            for wi, (w, acc) in enumerate(ws):
                for c in w:
                    adv = f.getlength(c)
                    self.letters.append((self._sprite(f, c, accent if acc else color, size, pad, asc, desc), x, by, idx))
                    x += adv + sp
                    idx += 1
                x += f.getlength(" ") + sp
        self.asc, self.n = asc, idx
        self.top, self.bottom = top_base - cap_h, top_base + (len(lines) - 1) * pitch
        self.span = (xl, xr)
        r = np.random.default_rng(seed + 7)
        t_land = t0 + stagger * idx + 0.22
        self.sparks = [(t_land + r.uniform(0, .18), r.uniform(xl, xr), r.uniform(self.top, self.bottom),
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
        ImageDraw.Draw(g).text((pad, pad), ch, font=f, fill=col + (255,))
        return np.array(Image.alpha_composite(out, g))

    def draw(self, img, tl):
        if tl < self.t0 or tl > self.t_exit + self.exit_dur + 0.05:
            return
        e = clip01((tl - self.t_exit) / self.exit_dur)
        for spr, x, by, idx in self.letters:
            a = ease_out((tl - self.t0 - idx * self.stagger) / self.dur)
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
    """Subtitle chunks: kicker font, text color + accent keywords, thick outline, pop-in 1.15 -> 1.0."""
    POP = 1.15

    def __init__(self, chunks, src_start, yc, size_px=240):
        size = size_px * S * self.POP
        f = font(FONT_KICKER, size)
        sw, pad = max(2, int(round(12 * S * self.POP))), int(0.25 * size)
        asc, desc = f.getmetrics()
        self.chunks = []
        for a, b, text in chunks:
            words = parse_markup(text)
            sp = f.getlength(" ")
            ws = [f.getlength(w) for w, _ in words]
            tw = sum(ws) + sp * (len(words) - 1)
            cw, ch = int(tw + 2 * pad), asc + desc + 2 * pad
            assert (tw + 2 * sw) / self.POP <= 0.96 * W, f"subtitle '{text}' too wide: {tw / self.POP / W:.2f}W"
            shadow = Image.new("L", (cw, ch), 0)
            sd, outl, fill = ImageDraw.Draw(shadow), Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            od, fd = ImageDraw.Draw(outl), ImageDraw.Draw(fill)
            x = pad
            for (w, acc), wl in zip(words, ws):
                sd.text((x, pad + 0.04 * size), w, font=f, fill=200, stroke_width=sw)
                od.text((x, pad), w, font=f, fill=(14, 10, 8, 255), stroke_width=sw, stroke_fill=(14, 10, 8, 255))
                fd.text((x, pad), w, font=f, fill=(ACCENT if acc else TEXT) + (255,))
                x += wl + sp
            base = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
            base.putalpha(shadow.filter(ImageFilter.GaussianBlur(0.03 * size)))
            spr = np.array(Image.alpha_composite(Image.alpha_composite(base, outl), fill))
            self.chunks.append((a - src_start, b - src_start, spr))
        self.yc = yc

    def draw(self, img, tl):
        for ta, tb, spr in self.chunks:
            if ta <= tl < tb:
                k = (1 + (self.POP - 1) * (1 - ease_out((tl - ta) / 0.12))) / self.POP
                h, w = spr.shape[:2]
                s = cv2.resize(spr, (max(1, int(w * k)), max(1, int(h * k))), interpolation=cv2.INTER_AREA)
                blit(img, s, int(W / 2 - s.shape[1] / 2), int(self.yc - s.shape[0] / 2))
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
    def __init__(self, path, crop):
        im = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
        ih, iw = im.shape[:2]
        if crop is None:
            cw = round(ih * 9 / 16); crop = ((iw - cw) // 2, 0, cw, ih)
        x, y, w, h = crop
        assert x >= 0 and y >= 0 and x + w <= iw and y + h <= ih, f"{path}: crop {crop} outside {iw}x{ih}"
        im = cv2.cvtColor(im[y:y + h, x:x + w], cv2.COLOR_BGR2RGB)
        im = cv2.resize(im, (W, H), interpolation=cv2.INTER_AREA if w > W else cv2.INTER_CUBIC)
        small = cv2.resize(im, (540, 960), interpolation=cv2.INTER_AREA)
        self.img = ffgrade(im, color_chain(match_gains(small)))

    def get(self, i): return self.img
    def close(self): pass


def probe_duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


# Per-project data, filled by load_config() from the --config module (see project_example.py).
# CLIPS: name -> (file in the clips dir, ffmpeg input opts, ffmpeg crop filter, allowed (good) source windows)
CLIPS = {}
FOOD_CLIPS = set()     # clips that get the extra appetizing warmth
AMBIENCE_CLIP = None   # CLIPS key whose real sound is the ambience bed when cfg["sfx"] is on
HERO = None            # hero/logo video (on black), resolved against the assets dir
LOGO = (800, 1640, 130, 1190)  # stable logo content bbox (x0, x1, y0, y1) in the 2560x1440 hero source
LOGO_W, GROUP_CY = 0.88, 0.45  # logo width / frame width; vertical center of logo+text group
END_TITLE, DOMAIN = "", ""     # end-card title (markup allowed) and domain line; empty = skipped
HERO_BG = None


def media(name):
    """Resolve a photo name: absolute path as-is, else the clips dir, else the build dir."""
    p = Path(name)
    if p.is_absolute():
        return p
    return next((b / p for b in (VID, BUILD) if (b / p).exists()), VID / p)


class Shot:
    def __init__(self, spec, F0, n):
        self.spec, self.F0, self.n = spec, F0, n
        self.kind = spec["kind"]
        self.speed = spec.get("speed", 1.0)
        self.push = spec.get("push", 0.06)
        self.drift = spec.get("drift", 0.0)
        self.grade = self.kind != "hero"
        self.trans, self.shake = spec.get("trans", "hard"), spec.get("shake", False)
        self.caps, self.sub, self.embers = [], None, None
        if self.kind == "photo":
            self.src = Still(media(spec["file"]), spec.get("crop"))
            self.push = spec.get("push", 0.08)
        elif self.kind == "hero":
            ytop, cw, x0 = self.hero_layout(spec)
            M, hh = round(600 * S), round(1440 * W / cw / 2) * 2
            chain = (f"crop={cw}:1440:{x0}:0,scale={W}:{hh}:flags=lanczos,pad={W}:{H + 2 * M}:0:{ytop + M}:black,crop={W}:{H}:0:{M}")
            self.src = self._ffmpeg(HERO, [], chain, spec["start"], [(0, 6.0)], 1.0)
            self.push = spec.get("push", 0.03)
        else:
            f, opts, crop, good = CLIPS[spec["clip"]]
            ch = f"{crop}," if crop else ""
            t1 = spec["start"] + self.n / FPS * self.speed  # this shot's own source range, not the clip's
            gains = clip_gains((spec["clip"], spec["start"]), VID / f, opts, crop, spec["start"], t1)
            color = color_chain(gains, food=spec["clip"] in FOOD_CLIPS)
            self.src = self._ffmpeg(VID / f, opts, f"{ch}scale={W}:{H}:flags={'lanczos' if S == 1 else 'area'},{color}",
                                    spec["start"], good, self.speed)
        self.setup_text(spec, n)
        if spec.get("embers"):
            self.embers = Embers(spec["embers"], seed=F0 + 1)

    def _ffmpeg(self, path, opts, chain, start, windows, speed):
        need_src = self.n / FPS * speed
        win = [w for w in windows if w[0] - 1e-3 <= start and start + need_src <= w[1] + 5e-3]
        assert win, f"{path.name}: source range {start:.3f}-{start + need_src:.3f} not inside good windows {windows}"
        assert start + need_src <= probe_duration(path) + 5e-3, f"{path.name}: range exceeds file duration"
        avail = win[0][1] - start
        length = min(avail, (self.n + 8) / FPS * speed)  # +8 frames covers the whip/zoom post-roll
        vf = f"setpts=(PTS-STARTPTS)/{speed},fps={FPS},{chain},format=rgb24"
        cmd = ["ffmpeg", "-v", "error", *opts, "-ss", f"{start:.4f}", "-t", f"{length:.4f}", "-i", str(path), "-an", "-vf", vf,
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        return Reader(cmd, self.n)

    def hero_layout(self, spec):
        """Logo + tagline (+ domain) as one group centered at GROUP_CY. Returns (logo y offset, crop width, crop x) for the source."""
        x0s, x1s, y0s, y1s = LOGO
        cw = round((x1s - x0s) / LOGO_W)
        x0 = round((x0s + x1s) / 2 - cw / 2)
        k = W / cw
        h_logo = (y1s - y0s) * k
        caps = [Caption(text, kw.pop("font", FONT_DISPLAY), 0.15, 0, t0, seed=self.F0 + j, top=0.0, **kw)
                for j, (t0, text, kw) in enumerate((t0, tx, dict(kw)) for t0, tx, kw in spec["hero_texts"])]
        gaps = [0.035 * H, 0.03 * H]
        gh = h_logo + sum(g + (c.bottom - c.top) for g, c in zip(gaps, caps))
        gt = max(GROUP_CY * H - gh / 2, 0.03 * H)
        y = gt + h_logo
        for g, c in zip(gaps, caps):
            c.shift(y + g - c.top)
            y = c.bottom
        self.caps += caps
        self.group = (gt / H, y / H)
        return round(gt - y0s * k), cw, x0

    def setup_text(self, spec, n):
        dur = n / FPS
        t_exit = dur - 0.30
        if spec.get("title"):
            t0 = spec.get("tdelay", 0.15)
            top = 0.205 if spec.get("kicker") else 0.18  # title cap-top; kicker sits above, all inside the 15%-72% safe zone
            c = Caption(spec["title"], FONT_DISPLAY, 0.15, 0, t0, t_exit=t_exit, sparks=16, seed=self.F0, fill=0.85, cap_frac=0.115, top=top * H)
            self.caps.append(c)
            if spec.get("kicker"):
                k = Caption(spec["kicker"], FONT_KICKER, 0.058, 0, t0 - 0.08, t_exit=t_exit, color=ACCENT, top=c.top - 0.085 * W,
                            stagger=0.012, spacing_em=0.16, dur=0.3, rise_em=0.4)
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
        ov = None
        if self.embers or any(c.sparks for c in self.caps):
            ov = np.zeros_like(img)
            if self.embers: self.embers.draw(ov, t)
            for c in self.caps:
                if c.sparks: c.draw_sparks(ov, tl)
            img = composite_particles(img, ov)
        for c in self.caps:
            c.draw(img, tl)
        if self.sub:
            self.sub.draw(img, tl)
        return img

    def close(self): self.src.close()


# ----------------------------------------------------------------------------- timeline / audio
TRANS_WIN = {"hard": (0, 0), "flash": (0, 0), "whip": (4, 4), "zoom": (5, 5)}


def plan(cfg):
    key, _, st = cfg["song"]
    rel = [b - st for b in SONGS[key]["beats"] if b >= st - 0.05]
    rel[0] = max(rel[0], 0.0)
    shots, a, bi = [], 0, 0
    for sp in cfg["shots"]:
        if "beats" in sp:
            bi += sp["beats"]; b = round(rel[bi] * FPS)
        elif "dur" in sp:
            b = a + round(sp["dur"] * FPS)
        else:  # "after": END card running until the first beat >= start + after
            b = round(rel[bisect.bisect_left(rel, a / FPS + sp["after"])] * FPS)
        shots.append((sp, a, b))
        a = b
    return rel, shots


def build_audio(out, cfg, total, v_start, v_end, sfx_wav):
    key, song_file, st = cfg["song"]
    args = ["-ss", f"{st}", "-t", f"{total + 0.5:.3f}", "-i", str(MUSIC / song_file)]
    si = 2 if cfg.get("voice") else 1  # input index of the SFX track
    sfx = f"[{si}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f}[fx]"
    fade = f"afade=t=out:st={total - 1.0:.3f}:d=1.0"
    gain, limit = f"volume={cfg['gain_db']}dB", "alimiter=limit=0.84:level=false"
    base = f"aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},{gain}"
    vf = []
    if cfg.get("voice"):
        a0, a1 = v_start, v_end
        duck = f"volume='1-0.75*(min(1,max(0,(t-{a0:.3f})/0.3))-min(1,max(0,(t-{a1:.3f})/0.6)))':eval=frame"
        vf.append(f"[0:a]{base},{duck},{fade}[mus]")
        args += ["-i", str(BUILD / cfg["voice"])]
        vf.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{v_end - v_start:.3f},volume={cfg['voice_gain_db']}dB,"
                  f"highpass=f=90,afade=t=in:d=0.08,afade=t=out:st={v_end - v_start - 0.25:.3f}:d=0.25[vo]")
        vf.append(f"anullsrc=r=48000:cl=stereo:d={v_start:.3f}[sil];[sil][vo]concat=n=2:v=0:a=1[vpad]")
        mix = "[mus][vpad]amix=inputs=2"
        if sfx_wav:
            args += ["-i", str(sfx_wav)]
            vf.append(sfx)
            mix = "[mus][vpad][fx]amix=inputs=3"
        vf.append(f"{mix}:normalize=0:duration=first,{limit},asetpts=N/SR/TB,atrim=0:{total:.3f}[a]")
    else:
        if sfx_wav:
            args += ["-i", str(sfx_wav)]
            vf.append(sfx)
            vf.append(f"[0:a]{base},{fade}[mus];[mus][fx]amix=inputs=2:normalize=0:duration=first,{limit},"
                      f"asetpts=N/SR/TB,atrim=0:{total:.3f}[a]")
        else:
            vf.append(f"[0:a]{base},{fade},{limit},asetpts=N/SR/TB,atrim=0:{total:.3f}[a]")
    subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", *args, "-filter_complex", ";".join(vf), "-map", "[a]",
                    "-c:a", "aac", "-b:a", "256k", str(out)], check=True)


# ----------------------------------------------------------------------------- render
def render_reel(name, cfg, preview, audio_only=False):
    global HERO_BG
    HERO_BG = np.full((H, W, 3), BG, np.uint8)
    rel, plan_ = plan(cfg)
    total = plan_[-1][2]
    tsec = total / FPS
    out_dir = BUILD / "preview" if preview else OUT
    out_dir.mkdir(parents=True, exist_ok=True)
    final, tmp_v, tmp_a = out_dir / f"{name}.mp4", BUILD / f"_{name}_v.mp4", BUILD / f"_{name}_a.m4a"
    sp_last = [p for p in plan_ if p[0].get("voice_shot")]
    v_start = sp_last[0][1] / FPS if sp_last else 0
    v_end = sp_last[0][2] / FPS if sp_last else 0
    print(f"== {name}: {tsec:.3f}s ({total} frames) W={W}x{H}", flush=True)
    for sp, a, b in plan_:
        print(f"   {a / FPS:7.3f}s  {sp['kind']:5s} {sp.get('clip') or Path(str(sp.get('file', 'hero'))).name:26s} "
              f"{(b - a) / FPS:5.2f}s  trans={sp.get('trans', '-')}{'+shake' if sp.get('shake') else ''}", flush=True)
    # SFX are opt-in (cfg["sfx"]=True): generic synthesized effects tend to clash with music-driven reels.
    sfx_wav = None
    if cfg.get("sfx"):
        from sfx import build_sfx  # lazy: needs scipy
        amb = (AMBIENCE_CLIP, CLIPS[AMBIENCE_CLIP][0]) if AMBIENCE_CLIP else None
        sfx_wav = build_sfx(plan_, FPS, tsec, BUILD / f"_{name}_sfx.wav", VID, (v_start, v_end), amb)
    build_audio(tmp_a, cfg, tsec, v_start, v_end, sfx_wav)
    if audio_only:
        return
    shots = [Shot(sp, a, b - a) for sp, a, b in plan_]
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
            # boundary effects (global): flash+flare, shake
            for k, (ty, Fk, pre, post, d) in bwin.items():
                j = f - Fk
                if 0 <= j < 18 and ty == "flash":
                    img = flare(img, (1 - j / 18) ** 2)
                    if j < 6: img = cv2.addWeighted(img, 1 - 0.85 * (1 - j / 6), white, 0.85 * (1 - j / 6), 0)
                if 0 <= j < 6 and shots[k].shake:
                    amp = 0.02 * W * (1 - j / 6)
                    img = affine(img, 1.0, rng.uniform(-amp, amp), rng.uniform(-amp, amp))
            if f < 18:  # intro: flare + soft flash on beat 0
                img = flare(img, (1 - f / 18) ** 2)
                if f < 8: img = cv2.addWeighted(img, 1 - 0.5 * (1 - f / 8), white, 0.5 * (1 - f / 8), 0)
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


# ----------------------------------------------------------------------------- project config
def add_branding_text(rel, plan_):
    """Intro tagline on beat `tag_beat`; end card title + domain. Needs beat times, so done after plan()."""
    for sp, a, b in plan_:
        if sp.get("tagline"):
            sp["hero_texts"] = [(rel[sp["tag_beat"]] - a / FPS, sp["tagline"], dict(sparks=22, cap_frac=0.06, min_frac=0.8))]
        if sp.get("end"):
            texts = []
            if END_TITLE:
                texts.append((0.45, END_TITLE, dict(sparks=22, cap_frac=0.06, min_frac=0.7)))
            if DOMAIN:
                texts.append((1.30, DOMAIN, dict(font=FONT_BODY, cap_frac=0.025, stagger=0.02, spacing_em=0.1, color=TEXT)))
            sp["hero_texts"] = texts


_plan = plan
def plan(cfg):  # noqa: F811 - wraps the base planner to inject branding captions
    rel, p = _plan(cfg)
    add_branding_text(rel, p)
    return rel, p


def load_config(path):
    """Import the project config module and copy its settings into this module. Returns its REELS dict."""
    spec = importlib.util.spec_from_file_location("reel_project", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    g = globals()
    for k in ("CLIPS", "FOOD_CLIPS", "AMBIENCE_CLIP", "LOGO", "LOGO_W", "GROUP_CY", "END_TITLE", "DOMAIN", "LOOK", "FOOD_WARM"):
        if hasattr(mod, k):
            g[k] = getattr(mod, k)
    pal = getattr(mod, "PALETTE", {})
    for k, name in (("text", "TEXT"), ("accent", "ACCENT"), ("fire", "FIRE"), ("bg", "BG")):
        if k in pal:
            g[name] = tuple(pal[k])
    fonts = mod.FONTS  # relative names resolve against the assets dir; absolute paths pass through
    g["FONT_DISPLAY"], g["FONT_KICKER"], g["FONT_BODY"] = (ASSETS / fonts[k] for k in ("display", "kicker", "body"))
    g["HERO"] = ASSETS / mod.HERO
    return mod.REELS


def main():
    env = os.environ.get
    ap = argparse.ArgumentParser(description="Render beat-synced branded vertical reels from a project config.")
    ap.add_argument("names", nargs="*", help="reel names from the config (default: all)")
    ap.add_argument("--config", default=env("REEL_CONFIG", str(Path(__file__).with_name("project_example.py"))),
                    help="project config module (default: project_example.py next to this script)")
    ap.add_argument("--build-dir", default=env("REEL_BUILD_DIR", "./build"), help="scratch dir with songs.json; previews go to <build>/preview")
    ap.add_argument("--videos", default=env("REEL_VIDEOS", "./clips"), help="dir with the source clips and photos")
    ap.add_argument("--music", default=env("REEL_MUSIC", "./music"), help="dir with the song files you provide")
    ap.add_argument("--assets", default=env("REEL_ASSETS", "./assets"), help="dir with fonts and the hero video")
    ap.add_argument("--out", default=env("REEL_OUT", "./out"), help="dir for the 4K finals")
    ap.add_argument("--preview", action="store_true", help="540x960 fast preview instead of 4K")
    ap.add_argument("--audio-only", action="store_true", help="only build the audio track")
    a = ap.parse_args()
    global BUILD, VID, MUSIC, ASSETS, OUT
    BUILD, VID, MUSIC, ASSETS, OUT = (Path(x) for x in (a.build_dir, a.videos, a.music, a.assets, a.out))
    songs = BUILD / "songs.json"
    if not songs.exists():
        sys.exit(f"{songs} not found: run analyze_songs.py first")
    SONGS.update(json.load(open(songs, encoding="utf-8")))
    reels = load_config(a.config)
    configure(a.preview)
    for n in (a.names or reels):
        render_reel(n, reels[n], a.preview, a.audio_only)


if __name__ == "__main__":
    main()
