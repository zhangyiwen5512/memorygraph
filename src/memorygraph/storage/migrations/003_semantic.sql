-- 003_semantic.sql — semantic annotations, unknowns, insights, modules
-- Per-annotation granularity: each symbol annotation is an independent row.
-- Replaces the JSON-file semantic store (.memorygraph/semantic/<hash>.json).

CREATE TABLE IF NOT EXISTS semantic_annotations (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'unknown',
    summary         TEXT NOT NULL DEFAULT '',
    design_intent   TEXT NOT NULL DEFAULT '',
    pitfalls        TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'manual',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(file_path, symbol)
);

CREATE INDEX IF NOT EXISTS idx_semantic_annotations_file
    ON semantic_annotations(file_path);

CREATE INDEX IF NOT EXISTS idx_semantic_annotations_symbol
    ON semantic_annotations(symbol);

CREATE TABLE IF NOT EXISTS semantic_unknowns (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    question        TEXT NOT NULL,
    context         TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'manual',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(file_path, symbol, question)
);

CREATE INDEX IF NOT EXISTS idx_semantic_unknowns_file
    ON semantic_unknowns(file_path);

CREATE TABLE IF NOT EXISTS semantic_insights (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL,
    insight         TEXT NOT NULL,
    related_symbols TEXT[] NOT NULL DEFAULT '{}',
    source          TEXT NOT NULL DEFAULT 'manual',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semantic_insights_file
    ON semantic_insights(file_path);

CREATE TABLE IF NOT EXISTS semantic_modules (
    id              SERIAL PRIMARY KEY,
    file_path       TEXT NOT NULL UNIQUE,
    module_summary  TEXT NOT NULL DEFAULT '',
    module_roles    JSONB NOT NULL DEFAULT '{}',
    metrics         JSONB NOT NULL DEFAULT '{}',
    odors           JSONB NOT NULL DEFAULT '[]',
    source          TEXT NOT NULL DEFAULT 'manual',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_semantic_modules_file
    ON semantic_modules(file_path);

-- Migration tracking
INSERT INTO schema_migrations (version, description) VALUES
    (3, 'semantic annotations, unknowns, insights, modules (PG-native semantic store)')
ON CONFLICT (version) DO NOTHING;
