# HC01 Frontend Portal UI

React + Vite portal suite for the HC01 ICU platform.

## Supabase + Backend Integration

This frontend now uses:
- Supabase for live tables/auth
- FastAPI backend for ingestion and AI agent pipeline execution

1. Copy env template:
  - `cp .env.example .env`
2. Set values in `.env`:
  - `VITE_SUPABASE_URL`
  - `VITE_SUPABASE_ANON_KEY`
  - `VITE_BACKEND_URL` (example: `http://localhost:8080`)
  - `VITE_PUBLIC_APP_URL` (example: `https://your-app.vercel.app`)
3. Use valid Supabase user credentials on login.

## PIN Access Setup (Required for new landing/login flow)

1. Apply security schema in Supabase SQL editor:
  - `backend/database/security_schema.sql`
2. Provision PIN credentials in table `pin_access`:
  - `role`: `patient` (4 digit), `doctor` (6 digit), `staff` (6 digit)
  - `identifier`: unique login handle
  - `pin_hash`: SHA-256 of `role:identifier:pin` (identifier lowercased)
3. Start frontend and login using role + identifier + PIN.

Note: For production, route credential operations through secured backend service keys and enable strict RLS policies.

## Included Screens

- Single Login Page (role-based redirect)
- Doctor Portal
  - Edit patient report
  - Analytical dashboard for health variation
  - Risk overview summary
- Staff Portal
  - Multi-file upload to backend `/upload/{patient_id}`
  - Auto-trigger analysis after upload via backend `/reports/analyse`
  - Refresh report from backend `/reports/{patient_id}/current`
  - Add patient form with required patient 4-digit PIN
  - NFC linker option
- NFC Route
  - `/nfc/:patientId` requires doctor ID + 6-digit PIN before showing patient report
- Patient Portal
  - Doctor summary
  - Analytical dashboard
  - Lab history
  - Care team
  - Vaccinations

## Run

1. Open terminal in `frontend/`
2. Install dependencies:
   - `npm install`
3. Start dev server:
   - `npm run dev`
4. Open the URL printed by Vite (usually `http://localhost:5173`)

## Notes

- Portals are wired to Supabase auth and tables: `patients`, `reports`, `parsed_data`, and `clinicians`.
- Report updates are also fetched via backend API and displayed in a structured clinical report layout.
- If some optional columns are missing in your schema, the UI uses safe fallbacks.
- Compliance-oriented controls implemented in UI flow:
  - Role-based access boundaries (`doctor`, `staff`, `patient`)
  - Failed login lockout with cooldown
  - Session inactivity timeout (15 minutes)
  - Security audit logging for login and PIN change events

## Hosting SPA Routes

- Vercel rewrite config: `vercel.json`
- Netlify redirect config: `netlify.toml`

These ensure deep links such as `/nfc/<patient_uuid>` resolve correctly in production.
