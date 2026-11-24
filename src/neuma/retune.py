"""Put a sung take back on the melody and its notes back at their loudness,
and measure how far off it is.

Voice Changer keeps the timing of the guide but not its pitch, so the melody
has to be restored afterwards. The correction is deliberately gentle: only the
slow part of the pitch error is removed (the wrong note), while the voice's own
fast movement (jitter, vibrato, the shape of its attacks) is left alone.
Replacing the whole pitch line with the computed melody is more exact and
sounds markedly more robotic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyworld as pw

FRAME_MS = 5.0
FRAME_S = FRAME_MS / 1000
STEP_S = 0.01  # grid on which the correction is smoothed


def _mono(audio: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(audio if audio.ndim == 1 else audio.mean(axis=1), dtype=np.float64)


def _track(audio: np.ndarray, sample_rate: int):
    return pw.harvest(audio, sample_rate, f0_floor=60, f0_ceil=700, frame_period=FRAME_MS)


def _melody_at(times: np.ndarray, melody_hz: np.ndarray, key_shift: float) -> np.ndarray:
    hz = np.interp(times, np.arange(len(melody_hz)) * FRAME_S, melody_hz)
    return hz * 2 ** (key_shift / 12)


def _correction(times, sung_hz, wanted_hz, smooth_ms: float) -> np.ndarray:
    """Correction in octaves for each voiced frame: the smoothed pitch error.

    A short median filter drops pitch-tracker glitches; the low-pass then keeps
    only error slower than ``smooth_ms``.
    """
    grid = np.arange(0, times[-1] + STEP_S, STEP_S)
    error = np.interp(grid, times, np.log2(wanted_hz / sung_hz))  # bridges unvoiced gaps
    padded = np.pad(error, 2, mode="edge")
    error = np.median(np.lib.stride_tricks.sliding_window_view(padded, 5), axis=1)
    n = max(int(smooth_ms / 1000 / STEP_S) | 1, 3)
    window = np.hanning(n + 2)[1:-1]
    padded = np.pad(error, n // 2, mode="edge")
    error = np.convolve(padded, window / window.sum(), mode="valid")
    return np.interp(times, grid, error)


def retune(
    audio: np.ndarray,
    sample_rate: int,
    melody_hz: np.ndarray,
    *,
    smooth_ms: float = 150,
    key_shift: float = 0,
) -> np.ndarray:
    """Return ``audio`` moved onto ``melody_hz`` (one value per 5 ms frame).

    ``key_shift`` transposes the melody by that many semitones first.
    """
    audio = _mono(audio)
    f0, t = _track(audio, sample_rate)
    voiced = f0 > 0
    if not voiced.any():
        raise ValueError("no pitch found in the take")
    sp = pw.cheaptrick(audio, f0, t, sample_rate)
    ap = pw.d4c(audio, f0, t, sample_rate)
    wanted = _melody_at(t[voiced], melody_hz, key_shift)
    new = np.zeros_like(f0)
    new[voiced] = f0[voiced] * 2 ** _correction(t[voiced], f0[voiced], wanted, smooth_ms)
    out = pw.synthesize(new, sp, ap, sample_rate, FRAME_MS)
    return out * 0.7 / np.abs(out).max()


def _note_levels(audio: np.ndarray, sample_rate: int, notes) -> np.ndarray:
    """Level in dB of the middle 60% of each note, against the median note."""
    levels = []
    for note in notes:
        mid, half = (note.start_s + note.end_s) / 2, (note.end_s - note.start_s) * 0.3
        part = audio[int((mid - half) * sample_rate): int((mid + half) * sample_rate)]
        levels.append(10 * np.log10(np.mean(part**2) + 1e-12) if len(part) else -120.0)
    levels = np.array(levels)
    return levels - np.median(levels)


def level(
    audio: np.ndarray,
    sample_rate: int,
    notes,
    guide: np.ndarray,
    guide_rate: int,
    *,
    max_boost_db: float = 9,
    max_cut_db: float = 6,
) -> np.ndarray:
    """Bring each note of a take to the loudness it has in the guide.

    Voice Changer keeps the words and the timing but swallows some syllables,
    returning them 10 dB or more below their neighbours. Timing survives, so
    the guide says how loud each note was meant to be. The gain glides from
    one note to the next, and is limited:
    a note that came back as a whisper is noise, and stays quiet.
    """
    audio = _mono(audio)
    gain_db = np.clip(_note_levels(_mono(guide), guide_rate, notes) - _note_levels(audio, sample_rate, notes),
                      -max_cut_db, max_boost_db)
    # Each note holds its gain over its middle 60%; the gain glides in between.
    at = [m + side * (note.end_s - note.start_s) * 0.3
          for note in notes for m in [(note.start_s + note.end_s) / 2] for side in (-1, 1)]
    curve = np.interp(np.arange(len(audio)) / sample_rate, at, np.repeat(gain_db, 2))
    out = audio * 10 ** (curve / 20)
    return out * 0.7 / np.abs(out).max()


@dataclass(frozen=True)
class Tuning:
    cents: tuple[float | None, ...]  # per note, sung minus written; None if no pitch found

    @property
    def found(self) -> list[float]:
        return [c for c in self.cents if c is not None]

    @property
    def median_abs_cents(self) -> float:
        return float(np.median(np.abs(self.found)))

    def within(self, cents: float) -> int:
        return sum(abs(c) <= cents for c in self.found)

    def __str__(self) -> str:
        return (f"{self.within(30)} of {len(self.cents)} notes within 30 cents, "
                f"median error {self.median_abs_cents:.0f} cents")


def tuning(audio: np.ndarray, sample_rate: int, notes, *, key_shift: float = 0) -> Tuning:
    """Compare the sung pitch of each note (its middle 60%) with the written one.

    ``notes`` are ``guide.TimedNote``-like: ``start_s``, ``end_s``, ``hz``.
    """
    f0, t = _track(_mono(audio), sample_rate)
    cents: list[float | None] = []
    for note in notes:
        mid, half = (note.start_s + note.end_s) / 2, (note.end_s - note.start_s) * 0.3
        sung = f0[(t >= mid - half) & (t <= mid + half)]
        sung = sung[sung > 0]
        if len(sung) < 3:
            cents.append(None)
        else:
            cents.append(float(1200 * np.log2(np.median(sung) / note.hz) - 100 * key_shift))
    return Tuning(tuple(cents))


def singer_key(audio: np.ndarray, sample_rate: int, notes) -> int:
    """Semitones by which the take sits above the written melody, to the nearest one.

    Chant pitch is relative. Retuning to the key the voice chose, instead of
    the key it was asked for, needs the smallest correction.
    """
    found = tuning(audio, sample_rate, notes).found
    if not found:
        raise ValueError("no pitch found in the take")
    return round(float(np.median(found)) / 100)
