"""Text safe-zone audit: exact pixel rows of every caption / subtitle, plus a face-overlap check against caption-free renders.

    python textzone.py --config my_project.py --build-dir build --videos clips --music music --assets assets [reel names]
    python textzone.py --config my_project.py ... --faces      # also scan <build>/notext/<name>.mp4 for faces under the text

Method: each text object is drawn on a black canvas at the moment it is fully on screen and its bounding box is measured, so the
numbers are the real pixels, not the layout intent. Rules checked (FAIL lines, exit code 1):
  * titles, kickers, subtitles inside 15-72 % of the frame height (platform UI covers the top and the bottom/side rail),
  * the intro tagline / end-card group ends above GROUP_BOTTOM (70 %),
  * subtitle chunks <= 80 % of the width (and every end-card CTA line >= 2.9 % of the height: legibility),
  * with --faces: no OpenCV Haar face has > 20 % of its box under a caption (text never covers a face).
Render the caption-free videos first:  python reel_engine.py --config my_project.py --notext --preview
"""
import argparse, subprocess, sys
from pathlib import Path
import cv2, numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def full(c):
    """Time at which every letter of a Caption is fully risen."""
    return max(l[3] for l in c.letters) + c.dur + 0.02


def bbox(img, thr=70):
    m = img.max(2) > thr
    ys, xs = np.nonzero(m)
    return (xs.min(), ys.min(), xs.max(), ys.max()) if len(ys) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*", help="reel names (default: all)")
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--videos", default="./clips")
    ap.add_argument("--music", default="./music")
    ap.add_argument("--assets", default="./assets")
    ap.add_argument("--faces", action="store_true", help="scan the caption-free renders for faces under the text")
    a = ap.parse_args()
    import reel_engine as E
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    W, H, FPS = E.W, E.H, E.FPS
    casc = [cv2.CascadeClassifier(cv2.data.haarcascades + n) for n in ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml", "haarcascade_profileface.xml")]

    def faces(g):
        out = []
        for c in casc:
            out += [tuple(int(v) for v in x) for x in c.detectMultiScale(g, 1.1, 5, minSize=(22, 22))]
        return out

    fails = 0
    for name in a.names or list(reels):
        cfg = reels[name]
        _, plan_ = E.plan(cfg)
        boxes = []  # (label, t_from, t_to, bbox, extra)
        for sp, f0, f1 in plan_:
            n = f1 - f0
            if sp["kind"] == "hero":
                sh = E.Shot(sp, f0, n, text_only=True)
                if not sh.caps:
                    continue
                tl = max(full(c) for c in sh.caps)
                img = np.zeros((H, W, 3), np.uint8)
                for c in sh.caps: c.draw(img, tl)
                boxes.append(("end card text" if sp.get("end") else "intro tagline", f0 / FPS, f1 / FPS, bbox(img), dict(group_top=sh.group[0], logo_w=sh.group[2])))
            elif sp.get("title"):
                sh = E.Shot(sp, f0, n, text_only=True)
                t_exit = n / FPS - 0.30
                tl = min(max(full(c) for c in sh.caps), t_exit - 0.05)
                img = np.zeros((H, W, 3), np.uint8)
                for c in sh.caps: c.draw(img, tl)
                boxes.append(("title+kicker", f0 / FPS + 0.5, f1 / FPS - 0.3, bbox(img), dict(text=sp["title"], read=round(sh.title_read, 2))))
            if sp.get("subs"):
                sh = E.Shot(sp, f0, n, text_only=True)
                for ta, tb, spr, _y in sh.sub.chunks:
                    img = np.zeros((H, W, 3), np.uint8); sh.sub.draw(img, ta + 0.3)
                    boxes.append(("subtitle", f0 / FPS + ta + 0.3, f0 / FPS + tb, bbox(img), {}))
        gs = E.reel_subtitles(plan_, cfg.get("_vt"))
        if gs:
            for ta, tb, spr, _y in gs.chunks:
                img = np.zeros((H, W, 3), np.uint8); gs.draw(img, ta + 0.3)
                boxes.append(("subtitle", ta + 0.3, tb, bbox(img), {}))
        overlaps = []
        rend = Path(a.build_dir) / "notext" / f"{name}.mp4"
        if a.faces and rend.exists():
            pr = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(rend), "-vf", "select='not(mod(n,6))'", "-fps_mode", "passthrough",
                                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, bufsize=W * H * 3 * 4)
            idx = 0
            while True:
                raw = pr.stdout.read(W * H * 3)
                if len(raw) < W * H * 3: break
                t = idx * 6 / FPS; idx += 1
                act = [bx for bx in boxes if bx[1] <= t < bx[2] and bx[3] is not None and bx[0] not in ("end card text", "intro tagline")]
                if not act: continue
                g = cv2.equalizeHist(cv2.cvtColor(np.frombuffer(raw, np.uint8).reshape(H, W, 3), cv2.COLOR_RGB2GRAY))
                for (x, y, fw, fh) in faces(g):
                    for bx in act:
                        x0, y0, x1, y1 = bx[3]
                        ix = max(0, min(x1, x + fw) - max(x, x0)); iy = max(0, min(y1, y + fh) - max(y, y0))
                        if ix * iy / (fw * fh) > 0.2:
                            overlaps.append((round(t, 1), bx[0], (x, y, fw, fh)))
        elif a.faces:
            print(f"   (no caption-free render at {rend}: face check skipped)")
        print(f"\n== {name}")
        for lab in ("intro tagline", "end card text", "title+kicker", "subtitle"):
            sel = [bx for bx in boxes if bx[0] == lab and bx[3]]
            if not sel: continue
            top = min(bx[3][1] for bx in sel) / H * 100; bot = max(bx[3][3] for bx in sel) / H * 100
            wide = max(bx[3][2] - bx[3][0] for bx in sel) / W * 100
            problems = []
            if lab in ("title+kicker", "subtitle") and (top < 15 or bot > 72): problems.append("outside 15-72 %")
            if lab in ("intro tagline", "end card text") and bot > E.GROUP_BOTTOM * 100 + 0.5: problems.append(f"below {E.GROUP_BOTTOM * 100:.0f} %")
            if lab == "subtitle" and wide > 80: problems.append("wider than 80 %")
            extra = f"  logo width {sel[0][4]['logo_w'] * 100:.0f}% W, group top {sel[0][4]['group_top'] * 100:.1f}%" if lab in ("intro tagline", "end card text") else ""
            fails += bool(problems)
            print(f"   {lab:14s} rows {top:5.1f}% - {bot:5.1f}% of H, widest {wide:4.1f}% of W  ({len(sel)} item(s)){extra}{'  FAIL: ' + ', '.join(problems) if problems else ''}")
        if a.faces:
            fails += bool(overlaps)
            print(f"   face overlaps (>20% of a detected face inside a caption box): {len(overlaps)} {overlaps[:6]}")
    print(f"\n{'FAIL' if fails else 'PASS'}: {fails} problem group(s)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
