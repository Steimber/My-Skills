"""Write the chosen candidates as deliverables and verify them.

    python finalize.py A_best=A:e12_dfa12_g B_best=B:h1_df --work build/voice_work

Each argument is  <output name>=<speaker>:<candidate>. Output: final/<name>.wav = 48 kHz, L=R, 32-bit float, full length,
sample-aligned with the source's first audio sample, peak-normalised to -3 dBFS over the whole file, NO fades (the engine fades
every piece by 20 ms itself). The engine takes these files as cfg["voice"] (relative to --build-dir, or absolute) and cuts the
pieces by source time. Each file is re-read and checked: channels equal, length vs the source, peak, used-range level, lag vs the mix.
"""
import argparse
import numpy as np, soundfile as sf
import common as C
import metrics as M


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("items", nargs="+", help="<name>=<speaker>:<candidate>")
    a = ap.parse_args()
    C.init(a.work)
    for item in a.items:
        out, rest = (item.split("=", 1) + [""])[:2]
        sp, cand = (rest.split(":", 1) + [""])[:2]
        if not (out and sp and cand):
            raise SystemExit(f"bad item '{item}': expected name=speaker:candidate")
        x = C.read_mono48(C.HERE / "cands" / f"{sp}_{cand}.wav")
        y = (x * (10 ** (-3 / 20) / np.abs(x).max())).astype(np.float32)
        dest = C.HERE / "final" / f"{out}.wav"
        dest.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(dest), np.stack([y, y], axis=1), C.SR, subtype="FLOAT")
        r, fs = sf.read(str(dest), dtype="float32", always_2d=True)
        o = C.read_mono48(C.HERE / "src" / f"{sp}_orig48.wav")
        m = r.mean(1)
        lag = M.lag_vs(m, o, sp)
        u = C.used_concat(sp, m)
        print(f"{out}: cand={cand} sr={fs} ch={r.shape[1]} frames={len(r)} (src {len(o)}) L==R {np.array_equal(r[:, 0], r[:, 1])} "
              f"peak {20 * np.log10(np.abs(r).max()):.2f} dBFS, used-range peak {20 * np.log10(np.abs(u).max()):.1f} dBFS, "
              f"used-range RMS {C.rms_db(u):.1f} dBFS, lag vs source mix {lag} samples")


if __name__ == "__main__":
    main()
