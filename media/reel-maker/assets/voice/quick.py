"""Fast path without scoring: source audio -> htdemucs vocal stem -> mono (L=R), peak -3 dBFS -> final/<id>_quick.wav.

    python quick.py --work build/voice_work            # speakers from spec.json
    python quick.py A --model htdemucs_ft

Good enough for a clean speaker over a quiet or musical background. For a noisy room (crowd, kitchen, street) run the full
candidate pipeline instead (sep.py with several models, build_cands.py, evaluate.py, finalize.py): there, an ensemble + limited
DeepFilterNet + soft gate beat a single stem on word recall. Point the reel config at the result: voice="voice/<id>_quick.wav"
after copying it into <build>/voice/ (or use an absolute path).
"""
import argparse, subprocess, sys
from pathlib import Path
import numpy as np, soundfile as sf
import common as C


def main():
    ap = C.work_arg(argparse.ArgumentParser(description=__doc__.split("\n")[0]))
    ap.add_argument("speakers", nargs="*")
    ap.add_argument("--model", default="htdemucs")
    a = ap.parse_args()
    C.init(a.work)
    here = Path(__file__).resolve().parent
    for script, extra in (("extract.py", []), ("sep.py", [a.model])):
        subprocess.run([sys.executable, str(here / script), *extra, *a.speakers, "--work", str(C.HERE)], check=True)
    for sp in C.speakers(a.speakers):
        x = C.stem48(sp, a.model)
        y = (x * (10 ** (-3 / 20) / max(float(np.abs(x).max()), 1e-9))).astype(np.float32)
        dest = C.HERE / "final" / f"{sp}_quick.wav"
        sf.write(str(dest), np.stack([y, y], axis=1), C.SR, subtype="FLOAT")
        print("wrote", dest)


if __name__ == "__main__":
    main()
