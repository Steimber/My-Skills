"""Music gain per reel: measure the song section a reel uses and suggest the fixed `gain_db` that lands near -14 LUFS.

    python gain_check.py --config my_project.py --build-dir build --music music --videos clips [reel names] [--target -14]

Why fixed gains: single-pass dynamic `loudnorm` made music pump. Measure once with ebur128, set `gain_db` in the reel config, then
verify the FINAL file with verify_media.py (the master limiter and the voice move the result by a dB or two). For a reel with speech
the music is ducked under the voice, so the figure is for the music bus alone: expect the final mix ~1-3 LU above the speech-weighted
target, and use bed_db / the voice level (voice_lufs) to balance the two. Applies the reel's `music_fx` before measuring.
"""
import argparse, math, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--config", required=True)
    ap.add_argument("--build-dir", default="./build")
    ap.add_argument("--videos", default="./clips")
    ap.add_argument("--music", default="./music")
    ap.add_argument("--assets", default="./assets")
    ap.add_argument("--target", type=float, default=-14.0, help="integrated loudness to aim at (default -14 LUFS)")
    a = ap.parse_args()
    import reel_engine as E
    reels = E.init(a.config, a.build_dir, a.videos, a.music, a.assets, "./out", preview=True)
    for name in a.names or list(reels):
        cfg = reels[name]
        _, plan_ = E.plan(cfg)
        total = plan_[-1][2] / E.FPS
        key, song_file, st = cfg["song"]
        fx = ("," + cfg["music_fx"]) if cfg.get("music_fx") else ""
        af = f"aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f}{fx},ebur128=peak=true"
        r = subprocess.run(["ffmpeg", "-nostats", "-hide_banner", "-ss", f"{st}", "-t", f"{total + 0.5:.3f}", "-i", str(E.MUSIC / song_file),
                            "-af", af, "-f", "null", "-"], capture_output=True, text=True, check=True)
        summ = r.stderr[r.stderr.rindex("Summary"):]
        I = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1))
        tp = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summ).group(1))
        sugg = a.target - I
        print(f"{name:24s} {key} from {st}s ({total:.1f}s): music {I:6.1f} LUFS at gain 0 (peak {tp:+.1f} dBFS) -> gain_db {sugg:+.1f}"
              f"   (config now {cfg['gain_db']:+.1f} -> about {I + cfg['gain_db']:.1f} LUFS before the limiter{', voice ducks it' if cfg.get('voice') else ''})")
        ceil = 20 * math.log10(float(re.search(r"limit=([\d.]+)", E.LIMITER).group(1)))
        if tp + sugg > ceil + 0.5:  # the master limiter would flatten peaks by this much: a crushed, peaky section (or a high target)
            print(f"{'':24s} note: peaks would reach {tp + sugg:+.1f} dBFS against the limiter at {ceil:+.1f} dBFS ({tp + sugg - ceil:.1f} dB of reduction): "
                  "expect pumping and true peaks near -1 dBTP; pick a calmer section, a lower --target, or accept it")


if __name__ == "__main__":
    main()
