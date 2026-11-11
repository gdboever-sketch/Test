import asyncio
import json

from negotiator.coach import COACHING_SCHEMA, Coach, CoachingUpdate

from .conftest import ANALYSIS, FakeClaude


def test_request_shape_and_caching(brief, settings, fake_claude):
    coach = Coach(brief, settings, client=fake_claude)
    req = coach.build_request(["[00:01] Speaker 0: hi", "[00:09] Speaker 1: hello"], None, {0: "Me"}, ["note"])
    assert req["model"] == "claude-opus-5-5"
    assert "temperature" not in req and "thinking" not in req
    assert req["fallbacks"] == "default"
    assert req["output_config"]["format"]["schema"] is COACHING_SCHEMA
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Annual price" in req["system"][0]["text"]
    blocks = req["messages"][0]["content"]
    # Two transcript windows, cache breakpoint on the newest, then the volatile tail.
    assert len(blocks) == 3
    assert "cache_control" not in blocks[0]
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["text"].endswith("</transcript>")
    assert "Speaker 0: Me" in blocks[2]["text"] and "- note" in blocks[2]["text"]


def test_earlier_windows_are_byte_identical_between_rounds(brief, settings, fake_claude):
    coach = Coach(brief, settings, client=fake_claude)
    first = coach.build_request(["a", "b"], None, {})
    second = coach.build_request(["a", "b", "c"], CoachingUpdate.model_validate(ANALYSIS), {0: "Me"})
    assert first["system"] == second["system"]
    assert first["messages"][0]["content"][0]["text"] == second["messages"][0]["content"][0]["text"]


def test_analyze_parses_structured_output(brief, settings, fake_claude):
    update = asyncio.run(Coach(brief, settings, client=fake_claude).analyze(["x"], None, {}))
    assert update.alerts[0].severity == "critical"
    assert update.offers[0].value == "$480k"


def test_analyze_returns_none_on_refusal_or_bad_json(brief, settings):
    refused = FakeClaude(stop_reason="refusal")
    assert asyncio.run(Coach(brief, settings, client=refused).analyze(["x"], None, {})) is None
    garbled = FakeClaude(analysis_text=json.dumps({"suggestions": "nope"}))
    assert asyncio.run(Coach(brief, settings, client=garbled).analyze(["x"], None, {})) is None


def test_schema_is_closed_and_fully_required():
    def walk(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        elif node.get("type") == "array":
            walk(node["items"])

    walk(COACHING_SCHEMA)
