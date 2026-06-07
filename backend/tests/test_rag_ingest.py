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


def test_embed_texts_retries_timeout_before_success(monkeypatch):
    calls = {"count": 0}

    def fake_request_json(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("timed out")
        return {"data": [{"embedding": [0.9, 0.8]}]}

    monkeypatch.setattr(ingest, "request_json", fake_request_json)
    monkeypatch.setattr(ingest.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "2")

    embeddings = ingest.embed_texts(["bonjour"])

    assert embeddings == [[0.9, 0.8]]
    assert calls["count"] == 3


def test_embed_texts_reports_attempt_count_when_retries_exhausted(monkeypatch):
    monkeypatch.setattr(ingest, "request_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))
    monkeypatch.setattr(ingest.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("EMBEDDING_MAX_RETRIES", "1")

    with pytest.raises(RuntimeError, match=r"after 2 attempt\(s\)"):
        ingest.embed_texts(["bonjour"])


def test_embed_texts_batches_requests(monkeypatch):
    calls = []

    def fake_request_json(_method, _url, payload=None, timeout_seconds=0):
        calls.append((payload, timeout_seconds))
        inputs = payload["input"]
        return {"data": [{"embedding": [float(index)]} for index, _ in enumerate(inputs)]}

    monkeypatch.setattr(ingest, "request_json", fake_request_json)
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "2")

    embeddings = ingest.embed_texts(["a", "b", "c", "d", "e"])

    assert len(calls) == 3
    assert [len(call[0]["input"]) for call in calls] == [2, 2, 1]
    assert len(embeddings) == 5


def test_embed_texts_rejects_non_positive_batch_size(monkeypatch):
    monkeypatch.setenv("EMBEDDING_BATCH_SIZE", "0")

    with pytest.raises(RuntimeError, match="EMBEDDING_BATCH_SIZE"):
        ingest.embed_texts(["bonjour"])
