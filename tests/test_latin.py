from pathlib import Path

import pytest

from neuma.gabc import parse
from neuma.latin import spoken

CHANT = Path(__file__).parent.parent / "chants" / "rorate-caeli"


def say(words: str, style: str = "roman") -> list[str]:
    """``"gra-ti-a ple-na"`` -> spoken spellings, with word boundaries at spaces."""
    syllables, starts = [], []
    for word in words.split():
        for i, syl in enumerate(word.split("-")):
            syllables.append(syl)
            starts.append(i == 0)
    return spoken(syllables, starts, style)


def test_refrain_of_rorate_caeli():
    syllables = parse((CHANT / "refrain.gabc").read_text()).syllables
    assert spoken([s.text for s in syllables], [s.starts_word for s in syllables]) == [
        "ro", "ra", "te", "ce", "li", "de", "su", "per",
        "et", "nu", "bes", "plu", "ant", "iu", "stum",
    ]


def test_case_accents_and_punctuation_are_dropped():
    assert spoken(["Dó", "mi", "ne,", "tis :"], [True, False, False, True]) == ["do", "mi", "ne", "tis"]


@pytest.mark.parametrize("words, expected", [
    ("cae-li", ["ce", "li"]),
    ("moe-ró-re", ["me", "ro", "re"]),
    ("ju-stum", ["iu", "stum"]),
    ("Je-rú-sa-lem", ["ie", "ru", "sa", "lem"]),
    ("pro-phé-ta", ["pro", "fe", "ta"]),
    ("ca-thó-li-cam", ["ca", "to", "li", "cam"]),
    ("ky-ri-e", ["ki", "ri", "e"]),
])
def test_spellings_italian_lacks(words, expected):
    assert say(words) == expected


@pytest.mark.parametrize("words, expected", [
    ("grá-ti-a", ["gra", "zi", "a"]),
    ("san-cti-fi-ca-ti-ó-nis", ["sanc", "ti", "fi", "ca", "zi", "o", "nis"]),
    ("af-fli-cti-ó-nem", ["af", "flic", "zi", "o", "nem"]),
    ("hó-sti-a", ["ho", "sti", "a"]),          # not after s
    ("hós-ti-a", ["hos", "ti", "a"]),          # however the syllables are divided
    ("pa-ti a-mo", ["pa", "ti", "a", "mo"]),   # not across a word boundary
    ("ti-mé-re", ["ti", "me", "re"]),          # not before a consonant
])
def test_ti_before_a_vowel(words, expected):
    assert say(words) == expected


def test_doubled_soft_consonant_across_the_syllable_break():
    assert say("ec-ce") == ["et", "ce"]
    assert say("pec-cá-vi-mus") == ["pec", "ca", "vi", "mus"]  # hard: unchanged


def test_mihi_and_nihil_keep_a_k():
    assert say("mi-hi ni-hil ho-mo") == ["mi", "ki", "ni", "kil", "ho", "mo"]


def test_every_syllable_of_the_chant_has_a_spelling_with_a_vowel():
    for name in ("refrain", "verse-1", "verse-2", "verse-3", "verse-4"):
        syllables = parse((CHANT / f"{name}.gabc").read_text()).syllables
        for s in spoken([s.text for s in syllables], [s.starts_word for s in syllables]):
            assert s.isalpha() and s.islower() and set(s) & set("aeiou"), s


def test_syllable_without_letters_is_an_error():
    with pytest.raises(ValueError):
        spoken(["..."], [True])


@pytest.mark.parametrize("words, expected", [
    ("fa-cta est", ["fac", "ta", "est"]),
    ("san-ctus", ["sanc", "tus"]),
    ("scri-ptor", ["scrip", "tor"]),
    ("i-pse", ["ip", "se"]),
    ("psal-mus", ["psal", "mus"]),             # nothing to lean on at the start of a word
    ("et ptó-le", ["et", "pto", "le"]),
    ("abs-cón-di-sti", ["aps", "con", "di", "sti"]),
])
def test_clusters_a_lone_syllable_cannot_start_with(words, expected):
    assert say(words) == expected


@pytest.mark.parametrize("words, expected", [
    ("cae-li", ["ce", "lij"]),                          # Polish c is already "ts"; j keeps a final i bright
    ("ec-ce", ["ek", "ce"]),
    ("pec-cá-vi-mus", ["pek", "ka", "wij", "mus"]),
    ("san-ctus", ["sank", "tus"]),
    ("ju-stum", ["ju", "stum"]),
    ("Ie-sus", ["je", "sus"]),
    ("qui-a", ["kwij", "a"]),
    ("san-guis", ["san", "gwis"]),
    ("di-xit", ["dij", "ksjit"]),
    ("grá-ti-a", ["gra", "tsjij", "a"]),
    ("hó-sti-a", ["ho", "stij", "a"]),
    ("cí-vi-tas", ["tsjij", "wij", "tas"]),               # not the soft Polish "ci"
    ("Si-on", ["sjij", "on"]),
    ("mi-hi", ["mij", "hij"]),                            # h is sounded
    ("lau-da-vé-runt", ["lał", "da", "we", "runt"]),
    ("Je-rú-sa-lem", ["je", "ru", "sà", "lem"]),
])
def test_polish_style(words, expected):
    assert say(words, "polish") == expected


def test_unknown_style_is_refused():
    with pytest.raises(ValueError, match="roman"):
        say("a-men", "klingon")


def test_a_lone_us_is_not_the_english_word():
    assert say("me-us De-us") == ["me", "hus", "de", "hus"]
    assert say("Dó-mi-nus") == ["do", "mi", "nus"]
