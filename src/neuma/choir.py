"""Turn several takes of the same chant into a small choir in a church.

Every take comes from the same guide, so the voices are sample-aligned and in
tune with each other to a few cents: a stack of them sounds like one voice
with a chorus effect, not like several people. Three things make a choir of it:

* pitch: each voice is retuned a few cents off the others (done by the caller,
  see ``detunes``);
* timing: each voice enters a little early or late and wanders slowly around
  that offset, like singers following each other by ear;
* space: voices are spread across the stereo field and the sum is placed in a
  long, dark reverb.

The reverb is a synthetic impulse response (decaying noise), not a measured
church, which keeps the project free of sample files.
"""

from __future__ import annotations

import numpy as np


def detunes(count: int, cents: float, seed: int = 0) -> list[float]:
    """A fixed offset in cents for each voice, spread evenly over ±``cents``
    and shuffled, so that no two voices share one and the choir stays centred."""
    if count == 1:
        return [0.0]
    spread = np.linspace(-cents, cents, count)
    return [float(c) for c in np.random.default_rng(seed).permutation(spread)]


def _smooth_noise(n: int, sample_rate: int, period_s: float, rng) -> np.ndarray:
    """Noise in -1..1 that changes about once per ``period_s``."""
    knots = rng.uniform(-1, 1, int(n / sample_rate / period_s) + 4)
    at = np.linspace(0, len(knots) - 1, n)
    eased = (1 - np.cos((at % 1) * np.pi)) / 2  # cosine interpolation between knots
    i = at.astype(int).clip(0, len(knots) - 2)
    return knots[i] * (1 - eased) + knots[i + 1] * eased


def loosen(audio: np.ndarray, sample_rate: int, *, offset_ms: float, wander_ms: float, seed: int = 0) -> np.ndarray:
    """Delay ``audio`` by ``offset_ms`` plus a slow wander of ±``wander_ms``.

    The delay changes by a few milliseconds per second, far too slowly to be
    heard as a change of pitch.
    """
    n = len(audio)
    rng = np.random.default_rng(seed)
    delay_s = (offset_ms + wander_ms * _smooth_noise(n, sample_rate, 1.5, rng)) / 1000
    read_at = np.arange(n) - delay_s * sample_rate
    return np.interp(read_at, np.arange(n), audio, left=0.0, right=0.0)


def church_impulse(sample_rate: int, *, decay_s: float = 3.5, predelay_ms: float = 20, seed: int = 0) -> np.ndarray:
    """A stereo impulse response, shape (n, 2): noise that takes ``decay_s`` to
    fall by 60 dB, with the high frequencies dying about three times faster, as
    they do in a large stone room."""
    rng = np.random.default_rng(seed)
    n = int(decay_s * 1.2 * sample_rate)
    t = np.arange(n) / sample_rate
    freqs = np.fft.rfftfreq(n, 1 / sample_rate)
    dark = 1 / (1 + (freqs / 1200) ** 2)  # keeps what is below about 1.2 kHz
    channels = []
    for _ in range(2):
        noise = rng.standard_normal(n)
        low = np.fft.irfft(np.fft.rfft(noise) * dark, n)
        high = noise - low
        tail = low * 10 ** (-3 * t / decay_s) + 0.5 * high * 10 ** (-3 * t / (decay_s / 3))
        tail *= np.minimum(t / 0.04, 1.0)  # the room takes 40 ms to fill
        channels.append(np.concatenate([np.zeros(int(predelay_ms / 1000 * sample_rate)), tail]))
    impulse = np.stack(channels, axis=1)
    return impulse / np.sqrt((impulse**2).sum(axis=0).mean())


def _convolve(signal: np.ndarray, impulse: np.ndarray) -> np.ndarray:
    n = len(signal) + len(impulse) - 1
    size = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(signal, size) * np.fft.rfft(impulse, size), size)[:n]


def reverb(stereo: np.ndarray, sample_rate: int, *, decay_s: float = 3.5, wet: float = 0.3, seed: int = 0) -> np.ndarray:
    """Add the church to a stereo signal. The result is longer by the tail."""
    impulse = church_impulse(sample_rate, decay_s=decay_s, seed=seed)
    tail = np.stack([_convolve(stereo[:, c], impulse[:, c]) for c in range(2)], axis=1)
    out = wet * tail
    out[: len(stereo)] += (1 - wet) * stereo
    return out


def mix(
    voices: list[np.ndarray],
    sample_rate: int,
    *,
    spread_ms: float = 25,
    width: float = 0.6,
    decay_s: float = 3.5,
    wet: float = 0.3,
    seed: int = 0,
) -> np.ndarray:
    """Mix mono takes of the same length-ish into a stereo choir, shape (n, 2).

    ``spread_ms`` is how far apart the voices may be in time, ``width`` how
    much of the stereo field they fill (0 mono, 1 hard left to hard right),
    ``decay_s`` and ``wet`` the length and amount of reverb (``wet=0`` for none).
    """
    rng = np.random.default_rng(seed)
    count = len(voices)
    n = max(len(v) for v in voices)
    offsets = rng.uniform(0, spread_ms, count) if count > 1 else np.zeros(1)
    offsets -= offsets.min()
    positions = rng.permutation(np.linspace(-width, width, count)) if count > 1 else np.zeros(1)

    stereo = np.zeros((n, 2))
    for i, voice in enumerate(voices):
        voice = np.pad(voice, (0, n - len(voice)))
        voice = voice / np.sqrt(np.mean(voice**2))  # equal loudness
        voice = loosen(voice, sample_rate, offset_ms=offsets[i], wander_ms=spread_ms / 4, seed=seed + 1 + i)
        angle = (positions[i] + 1) * np.pi / 4  # constant-power pan
        stereo[:, 0] += voice * np.cos(angle)
        stereo[:, 1] += voice * np.sin(angle)

    if wet > 0:
        stereo = reverb(stereo, sample_rate, decay_s=decay_s, wet=wet, seed=seed)
    return stereo * 0.7 / np.abs(stereo).max()


def join(pieces: list[np.ndarray], sample_rate: int, *, overlap_s: float = 2.5) -> np.ndarray:
    """Put mixed pieces one after another, e.g. refrain, verse, refrain.

    Each piece ends in its reverb tail, so the next one starts ``overlap_s``
    before the previous file ends: the tail rings on under the new entry, as
    it would in a church, and the pause stays about a breath long.
    """
    overlap = int(overlap_s * sample_rate)
    starts, end = [], 0
    for piece in pieces:
        starts.append(max(end - overlap, 0))
        end = starts[-1] + len(piece)
    out = np.zeros((end,) + pieces[0].shape[1:])
    for start, piece in zip(starts, pieces):
        out[start : start + len(piece)] += piece
    return out * 0.7 / np.abs(out).max()
