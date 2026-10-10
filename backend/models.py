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


class SLAPriority(str, Enum):
    """Triage band assigned by the SLA & Routing Manager.

    Drives queue ordering and the resolution deadline. ``CRITICAL`` is reserved
    for safety incidents, which are fast-tracked and always human-reviewed.
    """

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class RoutingStatus(str, Enum):
    """Where the ticket sits in the routing lifecycle."""

    QUEUED = "queued"
    FAST_TRACKED = "fast_tracked"
    IN_ARBITRATION = "in_arbitration"
    AUTO_RESOLVED = "auto_resolved"
    ESCALATED_TO_HUMAN = "escalated_to_human"
    OVERRIDDEN = "overridden"


class AgentRole(str, Enum):
    """Agents participating in the arbitration pipeline."""

    ORCHESTRATOR = "orchestrator"
    SLA_ROUTER = "sla_router"
    EVIDENCE_COLLECTION = "evidence_collection"
    EVIDENCE = "evidence"
    FRAUD = "fraud"
    POLICY = "policy"
    ASR = "asr"
    VISION = "vision"
    RIDER_ADVOCATE = "rider_advocate"
    DRIVER_ADVOCATE = "driver_advocate"
    JUDGE = "judge"
    ESCALATION = "escalation"
    LEARNING = "learning"


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


class AudioSegment(_Strict):
    """One speaker turn returned by the TRTC ASR pipeline."""

    speaker: Literal["rider", "driver", "unknown"] = "unknown"
    start_s: float = Field(default=0.0, ge=0)
    end_s: float = Field(default=0.0, ge=0)
    text: str = ""
    hostility: float = Field(default=0.0, ge=0, le=1)


class AudioTranscript(_Strict):
    """Structured output of `trtc_client.py` for one audio attachment."""

    attachment_id: str
    #: Web path of the source clip, so the UI can play it back next to the text.
    source_url: Optional[str] = None
    engine: Literal["trtc", "simulated"] = "simulated"
    language: str = "en-SG"
    duration_s: float = Field(default=0.0, ge=0)
    confidence: float = Field(default=0.0, ge=0, le=1)
    segments: list[AudioSegment] = Field(default_factory=list)
    full_text: str = ""
    hostility_score: float = Field(default=0.0, ge=0, le=1)
    threat_detected: bool = False
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""


class VideoFrame(_Strict):
    """A keyframe extracted from an ingested video clip."""

    index: int
    timestamp_s: float = Field(default=0.0, ge=0)
    path: str
    width: Optional[int] = None
    height: Optional[int] = None
    mean_luminance: Optional[float] = None
    motion_score: Optional[float] = None
    label: Optional[str] = None


class VideoAnalysis(_Strict):
    """Structured output of `vision_utils.py` + the vision model for a video."""

    attachment_id: str
    #: Web path of the source clip, so the UI can play it back next to the frames.
    source_url: Optional[str] = None
    duration_s: float = Field(default=0.0, ge=0)
    fps: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frames_extracted: int = 0
    frames: list[VideoFrame] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    severity: Literal["none", "normal_wear", "minor_mess", "liquid_spill", "major_damage"] = (
        "none"
    )
    reasoning: str = ""
    engine: Literal["ffmpeg", "opencv", "unavailable"] = "ffmpeg"


class MediaAttachment(_Domain):
    """Vision / audio pipeline payload (Image Analysis Agent — stretch goal)."""

    attachment_id: str = Field(default_factory=lambda: _new_id("media"))
    media_type: Literal["image", "video", "audio"] = "image"
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

    # --- Phase 3: multi-modal ingestion ------------------------------------
    duration_s: Optional[float] = Field(
        default=None, description="Runtime of an audio/video payload in seconds"
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Filesystem path of an uploaded payload (relative to the media dir)",
    )
    asset_key: Optional[str] = Field(
        default=None, description="Key into the Miora mock-asset manifest served by the UI"
    )
    transcript: Optional[AudioTranscript] = Field(
        default=None, description="Populated by the TRTC ASR pipeline for audio payloads"
    )
    video: Optional[VideoAnalysis] = Field(
        default=None, description="Populated by the video ingestion pipeline"
    )


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

    # --- SLA & Routing Manager (pre-processing layer) ----------------------
    sla_priority: Optional[SLAPriority] = Field(
        default=None,
        description="Set by the caller to override triage; otherwise derived from dispute type",
    )
    routing_status: RoutingStatus = Field(
        default=RoutingStatus.QUEUED,
        description="Lifecycle position assigned by the SLA & Routing Manager",
    )
    sla_due_at: Optional[datetime] = Field(
        default=None, description="Resolution deadline derived from the priority band"
    )

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
# Pre-processing layer: SLA routing, evidence ingestion, risk & precedent
# ---------------------------------------------------------------------------


class SLARoutingDecision(_Strict):
    """Triage verdict from the SLA & Routing Manager (pre-processing layer)."""

    dispute_id: str
    priority: SLAPriority
    routing_status: RoutingStatus
    fast_tracked: bool
    queue: str
    queue_position: int
    sla_target_minutes: float
    sla_due_at: datetime
    reasons: list[str] = Field(default_factory=list)


class CollectionRecord(_Strict):
    """One upstream source fetched by the Evidence Collection Agent."""

    source: str
    endpoint: str
    records: int = 0
    latency_ms: int = 0
    status: Literal["ok", "degraded", "empty", "failed"] = "ok"
    note: Optional[str] = None


class CollectionManifest(_Strict):
    """Aggregated ingestion report from the Evidence Collection Agent."""

    dispute_id: str
    sources: list[CollectionRecord] = Field(default_factory=list)
    total_records: int = 0
    total_latency_ms: int = 0
    degraded: bool = False
    summary: str = ""

    @property
    def ok(self) -> bool:
        return not self.degraded


class FraudAssessment(_Strict):
    """Structured verdict from the Fraud & Bad-Faith Detection Agent."""

    dispute_id: str
    risk_score: float = Field(default=0.0, ge=0, le=1)
    verdict: Literal["none", "low", "suspected", "likely", "confirmed"] = "none"
    rider_risk: float = Field(default=0.0, ge=0, le=1)
    driver_risk: float = Field(default=0.0, ge=0, le=1)
    signals: list[RiskSignal] = Field(default_factory=list)
    recommended_action: str = ""
    policy_refs: list[str] = Field(default_factory=list)
    reasoning: str = ""


class PrecedentCase(_Strict):
    """A historical ruling held in the mock RAG knowledge base."""

    precedent_id: str = Field(default_factory=lambda: _new_id("prec"))
    dispute_type: DisputeType
    title: str
    fact_signature: dict[str, Any] = Field(default_factory=dict)
    summary: str
    ruling: str
    amount: float = 0.0
    source: Literal["seed", "human_override"] = "seed"
    created_at: datetime = Field(default_factory=_utcnow)
    learned_from_run_id: Optional[str] = None
    reviewer_note: Optional[str] = None


class PrecedentMatch(_Strict):
    """A retrieved precedent plus why it matched and what it suggests."""

    precedent: PrecedentCase
    similarity: float = Field(default=0.0, ge=0, le=1)
    matched_on: list[str] = Field(default_factory=list)
    recommendation: str = ""


class PrecedentBundle(_Strict):
    """Retrieval result handed to the Judge for consistency enforcement."""

    dispute_id: str
    matches: list[PrecedentMatch] = Field(default_factory=list)
    retrieved_count: int = 0
    consistency_note: str = ""


class EscalationPacket(_Strict):
    """Everything a human reviewer needs, assembled post-ruling."""

    run_id: str
    dispute_id: str
    priority: SLAPriority
    queue: str
    sla_due_at: Optional[datetime] = None
    routed_to: str = "human_review_queue"
    case_summary: str = ""
    evidence_digest: list[str] = Field(default_factory=list)
    conflicting_points: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    judge_recommendation: str = ""
    recommended_focus: list[str] = Field(default_factory=list)


class OverrideRequest(_Strict):
    """Human reviewer correction to an escalated ruling."""

    reviewer_id: str
    decision: Decision
    amount: float = Field(default=0.0, ge=0)
    rationale: str = Field(min_length=1)
    add_to_knowledge_base: bool = True
    tags: list[str] = Field(default_factory=list)


class OverrideAccepted(_Strict):
    """Response to an override — confirms the knowledge base absorbed it."""

    run_id: str
    dispute_id: str
    status: Literal["overridden"] = "overridden"
    previous_decision: Optional[str] = None
    new_decision: Decision
    new_amount: float = 0.0
    precedent_id: Optional[str] = None
    knowledge_base_size: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------


class VisionFinding(_Strict):
    """Output of the Image Analysis Agent (images, videos and audio transcripts)."""

    attachment_id: str
    genuine: bool
    authenticity_confidence: float = Field(default=0.0, ge=0, le=1)
    ai_generated_probability: Optional[float] = None
    exif_timestamp_delta_min: Optional[float] = None
    severity: Literal["none", "normal_wear", "minor_mess", "liquid_spill", "major_damage"] = "none"
    anomalies: list[str] = Field(default_factory=list)
    reasoning: str = ""

    # --- Phase 3: multi-modal ----------------------------------------------
    media_kind: Literal["image", "video", "audio"] = "image"
    video: Optional[VideoAnalysis] = None
    transcript: Optional[AudioTranscript] = None


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
    routing: Optional[SLARoutingDecision] = None
    collection: Optional[CollectionManifest] = None
    evidence: Optional[EvidencePacket] = None
    fraud: Optional[FraudAssessment] = None
    precedents: Optional[PrecedentBundle] = None
    vision: list[VisionFinding] = Field(default_factory=list)
    rider_argument: Optional[AdvocateArgument] = None
    driver_argument: Optional[AdvocateArgument] = None
    ruling: Optional[Ruling] = None
    escalation: Optional[EscalationPacket] = None
    override: Optional[OverrideAccepted] = None
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
    # SLA triage assigned the moment the ticket was accepted.
    sla_priority: Optional[SLAPriority] = None
    fast_tracked: bool = False
    queue: Optional[str] = None
    sla_due_at: Optional[datetime] = None


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
    #: Miora-generated mock evidence rendered by the UI (Phase 3)
    evidence_assets: list[str] = Field(default_factory=list)
