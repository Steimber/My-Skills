"""VAD-driven soft expander: unity gain around speech (+guard), `depth_db` attenuation elsewhere, raised-cosine ramps.

The speech map comes from evaluate.py's `mask` stage (vad.json: Silero VAD run on several cleaned candidates, union of segments).
Use it AFTER separation / DeepFilterNet: it silences the leftover pumping noise in the pauses without touching the words.
"""
import numpy as np
import common as C


def gate_gain(sp, n, depth_db=25.0, pre=0.10, post=0.20, ramp=0.025):
    vad = C.jload("vad.json", {})
    if sp not in vad:
        raise SystemExit("vad.json has no entry for speaker %s: run `evaluate.py mask` first" % sp)
    m = np.zeros(n)
    for iv in vad[sp].values():  # union over the consensus candidates
        for s, e in iv:
            m[int(max(0.0, s - pre) * C.SR): int((e + post) * C.SR)] = 1.0
    k = np.hanning(int(2 * ramp * C.SR) | 1); k /= k.sum()
    g = np.clip(np.convolve(m, k, mode="same"), 0, 1)
    floor = 10 ** (-depth_db / 20)
    return (floor + (1 - floor) * g).astype(np.float32)
