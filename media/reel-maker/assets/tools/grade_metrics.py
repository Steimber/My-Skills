"""Colour consistency metrics of rendered reels: shot-to-shot delta E, exposure spread, clipping, crushing, skin band.

    python grade_metrics.py --config my_project.py --build-dir build --videos clips --music music [--renders build/notext] [reel names]

Samples 3 frames per picture shot (25/50/75 %) from the caption-free renders (<build>/notext, or --renders) and prints, per reel:
  * dE00 between the mean Lab colours of consecutive shots (lower = shots match; the LUT + per-shot matching took 7.8 -> 5.4),
  * L50 (median lightness) spread over the shots, share of pixels clipped (>= 252) and crushed (< 4), 1st-percentile L*,
  * with a validated face: share of face-skin pixels inside the natural band (hue 36-66 deg, chroma 12-45 in Lab; the skin guard
    keeps this above ~90 %; unguarded saturation pushes faces orange).
Use it to compare two grades (render both, run both) - never to certify a look: judge on the before/after sheet first.
"""
import argparse, sys
from pathlib import Path
import cv2, numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "look"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--videos", default="./clips")
    ap.add_argument("--music", default="./music")
    ap.add_argument("--assets", default="./assets")
    ap.add_argument("--renders", help="dir with <name>.mp4 (default <build>/notext)")
    a = ap.parse_args()
    import reel_engine as E
    import cmx, faces as FC
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    rdir = Path(a.renders) if a.renders else Path(a.build_dir) / "notext"
    for name in a.names or list(reels):
        _, shots = E.plan(reels[name])
        cap = cv2.VideoCapture(str(rdir / f"{name}.mp4"))
        if not cap.isOpened():
            sys.exit(f"{rdir / (name + '.mp4')} not found: render with --notext --preview first")
        rows, skin_in, skin_n = [], 0, 0
        for sp, f0, f1 in shots:
            if sp["kind"] == "hero":
                continue
            px, sk = [], []
            for q in (0.25, 0.5, 0.75):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(f0 + (f1 - f0) * q))
                ok, fr = cap.read()
                if not ok:
                    continue
                rgb = cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)
                px.append(cv2.resize(rgb, (135, 240), interpolation=cv2.INTER_AREA).reshape(-1, 3) / 255.0)
                for (x, y, w, h) in FC.detect(rgb, width=rgb.shape[1], min_frac=0.10, skin_min=0.5):
                    reg = rgb[y + int(h * .3):y + int(h * .8), x + int(w * .2):x + int(w * .8)]
                    m = FC.skin_mask(reg)
                    if m.mean() > .3:
                        sk.append(cmx.rgb2lab(reg[m][::3] / 255.0))
            if not px:
                continue
            p = np.concatenate(px)
            lab = cmx.rgb2lab(p)
            rows.append(dict(lab=lab.mean(0), L50=float(np.median(lab[:, 0])), p1=float(np.percentile(lab[:, 0], 1)),
                             clip=float((p.max(1) >= 252 / 255).mean() * 100), crush=float((cmx.luma(p) < 4 / 255).mean() * 100)))
            for s in sk:
                lch = cmx.lab2lch(s)
                skin_in += float(((lch[:, 2] > 36) & (lch[:, 2] < 66) & (lch[:, 1] > 12) & (lch[:, 1] < 45)).mean()); skin_n += 1
        if len(rows) < 2:
            print(f"{name}: fewer than 2 picture shots"); continue
        de = [float(cmx.de00(rows[i]["lab"], rows[i + 1]["lab"])) for i in range(len(rows) - 1)]
        print(f"\n== {name}: {len(rows)} shots")
        print("   dE00 consecutive: " + " ".join(f"{x:4.1f}" for x in de) + f" | mean {np.mean(de):.1f}")
        print(f"   L50 mean {np.mean([r['L50'] for r in rows]):.1f} sd {np.std([r['L50'] for r in rows]):.1f} | clipped>=252 {np.mean([r['clip'] for r in rows]):.2f}% "
              f"(max {max(r['clip'] for r in rows):.2f}) | crushed<4 {np.mean([r['crush'] for r in rows]):.2f}% (max {max(r['crush'] for r in rows):.2f}) | p1 L* {np.mean([r['p1'] for r in rows]):.1f}")
        print("   skin in natural band: " + (f"{100 * skin_in / skin_n:.0f}% over {skin_n} face detection(s)" if skin_n else "no validated face"))


if __name__ == "__main__":
    main()
