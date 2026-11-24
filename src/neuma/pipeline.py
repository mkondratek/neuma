"""GABC file in, sung and retuned take out: the whole path for one voice."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from neuma import guide as guide_mod
from neuma.elevenlabs import ElevenLabs
from neuma.gabc import parse
from neuma.retune import Tuning, retune, singer_key, tuning
from neuma.rhythm import note_events


@dataclass(frozen=True)
class Take:
    guide: Path
    raw: Path  # what Voice Changer returned
    sung: Path  # the same, retuned
    key_shift: int  # semitones between the written key and the one sung
    before: Tuning
    after: Tuning


def render_guide(
    gabc: Path,
    out_dir: Path,
    *,
    transpose: int = 0,
    unit_s: float = 0.36,
    glide_ms: float = 80,
    speak: guide_mod.Speaker | None = None,
) -> guide_mod.Guide:
    """Write ``guide.wav``, ``pitch.npy`` and ``notes.json`` into ``out_dir``."""
    events = note_events(parse(gabc.read_text()), transpose=transpose)
    result = guide_mod.render(events, unit_s=unit_s, glide_ms=glide_ms, speak=speak)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.write(out_dir / "guide.wav")
    np.save(out_dir / "pitch.npy", result.pitch_hz)
    (out_dir / "notes.json").write_text(json.dumps([asdict(n) for n in result.notes], indent=1))
    return result


def sing(
    gabc: Path,
    voice_id: str,
    client: ElevenLabs,
    out_dir: Path,
    *,
    label: str | None = None,
    follow_singer_key: bool = False,
    smooth_ms: float = 150,
    **guide_options,
) -> Take:
    """Guide, Voice Changer, retune. Only the Voice Changer step can cost credits,
    and only when this exact guide has not been sung by this voice before.

    With ``follow_singer_key`` the take is tuned in the key the voice drifted
    to (to the nearest semitone) rather than the key it was asked for, which
    needs less correction. A choir needs every voice in the same key instead.
    """
    guide = render_guide(gabc, out_dir, **guide_options)
    guide_path = out_dir / "guide.wav"
    cached = client.voice_changer(guide_path.read_bytes(), guide.duration_s, voice_id)

    label = label or voice_id[:8]
    raw = out_dir / f"{label}-raw{cached.suffix}"
    raw.write_bytes(cached.read_bytes())

    audio, sample_rate = sf.read(raw, dtype="float64")
    shift = singer_key(audio, sample_rate, guide.notes) if follow_singer_key else 0
    fixed = retune(audio, sample_rate, guide.pitch_hz, smooth_ms=smooth_ms, key_shift=shift)
    sung = out_dir / f"{label}.wav"
    sf.write(sung, fixed, sample_rate, subtype="PCM_16")

    return Take(
        guide=guide_path,
        raw=raw,
        sung=sung,
        key_shift=shift,
        before=tuning(audio, sample_rate, guide.notes, key_shift=shift),
        after=tuning(fixed, sample_rate, guide.notes, key_shift=shift),
    )
