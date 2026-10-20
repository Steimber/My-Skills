"""Verify finished reels: A/V durations, clean decode, audio packet gaps, loudness, true peak, mono-fold loss.

    python verify_media.py out/reel1.mp4 out/reel2.mp4            # exit code 1 if any check fails
    python verify_media.py out/*.mp4 --lufs -14 --lufs-tol 1.5 --max-dur 59

Checks (PASS/FAIL): |video - audio duration| <= 0.05 s, `ffmpeg -v error -f null` prints nothing, largest gap between audio packet
timestamps <= 0.03 s (a real hole in the audio, not AAC's 21 ms frame), integrated loudness within --lufs +- tol, true peak
<= -1 dBTP, no stereo cancellation (mono-fold loss <= 1.5 dB: phones and speakers often sum to mono). Reports resolution / fps.
"""
import argparse, json, re, subprocess, sys
import numpy as np


def run(*a):
    return subprocess.run(a, capture_output=True, text=True)


def mono_fold(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "2", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2).astype(np.float64)
    avg = ((x[:, 0] ** 2).mean() + (x[:, 1] ** 2).mean()) / 2
    mono = (x.mean(1) ** 2).mean()
    return 10 * np.log10(mono / avg + 1e-12), float(np.corrcoef(x[:, 0], x[:, 1])[0, 1]) if x.std() > 0 else 1.0


def check(path, a):
    pr = json.loads(run("ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration", "-of", "json", path).stdout)["streams"]
    v = next(s for s in pr if s["codec_type"] == "video")
    au = next((s for s in pr if s["codec_type"] == "audio"), None)
    ok = True
    notes = []
    if au is None:
        print(f"{path}: NO AUDIO STREAM"); return False
    dd = abs(float(v["duration"]) - float(au["duration"]))
    dec = run("ffmpeg", "-v", "error", "-i", path, "-f", "null", "-").stderr.strip()
    pk = [float(x.strip(",")) for x in run("ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "packet=pts_time", "-of", "csv=p=0", path).stdout.split()]
    gap = max(np.diff(pk)) if len(pk) > 1 else 0.0
    e = run("ffmpeg", "-nostats", "-i", path, "-af", "ebur128=peak=true", "-f", "null", "-").stderr
    summ = e[e.rindex("Summary"):]
    I = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1))
    TP = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ).group(1))
    fold, corr = mono_fold(path)
    for name, cond, val in (("A/V duration", dd <= 0.05, f"diff={dd:.3f}s"), ("decode", not dec, "clean" if not dec else "ERR " + dec[:80]),
                            ("audio gap", gap <= 0.03, f"max gap={gap:.4f}s"), ("loudness", abs(I - a.lufs) <= a.lufs_tol, f"{I:.1f} LUFS"),
                            ("true peak", TP <= -1.0, f"{TP:.1f} dBTP"), ("mono fold", fold >= -1.5, f"{fold:+.2f} dB (L/R corr {corr:+.2f})")):
        ok &= bool(cond)
        notes.append(f"{name}={val}{'' if cond else ' FAIL'}")
    d = float(v["duration"])
    if a.max_dur and d > a.max_dur:
        ok = False; notes.append(f"duration {d:.1f}s > {a.max_dur} FAIL")
    print(f"{'PASS' if ok else 'FAIL'} {path.replace(chr(92), '/').split('/')[-1]}: {v['width']}x{v['height']} {v['r_frame_rate']} v={d:.3f}s a={float(au['duration']):.3f}s | " + " | ".join(notes))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--lufs", type=float, default=-14.0, help="target integrated loudness (default -14)")
    ap.add_argument("--lufs-tol", type=float, default=1.5)
    ap.add_argument("--max-dur", type=float, default=0.0, help="fail above this duration in seconds (0 = off)")
    a = ap.parse_args()
    res = [check(f, a) for f in a.files]
    sys.exit(0 if all(res) else 1)


if __name__ == "__main__":
    main()
