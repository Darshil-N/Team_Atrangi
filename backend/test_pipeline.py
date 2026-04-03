"""
test_pipeline.py — End-to-end test for HC01 agent pipeline.

Runs the full pipeline DIRECTLY in Python (no server needed).
Seeds synthetic patient data into Supabase, runs all agents, prints results.

Usage (from backend/ directory):
    python test_pipeline.py            # Test Case A — stable patient
    python test_pipeline.py --outlier  # Test Case C — K+=14.0 lab error
    python test_pipeline.py --sepsis   # Test Case B — sepsis markers
"""
import sys
import asyncio
import json
import os

# Must be set BEFORE any HuggingFace/sentence-transformers import
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from datetime import datetime, timedelta, timezone
from database.supabase_client import create_patient, insert_parsed_data
from agents.orchestrator import run_pipeline


# ─────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────

def ts(days_ago: int = 0, hour: int = 8) -> str:
    """Return an ISO 8601 UTC timestamp N days ago."""
    t = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return t.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


# ─────────────────────────────────────────────────────────
# Test datasets
# ─────────────────────────────────────────────────────────

def build_stable_data(patient_id: str):
    """Test Case A: Normal labs, no concerning trends."""
    insert_parsed_data(patient_id, "note", ts(2),
        {"text": "Patient admitted for routine monitoring. No fever, no chills. "
                 "Vitals stable. Patient alert and oriented."})
    for day, wbc, lact, cr in [(2, 7.0, 0.9, 0.8), (1, 7.5, 1.0, 0.9), (0, 8.0, 1.1, 0.9)]:
        insert_parsed_data(patient_id, "lab", ts(day), {
            "values": {
                "WBC":        {"value": wbc,  "unit": "K/uL"},
                "Lactate":    {"value": lact, "unit": "mmol/L"},
                "Creatinine": {"value": cr,   "unit": "mg/dL"},
                "Potassium":  {"value": 4.1,  "unit": "mmol/L"},
            }
        })
    print("  Seeded: stable patient (normal labs, no symptoms)")


def build_sepsis_data(patient_id: str):
    """Test Case B: Rising WBC + Lactate + fever notes -> early sepsis."""
    insert_parsed_data(patient_id, "note", ts(3),
        {"text": "Patient presents with fever 38.8C, chills, and lethargy. "
                 "Appears fatigued. Suspected infection source unknown."})
    insert_parsed_data(patient_id, "note", ts(1),
        {"text": "Patient continues to have rigors. Tachycardia noted HR=118. "
                 "Blood pressure trending down 95/60. Clinician concerned about sepsis."})
    for day, wbc, lact, cr in [(3, 11.0, 1.2, 0.9), (2, 13.5, 1.8, 1.0),
                                (1, 15.2, 2.8, 1.2), (0, 17.8, 3.4, 1.4)]:
        insert_parsed_data(patient_id, "lab", ts(day), {
            "values": {
                "WBC":        {"value": wbc,  "unit": "K/uL"},
                "Lactate":    {"value": lact, "unit": "mmol/L"},
                "Creatinine": {"value": cr,   "unit": "mg/dL"},
                "Potassium":  {"value": 4.2,  "unit": "mmol/L"},
            }
        })
    print("  Seeded: sepsis patient (rising WBC/Lactate + fever notes)")


def build_outlier_data(patient_id: str):
    """Test Case C: K+=14.0 — impossible value, must be flagged, must NOT update diagnosis."""
    insert_parsed_data(patient_id, "note", ts(2),
        {"text": "Patient admitted for post-operative monitoring. "
                 "Mild discomfort reported. Vitals within acceptable limits."})
    for day, wbc, lact, potassium in [(3, 8.0, 1.0, 4.0), (2, 8.2, 1.1, 4.1),
                                       (1, 8.1, 1.0, 3.9), (0, 8.3, 1.1, 14.0)]:
        insert_parsed_data(patient_id, "lab", ts(day), {
            "values": {
                "WBC":       {"value": wbc,       "unit": "K/uL"},
                "Lactate":   {"value": lact,      "unit": "mmol/L"},
                "Potassium": {"value": potassium, "unit": "mmol/L"},
            }
        })
    print("  Seeded: outlier patient (K+=14.0 on day 0 — PROBABLE LAB ERROR expected)")


# ─────────────────────────────────────────────────────────
# Main async runner
# ─────────────────────────────────────────────────────────

async def run_test(scenario: str):
    print(f"\n{'='*60}")
    print(f"  HC01 Pipeline Test — {scenario.upper()} SCENARIO")
    print(f"{'='*60}\n")

    # Step 1: create patient
    print("Step 1: Creating test patient in Supabase...")
    patient = create_patient(
        name=f"Test Patient ({scenario})",
        subject_id=f"TEST_{scenario.upper()}_001"
    )
    patient_id = patient["patient_id"]
    print(f"  patient_id = {patient_id}")

    # Step 2: seed data
    print("Step 2: Seeding test data into Supabase...")
    if scenario == "stable":
        build_stable_data(patient_id)
    elif scenario == "sepsis":
        build_sepsis_data(patient_id)
    elif scenario == "outlier":
        build_outlier_data(patient_id)

    # Step 3: run pipeline directly (no HTTP)
    print("Step 3: Running agent pipeline (this takes 30-90s)...")
    print("  note_parser + lab_mapper -> rag_agent -> chief_agent (Gemini)...\n")
    report = await run_pipeline(patient_id)

    # Step 4: print results
    print(f"\n{'─'*60}")
    print("RESULTS")
    print(f"{'─'*60}")
    print(f"  diagnosis_updated : {report.get('diagnosis_updated')}")
    print(f"  risk_flags        : {len(report.get('risk_flags', []))} flag(s)")
    print(f"  outlier_alerts    : {len(report.get('outlier_alerts', []))} alert(s)")

    for flag in report.get("risk_flags", []):
        print(f"\n  [RISK] {flag.get('risk')} — Severity: {flag.get('severity')}")
        for ev in (flag.get("evidence") or [])[:3]:
            print(f"    . {ev}")
        for cite in (flag.get("guideline_citations") or [])[:1]:
            print(f"    Guideline: [{cite.get('source')}] \"{cite.get('text','')[:100]}\"")

    for alert in report.get("outlier_alerts", []):
        print(f"\n  [OUTLIER] {alert.get('parameter')}: {alert.get('reported_value')}")
        print(f"    Expected : {alert.get('expected_range')}")
        print(f"    Flag     : {alert.get('flag')}")
        print(f"    Action   : {alert.get('action_required')}")

    print(f"\n  Reasoning: {str(report.get('reasoning', ''))[:400]}")

    # Step 5: assertions
    print(f"\n{'─'*60}")
    print("ASSERTIONS")
    print(f"{'─'*60}")

    if scenario == "stable":
        no_high = all(
            f.get("severity") not in ("HIGH", "CRITICAL")
            for f in report.get("risk_flags", [])
        )
        print(f"  {'PASS' if no_high else 'FAIL'} — No HIGH/CRITICAL flags for stable patient")

    elif scenario == "sepsis":
        has_high = any(
            f.get("severity") in ("HIGH", "CRITICAL")
            for f in report.get("risk_flags", [])
        )
        print(f"  {'PASS' if has_high else 'FAIL'} — At least one HIGH/CRITICAL flag detected")

    elif scenario == "outlier":
        not_updated = report.get("diagnosis_updated") is False
        has_alert   = len(report.get("outlier_alerts", [])) > 0
        print(f"  {'PASS' if not_updated else 'FAIL'} — diagnosis_updated is False")
        print(f"  {'PASS' if has_alert else 'FAIL'} — outlier_alerts present")
        for a in report.get("outlier_alerts", []):
            if a.get("parameter") == "Potassium":
                print(f"  PASS — Potassium flagged as: {a.get('flag')}")
                break

    print()


if __name__ == "__main__":
    scenario = (
        "outlier" if "--outlier" in sys.argv else
        "sepsis"  if "--sepsis"  in sys.argv else
        "stable"
    )
    asyncio.run(run_test(scenario))
