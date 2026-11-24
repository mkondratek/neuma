from dataclasses import dataclass

import numpy as np
import pytest
import pyworld as pw

from neuma.guide import midi_to_hz
from neuma.retune import FRAME_MS, FRAME_S, retune, singer_key, tuning

SR = 22050
NOTE_S = 0.6


@dataclass
class N:
    start_s: float
    end_s: float
    hz: float


MELODY = [53, 55, 57, 55]  # F G A G
NOTES = [N(i * NOTE_S, (i + 1) * NOTE_S, float(midi_to_hz(m))) for i, m in enumerate(MELODY)]
FRAMES = int(len(MELODY) * NOTE_S / FRAME_S)
MELODY_HZ = midi_to_hz(np.repeat(MELODY, FRAMES // len(MELODY)))


def voice(f0: np.ndarray) -> np.ndarray:
    """A buzzy vowel-like tone on the given pitch line (one value per 5 ms)."""
    hz = np.repeat(f0, int(SR * FRAME_S))
    phase = 2 * np.pi * np.cumsum(hz) / SR
    return 0.2 * sum(np.sin(h * phase) / h for h in range(1, 16))


def take(note_errors_cents, vibrato_cents=0.0, shift_cents=0.0) -> np.ndarray:
    """The melody sung out of tune: a per-note error, optional vibrato and key shift."""
    per_note = np.repeat(note_errors_cents, FRAMES // len(MELODY))
    t = np.arange(FRAMES) * FRAME_S
    cents = per_note + shift_cents + vibrato_cents * np.sin(2 * np.pi * 6 * t)
    return voice(MELODY_HZ * 2 ** (cents / 1200))


def test_tuning_reports_the_error_of_each_note():
    report = tuning(take([-300, 0, 150, -80]), SR, NOTES)
    assert report.cents == pytest.approx((-300, 0, 150, -80), abs=8)
    assert report.within(30) == 1
    assert report.median_abs_cents == pytest.approx(115, abs=8)


def test_retune_puts_every_note_on_the_melody():
    fixed = retune(take([-300, 40, 150, -80]), SR, MELODY_HZ)
    report = tuning(fixed, SR, NOTES)
    assert report.within(15) == len(NOTES), report.cents


def test_retune_keeps_the_voices_own_vibrato():
    def vibrato_depth(audio):
        f0, t = pw.harvest(audio, SR, f0_floor=60, f0_ceil=700, frame_period=FRAME_MS)
        held = f0[(t > 0.15) & (t < 0.45)]  # the middle of the first note
        return float(np.std(1200 * np.log2(held / np.median(held))))

    wobbly = take([-300, 40, 150, -80], vibrato_cents=40)
    before, after = vibrato_depth(wobbly), vibrato_depth(retune(wobbly, SR, MELODY_HZ))
    assert before > 20
    # A 150 ms smoothing window still removes about half of a 6 Hz vibrato;
    # replacing the pitch line outright would remove all of it.
    assert after > 0.4 * before


def test_retune_leaves_an_in_tune_take_in_tune():
    report = tuning(retune(take([0, 0, 0, 0]), SR, MELODY_HZ), SR, NOTES)
    assert report.within(10) == len(NOTES)


def test_singer_key_is_the_nearest_semitone_the_voice_chose():
    flat_take = take([-20, 30, 10, -40], shift_cents=-300)
    assert singer_key(flat_take, SR, NOTES) == -3


def test_retune_to_the_singers_key():
    flat_take = take([-20, 30, 10, -40], shift_cents=-300)
    fixed = retune(flat_take, SR, MELODY_HZ, key_shift=-3)
    assert tuning(fixed, SR, NOTES, key_shift=-3).within(15) == len(NOTES)
    assert tuning(fixed, SR, NOTES).within(30) == 0  # three semitones from the written key


def test_silence_has_no_pitch_to_retune():
    with pytest.raises(ValueError):
        retune(np.zeros(SR), SR, MELODY_HZ)
