import json

from fastapi.testclient import TestClient

from negotiator.rehearsal import parse_transcript, rounds_for
from negotiator.server import create_app

AUTH = {"Authorization": "Bearer admin-secret"}


def test_parse_transcript_handles_timestamps_and_continuations():
    text = "[00:01] Sam: Our price is high.\nIt reflects new features.\n\nJordan: Hm."
    assert parse_transcript(text) == [("Sam", "Our price is high. It reflects new features."), ("Jordan", "Hm.")]
    assert rounds_for(7, 3) == 3


def _client(settings, fake_claude):
    return TestClient(create_app(settings, claude=fake_claude))


def test_lab_page_and_playbook(settings, fake_claude):
    with _client(settings, fake_claude) as client:
        assert "Negotiation lab" in client.get("/lab").text
        assert client.get("/api/lab/playbook").status_code == 401
        data = client.get("/api/lab/playbook", headers=AUTH).json()
        assert len(data["strategies"]) >= 20
        assert data["example"]["brief"]["title"].startswith("Renewal")
        assert "Jordan:" in data["example"]["transcript"]


def test_lab_run_streams_rounds_and_debrief(settings, fake_claude, brief):
    transcript = "\n".join(f"P{i % 2}: line {i}" for i in range(7))
    with _client(settings, fake_claude) as client:
        r = client.post("/api/lab/run", headers=AUTH,
                        json={"brief": brief.model_dump(), "transcript": transcript, "every": 3})
        assert r.status_code == 200
        events = [json.loads(line) for line in r.text.splitlines()]
    assert [e["type"] for e in events] == ["start", "analysis", "analysis", "analysis", "summary", "done"]
    assert events[0]["rounds"] == 3
    assert [e["after_line"] for e in events if e["type"] == "analysis"] == [3, 6, 7]
    assert events[1]["update"]["suggestions"][0]["strategy"] == "counter-an-extreme-anchor"
    assert events[-2]["markdown"].startswith("# Debrief")
    # Rounds build on each other: the third request carries all three transcript windows.
    analysis_requests = [r for r in fake_claude.requests if "output_config" in r and "format" in r["output_config"]]
    assert len(analysis_requests[2]["messages"][0]["content"]) == 4


def test_lab_run_validation(settings, fake_claude, brief):
    with _client(settings, fake_claude) as client:
        body = {"brief": brief.model_dump(), "transcript": "no speaker lines here"}
        assert client.post("/api/lab/run", json=body).status_code == 401
        assert client.post("/api/lab/run", headers=AUTH, json=body).status_code == 422
        body["transcript"] = "\n".join(f"A: {i}" for i in range(200))
        body["every"] = 1
        r = client.post("/api/lab/run", headers=AUTH, json=body)
        assert r.status_code == 422 and "rounds" in r.text
        body.update(every=3, brief={**brief.model_dump(), "excluded_strategies": ["nope"]})
        assert client.post("/api/lab/run", headers=AUTH, json=body).status_code == 422


def test_lab_run_needs_an_api_key(settings, brief, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with TestClient(create_app(settings)) as client:
        r = client.post("/api/lab/run", headers=AUTH,
                        json={"brief": brief.model_dump(), "transcript": "A: hi"})
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.text
