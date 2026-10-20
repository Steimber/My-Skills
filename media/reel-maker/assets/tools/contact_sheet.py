"""Contact sheets: look at every clip (to pick moments) and every render (to review it) before trusting numbers.

    python contact_sheet.py clips/clip_01.mp4 clips/clip_02.mp4 --fps 2 --out build/sheets          # source clips, 2 fps
    python contact_sheet.py build/preview/reel1.mp4 --fps 4 --width 135 --cols 16 --out build/sheets  # a preview, 4 fps
    python contact_sheet.py clips/clip_01.mp4 --noautorotate                                          # wrong rotation metadata

One JPEG per input: <out>/<name>_sheet.jpg. Tiles run left-to-right, top-to-bottom: tile k is at t = k / fps, so the printed
tile index maps straight to a source time. Photos (jpg/png) are tiled as a single frame each.
Look for: faces covered by text, text outside 15-72 % of the height, blurry floor frames, black or frozen runs, empty frame halves,
the same place/person/sign appearing in two reels (repeat), wrong rotation. `--noautorotate` mirrors the config's input opts.
"""
import argparse, json, subprocess
from pathlib import Path


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)], capture_output=True, text=True)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--width", type=int, default=135, help="tile width in px (tile height follows the aspect)")
    ap.add_argument("--cols", type=int, default=16)
    ap.add_argument("--out", default="./build/sheets")
    ap.add_argument("--noautorotate", action="store_true", help="ignore rotation metadata (compare with the autorotated sheet)")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for f in a.files:
        p = Path(f)
        is_img = p.suffix.lower() in (".jpg", ".jpeg", ".png", ".bmp", ".webp")
        d = 0.0 if is_img else duration(p)
        n = 1 if is_img else max(1, int(d * a.fps + 0.999))
        rows = -(-n // a.cols)
        dest = out / f"{p.stem}_sheet.jpg"
        vf = ([] if is_img else [f"fps={a.fps}"]) + [f"scale={a.width}:-2", f"tile={min(a.cols, n)}x{rows}"]
        cmd = ["ffmpeg", "-v", "error", "-y", *(["-noautorotate"] if a.noautorotate else []), "-i", str(p), "-vf", ",".join(vf), "-frames:v", "1", "-q:v", "3", str(dest)]
        subprocess.run(cmd, check=True)
        print(f"{p.name}: {d:.1f}s, {n} tiles ({rows} rows x {min(a.cols, n)} cols, tile k = {1 / a.fps:.2f} s x k) -> {dest}")


if __name__ == "__main__":
    main()
