"""Render note events as a guide track: a rough sung voice for Voice Changer.

Voice Changer takes audio, not text, so the guide has to carry the words, the
timing and (as far as the model will follow it) the melody. Each syllable is
spoken by a speech voice, then the WORLD vocoder stretches its vowel to the
note lengths and replaces the spoken pitch with a smooth melodic line.

Rendering is deterministic: the same events and settings give the same bytes,
which is what lets the Voice Changer cache work.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyworld as pw
import soundfile as sf

from neuma.latin import spoken
from neuma.rhythm import NoteEvent

SAMPLE_RATE = 22050
FRAME_MS = 5.0
FRAME_S = FRAME_MS / 1000
MIN_VOWEL_FRAMES = 12  # 60 ms
MIN_VOWEL_SHARE = 0.5  # of a syllable's time; consonants are shortened to make room

Speaker = Callable[[str], np.ndarray]  # spelling -> mono float64 at SAMPLE_RATE


@dataclass(frozen=True)
class TimedNote:
    start_s: float
    end_s: float
    hz: float
    syllable: str


@dataclass(frozen=True)
class Guide:
    audio: np.ndarray  # mono float64 at SAMPLE_RATE
    pitch_hz: np.ndarray  # the intended melody, one value per 5 ms frame
    notes: tuple[TimedNote, ...]

    @property
    def duration_s(self) -> float:
        return len(self.audio) / SAMPLE_RATE

    def write(self, path: Path | str) -> None:
        sf.write(path, self.audio, SAMPLE_RATE, subtype="PCM_16")


def midi_to_hz(midi):
    return 440.0 * 2 ** ((np.asarray(midi, dtype=float) - 69) / 12)


# --- speech source ----------------------------------------------------------


def mac_say(voice: str = "Alice", cache_dir: Path | str = ".cache/say") -> Speaker:
    """Speak with a macOS system voice; every utterance is cached on disk."""
    cache = Path(cache_dir)

    def speak(text: str) -> np.ndarray:
        key = hashlib.sha256(f"{voice}|{text}|{SAMPLE_RATE}".encode()).hexdigest()[:16]
        path = cache / f"{key}.wav"
        if not path.exists():
            cache.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["say", "-v", voice, "--file-format=WAVE",
                 f"--data-format=LEI16@{SAMPLE_RATE}", "-o", str(path), text],
                check=True,
            )
        x, sr = sf.read(path, dtype="float64")
        if sr != SAMPLE_RATE:
            raise ValueError(f"{path} is at {sr} Hz, expected {SAMPLE_RATE}")
        return np.ascontiguousarray(x if x.ndim == 1 else x.mean(axis=1))

    return speak


@dataclass(frozen=True)
class _Spoken:
    """WORLD analysis of one spoken syllable, split around its vowel."""

    sp: np.ndarray  # spectral envelope per frame
    ap: np.ndarray  # aperiodicity per frame
    voiced: np.ndarray
    vowel: tuple[int, int]  # frame range; the only part that is stretched

    @property
    def onset(self) -> int:
        return self.vowel[0]

    @property
    def tail(self) -> int:
        return len(self.voiced) - self.vowel[1]


def _analyse(x: np.ndarray, text: str) -> _Spoken:
    f0, t = pw.harvest(x, SAMPLE_RATE, f0_floor=60, f0_ceil=500, frame_period=FRAME_MS)
    sp = pw.cheaptrick(x, f0, t, SAMPLE_RATE)
    ap = pw.d4c(x, f0, t, SAMPLE_RATE)
    energy = sp.sum(axis=1)

    active = np.flatnonzero(energy > 1e-3 * energy.max())
    lo, hi = max(active[0] - 2, 0), active[-1] + 3
    f0, sp, ap, energy = f0[lo:hi], sp[lo:hi], ap[lo:hi], energy[lo:hi]
    voiced = f0 > 0
    if not voiced.any():
        raise ValueError(f"no voiced sound in spoken syllable {text!r}")

    # The vowel is the loudest voiced stretch; grow it while it stays loud.
    peak = int(np.argmax(np.where(voiced, energy, 0)))
    threshold = 0.25 * energy[peak]
    a = peak
    while a > 0 and voiced[a - 1] and energy[a - 1] > threshold:
        a -= 1
    b = peak + 1
    while b < len(energy) and voiced[b] and energy[b] > threshold:
        b += 1

    sp = sp / energy[a:b].mean()  # equal loudness across syllables
    return _Spoken(sp, ap, voiced, (a, b))


# --- melody line ------------------------------------------------------------


def glide(steps: np.ndarray, rise_ms: float, damping: float = 0.85) -> np.ndarray:
    """Turn a stepped pitch line (in semitones, one value per frame) into a sung one.

    A second-order low-pass, the usual model of a singer's pitch transition:
    notes are joined by a short portamento with a slight overshoot instead of a
    step. ``rise_ms`` is the 10-90% time of a transition. The filter's lag is
    removed, so a glide straddles its note boundary instead of trailing it.
    """
    w = 3.4 / (rise_ms / 1000)
    out = np.empty(len(steps))
    pos, vel = float(steps[0]), 0.0
    for n, target in enumerate(steps):
        vel += (w * w * (target - pos) - 2 * damping * w * vel) * FRAME_S
        pos += vel * FRAME_S
        out[n] = pos
    lag = int(round(2 * damping / w / FRAME_S))
    return np.concatenate([out[lag:], np.full(lag, out[-1])])


def _drift(n: int, seed: int, cents: float = 5.0) -> np.ndarray:
    """Slow random pitch drift in semitones: a held note is never ruler-flat."""
    noise = np.random.default_rng(seed).standard_normal(n)
    slow = np.convolve(noise, np.hanning(160), mode="same")[:n]  # "same" is 160 long for short clips
    return cents / 100 * slow / max(np.abs(slow).max(), 1e-9)


# --- assembly ---------------------------------------------------------------


def _stretch(frames: np.ndarray, length: int) -> np.ndarray:
    pos = np.linspace(0, len(frames) - 1, length)
    i = np.floor(pos).astype(int)
    j = np.minimum(i + 1, len(frames) - 1)
    w = (pos - i)[:, None]
    return frames[i] * (1 - w) + frames[j] * w


def _resize(part: np.ndarray, length: int) -> np.ndarray:
    """Shorten a run of consonant frames (or flags) to ``length`` by picking frames."""
    if length >= len(part):
        return part
    return part[np.round(np.linspace(0, len(part) - 1, length)).astype(int)]


def _consonant_lengths(groups, syllables, unit) -> tuple[list[int], list[int]]:
    """Frames each syllable may spend on its onset and tail consonants.

    Spoken in isolation, a syllable has long consonants. A sung note is mostly
    vowel, so where a tail and the next onset would take more than their share
    of a note, both are shortened in proportion.
    """
    onsets = [s.onset if s else 0 for s in syllables]
    tails = [s.tail if s else 0 for s in syllables]
    for i, (group, syl) in enumerate(zip(groups, syllables)):
        if syl is None:
            continue
        total = sum(round(e.units * unit) for e in group)
        room = total - max(MIN_VOWEL_FRAMES, round(total * MIN_VOWEL_SHARE))
        follows = i + 1 < len(groups) and syllables[i + 1] is not None
        wanted = tails[i] + (onsets[i + 1] if follows else 0)
        if wanted > room:
            scale = max(room, 0) / wanted
            tails[i] = round(tails[i] * scale)
            if follows:
                onsets[i + 1] = round(onsets[i + 1] * scale)
    return onsets, tails


def _group(events: list[NoteEvent]) -> list[list[NoteEvent]]:
    """Syllables as runs of notes; each rest is a group of its own."""
    groups: list[list[NoteEvent]] = []
    for e in events:
        if e.is_rest or e.starts_syllable or not groups or groups[-1][0].is_rest:
            groups.append([e])
        else:
            groups[-1].append(e)
    return groups


def render(
    events: list[NoteEvent],
    *,
    unit_s: float = 0.36,
    glide_ms: float = 80,
    speak: Speaker | None = None,
    seed: int = 0,
) -> Guide:
    """``unit_s`` is the length of a plain note; ``glide_ms`` the note-to-note glide."""
    speak = speak or mac_say()
    groups = _group(events)
    while groups and groups[-1][0].is_rest:  # trailing silence would only cost credits
        groups.pop()
    sung = [g for g in groups if not g[0].is_rest]
    if not sung:
        raise ValueError("no notes to sing")
    spellings = spoken([g[0].syllable for g in sung], [g[0].starts_word for g in sung])
    voices = iter(_analyse(speak(s), s) for s in spellings)
    syllables = [None if g[0].is_rest else next(voices) for g in groups]
    bins = next(s for s in syllables if s).sp.shape[1]
    unit = unit_s / FRAME_S

    onsets, tails = _consonant_lengths(groups, syllables, unit)

    sp, ap, voiced, steps, notes = [], [], [], [], []
    frames = 0

    def emit(part_sp, part_ap, part_voiced, part_steps):
        nonlocal frames
        sp.append(part_sp)
        ap.append(part_ap)
        voiced.append(np.asarray(part_voiced, dtype=bool))
        steps.append(np.asarray(part_steps, dtype=float))
        frames += len(part_steps)

    for i, (group, syl) in enumerate(zip(groups, syllables)):
        next_onset = onsets[i + 1] if i + 1 < len(groups) else 0
        if syl is None:
            n = round(group[0].units * unit)
            # Silence. The melody line already sits on the next note, so the
            # entry after a pause is not a glide from the previous phrase.
            upcoming = groups[i + 1][0].midi if i + 1 < len(groups) else steps[-1][-1]
            emit(np.full((n, bins), 1e-12), np.ones((n, bins)), np.zeros(n), np.full(n, upcoming))
            continue

        a, b = syl.vowel
        lengths = [round(e.units * unit) for e in group]
        pitches = np.array([e.midi for e in group], dtype=float)
        # A note starts on its vowel: consonants take their time from the end
        # of the previous vowel, as singers do.
        onset, tail = onsets[i], tails[i]
        emit(_resize(syl.sp[:a], onset), _resize(syl.ap[:a], onset),
             _resize(syl.voiced[:a], onset), np.full(onset, pitches[0]))
        start = frames
        vowel = max(sum(lengths) - tail - next_onset, MIN_VOWEL_FRAMES)
        k = np.arange(vowel + tail)
        line = pitches[np.minimum(np.searchsorted(np.cumsum(lengths), k, side="right"), len(group) - 1)]
        emit(_stretch(syl.sp[a:b], vowel), _stretch(syl.ap[a:b], vowel), np.ones(vowel), line[:vowel])
        emit(_resize(syl.sp[b:], tail), _resize(syl.ap[b:], tail), _resize(syl.voiced[b:], tail), line[vowel:])
        for e, n in zip(group, lengths):
            notes.append(TimedNote(start * FRAME_S, (start + n) * FRAME_S, float(midi_to_hz(e.midi)), e.syllable))
            start += n

    sp, ap = np.concatenate(sp), np.concatenate(ap)
    voiced = np.concatenate(voiced)
    line = glide(np.concatenate(steps), glide_ms) + _drift(frames, seed)
    pitch_hz = midi_to_hz(line)

    audio = pw.synthesize(np.where(voiced, pitch_hz, 0.0), np.ascontiguousarray(sp),
                          np.ascontiguousarray(ap), SAMPLE_RATE, FRAME_MS)
    fade = int(0.03 * SAMPLE_RATE)
    audio[:fade] *= np.linspace(0, 1, fade)
    audio[-fade:] *= np.linspace(1, 0, fade)
    audio *= 0.7 / np.abs(audio).max()
    return Guide(audio, pitch_hz, tuple(notes))
