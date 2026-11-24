from pathlib import Path

import pytest

from neuma.gabc import parse
from neuma.rhythm import NoteEvent, note_events

CHANT = Path(__file__).parent.parent / "chants" / "rorate-caeli"


def units(source: str) -> list[float]:
    return [e.units for e in note_events(parse(source))]


def test_refrain_of_rorate_caeli():
    events = note_events(parse((CHANT / "refrain.gabc").read_text()))

    assert [e.units for e in events] == pytest.approx([
        1, 1, 1, 2, 1, 1, 1, 1, 1, 2, 2,            # Rorate caeli desuper,
        1,                                          # half bar
        1, 1, 1, 1, 1, 1, 1.15, 1.15, 2.3,          # et nubes pluant justum.
        3,                                          # double bar
    ])
    assert [e.midi for e in events if not e.is_rest] == [
        53, 55, 57, 57, 62, 60, 60, 58, 57, 57, 55, 57, 58, 57, 55, 53, 52, 53, 52, 50,
    ]
    assert events[1] == NoteEvent("rá", 55, 1.0, starts_syllable=True)
    assert events[2] == NoteEvent("rá", 57, 1.0, starts_syllable=False)
    assert events[11] == NoteEvent("", None, 1.0)


def test_transpose_moves_every_note_and_no_rest():
    events = note_events(parse("(c4) a(d) (;) b(j)"), transpose=-7)
    assert [e.midi for e in events] == [43, None, 53]


def test_dot_wins_over_episema():
    assert units("(c4) a(h_) b(h.) c(h._)") == [1.5, 2, 2]


def test_note_before_a_quilisma_is_held_even_across_syllables():
    assert units("(c4) a(ghwi)") == [1.5, 1, 1]
    assert units("(c4) a(g) b(hwi)") == [1.5, 1, 1]
    assert units("(c4) a(g.) b(hwi)") == [2, 1, 1]


def test_quarter_bar_is_a_breath_taken_from_the_note_before():
    assert units("(c4) a(h) (,) b(h)") == [0.75, 0.25, 1]
    assert units("(c4) a(h.) (`) b(h)") == [1.75, 0.25, 1]


def test_bar_rests():
    assert units("(c4) a(h) (;) b(h) (:) c(h)") == [1, 1, 1, 2, 1]


def test_cadence_slows_the_last_three_notes_before_a_double_bar():
    assert units("(c4) a(h) b(h) c(h) d(h.) (::)") == pytest.approx([1, 1.15, 1.15, 2.3, 3])


def test_consecutive_bars_make_one_pause():
    assert units("(c4) a(h) (;) (:) b(h)") == [1, 1, 1]


def test_every_verse_has_a_positive_length_for_every_event():
    for name in ("verse-1", "verse-2", "verse-3", "verse-4"):
        events = note_events(parse((CHANT / f"{name}.gabc").read_text()))
        assert all(e.units > 0 for e in events)
        assert events[-1].is_rest and events[-1].units == 3
