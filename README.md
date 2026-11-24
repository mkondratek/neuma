# neuma

Gregorian chant, sung by AI voices.

neuma reads chant in [GABC](https://gregorio-project.github.io/gabc/) notation
and makes [ElevenLabs](https://elevenlabs.io) voices sing it. The first chant is
the Advent hymn *Rorate caeli desuper*.

It is an experiment: can a speech model be made to sing a melody written a
thousand years before it existed? The short answer so far is "yes, with help,
and it still sounds more like a robot than a monk".

## Status

Work in progress.

- [x] Read GABC into notes with pitch and length
- [x] Render a guide track that carries the words and the melody
- [x] One voice, refrain only, as a proof of concept
- [ ] One voice, whole chant, from the command line
- [ ] A small choir with church reverb
- [ ] Audio samples here

## How it works

ElevenLabs has no endpoint that takes a melody, so neuma goes around:

1. **Parse** the GABC file into syllables and notes.
2. **Apply a rhythm rule.** Chant has no meter; every note is one pulse unless a
   sign lengthens it.
3. **Render a guide track** locally: each syllable is spoken by a system voice,
   then stretched and re-pitched to the melody, with glides between notes.
4. **Send the guide through ElevenLabs Voice Changer**, which returns it in a
   real-sounding voice.
5. **Retune.** Voice Changer keeps the timing but not the pitch, so the melody
   is put back afterwards.

[docs/design.md](docs/design.md) has the details: components, the ElevenLabs
calls, and what is cached where.

## What I learned so far

- Voice Changer treats pitch as intonation, not melody. Given a guide that is
  in tune to a few cents, it returns notes 300 to 700 cents flat, with the
  intervals bent. Timing and the shape of the melody survive.
- Because timing survives, pitch can be corrected afterwards. Correcting only
  the slow pitch error, and leaving the voice's own fast movement alone, sounds
  better than imposing the melody outright.
- The result is in tune and recognisably a voice, but closer to robotic than
  human.

## Try it

Needs macOS (the guide uses the built-in `say` voices, with the Italian voice
"Alice" installed) and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

```bash
uv run pytest
```

Render a guide track. This is local and free:

```bash
uv run neuma guide chants/rorate-caeli/refrain.gabc
```

It writes `out/refrain/guide.wav`. Useful options: `--transpose` (semitones),
`--unit` (seconds per note), `--glide` (milliseconds between notes).

The ElevenLabs step currently lives in `experiments/` and needs an API key in
the `ELEVENLABS_API_KEY` environment variable, with access to Speech to Speech.
Every response is cached on disk, and each run has a credit cap, so re-runs
cost nothing.

## Credits

- Chant transcriptions come from [GregoBase](https://gregobase.selapa.net/) and
  are CC0. See [chants/README.md](chants/README.md).
- Voices by [ElevenLabs](https://elevenlabs.io).
- Pitch analysis and resynthesis use [WORLD](https://github.com/mmorise/World)
  and [Praat](https://www.fon.hum.uva.nl/praat/) via
  [Parselmouth](https://github.com/YannickJadoul/Parselmouth).
