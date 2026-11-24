"""Respell Latin syllables so an Italian speech voice says them as church Latin.

Ecclesiastical Latin is pronounced almost exactly as Italian is spelled, so
most syllables pass through untouched: soft c and g before e and i, "gn",
"sc", "qu" and silent h already come out right. Only the spellings Italian
does not share need rewriting.

Syllables are spoken one at a time, which adds a second problem: chant books
divide "fa-cta" and "i-pse", and a voice handed "cta" on its own spells out the
letter ("ci-ta"), adding a vowel. Such clusters are divided for speech instead
("fac-ta", "ip-se"); the notes stay on the same vowels.
"""

from __future__ import annotations

import unicodedata

VOWELS = "aeiou"
SPLIT_ONSETS = ("ct", "pt", "ps")  # said as two syllables when they start one


def spoken(syllables: list[str], starts_word: list[bool]) -> list[str]:
    """One pronounceable spelling per syllable; both lists run in sung order."""
    plain = [_plain(s) for s in syllables]
    for i in range(1, len(plain)):
        if plain[i][:2] in SPLIT_ONSETS and plain[i - 1] and not starts_word[i]:
            plain[i - 1] += plain[i][0]
            plain[i] = plain[i][1:]
    out = []
    for i, syl in enumerate(plain):
        if not syl:
            raise ValueError(f"nothing to pronounce in syllable {syllables[i]!r}")
        inside_word = i + 1 < len(plain) and not starts_word[i + 1]
        nxt = plain[i + 1] if inside_word else ""
        prev = plain[i - 1] if i > 0 and not starts_word[i] else ""

        # "ti" before a vowel is "tsi" (gra-ti-a), but not after s, t or x.
        if syl.endswith("ti") and nxt and nxt[0] in VOWELS:
            before = syl[-3:-2] or prev[-1:]
            if before not in ("s", "t", "x"):
                syl = syl[:-2] + "zi"
        # A doubled soft consonant is split by the syllable break: ec-ce, ag-ger.
        if syl[-1] in "cg" and nxt[:1] == syl[-1] and nxt[1:2] in ("e", "i"):
            syl = syl[:-1] + ("t" if syl[-1] == "c" else "d")
        # "abs" alone comes out as "a-bes"; the b is devoiced before s anyway.
        if syl.endswith("bs"):
            syl = syl[:-2] + "ps"
        # mi-hi and ni-hil keep a hard "k"; every other h is silent, as in Italian.
        if syl.startswith("hi") and prev in ("mi", "ni"):
            syl = "k" + syl[1:]
        out.append(syl)
    return out


def _plain(text: str) -> str:
    """Lower-case letters only, with the digraphs Italian lacks spelled out."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if c.isalpha() and not unicodedata.combining(c))
    for old, new in (("ae", "e"), ("oe", "e"), ("æ", "e"), ("œ", "e"),
                     ("ph", "f"), ("th", "t"), ("j", "i"), ("y", "i")):
        text = text.replace(old, new)
    return text
