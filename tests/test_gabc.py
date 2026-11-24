from pathlib import Path

import pytest

from neuma.gabc import Bar, GabcError, Note, parse

CHANT = Path(__file__).parent.parent / "chants" / "rorate-caeli"

D3, E3, F3, G3, A3, Bb3, B3, C4, D4 = 50, 52, 53, 55, 57, 58, 59, 60, 62


def midis(source: str) -> list[int]:
    return [n.midi for s in parse(source).syllables for n in s.notes]


def test_refrain_of_rorate_caeli():
    score = parse((CHANT / "refrain.gabc").read_text())

    assert score.headers["name"] == "Rorate caeli desuper"
    assert score.headers["mode"] == "1"
    assert [s.text for s in score.syllables] == [
        "RO", "rá", "te", "cae", "li", "dé", "su", "per,",
        "et", "nu", "bes", "plu", "ant", "ju", "stum.",
    ]
    assert [[n.midi for n in s.notes] for s in score.syllables] == [
        [F3], [G3, A3], [A3], [D4], [C4], [C4, Bb3], [A3], [A3, G3],
        [A3], [Bb3], [A3], [G3, F3], [E3], [F3, E3], [D3],
    ]
    assert [s.text for s in score.syllables if s.starts_word] == [
        "RO", "cae", "dé", "et", "nu", "plu", "ju",
    ]
    assert [i.kind for i in score.items if isinstance(i, Bar)] == ["minor", "finalis"]


def test_rhythmic_signs_of_the_refrain():
    by_text = {s.text: s.notes for s in parse((CHANT / "refrain.gabc").read_text()).syllables}
    assert by_text["te"] == (Note(A3, dotted=True),)
    assert by_text["cae"] == (Note(D4, ictus=True),)
    assert by_text["per,"] == (Note(A3, dotted=True), Note(G3, dotted=True))  # (hg..)
    assert by_text["nu"] == (Note(Bb3, ictus=True),)


@pytest.mark.parametrize("name, syllables", [
    ("verse-1", 78), ("verse-2", 74), ("verse-3", 64), ("verse-4", 73),
])
def test_verses_parse_and_stay_in_the_mode(name, syllables):
    score = parse((CHANT / f"{name}.gabc").read_text())
    assert len(score.syllables) == syllables
    assert not score.syllables[0].text[0].isdigit()  # "1." is a label, not a syllable
    pitches = {n.midi for s in score.syllables for n in s.notes}
    assert pitches <= {D3, E3, F3, G3, A3, Bb3, C4, D4}  # mode 1, every B flattened
    assert score.items[-1] == Bar("finalis")


@pytest.mark.parametrize("clef, expected", [
    ("c4", D3), ("c3", F3), ("c2", A3), ("c1", C4),
    ("f4", 43), ("f3", 46 + 1), ("f2", D3), ("f1", F3),
])
def test_clef_sets_the_pitch_of_the_bottom_line(clef, expected):
    assert midis(f"({clef}) a(d)") == [expected]


def test_positions_run_diatonically_from_below_the_staff():
    assert midis("(c4) a(abcdefghijklm)") == [45, 47, 48, 50, 52, 53, 55, 57, 59, 60, 62, 64, 65]


def test_flat_lasts_until_the_end_of_the_word():
    assert midis("(c4) a(ixi)b(i) c(i)") == [Bb3, Bb3, B3]


def test_flat_ends_at_a_bar_and_only_touches_its_own_position():
    assert midis("(c4) a(ixih) (,) b(i)") == [Bb3, A3, B3]


def test_flat_may_be_written_ahead_of_its_note():
    assert midis("(c4) do(ixfi)lor(h)") == [F3, Bb3, A3]  # verse 4


def test_natural_and_sharp():
    assert midis("(c4) a(ixiiyi)") == [Bb3, B3]
    assert midis("(c4) a(f#f)") == [F3 + 1]


def test_clef_with_flat_lowers_every_b():
    assert midis("(cb3) a(g) b(g)") == [Bb3, Bb3]
    assert midis("(cb3) a(gyg)") == [B3]


def test_clef_change_mid_score():
    assert midis("(c4) a(j) (c3) b(h)") == [C4, C4]


def test_episema_quilisma_and_repeated_notes():
    (s,) = parse("(c4) a(h_gwhvGFhss)").syllables
    assert s.notes == (
        Note(A3, episema=True), Note(G3, quilisma=True), Note(A3),
        Note(G3), Note(F3), Note(A3), Note(A3),
    )


def test_visual_marks_and_markup_are_dropped():
    score = parse("(c4) <i>A</i>l(h!g/f) {le}(g) lu(f) *(;) ia(e.) (::) (z) (Z-)")
    assert [s.text for s in score.syllables] == ["Al", "le", "lu", "ia"]
    assert [i.kind for i in score.items if isinstance(i, Bar)] == ["minor", "finalis"]


def test_all_bar_kinds():
    bars = [i.kind for i in parse("(c4) a(h) (`) (,) (;) (:) (::)").items if isinstance(i, Bar)]
    assert bars == ["virgula", "minima", "minor", "maior", "finalis"]


def test_body_without_headers():
    assert midis("(c4) a(d)") == [D3]


@pytest.mark.parametrize("source", ["a(h)", "(c4) a(h$)", "(c4) (h)", "(c4) a(.h)", "(c4) a(h) trailing"])
def test_malformed_input_is_rejected(source):
    with pytest.raises(GabcError):
        parse(source)
