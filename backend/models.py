"""Pydantic v2 schemas for the RydeResolve multi-agent dispute resolution system.

The domain models mirror the ``DISP-002`` No-Show Charge dataset shipped with the
Ryde problem statement (``dispute_ticket``, ``rider_profile``, ``driver_profile``,
``trip_data``, ``gps_telemetry``, ``chat_logs``, ``app_events``,
``cancellation_policy``) and extend it with:

* ``media_attachments``  — optional payload consumed by the Image Analysis Agent
                           (multi-modal stretch goal).
* Optional trip fields   — fare / route fields needed by the Route Deviation and
                           Property Damage dispute categories.

The wire models at the bottom (``AgentEvent``, ``Fact``, ``EvidencePacket``,
``AdvocateArgument``, ``Ruling``, ``ResolutionResult``) describe the observable
inter-agent contract streamed to the frontend over SSE.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class _Domain(BaseModel):
    """Base for ingested domain data.

    ``extra="allow"`` keeps ingestion forgiving: different dispute categories
    carry different auxiliary fields and we do not want a single unknown key to
    reject an otherwise perfectly valid ticket.
    """

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class _Strict(BaseModel):
    """Base for internally produced API payloads (no silent extras)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DisputeType(str, Enum):
    """Supported dispute categories (Ryde problem statement)."""

    NO_SHOW_CHARGE = "no_show_charge"
    ROUTE_DEVIATION = "route_deviation"
    PROPERTY_DAMAGE = "property_damage"
    SAFETY_INCIDENT = "safety_incident"
    FARE_DISPUTE = "fare_dispute"


class Party(str, Enum):
    RIDER = "rider"
    DRIVER = "driver"
    SYSTEM = "system"
    NEUTRAL = "neutral"


class DisputeStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class AgentRole(str, Enum):
    """Agents participating in the arbitration pipeline."""

    ORCHESTRATOR = "orchestrator"
    EVIDENCE = "evidence"
    VISION = "vision"
    RIDER_ADVOCATE = "rider_advocate"
    DRIVER_ADVOCATE = "driver_advocate"
    JUDGE = "judge"
    ESCALATION = "escalation"


class Decision(str, Enum):
    """Final ruling outcomes available to the Judge Agent."""

    REFUND_RIDER = "refund_rider"
    PARTIAL_REFUND = "partial_refund"
    UPHOLD_CHARGE = "uphold_charge"
    COMPENSATE_DRIVER = "compensate_driver"
    NO_ACTION = "no_action"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class EventLevel(str, Enum):
    INFO = "info"
    EVIDENCE = "evidence"
    ARGUMENT = "argument"
    RULING = "ruling"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Domain: dispute intake
# ---------------------------------------------------------------------------


class DisputeTicket(_Domain):
    dispute_id: str
    trip_id: str
    filed_by: Literal["rider", "driver"]
    dispute_type: DisputeType
    description: str
    filed_at: datetime
    status: DisputeStatus = DisputeStatus.OPEN


class DisputeHistory(_Domain):
    """Dispute history block.

    The rider block uses ``upheld``; the driver block uses ``upheld_against``.
    Both are optional so a single model can validate either shape.
    """

    total_disputes: int = 0
    upheld: Optional[int] = None
    upheld_against: Optional[int] = None
    rejected: int = 0

    @property
    def upheld_count(self) -> int:
        return (self.upheld or 0) + (self.upheld_against or 0)

    @property
    def success_rate(self) -> float:
        if self.total_disputes == 0:
            return 0.0
        return round(self.upheld_count / self.total_disputes, 3)


class RiderProfile(_Domain):
    rider_id: str
    name: str
    account_age_days: int = 0
    total_trips: int = 0
    avg_rating: float = Field(default=5.0, ge=0, le=5)
    dispute_history: DisputeHistory = Field(default_factory=DisputeHistory)
    fraud_flags: int = 0
    fraud_flag_details: Optional[str] = None
    payment_method: Optional[str] = None


class DriverProfile(_Domain):
    driver_id: str
    name: str
    account_age_days: int = 0
    total_trips: int = 0
    avg_rating: float = Field(default=5.0, ge=0, le=5)
    dispute_history: DisputeHistory = Field(default_factory=DisputeHistory)
    fraud_flags: int = 0
    vehicle: Optional[str] = None


class GeoPoint(_Domain):
    name: Optional[str] = None
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class FareLineItem(_Domain):
    label: str
    amount: float


class TripData(_Domain):
    trip_id: str
    rider_id: Optional[str] = None
    driver_id: Optional[str] = None

    pickup_location: Optional[GeoPoint] = None
    dropoff_location: Optional[GeoPoint] = None

    # --- timing -------------------------------------------------------------
    scheduled_time: Optional[datetime] = None
    driver_arrival_time: Optional[datetime] = None
    driver_wait_start: Optional[datetime] = None
    cancellation_time: Optional[datetime] = None
    trip_start_time: Optional[datetime] = None
    trip_end_time: Optional[datetime] = None

    # --- cancellation / no-show ---------------------------------------------
    cancellation_fee: Optional[float] = None
    cancellation_reason: Optional[str] = None

    # --- route deviation / fare ---------------------------------------------
    estimated_distance_km: Optional[float] = None
    actual_distance_km: Optional[float] = None
    estimated_duration_min: Optional[float] = None
    actual_duration_min: Optional[float] = None
    fare_estimate: Optional[float] = None
    fare_charged: Optional[float] = None
    fare_breakdown: list[FareLineItem] = Field(default_factory=list)
    surge_multiplier: float = 1.0

    # --- property damage ------------------------------------------------------
    cleaning_fee_claimed: Optional[float] = None


class GpsPoint(_Domain):
    timestamp: datetime
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    speed_kmh: float = 0.0
    status: str = "en_route"


class ChatMessage(_Domain):
    timestamp: datetime
    sender: Literal["rider", "driver", "system"]
    type: str = "message"
    content: str


class AppEvent(_Domain):
    timestamp: datetime
    event_type: str
    details: Optional[str] = None


class CancellationPolicy(_Domain):
    free_wait_time_min: float = 5
    cancellation_fee_after_wait: float = 5.00
    no_show_threshold_min: float = 8
    fee_goes_to: str = "driver_compensation"


class MediaAttachment(_Domain):
    """Vision pipeline payload (Image Analysis Agent — stretch goal)."""

    attachment_id: str = Field(default_factory=lambda: _new_id("media"))
    media_type: Literal["image", "video"] = "image"
    url: str
    uploaded_by: Literal["rider", "driver"] = "driver"
    # EXIF / provenance signals used for forensic checks
    captured_at: Optional[datetime] = None
    device_model: Optional[str] = None
    gps_lat: Optional[float] = None
    gps_lng: Optional[float] = None
    exif_present: bool = True
    ai_generated_probability: Optional[float] = Field(default=None, ge=0, le=1)
    caption: Optional[str] = None


class DisputeCase(_Domain):
    """Root model — a complete, self-contained dispute dossier."""

    dispute_ticket: DisputeTicket
    rider_profile: Optional[RiderProfile] = None
    driver_profile: Optional[DriverProfile] = None
    trip_data: TripData
    gps_telemetry: list[GpsPoint] = Field(default_factory=list)
    chat_logs: list[ChatMessage] = Field(default_factory=list)
    app_events: list[AppEvent] = Field(default_factory=list)
    cancellation_policy: Optional[CancellationPolicy] = None
    media_attachments: list[MediaAttachment] = Field(default_factory=list)

    @property
    def dispute_id(self) -> str:
        return self.dispute_ticket.dispute_id

    @property
    def dispute_type(self) -> DisputeType:
        return self.dispute_ticket.dispute_type


# ---------------------------------------------------------------------------
# Evidence layer (deterministic, auditable)
# ---------------------------------------------------------------------------


class Fact(_Strict):
    """A single verified, machine-derived fact about the dispute."""

    key: str
    label: str
    value: Any
    unit: Optional[str] = None
    source: str = "telemetry"
    supports: Literal["rider", "driver", "neutral"] = "neutral"
    note: Optional[str] = None


class PolicyCheck(_Strict):
    """A policy clause evaluated against observed behaviour."""

    ref: str
    description: str
    expected: str
    actual: str
    compliant: bool
    supports: Literal["rider", "driver", "neutral"] = "neutral"


class RiskSignal(_Strict):
    """Behavioural / fraud risk signal (Fraud & Bad-Faith stretch goal)."""

    party: Literal["rider", "driver"]
    signal: str
    severity: Literal["low", "medium", "high"] = "low"
    detail: str


class EvidencePacket(_Strict):
    """Everything the advocates and the judge are allowed to argue over."""

    dispute_id: str
    dispute_type: DisputeType
    facts: list[Fact] = Field(default_factory=list)
    policy_checks: list[PolicyCheck] = Field(default_factory=list)
    risk_signals: list[RiskSignal] = Field(default_factory=list)
    summary: str = ""

    def facts_for(self, party: Literal["rider", "driver"]) -> list[Fact]:
        return [f for f in self.facts if f.supports == party]


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------


class VisionFinding(_Strict):
    """Output of the Image Analysis Agent."""

    attachment_id: str
    genuine: bool
    authenticity_confidence: float = Field(default=0.0, ge=0, le=1)
    ai_generated_probability: Optional[float] = None
    exif_timestamp_delta_min: Optional[float] = None
    severity: Literal["none", "normal_wear", "minor_mess", "liquid_spill", "major_damage"] = "none"
    anomalies: list[str] = Field(default_factory=list)
    reasoning: str = ""


class AdvocateArgument(_Strict):
    """Structured argument produced by an advocate agent."""

    agent: Literal["rider_advocate", "driver_advocate"]
    headline: str
    claim: str
    cited_facts: list[str] = Field(default_factory=list)
    policy_refs: list[str] = Field(default_factory=list)
    requested_outcome: str
    confidence: float = Field(default=0.0, ge=0, le=1)
    weaknesses: list[str] = Field(default_factory=list)


class Ruling(_Strict):
    """Final, structured ruling issued by the Judge Agent."""

    dispute_id: str
    decision: Decision
    amount: float = 0.0
    confidence: float = Field(default=0.0, ge=0, le=1)
    reasoning: str = ""
    key_findings: list[str] = Field(default_factory=list)
    policy_applied: list[str] = Field(default_factory=list)
    rider_summary: str = ""
    driver_summary: str = ""
    escalated: bool = False
    escalation_reason: Optional[str] = None


class AgentEvent(_Strict):
    """Observable inter-agent message streamed to the frontend over SSE."""

    run_id: str
    seq: int
    ts: datetime = Field(default_factory=_utcnow)
    agent: AgentRole
    stage: str
    message: str
    level: EventLevel = EventLevel.INFO
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[int] = None


class ResolutionResult(_Strict):
    """Complete outcome of one orchestrator run."""

    run_id: str
    dispute_id: str
    dispute_type: DisputeType
    status: DisputeStatus
    engine: Literal["adp", "offline"] = "offline"
    evidence: Optional[EvidencePacket] = None
    vision: list[VisionFinding] = Field(default_factory=list)
    rider_argument: Optional[AdvocateArgument] = None
    driver_argument: Optional[AdvocateArgument] = None
    ruling: Optional[Ruling] = None
    started_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    errors: list[str] = Field(default_factory=list)


class DisputeRequest(_Strict):
    """POST /dispute body.

    Accepts either a full dossier (``case``) or a reference to a built-in sample
    (``case_id``). Exactly one must be supplied.
    """

    case: Optional[DisputeCase] = None
    case_id: Optional[str] = None

    @model_validator(mode="after")
    def _require_one_source(self) -> "DisputeRequest":
        if self.case is None and not self.case_id:
            raise ValueError("provide either 'case' (full dossier) or 'case_id' (built-in sample)")
        return self


class DisputeAccepted(_Strict):
    """POST /dispute response."""

    run_id: str
    dispute_id: str
    dispute_type: DisputeType
    stream_url: str
    result_url: str
    engine: Literal["adp", "offline"]


class CaseSummary(_Strict):
    """Lightweight descriptor for the built-in sample dataset."""

    case_id: str
    dispute_id: str
    dispute_type: DisputeType
    title: str
    blurb: str
    expected_ruling: str
    filed_by: str
    multimodal: bool
