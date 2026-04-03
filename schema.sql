-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.audit_logs (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  clinician_id uuid,
  patient_id uuid,
  action character varying NOT NULL,
  timestamp timestamp with time zone DEFAULT now(),
  CONSTRAINT audit_logs_pkey PRIMARY KEY (id),
  CONSTRAINT audit_logs_clinician_id_fkey FOREIGN KEY (clinician_id) REFERENCES public.clinicians(id),
  CONSTRAINT audit_logs_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patients(patient_id)
);
CREATE TABLE public.clinicians (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  full_name character varying NOT NULL,
  role character varying,
  department character varying,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT clinicians_pkey PRIMARY KEY (id)
);
CREATE TABLE public.parsed_data (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  patient_id uuid,
  raw_data_id uuid,
  timestamp timestamp with time zone,
  data_type character varying,
  structured_json jsonb,
  created_at timestamp with time zone DEFAULT now(),
  CONSTRAINT parsed_data_pkey PRIMARY KEY (id),
  CONSTRAINT parsed_data_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patients(patient_id),
  CONSTRAINT parsed_data_raw_data_id_fkey FOREIGN KEY (raw_data_id) REFERENCES public.raw_data(id)
);
CREATE TABLE public.patients (
  patient_id uuid NOT NULL DEFAULT gen_random_uuid(),
  subject_id character varying,
  name character varying NOT NULL,
  date_of_birth date,
  gender character varying,
  status character varying DEFAULT 'admitted'::character varying,
  admission_timestamp timestamp with time zone DEFAULT now(),
  nfc_tag_id character varying UNIQUE,
  created_at timestamp with time zone DEFAULT now(),
  nfc_url text,
  CONSTRAINT patients_pkey PRIMARY KEY (patient_id)
);
CREATE TABLE public.raw_data (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  patient_id uuid,
  uploader_id uuid,
  data_type character varying,
  raw_content text,
  file_path text,
  status character varying DEFAULT 'pending'::character varying,
  uploaded_at timestamp with time zone DEFAULT now(),
  CONSTRAINT raw_data_pkey PRIMARY KEY (id),
  CONSTRAINT raw_data_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patients(patient_id),
  CONSTRAINT raw_data_uploader_id_fkey FOREIGN KEY (uploader_id) REFERENCES public.clinicians(id)
);
CREATE TABLE public.reports (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  patient_id uuid,
  report_version integer,
  disease_timeline jsonb,
  risk_flags jsonb,
  outlier_alerts jsonb,
  generated_at timestamp with time zone DEFAULT now(),
  is_current boolean DEFAULT true,
  diagnosis_updated boolean DEFAULT false,
  reasoning text DEFAULT ''::text,
  CONSTRAINT reports_pkey PRIMARY KEY (id),
  CONSTRAINT reports_patient_id_fkey FOREIGN KEY (patient_id) REFERENCES public.patients(patient_id)
);