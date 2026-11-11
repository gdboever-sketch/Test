"""Run the coach over a written transcript, round by round, as if it were live.

Shared by `negotiator replay` and the web test lab.
"""

from __future__ import annotations

import re
from typing import Any, AsyncIterator

from .coach import Coach, CoachingUpdate
from .transcriber import Utterance

# Optional "[00:12]" timestamp, then "Name: what they said".
_LINE = re.compile(r"^\s*(?:\[[0-9:]+\]\s*)?([^:]{1,60}):\s*(.+?)\s*$")


def parse_transcript(text: str) -> list[tuple[str, str]]:
    """Return (speaker, text) pairs; lines without "Name:" continue the previous one."""
    lines: list[tuple[str, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        m = _LINE.match(raw)
        if m:
            lines.append((m.group(1).strip(), m.group(2)))
        elif lines:
            who, said = lines[-1]
            lines[-1] = (who, f"{said} {raw.strip()}")
    return lines


def rounds_for(line_count: int, every: int) -> int:
    return -(-line_count // max(1, every))


async def rehearse(
    coach: Coach,
    lines: list[tuple[str, str]],
    every: int = 3,
    summary: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Yield one event per analysis round, then the debrief.

    Events: {"type": "analysis", ...}, {"type": "summary", ...}, {"type": "done", ...}.
    """
    speakers: dict[str, int] = {}
    labels: dict[int, str] = {}
    utterances: list[Utterance] = []
    chunks: list[str] = []
    pending: list[Utterance] = []
    latest: CoachingUpdate | None = None
    clock = 0.0
    every = max(1, every)

    for i, (who, text) in enumerate(lines, start=1):
        n = speakers.setdefault(who, len(speakers))
        labels[n] = who
        u = Utterance(n, text, clock, clock + 4)
        clock += 5
        utterances.append(u)
        pending.append(u)
        if i % every == 0 or i == len(lines):
            chunks.append("\n".join(p.render() for p in pending))
            pending = []
            update = await coach.analyze(chunks, latest, labels)
            if update is not None:
                latest = update
            yield {
                "type": "analysis",
                "after_line": i,
                "speaker": who,
                "text": text,
                "update": update.model_dump() if update else None,
            }

    if summary:
        debrief = await coach.summarize("\n".join(u.render() for u in utterances), latest, labels)
        yield {"type": "summary", "markdown": debrief}
    yield {"type": "done", "final": latest.model_dump() if latest else None}
