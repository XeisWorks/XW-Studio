"""Ideas JSON store tests."""
from pathlib import Path

import pytest

from xw_studio.services.ideas.store import IdeaEntry, IdeasStore


@pytest.fixture
def ideas_path(tmp_path: Path) -> Path:
    return tmp_path / "ideas.json"


def test_add_and_list(ideas_path: Path) -> None:
    store = IdeasStore(ideas_path)
    store.add_idea(IdeaEntry(title="A", body="alpha"))
    store.add_idea(IdeaEntry(title="B", body="beta"))
    rows = store.list_ideas()
    assert len(rows) == 2
    assert rows[0].title == "A"
