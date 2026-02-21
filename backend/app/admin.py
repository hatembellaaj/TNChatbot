import csv
import io
import json
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pypdf import PdfReader

from app.db import get_connection
from app.rag.ingest import (
    derive_intent_from_path,
    embed_texts,
    ensure_qdrant_collection,
    estimate_tokens,
    upsert_qdrant_points,
    chunk_text,
)

ADMIN_CONFIG_KEYS = ("audience_metrics", "offers_copy", "email_config", "sectors")


def _get_admin_password() -> str:
    expected = os.getenv("ADMIN_PASSWORD")
    if not expected:
        raise HTTPException(status_code=500, detail="ADMIN_PASSWORD not configured")
    return expected


def _ensure_admin_password(password: str | None) -> None:
    expected = _get_admin_password()
    if not password or password != expected:
        raise HTTPException(status_code=401, detail="Invalid admin password")


def require_admin_password(
    x_admin_password: str | None = Header(None),
) -> None:
    _ensure_admin_password(x_admin_password)


auth_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_admin_password)])


@auth_router.post("/api/admin/login")
def login_admin(payload: Dict[str, str] = Body(...)) -> Dict[str, bool]:
    _ensure_admin_password(payload.get("password"))
    return {"ok": True}


def load_admin_config(keys: Iterable[str] = ADMIN_CONFIG_KEYS) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    keys_list = list(keys)
    if not keys_list:
        return config
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, value FROM admin_config WHERE key = ANY(%s)",
                (keys_list,),
            )
            for key, value in cur.fetchall():
                config[key] = value
    return config


def _upsert_config(key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_config (key, value, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key)
                DO UPDATE SET value = EXCLUDED.value, updated_at = NOW()
                """,
                (key, json.dumps(payload)),
            )
    return payload


def _get_config(key: str) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM admin_config WHERE key = %s", (key,))
            row = cur.fetchone()
            if not row:
                return {}
            return row[0]


@router.get("/api/admin/audience-metrics")
def get_audience_metrics() -> Dict[str, Any]:
    return {"key": "audience_metrics", "value": _get_config("audience_metrics")}


@router.put("/api/admin/audience-metrics")
def put_audience_metrics(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "audience_metrics", "value": _upsert_config("audience_metrics", payload)}


@router.get("/api/admin/offers-copy")
def get_offers_copy() -> Dict[str, Any]:
    return {"key": "offers_copy", "value": _get_config("offers_copy")}


@router.put("/api/admin/offers-copy")
def put_offers_copy(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "offers_copy", "value": _upsert_config("offers_copy", payload)}


@router.get("/api/admin/email-config")
def get_email_config() -> Dict[str, Any]:
    return {"key": "email_config", "value": _get_config("email_config")}


@router.put("/api/admin/email-config")
def put_email_config(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "email_config", "value": _upsert_config("email_config", payload)}


@router.get("/api/admin/sectors")
def get_sectors() -> Dict[str, Any]:
    return {"key": "sectors", "value": _get_config("sectors")}


@router.put("/api/admin/sectors")
def put_sectors(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    return {"key": "sectors", "value": _upsert_config("sectors", payload)}


@router.get("/api/admin/leads")
def get_leads(format: str | None = Query(default=None)) -> Any:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, full_name, company, email, phone, entry_path, lead_type,
                       extra_json, created_at
                FROM leads
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()

    leads: List[Dict[str, Any]] = []
    for row in rows:
        (
            lead_id,
            full_name,
            company,
            email,
            phone,
            entry_path,
            lead_type,
            extra_json,
            created_at,
        ) = row
        leads.append(
            {
                "id": str(lead_id),
                "full_name": full_name,
                "company": company,
                "email": email,
                "phone": phone,
                "entry_path": entry_path,
                "lead_type": lead_type,
                "extra_json": extra_json or {},
                "created_at": created_at.isoformat() if created_at else None,
            }
        )

    if format and format.lower() == "csv":
        buffer = io.StringIO()
        fieldnames = [
            "id",
            "full_name",
            "company",
            "email",
            "phone",
            "entry_path",
            "lead_type",
            "extra_json",
            "created_at",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            row = dict(lead)
            row["extra_json"] = json.dumps(row["extra_json"], ensure_ascii=False)
            writer.writerow(row)
        buffer.seek(0)
        headers = {"Content-Disposition": "attachment; filename=leads.csv"}
        return StreamingResponse(buffer, media_type="text/csv", headers=headers)

    return {"count": len(leads), "items": leads}


@router.get("/api/admin/overview")
def get_overview() -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chat_sessions")
            sessions_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM chat_messages")
            messages_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM leads")
            leads_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM kb_documents")
            kb_documents_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM kb_chunks")
            kb_chunks_count = cur.fetchone()[0]

    return {
        "sessions": sessions_count,
        "messages": messages_count,
        "leads": leads_count,
        "kb_documents": kb_documents_count,
        "kb_chunks": kb_chunks_count,
    }


@router.get("/api/admin/conversations")
def get_conversations(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chat_sessions")
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT session_id, step, created_at
                FROM chat_sessions
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            sessions = cur.fetchall()

            session_ids = [row[0] for row in sessions]
            messages_by_session: Dict[str, List[Dict[str, Any]]] = {
                str(session_id): [] for session_id in session_ids
            }
            if session_ids:
                cur.execute(
                    """
                    SELECT session_id, role, content, step, created_at
                    FROM chat_messages
                    WHERE session_id = ANY(%s)
                    ORDER BY created_at ASC
                    """,
                    (session_ids,),
                )
                for session_id, role, content, step, created_at in cur.fetchall():
                    messages_by_session[str(session_id)].append(
                        {
                            "role": role,
                            "content": content,
                            "step": step,
                            "created_at": created_at.isoformat()
                            if created_at
                            else None,
                        }
                    )

    items = [
        {
            "session_id": str(session_id),
            "step": step,
            "created_at": created_at.isoformat() if created_at else None,
            "messages": messages_by_session.get(str(session_id), []),
        }
        for session_id, step, created_at in sessions
    ]
    return {"total": total, "count": len(items), "items": items}


@router.get("/api/admin/kb/documents")
def get_kb_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM kb_documents")
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT d.id, d.source_type, d.source_uri, d.title, d.status,
                       d.created_at, d.updated_at, COUNT(c.id) AS chunk_count
                FROM kb_documents d
                LEFT JOIN kb_chunks c ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.updated_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()

    items = []
    for (
        document_id,
        source_type,
        source_uri,
        title,
        status,
        created_at,
        updated_at,
        chunk_count,
    ) in rows:
        items.append(
            {
                "id": str(document_id),
                "source_type": source_type,
                "source_uri": source_uri,
                "title": title,
                "status": status,
                "created_at": created_at.isoformat() if created_at else None,
                "updated_at": updated_at.isoformat() if updated_at else None,
                "chunk_count": chunk_count,
            }
        )

    return {"total": total, "count": len(items), "items": items}


@router.get("/api/admin/kb/chunks")
def get_kb_chunks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    document_id: str | None = Query(default=None),
    query: str | None = Query(default=None),
) -> Dict[str, Any]:
    filters: List[str] = []
    params: List[Any] = []
    if document_id:
        filters.append("c.document_id = %s")
        params.append(document_id)
    if query:
        filters.append("c.content ILIKE %s")
        params.append(f"%{query}%")

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM kb_chunks c {where_clause}",
                tuple(params),
            )
            total = cur.fetchone()[0]
            params_with_paging = params + [limit, offset]
            cur.execute(
                f"""
                SELECT c.id, c.document_id, c.chunk_index, c.content, c.token_count,
                       c.created_at, d.title, d.source_uri
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                {where_clause}
                ORDER BY c.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params_with_paging),
            )
            rows = cur.fetchall()

    items = []
    for (
        chunk_id,
        doc_id,
        chunk_index,
        content,
        token_count,
        created_at,
        title,
        source_uri,
    ) in rows:
        items.append(
            {
                "id": str(chunk_id),
                "document_id": str(doc_id),
                "chunk_index": chunk_index,
                "content": content,
                "token_count": token_count,
                "created_at": created_at.isoformat() if created_at else None,
                "title": title,
                "source_uri": source_uri,
            }
        )

    return {"total": total, "count": len(items), "items": items}


def _normalize_chunk_params(chunk_size: int | None, overlap: int | None) -> tuple[int, int]:
    resolved_chunk_size = chunk_size or int(os.getenv("RAG_CHUNK_SIZE", "200"))
    resolved_overlap = overlap if overlap is not None else int(os.getenv("RAG_CHUNK_OVERLAP", "40"))
    if resolved_chunk_size <= 0:
        raise HTTPException(status_code=400, detail="chunk_size doit être supérieur à 0")
    if resolved_overlap < 0:
        raise HTTPException(status_code=400, detail="overlap doit être supérieur ou égal à 0")
    if resolved_overlap >= resolved_chunk_size:
        raise HTTPException(
            status_code=400,
            detail="overlap doit être strictement inférieur à chunk_size",
        )
    return resolved_chunk_size, resolved_overlap




def _ingest_document(
    *,
    title: str,
    source_uri: str,
    content: str,
    chunk_size: int,
    overlap: int,
    source_type: str = "admin",
    report: Callable[[str, Dict[str, Any]], None] | None = None,
) -> Dict[str, Any]:
    if report:
        report("chunking_started", {"chunk_size": chunk_size, "overlap": overlap})
    chunks = chunk_text(content, chunk_size, overlap)
    if not chunks:
        raise HTTPException(status_code=400, detail="Aucun chunk généré")

    if report:
        report("chunking_completed", {"chunks": len(chunks)})
        report("embedding_started", {"chunks": len(chunks)})
    try:
        embeddings = embed_texts(chunks)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not embeddings or not embeddings[0]:
        raise HTTPException(status_code=502, detail="Les embeddings n'ont pas pu être générés")

    if report:
        report("embedding_completed", {"dimension": len(embeddings[0]), "count": len(embeddings)})
        report("qdrant_collection_prepare", {"dimension": len(embeddings[0])})
    ensure_qdrant_collection(len(embeddings[0]))
    intent = derive_intent_from_path(Path(f"{title}.txt"))

    if report:
        report("database_write_started", {})
    with get_connection() as conn:
        run_id = conn.execute(
            "INSERT INTO kb_ingestion_runs (status) VALUES ('running') RETURNING id"
        ).fetchone()[0]
        doc_id = conn.execute(
            """
            INSERT INTO kb_documents (ingestion_run_id, source_type, source_uri, title, status)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (run_id, source_type, source_uri, title, "processing"),
        ).fetchone()[0]

        points: List[Dict[str, Any]] = []
        rows: List[Dict[str, Any]] = []
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            chunk_id = uuid.uuid4()
            token_count = estimate_tokens(chunk)
            conn.execute(
                """
                INSERT INTO kb_chunks (id, document_id, chunk_index, content, embedding, token_count)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (chunk_id, doc_id, index, chunk, json.dumps(embedding), token_count),
            )
            rows.append(
                {
                    "chunk_id": str(chunk_id),
                    "chunk_index": index,
                    "token_count": token_count,
                    "content_preview": chunk[:220],
                    "embedding_dimension": len(embedding),
                }
            )
            points.append(
                {
                    "id": str(chunk_id),
                    "vector": embedding,
                    "payload": {
                        "document_id": str(doc_id),
                        "chunk_index": index,
                        "content": chunk,
                        "intent": intent,
                        "source_uri": source_uri,
                        "title": title,
                    },
                }
            )

        if report:
            report("database_chunks_inserted", {"rows": len(rows)})
            report("qdrant_upsert_started", {"points": len(points)})
        upsert_qdrant_points(points)
        if report:
            report("qdrant_upsert_completed", {"points": len(points)})
        conn.execute(
            "UPDATE kb_documents SET status = %s, updated_at = NOW() WHERE id = %s",
            ("ready", doc_id),
        )
        conn.execute(
            """
            UPDATE kb_ingestion_runs
            SET status = %s, finished_at = NOW(), stats = %s
            WHERE id = %s
            """,
            (
                "finished",
                json.dumps({"documents": 1, "chunks": len(rows), "skipped": 0}),
                run_id,
            ),
        )

    if report:
        report("ingestion_completed", {"run_id": str(run_id), "document_id": str(doc_id), "chunks": len(rows)})

    return {
        "run_id": str(run_id),
        "document_id": str(doc_id),
        "title": title,
        "source_uri": source_uri,
        "status": "ready",
        "rows": rows,
    }


def _decode_upload_content(upload: UploadFile, raw_content: bytes) -> str:
    if not raw_content:
        raise HTTPException(status_code=400, detail="Le fichier uploadé est vide")

    content_type = (upload.content_type or "").lower()
    filename = (upload.filename or "").lower()

    try:
        if "pdf" in content_type or filename.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(raw_content))
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            content = "\n\n".join(page for page in pages if page)
            if not content:
                raise HTTPException(status_code=400, detail="Aucun texte exploitable trouvé dans le PDF")
            return content

        if "jsonl" in content_type or filename.endswith(".jsonl"):
            lines = raw_content.decode("utf-8").splitlines()
            parsed_lines = []
            for index, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                try:
                    parsed_lines.append(json.dumps(json.loads(line), ensure_ascii=False, indent=2))
                except json.JSONDecodeError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail=f"JSONL invalide à la ligne {index}",
                    ) from exc
            return "\n\n".join(parsed_lines)

        if "json" in content_type or filename.endswith(".json"):
            parsed = json.loads(raw_content.decode("utf-8"))
            return json.dumps(parsed, ensure_ascii=False, indent=2)

        return raw_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Encodage non supporté. Utilisez un fichier UTF-8 (.txt/.md/.json/.jsonl).",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Fichier JSON invalide") from exc


def _transform_content_to_toon(content: str) -> str:
    paragraphs = [block.strip() for block in content.split("\n\n") if block.strip()]
    if not paragraphs:
        raise HTTPException(status_code=400, detail="Le contenu à transformer est vide")

    transformed: List[str] = []
    for paragraph in paragraphs:
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        transformed_lines = [f"🎬 {line.rstrip('.!?')} !" for line in lines]
        transformed.append("\n".join(transformed_lines))
    return "\n\n".join(transformed)


@router.post("/api/admin/kb/ingestion/upload/parse")
async def parse_ingestion_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    filename = (file.filename or "document").strip()
    content = _decode_upload_content(file, await file.read())
    return {
        "filename": filename,
        "content": content,
        "char_count": len(content),
        "token_estimate": estimate_tokens(content),
    }


@router.post("/api/admin/kb/ingestion/transform")
def transform_ingestion_content(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    mode = str(payload.get("mode") or "toon").strip().lower()
    content = str(payload.get("content") or "")
    if mode != "toon":
        raise HTTPException(status_code=400, detail="Mode de transformation non supporté")
    transformed_content = _transform_content_to_toon(content)
    return {
        "mode": mode,
        "original_char_count": len(content),
        "transformed_char_count": len(transformed_content),
        "transformed_content": transformed_content,
    }


@router.post("/api/admin/kb/ingestion/preview")
def preview_ingestion(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    title = str(payload.get("title") or "").strip() or "Document"
    content = str(payload.get("content") or "")
    source_uri = str(payload.get("source_uri") or title)
    include_embeddings = bool(payload.get("include_embeddings", True))
    chunk_size, overlap = _normalize_chunk_params(payload.get("chunk_size"), payload.get("overlap"))

    if not content.strip():
        raise HTTPException(status_code=400, detail="Le contenu du document est vide")

    split_blocks = [block.strip() for block in content.split("\n\n") if block.strip()]
    chunks = chunk_text(content, chunk_size, overlap)
    preview_chunks: List[Dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        preview_chunks.append(
            {
                "chunk_index": index,
                "content": chunk,
                "token_count": estimate_tokens(chunk),
                "char_count": len(chunk),
            }
        )

    embeddings: List[List[float]] = []
    embedding_dimension = 0
    if include_embeddings and chunks:
        try:
            embeddings = embed_texts(chunks)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Impossible de générer les embeddings pour la prévisualisation: {exc}",
            ) from exc
        embedding_dimension = len(embeddings[0]) if embeddings and embeddings[0] else 0
        for index, values in enumerate(embeddings):
            preview_chunks[index]["embedding_dimension"] = len(values)
            preview_chunks[index]["embedding_preview"] = values[:8]

    return {
        "document": {
            "title": title,
            "source_uri": source_uri,
            "char_count": len(content),
            "token_estimate": estimate_tokens(content),
        },
        "params": {
            "chunk_size": chunk_size,
            "overlap": overlap,
            "include_embeddings": include_embeddings,
        },
        "split": {
            "block_count": len(split_blocks),
            "blocks": split_blocks,
        },
        "chunks": preview_chunks,
        "embeddings": {
            "generated": include_embeddings,
            "count": len(embeddings),
            "dimension": embedding_dimension,
        },
    }


@router.post("/api/admin/kb/ingestion/run")
def run_ingestion(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    title = str(payload.get("title") or "").strip() or "Document"
    content = str(payload.get("content") or "")
    source_uri = str(payload.get("source_uri") or title)
    chunk_size, overlap = _normalize_chunk_params(payload.get("chunk_size"), payload.get("overlap"))

    if not content.strip():
        raise HTTPException(status_code=400, detail="Le contenu du document est vide")

    return _ingest_document(
        title=title,
        source_uri=source_uri,
        content=content,
        chunk_size=chunk_size,
        overlap=overlap,
        source_type="admin",
    )




@router.post("/api/admin/kb/ingestion/run/stream")
def run_ingestion_stream(payload: Dict[str, Any] = Body(...)) -> StreamingResponse:
    title = str(payload.get("title") or "").strip() or "Document"
    content = str(payload.get("content") or "")
    source_uri = str(payload.get("source_uri") or title)
    chunk_size, overlap = _normalize_chunk_params(payload.get("chunk_size"), payload.get("overlap"))

    if not content.strip():
        raise HTTPException(status_code=400, detail="Le contenu du document est vide")

    def event_stream():
        events: queue.Queue[bytes | None] = queue.Queue()

        def push(event: str, data: Dict[str, Any]) -> None:
            message = {"event": event, "data": data}
            events.put((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))

        def worker() -> None:
            try:
                push("ingestion_started", {"title": title, "source_uri": source_uri})
                result = _ingest_document(
                    title=title,
                    source_uri=source_uri,
                    content=content,
                    chunk_size=chunk_size,
                    overlap=overlap,
                    source_type="admin",
                    report=push,
                )
                push("result", result)
            except HTTPException as exc:
                push("error", {"detail": exc.detail, "status_code": exc.status_code})
            except Exception as exc:  # pragma: no cover
                push("error", {"detail": str(exc), "status_code": 500})
            finally:
                events.put(None)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = events.get()
            if item is None:
                break
            yield item

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.post("/api/admin/kb/ingestion/upload")
async def run_ingestion_upload(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    source_uri: str | None = Form(default=None),
    chunk_size: int | None = Form(default=None),
    overlap: int | None = Form(default=None),
) -> Dict[str, Any]:
    resolved_chunk_size, resolved_overlap = _normalize_chunk_params(chunk_size, overlap)
    filename = (file.filename or "document.txt").strip()
    resolved_title = (title or Path(filename).stem).strip() or "Document"
    resolved_source_uri = (source_uri or f"admin/upload/{filename}").strip() or f"admin/upload/{filename}"

    content = _decode_upload_content(file, await file.read())
    if not content.strip():
        raise HTTPException(status_code=400, detail="Le contenu du document est vide")

    return _ingest_document(
        title=resolved_title,
        source_uri=resolved_source_uri,
        content=content,
        chunk_size=resolved_chunk_size,
        overlap=resolved_overlap,
        source_type="upload",
    )
