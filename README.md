# Negotiation coach

An agent that dials into your meeting by phone, listens, and coaches you
privately during a negotiation. It never speaks in the meeting except for an
optional one-line announcement when it joins. Its advice appears only on a
private dashboard that you keep open on your laptop or phone.

```
Meeting bridge (Zoom/Teams/Meet/any phone bridge)
        │  phone call (Twilio dials the dial-in number and enters the meeting ID)
        ▼
Twilio Media Stream ──audio──▶ this server ──audio──▶ Deepgram (live STT + speaker diarization)
                                    │                         │
                                    │◀──────── utterances ────┘
                                    ▼
                         Claude (claude-opus-5-5): structured coaching
                                    │
                                    ▼
                  Private dashboard (Server-Sent Events): next moves,
                  alerts, offer ledger, transcript, notes to the coach
                                    │
                         call ends ─▶ debrief (summary.md) + transcript saved
```

## What it does during the call

- **Next moves:** up to three short suggestions (what to say, ask, avoid, or a
  tactic), each with a one-line rationale.
- **Alerts:** a red line under threat, being about to reveal something on your
  do-not-disclose list, conceding without getting something back, an offer
  past your walk-away point, or pressure tactics such as fake deadlines.
- **Offer ledger:** every term either side has proposed, with its latest status.
- **Counterpart signals:** what the transcript reveals about the other side's
  interests and constraints.
- **Private notes:** tell the coach things it can't hear, for example "they
  just put 5% in the chat" or "I can go to 18 months".
- **Speaker labels:** a phone line mixes everyone into one channel, so speakers
  arrive as numbers. Label them on the dashboard ("Speaker 0 = me").
- **Debrief:** when the call ends you get a Markdown debrief covering the outcome
  against your targets, agreed terms, open items, concessions, next steps, and
  coaching notes. It is saved under `sessions/<id>/`.

Everything is driven by a **negotiation brief** you write before the call:
goal, BATNA, issues with targets and walk-away points, tradeables, red lines,
and what not to disclose. See [`examples/brief.example.yaml`](examples/brief.example.yaml).

## Strategy playbook

The coach follows a playbook of negotiation strategies kept in
[`strategies/`](strategies/), with one Markdown file per strategy. Each file
says when the strategy applies, what to listen for, when not to use it, the
moves to make, and phrases to say. Each suggestion on the dashboard shows the
strategy it came from. The bundled playbook has 21 strategies in seven
categories: preparation, opening, information, value creation, concessions,
closing, and defense against hardball tactics.

- **Add or edit strategies** by editing the Markdown files. The format is in
  [`strategies/README.md`](strategies/README.md). Check your changes with
  `negotiator strategies check`.
- **Tune it per negotiation** with `preferred_strategies` and
  `excluded_strategies` in the brief.
- **Keep it in its own repository** by setting `STRATEGIES_DIR` to a checkout of it.

The whole playbook (about 6k tokens) is sent in the cached system prompt, so
each analysis reads it from the cache instead of paying full price.

## Setup

You need Python 3.10+, plus accounts with
[Anthropic](https://platform.claude.com), [Twilio](https://www.twilio.com) (a
voice-capable phone number) and [Deepgram](https://deepgram.com).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # fill in the keys
```

Twilio has to reach the server over public HTTPS, so for local use run a tunnel
such as `ngrok http 8000` and put its URL in `PUBLIC_BASE_URL`.

## Rehearse from the command line

`replay` runs the coach over a written transcript, which is a cheap way to tune
your brief before the real meeting:

```bash
negotiator replay --brief examples/brief.example.yaml examples/transcript.example.txt --summary
```

## Test lab (web app)

The server includes a test lab at `/lab`. You fill in a brief, paste a
transcript, and watch the coach's output appear round by round, ending with
the debrief. It needs only `ANTHROPIC_API_KEY` and `NEGOTIATOR_ADMIN_TOKEN` in
`.env`. No Twilio, Deepgram or tunnel is involved.

```bash
negotiator serve
# open http://127.0.0.1:8000/lab, enter your admin token, click "Load example", then "Run the coach"
```

1. **Brief:** goal, BATNA, issues with targets and walk-away points, tradeables,
   red lines, what not to disclose, and which playbook strategies to prefer or exclude.
2. **Transcript:** one `Name: what they said` per line. Choose how often the
   coach analyses ("every 3 lines" is close to the live pace). The page shows
   how many Claude calls the run will make.
3. **Results:** each round shows the alerts and suggestions (tagged with their
   strategy) after that point in the conversation, next to the running offer
   ledger. The debrief comes last.

Every run calls the Claude API on your key. The lab is limited to 400 lines and
60 rounds per run, and it needs the admin token, so a publicly exposed server
can't run up your bill.

## Join a real meeting

```bash
negotiator serve                      # terminal 1 (behind your tunnel)
negotiator dial \
  --brief my-brief.yaml \
  --number +16465588656 \
  --digits "wwww84512345678#wwww#"    # meeting ID, pause, skip participant ID
```

`dial` prints a private dashboard URL. Open it, and join the meeting yourself as
usual. In `--digits`, `w` is a half-second pause. Most bridges want the meeting
ID followed by `#`, and some then ask for a participant ID or a passcode. Copy
the dial-in number and the order of the prompts from your meeting invite.

## Consent and recording laws

The agent transcribes the meeting. In many places (for example California,
Florida, Illinois, much of the EU) **every** participant has to consent to
recording or transcription. The agent appears in the meeting as a phone
participant, and by default it says the `ANNOUNCEMENT_TEXT` when it joins. Only
set `ANNOUNCE_ON_JOIN=false` if you have consent another way. You are
responsible for complying with the law and with your organisation's policies.

The coach is also told never to suggest lying, inventing competing offers, or
misrepresenting facts.

## Configuration

All settings are environment variables (see [`.env.example`](.env.example)).

| Variable | Default | Purpose |
|---|---|---|
| `COACH_EFFORT` | `low` | Claude effort for live coaching. `low` keeps tips fast; `medium`/`high` think harder but take longer. |
| `SUMMARY_EFFORT` | `high` | Claude effort for the debrief. |
| `COACH_MIN_INTERVAL` | `8` | Minimum seconds between analyses. |
| `COACH_MIN_NEW_WORDS` | `25` | New words needed before the next analysis. A private note triggers one straight away. |
| `ANNOUNCE_ON_JOIN` / `ANNOUNCEMENT_TEXT` | on | The disclosure the agent says when it joins. |
| `VALIDATE_TWILIO_SIGNATURES` | `true` | Rejects status callbacks that are not signed by Twilio. |
| `NEGOTIATOR_ADMIN_TOKEN` | — | Shared secret the CLI needs to start calls. |

## How the Claude calls are built

- **Model:** `claude-opus-5-5` with adaptive thinking (always on for this
  model) and `output_config.effort` as the speed/depth control.
- **Structured outputs:** each analysis is validated against a closed JSON schema
  (`negotiator/coach.py`) and then parsed into Pydantic models.
- **Prompt caching:** the system prompt and brief are cached. The transcript is
  sent as one content block per analysis window, with a cache breakpoint on the
  newest window, so each round reads the earlier conversation from the cache
  instead of paying full price for it again. Labels, notes, and the previous
  analysis go after the breakpoint because they change between rounds.
- **Prompt injection:** the transcript is treated as data. Anything said in the
  meeting that addresses "the AI" is ignored, and the coach can flag it.
- **Refusal fallback:** requests opt into server-side fallbacks
  (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`). A refused or
  failed round keeps the previous advice on screen and never stops the call.

## Security notes

- Dashboard URLs contain a per-session secret. Treat them like a password.
- The Twilio media stream is authenticated with the same secret, passed as a
  stream parameter.
- Sessions are held in memory, so restarting the server ends live sessions.
  Transcripts and debriefs are written to `SESSIONS_DIR`. Protect that
  directory, because it contains everything that was said.

## Development

```bash
pytest
```

The tests use fake Claude, Twilio and Deepgram clients, so they need no keys
and make no network calls.

## Layout

```
negotiator/
  brief.py        negotiation brief model (YAML)
  coach.py        Claude prompts, schema, analysis and debrief
  transcriber.py  Deepgram live streaming and diarization
  telephony.py    Twilio dial-out, TwiML, signature checks
  session.py      per-meeting state, coaching loop, persistence
  server.py       FastAPI: API, dashboard feed, Twilio media WebSocket
  strategies.py   loads and validates the playbook
  static/dashboard.html
  cli.py          serve / dial / replay / strategies
strategies/       the playbook: one Markdown file per strategy
```
