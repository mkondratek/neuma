"""M0 go/no-go: can ElevenLabs Voice Changer sing a melody it is given?

The refrain of "Rorate caeli desuper" is hand-coded here (the GABC parser is M1).
A guide track is built locally at zero cost: each syllable is spoken by a macOS
Italian voice, then the WORLD vocoder stretches its vowel to the note lengths and
replaces its pitch with a smooth melodic contour. The guide goes through Voice
Changer, and the pitch of what comes back is measured against the melody.

    uv run experiments/m0_refrain.py guide
    uv run experiments/m0_refrain.py voices
    uv run experiments/m0_refrain.py sing --voice <voice_id> --max-credits 200
    uv run experiments/m0_refrain.py measure <audio file>
    uv run experiments/m0_refrain.py retune <audio file>

Result (two calls, "George" voice): Voice Changer keeps the timing exactly and
follows the shape of the melody, but treats pitch as intonation. Notes came back
300-700 cents flat with bent intervals, 0 of 20 within 30 cents, whether the
guide sat at D3 or a fifth lower. ``retune`` puts the melody back with WORLD:
in tune (median error 4 cents), but audibly robotic.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyworld as pw
import soundfile as sf

from neuma.elevenlabs import ElevenLabs, voice_changer_credits

SR = 22050
FRAME_MS = 5.0
FRAME_S = FRAME_MS / 1000
OUT = Path("out/m0")
SAY_CACHE = Path(".cache/say")

# Semitones above the final (D). GABC with a c4 clef: d e f g h ix j k.
D, E, F, G, A, Bb, C, D2 = 0, 2, 3, 5, 7, 8, 10, 12

# (c4) RO(f)rá(gh)te(h.) cae(k')li(j) dé(ixji)su(h)per,(hg..) (;)
#      et(h) nu(ixi')bes(h) plu(gf)ant(e) ju(fe)stum.(d.) (::)
# Each entry: (syllable as an Italian speaker would spell it, [(pitch, units), ...]).
# A plain note is 1 unit, a dotted note 2; None is a rest.
REFRAIN: list[tuple[str | None, list[tuple[int, float]]]] = [
    ("ro", [(F, 1)]),
    ("ra", [(G, 1), (A, 1)]),
    ("te", [(A, 2)]),
    ("ce", [(D2, 1)]),
    ("li", [(C, 1)]),
    ("de", [(C, 1), (Bb, 1)]),
    ("su", [(A, 1)]),
    ("per", [(A, 2), (G, 2)]),
    (None, [(0, 1)]),  # (;) half bar
    ("et", [(A, 1)]),
    ("nu", [(Bb, 1)]),
    ("bes", [(A, 1)]),
    ("plu", [(G, 1), (F, 1)]),
    ("ant", [(E, 1)]),
    ("iu", [(F, 1), (E, 1)]),
    ("stum", [(D, 2)]),
]


def hz(semitones_above_final: float, final_midi: float) -> float:
    return 440.0 * 2 ** ((final_midi + semitones_above_final - 69) / 12)


# --- speech source ----------------------------------------------------------


def say(text: str, voice: str) -> np.ndarray:
    """Speak ``text`` with a macOS system voice; cached, mono float64 at SR."""
    key = hashlib.sha256(f"{voice}|{text}|{SR}".encode()).hexdigest()[:16]
    path = SAY_CACHE / f"{key}.wav"
    if not path.exists():
        SAY_CACHE.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["say", "-v", voice, "--file-format=WAVE", f"--data-format=LEI16@{SR}",
             "-o", str(path), text],
            check=True,
        )
    x, sr = sf.read(path, dtype="float64")
    assert sr == SR
    return np.ascontiguousarray(x if x.ndim == 1 else x.mean(axis=1))


@dataclass
class Syllable:
    """WORLD analysis of one spoken syllable, split around its vowel."""

    text: str
    sp: np.ndarray  # spectral envelope per frame
    ap: np.ndarray  # aperiodicity per frame
    voiced: np.ndarray
    core: tuple[int, int]  # frame range of the vowel, the only part that is stretched

    @property
    def onset(self) -> int:
        return self.core[0]

    @property
    def tail(self) -> int:
        return len(self.voiced) - self.core[1]


def analyse_syllable(text: str, voice: str) -> Syllable:
    x = say(text, voice)
    f0, t = pw.harvest(x, SR, f0_floor=60, f0_ceil=500, frame_period=FRAME_MS)
    sp = pw.cheaptrick(x, f0, t, SR)
    ap = pw.d4c(x, f0, t, SR)
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
    c0 = peak
    while c0 > 0 and voiced[c0 - 1] and energy[c0 - 1] > threshold:
        c0 -= 1
    c1 = peak + 1
    while c1 < len(energy) and voiced[c1] and energy[c1] > threshold:
        c1 += 1

    sp = sp / energy[c0:c1].mean()  # equal loudness across syllables
    return Syllable(text, sp, ap, voiced, (c0, c1))


# --- guide assembly ---------------------------------------------------------


def stretch(frames: np.ndarray, length: int) -> np.ndarray:
    """Resample a run of analysis frames to ``length`` frames (linear)."""
    pos = np.linspace(0, len(frames) - 1, length)
    i = np.floor(pos).astype(int)
    j = np.minimum(i + 1, len(frames) - 1)
    w = (pos - i)[:, None]
    return frames[i] * (1 - w) + frames[j] * w


def glide(target: np.ndarray, rise_ms: float, damping: float = 0.85) -> np.ndarray:
    """Turn a stepped pitch line (semitones) into a sung one.

    A second-order low-pass, the usual model of a singer's pitch transition:
    notes are joined by a short portamento with a slight overshoot instead of a
    step. The filter's lag is removed so a glide straddles its note boundary.
    """
    w = 3.4 / (rise_ms / 1000)  # natural frequency for the requested 10-90% rise
    y = np.empty_like(target)
    pos, vel = target[0], 0.0
    for n, u in enumerate(target):
        acc = w * w * (u - pos) - 2 * damping * w * vel
        vel += acc * FRAME_S
        pos += vel * FRAME_S
        y[n] = pos
    lag = int(round(2 * damping / w / FRAME_S))
    return np.concatenate([y[lag:], np.full(lag, y[-1])])


def build_guide(unit_s: float, final_midi: float, voice: str, rise_ms: float, seed: int = 0):
    """Returns (audio, notes, pitch): notes are (start_s, end_s, hz, syllable) for
    measuring, pitch is the intended melody in Hz for every 5 ms frame."""
    syls = [analyse_syllable(text, voice) if text else None for text, _ in REFRAIN]
    bins = next(s for s in syls if s).sp.shape[1]
    unit = round(unit_s / FRAME_S)

    # The last three notes slow down by 15%.
    scale = {}
    flat = [(i, j) for i, (text, ns) in enumerate(REFRAIN) if text for j in range(len(ns))]
    for i, j in flat[-3:]:
        scale[i, j] = 1.15

    sp, ap, voiced, pitch, notes = [], [], [], [], []

    def emit(s_sp, s_ap, s_voiced, s_pitch):
        sp.append(s_sp)
        ap.append(s_ap)
        voiced.append(np.asarray(s_voiced, dtype=bool))
        pitch.append(np.asarray(s_pitch, dtype=float))

    def now() -> int:
        return sum(len(v) for v in voiced)

    for i, (text, ns) in enumerate(REFRAIN):
        nxt = syls[i + 1] if i + 1 < len(syls) else None
        next_first = REFRAIN[i + 1][1][0][0] if i + 1 < len(REFRAIN) else ns[-1][0]
        if text is None:
            n = round(ns[0][1] * unit)
            # Silence; the pitch line already sits on the next note.
            emit(np.full((n, bins), 1e-12), np.ones((n, bins)), np.zeros(n), np.full(n, next_first))
            continue

        s = syls[i]
        c0, c1 = s.core
        lengths = [round(u * unit * scale.get((i, j), 1.0)) for j, (_, u) in enumerate(ns)]
        total = sum(lengths)
        # A note starts on its vowel: consonants take their time from the
        # end of the previous vowel, as singers do.
        emit(s.sp[:c0], s.ap[:c0], s.voiced[:c0], np.full(c0, ns[0][0]))
        start = now()
        core_len = max(total - s.tail - (nxt.onset if nxt else 0), 12)
        ends = np.cumsum(lengths)
        k = np.arange(core_len + s.tail)
        line = np.array([p for p, _ in ns])[np.minimum(np.searchsorted(ends, k, side="right"), len(ns) - 1)]
        emit(stretch(s.sp[c0:c1], core_len), stretch(s.ap[c0:c1], core_len),
             np.ones(core_len), line[:core_len])
        emit(s.sp[c1:], s.ap[c1:], s.voiced[c1:], line[core_len:])
        t = start
        for (p, _), n in zip(ns, lengths):
            notes.append((t * FRAME_S, (t + n) * FRAME_S, hz(p, final_midi), text))
            t += n

    sp, ap = np.concatenate(sp), np.concatenate(ap)
    voiced, steps = np.concatenate(voiced), np.concatenate(pitch)

    line = glide(steps, rise_ms)
    # Slow, small pitch drift (about +-5 cents): a held note is never ruler-flat.
    rng = np.random.default_rng(seed)
    drift = np.convolve(rng.standard_normal(len(line)), np.hanning(160), mode="same")
    line = line + 0.05 * drift / np.abs(drift).max()
    f0 = np.where(voiced, hz(line, final_midi), 0.0)

    audio = pw.synthesize(f0, np.ascontiguousarray(sp), np.ascontiguousarray(ap), SR, FRAME_MS)
    fade = int(0.03 * SR)
    audio[:fade] *= np.linspace(0, 1, fade)
    audio[-fade:] *= np.linspace(1, 0, fade)
    audio *= 0.7 / np.abs(audio).max()
    return audio, notes, hz(line, final_midi)


# --- measuring --------------------------------------------------------------


def measure(path: Path, notes: list) -> dict:
    """Compare the sung pitch of ``path`` with the melody, note by note."""
    x, sr = sf.read(path, dtype="float64")
    x = np.ascontiguousarray(x if x.ndim == 1 else x.mean(axis=1))
    f0, t = pw.harvest(x, sr, f0_floor=60, f0_ceil=700, frame_period=FRAME_MS)

    rows = []
    for start, end, target, text in notes:
        mid, half = (start + end) / 2, (end - start) * 0.3  # the middle 60% of the note
        sel = f0[(t >= mid - half) & (t <= mid + half)]
        sung = sel[sel > 0]
        if len(sung) < 3:
            rows.append((text, target, None, None, 0.0))
            continue
        cents = 1200 * np.log2(np.median(sung) / target)
        wobble = float(np.std(1200 * np.log2(sung / np.median(sung))))
        rows.append((text, target, float(cents), wobble, len(sung) / max(len(sel), 1)))

    errs = np.array([r[2] for r in rows if r[2] is not None])
    # A voice may answer an octave away; judge the melody, not the register.
    octave = 1200 * round(float(np.median(errs)) / 1200) if len(errs) else 0
    print(f"{path}  (octave offset {octave // 1200:+d})")
    print(" syll   target Hz   error cents   wobble   voiced")
    for text, target, cents, wobble, frac in rows:
        if cents is None:
            print(f" {text:<5} {target:9.1f}   (no pitch found)")
        else:
            print(f" {text:<5} {target:9.1f}   {cents - octave:+9.0f}   {wobble:6.0f}   {frac:5.0%}")
    e = np.abs(errs - octave)
    summary = {
        "notes": len(rows),
        "notes_with_pitch": len(errs),
        "median_abs_cents": float(np.median(e)) if len(e) else None,
        "max_abs_cents": float(e.max()) if len(e) else None,
        "within_30_cents": int((e <= 30).sum()),
    }
    print(" ", summary)
    return summary


# --- commands ---------------------------------------------------------------


def cmd_guide(args) -> tuple[Path, list]:
    audio, notes, pitch = build_guide(args.unit, args.final, args.say_voice, args.rise)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "guide.wav"
    sf.write(path, audio, SR, subtype="PCM_16")
    (OUT / "notes.json").write_text(json.dumps(notes, indent=1))
    np.save(OUT / "pitch.npy", pitch)
    seconds = len(audio) / SR
    print(f"wrote {path}: {seconds:.1f}s, ~{voice_changer_credits(seconds)} credits per Voice Changer call")
    return path, notes


def cmd_voices(args) -> None:
    el = ElevenLabs()
    sub = el.subscription()
    print(f"plan {sub.get('tier')}: {sub.get('character_count')} of {sub.get('character_limit')} credits used")
    for v in el.voices():
        labels = v.get("labels") or {}
        print(f" {v['voice_id']}  {v['name']:<28} {v.get('category', ''):<10} "
              f"{labels.get('gender', '')} {labels.get('age', '')} {labels.get('descriptive', '')}")


def cmd_sing(args) -> None:
    path, notes = cmd_guide(args)
    el = ElevenLabs(max_credits=args.max_credits)
    settings = json.loads(args.settings) if args.settings else None
    result = el.voice_changer(path.read_bytes(), sf.info(path).duration, args.voice,
                              voice_settings=settings, seed=args.seed)
    dest = OUT / f"sung-{args.voice[:8]}-{result.stem[:6]}{result.suffix}"
    dest.write_bytes(result.read_bytes())
    print(f"spent ~{el.spent} credits this run -> {dest}")
    measure(dest, notes)


def cmd_measure(args) -> None:
    measure(Path(args.file), json.loads((OUT / "notes.json").read_text()))


def cmd_retune(args) -> None:
    """Put a sung result back on the melody: keep its voice, replace its pitch."""
    src = Path(args.file)
    x, sr = sf.read(src, dtype="float64")
    x = np.ascontiguousarray(x if x.ndim == 1 else x.mean(axis=1))
    f0, t = pw.harvest(x, sr, f0_floor=60, f0_ceil=700, frame_period=FRAME_MS)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)
    pitch = np.load(OUT / "pitch.npy")
    melody = np.interp(t, np.arange(len(pitch)) * FRAME_S, pitch)
    y = pw.synthesize(np.where(f0 > 0, melody, 0.0), sp, ap, sr, FRAME_MS)
    dest = src.with_name(src.stem + "-retuned.wav")
    sf.write(dest, y * 0.7 / np.abs(y).max(), sr, subtype="PCM_16")
    print(f"wrote {dest}")
    measure(dest, json.loads((OUT / "notes.json").read_text()))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--unit", type=float, default=0.36, help="seconds per plain note")
    p.add_argument("--final", type=float, default=50, help="MIDI note of the final (50 = D3)")
    p.add_argument("--rise", type=float, default=80, help="glide time between notes, ms")
    p.add_argument("--say-voice", default="Alice", help="macOS voice that speaks the syllables")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("guide").set_defaults(fn=cmd_guide)
    sub.add_parser("voices").set_defaults(fn=cmd_voices)
    s = sub.add_parser("sing")
    s.add_argument("--voice", required=True)
    s.add_argument("--max-credits", type=int, required=True)
    s.add_argument("--settings", help="voice_settings as JSON")
    s.add_argument("--seed", type=int, default=0)
    s.set_defaults(fn=cmd_sing)
    m = sub.add_parser("measure")
    m.add_argument("file")
    m.set_defaults(fn=cmd_measure)
    r = sub.add_parser("retune")
    r.add_argument("file")
    r.set_defaults(fn=cmd_retune)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
