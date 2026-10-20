"""Cross-reel visual repeat check: ORB features + RANSAC homography inliers between frames of every pair of reels.

    python reel_engine.py --config my_project.py --notext --preview          # caption-free renders in <build>/notext
    python orb_repeats.py --config my_project.py --build-dir build --videos clips --music music [--min-inliers 30]

"No repeats" means VISUAL repeats, not only distinct source ranges: the same person, sign, table or hand seen from another range of
the same clip still reads as a repeat. For every pair of reels the best frame pair is scored by the RANSAC homography inliers:
the same hand on the same grill scored 144, unrelated shots stay below ~30; adjacent ranges of one pan still share signs/menus.
Pairs above --min-inliers are flagged. Fix by moving one shot's range, cropping differently, or swapping the shot. Talking-head
shots of the SAME speaker are skipped between reels by default (--include-heads to score them). Text is never in the renders
(--notext), so captions cannot create matches.
"""
import argparse, itertools, json, sys
from pathlib import Path
import cv2, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="reel names (default: all in the config)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--videos", default="./clips")
    ap.add_argument("--music", default="./music")
    ap.add_argument("--assets", default="./assets")
    ap.add_argument("--renders", help="dir with <name>.mp4 caption-free renders (default <build>/notext)")
    ap.add_argument("--min-inliers", type=int, default=30)
    ap.add_argument("--step", type=float, default=0.25, help="seconds between sampled frames")
    ap.add_argument("--include-heads", action="store_true")
    a = ap.parse_args()
    import reel_engine as E
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    names = a.names or list(reels)
    rdir = Path(a.renders) if a.renders else Path(a.build_dir) / "notext"
    orb = cv2.ORB_create(1500)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    data = {}  # reel -> list of (t, label, kp, des)
    for name in names:
        _, shots = E.plan(reels[name])
        cap = cv2.VideoCapture(str(rdir / f"{name}.mp4"))
        if not cap.isOpened():
            sys.exit(f"{rdir / (name + '.mp4')} not found: render with --notext --preview first")
        items = []
        for sp, f0, f1 in shots:
            if sp["kind"] == "hero":
                continue
            label = f"{sp.get('clip') or str(sp.get('file', ''))[-18:]}@{sp.get('start', 0):.1f}" + ("/head" if sp.get("role") == "head" else "")
            t = f0 / E.FPS + 0.15
            while t < f1 / E.FPS - 0.15:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * E.FPS)))
                ok, fr = cap.read()
                if ok:
                    g = cv2.cvtColor(cv2.resize(fr, (270, 480)), cv2.COLOR_BGR2GRAY)
                    kp, des = orb.detectAndCompute(g, None)
                    if des is not None and len(kp) > 20:
                        items.append((round(t, 2), label, kp, des))
                t += a.step
        data[name] = items
        print(name, len(items), "frames", flush=True)

    def inliers(x, y):
        m = bf.knnMatch(x[3], y[3], k=2)
        good = [p[0] for p in m if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(good) < 12:
            return len(good) // 3
        src = np.float32([x[2][g.queryIdx].pt for g in good]); dst = np.float32([y[2][g.trainIdx].pt for g in good])
        _, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        return int(mask.sum()) if mask is not None else 0

    flagged, res = 0, {}
    for ra, rb in itertools.combinations(names, 2):
        best = []
        for fa in data[ra]:
            for fb in data[rb]:
                if not a.include_heads and fa[1].endswith("/head") and fb[1].endswith("/head"):
                    continue
                best.append((inliers(fa, fb), fa[0], fa[1], fb[0], fb[1]))
        best.sort(reverse=True)
        res[f"{ra}|{rb}"] = best[:3]
        if not best:
            continue
        flag = best[0][0] >= a.min_inliers
        flagged += flag
        print(f"{'REPEAT' if flag else 'ok    '} {ra[:18]:18s} vs {rb[:18]:18s} max inliers {best[0][0]:3d} | {best[0][1:]}", flush=True)
    out = Path(a.build_dir) / "orb_result.json"
    json.dump(res, open(out, "w", encoding="utf-8"), default=str)
    print(f"{flagged} pair(s) at or above {a.min_inliers} inliers; details in {out}")
    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
