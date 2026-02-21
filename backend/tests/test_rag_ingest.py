import io
import sys
from pathlib import Path
from urllib.error import HTTPError

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2] / "backend"))

import app.rag.ingest as ingest  # noqa: E402


def test_embed_texts_wraps_timeout_error(monkeypatch):
    monkeypatch.setattr(ingest, "request_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))

    with pytest.raises(RuntimeError, match="Embedding request failed"):
        ingest.embed_texts(["bonjour"])


def test_embed_texts_includes_http_error_detail(monkeypatch):
    http_error = HTTPError(
        url="http://embeddings.local/v1/embeddings",
        code=500,
        msg="Internal Server Error",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"model unavailable"}'),
    )
    monkeypatch.setattr(ingest, "request_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error))

    with pytest.raises(RuntimeError, match=r"Embedding request failed \(500\)") as exc_info:
        ingest.embed_texts(["bonjour"])

    assert "model unavailable" in str(exc_info.value)


def test_embed_texts_uses_embedding_timeout_seconds_env(monkeypatch):
    observed = {}

    def fake_request_json(method, url, payload=None, timeout_seconds=0):
        observed["method"] = method
        observed["url"] = url
        observed["payload"] = payload
        observed["timeout_seconds"] = timeout_seconds
        return {"data": [{"embedding": [0.1, 0.2]}]}

    monkeypatch.setattr(ingest, "request_json", fake_request_json)
    monkeypatch.setenv("EMBEDDING_TIMEOUT_SECONDS", "77")

    embeddings = ingest.embed_texts(["bonjour"])

    assert embeddings == [[0.1, 0.2]]
    assert observed["timeout_seconds"] == 77.0
