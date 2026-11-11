"""Twilio: dial the meeting's phone bridge and stream its audio to this server."""

from __future__ import annotations

import asyncio
import re
from urllib.parse import urlparse

from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from .config import Settings

_DIGITS = re.compile(r"^[0-9wW#*]*$")


def normalize_digits(digits: str | None) -> str | None:
    """Validate the DTMF sequence used to get into the meeting.

    Use `w` for a half-second pause, for example "wwww123456789#wwww#" for
    a meeting ID, a pause, and an empty participant ID.
    """
    if not digits:
        return None
    cleaned = digits.replace(" ", "").replace(",", "w")
    if not _DIGITS.match(cleaned):
        raise ValueError("digits may contain only 0-9, *, #, and w (pause)")
    return cleaned


def media_stream_url(settings: Settings, session_id: str) -> str:
    parsed = urlparse(settings.public_base_url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("PUBLIC_BASE_URL must be an https:// URL Twilio can reach")
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return f"{scheme}://{parsed.netloc}{parsed.path.rstrip('/')}/media/{session_id}"


def build_twiml(settings: Settings, session_id: str, token: str, digits: str | None) -> str:
    response = VoiceResponse()
    # Give the bridge time to answer and play its greeting.
    response.pause(length=2)
    if digits:
        response.play(digits=digits)
    if settings.announce_on_join and settings.announcement_text:
        response.say(settings.announcement_text)
    connect = Connect()
    stream = connect.stream(url=media_stream_url(settings, session_id))
    # Twilio stream URLs cannot carry query strings; custom parameters arrive
    # in the stream's "start" message instead.
    stream.parameter(name="token", value=token)
    response.append(connect)
    return str(response)


class Telephony:
    def __init__(self, settings: Settings) -> None:
        missing = [
            name
            for name, value in (
                ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
                ("PUBLIC_BASE_URL", settings.public_base_url),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing settings: {', '.join(missing)}")
        self.settings = settings
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self.validator = RequestValidator(settings.twilio_auth_token)

    async def dial(self, session_id: str, token: str, number: str, digits: str | None) -> str:
        twiml = build_twiml(self.settings, session_id, token, digits)
        status_url = f"{self.settings.public_base_url}/twilio/status/{session_id}"
        call = await asyncio.to_thread(
            self.client.calls.create,
            to=number,
            from_=self.settings.twilio_from_number,
            twiml=twiml,
            status_callback=status_url,
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        return call.sid

    async def hang_up(self, call_sid: str) -> None:
        await asyncio.to_thread(self.client.calls(call_sid).update, status="completed")

    def is_valid_request(self, url: str, params: dict[str, str], signature: str | None) -> bool:
        if not self.settings.validate_twilio_signatures:
            return True
        return bool(signature) and self.validator.validate(url, params, signature)
