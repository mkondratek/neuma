"""Parse GABC, the plain-text notation for Gregorian chant used by Gregorio.

A GABC body is a run of ``text(notes)`` groups::

    (c4) RO(f)rá(gh)te(h.) cae(k')li(j) dé(ixji)su(h)per,(hg..) (;)

Inside the parentheses the letters ``a``-``m`` are positions on the four-line
staff (``d``, ``f``, ``h``, ``j`` are the lines), so they only become pitches
once a clef says where C or F sits. This parser covers what sung chant needs:
clefs, accidentals, the rhythmic signs and the bar lines. Purely visual signs
(note shapes, spacing, line breaks) are read and dropped.

Pitches are returned as MIDI numbers at notated pitch, with the C of a C clef
as middle C (60) and the F of an F clef as the F below it (53). Chant pitch is
relative, so a singer transposes freely; that happens after parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

BarKind = Literal["virgula", "minima", "minor", "maior", "finalis"]

_C_MAJOR = (0, 2, 4, 5, 7, 9, 11)
_B = 6  # scale degree of B, the note a clef flat lowers
_POSITIONS = "abcdefghijklm"
_CLEF = re.compile(r"(c|f)(b?)([1-4])")
_VISUAL = "vVwWoOsqrR~<>-/!@ \t\n\r`=^"  # shapes, liquescence, spacing, separators
_MARKUP = re.compile(r"<[^>]*>|[{}*]")
_VERSE_LABEL = re.compile(r"^\s*\d+\.\s*")


class GabcError(ValueError):
    pass


@dataclass(frozen=True)
class Note:
    midi: int
    dotted: bool = False  # punctum mora: the note is doubled
    episema: bool = False  # horizontal episema: the note is held slightly
    quilisma: bool = False  # the note before a quilisma is lengthened
    ictus: bool = False  # vertical episema: a grouping mark, no length of its own


@dataclass(frozen=True)
class Syllable:
    text: str
    notes: tuple[Note, ...]
    starts_word: bool


@dataclass(frozen=True)
class Bar:
    kind: BarKind


@dataclass(frozen=True)
class Score:
    headers: dict[str, str]
    items: tuple[Syllable | Bar, ...]

    @property
    def syllables(self) -> list[Syllable]:
        return [i for i in self.items if isinstance(i, Syllable)]


@dataclass
class _Clef:
    letter: str
    line: int
    flat: bool

    def midi(self, position: int, accidental: int) -> int:
        clef_position = 1 + 2 * self.line  # line 1 is "d", line 4 is "j"
        degree = (0 if self.letter == "c" else 3) + position - clef_position
        base = 60 if self.letter == "c" else 48  # the octave of C that holds the clef note
        return base + 12 * (degree // 7) + _C_MAJOR[degree % 7] + accidental

    def degree(self, position: int) -> int:
        return ((0 if self.letter == "c" else 3) + position - (1 + 2 * self.line)) % 7


def parse(source: str) -> Score:
    head, sep, body = source.partition("%%")
    if not sep:
        head, body = "", source
    headers = {}
    for line in head.split(";"):
        key, colon, value = line.strip().partition(":")
        if colon:
            headers[key.strip()] = value.strip()

    items: list[Syllable | Bar] = []
    clef: _Clef | None = None
    accidentals: dict[int, int] = {}  # staff position -> semitones, until the word ends
    pos = 0
    label_allowed = True
    for m in re.finditer(r"\(([^)]*)\)", body):
        raw_text = body[pos : m.start()]
        pos = m.end()
        text = _MARKUP.sub("", raw_text)
        if label_allowed:  # "1. Ne(f)": a verse number is not sung
            text = _VERSE_LABEL.sub("", text)
        starts_word = not items or raw_text[:1].isspace() or not text.strip() or isinstance(items[-1], Bar)
        if starts_word:
            accidentals.clear()

        notes: list[Note] = []
        bars: list[Bar] = []
        clef = _read_group(m.group(1).split("|")[0], clef, accidentals, notes, bars)

        if notes:
            if not text.strip():
                raise GabcError(f"notes without a syllable: ({m.group(1)})")
            items.append(Syllable(text.strip(), tuple(notes), starts_word))
            label_allowed = False
        items.extend(bars)
        if bars:
            accidentals.clear()
    if body[pos:].strip():
        raise GabcError(f"text after the last group: {body[pos:].strip()!r}")
    return Score(headers, tuple(items))


def _read_group(group, clef, accidentals, notes, bars) -> _Clef | None:
    """Read the inside of one ``(...)``; returns the clef in force afterwards."""
    i, n = 0, len(group)
    while i < n:
        ch = group[i]
        nxt = group[i + 1] if i + 1 < n else ""

        if m := _CLEF.match(group, i):
            clef = _Clef(m.group(1), int(m.group(3)), bool(m.group(2)))
            accidentals.clear()
            i = m.end()
        elif ch.lower() in _POSITIONS:
            if clef is None:
                raise GabcError(f"note before any clef in ({group})")
            position = _POSITIONS.index(ch.lower())
            if nxt in ("x", "y", "#"):
                accidentals[position] = {"x": -1, "y": 0, "#": 1}[nxt]
                i += 2
            elif nxt == "+":  # a custos shows the next line's first note; not sung
                i += 2
            else:
                default = -1 if clef.flat and clef.degree(position) == _B else 0
                notes.append(Note(clef.midi(position, accidentals.get(position, default))))
                i += 1
        elif ch in "sv" and notes and group[i - 1] == ch:
            notes.append(Note(notes[-1].midi))  # "hss", "hvv": the note is repeated
            i += 1
        elif ch in "zZ":  # line break, or "z0" for an automatic custos
            i += 1
            while i < n and group[i] in "+-0":
                i += 1
        elif ch in ".'_" or (ch == "w" and notes):
            if not notes:
                raise GabcError(f"{ch!r} before any note in ({group})")
            last = notes[-1]
            if ch == ".":
                if last.dotted and len(notes) > 1:  # "(hg..)": both notes are dotted
                    notes[-2] = _with(notes[-2], dotted=True)
                notes[-1] = _with(last, dotted=True)
            elif ch == "_":
                notes[-1] = _with(last, episema=True)
            elif ch == "'":
                notes[-1] = _with(last, ictus=True)
            else:
                notes[-1] = _with(last, quilisma=True)
            i += 1
            while i < n and group[i].isdigit():  # placement hints such as _0 or '1
                i += 1
        elif ch in ",;:":
            if ch == ":" and nxt == ":":
                bars.append(Bar("finalis"))
                i += 2
            else:
                bars.append(Bar({",": "minima", ";": "minor", ":": "maior"}[ch]))
                i += 1
            while i < n and (group[i].isdigit() or group[i] in "_?'"):  # bar variants
                i += 1
        elif ch == "`":
            bars.append(Bar("virgula"))
            i += 1
        elif ch == "[":  # bracketed attributes, e.g. [alt:...]
            end = group.find("]", i)
            if end < 0:
                raise GabcError(f"unclosed '[' in ({group})")
            i = end + 1
        elif ch in _VISUAL or ch.isdigit():
            i += 1
        else:
            raise GabcError(f"unsupported character {ch!r} in ({group})")
    return clef


def _with(note: Note, **changes) -> Note:
    return Note(**{**note.__dict__, **changes})
