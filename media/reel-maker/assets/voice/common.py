"""Shared helpers of the voice isolation pipeline (separation candidates -> post-filters -> scoring -> deliverable).

Work dir layout (--work, default ./build/voice_work); every script takes --work and calls common.init(work):

    spec.json                           speakers + the source ranges that will be used + reference text (see spec.example.json)
    src/<id>_orig48.wav                 48 kHz stereo original, extracted by extract.py (sample-aligned with the source file)
    stems/<id>_<model>_voc44.wav        separation output at 44.1 kHz (sep.py)
    cands/<id>_<name>.wav               candidates: 48 kHz mono float32, unnormalised, sample-aligned (build_cands.py, build_extra.py)
    vad.json sig.json asr.json ll.json asrj.json   evaluation caches (evaluate.py; re-runs are incremental)
    final/<name>.wav                    deliverables (finalize.py)

Rules that came out of testing: score only the ranges that will be used; level-match candidates before measuring; never judge a
candidate on listening alone (ASR recall is noisy, +-2 words, so also use the Whisper likelihood of the reference text).
"""
import json, os, re, sys, unicodedata
from pathlib import Path
import numpy as np, soundfile as sf
from scipy.signal import resample_poly

SR = 48000
HERE = Path(os.environ.get("VOICE_WORK", "./build/voice_work")).resolve()  # replaced by init()
SPEC = {}
RANGES = {}   # speaker -> [(start s, end s, reference text)] in source-file time
LANG = "en"


def init(work=None):
    """Select the work dir and load spec.json. Returns the work Path."""
    global HERE, SPEC, RANGES, LANG
    if work:
        HERE = Path(work).resolve()
    p = HERE / "spec.json"
    if not p.exists():
        sys.exit(f"{p} not found: copy spec.example.json there and edit it")
    SPEC = json.load(open(p, encoding="utf-8"))
    LANG = SPEC.get("language", "en")
    RANGES = {sp: [(r["start"], r["end"], r["text"]) for r in d["ranges"]] for sp, d in SPEC["speakers"].items()}
    for sub in ("src", "stems", "cands", "final"):
        (HERE / sub).mkdir(parents=True, exist_ok=True)
    return HERE


def speakers(only=None):
    return [s for s in RANGES if not only or s in only]


def norm_words(t):
    """Lower case, accents stripped, punctuation removed -> word list (the scoring normalisation)."""
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return t.split()


def read_mono48(path):
    x, fs = sf.read(str(path), dtype="float32", always_2d=True)
    assert fs == SR, (path, fs)
    return x.mean(1)


def to16k(x48):
    return resample_poly(x48, 1, 3).astype(np.float32)


def stem48(sp, name):
    """Separation vocal stem (44.1 kHz stereo, aligned with the 48 kHz original) -> 48 kHz mono, original length."""
    x, fs = sf.read(str(HERE / "stems" / f"{sp}_{name}_voc44.wav"), dtype="float32", always_2d=True)
    assert fs == 44100
    y = resample_poly(x.mean(1), 160, 147).astype(np.float32)
    n = len(read_mono48(HERE / "src" / f"{sp}_orig48.wav"))
    return np.pad(y, (0, max(0, n - len(y))))[:n]


def used_mask(sp, n, fs=SR):
    m = np.zeros(n, bool)
    for a, b, _ in RANGES[sp]:
        m[int(round(a * fs)):int(round(b * fs))] = True
    return m


def used_concat(sp, x, fs=SR):
    return np.concatenate([x[int(round(a * fs)):int(round(b * fs))] for a, b, _ in RANGES[sp]])


def rms_db(x):
    return 10 * np.log10(np.mean(np.square(x, dtype=np.float64)) + 1e-20)


def jload(name, default):
    p = HERE / name
    return json.load(open(p, encoding="utf-8")) if p.exists() else default


def jsave(name, obj):
    json.dump(obj, open(HERE / name, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def work_arg(ap):
    """Add the shared --work option to an argparse parser."""
    ap.add_argument("--work", default=os.environ.get("VOICE_WORK", "./build/voice_work"), help="work dir with spec.json (default ./build/voice_work)")
    return ap
