import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

import app.rag.ingest as ingest  # noqa: E402


def test_embed_texts_wraps_timeout_error(monkeypatch):
    monkeypatch.setattr(ingest, "request_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))

    with pytest.raises(RuntimeError, match="Embedding request failed"):
        ingest.embed_texts(["bonjour"])
