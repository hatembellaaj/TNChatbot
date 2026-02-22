import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

import app.rag.retrieve as retrieve  # noqa: E402


def test_retrieve_rag_selection_exposes_selected_chunks(monkeypatch):
    monkeypatch.setattr(
        retrieve,
        "retrieve_rag_context",
        lambda *_args, **_kwargs: "[1] chunk A\n\n[2] chunk B",
    )

    result = retrieve.retrieve_rag_selection("question")

    assert result.context == "[1] chunk A\n\n[2] chunk B"
    assert result.selected_chunks == [
        {"content": "[1] chunk A"},
        {"content": "[2] chunk B"},
    ]


def test_retrieve_rag_selection_handles_empty_context(monkeypatch):
    monkeypatch.setattr(retrieve, "retrieve_rag_context", lambda *_args, **_kwargs: "")

    result = retrieve.retrieve_rag_selection("question")

    assert result.context == ""
    assert result.selected_chunks == []
