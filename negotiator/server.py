"""HTTP and WebSocket server.

- POST /api/sessions          start a call (admin token required)
- GET  /s/{id}?token=...      private live dashboard
- GET  /api/s/{id}/events     dashboard feed (Server-Sent Events)
- POST /api/s/{id}/speakers   label a diarized speaker ("Speaker 0 = me")
- POST /api/s/{id}/notes      private note to the coach
- POST /api/s/{id}/hangup     leave the meeting
- POST /twilio/status/{id}    Twilio call status callback
- WS   /media/{id}            Twilio media stream (audio in, nothing out)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import secrets
from importlib import resources
from typing import Any, Callable

import anthropic
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from .brief import NegotiationBrief
from .coach import Coach
from .config import Settings
from .session import MeetingSession, SessionStore
from .telephony import Telephony, normalize_digits
from .transcriber import DeepgramTranscriber

log = logging.getLogger(__name__)

TERMINAL_CALL_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


class StartSessionRequest(BaseModel):
    brief: NegotiationBrief
    number: str = Field(description="The meeting's dial-in number, in E.164 format.")
    digits: str | None = Field(
        default=None, description="DTMF to enter after connecting, e.g. 'wwww123456789#wwww#'."
    )


class SpeakerLabel(BaseModel):
    speaker: int
    label: str


class Note(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


def create_app(
    settings: Settings,
    telephony: Telephony | None = None,
    claude: anthropic.AsyncAnthropic | None = None,
    transcriber_factory: Callable[..., Any] | None = None,
) -> FastAPI:
    app = FastAPI(title="Negotiation coach")
    store = SessionStore()
    app.state.store = store
    app.state.settings = settings

    def get_telephony() -> Telephony:
        nonlocal telephony
        if telephony is None:
            telephony = Telephony(settings)
        return telephony

    def make_transcriber(on_utterance):
        if transcriber_factory is not None:
            return transcriber_factory(on_utterance)
        return DeepgramTranscriber(settings.deepgram_api_key, on_utterance, settings.deepgram_model)

    def require_admin(authorization: str | None = Header(default=None)) -> None:
        expected = settings.admin_token
        if not expected:
            raise HTTPException(503, "NEGOTIATOR_ADMIN_TOKEN is not configured")
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not secrets.compare_digest(given, expected):
            raise HTTPException(401, "invalid admin token")

    def session_for(session_id: str, token: str | None = Query(default=None)) -> MeetingSession:
        session = store.authorized(session_id, token)
        if session is None:
            raise HTTPException(404, "session not found")
        return session

    # ---- starting a call ------------------------------------------------

    @app.post("/api/sessions", dependencies=[Depends(require_admin)])
    async def start_session(body: StartSessionRequest) -> dict[str, str]:
        if transcriber_factory is None and not settings.deepgram_api_key:
            raise HTTPException(503, "DEEPGRAM_API_KEY is not configured")
        try:
            digits = normalize_digits(body.digits)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        coach = Coach(body.brief, settings, client=claude)
        session = store.add(MeetingSession(brief=body.brief, coach=coach, settings=settings))
        session.start()
        session.set_status("dialing")
        try:
            session.call_sid = await get_telephony().dial(
                session.id, session.token, body.number, digits
            )
        except Exception as e:
            log.exception("Dial failed")
            session.set_status("failed")
            raise HTTPException(502, f"could not place the call: {e}") from e
        return {
            "id": session.id,
            "call_sid": session.call_sid,
            "dashboard_url": f"{settings.public_base_url}/s/{session.id}?token={session.token}",
        }

    # ---- dashboard ------------------------------------------------------

    dashboard_html = resources.files("negotiator").joinpath("static/dashboard.html").read_text()

    @app.get("/s/{session_id}", response_class=HTMLResponse)
    async def dashboard(session: MeetingSession = Depends(session_for)) -> str:
        return dashboard_html

    @app.get("/api/s/{session_id}/state")
    async def state(session: MeetingSession = Depends(session_for)) -> dict[str, Any]:
        return session.snapshot()

    @app.get("/api/s/{session_id}/events")
    async def events(request: Request, session: MeetingSession = Depends(session_for)):
        queue = session.subscribe()

        async def stream():
            try:
                yield f"event: snapshot\ndata: {json.dumps(session.snapshot())}\n\n"
                while not await request.is_disconnected():
                    try:
                        event, data = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
            finally:
                session.unsubscribe(queue)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/s/{session_id}/speakers")
    async def label_speaker(body: SpeakerLabel, session: MeetingSession = Depends(session_for)):
        session.label_speaker(body.speaker, body.label)
        return {"ok": True}

    @app.post("/api/s/{session_id}/notes")
    async def add_note(body: Note, session: MeetingSession = Depends(session_for)):
        session.add_note(body.note)
        return {"ok": True}

    @app.post("/api/s/{session_id}/hangup")
    async def hang_up(session: MeetingSession = Depends(session_for)):
        if session.call_sid:
            await get_telephony().hang_up(session.call_sid)
        return {"ok": True}

    # ---- Twilio ---------------------------------------------------------

    @app.post("/twilio/status/{session_id}")
    async def call_status(session_id: str, request: Request):
        form = {k: str(v) for k, v in (await request.form()).items()}
        url = f"{settings.public_base_url}/twilio/status/{session_id}"
        if not get_telephony().is_valid_request(url, form, request.headers.get("X-Twilio-Signature")):
            raise HTTPException(403, "invalid Twilio signature")
        session = store.get(session_id)
        if session is None or form.get("CallSid") != session.call_sid:
            raise HTTPException(404, "session not found")
        status = form.get("CallStatus", "")
        log.info("Call %s status: %s", session.call_sid, status)
        if status in TERMINAL_CALL_STATUSES:
            asyncio.create_task(session.finish())
        elif status:
            session.set_status("in meeting" if status == "in-progress" else status)
        return {"ok": True}

    @app.websocket("/media/{session_id}")
    async def media(websocket: WebSocket, session_id: str):
        await websocket.accept()
        session: MeetingSession | None = None
        transcriber = None
        try:
            while True:
                message = json.loads(await websocket.receive_text())
                event = message.get("event")
                if event == "start":
                    token = message.get("start", {}).get("customParameters", {}).get("token")
                    session = store.authorized(session_id, token)
                    if session is None:
                        log.warning("Rejected media stream for %s: bad token", session_id)
                        await websocket.close(code=1008)
                        return
                    transcriber = make_transcriber(session.add_utterance)
                    await transcriber.start()
                    session.set_status("in meeting")
                elif event == "media" and transcriber is not None:
                    await transcriber.send_audio(base64.b64decode(message["media"]["payload"]))
                elif event == "stop":
                    break
        except WebSocketDisconnect:
            pass
        finally:
            if transcriber is not None:
                await transcriber.close()
            if session is not None:
                asyncio.create_task(session.finish())

    return app


def app_from_env() -> FastAPI:
    """Entry point for `uvicorn negotiator.server:app_from_env --factory`."""
    from .config import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return create_app(Settings.from_env())
