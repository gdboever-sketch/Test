"""The strategy playbook: a folder of Markdown files the coach follows.

Each strategy is one `.md` file with YAML front matter and a Markdown body:

    ---
    id: conditional-concessions
    name: Conditional concessions
    category: concessions
    summary: Never give something without getting something back.
    use_when: [...]
    signals: [...]
    avoid_when: [...]
    ---
    ## Moves
    ...

The whole playbook goes into the coach's system prompt, which is cached for
the length of the call, so adding strategies costs little per analysis.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError

CATEGORIES = (
    "preparation",
    "opening",
    "information",
    "value-creation",
    "concessions",
    "closing",
    "defense",
)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "strategies"


class Strategy(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str
    category: str
    summary: str
    use_when: list[str] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)
    avoid_when: list[str] = Field(default_factory=list)
    body: str = ""
    source: str = ""

    def render(self) -> str:
        parts = [f'<strategy id="{self.id}" category="{self.category}">', f"# {self.name}", self.summary]
        for label, items in (
            ("Use when", self.use_when),
            ("Signals in the conversation", self.signals),
            ("Avoid when", self.avoid_when),
        ):
            if items:
                parts.append(f"{label}:\n" + "\n".join(f"- {i}" for i in items))
        if self.body.strip():
            parts.append(self.body.strip())
        parts.append("</strategy>")
        return "\n".join(parts)


class PlaybookError(ValueError):
    pass


def parse_strategy(text: str, source: str = "") -> Strategy:
    if not text.startswith("---"):
        raise PlaybookError(f"{source}: missing YAML front matter")
    try:
        _, front, body = text.split("---", 2)
    except ValueError as e:
        raise PlaybookError(f"{source}: front matter is not closed with ---") from e
    try:
        meta = yaml.safe_load(front) or {}
        strategy = Strategy.model_validate({**meta, "body": body.strip(), "source": source})
    except (yaml.YAMLError, ValidationError) as e:
        raise PlaybookError(f"{source}: {e}") from e
    if strategy.category not in CATEGORIES:
        raise PlaybookError(
            f"{source}: category {strategy.category!r} is not one of {', '.join(CATEGORIES)}"
        )
    return strategy


class Playbook:
    def __init__(self, strategies: list[Strategy]) -> None:
        seen: dict[str, str] = {}
        for s in strategies:
            if s.id in seen:
                raise PlaybookError(f"duplicate id {s.id!r} in {seen[s.id]} and {s.source}")
            seen[s.id] = s.source
        order = {c: i for i, c in enumerate(CATEGORIES)}
        self.strategies = sorted(strategies, key=lambda s: (order[s.category], s.id))

    @classmethod
    def load(cls, directory: str | Path | None = None) -> "Playbook":
        root = Path(directory) if directory else DEFAULT_DIR
        if not root.is_dir():
            raise PlaybookError(f"strategy directory not found: {root}")
        files = sorted(p for p in root.rglob("*.md") if p.name.lower() != "readme.md")
        return cls([parse_strategy(p.read_text(), str(p.relative_to(root))) for p in files])

    @property
    def ids(self) -> list[str]:
        return [s.id for s in self.strategies]

    def get(self, strategy_id: str) -> Strategy | None:
        return next((s for s in self.strategies if s.id == strategy_id), None)

    def select(self, preferred: list[str], excluded: list[str]) -> "Playbook":
        """Drop excluded strategies; check that every id named in the brief exists."""
        unknown = [i for i in [*preferred, *excluded] if i not in self.ids]
        if unknown:
            raise PlaybookError(f"unknown strategy ids in brief: {', '.join(unknown)}")
        return Playbook([s for s in self.strategies if s.id not in excluded])

    def names(self) -> dict[str, str]:
        return {s.id: s.name for s in self.strategies}

    def render(self, preferred: list[str] | None = None) -> str:
        lines = ["<playbook>"]
        if preferred:
            lines.append(
                "The user wants these strategies favoured when they fit: " + ", ".join(preferred)
            )
        lines.extend(s.render() for s in self.strategies)
        lines.append("</playbook>")
        return "\n\n".join(lines)

    def __len__(self) -> int:
        return len(self.strategies)
