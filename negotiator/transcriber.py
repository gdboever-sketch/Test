"""Streaming speech-to-text with speaker diarization (Deepgram).

Twilio sends 8 kHz mu-law audio. It is forwarded unchanged to Deepgram's live
endpoint, which returns final transcripts with a speaker number per word.
On a phone dial-in every participant shares one audio channel, so diarization
is the only way to tell speakers apart.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

import websockets

log = logging.getLogger(__name__)

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"


@dataclass
class Utterance:
    speaker: int | None
    text: str
    start: float
    end: float

    def render(self) -> str:
        who = f"Speaker {self.speaker}" if self.speaker is not None else "Unknown speaker"
        return f"[{_clock(self.start)}] {who}: {self.text}"


def _clock(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60:02d}:{total % 60:02d}"


def utterances_from_result(message: dict[str, Any]) -> list[Utterance]:
    """Split one final Deepgram result into utterances by speaker turn."""
    if message.get("type") != "Results" or not message.get("is_final"):
        return []
    alternatives = message.get("channel", {}).get("alternatives") or []
    if not alternatives:
        return []
    words = alternatives[0].get("words") or []
    if not words:
        text = (alternatives[0].get("transcript") or "").strip()
        if not text:
            return []
        start = float(message.get("start", 0.0))
        return [Utterance(None, text, start, start + float(message.get("duration", 0.0)))]

    out: list[Utterance] = []
    for word in words:
        speaker = word.get("speaker")
        token = word.get("punctuated_word") or word.get("word", "")
        if out and out[-1].speaker == speaker:
            out[-1].text += " " + token
            out[-1].end = float(word.get("end", out[-1].end))
        else:
            out.append(
                Utterance(speaker, token, float(word.get("start", 0.0)), float(word.get("end", 0.0)))
            )
    return out


UtteranceHandler = Callable[[Utterance], Awaitable[None]]


class DeepgramTranscriber:
    def __init__(self, api_key: str, on_utterance: UtteranceHandler, model: str = "nova-3") -> None:
        if not api_key:
            raise ValueError("DEEPGRAM_API_KEY is not set")
        self.api_key = api_key
        self.on_utterance = on_utterance
        self.model = model
        self._ws: Any = None
        self._reader: asyncio.Task | None = None
        self._keepalive: asyncio.Task | None = None

    @property
    def url(self) -> str:
        params = {
            "model": self.model,
            "encoding": "mulaw",
            "sample_rate": 8000,
            "channels": 1,
            "diarize": "true",
            "punctuate": "true",
            "smart_format": "true",
            "interim_results": "false",
        }
        return f"{DEEPGRAM_URL}?{urlencode(params)}"

    async def start(self) -> None:
        self._ws = await websockets.connect(
            self.url, additional_headers={"Authorization": f"Token {self.api_key}"}
        )
        self._reader = asyncio.create_task(self._read())
        self._keepalive = asyncio.create_task(self._keep_alive())

    async def send_audio(self, chunk: bytes) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(chunk)
            except websockets.ConnectionClosed:
                log.warning("Deepgram connection closed; dropping audio")

    async def _keep_alive(self) -> None:
        # Deepgram closes idle streams; this keeps long silences from ending it.
        while True:
            await asyncio.sleep(5)
            with contextlib.suppress(websockets.ConnectionClosed):
                await self._ws.send(json.dumps({"type": "KeepAlive"}))

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue
                for utterance in utterances_from_result(json.loads(raw)):
                    try:
                        await self.on_utterance(utterance)
                    except Exception:
                        log.exception("Utterance handler failed")
        except websockets.ConnectionClosed:
            pass

    async def close(self) -> None:
        if self._keepalive:
            self._keepalive.cancel()
        if self._ws is not None:
            with contextlib.suppress(websockets.ConnectionClosed):
                # Ask Deepgram to flush the final results before closing.
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            if self._reader:
                with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
                    await asyncio.wait_for(self._reader, timeout=5)
            await self._ws.close()
            self._ws = None
