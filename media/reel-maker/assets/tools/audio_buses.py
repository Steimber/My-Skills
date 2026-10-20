"""Audio reconnaissance of one reel: rebuild its buses with the engine's own graph and measure the music / voice balance.

    python audio_buses.py --config my_project.py --build-dir build --music music --videos clips reel4_voice [--out build/buses]

Writes <out>/<reel>_{music,voice,song}.wav (32-bit float, 48 kHz, BEFORE the master limiter: music bus after duck/bed, voice bus after
its chain, and the plain song section at the reel's gain) and prints, for the speech section:
  * integrated loudness of each bus (BS.1770 K-weighting) and the voice - music difference in LU,
  * per band (100-500, 500-1k, 1-4k, 4-8k Hz) voice minus music RMS in dB, and the 6 weakest 0.5 s windows in the 1-4 kHz speech band
    (the band that carries consonants; negative = the music is louder than the voice there),
  * mono-fold loss of the summed buses and how often / how far the master limiter (limit from LIMITER) would act.
Use it to set bed_db, carve_db and voice_lufs per song instead of guessing; then confirm on the final mix with verify_voice.py.
"""
import argparse, re, subprocess, sys
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import butter, lfilter, sosfilt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FS = 48000


def kweight(x):
    b1 = [1.53512485958697, -2.69169618940638, 1.19839281085285]; a1 = [1, -1.69065929318241, 0.73248077421585]
    b2 = [1.0, -2.0, 1.0]; a2 = [1.0, -1.99004745483398, 0.99007225036621]
    return lfilter(b2, a2, lfilter(b1, a1, x, axis=0), axis=0)


def integrated(x):
    """ITU-R BS.1770 integrated loudness (LUFS) of a (n, 2) array at 48 kHz: 400 ms blocks, 75 % overlap, absolute + relative gate."""
    win, hop = int(0.4 * FS), int(0.1 * FS)
    ms = (kweight(x) ** 2).sum(1)
    c = np.concatenate([[0], np.cumsum(ms)])
    idx = np.arange((len(ms) - win) // hop + 1) * hop
    z = (c[idx + win] - c[idx]) / win
    lk = lambda v: -0.691 + 10 * np.log10(np.maximum(v, 1e-12))
    g = z[lk(z) > -70]
    if not len(g):
        return -70.0
    rel = lk(g.mean()) - 10
    return float(lk(z[(lk(z) > -70) & (lk(z) > rel)].mean()))


def db(a): return 20 * np.log10(np.maximum(a, 1e-12))


def band(x, lo, hi):
    return sosfilt(butter(4, [lo, hi], btype="band", fs=FS, output="sos"), x, axis=0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="reel names (default: all with speech)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--videos", default="./clips")
    ap.add_argument("--music", default="./music")
    ap.add_argument("--assets", default="./assets")
    ap.add_argument("--out", help="dir for the bus wavs (default <build>/buses)")
    a = ap.parse_args()
    import reel_engine as E
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    out = Path(a.out) if a.out else Path(a.build_dir) / "buses"
    out.mkdir(parents=True, exist_ok=True)
    limit = float(re.search(r"limit=([\d.]+)", E.LIMITER).group(1))
    for name in a.names or [n for n, c in reels.items() if c.get("voice")]:
        cfg = reels[name]
        _, plan_ = E.plan(cfg)
        total = plan_[-1][2] / E.FPS
        v0, v1 = E.voice_window(cfg, plan_)
        args, vf, labels = E.audio_buses(cfg, total, v0, v1)
        key, song_file, st = cfg["song"]
        vf.append(f"[0:a]{E.music_base(cfg, total)},afade=t=out:st={total - E.FADE_OUT:.3f}:d={E.FADE_OUT}[song]")  # reference: no duck, no bed
        paths = {"mus": out / f"{name}_music.wav", "vpad": out / f"{name}_voice.wav", "song": out / f"{name}_song.wav"}
        cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *args, "-filter_complex", ";".join(vf)]
        for lab in [l.strip("[]") for l in labels if l != "[fx]"] + ["song"]:
            cmd += ["-map", f"[{lab}]", "-c:a", "pcm_f32le", "-ar", str(FS), str(paths[lab])]
        subprocess.run(cmd, check=True)
        m, _ = sf.read(str(paths["mus"]), dtype="float64")
        print(f"\n== {name}: song {key} from {st}s, {total:.1f}s")
        print(f"   music bus {integrated(m):.1f} LUFS overall")
        if "vpad" not in paths or not paths["vpad"].exists():
            continue
        v, _ = sf.read(str(paths["vpad"]), dtype="float64")
        s_, _ = sf.read(str(paths["song"]), dtype="float64")
        n = min(len(m), len(v))
        m, v, s_ = m[:n], v[:n], s_[:n]
        a0, a1 = (cfg["_vt"]["v_start"], cfg["_vt"]["v_end"]) if cfg.get("_vt") else (v0, v1)
        sl = slice(int((a0 + 0.6) * FS), int(a1 * FS))
        Lv, Lm, Ls = integrated(v[sl]), integrated(m[sl]), integrated(s_[sl])
        print(f"   speech {a0:.2f}-{a1:.2f}s: voice {Lv:.1f} LUFS, music bus {Lm:.1f}, voice - music {Lv - Lm:+.1f} LU (unducked song {Ls:.1f})")
        for lo, hi in [(100, 500), (500, 1000), (1000, 4000), (4000, 8000)]:
            bv, bm = band(v[sl], lo, hi), band(m[sl], lo, hi)
            rv, rm = db(np.sqrt((bv ** 2).mean())), db(np.sqrt((bm ** 2).mean()))
            print(f"     {lo:>4}-{hi:<4} Hz: voice {rv:6.1f} dB  music {rm:6.1f} dB  V-M {rv - rm:+5.1f} dB")
        bv, bm = band(v[sl], 1000, 4000), band(m[sl], 1000, 4000)
        hop = int(0.5 * FS)
        starts = list(range(0, len(bv) - hop, hop))
        rv = np.array([db(np.sqrt((bv[i:i + hop] ** 2).mean())) for i in starts])
        rm = np.array([db(np.sqrt((bm[i:i + hop] ** 2).mean())) for i in starts])
        act = rv > np.percentile(rv, 90) - 15  # windows where the voice is actually talking (skip pauses)
        wins = [(round(a0 + 0.6 + i / FS, 1), round(float(d), 1)) for i, d, ok in zip(starts, rv - rm, act) if ok]
        print("   weakest 0.5 s windows (1-4k voice minus music, dB):", sorted(wins, key=lambda z: z[1])[:6], "| median", round(float(np.median([w[1] for w in wins])), 1))
        mix = m + v
        mono = mix.mean(1)
        print(f"   mono-fold loss {10 * np.log10((mono ** 2).mean() / (((mix ** 2).sum(1)) / 2).mean() + 1e-12):+.2f} dB | summed buses: "
              f"peak {db(np.abs(mix).max()):.1f} dBFS, {int((np.abs(mix).max(1) > limit).sum())} samples above the limiter ({limit}), "
              f"max reduction {db(np.abs(mix).max() / limit):.1f} dB")


if __name__ == "__main__":
    main()
