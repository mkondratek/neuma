import httpx
import pytest

from neuma.elevenlabs import BudgetExceeded, ElevenLabs, voice_changer_credits


def make_client(tmp_path, max_credits, calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=b"fake-mp3")

    return ElevenLabs(
        "test-key",
        cache_dir=tmp_path,
        max_credits=max_credits,
        transport=httpx.MockTransport(handler),
    )


def test_credits_are_duration_based():
    assert voice_changer_credits(60) == 1200
    assert voice_changer_credits(9.3) == 186


def test_second_identical_call_is_served_from_disk(tmp_path):
    calls = []
    el = make_client(tmp_path, 1000, calls)
    first = el.voice_changer(b"audio", 10, "voice")
    second = el.voice_changer(b"audio", 10, "voice")
    assert first == second
    assert first.read_bytes() == b"fake-mp3"
    assert len(calls) == 1
    assert el.spent == voice_changer_credits(10)


def test_cache_survives_a_new_client_with_no_budget(tmp_path):
    calls = []
    make_client(tmp_path, 1000, calls).voice_changer(b"audio", 10, "voice")
    make_client(tmp_path, 0, calls).voice_changer(b"audio", 10, "voice")
    assert len(calls) == 1


def test_different_voice_or_audio_is_a_different_request(tmp_path):
    calls = []
    el = make_client(tmp_path, 1000, calls)
    el.voice_changer(b"audio", 10, "voice-a")
    el.voice_changer(b"audio", 10, "voice-b")
    el.voice_changer(b"other", 10, "voice-a")
    assert len(calls) == 3


def test_budget_is_checked_before_the_network(tmp_path):
    calls = []
    el = make_client(tmp_path, 100, calls)
    with pytest.raises(BudgetExceeded):
        el.voice_changer(b"audio", 10, "voice")
    assert calls == []


def test_key_is_sent_as_header_not_in_url(tmp_path):
    calls = []
    make_client(tmp_path, 1000, calls).voice_changer(b"audio", 10, "voice")
    assert calls[0].headers["xi-api-key"] == "test-key"
    assert "test-key" not in str(calls[0].url)
