"""Before/after test of the warm color look: per-clip match (exposure + white balance) then the look chain.

    python grade_before_after.py --videos clips clip_01.mp4@3.0 clip_03.mp4@5.0 clip_09.mp4@5.0:crop=ih*9/16:ih:1159:0

Sample syntax: file@seconds[:crop]. crop = an ffmpeg crop filter, `none`, or omitted for the 9:16 center crop.
Use --noautorotate FILE (repeatable) for clips with wrong rotation metadata. Output: <out>/before_after.jpg
"""
import argparse, subprocess
import numpy as np
from pathlib import Path

W, H = 540, 960
CENTER = "crop=ih*9/16:ih"

# Warm look: deep blacks with highlight roll-off, cool-ish shadows / warm highlights, smart saturation, crisp detail.
LOOK = ",".join([
    "curves=master='0/0 0.06/0.03 0.25/0.22 0.5/0.52 0.8/0.83 0.95/0.94 1/0.98'",   # gentle S, deeper blacks
    "colorbalance=rs=-0.04:bs=0.05:rm=0.03:bm=-0.02:rh=0.07:gh=0.02:bh=-0.06",  # teal shadows, fire highlights
    "vibrance=intensity=0.28",
    "eq=contrast=1.04:saturation=1.05",
    "cas=strength=0.45",
])


def grab(path, t, opts, crop):
    vf = ",".join(x for x in [crop, f"scale={W}:{H}:flags=lanczos", "format=rgb24"] if x)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", str(t), "-i", str(path),
                                   "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def match_gains(img):
    """Half-strength gray-world WB + exposure pull toward mid luma; returns per-channel gains."""
    f = img.astype(np.float32) / 255
    mask = (f.max(2) < 0.95) & (f.max(2) > 0.04)        # ignore clipped lights and pure black
    m = f[mask].mean(0)
    wb = (m.mean() / m) ** 0.5                          # 50 % toward neutral, keeps night warmth
    luma = (f[mask] * wb).mean()
    exp = (0.36 / max(luma, 1e-3)) ** 0.5               # 50 % toward target exposure
    return np.clip(wb * exp, 0.75, 1.45)


def grade(img, gains):
    r, g, b = gains
    vf = f"colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f},{LOOK},format=rgb24"
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                        "-i", "-", "-vf", vf, "-f", "rawvideo", "-"], input=img.tobytes(),
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(H, W, 3)


def parse_sample(s):
    name, at, rest = s.rpartition("@")
    if not at or not name:
        raise SystemExit(f"bad sample '{s}': expected file@seconds[:crop]")
    t, _, crop = rest.partition(":")
    crop = CENTER if crop == "" else None if crop == "none" else crop
    return name, float(t), crop


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("samples", nargs="+", help="file@seconds[:crop]")
    ap.add_argument("--videos", default="./clips", help="dir with the source clips")
    ap.add_argument("--out", default="./build/grade", help="output dir (default: ./build/grade)")
    ap.add_argument("--noautorotate", action="append", default=[], metavar="FILE", help="clip with wrong rotation metadata")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    for s in a.samples:
        f, t, crop = parse_sample(s)
        before = grab(Path(a.videos) / f, t, ["-noautorotate"] if f in a.noautorotate else [], crop)
        gains = match_gains(before)
        rows.append(np.hstack([before, np.full((H, 8, 3), 255, np.uint8), grade(before, gains)]))
        print(f"{f}@{t}: gains {np.round(gains, 3)}")

    # two columns of pairs to keep the sheet compact
    pairs = [np.vstack(rows[i::2] + ([np.zeros_like(rows[0])] if len(rows[i::2]) < len(rows[0::2]) else []))
             for i in (0, 1)]
    sheet = np.hstack([pairs[0], np.full((pairs[0].shape[0], 24, 3), 0, np.uint8), pairs[1]])
    dest = out / "before_after.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{sheet.shape[1]}x{sheet.shape[0]}", "-i", "-", "-vf", "scale=iw/2:-2", str(dest)],
                   input=sheet.tobytes(), check=True)
    print("sheet:", dest)


if __name__ == "__main__":
    main()
