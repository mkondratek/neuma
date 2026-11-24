"""Minimal ElevenLabs client: disk cache first, credit budget second, network last.

Every paid response is stored under ``cache_dir`` keyed by a hash of the request
(input audio bytes plus all parameters), so re-running a pipeline never spends
quota twice on the same request.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path

import httpx

API = "https://api.elevenlabs.io"
VOICE_CHANGER_CREDITS_PER_MINUTE = 1000  # documented: duration-based, 1000 per minute


class BudgetExceeded(RuntimeError):
    pass


def voice_changer_credits(duration_s: float) -> int:
    return math.ceil(duration_s / 60 * VOICE_CHANGER_CREDITS_PER_MINUTE)


class ElevenLabs:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        cache_dir: Path | str = ".cache/elevenlabs",
        max_credits: int = 0,
        transport: httpx.BaseTransport | None = None,
    ):
        """``max_credits`` caps what this instance may spend on uncached calls."""
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.max_credits = max_credits
        self.spent = 0
        self._transport = transport

    def _client(self) -> httpx.Client:
        if not self._api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not set")
        return httpx.Client(
            base_url=API,
            headers={"xi-api-key": self._api_key},
            timeout=120,
            transport=self._transport,
        )

    # Free calls ---------------------------------------------------------

    def subscription(self) -> dict:
        with self._client() as c:
            r = c.get("/v1/user/subscription")
            r.raise_for_status()
            return r.json()

    def voices(self) -> list[dict]:
        with self._client() as c:
            r = c.get("/v1/voices")
            r.raise_for_status()
            return r.json()["voices"]

    # Paid calls ---------------------------------------------------------

    def voice_changer(
        self,
        audio: bytes,
        duration_s: float,
        voice_id: str,
        *,
        model_id: str = "eleven_multilingual_sts_v2",
        output_format: str = "mp3_44100_128",
        seed: int | None = 0,
        voice_settings: dict | None = None,
    ) -> Path:
        """Convert ``audio`` to ``voice_id``; returns the path of the cached result."""
        params = {
            "endpoint": "voice-changer",
            "voice_id": voice_id,
            "model_id": model_id,
            "output_format": output_format,
            "seed": seed,
            "voice_settings": voice_settings,
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
        }
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:24]
        ext = output_format.split("_")[0]
        path = self.cache_dir / f"{key}.{ext}"
        if path.exists():
            return path

        cost = voice_changer_credits(duration_s)
        if self.spent + cost > self.max_credits:
            raise BudgetExceeded(
                f"call needs ~{cost} credits; {self.spent} spent of {self.max_credits} allowed"
            )

        data = {"model_id": model_id}
        if seed is not None:
            data["seed"] = str(seed)
        if voice_settings is not None:
            data["voice_settings"] = json.dumps(voice_settings)
        with self._client() as c:
            r = c.post(
                f"/v1/voice-changer/{voice_id}",
                params={"output_format": output_format},
                data=data,
                files={"audio": ("guide.wav", audio, "audio/wav")},
            )
        if r.status_code != 200:
            raise RuntimeError(f"voice changer failed: HTTP {r.status_code}: {r.text[:500]}")
        self.spent += cost

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        meta = params | {
            "estimated_credits": cost,
            "duration_s": round(duration_s, 3),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return path
