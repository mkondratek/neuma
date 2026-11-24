"""M0 follow-up: put a Voice Changer take back in tune without making it robotic.

Voice Changer returns a human-sounding take that is out of tune. Replacing its
whole pitch line through the WORLD vocoder fixes the tuning but sounds robotic.
This script tries two remedies on a take that is already on disk (no credits):

* gentle: move each stretch of the take only by how far it is off the melody,
  so the voice's own fast pitch movement (jitter, wobble, attacks) survives;
* PSOLA: shift pitch on the original waveform (Praat's overlap-add) instead of
  rebuilding the sound in a vocoder.

    uv run experiments/m0_retune.py out/m0/<take>.mp3

Needs out/m0/pitch.npy and notes.json from the m0_refrain.py run that made the take.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import parselmouth
import pyworld as pw
import soundfile as sf
from parselmouth.praat import call

from m0_refrain import FRAME_MS, FRAME_S, OUT, measure

STEP = 0.01  # s, grid on which the correction is computed


def correction(times, sung_hz, melody_at, smooth_ms: float) -> np.ndarray:
    """Smooth pitch correction in octaves, for every point of the sung pitch.

    The raw deviation (melody / sung) is median-filtered to drop tracker
    glitches and then low-passed: anything slower than ``smooth_ms`` is
    corrected, anything faster is left to the singer.
    """
    grid = np.arange(0, times[-1] + STEP, STEP)
    dev = np.log2(melody_at(times) / sung_hz)
    dev = np.interp(grid, times, dev)  # bridges unvoiced gaps
    k = 5
    padded = np.pad(dev, k // 2, mode="edge")
    dev = np.median(np.lib.stride_tricks.sliding_window_view(padded, k), axis=1)
    n = max(int(smooth_ms / 1000 / STEP) | 1, 3)
    win = np.hanning(n + 2)[1:-1]
    padded = np.pad(dev, n // 2, mode="edge")
    dev = np.convolve(padded, win / win.sum(), mode="valid")
    return np.interp(times, grid, dev)


def psola(x, sr, melody_at, smooth_ms: float | None) -> np.ndarray:
    """Retune on the waveform. ``smooth_ms=None`` imposes the melody outright."""
    snd = parselmouth.Sound(x, sampling_frequency=sr)
    manip = call(snd, "To Manipulation", 0.01, 60, 400)
    tier = call(manip, "Extract pitch tier")
    n = call(tier, "Get number of points")
    times = np.array([call(tier, "Get time from index", i) for i in range(1, n + 1)])
    sung = np.array([call(tier, "Get value at index", i) for i in range(1, n + 1)])
    if smooth_ms is None:
        new = melody_at(times)
    else:
        new = sung * 2 ** correction(times, sung, melody_at, smooth_ms)
    out = call("Create PitchTier", "retuned", 0, snd.duration)
    for t, f in zip(times, new):
        call(out, "Add point", float(t), float(f))
    call([out, manip], "Replace pitch tier")
    return call(manip, "Get resynthesis (overlap-add)").values[0]


def world(x, sr, melody_at, smooth_ms: float) -> np.ndarray:
    """The gentle correction through the vocoder, to tell method from bluntness."""
    f0, t = pw.harvest(x, sr, f0_floor=60, f0_ceil=700, frame_period=FRAME_MS)
    sp, ap = pw.cheaptrick(x, f0, t, sr), pw.d4c(x, f0, t, sr)
    v = f0 > 0
    new = np.zeros_like(f0)
    new[v] = f0[v] * 2 ** correction(t[v], f0[v], melody_at, smooth_ms)
    return pw.synthesize(new, sp, ap, sr, FRAME_MS)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--smooth", type=float, default=150, help="correct only what is slower than this, ms")
    args = p.parse_args()

    src = Path(args.file)
    x, sr = sf.read(src, dtype="float64")
    x = np.ascontiguousarray(x if x.ndim == 1 else x.mean(axis=1))
    pitch = np.load(OUT / "pitch.npy")
    notes = json.loads((OUT / "notes.json").read_text())

    def melody_at(t):
        return np.interp(t, np.arange(len(pitch)) * FRAME_S, pitch)

    variants = {
        "psola-gentle": lambda: psola(x, sr, melody_at, args.smooth),
        "psola-strict": lambda: psola(x, sr, melody_at, None),
        "world-gentle": lambda: world(x, sr, melody_at, args.smooth),
    }
    for name, render in variants.items():
        y = render()
        dest = src.with_name(f"{src.stem}-{name}.wav")
        sf.write(dest, y * 0.7 / np.abs(y).max(), sr, subtype="PCM_16")
        measure(dest, notes)


if __name__ == "__main__":
    main()
