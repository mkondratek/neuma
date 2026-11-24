"""Command line.

    neuma guide chants/rorate-caeli/refrain.gabc          local and free
    neuma voices                                          quota and voices
    neuma sing chants/rorate-caeli/refrain.gabc --voice George --max-credits 200
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from neuma import guide, pipeline
from neuma.elevenlabs import BudgetExceeded, ElevenLabs, voice_changer_credits


def _guide_options(args) -> dict:
    return {
        "transpose": args.transpose,
        "unit_s": args.unit,
        "glide_ms": args.glide,
        "speak": guide.mac_say(args.say_voice),
    }


def _out_dir(args) -> Path:
    return Path(args.out or Path("out") / Path(args.gabc).stem)


def cmd_guide(args) -> None:
    out = _out_dir(args)
    result = pipeline.render_guide(Path(args.gabc), out, **_guide_options(args))
    print(f"{out / 'guide.wav'}: {len(result.notes)} notes, {result.duration_s:.1f}s, "
          f"~{voice_changer_credits(result.duration_s)} credits per Voice Changer call")


def cmd_voices(args) -> None:
    client = ElevenLabs()
    try:
        sub = client.subscription()
        print(f"plan {sub.get('tier')}: {sub.get('character_count')} of "
              f"{sub.get('character_limit')} credits used")
    except Exception as e:  # the key may lack the User permission; voices still work
        print(f"quota unavailable ({e})")
    for v in client.voices():
        labels = v.get("labels") or {}
        print(f"{v['voice_id']}  {v['name']:<40} {labels.get('gender', ''):<8} {labels.get('age', '')}")


def _voice(client: ElevenLabs, wanted: str) -> tuple[str, str]:
    """Accept a voice id, or the start of a voice name. Returns (id, label)."""
    if re.fullmatch(r"[A-Za-z0-9]{20}", wanted):
        return wanted, wanted[:8]
    matches = [v for v in client.voices() if v["name"].lower().startswith(wanted.lower())]
    if len(matches) != 1:
        names = ", ".join(v["name"] for v in matches) or "none"
        sys.exit(f"voice {wanted!r} matches {names}; run `neuma voices`")
    return matches[0]["voice_id"], re.split(r"\W", matches[0]["name"])[0].lower()


def cmd_sing(args) -> None:
    client = ElevenLabs(max_credits=args.max_credits)
    voice_id, label = _voice(client, args.voice)
    try:
        take = pipeline.sing(
            Path(args.gabc), voice_id, client, _out_dir(args),
            label=label, follow_singer_key=args.singer_key, smooth_ms=args.smooth,
            **_guide_options(args),
        )
    except BudgetExceeded as e:
        sys.exit(f"not sent: {e}. Pass --max-credits to allow it.")
    print(f"spent ~{client.spent} credits" if client.spent else "served from cache, 0 credits")
    if args.singer_key:
        print(f"sung {take.key_shift:+d} semitones from the written key")
    print(f"as returned: {take.before}")
    print(f"retuned:     {take.after}")
    print(take.sung)


def main() -> None:
    p = argparse.ArgumentParser(prog="neuma", description="Gregorian chant, sung by ElevenLabs voices")
    sub = p.add_subparsers(dest="command", required=True)

    def chant_options(c):
        c.add_argument("gabc")
        c.add_argument("--out", help="output directory (default: out/<file name>)")
        c.add_argument("--transpose", type=int, default=0, help="semitones from notated pitch")
        c.add_argument("--unit", type=float, default=0.36, help="seconds per plain note")
        c.add_argument("--glide", type=float, default=80, help="glide between notes, ms")
        c.add_argument("--say-voice", default="Alice", help="macOS voice that speaks the syllables")

    g = sub.add_parser("guide", help="render the guide track for a GABC file (free, local)")
    chant_options(g)
    g.set_defaults(fn=cmd_guide)

    v = sub.add_parser("voices", help="show quota and available voices (free)")
    v.set_defaults(fn=cmd_voices)

    s = sub.add_parser("sing", help="guide, ElevenLabs Voice Changer, retune")
    chant_options(s)
    s.add_argument("--voice", required=True, help="ElevenLabs voice id, or the start of its name")
    s.add_argument("--max-credits", type=int, default=0,
                   help="credits this run may spend; the default 0 only allows cached takes")
    s.add_argument("--singer-key", action="store_true",
                   help="tune in the key the voice drifted to, not the written one")
    s.add_argument("--smooth", type=float, default=150,
                   help="correct only pitch error slower than this, ms")
    s.set_defaults(fn=cmd_sing)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
