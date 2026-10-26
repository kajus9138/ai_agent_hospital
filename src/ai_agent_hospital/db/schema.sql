-- Schema das threads de conversa. Idempotente: pode rodar a cada inicialização.
-- gen_random_uuid() é nativo a partir do PostgreSQL 13.

CREATE TABLE IF NOT EXISTS threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Ordem de inserção: timestamps podem empatar (resolução de microssegundo), seq não.
    seq BIGINT GENERATED ALWAYS AS IDENTITY,
    thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content TEXT NOT NULL,
    tool_calls JSONB,
    -- clock_timestamp() e não NOW(): NOW() é fixo na transação.
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages (thread_id, seq);
