"""One meeting: the transcript, the coaching loop, and the private dashboard feed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from .brief import NegotiationBrief
from .coach import Coach, CoachingUpdate
from .config import Settings
from .transcriber import Utterance

log = logging.getLogger(__name__)


@dataclass
class MeetingSession:
    brief: NegotiationBrief
    coach: Coach
    settings: Settings
    id: str = field(default_factory=lambda: secrets.token_hex(6))
    # Secret used in dashboard URLs and to authenticate the Twilio media stream.
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))

    status: str = "created"
    call_sid: str | None = None
    utterances: list[Utterance] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)
    pending: list[Utterance] = field(default_factory=list)
    speaker_labels: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    latest: CoachingUpdate | None = None
    summary: str | None = None

    _subscribers: list[asyncio.Queue] = field(default_factory=list, repr=False)
    _loop_task: asyncio.Task | None = field(default=None, repr=False)
    _last_analysis: float = field(default=0.0, repr=False)
    _force: bool = field(default=False, repr=False)
    _finished: bool = field(default=False, repr=False)

    # ---- dashboard feed -------------------------------------------------

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with contextlib.suppress(ValueError):
            self._subscribers.remove(q)

    def publish(self, event: str, data: Any) -> None:
        for q in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait((event, data))

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.brief.title,
            "status": self.status,
            "transcript": [u.render() for u in self.utterances],
            "speakers": {str(k): v for k, v in self.speaker_labels.items()},
            "notes": self.notes,
            "analysis": self.latest.model_dump() if self.latest else None,
            "summary": self.summary,
        }

    def set_status(self, status: str) -> None:
        self.status = status
        self.publish("status", status)

    # ---- inputs ---------------------------------------------------------

    async def add_utterance(self, utterance: Utterance) -> None:
        self.utterances.append(utterance)
        self.pending.append(utterance)
        self.publish("transcript", utterance.render())

    def label_speaker(self, speaker: int, label: str) -> None:
        if label.strip():
            self.speaker_labels[speaker] = label.strip()
        else:
            self.speaker_labels.pop(speaker, None)
        self.publish("speakers", {str(k): v for k, v in self.speaker_labels.items()})

    def add_note(self, note: str) -> None:
        self.notes.append(note.strip())
        self._force = True
        self.publish("notes", self.notes)

    # ---- coaching loop --------------------------------------------------

    def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._run())

    def _new_words(self) -> int:
        return sum(len(u.text.split()) for u in self.pending)

    def should_analyze(self, now: float) -> bool:
        if now - self._last_analysis < self.settings.min_interval:
            return False
        if self._force:
            return True
        return self._new_words() >= self.settings.min_new_words

    async def analyze_now(self) -> None:
        self._force = False
        self._last_analysis = time.monotonic()
        if self.pending:
            self.chunks.append("\n".join(u.render() for u in self.pending))
            self.pending = []
        self.publish("thinking", True)
        try:
            update = await self.coach.analyze(
                self.chunks, self.latest, self.speaker_labels, self.notes
            )
        finally:
            self.publish("thinking", False)
        if update is not None:
            self.latest = update
            self.publish("analysis", update.model_dump())

    async def _run(self) -> None:
        while not self._finished:
            if self.should_analyze(time.monotonic()):
                try:
                    await self.analyze_now()
                except Exception:
                    log.exception("Analysis round failed")
            await asyncio.sleep(1.0)

    # ---- end of call ----------------------------------------------------

    def full_transcript(self) -> str:
        return "\n".join(u.render() for u in self.utterances)

    async def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        if self._loop_task:
            self._loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._loop_task
        self.set_status("summarizing")
        self.summary = await self.coach.summarize(
            self.full_transcript(), self.latest, self.speaker_labels
        )
        self.publish("summary", self.summary)
        self.save()
        self.set_status("ended")

    def save(self) -> None:
        out = self.settings.sessions_dir / self.id
        out.mkdir(parents=True, exist_ok=True)
        (out / "transcript.txt").write_text(self.full_transcript() + "\n")
        (out / "brief.json").write_text(self.brief.model_dump_json(indent=2))
        snapshot = self.snapshot()
        snapshot.pop("transcript")
        (out / "session.json").write_text(json.dumps(snapshot, indent=2))
        if self.summary:
            (out / "summary.md").write_text(self.summary + "\n")
        log.info("Saved session %s to %s", self.id, out)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, MeetingSession] = {}

    def add(self, session: MeetingSession) -> MeetingSession:
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> MeetingSession | None:
        return self._sessions.get(session_id)

    def authorized(self, session_id: str, token: str | None) -> MeetingSession | None:
        session = self.get(session_id)
        if session and token and secrets.compare_digest(session.token, token):
            return session
        return None
