"""Do the cuts land on the music? Compare every cut with the percussive onsets / kick hits of the song section the reel uses.

    python rhythm_check.py --config my_project.py --build-dir build --music music --videos clips [reel names]

Per reel: fits an ideal beat grid (period + phase) to the percussive onset envelope, compares songs.json beats with it, and lists
every cut with its offset to the nearest grid beat, percussive onset and kick (ms; + = the hit comes after the cut). Summary line:
`suggested BEAT_LAG`. librosa's tracker usually reports beats ~15-35 ms late relative to the audible hit; the engine cuts BEAT_LAG
earlier than the json beat (default 0.020). Change the config value only when the median over SEVERAL songs agrees; a cut that
precedes the hit by 0-30 ms feels tight, a cut after the hit feels late. Large offsets with a stable sign on one song = wrong
song start (the section starts between beats) or a tempo drift: refit by `analyze_songs.py` on a trimmed file.
"""
import argparse, subprocess, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
SR, HOP = 22050, 64


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="reel names (default: all)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--videos", default="./clips")
    ap.add_argument("--music", default="./music")
    ap.add_argument("--assets", default="./assets")
    a = ap.parse_args()
    import librosa
    import reel_engine as E
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    wdir = Path(a.build_dir) / "rhythm"
    wdir.mkdir(parents=True, exist_ok=True)
    lags = []
    for name in a.names or list(reels):
        cfg = reels[name]
        rel, shots = E.plan(cfg)
        key, fname, st = cfg["song"]
        tot = shots[-1][2] / E.FPS
        wav = wdir / f"{key}_{st}.wav"
        if not wav.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(st), "-t", f"{tot + 1:.2f}", "-i", str(E.MUSIC / fname), "-ac", "1", "-ar", str(SR), str(wav)], check=True)
        y, _ = librosa.load(str(wav), sr=SR)
        yh, yp = librosa.effects.hpss(y)
        oenv = librosa.onset.onset_strength(y=yp, sr=SR, hop_length=HOP, aggregate=np.median, fmax=8000)
        t = librosa.frames_to_time(np.arange(len(oenv)), sr=SR, hop_length=HOP)
        S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP))
        fr = librosa.fft_frequencies(sr=SR, n_fft=2048)
        lo = S[(fr > 30) & (fr < 150)].sum(0)
        kick = np.maximum(np.diff(lo, prepend=lo[0]), 0)
        pk = librosa.util.peak_pick(oenv, pre_max=8, post_max=8, pre_avg=24, post_avg=24, delta=0.35 * np.std(oenv), wait=12)
        onsets = t[pk]
        kp = librosa.util.peak_pick(kick, pre_max=8, post_max=8, pre_avg=24, post_avg=24, delta=0.5 * np.std(kick), wait=20)
        kicks = t[kp]
        P0 = 60 / E.SONGS[key]["tempo"]
        sm = np.convolve(oenv, np.hanning(7), mode="same")
        best = None
        for P in np.linspace(P0 * 0.985, P0 * 1.015, 61):  # grid fit: period + phase maximising the smoothed onset sum
            for ph in np.arange(0, P, 0.004):
                tt = np.arange(ph, tot - 0.1, P)
                idx = np.round(tt / (HOP / SR)).astype(int); idx = idx[idx < len(sm)]
                sc = sm[idx].mean()
                if best is None or sc > best[0]:
                    best = (sc, P, ph)
        _, P, ph = best
        grid = np.arange(ph, tot, P)
        raw = np.array([b - st for b in E.SONGS[key]["beats"] if 0 <= b - st < tot])  # json beats before BEAT_LAG
        off = np.array([(b - grid[np.argmin(abs(grid - b))]) * 1000 for b in raw])
        d = np.array([(onsets[np.argmin(abs(onsets - b))] - b) * 1000 for b in raw if len(onsets)])
        d = d[np.abs(d) < 100]
        print(f"\n== {name}: song {key} from {st}s | fitted period {P * 1000:.2f} ms ({60 / P:.2f} BPM, json {E.SONGS[key]['tempo']:.2f}), phase {ph * 1000:.0f} ms")
        print(f"   json beats vs ideal grid: mean {off.mean():+.0f} ms, std {off.std():.0f} ms | onset - json beat: median {np.median(d):+.0f} ms over {len(d)} beats")
        lags.append(-float(np.median(d)) / 1000)
        print("   cut      trans   vs engine beat | vs grid | nearest perc. onset | nearest kick")
        for k, (sp, f0, f1) in enumerate(shots[1:], 1):
            bt = f0 / E.FPS
            jb = rel[int(np.argmin([abs(x - bt) for x in rel]))]
            go = (bt - grid[int(np.argmin(abs(grid - bt)))]) * 1000
            on = onsets[np.argmin(abs(onsets - bt))] if len(onsets) else np.nan
            kk = kicks[np.argmin(abs(kicks - bt))] if len(kicks) else np.nan
            print(f"   {bt:7.3f}s {sp.get('trans', '-'):6s} {1000 * (bt - jb):+6.0f} ms      {go:+6.0f} ms  {1000 * (on - bt):+6.0f} ms           {1000 * (kk - bt):+6.0f} ms")
    if lags:
        print(f"\nsuggested BEAT_LAG (median over {len(lags)} reel(s)): {np.median(lags):.3f} s (config value now {E.BEAT_LAG:.3f})")


if __name__ == "__main__":
    main()
