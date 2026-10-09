"""Deterministic async state pipeline for multi-agent dispute arbitration.

The pipeline is deliberately *not* an autonomous agent graph — it is an explicit
state machine, which is what a legal-style arbitration process actually needs:

    1. INTAKE      validate the dossier against Pydantic models
    2. EVIDENCE    compute auditable facts in pure Python (no LLM)
    3. VISION      (conditional) forensic screen of submitted media
    4. ADVOCACY    Rider + Driver advocates run concurrently via asyncio.gather
    5. ARBITRATION Judge weighs both cases against policy
    6. ESCALATION  confidence gate -> human-in-the-loop

Every state transition is emitted as an ``AgentEvent`` so the frontend can stream
the agents "thinking" in real time over SSE — the observability requirement from
the Ryde problem statement ("inter-agent communication should be observable").
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional

from adp_client import (
    ADPClient,
    LLMError,
    LLMProvider,
    OfflineReasoner,
    build_provider,
)
from config import Settings
from evidence import extract_evidence
from models import (
    AdvocateArgument,
    AgentEvent,
    AgentRole,
    Decision,
    DisputeCase,
    DisputeStatus,
    EventLevel,
    EvidencePacket,
    ResolutionResult,
    Ruling,
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

    @property
    def engine(self) -> str:
        return self.provider.engine

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

        # --- 2. EVIDENCE ---------------------------------------------------
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
        await self._pace()

        # --- 3. VISION (conditional) ----------------------------------------
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
                await run.emit(
                    AgentRole.VISION,
                    "vision_analysis",
                    f"Image Analysis Agent is inspecting {attachment.attachment_id}: verifying "
                    "authenticity and cross-referencing the EXIF timestamp against the trip window...",
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
                        f"Image Analysis: photo is {'GENUINE' if finding.genuine else 'NOT ADMISSIBLE'} "
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
            lambda p: p.run_judge(case, packet, vision, rider_argument, driver_argument),
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
    # Escalation gate (stretch goal: human-in-the-loop)
    # ------------------------------------------------------------------

    async def _apply_escalation(self, run: Run, ruling: Ruling) -> None:
        reasons: list[str] = []
        if ruling.escalation_reason:
            reasons.append(ruling.escalation_reason)

        if run.case.dispute_type.value in self.settings.auto_escalate_dispute_types:
            reasons.append(
                f"{run.case.dispute_type.value.replace('_', ' ')} disputes always require human review."
            )

        if ruling.confidence < self.settings.confidence_escalation_threshold:
            reasons.append(
                f"Confidence {ruling.confidence:.0%} is below the "
                f"{self.settings.confidence_escalation_threshold:.0%} autonomy threshold."
            )
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
        await run.emit(
            AgentRole.ESCALATION,
            "escalation_triggered",
            f"Escalated to a human reviewer — {ruling.escalation_reason}",
            level=EventLevel.WARNING,
            payload={"reason": ruling.escalation_reason},
        )

    # ------------------------------------------------------------------
    # Resilience: ADP failure -> deterministic reasoner
    # ------------------------------------------------------------------

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
