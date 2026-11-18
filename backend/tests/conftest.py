"""Shared test setup."""

import pytest

from app.build import export


@pytest.fixture(autouse=True)
def _approved_glossary(monkeypatch) -> None:
    """The shipped glossary awaits the owner's approval (D81) and a release build refuses
    while any entry is unapproved. Release-path tests about summaries or verification run
    with every entry approved; test_glossary_contract.py tests the real, unapproved file."""
    approved = {k: {**e, "approved": True} for k, e in export.load_glossary().items()}
    monkeypatch.setattr(export, "load_glossary", lambda: approved)
