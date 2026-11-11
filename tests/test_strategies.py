import pytest

from negotiator.strategies import CATEGORIES, Playbook, PlaybookError, parse_strategy

GOOD = """---
id: test-move
name: Test move
category: closing
summary: Do the thing.
signals: ["one more thing"]
---
## Moves
- Step one.
"""


def test_bundled_playbook_is_valid():
    playbook = Playbook.load()
    assert len(playbook) >= 20
    assert {s.category for s in playbook.strategies} == set(CATEGORIES)
    for s in playbook.strategies:
        assert s.use_when and s.signals, s.id
        for section in ("## Moves", "## Say it like this", "## Watch out"):
            assert section in s.body, (s.id, section)


def test_parse_and_render():
    s = parse_strategy(GOOD, "x.md")
    text = s.render()
    assert text.startswith('<strategy id="test-move" category="closing">')
    assert "- one more thing" in text and "Step one." in text


@pytest.mark.parametrize("bad", [
    "no front matter",
    GOOD.replace("category: closing", "category: magic"),
    GOOD.replace("id: test-move", "id: Test Move"),
    GOOD.replace("summary: Do the thing.\n", ""),
])
def test_invalid_strategies_are_rejected(bad):
    with pytest.raises(PlaybookError):
        parse_strategy(bad, "bad.md")


def test_duplicate_ids_and_unknown_brief_ids(tmp_path):
    (tmp_path / "a.md").write_text(GOOD)
    (tmp_path / "README.md").write_text("ignored")
    assert Playbook.load(tmp_path).ids == ["test-move"]
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text(GOOD)
    with pytest.raises(PlaybookError, match="duplicate"):
        Playbook.load(tmp_path)
    with pytest.raises(PlaybookError, match="unknown"):
        Playbook([parse_strategy(GOOD)]).select(["nope"], [])
