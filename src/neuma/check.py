"""Look for trouble in a guide before any credits are spent on it.

The guide is built from syllables spoken one at a time by a speech voice, and
that goes wrong in a few known ways: the voice spells a syllable out, starts
a consonant with a burst as loud as the vowel, lets a vowel trail off into a
hum, or the rendered note comes out much quieter than its neighbours. Voice
Changer turns each of these into a confidently wrong word, so they are worth
finding first. Every check here is a measurement that caught a real fault in
*Rorate caeli*; none of them replaces listening.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neuma import guide as guide_mod
from neuma.rhythm import NoteEvent

FRAME_MS = guide_mod.FRAME_MS
SONORANTS = "lmnrjwł"  # consonants that are loud and voiced like a vowel
VOWELS = "aeiouyà"
# A rolled r and the Polish voice's b, d and g begin with a stretch of voice
# as loud as the vowel. It measures like a fault and, checked by ear, is not one.
VOICED_ONSETS = "rbdg"
SECOND_VOWEL_MS = 80  # a loud stretch this long outside the vowel is another syllable
LOUD_ONSET_MS = 40  # shorter bursts before the vowel are ordinary
BRIGHT_SHARE = 0.8  # of the vowel that must keep its upper formants
QUIET_NOTE_DB = -8  # against the median note


@dataclass(frozen=True)
class Finding:
    written: str  # the syllable as in the chant
    spoken: str  # the spelling given to the speech voice
    start_s: float  # where its first occurrence sits in the guide
    end_s: float
    problem: str

    def __str__(self) -> str:
        return f"{self.start_s:6.2f} s  {self.written} (spoken {self.spoken!r}): {self.problem}"


def _stray_sounds(spoken: str, syllable) -> list[str]:
    """Loud voiced stretches that are not the vowel."""
    if sum(c in VOWELS for c in spoken) != 1:
        return []  # a diphthong has a second vowel by design
    vowel_at = next(i for i, c in enumerate(spoken) if c in VOWELS)
    onset, coda = spoken[:vowel_at], spoken[vowel_at + 1:]
    energy = syllable.sp.sum(axis=1)
    a, b = syllable.vowel
    problems = []
    for start, end in guide_mod._loud_runs(energy, syllable.voiced):
        ms = (end - start) * FRAME_MS
        if end <= a and ms >= SECOND_VOWEL_MS:
            problems.append(f"{ms:.0f} ms of vowel-like sound before the part taken as the vowel; "
                            "the voice may be spelling the syllable out, or the wrong part is stretched")
        elif end <= a and ms >= LOUD_ONSET_MS and not any(c in VOICED_ONSETS for c in onset):
            problems.append(f"{ms:.0f} ms of voice before the vowel, as loud as the vowel; it may be heard as m or n")
        elif start >= b and ms >= SECOND_VOWEL_MS and not any(c in SONORANTS for c in coda):
            problems.append(f"{ms:.0f} ms of vowel-like sound after the vowel; the voice may be adding a syllable")
    return problems


def _fading_vowel(spoken: str, syllable) -> list[str]:
    """An open syllable whose i or e loses its upper formants before it ends.

    Back vowels have little up there to lose, so they are not judged.
    """
    if spoken[-1] not in "iey":
        return []
    a, b = syllable.vowel
    freqs = np.linspace(0, guide_mod.SAMPLE_RATE / 2, syllable.sp.shape[1])

    def band(lo, hi):
        return 10 * np.log10(syllable.sp[a:b, (freqs >= lo) & (freqs < hi)].mean(axis=1) + 1e-15)

    brightness = band(1900, 3200) - band(150, 500)
    bright = np.flatnonzero(brightness > np.percentile(brightness, 80) - 6)
    share = (bright[-1] + 1) / (b - a)
    if share < BRIGHT_SHARE:
        return [f"the vowel turns dull for its last {100 * (1 - share):.0f}%; it may be heard as a hum"]
    return []


def _quiet(spans, result: guide_mod.Guide) -> list[tuple[int, str]]:
    """Syllables whose loudest note is well below the usual note level."""
    rate = guide_mod.SAMPLE_RATE

    def level(note):
        mid, half = (note.start_s + note.end_s) / 2, (note.end_s - note.start_s) * 0.3
        part = result.audio[int((mid - half) * rate): int((mid + half) * rate)]
        return 10 * np.log10(np.mean(part**2) + 1e-15)

    levels = [max(level(n) for n in notes) for notes in spans]
    usual = float(np.median(levels))
    return [(i, f"sung {usual - lv:.0f} dB quieter than the other syllables")
            for i, lv in enumerate(levels) if lv - usual < QUIET_NOTE_DB]


def check(
    events: list[NoteEvent],
    *,
    speak: guide_mod.Speaker | None = None,
    latin: str = "roman",
    **render_options,
) -> tuple[guide_mod.Guide, list[Finding]]:
    """The guide these events give, and what looks wrong in it, in sung order.

    A syllable that occurs several times is reported where it comes first.
    """
    speak = speak or guide_mod.mac_say(guide_mod.VOICES.get(latin, "Alice"))
    result = guide_mod.render(events, speak=speak, latin=latin, **render_options)

    groups = [g for g in guide_mod._group(events) if not g[0].is_rest]
    spellings = guide_mod.spoken([g[0].syllable for g in groups], [g[0].starts_word for g in groups], latin)
    notes, spans = iter(result.notes), []
    for group in groups:
        spans.append([next(notes) for _ in group])

    problems: dict[int, list[str]] = {}
    seen = set()
    for i, spoken in enumerate(spellings):
        if spoken not in seen:
            seen.add(spoken)
            syllable = guide_mod._analyse(speak(spoken), spoken)
            found = _stray_sounds(spoken, syllable) + _fading_vowel(spoken, syllable)
            if found:
                problems[i] = found
    for i, problem in _quiet(spans, result):
        problems.setdefault(i, []).append(problem)

    findings = [
        Finding(groups[i][0].syllable, spellings[i], spans[i][0].start_s, spans[i][-1].end_s, problem)
        for i in sorted(problems) for problem in problems[i]
    ]
    return result, findings


def excerpts(result: guide_mod.Guide, findings: list[Finding], *, margin_s: float = 0.35) -> np.ndarray:
    """The flagged places cut out of the guide, one after another, for listening.

    Each excerpt keeps its neighbours, because a syllable is judged in context.
    """
    rate = guide_mod.SAMPLE_RATE
    gap = np.zeros(int(0.5 * rate))
    parts, done = [], set()
    for f in findings:
        if f.start_s in done:
            continue
        done.add(f.start_s)
        parts += [result.audio[max(int((f.start_s - margin_s) * rate), 0): int((f.end_s + margin_s) * rate)], gap]
    return np.concatenate(parts) if parts else np.zeros(0)
