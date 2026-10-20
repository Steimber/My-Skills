"""DeepFilterNet3 enhancement wrapper: the python API (`df.enhance`) on top of the numpy `libdf` port in this directory.

Setup (nothing of DeepFilterNet is bundled except the port):
    pip install --user deepfilternet            # python package `df`; its Rust extension `libdf` is replaced by libdf.py here
    Model weights (DeepFilterNet3, MIT OR Apache-2.0) come from the upstream project, https://github.com/Rikorose/DeepFilterNet:
      * leave DFN_MODEL_DIR unset and `df.init_df()` fetches them into its cache on first use, or
      * fetch https://github.com/Rikorose/DeepFilterNet/raw/main/models/DeepFilterNet3.zip yourself, unzip it to a folder holding
        config.ini + checkpoints/ and set DFN_MODEL_DIR=<that folder> (works offline).

    from dfrun import df_enhance
    y = df_enhance(x48)                      # full strength
    y = df_enhance(x48, atten_lim_db=12)     # limit the noise attenuation to 12 dB: keeps consonants of a noisy speaker intact
"""
import os, sys, types
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)  # so `import libdf` finds the numpy port libdf.py

# df.io does `from torchaudio.backend.common import AudioMetaData`, removed in torchaudio >= 2.1
if "torchaudio.backend.common" not in sys.modules:
    import torchaudio
    be, common = types.ModuleType("torchaudio.backend"), types.ModuleType("torchaudio.backend.common")

    class AudioMetaData:  # only used as a type annotation by df.io
        pass

    common.AudioMetaData = AudioMetaData
    be.common = common
    sys.modules["torchaudio.backend"], sys.modules["torchaudio.backend.common"] = be, common

import torch  # noqa: E402
from df.enhance import enhance, init_df  # noqa: E402

_state = {}


def load():
    if "m" not in _state:
        d = os.environ.get("DFN_MODEL_DIR") or None
        _state["m"] = init_df(d, post_filter=False, log_level="ERROR", log_file=None, epoch="best")
    return _state["m"]


def df_enhance(x48, atten_lim_db=None):
    """x48: float32 mono array at 48 kHz -> enhanced float32 mono, same length, delay-compensated."""
    model, df_state, _ = load()
    t = torch.from_numpy(np.ascontiguousarray(x48, dtype=np.float32))[None]
    out = enhance(model, df_state, t, pad=True, atten_lim_db=atten_lim_db)
    return out[0].numpy().astype(np.float32)
