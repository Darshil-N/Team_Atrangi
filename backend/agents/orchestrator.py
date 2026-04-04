"""
agents/orchestrator.py  Pipeline coordinator for all four agents.

Execution order:
  1. Build unified patient state from parsed_data (state_builder)
  2. Run agents 13 IN PARALLEL (note_parser, lab_mapper, rag_agent)
      asyncio.gather cuts total latency by ~3x vs sequential
  3. Run agent 4 (chief_agent)  waits for 13 to finish
  4. Save the final report to Supabase

Usage (called from FastAPI background task):
    from agents.orchestrator import run_pipeline
    report = await run_pipeline(patient_id="550e8400-...")

Usage (standalone test from backend/ directory):
    python -m agents.orchestrator <patient_id>
"""
from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Dict, Optional

from processing.state_builder import build_state, state_is_empty, summarise_state
from agents import note_parser, lab_mapper, rag_agent, chief_agent
from database.supabase_client import get_current_report, save_report

logger = logging.getLogger(__name__)

_active_runs: set[str] = set()
_pending_runs: set[str] = set()
_run_state_lock = asyncio.Lock()



async def run_pipeline(patient_id: str) -> Dict[str, Any]:
    """
    Run the full multi-agent diagnostic pipeline for a single patient.

    Args:
        patient_id: UUID of the patient to analyse.

    Returns:
        The final report dict (ChiefAgentOutput), also saved to Supabase.

    Raises:
        ValueError: if patient_id is empty or no data exists for the patient.
    """
    if not patient_id:
        raise ValueError("patient_id must not be empty.")

    logger.info("orchestrator:  PIPELINE START  patient=%s ", patient_id)

    logger.info("orchestrator: [1/4] Building patient state...")
    state = build_state(patient_id)

    if state_is_empty(state):
        raise ValueError(
            f"No parsed data found for patient {patient_id}. "
            "Upload and process clinical files first."
        )

    logger.info("orchestrator: State ready  %s", summarise_state(state))

    logger.info("orchestrator: [2/4] Fetching previous report...")
    prev_report: Optional[Dict[str, Any]] = None
    try:
        prev_report = get_current_report(patient_id)
        if prev_report:
            logger.info(
                "orchestrator: Previous report found  v%d",
                prev_report.get("report_version", "?"),
            )
        else:
            logger.info("orchestrator: No previous report  this is first assessment.")
    except Exception as exc:
        logger.warning("orchestrator: Could not fetch previous report: %s", exc)

    logger.info(
        "orchestrator: [3/4] Running note_parser, lab_mapper, rag_agent in parallel..."
    )

    symptoms_output, lab_output = await asyncio.gather(
        note_parser.run(state),
        lab_mapper.run(state),
    )

    rag_output = await rag_agent.run(state, symptoms_output, lab_output)

    logger.info(
        "orchestrator: Agent outputs  "
        "symptoms=%d, trends=%d, outliers=%d, guidelines=%d",
        len(symptoms_output.get("symptoms", [])),
        len(lab_output.get("trends", {})),
        len(lab_output.get("outliers", [])),
        len(rag_output.get("guidelines", [])),
    )

    logger.info("orchestrator: [4/4] Running chief synthesis agent (Gemini)...")
    report = await chief_agent.run(
        state,
        symptoms_output,
        lab_output,
        rag_output,
        prev_report,
    )

    logger.info("orchestrator: Saving report to Supabase...")
    try:
        saved = save_report(
            patient_id        = patient_id,
            timeline          = report.get("timeline", []),
            risk_flags        = report.get("risk_flags", []),
            outlier_alerts    = report.get("outlier_alerts", []),
            diagnosis_updated = report.get("diagnosis_updated", False),
            reasoning         = report.get("reasoning", ""),
            family_communication = report.get("family_communication", {}),
        )
        report["_saved_report_id"] = saved.get("id")
        logger.info(
            "orchestrator: Report saved  id=%s, version=%s",
            saved.get("id"), saved.get("report_version"),
        )
    except Exception as exc:
        logger.error(
            "orchestrator: Failed to save report to Supabase: %s. "
            "Report data is returned in memory but NOT persisted.", exc
        )
        report["_save_error"] = str(exc)

    logger.info("orchestrator:  PIPELINE COMPLETE  patient=%s ", patient_id)
    return report


async def run_pipeline_queued(patient_id: str, reason: str = "manual") -> Dict[str, Any]:
    """
    Queue-safe runner for one patient.

    Behaviour:
      - If no run is active: starts immediately.
      - If a run is already active for the same patient: marks a pending rerun and exits.
      - Active runner loops once more when pending flag is set, ensuring latest uploads are analyzed.
    """
    if not patient_id:
        raise ValueError("patient_id must not be empty.")

    async with _run_state_lock:
        if patient_id in _active_runs:
            _pending_runs.add(patient_id)
            logger.info(
                "orchestrator: queued rerun  patient=%s, reason=%s",
                patient_id,
                reason,
            )
            return {
                "_status": "queued",
                "_saved_report_id": None,
                "reasoning": "Analysis rerun queued while current run is in progress.",
            }
        _active_runs.add(patient_id)

    try:
        while True:
            async with _run_state_lock:
                _pending_runs.discard(patient_id)

            result = await run_pipeline(patient_id)

            async with _run_state_lock:
                should_rerun = patient_id in _pending_runs

            if not should_rerun:
                return result

            logger.info("orchestrator: executing queued rerun  patient=%s", patient_id)
    finally:
        async with _run_state_lock:
            _active_runs.discard(patient_id)



async def _main(patient_id: str) -> None:
    """Run the pipeline and pretty-print the result."""
    import json
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        report = await run_pipeline(patient_id)
        print("\n" + "" * 60)
        print("FINAL REPORT")
        print("" * 60)
        print(json.dumps(report, indent=2, default=str))
    except Exception as exc:
        print(f"\n Pipeline failed: {exc}")
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m agents.orchestrator <patient_id>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
