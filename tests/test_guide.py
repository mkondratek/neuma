import numpy as np
import pytest
import pyworld as pw

from neuma.gabc import parse
from neuma.guide import FRAME_MS, FRAME_S, SAMPLE_RATE, glide, midi_to_hz, render
from neuma.rhythm import note_events


def fake_speaker(text: str) -> np.ndarray:
    """A stand-in for a speech voice: 40 ms of noise, then a 200 ms vowel-like buzz."""
    rng = np.random.default_rng(len(text))
    t = np.arange(int(0.2 * SAMPLE_RATE)) / SAMPLE_RATE
    vowel = sum(np.sin(2 * np.pi * 180 * h * t) / h for h in range(1, 20))
    vowel *= np.minimum(1, np.minimum(t, t[-1] - t) / 0.02)
    noise = 0.02 * rng.standard_normal(int(0.04 * SAMPLE_RATE))
    return np.concatenate([noise, 0.3 * vowel, np.zeros(int(0.03 * SAMPLE_RATE))])


def sung_hz(audio: np.ndarray, start_s: float, end_s: float) -> float:
    """Median pitch over the middle 60% of a time span."""
    f0, t = pw.harvest(audio, SAMPLE_RATE, f0_floor=60, f0_ceil=700, frame_period=FRAME_MS)
    mid, half = (start_s + end_s) / 2, (end_s - start_s) * 0.3
    sel = f0[(t >= mid - half) & (t <= mid + half)]
    return float(np.median(sel[sel > 0]))


def cents(a: float, b: float) -> float:
    return 1200 * np.log2(a / b)


REFRAIN = "(c4) RO(f)rá(gh)te(h.) cae(k')li(j) dé(ixji)su(h)per,(hg..) (;) et(h) nu(ixi')bes(h) (::)"


@pytest.fixture(scope="module")
def guide():
    return render(note_events(parse(REFRAIN)), unit_s=0.3, speak=fake_speaker)


def test_every_note_is_sung_at_its_pitch(guide):
    assert len(guide.notes) == 14
    for note in guide.notes:
        assert abs(cents(sung_hz(guide.audio, note.start_s, note.end_s), note.hz)) < 25, note


def test_notes_carry_their_syllable_pitch_and_length(guide):
    first, second, third = guide.notes[:3]
    assert (first.syllable, second.syllable, third.syllable) == ("RO", "rá", "rá")
    assert first.hz == pytest.approx(midi_to_hz(53))
    assert first.end_s - first.start_s == pytest.approx(0.3)
    assert second.end_s == pytest.approx(third.start_s)  # a melisma has no gap
    dotted = guide.notes[3]
    assert dotted.end_s - dotted.start_s == pytest.approx(0.6)


def test_bar_line_is_silent_and_trailing_rest_is_dropped(guide):
    per, et = guide.notes[10], guide.notes[11]
    assert et.start_s - per.end_s >= 0.3  # the half bar, plus the next onset
    a, b = int((per.end_s + 0.05) * SAMPLE_RATE), int((per.end_s + 0.25) * SAMPLE_RATE)
    assert np.abs(guide.audio[a:b]).max() < 0.01 * np.abs(guide.audio).max()
    assert guide.duration_s < guide.notes[-1].end_s + 0.2  # no 3-unit rest at the end


def test_melody_line_covers_the_audio(guide):
    assert len(guide.pitch_hz) * FRAME_S == pytest.approx(guide.duration_s, abs=0.02)
    assert guide.pitch_hz.min() > midi_to_hz(52) and guide.pitch_hz.max() < midi_to_hz(63)


def test_rendering_is_deterministic():
    events = note_events(parse("(c4) a(fg) b(h.)"))
    one = render(events, speak=fake_speaker)
    two = render(events, speak=fake_speaker)
    assert np.array_equal(one.audio, two.audio)


def test_transposition_moves_the_sung_pitch():
    events = note_events(parse("(c4) a(h.)"), transpose=-7)
    g = render(events, speak=fake_speaker)
    assert abs(cents(sung_hz(g.audio, g.notes[0].start_s, g.notes[0].end_s), midi_to_hz(50))) < 25


def test_nothing_to_sing_is_an_error():
    with pytest.raises(ValueError):
        render(note_events(parse("(c4) (::)")), speak=fake_speaker)


# --- glide ------------------------------------------------------------------


def step(frames_before=100, frames_after=100, low=0.0, high=2.0):
    return np.concatenate([np.full(frames_before, low), np.full(frames_after, high)])


def test_glide_settles_on_both_notes():
    line = glide(step(), rise_ms=80)
    assert line[:60] == pytest.approx(0.0, abs=0.01)
    assert line[-40:] == pytest.approx(2.0, abs=0.01)


def test_glide_takes_about_the_requested_time():
    line = glide(step(), rise_ms=80)
    crossing = lambda level: int(np.argmax(line >= level))
    rise_ms = (crossing(1.8) - crossing(0.2)) * FRAME_MS
    assert 50 <= rise_ms <= 110


def test_glide_straddles_the_note_boundary():
    line = glide(step(), rise_ms=80)
    halfway = int(np.argmax(line >= 1.0))
    assert abs(halfway - 100) * FRAME_MS <= 25


def test_glide_overshoots_only_slightly():
    line = glide(step(), rise_ms=80)
    assert 2.0 <= line.max() <= 2.0 + 0.1  # under 5% of the interval


def test_slower_glide_is_slower():
    fast, slow = glide(step(), rise_ms=40), glide(step(), rise_ms=160)
    assert np.argmax(fast >= 1.8) < np.argmax(slow >= 1.8)
