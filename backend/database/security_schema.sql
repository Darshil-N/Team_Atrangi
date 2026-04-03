-- HC01 Security Access Schema
-- Apply in Supabase SQL editor before PIN login is enabled.

CREATE TABLE IF NOT EXISTS pin_access (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    identifier      TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('patient', 'doctor', 'staff')),
    display_name    TEXT,
    pin_hash        TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    must_rotate     BOOLEAN NOT NULL DEFAULT false,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    last_login_at   TIMESTAMPTZ,
    pin_changed_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(identifier, role)
);

CREATE INDEX IF NOT EXISTS idx_pin_access_lookup
    ON pin_access (identifier, role, is_active);

CREATE TABLE IF NOT EXISTS security_audit_logs (
    id               BIGSERIAL PRIMARY KEY,
    actor_identifier TEXT,
    actor_role       TEXT,
    action           TEXT NOT NULL,
    status           TEXT NOT NULL,
    detail           TEXT,
    actor_ip         TEXT,
    occurred_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_security_audit_occurred
    ON security_audit_logs (occurred_at DESC);

-- Optional stricter policies for production:
-- 1) Enable RLS and allow authenticated service role only.
-- 2) Restrict direct frontend writes and route auth through backend endpoints.
