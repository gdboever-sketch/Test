"""Runtime settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: str | os.PathLike = ".env") -> None:
    """Minimal .env loader so the project needs no extra dependency.

    Existing environment variables win over values in the file.
    """
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass
class Settings:
    model: str = "claude-opus-5-5"
    coach_effort: str = "low"
    summary_effort: str = "high"

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    deepgram_api_key: str = ""
    deepgram_model: str = "nova-3"

    public_base_url: str = ""
    # Required to start calls through the HTTP API (the CLI sends it).
    admin_token: str = ""
    validate_twilio_signatures: bool = True

    announce_on_join: bool = True
    announcement_text: str = (
        "Hello, an AI note taking assistant has joined this call to transcribe it."
    )

    # Coaching cadence: analyse at most once per `min_interval` seconds, and
    # only once at least `min_new_words` new words have been transcribed.
    min_interval: float = 8.0
    min_new_words: int = 25

    sessions_dir: Path = field(default_factory=lambda: Path("sessions"))
    # Folder (or separate Git checkout) holding the strategy playbook.
    # None means the playbook bundled with this repository.
    strategies_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            model=env("COACH_MODEL", cls.model),
            coach_effort=env("COACH_EFFORT", cls.coach_effort),
            summary_effort=env("SUMMARY_EFFORT", cls.summary_effort),
            twilio_account_sid=env("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=env("TWILIO_AUTH_TOKEN", ""),
            twilio_from_number=env("TWILIO_FROM_NUMBER", ""),
            deepgram_api_key=env("DEEPGRAM_API_KEY", ""),
            deepgram_model=env("DEEPGRAM_MODEL", cls.deepgram_model),
            public_base_url=env("PUBLIC_BASE_URL", "").rstrip("/"),
            admin_token=env("NEGOTIATOR_ADMIN_TOKEN", ""),
            validate_twilio_signatures=_bool(env("VALIDATE_TWILIO_SIGNATURES"), True),
            announce_on_join=_bool(env("ANNOUNCE_ON_JOIN"), True),
            announcement_text=env("ANNOUNCEMENT_TEXT", cls.announcement_text),
            min_interval=float(env("COACH_MIN_INTERVAL", cls.min_interval)),
            min_new_words=int(env("COACH_MIN_NEW_WORDS", cls.min_new_words)),
            sessions_dir=Path(env("SESSIONS_DIR", "sessions")),
            strategies_dir=Path(env("STRATEGIES_DIR")) if env("STRATEGIES_DIR") else None,
        )
