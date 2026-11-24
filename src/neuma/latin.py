"""Respell Latin syllables so an Italian speech voice says them as church Latin.

Ecclesiastical Latin is pronounced almost exactly as Italian is spelled, so
most syllables pass through untouched: soft c and g before e and i, "gn",
"sc", "qu" and silent h already come out right. Only the spellings Italian
does not share need rewriting.
"""

from __future__ import annotations

import unicodedata

VOWELS = "aeiou"


def spoken(syllables: list[str], starts_word: list[bool]) -> list[str]:
    """One pronounceable spelling per syllable; both lists run in sung order."""
    plain = [_plain(s) for s in syllables]
    out = []
    for i, syl in enumerate(plain):
        if not syl:
            raise ValueError(f"nothing to pronounce in syllable {syllables[i]!r}")
        inside_word = i + 1 < len(plain) and not starts_word[i + 1]
        nxt = plain[i + 1] if inside_word else ""
        prev = plain[i - 1] if i > 0 and not starts_word[i] else ""

        # "ti" before a vowel is "tsi" (gra-ti-a), but not after s, t or x.
        if syl.endswith("ti") and nxt and nxt[0] in VOWELS:
            before = syl[-3:-2]
            if before == "c":  # san-cti-o: Italian has no "ctz", so spell the sounds
                syl = syl[:-3] + "ktsi"
            elif before not in ("s", "t", "x"):
                syl = syl[:-2] + "zi"
        # A doubled soft consonant is split by the syllable break: ec-ce, ag-ger.
        if syl[-1] in "cg" and nxt[:1] == syl[-1] and nxt[1:2] in ("e", "i"):
            syl = syl[:-1] + ("t" if syl[-1] == "c" else "d")
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
