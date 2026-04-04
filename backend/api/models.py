"""
api/models.py  Pydantic schemas shared across all API routes.

These are the request/response models for FastAPI endpoints.
Agent output types are in agents/  these are only HTTP-level contracts.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field



class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="Patient full name")
    subject_id: Optional[str] = Field(None, description="MIMIC-III subject_id (optional)")


class PatientResponse(BaseModel):
    patient_id: UUID
    name: str
    subject_id: Optional[str]
    admission_timestamp: datetime
    nfc_url: Optional[str]
    created_at: datetime



class UploadStatus(BaseModel):
    """Represents the processing status of one uploaded file."""
    filename: str
    data_type: str                        # 'note' | 'lab' | 'vital'
    status: str                           # 'uploaded' | 'processing' | 'parsed' | 'error'
    file_url: Optional[str] = None
    error_message: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class UploadResponse(BaseModel):
    patient_id: UUID
    uploads: List[UploadStatus]
    message: str



class TimelineEvent(BaseModel):
    date: str
    event: str
    status: str                           # 'baseline' | 'stable' | 'deteriorating'
    vitals: Optional[Dict[str, Any]] = None
    labs: Optional[Dict[str, Any]] = None
    symptoms: Optional[List[str]] = None


class GuidelineCitation(BaseModel):
    source: str
    text: str
    confidence: float


class RiskFlag(BaseModel):
    risk: str
    severity: str                         # 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
    evidence: List[str]
    guideline_citations: List[GuidelineCitation]
    recommended_action: str


class OutlierAlert(BaseModel):
    parameter: str
    reported_value: float
    expected_range: str
    statistical_deviation: str
    flag: str                             # 'PROBABLE LAB ERROR' | 'VERIFY'
    action_required: str
    diagnosis_updated: bool = False


class ReportResponse(BaseModel):
    id: int
    patient_id: UUID
    report_version: int
    timeline: List[TimelineEvent]
    risk_flags: List[RiskFlag]
    outlier_alerts: List[OutlierAlert]
    diagnosis_updated: bool
    reasoning: str
    generated_at: datetime
    is_current: bool



class AnalysisRequest(BaseModel):
    patient_id: UUID = Field(..., description="UUID of the patient to analyse")


class AnalysisStatus(BaseModel):
    patient_id: UUID
    status: str                           # 'queued' | 'running' | 'completed' | 'failed'
    message: str
    report_id: Optional[int] = None



class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None
