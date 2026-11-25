# Design

neuma reads Gregorian chant in GABC notation and makes ElevenLabs voices sing it.

ElevenLabs has no endpoint that accepts a melody, so neuma builds a rough sung
"guide" locally, has Voice Changer re-voice it, and then corrects the pitch of
what comes back. Only one step talks to ElevenLabs.

## Pipeline

```mermaid
flowchart TD
    subgraph before["On your machine"]
        gabc[/"GABC file"/] --> parse["1. Parse"]
        parse -->|"syllables of notes"| rhythm["2. Rhythm rule"]
        rhythm -->|"note events"| guide["3. Guide track"]
    end
    subgraph el["ElevenLabs servers"]
        vc["4. Voice Changer"]
    end
    subgraph after["On your machine"]
        retune["5. Retune"] -->|"in-tune take.wav"| mix["6. Choir mix"]
        mix --> out[/"final audio"/]
    end
    guide ==>|"upload guide.wav"| vc
    vc ==>|"download take.mp3"| retune
    guide -.->|"melody line, kept locally"| retune
```

The path is a single line: steps 1-3 run locally, step 4 is the round trip to
ElevenLabs (thick arrows), steps 5-6 run locally again. ElevenLabs is not a
side branch; every take passes through it. The dotted arrow is the one thing
that skips it: the intended melody, which step 3 computes and step 5 needs in
order to know what "in tune" means. `elevenlabs.py` is the client for step 4:
it checks the cache and the credit cap, uploads the guide, and saves the reply.

| # | Step | Code | Input | Output | Status |
|---|---|---|---|---|---|
| 1 | Parse | `src/neuma/gabc.py` | GABC text | `Score`: syllables of notes at notated pitch, and bar lines | done, tested |
| 2 | Rhythm rule | `src/neuma/rhythm.py` | `Score`, transposition | list of `NoteEvent(syllable, midi, units)`, rests included | done, tested |
| 3 | Guide track | `src/neuma/guide.py`, `latin.py` | note events | `guide.wav`, the melody line, note timings | done, tested; `neuma guide <file.gabc>` |
| 4 | Voice Changer | `src/neuma/elevenlabs.py` | `guide.wav`, voice id | `<voice>-raw.mp3` in the chosen voice | done, tested |
| 5 | Retune and level | `src/neuma/retune.py` | raw take, melody line, guide | `<voice>.wav`, in tune and evenly loud, plus a tuning report | done, tested |
| 6 | Choir mix | `src/neuma/choir.py` | several retuned takes | `choir.wav`, stereo, with reverb | done, tested |

`src/neuma/pipeline.py` runs steps 1-5 for one voice (`neuma sing <file.gabc>
--voice <name>`) and steps 1-6 for several (`neuma choir <file.gabc> --voices
<name>,<name>`). A choir repeats steps 4 and 5 once per voice, with the same
guide; step 6 is local and can be redone with other settings for free.
`neuma join <files> --out <file>` puts mixed pieces in order (refrain, verse,
refrain), starting each one under the reverb tail of the one before.

## How each step works

**1. Parse.** GABC letters are staff positions, so they become pitches only once
the clef is known. The parser resolves clef and accidentals to MIDI numbers and
keeps the rhythmic signs (dot, episema, quilisma) as flags on each note.

**2. Rhythm rule.** Chant has no meter. Every note is one unit; a dot doubles it,
an episema or a following quilisma makes it 1.5; bar lines become breaths or
rests. The table is in the module docstring.

**3. Guide track.** Voice Changer takes audio only, no text, so the guide must
carry the words.

- Each syllable is respelled and spoken by a macOS voice (`say`), which is
  free. Two pronunciations are offered (`--latin`): `roman`, where an Italian
  voice reads Latin nearly as written (`cae` becomes `ce`, `ju` becomes `iu`),
  and `polish`, where a Polish voice gets `c` as "ts" for free and has to be
  kept from reading Latin the Polish way (`ci` becomes `tsji`, `qui` `kwi`).
- Syllables are spoken alone, so a voice can misread one: spell out a cluster
  it cannot start a word with (`cta` as "ci-ta") or expand an abbreviation.
  `ct`, `pt` and `ps` are therefore divided for speech (`fac-ta`), and every
  syllable of the chant was checked for having exactly one vowel.
- The vowel of a spoken syllable is the first loud voiced stretch of at least
  80 ms. Loudness alone is not enough: a rolled "r" opens with a burst louder
  than the vowel, and a nasal after the vowel can be louder too. A "p" gets
  60 ms of silence put back before it, since trimming removed its closure.
- `neuma check <file.gabc>` (`src/neuma/check.py`) measures every spoken
  syllable for these faults before anything is sent: a loud voiced stretch
  that is not the vowel, an "i" or "e" that turns dull before it ends, a
  syllable much quieter than the rest. It writes the flagged places to
  `check.wav`. It finds what has gone wrong before, not everything.
- The WORLD vocoder splits each syllable into onset consonants, vowel and tail,
  stretches only the vowel to the note lengths, and replaces the spoken pitch
  with the melody. A note starts on its vowel; consonants take their time from
  the end of the previous note and are shortened if they would crowd it.
- The melody line is the stepped note pitches passed through a second-order
  low-pass filter, which joins notes with a short glide (80 ms by default).

**4. Voice Changer.** The one network step. It returns the guide in a real
voice, with timing kept exactly, but with pitch 300-700 cents off: the model
treats pitch as intonation, not melody.

**5. Retune.** Because timing survives, the melody can be put back. The gentle
variant moves the take only by its slow pitch error (anything slower than
150 ms) and leaves the voice's own fast movement alone, which sounds less
robotic than imposing the melody line outright. The correction goes through
the WORLD vocoder; a waveform method (PSOLA) was tried and sounded no better.

Loudness is restored the same way. Voice Changer swallows some syllables: in
one refrain take the notes came back spread over 24 dB, where the guide has
them within a few. Each note is brought to the level it has in the guide,
measured over its middle 60%, with the gain gliding between notes. The boost
is limited (9 dB by default), because a note that came back as a whisper is
mostly noise.

**6. Choir mix.** Every take follows the same guide, so the voices come back
sample-aligned and, after retuning, on exactly the same pitch: stacked as they
are, they sound like one voice with an effect on it. The mix pulls them apart
again. Each voice is retuned a few cents off the others (up to 8), enters up
to 25 ms late and drifts a few milliseconds around that, and stands at its own
place in the stereo field. Each is also made a little warmer: 3 dB more
around 250 Hz and 4 dB less above 3.5 kHz, because the re-voiced takes
sounded cold. The sum goes through a reverb whose impulse
response is generated, not recorded: noise that decays over 3.5 seconds, with
the high frequencies dying three times faster, as in a stone church.

## ElevenLabs API

All calls are in `src/neuma/elevenlabs.py`. The key is read from the
`ELEVENLABS_API_KEY` environment variable and sent as the `xi-api-key` header.

The calls are plain HTTP (`httpx`), not the
[official SDK](https://github.com/elevenlabs/elevenlabs-python): three simple
endpoints do not need it, and a thin client keeps the cache and the credit
cap in one place, in front of the network, and easy to test without it.

| Call | Purpose | Cost |
|---|---|---|
| `POST /v1/voice-changer/{voice_id}` | re-voice the guide | documented as 1,000 credits per minute of input; measured about 1,200 on the free plan |
| `GET /v1/voices` | list usable voices | free |
| `GET /v1/user/subscription` | read remaining quota | free |

The Voice Changer request is multipart: the guide as `audio`, plus `model_id`
(`eleven_multilingual_sts_v2`), `seed` and optional `voice_settings`. The
response body is the audio itself, MP3 at 44.1 kHz, 128 kbps (the best format
the free plan allows without restrictions).

Two guards sit in front of the network:

- **Cache.** The request is hashed (SHA-256 over the audio bytes and every
  parameter). If that hash is on disk, the file is returned and nothing is sent.
- **Credit cap.** Each client has a `max_credits` budget. A call whose estimated
  cost would exceed it raises before any request is made.

## Files on disk

`.cache/`, `out/` and `.env` are git-ignored; only `docs/samples/` is committed.
With `--latin polish` the output directory is `out/<chant>-polish/`.

| Path | What | Format |
|---|---|---|
| `.cache/say/<hash>.wav` | one spoken syllable per file | WAV, 22.05 kHz, 16-bit mono |
| `.cache/elevenlabs/<hash>.mp3` | a Voice Changer response | MP3, 44.1 kHz, 128 kbps |
| `.cache/elevenlabs/<hash>.json` | the request that produced it, estimated credits, timestamp | JSON |
| `out/<chant>/guide.wav` | guide track | WAV, 22.05 kHz, 16-bit mono |
| `out/<chant>/pitch.npy` | intended melody in Hz, one value per 5 ms | NumPy array |
| `out/<chant>/notes.json` | start, end, pitch and syllable of every note | JSON |
| `out/<chant>/<voice>-raw.mp3` | copy of a Voice Changer take | MP3 |
| `out/<chant>/<voice>.wav` | retuned take | WAV, 44.1 kHz, 16-bit mono |
| `out/<chant>/check.wav` | the places `neuma check` flagged, cut from the guide | WAV, 22.05 kHz, 16-bit mono |
| `out/<chant>/choir.wav` | the mixed choir | WAV, 44.1 kHz, 16-bit stereo |
| `docs/samples/*.mp3` | the samples played by the project page (`docs/index.html`, served by GitHub Pages); the only audio that is committed | MP3, stereo or mono |

The caches are keyed by content, so they are safe to delete: spoken syllables
are regenerated for free, Voice Changer takes cost credits again.

## Known limits

- Voice Changer does not preserve pitch, so step 5 is required, and it costs
  some naturalness: the result is in tune but still closer to robotic than human.
- How far off Voice Changer lands varies from take to take and from voice to
  voice: median errors from 70 to 750 cents were seen.
- The choir's differences in pitch and timing are added by rule. All voices
  still share one guide, so they breathe and shape every syllable identically.
- The line is not legato: syllables come from speech, one at a time. Smoothing
  the guide's loudness did not help (see the README).
- The guide's speech source is macOS-only.
- Pitch measurement near consonants is unreliable; tuning figures are medians
  over the middle of each note.
