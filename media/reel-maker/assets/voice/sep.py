"""Run a Demucs model on the full-length 48 kHz originals; save the vocal stem at the model rate (44.1 kHz).

    python sep.py htdemucs --work build/voice_work            # all speakers
    python sep.py htdemucs_ft A --work build/voice_work       # one speaker
    python sep.py mdx_extra --threads 8

Mirrors the demucs CLI defaults (shifts=1, overlap=0.25, split=True, per-track mean/std normalisation). Run it on the WHOLE
original, then cut ranges later: separation quality drops at the edges of short excerpts. Models download on first use
(torch hub cache). CPU only is fine: a minute of speech takes a few minutes with htdemucs.
"""
import argparse, random, time
import numpy as np, soundfile as sf, torch
from scipy.signal import resample_poly
import common as C


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("model", help="htdemucs | htdemucs_ft | mdx_extra | any demucs pretrained name")
    ap.add_argument("speakers", nargs="*", help="speaker ids (default: all)")
    ap.add_argument("--threads", type=int, default=0, help="torch threads (default: torch's choice)")
    a = ap.parse_args()
    C.init(a.work)
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    random.seed(0); torch.manual_seed(0)
    if a.threads:
        torch.set_num_threads(a.threads)
    t0 = time.time()
    model = get_model(a.model); model.eval()
    sr = model.samplerate
    vi = model.sources.index("vocals")
    print(a.model, "sr", sr, "sources", model.sources, "loaded in %.1fs" % (time.time() - t0), flush=True)
    for sp in C.speakers(a.speakers):
        x, fs = sf.read(str(C.HERE / "src" / f"{sp}_orig48.wav"), dtype="float32")  # (n, 2)
        assert fs == 48000
        x44 = resample_poly(x, 147, 160, axis=0).astype(np.float32)
        wav = torch.from_numpy(x44.T.copy())  # (2, n)
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / ref.std()
        t1 = time.time()
        with torch.no_grad():
            out = apply_model(model, wav[None], shifts=1, split=True, overlap=0.25, progress=False, device="cpu", num_workers=0)[0]
        out = out * ref.std() + ref.mean()
        voc = out[vi].numpy().T  # (n, 2)
        sf.write(str(C.HERE / "stems" / f"{sp}_{a.model}_voc44.wav"), voc, sr, subtype="FLOAT")
        print(sp, a.model, "done in %.1fs" % (time.time() - t1), "frames", voc.shape[0], flush=True)


if __name__ == "__main__":
    main()
