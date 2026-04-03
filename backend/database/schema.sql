-- HC01 Database Schema
-- Run this in Supabase SQL editor: https://app.supabase.com → SQL Editor
-- All tables use RLS disabled for hackathon simplicity.

-- ─────────────────────────────────────────────────────────
-- 1. Patients
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS patients (
    patient_id          UUID PRIMARY KEY,
    subject_id          VARCHAR(50),             -- MIMIC-III compatibility
    name                VARCHAR(255) NOT NULL,
    admission_timestamp TIMESTAMPTZ  DEFAULT NOW(),
    nfc_url             TEXT,
    created_at          TIMESTAMPTZ  DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────
-- 2. Raw uploaded file metadata
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS raw_data (
    id           SERIAL PRIMARY KEY,
    patient_id   UUID        REFERENCES patients(patient_id) ON DELETE CASCADE,
    data_type    VARCHAR(50),                    -- 'note' | 'lab' | 'vital'
    raw_content  TEXT,
    file_url     TEXT,                           -- Supabase Storage URL
    uploaded_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────
-- 3. Parsed / structured data (output of processing pipeline)
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS parsed_data (
    id               SERIAL PRIMARY KEY,
    patient_id       UUID        REFERENCES patients(patient_id) ON DELETE CASCADE,
    timestamp        TIMESTAMPTZ,               -- time the clinical event occurred
    data_type        VARCHAR(50),               -- 'note' | 'lab' | 'vital'
    structured_json  JSONB       NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast per-patient time-ordered queries used by state_builder
CREATE INDEX IF NOT EXISTS idx_parsed_data_patient_time
    ON parsed_data (patient_id, timestamp ASC);

-- ─────────────────────────────────────────────────────────
-- 4. Diagnostic reports (versioned, one current per patient)
-- ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reports (
    id                SERIAL PRIMARY KEY,
    patient_id        UUID        REFERENCES patients(patient_id) ON DELETE CASCADE,
    report_version    INT         NOT NULL DEFAULT 1,
    disease_timeline  JSONB       NOT NULL DEFAULT '[]',
    risk_flags        JSONB       NOT NULL DEFAULT '[]',
    outlier_alerts    JSONB       NOT NULL DEFAULT '[]',
    family_communication JSONB    NOT NULL DEFAULT '{}',
    diagnosis_updated BOOLEAN     NOT NULL DEFAULT false,
    reasoning         TEXT        NOT NULL DEFAULT '',
    generated_at      TIMESTAMPTZ DEFAULT NOW(),
    is_current        BOOLEAN     NOT NULL DEFAULT true
);

ALTER TABLE reports
ADD COLUMN IF NOT EXISTS family_communication JSONB NOT NULL DEFAULT '{}';

-- Only one report per patient should have is_current = true at any time.
-- Enforced in application logic (supabase_client.save_report).
CREATE INDEX IF NOT EXISTS idx_reports_patient_current
    ON reports (patient_id, is_current);
