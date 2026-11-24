"""Respell Latin syllables so a speech voice says them as church Latin.

Church Latin has no single pronunciation; it follows the singer's country.
Two styles are offered, each spoken by a voice of the matching language:

* ``roman``: the Italianate pronunciation of the Roman books ("che-li",
  "et-che"), spoken by an Italian voice. Latin read as Italian is almost
  right already: soft c and g before e and i, "gn", "sc", "qu" and silent h
  need no help. Only the spellings Italian does not share are rewritten.
* ``polish``: the pronunciation traditional in Poland and, in most respects,
  the rest of central Europe ("tse-li", "ek-tse"), spoken by a Polish voice.
  Polish letters already have these sounds, so the work is the other way
  round: keeping the voice from reading Latin spellings the Polish way.

Syllables are spoken one at a time, which adds a second problem: chant books
divide "fa-cta" and "i-pse", and a voice handed "cta" on its own spells out the
letter ("ci-ta"), adding a vowel. Such clusters are divided for speech instead
("fac-ta", "ip-se"); the notes stay on the same vowels.
"""

from __future__ import annotations

import re
import unicodedata

VOWELS = "aeiouy"
SPLIT_ONSETS = ("ct", "pt", "ps")  # said as two syllables when they start one
# "us" alone (me-us, De-us) is read as the English word, and "ùs" as the
# letters U, S. The Italian h is silent, and with it the word is unknown.
ROMAN_MISREAD = {"us": "hus"}
POLISH_MISREAD = {"sa": "sà"}  # read as the abbreviation S.A. when it stands alone
VOICES = {"roman": "Alice", "polish": "Zosia"}  # macOS voices: Italian, Polish


def spoken(syllables: list[str], starts_word: list[bool], style: str = "roman") -> list[str]:
    """One pronounceable spelling per syllable; both lists run in sung order."""
    if style not in VOICES:
        raise ValueError(f"unknown Latin style {style!r}; choose from {', '.join(VOICES)}")
    plain = [_plain(s) for s in syllables]
    for i in range(1, len(plain)):
        if plain[i][:2] in SPLIT_ONSETS and plain[i - 1] and not starts_word[i]:
            plain[i - 1] += plain[i][0]
            plain[i] = plain[i][1:]
    respell = _roman if style == "roman" else _polish
    out = []
    for i, syl in enumerate(plain):
        if not syl:
            raise ValueError(f"nothing to pronounce in syllable {syllables[i]!r}")
        inside_word = i + 1 < len(plain) and not starts_word[i + 1]
        nxt = plain[i + 1] if inside_word else ""
        prev = plain[i - 1] if i > 0 and not starts_word[i] else ""
        out.append(respell(syl, prev, nxt))
    return out


def _plain(text: str) -> str:
    """Lower-case letters only, with the spellings neither language has spelled out."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if c.isalpha() and not unicodedata.combining(c))
    for old, new in (("ae", "e"), ("oe", "e"), ("æ", "e"), ("œ", "e"), ("ph", "f"), ("th", "t")):
        text = text.replace(old, new)
    return text


def _ti_is_tsi(syl: str, prev: str, nxt: str) -> bool:
    """ "ti" before a vowel is "tsi" (gra-ti-a), but not after s, t or x."""
    return (syl.endswith("ti") and nxt[:1] in tuple(VOWELS)
            and (syl[-3:-2] or prev[-1:]) not in ("s", "t", "x"))


def _roman(syl: str, prev: str, nxt: str) -> str:
    syl, prev, nxt = (s.replace("j", "i").replace("y", "i") for s in (syl, prev, nxt))
    if _ti_is_tsi(syl, prev, nxt):
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
    return ROMAN_MISREAD.get(syl, syl)


def _polish(syl: str, prev: str, nxt: str) -> str:
    if _ti_is_tsi(syl, prev, nxt):
        syl = syl[:-2] + "ci"
    # c is "ts" before e, i, y and "k" everywhere else; Polish c is always "ts".
    syl = re.sub(r"c(?![eiyh])", "k", syl)
    syl = syl.replace("qu", "kw").replace("x", "ks").replace("v", "w")
    if prev.endswith("n") or "ngu" in syl:  # san-guis, lin-gua
        syl = re.sub(r"gu(?=[aeio])", "gw", syl)
    syl = re.sub(r"^i(?=[aeou])", "j", syl)  # iu-stum, Ie-sus
    # Polish softens c, s and z before i ("ci" is like English "chee"); a j keeps
    # them hard. The c is written "ts" there, because the voice spells out "cji".
    syl = re.sub(r"([csz])i", r"\1ji", syl).replace("cji", "tsji")
    syl = syl.replace("au", "ał")  # one syllable, as in "lau-da": Polish "au" is two
    syl = POLISH_MISREAD.get(syl, syl)
    if syl.endswith("bs"):
        syl = syl[:-2] + "ps"
    # The voice lets an "i" that ends an utterance trail off into a dull hum,
    # which is then stretched over the note ("cae-lum" for "cae-li"). A j is
    # the same sound and keeps the i bright to its end.
    if syl.endswith("i"):
        syl += "j"
    return syl
