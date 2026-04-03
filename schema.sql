-- Phase 0: System Initialization Database Schema (Supabase PostgreSQL)

-- 1. Clinicians Table (Staff Profiles)
-- Links to auth.users in Supabase
CREATE TABLE clinicians (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- For actual Supabase Auth, use: id UUID PRIMARY KEY REFERENCES auth.users(id),
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(100), -- e.g., 'Attending', 'Nurse'
    department VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Patients Table
CREATE TABLE patients (
    patient_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_id VARCHAR(50),  -- MIMIC-III compatibility
    name VARCHAR(255) NOT NULL,
    date_of_birth DATE,      -- [NEW] Needed for age calculations (e.g. SOFA scoring)
    gender VARCHAR(20),      -- [NEW] Needed for lab reference baselines
    status VARCHAR(50) DEFAULT 'admitted', -- [NEW] Dashboard filtering 
    admission_timestamp TIMESTAMPTZ DEFAULT NOW(),
    nfc_tag_id VARCHAR(255) UNIQUE, -- [MODIFIED] More robust than a brittle URL string
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Raw Data Table
CREATE TABLE raw_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID REFERENCES patients(patient_id) ON DELETE CASCADE,
    uploader_id UUID REFERENCES clinicians(id) ON DELETE SET NULL, -- [NEW] Tracks who uploaded the file
    data_type VARCHAR(50),  -- 'note', 'lab', 'vital'
    raw_content TEXT,
    file_path TEXT,         -- [MODIFIED] Supabase Storage path is better than full URL
    status VARCHAR(50) DEFAULT 'pending', -- [NEW] Processing status: pending, processing, completed, error
    uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Parsed Data Table
CREATE TABLE parsed_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID REFERENCES patients(patient_id) ON DELETE CASCADE,
    raw_data_id UUID REFERENCES raw_data(id) ON DELETE CASCADE, -- [NEW] Data Lineage: traces parsed value back to raw file
    timestamp TIMESTAMPTZ,
    data_type VARCHAR(50),
    structured_json JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Reports Table
CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID REFERENCES patients(patient_id) ON DELETE CASCADE,
    report_version INT,
    disease_timeline JSONB,
    risk_flags JSONB,
    outlier_alerts JSONB,
    generated_at TIMESTAMPTZ DEFAULT NOW(),
    is_current BOOLEAN DEFAULT true
);

-- 6. Audit Logs Table (Healthcare Best Practice)
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    clinician_id UUID REFERENCES clinicians(id) ON DELETE SET NULL,
    patient_id UUID REFERENCES patients(patient_id) ON DELETE CASCADE,
    action VARCHAR(255) NOT NULL, -- e.g., 'uploaded_data', 'viewed_report', 'confirmed_redraw'
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Indexes (For Performance Optimization)
CREATE INDEX idx_reports_patient ON reports(patient_id);
CREATE INDEX idx_raw_status ON raw_data(status);
CREATE INDEX idx_parsed_timestamp ON parsed_data(timestamp);


