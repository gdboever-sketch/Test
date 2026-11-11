"""The negotiation brief: what you want, what you can give, and when to walk away."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Issue(BaseModel):
    """One negotiable term (price, term length, payment terms, ...)."""

    name: str
    target: str = Field(description="The outcome you are aiming for.")
    walk_away: str | None = Field(
        default=None, description="The worst value you would still accept."
    )
    priority: int = Field(default=3, ge=1, le=5, description="5 = most important.")
    notes: str | None = None


class NegotiationBrief(BaseModel):
    title: str
    me: str = Field(description="Who you are and who you represent.")
    counterpart: str = Field(description="Who is on the other side and what you know about them.")
    goal: str = Field(description="The deal you want, in one or two sentences.")
    batna: str = Field(description="Your best alternative if there is no deal.")
    issues: list[Issue] = Field(default_factory=list)
    tradeables: list[str] = Field(
        default_factory=list, description="Things you can concede cheaply."
    )
    red_lines: list[str] = Field(
        default_factory=list, description="Things you must never agree to."
    )
    do_not_disclose: list[str] = Field(
        default_factory=list, description="Information you must not reveal."
    )
    context: str | None = Field(default=None, description="Background, history, deadlines.")
    style: str | None = Field(default=None, description="How you want to come across.")

    @classmethod
    def load(cls, path: str | Path) -> "NegotiationBrief":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)

    def render(self) -> str:
        """Render the brief as plain text for the model."""
        lines = [
            f"Negotiation: {self.title}",
            f"Me: {self.me}",
            f"Counterpart: {self.counterpart}",
            f"Goal: {self.goal}",
            f"BATNA (my best alternative to a deal): {self.batna}",
        ]
        if self.issues:
            lines.append("Issues (priority 5 = most important):")
            for issue in sorted(self.issues, key=lambda i: -i.priority):
                walk = f"; walk-away: {issue.walk_away}" if issue.walk_away else ""
                note = f"; notes: {issue.notes}" if issue.notes else ""
                lines.append(
                    f"- {issue.name} (priority {issue.priority}): target {issue.target}{walk}{note}"
                )
        for label, items in (
            ("Tradeables (cheap for me to give)", self.tradeables),
            ("Red lines (never agree to)", self.red_lines),
            ("Do not disclose", self.do_not_disclose),
        ):
            if items:
                lines.append(f"{label}:")
                lines.extend(f"- {item}" for item in items)
        if self.context:
            lines.append(f"Context: {self.context}")
        if self.style:
            lines.append(f"Preferred style: {self.style}")
        return "\n".join(lines)
