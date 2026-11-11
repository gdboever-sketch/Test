import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from negotiator.brief import NegotiationBrief
from negotiator.config import Settings

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

ANALYSIS = {
    "suggestions": [
        {"priority": "high", "kind": "ask", "strategy": "counter-an-extreme-anchor", "text": "What drives the increase?", "rationale": "Test their anchor."}
    ],
    "alerts": [{"severity": "critical", "text": "You revealed your budget."}],
    "offers": [{"party": "them", "term": "Annual price", "value": "$480k", "status": "proposed"}],
    "counterpart_signals": ["Quarter-end pressure"],
    "summary": "They anchored high.",
}


@pytest.fixture
def brief() -> NegotiationBrief:
    return NegotiationBrief.load(EXAMPLES / "brief.example.yaml")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        public_base_url="https://coach.example.com",
        admin_token="admin-secret",
        min_interval=0.0,
        min_new_words=1,
        sessions_dir=tmp_path / "sessions",
    )


def _response(text, stop_reason="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        stop_details=None,
        usage=SimpleNamespace(
            input_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0, output_tokens=5
        ),
    )


class _Stream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get_final_message(self):
        return self.response


class FakeClaude:
    """Stands in for AsyncAnthropic and records every request."""

    def __init__(self, analysis_text=None, stop_reason="end_turn"):
        self.requests = []
        self.analysis_text = analysis_text or json.dumps(ANALYSIS)
        self.stop_reason = stop_reason
        outer = self

        class Messages:
            async def create(self, **kwargs):
                outer.requests.append(kwargs)
                return _response(outer.analysis_text, outer.stop_reason)

            def stream(self, **kwargs):
                outer.requests.append(kwargs)
                return _Stream(_response("# Debrief\nOutcome: pending."))

        self.beta = SimpleNamespace(messages=Messages())


@pytest.fixture
def fake_claude() -> FakeClaude:
    return FakeClaude()
