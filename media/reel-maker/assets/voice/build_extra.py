"""Extra candidates: partial-strength DeepFilterNet (atten_lim_db) and the VAD soft expander, on the htdemucs / ensemble stems.

    python build_extra.py --work build/voice_work [speaker ...]      # needs vad.json (evaluate.py mask) and cands/*_h1, *_e12

Writes cands/<id>_{h1_g, e12_g, e12_dfa12, e12_dfa24, e12_dfa12_g}.wav  (_g = gated, dfaNN = DeepFilterNet limited to NN dB).
Measured on two speakers: for a clean speaker full-strength DeepFilterNet after htdemucs won; for a noisier speaker it cost
recall, and the ensemble + DeepFilterNet limited to 12 dB + soft gate was the best compromise.
"""
import argparse
import numpy as np, soundfile as sf
import common as C
import dfrun, gate


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("speakers", nargs="*")
    a = ap.parse_args()
    C.init(a.work)
    for sp in C.speakers(a.speakers):
        L = lambda n: C.read_mono48(C.HERE / "cands" / f"{sp}_{n}.wav")
        h1, e12 = L("h1"), L("e12")
        g = gate.gate_gain(sp, len(h1))
        out = {
            "h1_g": h1 * g,
            "e12_g": e12 * g,
            "e12_dfa12": dfrun.df_enhance(e12, atten_lim_db=12),
            "e12_dfa24": dfrun.df_enhance(e12, atten_lim_db=24),
        }
        out["e12_dfa12_g"] = out["e12_dfa12"] * g
        for k, x in out.items():
            sf.write(str(C.HERE / "cands" / f"{sp}_{k}.wav"), x.astype(np.float32), C.SR, subtype="FLOAT")
        print(sp, "built", sorted(out), "gate: %.1f%% of samples at unity" % (100 * (g > 0.99).mean()), flush=True)


if __name__ == "__main__":
    main()
