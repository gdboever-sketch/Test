"""Command line: run the server, dial into a meeting, or rehearse against a transcript."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .brief import NegotiationBrief
from .config import Settings, load_dotenv


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "negotiator.server:app_from_env", factory=True, host=args.host, port=args.port
    )


def cmd_dial(args: argparse.Namespace) -> None:
    token = os.environ.get("NEGOTIATOR_ADMIN_TOKEN", "")
    if not token:
        sys.exit("Set NEGOTIATOR_ADMIN_TOKEN (the same value the server uses).")
    brief = NegotiationBrief.load(args.brief)
    body = json.dumps(
        {"brief": brief.model_dump(), "number": args.number, "digits": args.digits}
    ).encode()
    request = urllib.request.Request(
        f"{args.server.rstrip('/')}/api/sessions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        sys.exit(f"Server refused the call ({e.code}): {e.read().decode(errors='replace')}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach the server at {args.server}: {e.reason}")
    print(f"Dialing. Call SID: {result['call_sid']}")
    print(f"Open your private dashboard:\n  {result['dashboard_url']}")


def cmd_strategies(args: argparse.Namespace) -> None:
    from .strategies import Playbook, PlaybookError

    directory = args.dir or Settings.from_env().strategies_dir
    try:
        playbook = Playbook.load(directory)
    except PlaybookError as e:
        sys.exit(f"Playbook error: {e}")
    if args.action == "check":
        print(f"OK: {len(playbook)} strategies")
        return
    category = None
    for s in playbook.strategies:
        if s.category != category:
            category = s.category
            print(f"\n{category}")
        print(f"  {s.id:28} {s.summary}")


def _parse_transcript(path: Path) -> list[tuple[str, str]]:
    lines = []
    for raw in path.read_text().splitlines():
        if ":" in raw and raw.strip():
            who, _, text = raw.partition(":")
            lines.append((who.strip(), text.strip()))
    return lines


async def _replay(args: argparse.Namespace) -> None:
    from .coach import Coach
    from .transcriber import Utterance

    settings = Settings.from_env()
    brief = NegotiationBrief.load(args.brief)
    coach = Coach(brief, settings)
    names = coach.playbook.names()
    lines = _parse_transcript(Path(args.transcript))
    if not lines:
        sys.exit("No 'Speaker: text' lines found in the transcript.")

    speakers: dict[str, int] = {}
    labels: dict[int, str] = {}
    utterances: list[Utterance] = []
    chunks: list[str] = []
    pending: list[Utterance] = []
    latest = None
    clock = 0.0

    for i, (who, text) in enumerate(lines, start=1):
        n = speakers.setdefault(who, len(speakers))
        labels[n] = who
        u = Utterance(n, text, clock, clock + 4)
        clock += 5
        utterances.append(u)
        pending.append(u)
        if i % args.every == 0 or i == len(lines):
            chunks.append("\n".join(p.render() for p in pending))
            pending = []
            print(f"\n=== after line {i}: {who}: {text}")
            update = await coach.analyze(chunks, latest, labels)
            if update is None:
                print("  (no update)")
                continue
            latest = update
            for a in update.alerts:
                print(f"  ! [{a.severity}] {a.text}")
            for s in update.suggestions:
                via = f"  ({names[s.strategy]})" if s.strategy in names else ""
                print(f"  > [{s.priority}/{s.kind}] {s.text}{via}\n      {s.rationale}")

    if latest:
        print("\n=== offers")
        for o in latest.offers:
            print(f"  {o.party:4} {o.term}: {o.value} ({o.status})")
    if args.summary:
        print("\n=== debrief\n")
        print(await coach.summarize("\n".join(u.render() for u in utterances), latest, labels))


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="negotiator", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="Run the server Twilio connects to.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    dial = sub.add_parser("dial", help="Have the running server dial into a meeting.")
    dial.add_argument("--brief", required=True, help="Path to a negotiation brief (YAML).")
    dial.add_argument("--number", required=True, help="Meeting dial-in number, e.g. +16465588656.")
    dial.add_argument(
        "--digits",
        help="Keys to press after connecting; w = half-second pause. e.g. 'wwww84512345678#wwww#'",
    )
    dial.add_argument("--server", default="http://127.0.0.1:8000")
    dial.set_defaults(func=cmd_dial)

    replay = sub.add_parser(
        "replay", help="Rehearse: run the coach over a written transcript, no phone needed."
    )
    replay.add_argument("--brief", required=True)
    replay.add_argument("transcript", help="Text file with one 'Speaker: what they said' per line.")
    replay.add_argument("--every", type=int, default=3, help="Analyse after every N lines.")
    replay.add_argument("--summary", action="store_true", help="Also write the debrief.")
    replay.set_defaults(func=lambda a: asyncio.run(_replay(a)))

    strategies = sub.add_parser("strategies", help="List or validate the strategy playbook.")
    strategies.add_argument("action", choices=["list", "check"])
    strategies.add_argument("--dir", help="Playbook folder (default: STRATEGIES_DIR or ./strategies).")
    strategies.set_defaults(func=cmd_strategies)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
