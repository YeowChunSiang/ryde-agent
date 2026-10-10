"""Deterministic async state pipeline for multi-agent dispute arbitration.

The pipeline is deliberately *not* an autonomous agent graph — it is an explicit
state machine, which is what a legal-style arbitration process actually needs:

    1. TRIAGE       SLA & Routing Manager tags and fast-tracks the ticket
    2. COLLECTION   Evidence Collection Agent fans out over upstream services
                    (runs concurrently with the fraud and precedent agents)
    3. EVIDENCE     compute auditable facts in pure Python (no LLM)
    4. RISK         Fraud & Bad-Faith Agent scores both parties
    5. PRECEDENT    Policy & Precedent Agent retrieves analogous past rulings
    6. VISION       (conditional) forensic screen of submitted media
    7. ADVOCACY     Rider + Driver advocates run concurrently via asyncio.gather
    8. ARBITRATION  Judge weighs both cases against policy, risk and precedent
    9. ESCALATION   confidence gate -> human-in-the-loop hand-off packet

Every state transition is emitted as an ``AgentEvent`` so the frontend can stream
the agents "thinking" in real time over SSE — the observability requirement from
the Ryde problem statement ("inter-agent communication should be observable").
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Optional

from adp_client import (
    ADPClient,
    LLMError,
    LLMProvider,
    OfflineReasoner,
    build_provider,
)
from agents import (
    EvidenceCollectionAgent,
    FraudDetectionAgent,
    PolicyPrecedentAgent,
    SLARoutingManager,
    build_escalation_packet,
)
from trtc_client import SimulatedASRClient, build_asr_provider
from vision_utils import VideoProcessingError, analyse_video
from config import Settings
from evidence import extract_evidence
from media_store import MediaStore, resolve_media_path
from models import (
    AdvocateArgument,
    AgentEvent,
    AgentRole,
    Decision,
    DisputeCase,
    DisputeStatus,
    EventLevel,
    EvidencePacket,
    FraudAssessment,
    MediaAttachment,
    OverrideRequest,
    PrecedentBundle,
    ResolutionResult,
    RoutingStatus,
    Ruling,
    SLARoutingDecision,
    VisionFinding,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Run:
    """Mutable state for a single arbitration run."""

    def __init__(self, run_id: str, case: DisputeCase, engine: str) -> None:
        self.run_id = run_id
        self.case = case
        self.engine = engine
        #: Triage verdict, assigned before the run is queued so a fast-tracked
        #: ticket never sits behind standard ones.
        self.routing: Optional[SLARoutingDecision] = None
        self.events: list[AgentEvent] = []
        self.result = ResolutionResult(
            run_id=run_id,
            dispute_id=case.dispute_id,
            dispute_type=case.dispute_type,
            status=DisputeStatus.OPEN,
            engine=engine,  # type: ignore[arg-type]
        )
        self.done = False
        self._seq = 0
        self._lock = asyncio.Lock()

    async def emit(
        self,
        agent: AgentRole,
        stage: str,
        message: str,
        *,
        level: EventLevel = EventLevel.INFO,
        payload: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
    ) -> AgentEvent:
        async with self._lock:
            self._seq += 1
            event = AgentEvent(
                run_id=self.run_id,
                seq=self._seq,
                ts=_now(),
                agent=agent,
                stage=stage,
                message=message,
                level=level,
                payload=payload or {},
                duration_ms=duration_ms,
            )
            self.events.append(event)
            return event


class RunBroker:
    """In-memory registry of runs (single-process demo deployment)."""

    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}
        self.latest_run_id: Optional[str] = None

    def create(self, case: DisputeCase, engine: str) -> Run:
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        run = Run(run_id, case, engine)
        self.runs[run_id] = run
        self.latest_run_id = run_id
        return run

    def get(self, run_id: Optional[str] = None) -> Optional[Run]:
        if run_id is None:
            run_id = self.latest_run_id
        if run_id is None:
            return None
        return self.runs.get(run_id)


class Orchestrator:
    """Runs the arbitration pipeline and streams its state transitions."""

    def __init__(self, settings: Settings, broker: RunBroker) -> None:
        self.settings = settings
        self.broker = broker
        self.provider: LLMProvider = build_provider(settings)
        self.fallback: Optional[OfflineReasoner] = (
            OfflineReasoner(settings) if self.provider.engine == "adp" else None
        )

        # --- Phase 2 agents -------------------------------------------------
        self.sla = SLARoutingManager(settings)
        self.collector = EvidenceCollectionAgent(settings)
        self.fraud_agent = FraudDetectionAgent(settings)
        self.policy_agent = PolicyPrecedentAgent(settings)

        # --- Phase 3: multi-modal ingestion --------------------------------
        self.asr = build_asr_provider(settings)
        self.media_store = MediaStore(settings)
        self._backend_root = Path(__file__).resolve().parent

    @property
    def engine(self) -> str:
        return self.provider.engine

    @property
    def knowledge_base_size(self) -> int:
        return self.policy_agent.store.size

    def triage(self, case: DisputeCase) -> SLARoutingDecision:
        """Assign an SLA band at the API boundary, before the run is queued."""
        return self.sla.route(case)

    async def apply_override(
        self, run_id: str, request: OverrideRequest
    ) -> Optional[ResolutionResult]:
        """Absorb a human correction into the precedent knowledge base.

        This is the learning feedback loop: the reviewer's decision becomes a
        new precedent, so the next similar dispute is judged against it.
        """
        run = self.broker.get(run_id)
        if run is None:
            return None

        previous = run.result.ruling.decision.value if run.result.ruling else None
        precedent = self.policy_agent.learn_from_override(
            run.case,
            run.result.evidence,
            run.result.ruling,
            request,
            run_id,
        )

        from models import OverrideAccepted  # local import: avoids a cycle at import time

        run.result.override = OverrideAccepted(
            run_id=run_id,
            dispute_id=run.case.dispute_id,
            previous_decision=previous,
            new_decision=request.decision,
            new_amount=request.amount,
            precedent_id=precedent.precedent_id if precedent else None,
            knowledge_base_size=self.knowledge_base_size,
            message=(
                f"Override recorded. Added precedent "
                f"{precedent.precedent_id if precedent else '(none)'} to the knowledge base "
                f"({self.knowledge_base_size} precedents now)."
                if precedent
                else "Override recorded without adding a precedent."
            ),
        )

        if run.result.ruling is not None:
            run.result.ruling.decision = request.decision
            run.result.ruling.amount = request.amount
            run.result.ruling.escalated = False
            run.result.ruling.escalation_reason = None
            run.result.ruling.reasoning = (
                f"{run.result.ruling.reasoning}\n\n"
                f"HUMAN OVERRIDE by {request.reviewer_id}: {request.rationale.strip()}"
            ).strip()
        run.case.routing_status = RoutingStatus.OVERRIDDEN
        run.result.status = DisputeStatus.RESOLVED

        await run.emit(
            AgentRole.LEARNING,
            "override_applied",
            f"Learning loop: reviewer {request.reviewer_id} overrode this ruling to "
            f"{request.decision.value.replace('_', ' ')}"
            + (f" (S${request.amount:.2f})" if request.amount else "")
            + (
                f". Knowledge base now holds {self.knowledge_base_size} precedents."
                if precedent
                else "."
            ),
            level=EventLevel.RULING,
            payload=run.result.override.model_dump(mode="json"),
        )
        return run.result

    async def _pace(self) -> None:
        """Throttle offline runs so the SSE stream is watchable in a live demo.

        Only applied when the deterministic reasoner is driving — with real ADP
        inference, model latency already paces the stream and adding artificial
        delay would be dishonest.
        """
        if self.provider.engine == "offline" and self.settings.offline_demo_pacing_ms > 0:
            await asyncio.sleep(self.settings.offline_demo_pacing_ms / 1000.0)

    # ------------------------------------------------------------------
    # Public entrypoint
    # ------------------------------------------------------------------

    async def arbitrate(self, case: DisputeCase) -> Run:
        """Execute the full pipeline, emitting events as it goes."""
        run = self.broker.create(case, self.engine)
        started = time.perf_counter()
        try:
            await self._pipeline(run)
        except Exception as exc:  # never let a run die silently
            run.result.errors.append(f"{type(exc).__name__}: {exc}")
            await run.emit(
                AgentRole.ORCHESTRATOR,
                "pipeline_error",
                f"Pipeline failed: {type(exc).__name__}: {exc}",
                level=EventLevel.ERROR,
            )
        finally:
            run.result.finished_at = _now()
            run.result.duration_ms = int((time.perf_counter() - started) * 1000)
            run.done = True
        return run

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    async def _pipeline(self, run: Run) -> None:
        case = run.case
        t0 = time.perf_counter()

        # --- 1. INTAKE ----------------------------------------------------
        ticket = case.dispute_ticket
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "intake",
            f"Dispute {ticket.dispute_id} ingested — {ticket.dispute_type.value.replace('_', ' ')} "
            f"filed by the {ticket.filed_by}.",
            payload={
                "dispute_id": ticket.dispute_id,
                "trip_id": ticket.trip_id,
                "dispute_type": ticket.dispute_type.value,
                "filed_by": ticket.filed_by,
                "statement": ticket.description,
            },
        )
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "intake",
            f"Dossier validated: {len(case.gps_telemetry)} GPS pings, {len(case.chat_logs)} chat "
            f"messages, {len(case.app_events)} app events, {len(case.media_attachments)} media "
            f"attachment(s). Engine mode: {self.engine}.",
            payload={
                "gps_points": len(case.gps_telemetry),
                "chat_messages": len(case.chat_logs),
                "app_events": len(case.app_events),
                "media_attachments": len(case.media_attachments),
                "engine": self.engine,
            },
        )

        # --- 2. SLA & ROUTING ------------------------------------------------
        routing = run.routing or self.sla.route(case)
        run.routing = routing
        run.result.routing = routing
        run.case.routing_status = RoutingStatus.IN_ARBITRATION
        await run.emit(
            AgentRole.SLA_ROUTER,
            "sla_routing",
            f"SLA & Routing Manager — priority {routing.priority.value.upper()}"
            + (" [FAST-TRACKED]" if routing.fast_tracked else "")
            + f" → queue '{routing.queue}' position {routing.queue_position}, "
            f"resolve within {routing.sla_target_minutes:.0f} min.",
            level=EventLevel.WARNING if routing.fast_tracked else EventLevel.INFO,
            payload=routing.model_dump(mode="json"),
        )
        for reason in routing.reasons:
            await run.emit(AgentRole.SLA_ROUTER, "sla_reason", reason)
        await self._pace()

        # --- 2b. MULTI-MODAL INGESTION (audio ASR + video keyframes) --------
        await self._prepare_media(run)

        # --- 3. PARALLEL: collection | evidence | fraud | precedent ----------
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "parallel_dispatch",
            "Dispatching the Evidence Collection, Fraud & Bad-Faith and Policy & Precedent "
            "agents concurrently — upstream retrieval overlaps with risk scoring and "
            "precedent retrieval instead of queueing behind it.",
        )
        t_parallel = time.perf_counter()

        # Start the collector first: it awaits simulated upstream latency, and
        # every other agent gets to run during those awaits.
        collection_task = asyncio.create_task(self.collector.collect(case))

        # --- 3a. EVIDENCE EXTRACTION (pure Python, no LLM) -------------------
        t_stage = time.perf_counter()
        packet = extract_evidence(case)
        run.result.evidence = packet
        await run.emit(
            AgentRole.EVIDENCE,
            "evidence_extraction",
            packet.summary,
            level=EventLevel.EVIDENCE,
            duration_ms=int((time.perf_counter() - t_stage) * 1000),
            payload={"summary": packet.summary},
        )
        for fact in packet.facts[:8]:
            await run.emit(
                AgentRole.EVIDENCE,
                "evidence_fact",
                f"{fact.label}: {fact.value}{(' ' + fact.unit) if fact.unit else ''}"
                + (f" — {fact.note}" if fact.note else ""),
                level=EventLevel.EVIDENCE,
                payload={
                    "key": fact.key,
                    "supports": fact.supports,
                    "source": fact.source,
                    "value": fact.value,
                    "unit": fact.unit,
                },
            )
        for check in packet.policy_checks:
            await run.emit(
                AgentRole.EVIDENCE,
                "policy_check",
                f"[{check.ref}] {'PASS' if check.compliant else 'FAIL'} — {check.description} "
                f"(expected {check.expected}, observed {check.actual})",
                level=EventLevel.WARNING if not check.compliant else EventLevel.EVIDENCE,
                payload={
                    "ref": check.ref,
                    "compliant": check.compliant,
                    "supports": check.supports,
                },
            )
        for signal in packet.risk_signals:
            await run.emit(
                AgentRole.EVIDENCE,
                "risk_signal",
                f"Risk ({signal.party}/{signal.severity}): {signal.signal} — {signal.detail}",
                level=EventLevel.WARNING if signal.severity != "low" else EventLevel.INFO,
                payload={"party": signal.party, "severity": signal.severity},
            )

        # --- 3b/3c. FRAUD + PRECEDENT (concurrent with the collector) --------
        fraud_task = asyncio.create_task(self._fraud(run, case, packet))
        precedent_task = asyncio.create_task(self._precedent(run, case, packet))

        manifest = await collection_task
        run.result.collection = manifest
        await run.emit(
            AgentRole.EVIDENCE_COLLECTION,
            "collection_complete",
            manifest.summary,
            level=EventLevel.WARNING if manifest.degraded else EventLevel.INFO,
            duration_ms=manifest.total_latency_ms,
            payload=manifest.model_dump(mode="json"),
        )
        for record in manifest.sources:
            await run.emit(
                AgentRole.EVIDENCE_COLLECTION,
                "collection_source",
                f"{record.source} {record.endpoint} → {record.records} record(s) "
                f"in {record.latency_ms} ms [{record.status}]"
                + (f" — {record.note}" if record.note else ""),
                level=EventLevel.WARNING if record.status != "ok" else EventLevel.INFO,
                payload=record.model_dump(mode="json"),
            )

        fraud = await fraud_task
        precedents = await precedent_task
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "parallel_complete",
            f"Collection, fraud and precedent agents all returned in "
            f"{int((time.perf_counter() - t_parallel) * 1000)} ms of combined wall-clock "
            f"(fanned out, not serialised).",
        )
        await self._pace()

        # --- 6. VISION (conditional) ----------------------------------------
        vision: list[VisionFinding] = []
        if case.media_attachments:
            await run.emit(
                AgentRole.VISION,
                "vision_dispatch",
                f"Media payload detected — dispatching the Image Analysis Agent over "
                f"{len(case.media_attachments)} attachment(s).",
            )
            for attachment in case.media_attachments:
                t_vision = time.perf_counter()
                noun = {"image": "photo", "video": "clip", "audio": "recording"}.get(
                    attachment.media_type, "attachment"
                )
                await run.emit(
                    AgentRole.VISION,
                    "vision_analysis",
                    f"Image Analysis Agent is inspecting {attachment.attachment_id} ({noun}): "
                    "verifying authenticity and cross-referencing the capture timestamp "
                    "against the trip window...",
                )
                await self._pace()
                finding = await self._guarded(
                    run,
                    lambda p, a=attachment: p.run_vision(case, packet, a),
                    label="Image Analysis Agent",
                )
                vision.append(finding)
                run.result.vision = vision
                await run.emit(
                    AgentRole.VISION,
                    "vision_finding",
                    (
                        f"Image Analysis: {noun} is {'GENUINE' if finding.genuine else 'NOT ADMISSIBLE'} "
                        f"(severity '{finding.severity}', AI-probability "
                        f"{finding.ai_generated_probability}, EXIF delta "
                        f"{finding.exif_timestamp_delta_min} min)."
                    ),
                    level=EventLevel.WARNING if not finding.genuine else EventLevel.EVIDENCE,
                    duration_ms=int((time.perf_counter() - t_vision) * 1000),
                    payload=finding.model_dump(mode="json"),
                )
                for anomaly in finding.anomalies:
                    await run.emit(
                        AgentRole.VISION,
                        "vision_anomaly",
                        f"Metadata mismatch detected — {anomaly}",
                        level=EventLevel.WARNING,
                    )

        # --- 4. PARALLEL ADVOCACY --------------------------------------------
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "advocacy_dispatch",
            "Launching Rider Advocate and Driver Advocate concurrently (asyncio.gather).",
        )

        async def advocate(party: str) -> AdvocateArgument:
            t_adv = time.perf_counter()
            await run.emit(
                AgentRole.RIDER_ADVOCATE if party == "rider" else AgentRole.DRIVER_ADVOCATE,
                "advocacy_start",
                f"{party.title()} Advocate is analysing the GPS telemetry and chat logs...",
            )
            await self._pace()
            argument = await self._guarded(
                run,
                lambda p, party=party: p.run_advocate(case, packet, vision, party),
                label=f"{party.title()} Advocate",
            )
            await run.emit(
                AgentRole.RIDER_ADVOCATE if party == "rider" else AgentRole.DRIVER_ADVOCATE,
                "advocacy_complete",
                f"{party.title()} Advocate: {argument.headline}",
                level=EventLevel.ARGUMENT,
                duration_ms=int((time.perf_counter() - t_adv) * 1000),
                payload=argument.model_dump(mode="json"),
            )
            return argument

        rider_argument, driver_argument = await asyncio.gather(
            advocate("rider"), advocate("driver")
        )
        run.result.rider_argument = rider_argument
        run.result.driver_argument = driver_argument

        # --- 5. ARBITRATION -----------------------------------------------------
        await run.emit(
            AgentRole.JUDGE,
            "arbitration_start",
            "Judge Agent is weighing both submissions against the verified evidence and policy...",
        )
        await self._pace()
        t_judge = time.perf_counter()
        ruling = await self._guarded(
            run,
            lambda p: p.run_judge(
                case,
                packet,
                vision,
                rider_argument,
                driver_argument,
                run.result.fraud,
                run.result.precedents,
                routing,
            ),
            label="Judge Agent",
        )
        run.result.ruling = ruling
        await run.emit(
            AgentRole.JUDGE,
            "ruling",
            f"Ruling issued: {ruling.decision.value.replace('_', ' ').upper()}"
            + (f" (S${ruling.amount:.2f})" if ruling.amount else "")
            + f" — confidence {ruling.confidence:.0%}.",
            level=EventLevel.RULING,
            duration_ms=int((time.perf_counter() - t_judge) * 1000),
            payload=ruling.model_dump(mode="json"),
        )
        for finding_line in ruling.key_findings:
            await run.emit(
                AgentRole.JUDGE,
                "key_finding",
                finding_line,
                level=EventLevel.RULING,
            )

        # --- 6. ESCALATION --------------------------------------------------------
        await self._apply_escalation(run, ruling)

        run.result.status = (
            DisputeStatus.ESCALATED if ruling.escalated else DisputeStatus.RESOLVED
        )
        await run.emit(
            AgentRole.ORCHESTRATOR,
            "pipeline_complete",
            f"Arbitration complete in {int((time.perf_counter() - t0) * 1000)} ms — "
            f"status: {run.result.status.value}.",
            level=EventLevel.RULING if not ruling.escalated else EventLevel.WARNING,
        )

    # ------------------------------------------------------------------
    # Parallel risk & precedent agents (Phase 2)
    # ------------------------------------------------------------------

    async def _fraud(
        self, run: Run, case: DisputeCase, packet: EvidencePacket
    ) -> FraudAssessment:
        t = time.perf_counter()
        await run.emit(
            AgentRole.FRAUD,
            "fraud_scan",
            "Fraud & Bad-Faith Agent is scoring dispute history, account age and whether the "
            "filed claim contradicts the telemetry...",
        )
        await self._pace()
        assessment = await self._guarded(
            run,
            lambda p: p.run_fraud(case, packet),
            label="Fraud & Bad-Faith Agent",
        )
        run.result.fraud = assessment
        await run.emit(
            AgentRole.FRAUD,
            "fraud_verdict",
            f"Bad-faith risk {assessment.risk_score:.2f} ({assessment.verdict}) — "
            f"rider {assessment.rider_risk:.2f} / driver {assessment.driver_risk:.2f}. "
            f"{assessment.recommended_action}",
            level=(
                EventLevel.WARNING
                if assessment.verdict in ("likely", "confirmed")
                else EventLevel.INFO
            ),
            duration_ms=int((time.perf_counter() - t) * 1000),
            payload=assessment.model_dump(mode="json"),
        )
        for signal in assessment.signals:
            await run.emit(
                AgentRole.FRAUD,
                "fraud_signal",
                f"Risk ({signal.party}/{signal.severity}) {signal.signal} — {signal.detail}",
                level=EventLevel.WARNING if signal.severity != "low" else EventLevel.INFO,
                payload={"party": signal.party, "severity": signal.severity},
            )
        return assessment

    async def _precedent(
        self, run: Run, case: DisputeCase, packet: EvidencePacket
    ) -> PrecedentBundle:
        t = time.perf_counter()
        await run.emit(
            AgentRole.POLICY,
            "precedent_retrieval",
            "Policy & Precedent Agent is searching the knowledge base for analogous past rulings...",
        )
        await self._pace()
        bundle = await self.policy_agent.retrieve(case, packet)
        if self.provider.engine == "adp":
            # Ask the model to translate the retrieved precedents into guidance;
            # on failure _guarded degrades to the stored consistency note.
            guidance = await self._guarded(
                run,
                lambda p: p.run_precedent(case, bundle),
                label="Policy & Precedent Agent",
            )
            if guidance:
                bundle.consistency_note = guidance
        run.result.precedents = bundle
        await run.emit(
            AgentRole.POLICY,
            "precedent_result",
            f"Retrieved {bundle.retrieved_count} analogous precedent(s) — {bundle.consistency_note}",
            duration_ms=int((time.perf_counter() - t) * 1000),
            payload=bundle.model_dump(mode="json"),
        )
        for match in bundle.matches:
            await run.emit(
                AgentRole.POLICY,
                "precedent_match",
                f"[{match.precedent.precedent_id}] similarity {match.similarity:.2f} — "
                f"{match.precedent.title}; resolved as "
                f"{match.precedent.ruling.replace('_', ' ')}"
                + (f" (S${match.precedent.amount:.2f})" if match.precedent.amount else ""),
                payload=match.model_dump(mode="json"),
            )
        return bundle

    # ------------------------------------------------------------------
    # Escalation gate (stretch goal: human-in-the-loop)
    # ------------------------------------------------------------------

    async def _apply_escalation(self, run: Run, ruling: Ruling) -> None:
        reasons: list[str] = []
        if ruling.escalation_reason:
            reasons.append(ruling.escalation_reason)

        mandatory = run.case.dispute_type.value in self.settings.auto_escalate_dispute_types
        if mandatory:
            # The category rule is the authoritative reason, so skip the
            # judge-level "declined to rule" phrasing — saying both is noise.
            reasons.append(
                f"{run.case.dispute_type.value.replace('_', ' ')} disputes always require human review."
            )
        elif ruling.decision == Decision.ESCALATE_TO_HUMAN and not ruling.escalation_reason:
            reasons.append("The Judge declined to issue an autonomous ruling for this category.")

        if ruling.confidence < self.settings.confidence_escalation_threshold:
            reasons.append(
                f"Confidence {ruling.confidence:.0%} is below the "
                f"{self.settings.confidence_escalation_threshold:.0%} autonomy threshold."
            )
            if ruling.decision != Decision.ESCALATE_TO_HUMAN:
                ruling.decision = Decision.ESCALATE_TO_HUMAN
                ruling.amount = 0.0

        if not reasons:
            await run.emit(
                AgentRole.ESCALATION,
                "escalation_check",
                f"Confidence {ruling.confidence:.0%} clears the autonomy threshold — ruling is "
                "issued autonomously, no human review required.",
            )
            return

        ruling.escalated = True
        ruling.escalation_reason = " ".join(reasons)
        run.case.routing_status = RoutingStatus.ESCALATED_TO_HUMAN

        # Post-judge escalation protocol: autonomous arbitration halts here and
        # hands the reviewer a complete packet instead of a bare flag.
        packet = build_escalation_packet(
            run.run_id,
            run.case,
            run.routing,
            run.result.evidence,
            run.result.fraud,
            run.result.precedents,
            ruling,
            ruling.escalation_reason,
            confidence_threshold=self.settings.confidence_escalation_threshold,
        )
        run.result.escalation = packet

        await run.emit(
            AgentRole.ESCALATION,
            "escalation_triggered",
            f"Autonomous arbitration HALTED — escalated to a human reviewer. {ruling.escalation_reason}",
            level=EventLevel.WARNING,
            payload=packet.model_dump(mode="json"),
        )
        await run.emit(
            AgentRole.ESCALATION,
            "escalation_summary",
            packet.case_summary,
            level=EventLevel.WARNING,
        )
        for focus in packet.recommended_focus:
            await run.emit(AgentRole.ESCALATION, "escalation_focus", focus)
        for flag in packet.risk_flags[:4]:
            await run.emit(AgentRole.ESCALATION, "escalation_risk", flag, level=EventLevel.WARNING)

    # ------------------------------------------------------------------
    # Resilience: ADP failure -> deterministic reasoner
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Phase 3: multi-modal ingestion
    # ------------------------------------------------------------------

    async def _prepare_media(self, run: Run) -> None:
        """Transcribe audio and decode video before facts are computed.

        Runs *before* evidence extraction so the ASR transcript and the
        extracted keyframes become first-class facts the advocates, the fraud
        agent and the judge can cite — exactly like the GPS and chat logs.
        """
        case = run.case
        for attachment in case.media_attachments:
            if attachment.media_type == "audio":
                await self._transcribe_audio(run, attachment)
            elif attachment.media_type == "video":
                await self._ingest_video(run, attachment)

    async def _transcribe_audio(self, run: Run, attachment: MediaAttachment) -> None:
        if attachment.transcript is not None:
            return
        t0 = time.perf_counter()
        await run.emit(
            AgentRole.ASR,
            "audio_transcription",
            f"TRTC ASR is transcribing {attachment.attachment_id} "
            f"({attachment.duration_s or 0:.0f}s of in-cabin audio)...",
        )
        await self._pace()
        try:
            transcript = await self.asr.transcribe(attachment)
        except Exception as exc:  # live ASR failed -> deterministic fallback
            await run.emit(
                AgentRole.ASR,
                "audio_transcription",
                f"TRTC ASR unavailable ({type(exc).__name__}: {exc}); using the deterministic "
                "simulated transcription so the run still completes.",
                level=EventLevel.WARNING,
            )
            transcript = await SimulatedASRClient(self.settings).transcribe(attachment)
        attachment.transcript = transcript
        if not transcript.source_url:
            transcript.source_url = attachment.url or (
                self.media_store.web_path(Path(attachment.local_path))
                if attachment.local_path
                else None
            )
        level = EventLevel.WARNING if transcript.threat_detected else EventLevel.EVIDENCE
        await run.emit(
            AgentRole.ASR,
            "audio_transcript",
            f"Transcript ({len(transcript.segments)} turn(s), {transcript.engine} engine): "
            f"hostility {transcript.hostility_score:.2f}"
            + (", EXPLICIT THREAT DETECTED" if transcript.threat_detected else ""),
            level=level,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            payload=transcript.model_dump(mode="json"),
        )
        for segment in transcript.segments:
            await run.emit(
                AgentRole.ASR,
                "audio_turn",
                f"[{segment.start_s:.1f}s-{segment.end_s:.1f}s] {segment.speaker}: "
                f"{segment.text}",
                level=EventLevel.WARNING if segment.hostility >= 0.45 else EventLevel.EVIDENCE,
                payload={"speaker": segment.speaker, "hostility": segment.hostility},
            )

    async def _ingest_video(self, run: Run, attachment: MediaAttachment) -> None:
        if attachment.video is not None:
            return
        t0 = time.perf_counter()
        await run.emit(
            AgentRole.VISION,
            "video_ingest",
            f"Video payload {attachment.attachment_id} detected — sampling keyframes "
            f"at {self.settings.video_frame_fps:g} fps for visual analysis...",
        )
        await self._pace()
        path = (
            resolve_media_path(attachment.local_path, self.settings)
            if attachment.local_path
            else None
        )
        if path is None:
            await run.emit(
                AgentRole.VISION,
                "video_ingest",
                f"Video {attachment.attachment_id} has no decodable local payload — "
                "falling back to metadata-only analysis.",
                level=EventLevel.WARNING,
            )
            return
        try:
            analysis = await asyncio.to_thread(
                analyse_video, path, self.settings, attachment.attachment_id
            )
        except VideoProcessingError as exc:
            await run.emit(
                AgentRole.VISION,
                "video_ingest",
                f"Keyframe extraction failed: {exc}",
                level=EventLevel.WARNING,
            )
            return
        attachment.video = analysis
        attachment.duration_s = attachment.duration_s or analysis.duration_s
        if not analysis.source_url:
            analysis.source_url = attachment.url or self.media_store.web_path(
                Path(attachment.local_path)
            )
        await run.emit(
            AgentRole.VISION,
            "video_frames",
            f"Extracted {analysis.frames_extracted} keyframe(s) "
            f"({analysis.duration_s:.1f}s clip"
            + (f", {analysis.width}x{analysis.height}" if analysis.width else "")
            + f", {analysis.engine} backend).",
            level=EventLevel.EVIDENCE,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            payload=analysis.model_dump(mode="json"),
        )
        for anomaly in analysis.anomalies:
            await run.emit(
                AgentRole.VISION,
                "video_anomaly",
                f"Video integrity flag — {anomaly}",
                level=EventLevel.WARNING,
            )

    async def _guarded(
        self,
        run: Run,
        call: Callable[[LLMProvider], Any],
        *,
        label: str,
    ) -> Any:
        """Run an agent call, degrading to the offline reasoner on failure."""
        try:
            return await call(self.provider)
        except LLMError as exc:
            await run.emit(
                AgentRole.ORCHESTRATOR,
                "provider_degraded",
                f"{label} could not reach Tencent Cloud ADP ({exc}). Falling back to the "
                "deterministic offline reasoner so the arbitration still completes.",
                level=EventLevel.WARNING,
                payload={"error": str(exc), "fallback": "offline"},
            )
            if self.fallback is None:
                self.fallback = OfflineReasoner(self.settings)
            run.result.engine = "offline"
            return await call(self.fallback)


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------


def sse_frame(event: AgentEvent) -> str:
    """Serialise an event as a Server-Sent Event frame."""
    return f"event: {event.level.value}\ndata: {event.model_dump_json()}\n\n"


async def event_stream(
    run: Run, *, poll_interval: float = 0.05, idle_timeout: float = 300.0
) -> AsyncIterator[str]:
    """Yield SSE frames for a run, replaying history then following live."""
    index = 0
    waited = 0.0
    yield ": connected to RydeResolve arbitration stream\n\n"
    while True:
        while index < len(run.events):
            yield sse_frame(run.events[index])
            index += 1
            waited = 0.0
        if run.done:
            yield "event: end\ndata: {\"status\": \"complete\"}\n\n"
            return
        if waited >= idle_timeout:
            yield "event: timeout\ndata: {\"status\": \"timeout\"}\n\n"
            return
        await asyncio.sleep(poll_interval)
        waited += poll_interval
        if waited > 0 and int(waited / poll_interval) % 40 == 0:
            yield ": heartbeat\n\n"
