"""Signal metrics for one candidate (48 kHz mono float32, already level-matched), given the shared speech/gap masks.

Frames are 21.3 ms Hann windows with a 10 ms hop. Masks (masks_from_vad): speech = frames where >= 3 cleaned candidates agree a
voice is present (Silero VAD); gap = used frames well away from any speech (pauses); guard = the zone right next to speech
(onsets, tails, decay) that a VAD expander does not gate. Metrics (all in dB unless noted; "lower/higher is better"):
    sr_all_db / sr_db / sr_guard_db   speech-to-residual: speech power vs the leftover in pauses / in the file's pauses / next to speech (higher)
    gap_p95_rel, gap_std_db           loudest residual burst vs speech, residual fluctuation = musical noise (lower)
    gap_flat                          spectral flatness of the residual: ~1 noise-like, -> 0 tonal / music-like (higher)
    hf4_8_db, hf8_16_db               high-band energy during speech (naturalness proxy; too low = dull, too high = hiss)
    hole_frac                         share of voiced frames with a hole at 3-7 kHz while the low band sounds (consonants eaten) (lower)
    lsd_db, carved, carved_hf, added  speech fidelity vs the original in speech-dominant cells: log-spectral distance, share of cells removed
                                      by > 10 dB (overall / above 3 kHz), share added by > 10 dB (artefacts) (lower)
"""
import numpy as np, librosa
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import correlate
import common as C
from common import SR

NFFT, HOP = 1024, 480  # 21.3 ms window, 10 ms hop; frame k is centred on sample k*HOP
FREQ = np.fft.rfftfreq(NFFT, 1 / SR)
EPS = 1e-12


def stft_pow(x):
    S = librosa.stft(x, n_fft=NFFT, hop_length=HOP, window="hann", center=True)
    return (np.abs(S) ** 2).astype(np.float64)  # [bins, frames]


def band(P, lo, hi):
    return P[(FREQ >= lo) & (FREQ < hi)].sum(0)


def db(v):
    return 10 * np.log10(v + EPS)


def _dilate(v, before, after):
    """True at frame k if v[j] for some j in [k-after, k+before] (speech at j blocks frames [j-before, j+after])."""
    n = len(v)
    c = np.concatenate([[0], np.cumsum(v.astype(int))])
    k = np.arange(n)
    return (c[np.clip(k + before + 1, 0, n)] - c[np.clip(k - after, 0, n)]) > 0


def masks_from_vad(sp, segs, nfr, min_votes=3):
    """segs: {cand: [(start_s, end_s), ...]} Silero-VAD speech segments of several cleaned candidates.
    speech = frames where >= min_votes candidates agree.
    guard  = used frames within 0.10 s before / 0.20 s after any candidate's speech, but VAD-silent (onsets, tails, decay).
    gap    = frames beyond guard + 40 ms settling margin (0.14 s before / 0.24 s after), so a VAD expander's ramps are over."""
    min_votes = min(min_votes, max(1, len(segs)))  # fewer candidates than votes asked for: all must agree
    t = np.arange(nfr) * HOP / SR
    used = np.zeros(nfr, bool)
    for a, b, _ in C.RANGES[sp]:
        used |= (t >= a) & (t < b)
    votes = np.zeros(nfr, int)
    for iv in segs.values():
        m = np.zeros(nfr, bool)
        for s, e in iv:
            m |= (t >= s) & (t <= e)
        votes += m
    anyv = votes > 0
    near_g, near_w = _dilate(anyv, 10, 20), _dilate(anyv, 14, 24)
    # speech, gap inside used ranges, gap anywhere in the file, guard zone inside used ranges
    return (votes >= min_votes) & used, (~near_w) & used, ~near_w, near_g & ~anyv & used


def analyze(x, ref_P, sp, speech, gap, gap_all, guard):
    """x: candidate (level matched). ref_P: STFT power of the original mix (same normalisation procedure)."""
    P = stft_pow(x)
    nfr = P.shape[1]
    tot = P.sum(0)
    out = {}
    out["n_gap_frames"] = int(gap.sum())
    out["n_gap_all"] = int(gap_all.sum())
    out["sr_all_db"] = float(db(tot[speech].mean()) - db(tot[gap_all].mean()))  # same, residual measured in all VAD-silent frames of the file
    out["sr_db"] = float(db(tot[speech].mean()) - db(tot[gap].mean()))  # speech-to-residual, power-mean
    out["n_guard"] = int(guard.sum())
    out["sr_guard_db"] = float(db(tot[speech].mean()) - db(tot[guard].mean())) if guard.any() else float("nan")  # residual right next to speech (not gated by the VAD expander)
    g = db(tot[gap])
    out["gap_db"] = float(db(tot[gap].mean()))
    out["gap_p95_rel"] = float(np.percentile(g, 95) - db(tot[speech].mean()))  # loudest residual burst vs speech mean (dB, lower better)
    out["gap_std_db"] = float(g.std())  # fluctuation of residual (musical noise -> high)
    # spectral flatness of the residual (100 Hz - 12 kHz): ~1 noise-like, ->0 tonal/music-like
    sel = (FREQ >= 100) & (FREQ < 12000)
    Pg = P[sel][:, gap] + EPS
    out["gap_flat"] = float(np.mean(np.exp(np.mean(np.log(Pg), axis=0)) / Pg.mean(axis=0)))
    # naturalness proxies during speech
    out["hf4_8_db"] = float(db(band(P, 4000, 8000)[speech].sum()) - db(tot[speech].sum()))
    out["hf8_16_db"] = float(db(band(P, 8000, 16000)[speech].sum()) - db(tot[speech].sum()))
    L37 = db(band(P, 3000, 7000)); LL = db(band(P, 100, 3000))
    # local max over +-120 ms of speech frames = the nearest syllable peak
    def roll90(v):
        w = 12
        vp = np.pad(np.where(speech, v, -np.inf), (w, w), constant_values=-np.inf)
        win = sliding_window_view(vp, 2 * w + 1)
        return np.max(win, axis=1)
    r37, rL = roll90(L37), roll90(LL)
    voiced = speech & (LL > np.percentile(LL[speech], 50))  # loud enough low band: a syllable is sounding
    hole = voiced & (L37 < r37 - 20) & (LL > rL - 10)
    out["hole_frac"] = float(hole.sum() / max(1, voiced.sum()))
    # speech fidelity vs original in speech-dominant cells
    nf = ref_P[:, gap_all].mean(1)  # noise PSD of the original (power mean over gap frames)
    dom = (ref_P > (nf[:, None] * 10 ** 1.5)) & speech[None, :] & ((FREQ >= 100) & (FREQ < 10000))[:, None]
    d = 10 * np.log10(P + EPS) - 10 * np.log10(ref_P + EPS)
    dd = d[dom]
    dd = dd - np.median(dd)
    out["lsd_db"] = float(np.sqrt(np.mean(dd ** 2)))
    out["carved"] = float(np.mean(dd < -10))  # speech-dominant cells the candidate removed (>10 dB below original, gain-matched)
    hi = dom & (FREQ >= 3000)[:, None]
    dh = d[hi]; dh = dh - np.median(d[dom])
    out["carved_hf"] = float(np.mean(dh < -10)) if dh.size else float("nan")
    out["added"] = float(np.mean(dd > 10))  # cells much louder than original (artefact / music added)
    return out


def lag_vs(x, orig, sp, maxlag=60):
    m = C.used_mask(sp, len(x))
    a, b = x[m], orig[m]
    c = correlate(b, a, mode="full", method="fft")
    mid = len(a) - 1
    seg = c[mid - maxlag: mid + maxlag + 1]
    return int(np.argmax(np.abs(seg)) - maxlag)  # +k: candidate is k samples early vs orig? (0 = aligned)
