import base64
import json
import time

from fastapi.testclient import TestClient

from negotiator.server import create_app
from negotiator.transcriber import Utterance


class FakeTelephony:
    def __init__(self):
        self.dialed = []
        self.hung_up = []

    async def dial(self, session_id, token, number, digits):
        self.dialed.append((session_id, number, digits))
        return "CA123"

    async def hang_up(self, sid):
        self.hung_up.append(sid)

    def is_valid_request(self, url, params, signature):
        return signature == "good"


class FakeTranscriber:
    instances = []

    def __init__(self, on_utterance):
        self.on_utterance = on_utterance
        self.audio = b""
        self.closed = False
        FakeTranscriber.instances.append(self)

    async def start(self):
        pass

    async def send_audio(self, chunk):
        self.audio += chunk
        # Pretend every audio chunk is one finished sentence.
        await self.on_utterance(Utterance(1, "Our price is 480 thousand.", 0, 2))

    async def close(self):
        self.closed = True


def _app(settings, fake_claude):
    tel = FakeTelephony()
    app = create_app(settings, telephony=tel, claude=fake_claude, transcriber_factory=FakeTranscriber)
    return app, tel


def _start(client, brief):
    return client.post(
        "/api/sessions",
        json={"brief": brief.model_dump(), "number": "+15555550123", "digits": "wwww123#"},
        headers={"Authorization": "Bearer admin-secret"},
    )


def test_start_requires_admin_token(settings, fake_claude, brief):
    app, _ = _app(settings, fake_claude)
    with TestClient(app) as client:
        r = client.post("/api/sessions", json={"brief": brief.model_dump(), "number": "+1"},
                        headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


def test_full_call_flow(settings, fake_claude, brief):
    app, tel = _app(settings, fake_claude)
    with TestClient(app) as client:
        r = _start(client, brief)
        assert r.status_code == 200, r.text
        sid = r.json()["id"]
        token = r.json()["dashboard_url"].split("token=")[1]
        assert tel.dialed == [(sid, "+15555550123", "wwww123#")]

        assert client.get(f"/s/{sid}?token=nope").status_code == 404
        assert "Negotiation coach" in client.get(f"/s/{sid}?token={token}").text

        assert client.post(f"/api/s/{sid}/speakers?token={token}", json={"speaker": 0, "label": "Me"}).json()["ok"]
        assert client.post(f"/api/s/{sid}/notes?token={token}", json={"note": "Budget is 430"}).json()["ok"]

        # A stream with a bad token is rejected.
        with client.websocket_connect(f"/media/{sid}") as ws:
            ws.send_text(json.dumps({"event": "start", "start": {"customParameters": {"token": "bad"}}}))
            assert ws.receive().get("type") == "websocket.close"

        payload = base64.b64encode(b"\xff" * 160).decode()
        with client.websocket_connect(f"/media/{sid}") as ws:
            ws.send_text(json.dumps({"event": "connected"}))
            ws.send_text(json.dumps({"event": "start", "start": {"customParameters": {"token": token}}}))
            ws.send_text(json.dumps({"event": "media", "media": {"payload": payload}}))
            # Let the coaching loop run one analysis while the call is live.
            deadline = time.time() + 5
            session = app.state.store.get(sid)
            while session.latest is None and time.time() < deadline:
                time.sleep(0.1)
            ws.send_text(json.dumps({"event": "stop"}))

        deadline = time.time() + 5
        while session.status != "ended" and time.time() < deadline:
            time.sleep(0.1)

        assert FakeTranscriber.instances[-1].audio == b"\xff" * 160
        assert FakeTranscriber.instances[-1].closed
        assert session.latest.alerts[0].text == "You revealed your budget."
        assert session.status == "ended"
        state = client.get(f"/api/s/{sid}/state?token={token}").json()
        assert state["speakers"] == {"0": "Me"}
        assert state["summary"].startswith("# Debrief")
        assert state["strategies"]["counter-an-extreme-anchor"] == "Counter an extreme anchor"

        analysis_req = fake_claude.requests[0]
        tail = analysis_req["messages"][0]["content"][-1]["text"]
        assert "Speaker 0: Me" in tail and "Budget is 430" in tail
        assert "Speaker 1: Our price is 480 thousand." in analysis_req["messages"][0]["content"][0]["text"]

        out = settings.sessions_dir / sid
        assert "480 thousand" in (out / "transcript.txt").read_text()
        assert (out / "summary.md").exists()


def test_unknown_strategy_in_brief_is_rejected(settings, fake_claude, brief):
    app, _ = _app(settings, fake_claude)
    brief.preferred_strategies = ["does-not-exist"]
    with TestClient(app) as client:
        r = _start(client, brief)
        assert r.status_code == 422 and "does-not-exist" in r.text


def test_status_callback_checks_signature(settings, fake_claude, brief):
    app, _ = _app(settings, fake_claude)
    with TestClient(app) as client:
        sid = _start(client, brief).json()["id"]
        form = {"CallSid": "CA123", "CallStatus": "in-progress"}
        assert client.post(f"/twilio/status/{sid}", data=form, headers={"X-Twilio-Signature": "bad"}).status_code == 403
        assert client.post(f"/twilio/status/{sid}", data=form, headers={"X-Twilio-Signature": "good"}).status_code == 200
        assert app.state.store.get(sid).status == "in meeting"
