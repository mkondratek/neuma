"""Turn a parsed chant into timed note events.

Chant has no meter. This is a deliberately simple, explicit reading in the
Solesmes tradition: every note is one equal pulse unless a sign says otherwise.

    plain note                     1 unit
    dotted note                    2 units
    note under an episema          1.5 units
    note before a quilisma         1.5 units
    quarter bar or virgula         a 0.25-unit breath taken from the note before
    half bar                       1 unit of rest
    full bar                       2 units of rest
    double bar                     3 units of rest, and the three notes
                                   before it slow down by 15%

Durations are in units; the renderer decides how long a unit lasts.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from neuma.gabc import Bar, Score

DOTTED = 2.0
HELD = 1.5
BREATH = 0.25
RESTS = {"minor": 1.0, "maior": 2.0, "finalis": 3.0}
CADENCE_NOTES = 3
CADENCE_STRETCH = 1.15


@dataclass(frozen=True)
class NoteEvent:
    """One sung note, or a rest when ``midi`` is None."""

    syllable: str
    midi: int | None
    units: float
    starts_syllable: bool = False
    starts_word: bool = False

    @property
    def is_rest(self) -> bool:
        return self.midi is None


def note_events(score: Score, transpose: int = 0) -> list[NoteEvent]:
    """``transpose`` moves the notated pitch by that many semitones."""
    events: list[NoteEvent] = []
    for item in score.items:
        if isinstance(item, Bar):
            _bar(events, item)
            continue
        for k, note in enumerate(item.notes):
            units = DOTTED if note.dotted else HELD if note.episema else 1.0
            if note.quilisma and events and not events[-1].is_rest:
                events[-1] = replace(events[-1], units=max(events[-1].units, HELD))
            first = k == 0
            events.append(NoteEvent(item.text, note.midi + transpose, units, first, first and item.starts_word))
    return events


def _bar(events: list[NoteEvent], bar: Bar) -> None:
    if not events or events[-1].is_rest:
        return  # nothing sung since the last pause
    if bar.kind in RESTS:
        if bar.kind == "finalis":
            sung = [i for i, e in enumerate(events) if not e.is_rest][-CADENCE_NOTES:]
            for i in sung:
                events[i] = replace(events[i], units=events[i].units * CADENCE_STRETCH)
        events.append(NoteEvent("", None, RESTS[bar.kind]))
    else:
        events[-1] = replace(events[-1], units=events[-1].units - BREATH)
        events.append(NoteEvent("", None, BREATH))
