BEGIN;

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
    ON chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_leads_session
    ON leads (session_id);

CREATE INDEX IF NOT EXISTS idx_lead_events_lead
    ON lead_events (lead_id, created_at);

CREATE INDEX IF NOT EXISTS idx_export_logs_created
    ON export_logs (created_at);

CREATE INDEX IF NOT EXISTS idx_kb_documents_status
    ON kb_documents (status);

CREATE INDEX IF NOT EXISTS idx_kb_documents_ingestion_run
    ON kb_documents (ingestion_run_id);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_document
    ON kb_chunks (document_id, chunk_index);

COMMIT;
