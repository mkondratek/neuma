import io

import httpx
import numpy as np
import pytest
import soundfile as sf

from neuma import pipeline
from neuma.elevenlabs import BudgetExceeded, ElevenLabs
from neuma.guide import SAMPLE_RATE

from test_guide import fake_speaker

GABC = "name:Test;\n%%\n(c4) RO(f)rá(gh)te(h.) (::)"


def flat_singer(cents: float):
    """A fake Voice Changer: returns a buzz that holds one pitch, ``cents`` off F3."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        t = np.arange(int(1.6 * SAMPLE_RATE)) / SAMPLE_RATE
        hz = 174.61 * 2 ** (cents / 1200)
        buzz = 0.2 * sum(np.sin(2 * np.pi * hz * h * t) / h for h in range(1, 16))
        buffer = io.BytesIO()
        sf.write(buffer, buzz, SAMPLE_RATE, format="WAV", subtype="PCM_16")
        return httpx.Response(200, content=buffer.getvalue())

    return httpx.MockTransport(handler), calls


@pytest.fixture
def chant(tmp_path):
    path = tmp_path / "test.gabc"
    path.write_text(GABC)
    return path


def run(chant, tmp_path, transport, max_credits=100, **options):
    client = ElevenLabs("key", cache_dir=tmp_path / "cache", max_credits=max_credits, transport=transport)
    take = pipeline.sing(chant, "voice0000000000000000", client, tmp_path / "out",
                         speak=fake_speaker, unit_s=0.3, **options)
    return take, client


def test_sing_writes_guide_raw_take_and_retuned_take(chant, tmp_path):
    transport, calls = flat_singer(-250)
    take, client = run(chant, tmp_path, transport)

    assert len(calls) == 1 and client.spent > 0
    for path in (take.guide, take.raw, take.sung, tmp_path / "out" / "pitch.npy", tmp_path / "out" / "notes.json"):
        assert path.exists()
    assert sf.info(take.sung).samplerate == SAMPLE_RATE
    # The fake singer holds one wrong pitch; retuning moves it onto all four notes.
    assert take.before.within(30) == 0
    assert take.after.within(30) == 4, take.after.cents


def test_second_run_costs_nothing(chant, tmp_path):
    transport, calls = flat_singer(-250)
    run(chant, tmp_path, transport)
    _, client = run(chant, tmp_path, transport, max_credits=0)
    assert len(calls) == 1 and client.spent == 0


def test_without_budget_nothing_is_sent(chant, tmp_path):
    transport, calls = flat_singer(-250)
    with pytest.raises(BudgetExceeded):
        run(chant, tmp_path, transport, max_credits=0)
    assert calls == []


def test_changing_the_guide_is_a_new_request(chant, tmp_path):
    transport, calls = flat_singer(-250)
    run(chant, tmp_path, transport)
    run(chant, tmp_path, transport, transpose=-2)
    assert len(calls) == 2


def test_following_the_singers_key(chant, tmp_path):
    transport, _ = flat_singer(-250)
    take, _ = run(chant, tmp_path, transport, follow_singer_key=True)
    # F G A A against a held pitch 250 cents under F: the median note is about 5 semitones above it.
    assert take.key_shift < -2
    assert take.after.within(30) == 4


def test_choir_sings_each_voice_once_and_mixes_them(chant, tmp_path):
    transport, calls = flat_singer(-250)
    client = ElevenLabs("key", cache_dir=tmp_path / "cache", max_credits=100, transport=transport)
    voices = [("voice000000000000000a", "anna"), ("voice000000000000000b", "ben")]
    options = dict(speak=fake_speaker, unit_s=0.3, decay_s=1.0)
    result = pipeline.choir(chant, voices, client, tmp_path / "out", **options)

    assert len(calls) == 2
    assert (tmp_path / "out" / "anna.wav").exists() and (tmp_path / "out" / "ben.wav").exists()
    info = sf.info(result.mix)
    assert info.channels == 2 and info.duration > 2.0  # the takes plus the reverb tail
    # The voices are tuned apart, by about the 16 cents asked for.
    apart = [np.median(take.after.found) for take in result.takes]
    assert 8 < abs(apart[0] - apart[1]) < 24

    # Remixing with other settings costs nothing.
    again = ElevenLabs("key", cache_dir=tmp_path / "cache", max_credits=0, transport=transport)
    pipeline.choir(chant, voices, again, tmp_path / "out", wet=0.5, **options)
    assert len(calls) == 2
