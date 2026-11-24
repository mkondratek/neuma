"""Command line: ``neuma guide chants/rorate-caeli/refrain.gabc``."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from neuma import guide
from neuma.elevenlabs import voice_changer_credits
from neuma.gabc import parse
from neuma.rhythm import note_events


def cmd_guide(args) -> None:
    source = Path(args.gabc)
    events = note_events(parse(source.read_text()), transpose=args.transpose)
    result = guide.render(
        events,
        unit_s=args.unit,
        glide_ms=args.glide,
        speak=guide.mac_say(args.say_voice),
    )
    out = Path(args.out or Path("out") / source.stem)
    out.mkdir(parents=True, exist_ok=True)
    result.write(out / "guide.wav")
    np.save(out / "pitch.npy", result.pitch_hz)
    (out / "notes.json").write_text(json.dumps([asdict(n) for n in result.notes], indent=1))
    print(f"{out / 'guide.wav'}: {len(result.notes)} notes, {result.duration_s:.1f}s, "
          f"~{voice_changer_credits(result.duration_s)} credits per Voice Changer call")


def main() -> None:
    p = argparse.ArgumentParser(prog="neuma", description="Gregorian chant, sung by ElevenLabs voices")
    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("guide", help="render the guide track for a GABC file (free, local)")
    g.add_argument("gabc")
    g.add_argument("--out", help="output directory (default: out/<file name>)")
    g.add_argument("--transpose", type=int, default=0, help="semitones from notated pitch")
    g.add_argument("--unit", type=float, default=0.36, help="seconds per plain note")
    g.add_argument("--glide", type=float, default=80, help="glide between notes, ms")
    g.add_argument("--say-voice", default="Alice", help="macOS voice that speaks the syllables")
    g.set_defaults(fn=cmd_guide)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
