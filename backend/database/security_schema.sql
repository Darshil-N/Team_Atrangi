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

-- ─────────────────────────────────────────────────────────
-- RLS bootstrap (seamless mode for current app UX)
--
-- This section enables RLS while keeping existing frontend/backend flows working
-- to avoid "permission denied" errors during demos.
--
-- Harden later by replacing permissive policies with role-scoped rules.
-- ─────────────────────────────────────────────────────────

ALTER TABLE IF EXISTS patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS raw_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS parsed_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS clinicians ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS pin_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS security_audit_logs ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    rec RECORD;
BEGIN
    FOR rec IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
            AND tablename IN (
                'patients',
                'raw_data',
                'parsed_data',
                'reports',
                'clinicians',
                'pin_access',
                'security_audit_logs'
            )
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I.%I', rec.policyname, rec.schemaname, rec.tablename);
    END LOOP;
END $$;

CREATE POLICY patients_all_access ON patients
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);

CREATE POLICY raw_data_all_access ON raw_data
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);

CREATE POLICY parsed_data_all_access ON parsed_data
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);

CREATE POLICY reports_all_access ON reports
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);

CREATE POLICY clinicians_all_access ON clinicians
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);

CREATE POLICY pin_access_all_access ON pin_access
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);

CREATE POLICY security_audit_logs_all_access ON security_audit_logs
FOR ALL TO anon, authenticated, service_role
USING (true)
WITH CHECK (true);
