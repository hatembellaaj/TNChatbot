BEGIN;

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tn_conversation_step') THEN
        CREATE TYPE tn_conversation_step AS ENUM (
            'start',
            'qualification',
            'proposal',
            'follow_up',
            'completed'
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tn_lead_need_type') THEN
        CREATE TYPE tn_lead_need_type AS ENUM (
            'audit',
            'implementation',
            'support',
            'other'
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tn_budget_range') THEN
        CREATE TYPE tn_budget_range AS ENUM (
            'under_5k',
            '5k_10k',
            '10k_25k',
            '25k_plus'
        );
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tn_lead_sector') THEN
        CREATE TYPE tn_lead_sector AS ENUM (
            'retail',
            'finance',
            'healthcare',
            'education',
            'public',
            'other'
        );
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'chat_sessions') THEN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'chat_sessions' AND column_name = 'id'
        ) THEN
            ALTER TABLE chat_sessions
                ADD COLUMN id UUID DEFAULT gen_random_uuid();
            UPDATE chat_sessions SET id = gen_random_uuid() WHERE id IS NULL;
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'chat_sessions'::regclass
              AND contype = 'p'
        ) THEN
            ALTER TABLE chat_sessions ADD PRIMARY KEY (id);
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'chat_sessions'::regclass
              AND contype IN ('p', 'u')
              AND pg_get_constraintdef(oid) LIKE '%(id)%'
        ) THEN
            ALTER TABLE chat_sessions ADD CONSTRAINT chat_sessions_id_unique UNIQUE (id);
        END IF;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'leads') THEN
        IF NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = 'leads' AND column_name = 'id'
        ) THEN
            ALTER TABLE leads
                ADD COLUMN id UUID DEFAULT gen_random_uuid();
            UPDATE leads SET id = gen_random_uuid() WHERE id IS NULL;
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'leads'::regclass
              AND contype = 'p'
        ) THEN
            ALTER TABLE leads ADD PRIMARY KEY (id);
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint
            WHERE conrelid = 'leads'::regclass
              AND contype IN ('p', 'u')
              AND pg_get_constraintdef(oid) LIKE '%(id)%'
        ) THEN
            ALTER TABLE leads ADD CONSTRAINT leads_id_unique UNIQUE (id);
        END IF;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_step tn_conversation_step NOT NULL DEFAULT 'start',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
    full_name TEXT,
    email TEXT,
    phone TEXT,
    sector tn_lead_sector,
    need_type tn_lead_need_type,
    budget_range tn_budget_range,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS lead_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS export_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    export_type TEXT NOT NULL,
    status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_config (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
