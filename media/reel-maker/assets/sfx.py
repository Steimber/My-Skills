"""Synthesized, license-free sound design for the reel engine: whooshes, impacts, risers, fire ignite,
title sparkles, plus an optional real ambience bed taken from one of your own clips. Builds one stereo
48 kHz track aligned to the cut plan. Opt-in: reels only call this when their config sets sfx=True."""
import subprocess
import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
RNG = np.random.default_rng(7)


def _env(n, attack, release_shape=3.0):
    """Rise over `attack` (0..1 of length), then a curved decay to 0."""
    t = np.linspace(0, 1, n, endpoint=False)
    a = max(attack, 1e-3)
    return np.where(t < a, (t / a) ** 2, (1 - (t - a) / (1 - a)) ** release_shape)


def _swept_noise(n, f0, f1, f2, q=1.2):
    """Band-passed noise whose center goes f0 -> f1 (peak) -> f2, overlap-added in short blocks."""
    noise = RNG.standard_normal(n + 4096)
    out, blk, hop = np.zeros(n), 1024, 512
    win = np.hanning(blk)
    for s in range(0, n, hop):
        x = s / max(n - 1, 1)
        fc = f0 * (f1 / f0) ** (x / 0.6) if x < 0.6 else f1 * (f2 / f1) ** ((x - 0.6) / 0.4)
        lo, hi = max(fc / (1 + 1 / q), 30), min(fc * (1 + 1 / q), SR / 2 - 100)
        sos = butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        seg = sosfilt(sos, noise[s:s + blk])  # per-block filter; Hann overlap-add hides block edges
        e = min(blk, n - s)
        out[s:s + e] += (seg[:e] * win[:e])
    return out / (np.abs(out).max() + 1e-9)


def _pan(mono, p0, p1):
    """Equal-power pan moving from p0 to p1 (-1 left .. +1 right)."""
    p = np.linspace(p0, p1, len(mono))
    ang = (p + 1) * np.pi / 4
    return np.stack([mono * np.cos(ang), mono * np.sin(ang)], 1)


def whoosh(d=0.42, direction=1):
    n = int(d * SR)
    m = _swept_noise(n, 350, 2600, 700) * _env(n, 0.62, 2.2)
    return _pan(m, -0.7 * direction, 0.7 * direction)


def boom(d=0.9, f0=95, f1=38):
    n = int(d * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * np.cumsum(f1 + (f0 - f1) * np.exp(-t / 0.08)) / SR
    body = np.sin(ph) * np.exp(-t / 0.28)
    click = np.zeros(n); k = int(0.006 * SR)
    click[:k] = sosfilt(butter(2, 2000, "high", fs=SR, output="sos"), RNG.standard_normal(k)) * np.linspace(1, 0, k)
    m = 0.9 * body + 0.35 * click
    return _pan(m / np.abs(m).max(), 0, 0)


def crack(d=0.16):
    n = int(d * SR)
    m = sosfilt(butter(2, 1800, "high", fs=SR, output="sos"), RNG.standard_normal(n)) * np.exp(-np.arange(n) / SR / 0.03)
    return _pan(m / np.abs(m).max(), 0, 0)


def punch(d=0.22):
    n = int(d * SR)
    t = np.arange(n) / SR
    m = np.sin(2 * np.pi * np.cumsum(60 + 70 * np.exp(-t / 0.03)) / SR) * np.exp(-t / 0.07)
    return _pan(m / np.abs(m).max(), 0, 0)


def riser(d=0.38):
    n = int(d * SR)
    m = _swept_noise(n, 250, 3500, 5500) * np.linspace(0, 1, n) ** 2.2
    return _pan(m, 0, 0)


def ignite(d=1.3):
    n = int(d * SR)
    body = _swept_noise(n, 180, 1800, 600, q=0.8) * _env(n, 0.18, 1.6)
    crackle = np.zeros(n)
    for _ in range(70):  # fire crackles
        p, k = RNG.integers(0, n - 400), RNG.integers(60, 300)
        crackle[p:p + k] += RNG.standard_normal(k) * np.exp(-np.arange(k) / (k / 4)) * RNG.uniform(0.2, 1)
    crackle = sosfilt(butter(2, 1500, "high", fs=SR, output="sos"), crackle) * _env(n, 0.1, 1.2)
    m = body + 0.35 * crackle / (np.abs(crackle).max() + 1e-9)
    return _pan(m / np.abs(m).max(), -0.3, 0.3)


def sparkle(d=0.5):
    n = int(d * SR)
    t = np.arange(n) / SR
    m = np.zeros(n)
    for i in range(5):
        st = int(i * 0.045 * SR)
        f = RNG.uniform(2400, 5200)
        tt = t[: n - st]
        m[st:] += np.sin(2 * np.pi * f * tt) * np.exp(-tt / 0.06) * (0.8 ** i)
    return _pan(m / np.abs(m).max(), -0.4, 0.4)


def ambience_bed(path, src_start, dur):
    """Real ambient sound of a clip at real speed (even when the picture is slow motion). Check it has no speech."""
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-ss", f"{src_start:.3f}", "-t", f"{dur:.3f}",
                                   "-i", str(path), "-vn", "-ac", "2", "-ar", str(SR),
                                   "-af", "highpass=f=300", "-f", "f32le", "-"])
    a = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
    a /= np.abs(a).max() + 1e-9
    f = min(len(a) // 4, int(0.25 * SR))
    ramp = np.linspace(0, 1, f)[:, None]
    a[:f] *= ramp; a[-f:] *= ramp[::-1]
    return a


def db(x): return 10 ** (x / 20)


def build_sfx(plan_, fps, total, out_wav, vid_dir, voice=(0.0, 0.0), ambience=None):
    """plan_: [(spec, first_frame, end_frame)]. ambience: (clip key, file name in vid_dir) or None. Returns the path of a stereo 48 kHz WAV of length `total`."""
    track = np.zeros((int(total * SR) + SR, 2))

    def put(clip, t, gain_db):
        i = int(round(t * SR))
        if i < 0: clip, i = clip[-i:], 0
        e = min(len(track) - i, len(clip))
        if e > 0: track[i:i + e] += clip[:e] * db(gain_db)

    wdir = 1
    v0, v1 = voice
    for k, (sp, a, b) in enumerate(plan_):
        t = a / fps
        if k == 0 and sp["kind"] == "hero":
            put(ignite(), 0.0, -2); put(boom(1.1), 0.0, -2)
        if k > 0:
            ty = sp.get("trans", "hard")
            if ty == "whip":
                w = whoosh(direction=wdir); put(w, t - 0.62 * len(w) / SR, 0); wdir = -wdir
            elif ty == "flash":
                put(boom(), t, -2); put(crack(), t, -8)
            elif ty == "zoom":
                r = riser(); put(r, t - len(r) / SR, -4); put(boom(0.7, 110, 45), t, -3)
            else:
                put(punch(), t, -2)
            if sp.get("shake"):
                put(boom(0.5, 70, 35), t, -5)
            if sp.get("end"):
                put(ignite(1.0), t, -6)
        for t0, *_ in sp.get("hero_texts", []):
            put(sparkle(), t + t0, -12)
        if sp.get("title"):
            put(sparkle(), t + sp.get("tdelay", 0.15), -11)
        if ambience and sp.get("clip") == ambience[0]:
            dur = (b - a) / fps
            put(ambience_bed(vid_dir / ambience[1], sp["start"], dur + 0.2), t - 0.05, -8)

    track = track[: int(total * SR)]
    if v1 > v0:  # keep the testimonial clean: SFX dip 10 dB while he talks (transition hit stays)
        g = np.ones(len(track))
        i0, i1 = int((v0 + 0.25) * SR), int(v1 * SR)
        g[i0:i1] = db(-10)
        track *= g[:, None]
    peak = np.abs(track).max()
    if peak > db(-1):  # master limiter handles the rest
        track *= db(-1) / peak
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f64le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s16le", str(out_wav)], input=track.astype(np.float64).tobytes(), check=True)
    return out_wav
