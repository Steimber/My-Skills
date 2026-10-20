"""Before/after sheet of the colour look, to approve a grade before rendering anything.

    python before_after.py --videos clips clip_01.mp4@3.0 clip_03.mp4@5.0 clip_09.mp4@5.0:crop=ih*9/16:ih:1159:0
    python before_after.py --mode lut --food clip_07.mp4 --videos clips clip_01.mp4@3.0 clip_07.mp4@2.0

Sample syntax: file@seconds[:crop]. crop = an ffmpeg crop filter, `none`, or omitted for the 9:16 center crop.
Use --noautorotate FILE (repeatable) for clips with wrong rotation metadata.
--mode legacy (default): per-clip gains (50 % gray-world + 50 % exposure pull) + the ffmpeg LOOK chain, no extra deps.
--mode lut: the engine's v4 grade (3D LUT, skin guard, per-reel target over all samples); needs scipy + opencv.
Output: <out>/before_after.jpg (left = source, right = graded).
"""
import argparse, subprocess, sys
import numpy as np
from pathlib import Path

W, H = 540, 960
CENTER = "crop=ih*9/16:ih"

# Legacy warm look (same as the engine's default LOOK): deep blacks with highlight roll-off, cool shadows / warm highlights,
# vibrance instead of plain saturation (protects skin), crisp detail.
LOOK = ",".join([
    "curves=master='0/0 0.06/0.03 0.25/0.22 0.5/0.52 0.8/0.83 0.95/0.94 1/0.98'",
    "colorbalance=rs=-0.04:bs=0.05:rm=0.03:bm=-0.02:rh=0.07:gh=0.02:bh=-0.06",
    "vibrance=intensity=0.28",
    "eq=contrast=1.04:saturation=1.05",
    "cas=strength=0.45",
])


def grab(path, t, opts, crop, extra=""):
    vf = ",".join(x for x in [crop, f"scale={W}:{H}:flags=lanczos", extra, "format=rgb24"] if x)
    raw = subprocess.check_output(["ffmpeg", "-v", "error", *opts, "-ss", str(t), "-i", str(path),
                                   "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def match_gains(img):
    """Half-strength gray-world WB + exposure pull toward mid luma; returns per-channel gains."""
    f = img.astype(np.float32) / 255
    mask = (f.max(2) < 0.95) & (f.max(2) > 0.04)        # ignore clipped lights and pure black
    m = f[mask].mean(0)
    wb = (m.mean() / m) ** 0.5                          # 50 % toward neutral, keeps warm ambience
    luma = (f[mask] * wb).mean()
    exp = (0.36 / max(luma, 1e-3)) ** 0.5               # 50 % toward target exposure
    return np.clip(wb * exp, 0.75, 1.45)


def legacy_after(img, gains):
    r, g, b = gains
    vf = f"colorchannelmixer=rr={r:.3f}:gg={g:.3f}:bb={b:.3f},{LOOK},format=rgb24"
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                        "-i", "-", "-vf", vf, "-f", "rawvideo", "-"], input=img.tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.uint8).reshape(H, W, 3)


def parse_sample(s):
    if "@" not in s or s.startswith("@"):
        raise SystemExit(f"bad sample '{s}': expected file@seconds[:crop]")
    name, rest = s.rsplit("@", 1)
    t, crop = (rest.split(":", 1) + [""])[:2]
    crop = CENTER if crop == "" else None if crop == "none" else crop
    return name, float(t), crop


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("samples", nargs="+", help="file@seconds[:crop]")
    ap.add_argument("--videos", default="./clips", help="dir with the source clips")
    ap.add_argument("--out", default="./build/grade", help="output dir (default: ./build/grade)")
    ap.add_argument("--mode", choices=["legacy", "lut"], default="legacy")
    ap.add_argument("--noautorotate", action="append", default=[], metavar="FILE", help="clip with wrong rotation metadata")
    ap.add_argument("--food", action="append", default=[], metavar="FILE", help="(lut mode) clip graded with the food variant")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    vids = Path(a.videos)
    samples = [parse_sample(s) for s in a.samples]
    opts_of = lambda f: ["-noautorotate"] if f in a.noautorotate else []

    afters = []
    befores = [grab(vids / f, t, opts_of(f), crop) for f, t, crop in samples]
    if a.mode == "legacy":
        for (f, t, crop), b in zip(samples, befores):
            g = match_gains(b)
            print(f"{f}@{t}: gains {np.round(g, 3)}")
            afters.append(legacy_after(b, g))
    else:
        sys.path.insert(0, str(Path(__file__).parent))
        import grade as GV  # noqa: E402
        GV.configure(out / "lut")
        # one target over all samples, as the engine does per reel; each sample is a 1 s window around its time
        shots = [(str(vids / f), opts_of(f), crop, max(0.0, t - 0.5), t + 0.5) for f, t, crop in samples]
        target = GV.reel_target(shots)
        print(f"target: L50 {target['L50']:.1f} cast {target['cast'][0]:+.1f},{target['cast'][1]:+.1f}")
        for (f, t, crop), shot in zip(samples, shots):
            pre, post = GV.shot_filter_parts(*shot, target, food=f in a.food)
            raw = subprocess.check_output(
                ["ffmpeg", "-v", "error", *opts_of(f), "-ss", str(t), "-i", str(vids / f), "-frames:v", "1", "-vf",
                 ",".join(x for x in [crop, pre, f"scale={W}:{H}:flags=lanczos", post, "format=rgb24"] if x), "-f", "rawvideo", "-"])
            afters.append(np.frombuffer(raw, np.uint8).reshape(H, W, 3))

    rows = [np.hstack([b, np.full((H, 8, 3), 255, np.uint8), a_]) for b, a_ in zip(befores, afters)]
    # two columns of pairs to keep the sheet compact
    pairs = [np.vstack(rows[i::2] + ([np.zeros_like(rows[0])] if len(rows[i::2]) < len(rows[0::2]) else []))
             for i in (0, 1)] if len(rows) > 1 else [rows[0], np.zeros_like(rows[0])]
    sheet = np.hstack([pairs[0], np.full((pairs[0].shape[0], 24, 3), 0, np.uint8), pairs[1]])
    dest = out / "before_after.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", f"{sheet.shape[1]}x{sheet.shape[0]}", "-i", "-", "-vf", "scale=iw/2:-2", str(dest)],
                   input=sheet.tobytes(), check=True)
    print("sheet:", dest)


if __name__ == "__main__":
    main()
