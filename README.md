# neuma

Gregorian chant, sung by AI voices.

neuma reads chant in [GABC](https://gregorio-project.github.io/gabc/) notation
and makes [ElevenLabs](https://elevenlabs.io) voices sing it as a small choir.
The first chant is the Advent hymn *Rorate caeli desuper*.

It is an experiment: can a speech model be made to sing a melody written a
thousand years before it existed? The short answer is "yes, with help". One
voice alone still sounds more like a robot than a monk; four of them in a
church are much easier to listen to.

## Listen

**[Play the samples in the browser](https://mkondratek.github.io/neuma/)**, or download them here.
Voices by [elevenlabs.io](https://elevenlabs.io).

| Sample | What it is |
|---|---|
| [rorate-caeli-choir.mp3](docs/samples/rorate-caeli-choir.mp3) | Refrain, verse 1, refrain. Four voices, church reverb, Roman (Italianate) Latin. 64 s |
| [rorate-caeli-choir-polish.mp3](docs/samples/rorate-caeli-choir-polish.mp3) | The same in Polish-style Latin, for comparison |
| [refrain-one-voice.mp3](docs/samples/refrain-one-voice.mp3) | One voice, retuned, no reverb: what the choir is made of |
| [refrain-one-voice-before-retuning.mp3](docs/samples/refrain-one-voice-before-retuning.mp3) | The same take as ElevenLabs returned it: human, and out of tune |
| [refrain-guide.mp3](docs/samples/refrain-guide.mp3) | The local guide track that ElevenLabs was given |

## How it works

ElevenLabs has no endpoint that takes a melody, so neuma goes around:

1. **Parse** the GABC file into syllables and notes.
2. **Apply a rhythm rule.** Chant has no meter; every note is one pulse unless a
   sign lengthens it.
3. **Render a guide track** locally: each syllable is spoken by a system voice,
   then stretched and re-pitched to the melody, with glides between notes.
4. **Send the guide through ElevenLabs Voice Changer**, which returns it in a
   real-sounding voice.
5. **Retune and level.** Voice Changer keeps the timing but not the pitch, and
   swallows some syllables, so the melody and the loudness of each note are
   put back afterwards.
6. **Mix a choir.** Steps 4 and 5 are repeated with other voices; the takes
   are set slightly apart in pitch, time and place, and put in a church reverb.

[docs/design.md](docs/design.md) has the details: components, the ElevenLabs
calls, and what is cached where.

## What worked

- **Timing survives Voice Changer exactly.** That one property carries the
  whole project: because every take stays aligned with the guide, its pitch
  can be corrected afterwards, and several voices can be stacked.
- **Gentle retuning.** Correcting only the slow pitch error (the wrong note)
  and leaving the voice's own fast movement alone gets 85 to 89 of the 91
  notes of verse 1 within 30 cents, and sounds better than imposing the melody
  outright.
- **Levelling by the guide.** A take comes back with notes up to 24 dB apart
  in loudness; the guide knows how loud each one was meant to be, and the
  same alignment that allows retuning allows putting that back.
- **The choir hides the seams.** Four voices and a long reverb cover most of
  what sounds artificial in a single take.
- **A speech voice of the right language as the source of the words.** Church
  Latin read as Italian, or as Polish, is nearly right without any phonetics.
- **Caching every response.** All the mixing, joining and listening tests after
  a take is sung cost nothing.

## What did not

- **Voice Changer does not sing the melody it is given.** It treats pitch as
  intonation. From a guide that is in tune to a few cents it returns notes
  with a median error of 70 to 750 cents, with the intervals bent, differently
  for each voice and each take. Without step 5 there is no chant.
- **A single voice still sounds processed.** The retune rebuilds the voice in
  a vocoder, and the heavier the correction, the more that is heard. Nothing
  tried removed it: a waveform method (PSOLA) sounded no better, and a guide in
  the voice's natural range came back just as far off.
- **Short notes stay a little flat or sharp.** The correction needs about
  150 ms to act, so a few quick single notes end 30 to 50 cents off.
- **The choir is four copies of one performance.** Every voice follows the
  same guide, so they shape each syllable identically; the differences in
  pitch and timing are added by rule.
- **Speaking syllables one at a time has traps.** A voice handed "cta" alone
  spells out the letter ("fa-ci-ta est"); a lone "sa" was read as an
  abbreviation; the Polish voice opens a rolled "r" with a burst louder than
  the vowel ("y-ro-ra-te"), lets a final "i" trail into a hum ("cae-lum") and
  has a "p" too weak to hear ("nubes luant"). Voice Changer turns each into a
  confident wrong word. All of these are worked around, and `neuma check`
  now looks for them before credits are spent, but they were found by ear,
  and a new chant can bring new ones.
- **It is not cheap on a free plan.** Voice Changer cost about 1,200 credits
  per minute of audio (documented: 1,000). Four voices singing the whole
  chant, about two and a half minutes, need more than the 10,000 credits of a
  free month, which is why the sample stops after verse 1.
- **It is not legato.** Chant wants one sustained line; the guide is built
  syllable by syllable from speech, so vowels die away and syllables stand
  apart. A guide with held vowels, shorter consonants, joined syllables and
  lifted accents was tried: the sung take's loudness was measurably
  smoother (notes fading by 4 dB instead of 10), and it sounded worse. The
  measurement was not measuring legato, so the attempt was taken out.
- **macOS only**, because the guide uses the system's `say` voices.

## Try it

Needs macOS (the guide uses the built-in `say` voices: the Italian voice
"Alice", or the Polish voice "Zosia" for `--latin polish`) and
[uv](https://docs.astral.sh/uv/).

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

Check a guide for syllables the speech voice got wrong. Also local and free;
it prints what it measured and writes the flagged places to
`out/refrain/check.wav` to listen to:

```bash
uv run neuma check chants/rorate-caeli/refrain.gabc
```

Church Latin is pronounced differently from country to country. `--latin roman`
(the default) is the Italianate pronunciation, "che-li" and "et-che";
`--latin polish` is the central European one, "tse-li" and "ek-tse". Output
then goes to `out/refrain-polish/`.

Singing needs an ElevenLabs API key in the `ELEVENLABS_API_KEY` environment
variable, with access to Speech to Speech and read access to Voices:

```bash
uv run neuma voices
```

```bash
uv run neuma sing chants/rorate-caeli/refrain.gabc --voice George --transpose -7 --max-credits 200
```

It writes `out/refrain/george.wav` and prints how far off the take was before
and after retuning. Notes that came back too quiet are raised to match the
guide, by 9 dB at most (`--level`, 0 to switch it off). The refrain costs about 190 credits per voice. Every
response is cached on disk, so re-runs cost nothing, and without
`--max-credits` nothing is ever sent.

A choir is the same with several voices. Takes already sung are reused, and
the mix options (`--detune`, `--spread`, `--reverb`, `--wet`, `--warmth`, `--seed`) can be
changed without spending anything:

```bash
uv run neuma choir chants/rorate-caeli/refrain.gabc --voices George,Brian,Bill,Daniel --transpose -7 --max-credits 800
```

Pieces are put together with `join`, which lets each reverb tail ring on under
the next entry:

```bash
uv run neuma join out/refrain/choir.wav out/verse-1/choir.wav out/refrain/choir.wav --out out/rorate.mp3
```

## Credits

- Chant transcriptions come from [GregoBase](https://gregobase.selapa.net/) and
  are CC0. See [chants/README.md](chants/README.md).
- Voices by [ElevenLabs](https://elevenlabs.io), on the free plan: the samples
  are for non-commercial use.
- The code is under the [MIT licence](LICENSE).
- Pitch analysis and resynthesis use [WORLD](https://github.com/mmorise/World)
  via [pyworld](https://github.com/JeremyCCHsu/Python-Wrapper-for-World-Vocoder).
