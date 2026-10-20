"""Pure numpy port of the parts of `libdf` (DeepFilterLib 0.5.6, Rust/PyO3) that the `df.enhance` Python API needs.

Credit and license
    This file re-implements, line by line, parts of the DeepFilterNet project (libDF/src/lib.rs and transforms.rs, v0.5.6):
    https://github.com/Rikorose/DeepFilterNet - Copyright (c) Hendrik Schroeter and the DeepFilterNet contributors,
    licensed MIT OR Apache-2.0. This derived port is distributed under the same terms (MIT OR Apache-2.0); keep this notice.
    No model weights are included; see dfrun.py for how to obtain DeepFilterNet3.

Why
    PyPI ships DeepFilterLib wheels only for some CPython versions (cp38-cp311 at the time of writing) and building it needs a
    Rust toolchain, so `pip install deepfilternet` cannot provide `libdf` on newer Pythons (e.g. 3.12). With this module on
    sys.path (dfrun.py does that), `import df` works without it. Follows the Rust source: vorbis window, 1/fft^2*2hop
    analysis norm, ERB band widths, ERB-dB feature, exponential mean-norm and unit-norm. Not bit-exact vs the Rust build
    (float32 vs numpy rounding); the model-level behaviour is checked by selftest_df.py.
"""
import numpy as np
from scipy.signal import lfilter

MEAN_NORM_INIT = (-60.0, -90.0)
UNIT_NORM_INIT = (0.001, 0.0001)
_f32 = np.float32


def _freq2erb(f):
    return _f32(9.265) * np.log1p(_f32(f) / _f32(24.7 * 9.265))


def _erb2freq(n):
    return _f32(24.7 * 9.265) * (np.exp(_f32(n) / _f32(9.265)) - _f32(1.0))


def erb_fb(sr, fft_size, nb_bands, min_nb_freqs):
    nyq = sr // 2
    freq_width = _f32(sr) / _f32(fft_size)
    erb_low = _freq2erb(0.0)
    erb_high = _freq2erb(float(nyq))
    erb = [0] * nb_bands
    step = (erb_high - erb_low) / _f32(nb_bands)
    prev_freq = 0
    freq_over = 0
    for i in range(1, nb_bands + 1):
        f = _erb2freq(erb_low + _f32(i) * step)
        fb = int(np.floor(f / freq_width + _f32(0.5)))  # Rust f32::round (half away from zero)
        nb_freqs = fb - prev_freq - freq_over
        if nb_freqs < min_nb_freqs:
            freq_over = min_nb_freqs - nb_freqs
            nb_freqs = min_nb_freqs
        else:
            freq_over = 0
        erb[i - 1] = nb_freqs
        prev_freq = fb
    erb[nb_bands - 1] += 1
    too_large = sum(erb) - (fft_size // 2 + 1)
    if too_large > 0:
        erb[nb_bands - 1] -= too_large
    assert sum(erb) == fft_size // 2 + 1, (sum(erb), fft_size // 2 + 1)
    return np.asarray(erb, dtype=np.uint64)


class DF:
    def __init__(self, sr, fft_size, hop_size, nb_bands=None, min_nb_erb_freqs=None):
        assert hop_size * 2 <= fft_size and fft_size % hop_size == 0
        self._sr, self._fft, self._hop = sr, fft_size, hop_size
        self._erb = erb_fb(sr, fft_size, nb_bands or 32, min_nb_erb_freqs or 1)
        n_h = fft_size // 2
        i = np.arange(fft_size, dtype=np.float64)
        s = np.sin(0.5 * np.pi * (i + 0.5) / n_h)
        self.window = np.sin(0.5 * np.pi * s * s).astype(np.float32)  # vorbis
        self.wnorm = _f32(1.0 / (fft_size ** 2 / (2 * hop_size)))

    # --- accessors used by df.* ---
    def erb_widths(self): return self._erb.copy()
    def fft_window(self): return self.window.copy()
    def sr(self): return self._sr
    def fft_size(self): return self._fft
    def hop_size(self): return self._hop
    def nb_erb(self): return len(self._erb)
    def reset(self): pass  # stateless: each call is a full-signal transform that starts from zero memory

    def analysis(self, x, reset=True):
        """[C, T] float32 -> [C, T//hop, F] complex64 (trailing partial hop dropped, like chunks_exact)."""
        x = np.asarray(x, dtype=np.float32)
        hop, n = self._hop, self._fft
        nfr = x.shape[1] // hop
        xp = np.concatenate([np.zeros((x.shape[0], n - hop), np.float32), x[:, : nfr * hop]], axis=1)
        idx = np.arange(nfr)[:, None] * hop + np.arange(n)[None, :]
        frames = xp[:, idx] * self.window  # [C, nfr, n]
        spec = np.fft.rfft(frames.astype(np.float64), axis=-1) * float(self.wnorm)
        return spec.astype(np.complex64)

    def synthesis(self, spec, reset=True):
        """[C, T', F] complex64 -> [C, T'*hop] float32 (windowed overlap-add; rustfft inverse is unnormalised)."""
        spec = np.asarray(spec)
        hop, n = self._hop, self._fft
        c, nfr, _ = spec.shape
        fr = np.fft.irfft(spec.astype(np.complex128), n=n, axis=-1) * n  # unnormalised inverse
        fr = fr * self.window.astype(np.float64)
        kk = n // hop
        out = np.zeros((c, nfr + kk - 1, hop))
        for k in range(kk):  # frame t contributes its k-th hop-block to output block t+k
            out[:, k : k + nfr, :] += fr[:, :, k * hop : (k + 1) * hop]
        return out.reshape(c, -1)[:, : nfr * hop].astype(np.float32)


def erb(spec, erb_widths, db=True):
    """spec [..., F] complex -> [..., nb_erb] mean power per ERB band (optionally 10*log10(x+1e-10))."""
    spec = np.asarray(spec)
    p = (spec.real.astype(np.float32) ** 2 + spec.imag.astype(np.float32) ** 2)
    edges = np.concatenate([[0], np.cumsum(np.asarray(erb_widths, dtype=np.int64))])
    out = np.stack([p[..., a:b].mean(axis=-1) for a, b in zip(edges[:-1], edges[1:])], axis=-1)
    if db:
        out = np.log10(out + 1e-10) * 10.0
    return out.astype(np.float32)


def _ema(x, alpha, init):
    """s_t = (1-alpha)*x_t + alpha*s_{t-1} along axis -2 of [C, T, F]; init [F] or [C, F]. Returns s."""
    out = np.empty(x.shape, np.float64)
    for ch in range(x.shape[0]):
        z0 = (alpha * np.asarray(init, np.float64)).reshape(1, -1)  # [1, F]
        out[ch], _ = lfilter([1.0 - alpha], [1.0, -alpha], x[ch].astype(np.float64), axis=0, zi=z0)
    return out


def erb_norm(erb_db, alpha, state=None):
    n = erb_db.shape[-1]
    init = np.linspace(MEAN_NORM_INIT[0], MEAN_NORM_INIT[1], n)
    s = _ema(erb_db, alpha, init)
    return ((erb_db - s) / 40.0).astype(np.float32)


def unit_norm(spec, alpha, state=None):
    f = spec.shape[-1]
    init = np.linspace(UNIT_NORM_INIT[0], UNIT_NORM_INIT[1], f)
    s = _ema(np.abs(spec), alpha, init)
    return (spec / np.sqrt(s)).astype(np.complex64)


def unit_norm_init(num_freq_bins):
    return np.linspace(UNIT_NORM_INIT[0], UNIT_NORM_INIT[1], num_freq_bins, dtype=np.float32).reshape(1, num_freq_bins)
