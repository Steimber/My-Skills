"""Build every voice candidate as a full-length 48 kHz mono float32 wav (sample-aligned with the source, unnormalised level).

    python build_cands.py --work build/voice_work [speaker ...] [--no-df] [--no-nr]

Inputs: stems/<id>_<model>_voc44.wav from sep.py. Models recognised: h1=htdemucs, h2=htdemucs_ft, m3=mdx_extra.
Candidates written to cands/<id>_<name>.wav:
    orig                         the mix itself (control)
    h1 h2 m3                     single-model vocal stems
    e12 e23 e123                 ensembles (mean of the stems): different models make different artefacts, averaging cancels some
    <x>_df                       + DeepFilterNet3 at full strength (for orig, h1, h2, m3, e12, e23, e123)
    h1_nr e123_nr                + non-stationary spectral gating (noisereduce, prop_decrease 0.9)
Candidates whose inputs are missing are skipped. Next: evaluate.py mask, build_extra.py, evaluate.py sig/asr/ll.
"""
import argparse, time
import numpy as np, soundfile as sf
import common as C

MODELS = {"h1": "htdemucs", "h2": "htdemucs_ft", "m3": "mdx_extra"}
ENS = {"e12": ["h1", "h2"], "e23": ["h2", "m3"], "e123": ["h1", "h2", "m3"]}
DF_ON = ["h1", "h2", "m3", "e12", "e23", "e123", "orig"]
NR_ON = ["h1", "e123"]  # extra, cheap: spectral gating post-filter


def save(sp, name, x):
    sf.write(str(C.HERE / "cands" / f"{sp}_{name}.wav"), x.astype(np.float32), C.SR, subtype="FLOAT")


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("speakers", nargs="*")
    ap.add_argument("--no-df", action="store_true", help="skip the DeepFilterNet candidates (no df / weights installed)")
    ap.add_argument("--no-nr", action="store_true", help="skip the noisereduce candidates")
    a = ap.parse_args()
    C.init(a.work)
    if not a.no_df:
        import dfrun
    if not a.no_nr:
        import noisereduce as nr
    for sp in C.speakers(a.speakers):
        c = {"orig": C.read_mono48(C.HERE / "src" / f"{sp}_orig48.wav")}
        for k, m in MODELS.items():
            if (C.HERE / "stems" / f"{sp}_{m}_voc44.wav").exists():
                c[k] = C.stem48(sp, m)
        for k, parts in ENS.items():
            if all(p in c for p in parts):
                c[k] = np.mean([c[p] for p in parts], axis=0).astype(np.float32)
        if not a.no_df:
            for k in list(c):
                if k in DF_ON:
                    t = time.time()
                    c[k + "_df"] = dfrun.df_enhance(c[k])
                    print(sp, k, "DF %.1fs" % (time.time() - t), flush=True)
        if not a.no_nr:
            for k in NR_ON:
                if k in c:  # moderate settings limit musical noise
                    c[k + "_nr"] = nr.reduce_noise(y=c[k], sr=C.SR, stationary=False, prop_decrease=0.9, n_jobs=1).astype(np.float32)
        for k, x in c.items():
            save(sp, k, x)
        print(sp, "saved", sorted(c), flush=True)


if __name__ == "__main__":
    main()
