"""Hearing reactions: laughter, cheering and screaming, found by a small sound-recognition model (YAMNet, from
Google, Apache 2.0 licence), run on this computer.

A laugh is the clearest sign that something funny just happened, in any language, so these moments are marked
for the AI and give a small boost to the clips that hold them. Without the model (models/yamnet.onnx, shipped with ShaydoxCut) or
the onnxruntime package, this quietly does nothing and loudness alone is used, as before.
"""
import csv
import threading

import numpy as np

from . import config

_SHIPPED = config.ROOT / "models"            # comes with ShaydoxCut; a copy in the data folder wins
MODEL = next((d / "yamnet.onnx" for d in (config.MODELS_DIR, _SHIPPED) if (d / "yamnet.onnx").is_file()),
             _SHIPPED / "yamnet.onnx")
CLASSES = MODEL.with_name("yamnet_class_map.csv")
CHANNELS = ("laughter", "cheering", "screaming")
THRESHOLD = 0.15            # a chuckle is about 0.25, a hearty laugh higher; the background sits near 0

_lock = threading.Lock()
_state: dict = {}


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return MODEL.is_file() and CLASSES.is_file()


def _session():
    with _lock:
        if "s" not in _state:
            import onnxruntime as ort
            _state["s"] = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
            names = {}
            with open(CLASSES, newline="", encoding="utf-8") as f:
                rows = csv.reader(f)
                next(rows)
                for r in rows:
                    names[int(r[0])] = r[2]
            low = {i: n.lower() for i, n in names.items()}
            _state["idx"] = {
                "laughter": [i for i, n in low.items() if any(k in n for k in ("laugh", "giggle", "chuckle", "snicker", "chortle"))],
                "cheering": [i for i, n in names.items() if n in ("Cheering", "Applause", "Whoop")],
                "screaming": [i for i, n in names.items() if n in ("Screaming",)],
            }
        return _state["s"], _state["idx"]


def per_second(audio: np.ndarray) -> dict:
    """For 16 kHz audio (int16 or float), the strongest laughter, cheering and screaming in each second:
    {"laughter": [...], "cheering": [...], "screaming": [...]} with values from 0 to 1. Empty when unavailable."""
    if not available() or audio is None or len(audio) < 16000:
        return {}
    try:
        sess, idx = _session()
        wave = audio.astype(np.float32) / (32768.0 if audio.dtype == np.int16 else 1.0)
        name = sess.get_inputs()[0].name
        seconds = len(wave) // 16000 + 1
        out = {c: np.zeros(seconds, dtype=np.float32) for c in CHANNELS}
        window = 16000 * 300                         # five minutes at a time, so memory stays small
        for off in range(0, len(wave), window):
            chunk = wave[off: off + window]
            if len(chunk) < 16000:
                continue
            scores = sess.run(None, {name: chunk})[0]          # [frames, 521]
            if not len(scores):
                continue
            hop = (len(chunk) / 16000.0) / len(scores)
            for c in CHANNELS:
                vals = scores[:, idx[c]].max(axis=1) if idx[c] else np.zeros(len(scores))
                for f, v in enumerate(vals):
                    s = int(off / 16000 + f * hop)
                    if s < seconds and v > out[c][s]:
                        out[c][s] = v
        return {c: [round(float(v), 3) for v in out[c]] for c in CHANNELS}
    except Exception:  # noqa: BLE001 - a bonus signal: never a reason for a video to fail
        return {}


def level(r: dict, a: float, b: float) -> tuple:
    """The strongest reaction between seconds a and b: (0..1, "laughter" / "cheering" / "screaming" / "")."""
    if not r:
        return 0.0, ""
    best, kind = 0.0, ""
    for c in CHANNELS:
        seg = r.get(c, [])[max(0, int(a)): max(0, int(b) + 1)]
        if seg and max(seg) > best:
            best, kind = max(seg), c
    return best, kind


def slice_(r: dict, a: int, b: int) -> dict:
    """The part of the per-second values between seconds a and b."""
    return {c: v[a:b] for c, v in (r or {}).items()}
