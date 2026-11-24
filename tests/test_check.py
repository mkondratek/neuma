import numpy as np
import pytest

from neuma.check import check, excerpts
from neuma.gabc import parse
from neuma.guide import SAMPLE_RATE
from neuma.rhythm import note_events


def buzz(seconds: float, harmonics: int = 20, level: float = 0.3) -> np.ndarray:
    """A vowel-like sound; fewer harmonics make it duller."""
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    wave = sum(np.sin(2 * np.pi * 180 * h * t) / h for h in range(1, harmonics + 1))
    return level * wave * np.minimum(1, np.minimum(t, t[-1] - t) / 0.01)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLE_RATE))


def fading_vowel() -> np.ndarray:
    """A vowel that loses everything above 1 kHz after 120 ms."""
    upper = buzz(0.22) - buzz(0.22, 5)
    upper[int(0.12 * SAMPLE_RATE):] = 0
    return np.concatenate([buzz(0.22, 5) + upper, silence(0.03)])


def speaker(**sounds):
    """A voice that says each listed syllable as given and anything else plainly."""
    return lambda text: sounds.get(text, np.concatenate([buzz(0.2), silence(0.03)]))


def problems(gabc: str, **sounds) -> list[str]:
    _, findings = check(note_events(parse(gabc)), speak=speaker(**sounds))
    return [f"{f.spoken}: {f.problem}" for f in findings]


def test_plain_syllables_pass():
    assert problems("(c4) la(f) te(g) (::)") == []


def test_voiced_burst_before_the_vowel_is_reported():
    burst = np.concatenate([buzz(0.06, 3), silence(0.03), buzz(0.2), silence(0.03)])
    found = problems("(c4) da(f) te(g) (::)", da=burst)
    assert len(found) == 1 and "ms of voice before the vowel" in found[0]


def test_a_rolled_r_may_start_with_a_burst():
    burst = np.concatenate([buzz(0.06, 3), silence(0.03), buzz(0.2), silence(0.03)])
    assert problems("(c4) ra(f) te(g) (::)", ra=burst) == []


def test_spelled_out_syllable_is_reported():
    two = np.concatenate([buzz(0.2), silence(0.08), buzz(0.2), silence(0.03)])
    found = problems("(c4) la(f) cta(g) (::)", cta=two)
    assert len(found) == 1 and "after the vowel" in found[0]


def test_a_coda_that_sounds_like_a_vowel_is_expected():
    two = np.concatenate([buzz(0.2), silence(0.03), buzz(0.2, 3), silence(0.03)])
    assert problems("(c4) con(f) te(g) (::)", con=two) == []


def test_vowel_that_turns_dull_is_reported():
    found = problems("(c4) li(f) la(g) (::)", li=fading_vowel())
    assert len(found) == 1 and "turns dull" in found[0]


def test_back_vowels_are_not_judged_for_brightness():
    assert problems("(c4) lo(f) la(g) (::)", lo=fading_vowel()) == []


def test_findings_say_where_and_excerpts_can_be_heard():
    burst = np.concatenate([buzz(0.06, 3), silence(0.03), buzz(0.2), silence(0.03)])
    events = note_events(parse("(c4) la(f) da(g) te(h) (::)"))
    guide, findings = check(events, speak=speaker(da=burst), unit_s=0.3)
    (finding,) = findings
    assert finding.written == "da"
    assert finding.start_s == pytest.approx(guide.notes[1].start_s)
    clip = excerpts(guide, findings, margin_s=0.1)
    assert len(clip) == pytest.approx((0.3 + 0.2 + 0.5) * SAMPLE_RATE, rel=0.05)
    assert len(excerpts(guide, [])) == 0
