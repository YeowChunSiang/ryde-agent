"""Phase 2 specialist agents.

Three agents extend the original MVP (advocates + judge + vision):

* :class:`EvidenceCollectionAgent` — a *data-gathering orchestrator*, not an LLM
  text generator. It fans out over the upstream Ryde services (trip, telemetry,
  messaging, analytics, identity, media vault) concurrently and reports what it
  retrieved. Latency is simulated with a deterministic jitter so demos are
  reproducible while still exercising genuine ``asyncio`` concurrency.

* :class:`FraudDetectionAgent` — scores both parties for dispute abuse, fake
  claims and bad-faith behaviour, then emits a single :class:`FraudAssessment`
  that is fed straight to the Judge.

* :class:`PolicyPrecedentAgent` — a mock Retrieval-Augmented Generation layer.
  It keeps a knowledge base of company policy and past rulings, retrieves the
  1-2 most similar historical cases for consistency enforcement, and absorbs
  human overrides so the knowledge base demonstrably improves over time.

No LangGraph / AutoGen / CrewAI — the orchestration is plain ``asyncio``.
"""

from __future__ import annotations

import asyncio
import json
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from config import Settings
from models import (
    CollectionManifest,
    CollectionRecord,
    Decision,
    DisputeCase,
    DisputeType,
    EscalationPacket,
    EvidencePacket,
    FraudAssessment,
    OverrideRequest,
    PrecedentBundle,
    PrecedentCase,
    PrecedentMatch,
    RiskSignal,
    Ruling,
    SLAPriority,
    SLARoutingDecision,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _jitter(seed: str, spread_ms: int) -> int:
    """Deterministic pseudo-random latency in ``[0, spread_ms)``.

    Hash-based rather than ``random`` so a replayed demo produces identical
    timings — a flaky stream is worse than a predictable one.
    """
    return zlib.crc32(seed.encode()) % max(spread_ms, 1)


# ===========================================================================
# 1. SLA & Routing Manager
# ===========================================================================

#: Resolution targets per priority band (minutes).
SLA_TARGETS_MIN: dict[SLAPriority, float] = {
    SLAPriority.CRITICAL: 60.0,
    SLAPriority.HIGH: 240.0,
    SLAPriority.NORMAL: 1440.0,
    SLAPriority.LOW: 4320.0,
}

#: Queue each band is routed into.
SLA_QUEUES: dict[SLAPriority, str] = {
    SLAPriority.CRITICAL: "safety_escalations",
    SLAPriority.HIGH: "priority_resolution",
    SLAPriority.NORMAL: "standard_arbitration",
    SLAPriority.LOW: "batch_arbitration",
}


class SLARoutingManager:
    """Triages an incoming ticket before any agent work begins.

    Dispatch happens at the API boundary so a safety incident is tagged and
    fast-tracked ahead of everything already in the queue.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._queue_depth: dict[str, int] = {q: 0 for q in SLA_QUEUES.values()}

    def route(self, case: DisputeCase) -> SLARoutingDecision:
        ticket = case.dispute_ticket
        reasons: list[str] = []

        # --- derive priority -------------------------------------------------
        if case.sla_priority is not None:
            priority = case.sla_priority
            reasons.append(f"Priority {priority.value.upper()} pinned by the submitting system.")
        elif ticket.dispute_type == DisputeType.SAFETY_INCIDENT:
            priority = SLAPriority.CRITICAL
            reasons.append("Safety incident — auto-escalated to CRITICAL.")
        elif ticket.dispute_type == DisputeType.PROPERTY_DAMAGE:
            priority = SLAPriority.HIGH
            reasons.append("Property damage involves a monetary claim — routed as HIGH.")
        elif ticket.dispute_type == DisputeType.FARE_DISPUTE:
            priority = SLAPriority.HIGH
            reasons.append("Fare dispute affects charged revenue — routed as HIGH.")
        else:
            priority = SLAPriority.NORMAL
            reasons.append("Standard dispute category — routed as NORMAL.")

        # --- escalate priority on behavioural red flags -----------------------
        rider_flags = case.rider_profile.fraud_flags if case.rider_profile else 0
        driver_flags = case.driver_profile.fraud_flags if case.driver_profile else 0
        if max(rider_flags, driver_flags) >= 2:
            if priority not in (SLAPriority.CRITICAL,):
                priority = SLAPriority.HIGH
            reasons.append(
                f"Party carries {max(rider_flags, driver_flags)} fraud flags — priority raised."
            )

        # --- claim value ------------------------------------------------------
        trip = case.trip_data
        claim = trip.cleaning_fee_claimed or trip.cancellation_fee or 0.0
        if claim >= self.settings.sla_high_value_threshold and priority == SLAPriority.NORMAL:
            priority = SLAPriority.HIGH
            reasons.append(f"Claimed amount S${claim:.2f} exceeds the high-value threshold.")

        fast_tracked = priority in (SLAPriority.CRITICAL, SLAPriority.HIGH)
        queue = SLA_QUEUES[priority]

        # Fast-tracked tickets jump the queue: they are inserted at position 1
        # while standard tickets are appended behind whatever is pending.
        if fast_tracked:
            queue_position = 1
            reasons.append(f"Fast-tracked to the head of '{queue}'.")
        else:
            self._queue_depth[queue] += 1
            queue_position = self._queue_depth[queue]
            reasons.append(f"Queued at position {queue_position} in '{queue}'.")

        target = SLA_TARGETS_MIN[priority]
        due_at = (ticket.filed_at or _now()) + timedelta(minutes=target)

        decision = SLARoutingDecision(
            dispute_id=ticket.dispute_id,
            priority=priority,
            routing_status=case.routing_status,
            fast_tracked=fast_tracked,
            queue=queue,
            queue_position=queue_position,
            sla_target_minutes=target,
            sla_due_at=due_at,
            reasons=reasons,
        )

        # Reflect the triage verdict back onto the case for downstream agents.
        case.sla_priority = priority
        case.sla_due_at = due_at
        return decision

    def mark_in_arbitration(self, case: DisputeCase) -> None:
        from models import RoutingStatus

        case.routing_status = RoutingStatus.IN_ARBITRATION


# ===========================================================================
# 2. Evidence Collection Agent
# ===========================================================================


class EvidenceCollectionAgent:
    """Autonomously gathers the structured evidence behind a dispute.

    Every source is fetched concurrently; the agent returns an ingestion
    manifest so the pipeline can prove *what* it retrieved and *how long it
    took* rather than silently assuming the dossier is complete.
    """

    #: Upstream service -> mock endpoint template.
    SOURCES: tuple[tuple[str, str], ...] = (
        ("trip_service", "/v1/trips/{trip_id}"),
        ("telemetry_service", "/v1/trips/{trip_id}/gps"),
        ("messaging_service", "/v1/trips/{trip_id}/messages"),
        ("mobile_analytics", "/v1/trips/{trip_id}/events"),
        ("identity_service", "/v1/users/{rider_id}/profile"),
        ("media_vault", "/v1/trips/{trip_id}/media"),
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def collect(self, case: DisputeCase) -> CollectionManifest:
        trip_id = case.dispute_ticket.trip_id
        rider_id = case.rider_profile.rider_id if case.rider_profile else "unknown"
        started = time.perf_counter()

        async def fetch(source: str, endpoint: str, count: int) -> CollectionRecord:
            endpoint = endpoint.format(trip_id=trip_id, rider_id=rider_id)
            latency = self.settings.collection_base_latency_ms + _jitter(
                f"{case.dispute_id}:{source}", self.settings.collection_jitter_ms
            )
            if self.settings.collection_simulate_latency:
                await asyncio.sleep(latency / 1000.0)

            if count == 0:
                status, note = "empty", "Source returned no records for this trip."
            elif source == "telemetry_service" and count < 3:
                status, note = (
                    "degraded",
                    f"Only {count} GPS pings available — route reconstruction is approximate.",
                )
            else:
                status, note = "ok", None

            return CollectionRecord(
                source=source,
                endpoint=endpoint,
                records=count,
                latency_ms=latency,
                status=status,  # type: ignore[arg-type]
                note=note,
            )

        counts = {
            "trip_service": 1,
            "telemetry_service": len(case.gps_telemetry),
            "messaging_service": len(case.chat_logs),
            "mobile_analytics": len(case.app_events),
            "identity_service": 1 if case.rider_profile else 0,
            "media_vault": len(case.media_attachments),
        }

        records = await asyncio.gather(
            *[
                fetch(source, endpoint, counts.get(source, 0))
                for source, endpoint in self.SOURCES
                if not (source == "media_vault" and not case.media_attachments)
            ]
        )

        records = list(records)
        total_records = sum(r.records for r in records)
        degraded = any(r.status in ("degraded", "failed") for r in records)
        wall_ms = int((time.perf_counter() - started) * 1000)

        ok = [r for r in records if r.status == "ok"]
        summary = (
            f"Retrieved {total_records} records from {len(records)} upstream services in "
            f"{wall_ms} ms (parallel fan-out). "
            + (
                f"{len(records) - len(ok)} source(s) degraded."
                if degraded
                else "All sources responded normally."
            )
        )

        return CollectionManifest(
            dispute_id=case.dispute_id,
            sources=records,
            total_records=total_records,
            total_latency_ms=wall_ms,
            degraded=degraded,
            summary=summary,
        )


# ===========================================================================
# 3. Fraud & Bad-Faith Detection Agent
# ===========================================================================


class FraudDetectionAgent:
    """Scores both parties for dispute abuse, fake claims and collusion.

    Runs concurrently with the Evidence Collection Agent and hands the Judge a
    single structured assessment rather than a pile of raw profile fields.
    """

    #: Weights applied to each behavioural red flag.
    _FLAG_WEIGHT = 0.22

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def assess(
        self, case: DisputeCase, packet: Optional[EvidencePacket] = None
    ) -> FraudAssessment:
        # Yield control so this genuinely overlaps with the collection agent.
        await asyncio.sleep(0)

        signals: list[RiskSignal] = []
        rider_risk = self._score_party(case, packet, "rider", signals)
        driver_risk = self._score_party(case, packet, "driver", signals)
        self._cross_check_claim(case, packet, signals)

        # A bad-faith finding on either side raises the whole-case risk, but the
        # filing party's behaviour weighs more heavily: they set the narrative.
        filer = case.dispute_ticket.filed_by
        filer_risk = rider_risk if filer == "rider" else driver_risk
        other_risk = driver_risk if filer == "rider" else rider_risk
        risk_score = round(min(1.0, 0.65 * filer_risk + 0.35 * other_risk), 3)

        verdict = self._verdict(risk_score)
        action = self._recommended_action(case, verdict, filer)

        return FraudAssessment(
            dispute_id=case.dispute_id,
            risk_score=risk_score,
            verdict=verdict,  # type: ignore[arg-type]
            rider_risk=round(rider_risk, 3),
            driver_risk=round(driver_risk, 3),
            signals=signals,
            recommended_action=action,
            policy_refs=self._policy_refs(verdict),
            reasoning=self._reasoning(case, risk_score, verdict, signals, filer),
        )

    # --- scoring -----------------------------------------------------------

    def _score_party(
        self,
        case: DisputeCase,
        packet: Optional[EvidencePacket],
        party: str,
        signals: list[RiskSignal],
    ) -> float:
        profile = case.rider_profile if party == "rider" else case.driver_profile
        if profile is None:
            return 0.0

        score = 0.0
        history = profile.dispute_history

        # 1. Explicit fraud flags.
        if profile.fraud_flags:
            score += self._FLAG_WEIGHT * profile.fraud_flags
            # ``fraud_flag_details`` only exists on the rider profile.
            details = getattr(profile, "fraud_flag_details", None)
            signals.append(
                RiskSignal(
                    party=party,  # type: ignore[arg-type]
                    signal="prior_fraud_flags",
                    severity="high" if profile.fraud_flags >= 2 else "medium",
                    detail=(
                        f"{profile.fraud_flags} fraud flag(s) on record"
                        + (f" — {details}" if details else "")
                    ),
                )
            )

        # 2. Serial disputant: many disputes relative to trip volume.
        if history.total_disputes >= 5 and profile.total_trips > 0:
            rate = history.total_disputes / profile.total_trips
            if rate > 0.10:
                score += 0.25
                signals.append(
                    RiskSignal(
                        party=party,  # type: ignore[arg-type]
                        signal="serial_dispute_pattern",
                        severity="medium" if rate <= 0.25 else "high",
                        detail=(
                            f"{history.total_disputes} disputes across {profile.total_trips} trips "
                            f"({rate:.1%} — well above the ~2% baseline)"
                        ),
                    )
                )
            elif rate > 0.05:
                score += 0.10
                signals.append(
                    RiskSignal(
                        party=party,  # type: ignore[arg-type]
                        signal="elevated_dispute_rate",
                        severity="low",
                        detail=f"{rate:.1%} of trips end in a dispute — moderately elevated.",
                    )
                )

        # 3. Young account + immediate dispute behaviour.
        if profile.account_age_days <= 30 and history.total_disputes >= 2:
            score += 0.15
            signals.append(
                RiskSignal(
                    party=party,  # type: ignore[arg-type]
                    signal="new_account_high_disputes",
                    severity="medium",
                    detail=(
                        f"Account is {profile.account_age_days} days old with "
                        f"{history.total_disputes} disputes already filed."
                    ),
                )
            )

        # 4. Repeatedly-losing disputant: keeps filing claims that get rejected.
        if history.total_disputes >= 4 and history.rejected >= 3:
            score += 0.10
            signals.append(
                RiskSignal(
                    party=party,  # type: ignore[arg-type]
                    signal="persistent_rejected_claims",
                    severity="low",
                    detail=f"{history.rejected} of {history.total_disputes} past claims were rejected.",
                )
            )

        return min(score, 1.0)

    def _cross_check_claim(
        self,
        case: DisputeCase,
        packet: Optional[EvidencePacket],
        signals: list[RiskSignal],
    ) -> None:
        """Flag claims that telemetry actively contradicts (bad faith)."""
        if packet is None:
            return

        def num(key: str) -> Optional[float]:
            for fact in packet.facts:
                if fact.key == key and isinstance(fact.value, (int, float)):
                    return float(fact.value)
            return None

        filer = case.dispute_ticket.filed_by
        dtype = case.dispute_ticket.dispute_type

        if dtype == DisputeType.NO_SHOW_CHARGE:
            arrived = num("driver_arrived_at_pickup")
            wait = num("driver_wait_minutes")
            if arrived is None and wait is not None and wait >= 1:
                # Driver waited, so "the driver never showed" is contradicted.
                signals.append(
                    RiskSignal(
                        party=filer if filer == "rider" else "driver",  # type: ignore[arg-type]
                        signal="claim_contradicted_by_telemetry",
                        severity="high" if filer == "rider" else "medium",
                        detail=(
                            f"Filing party alleges a no-show, but telemetry shows the driver "
                            f"waited {wait:.0f} min at the pickup point."
                        ),
                    )
                )

        if dtype == DisputeType.PROPERTY_DAMAGE:
            # A damage claim with zero admissible media is a classic fake-claim shape.
            if not case.media_attachments:
                signals.append(
                    RiskSignal(
                        party=filer,  # type: ignore[arg-type]
                        signal="unsubstantiated_damage_claim",
                        severity="medium",
                        detail="Damage claim filed with no supporting photo or video evidence.",
                    )
                )

    def _verdict(self, score: float) -> str:
        if score < 0.20:
            return "none"
        if score < 0.40:
            return "low"
        if score < 0.60:
            return "suspected"
        if score < 0.80:
            return "likely"
        return "confirmed"

    def _policy_refs(self, verdict: str) -> list[str]:
        if verdict in ("likely", "confirmed"):
            return ["FRAUD-1", "FRAUD-3"]
        if verdict == "suspected":
            return ["FRAUD-1"]
        return []

    def _recommended_action(self, case: DisputeCase, verdict: str, filer: str) -> str:
        if verdict == "confirmed":
            return (
                f"Reject the {filer}'s claim outright and refer the account to the Trust & "
                "Safety team for possible suspension."
            )
        if verdict == "likely":
            return (
                "Do not auto-resolve. Require human review and treat the claim as "
                "not-established pending corroborating evidence."
            )
        if verdict == "suspected":
            return "Weigh the claim sceptically and demand corroboration before any payout."
        if verdict == "low":
            return "Proceed with normal arbitration; note the behavioural history in the record."
        return "No abuse indicators — proceed with normal arbitration."

    def _reasoning(
        self,
        case: DisputeCase,
        score: float,
        verdict: str,
        signals: list[RiskSignal],
        filer: str,
    ) -> str:
        if not signals:
            return (
                "No abuse indicators: neither party's dispute history, account age or claim "
                "shape deviates from baseline behaviour."
            )
        top = sorted(signals, key=lambda s: {"high": 0, "medium": 1, "low": 2}[s.severity])[:3]
        detail = "; ".join(f"{s.party}:{s.signal}" for s in top)
        return (
            f"Composite bad-faith risk {score:.2f} ({verdict}) on a case filed by the {filer}. "
            f"Principal indicators — {detail}."
        )


# ===========================================================================
# 4. Policy & Precedent Agent (mock RAG)
# ===========================================================================


#: Company policy clauses the knowledge base can cite.
POLICY_CLAUSES: dict[str, str] = {
    "CANCEL-1": "Drivers must wait at least the free wait period (5 min) before cancelling.",
    "CANCEL-2": "A no-show fee is chargeable only after the no-show threshold (8 min) elapses.",
    "CANCEL-3": "The driver must make at least one genuine contact attempt before cancelling.",
    "ROUTE-1": "Drivers must follow the estimated route unless the rider consents to a change.",
    "ROUTE-2": "Unconsented detours entitle the rider to a refund of the excess distance.",
    "DAMAGE-1": "Cleaning fees require photographic evidence submitted within 24 hours.",
    "DAMAGE-2": "Evidence failing forensic validation is inadmissible.",
    "FARE-1": "The charged fare must not exceed the estimate by more than 20% without cause.",
    "SAFETY-1": "Safety incidents are always escalated to a human reviewer.",
    "FRAUD-1": "Claims contradicted by telemetry are rejected and flagged.",
    "FRAUD-3": "Confirmed fraudulent claims are referred to Trust & Safety.",
}


def _seed_precedents() -> list[PrecedentCase]:
    """Historical rulings the knowledge base starts with.

    ``fact_signature`` drives similarity matching: the retriever compares it
    against the facts the evidence engine computed for the live case.
    """
    return [
        PrecedentCase(
            precedent_id="PREC-1001",
            dispute_type=DisputeType.NO_SHOW_CHARGE,
            title="Driver waited the full no-show window",
            fact_signature={
                "dispute_type": "no_show_charge",
                "driver_arrived": True,
                "past_threshold": True,
                "made_contact": True,
            },
            summary=(
                "Driver arrived on time, waited 9 min past the 8-min threshold and made two "
                "contact attempts. Rider never appeared."
            ),
            ruling=Decision.UPHOLD_CHARGE.value,
            amount=5.0,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1002",
            dispute_type=DisputeType.NO_SHOW_CHARGE,
            title="Driver cancelled early without contact",
            fact_signature={
                "dispute_type": "no_show_charge",
                "driver_arrived": True,
                "past_threshold": False,
                "made_contact": False,
            },
            summary=(
                "Driver reached the pickup point but cancelled after 3 min, below the 8-min "
                "no-show threshold, with no contact attempt."
            ),
            ruling=Decision.REFUND_RIDER.value,
            amount=5.0,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1003",
            dispute_type=DisputeType.ROUTE_DEVIATION,
            title="Unexcused detour added 3 km",
            fact_signature={
                "dispute_type": "route_deviation",
                "exceeds_estimate": True,
                "justified": False,
            },
            summary="Driver took a longer route without rider consent; trip ran 3.2 km over estimate.",
            ruling=Decision.PARTIAL_REFUND.value,
            amount=6.4,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1004",
            dispute_type=DisputeType.ROUTE_DEVIATION,
            title="Longer route explained by verified congestion",
            fact_signature={
                "dispute_type": "route_deviation",
                "exceeds_estimate": True,
                "justified": True,
            },
            summary=(
                "Trip ran 18% over estimate, but congestion data confirmed the detour and the "
                "driver explained it in chat; deviation deemed reasonable."
            ),
            ruling=Decision.NO_ACTION.value,
            amount=0.0,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1005",
            dispute_type=DisputeType.PROPERTY_DAMAGE,
            title="Verified spill photo within trip window",
            fact_signature={
                "dispute_type": "property_damage",
                "media_admissible": True,
            },
            summary="Driver submitted a timestamped photo taken 11 min after trip end; spill verified.",
            ruling=Decision.COMPENSATE_DRIVER.value,
            amount=60.0,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1006",
            dispute_type=DisputeType.PROPERTY_DAMAGE,
            title="Photo failed EXIF validation",
            fact_signature={
                "dispute_type": "property_damage",
                "media_admissible": False,
            },
            summary="Cleaning claim rested on a photo taken 86 min after trip end; ruled inadmissible.",
            ruling=Decision.NO_ACTION.value,
            amount=0.0,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1007",
            dispute_type=DisputeType.SAFETY_INCIDENT,
            title="Alleged unsafe driving, no corroboration",
            fact_signature={"dispute_type": "safety_incident"},
            summary="Rider alleged dangerous driving; no telemetry corroboration. Routed to human review.",
            ruling=Decision.ESCALATE_TO_HUMAN.value,
            amount=0.0,
            source="seed",
        ),
        PrecedentCase(
            precedent_id="PREC-1008",
            dispute_type=DisputeType.FARE_DISPUTE,
            title="Fare charged 34% over estimate",
            fact_signature={"dispute_type": "fare_dispute", "exceeds_estimate": True},
            summary="Charged fare exceeded the estimate by 34% with no traffic or detour justification.",
            ruling=Decision.PARTIAL_REFUND.value,
            amount=8.2,
            source="seed",
        ),
    ]


class PrecedentStore:
    """The knowledge base behind the Policy & Precedent Agent.

    Backed by a JSON file so human overrides survive a restart — that is what
    makes the learning loop observable rather than theoretical.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self.cases: list[PrecedentCase] = []
        self._loaded = False
        if path is not None:
            self._load()

    def _load(self) -> None:
        assert self.path is not None
        self._loaded = True
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text())
                self.cases = [PrecedentCase.model_validate(c) for c in raw]
                return
        except Exception:  # corrupt file -> reseed rather than crash the service
            pass
        self.cases = _seed_precedents()
        self._persist()

    def _persist(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps([c.model_dump(mode="json") for c in self.cases], indent=2)
            )
        except Exception:  # read-only FS must never break arbitration
            pass

    @property
    def size(self) -> int:
        if self.path is not None and not self._loaded:
            self._load()
        if not self.cases and self.path is None:
            self.cases = _seed_precedents()
        return len(self.cases)

    def all(self) -> list[PrecedentCase]:
        _ = self.size  # force lazy load/seed
        return list(self.cases)

    def add(self, case: PrecedentCase) -> PrecedentCase:
        _ = self.size
        self.cases.append(case)
        self._persist()
        return case

    def reset(self) -> None:
        self.cases = _seed_precedents()
        self._persist()


class PolicyPrecedentAgent:
    """Retrieves similar past rulings so the Judge stays consistent."""

    def __init__(self, settings: Settings, store: Optional[PrecedentStore] = None) -> None:
        self.settings = settings
        self.store = store or PrecedentStore(settings.precedent_store_path)

    async def retrieve(
        self, case: DisputeCase, packet: Optional[EvidencePacket] = None
    ) -> PrecedentBundle:
        await asyncio.sleep(0)

        facts = _fact_signature(case, packet)
        scored: list[tuple[float, list[str], PrecedentCase]] = []
        for precedent in self.store.all():
            score, matched = _similarity(precedent.fact_signature, facts)
            scored.append((score, matched, precedent))

        scored.sort(key=lambda t: t[0], reverse=True)
        top = [s for s in scored if s[0] > 0][: self.settings.precedent_top_k]

        matches = [
            PrecedentMatch(
                precedent=precedent,
                similarity=round(score, 3),
                matched_on=matched,
                recommendation=self._recommendation(precedent, score),
            )
            for score, matched, precedent in top
        ]

        return PrecedentBundle(
            dispute_id=case.dispute_id,
            matches=matches,
            retrieved_count=len(matches),
            consistency_note=self._consistency_note(case, matches),
        )

    def learn_from_override(
        self,
        case: DisputeCase,
        packet: Optional[EvidencePacket],
        ruling: Ruling,
        request: OverrideRequest,
        run_id: str,
    ) -> Optional[PrecedentCase]:
        """Absorb a human correction into the knowledge base."""
        if not request.add_to_knowledge_base:
            return None
        return self.store.add(
            PrecedentCase(
                dispute_type=case.dispute_type,
                title=f"Human override — {case.dispute_id}",
                fact_signature=_fact_signature(case, packet),
                summary=(
                    f"Reviewer {request.reviewer_id} overrode the escalated ruling on "
                    f"{case.dispute_id}. {request.rationale.strip()}"
                ),
                ruling=request.decision.value,
                amount=request.amount,
                source="human_override",
                learned_from_run_id=run_id,
                reviewer_note=request.rationale.strip(),
            )
        )

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _recommendation(precedent: PrecedentCase, score: float) -> str:
        strength = "strongly" if score >= 0.75 else ("moderately" if score >= 0.5 else "loosely")
        return (
            f"{precedent.precedent_id} ({strength} analogous) resolved as "
            f"{precedent.ruling.replace('_', ' ')}"
            + (f" for S${precedent.amount:.2f}" if precedent.amount else "")
            + ". Apply the same treatment unless this case is materially distinguishable."
        )

    @staticmethod
    def _consistency_note(case: DisputeCase, matches: list[PrecedentMatch]) -> str:
        if not matches:
            return (
                "No analogous precedent in the knowledge base — the Judge should rule on first "
                "principles and state its reasoning explicitly."
            )

        # Only precedents clearing the similarity bar are binding guidance; the
        # weaker ones are shown to the Judge as contrast, not as instruction.
        strong = [m for m in matches if m.similarity >= 0.50]
        if not strong:
            closest = matches[0]
            return (
                f"No precedent clears the 0.50 similarity bar. Closest was "
                f"{closest.precedent.precedent_id} at {closest.similarity:.2f} "
                f"({closest.precedent.ruling.replace('_', ' ')}) — treat as context only."
            )

        outcomes = {m.precedent.ruling for m in strong}
        if len(outcomes) == 1:
            outcome = outcomes.pop().replace("_", " ")
            return (
                f"{len(strong)} precedent(s) above the similarity bar all resolved as "
                f"{outcome} — the ruling should align for consistency."
            )
        return (
            "Strong precedents diverge ("
            + ", ".join(sorted(o.replace("_", " ") for o in outcomes))
            + "). Distinguish this case on its specific facts and explain the departure."
        )


def _num(facts: dict[str, Any], key: str) -> Optional[float]:
    value = facts.get(key)
    return float(value) if isinstance(value, (int, float)) else None


def _fact_signature(
    case: DisputeCase, packet: Optional[EvidencePacket]
) -> dict[str, Any]:
    """Reduce the live case to the same shape as ``PrecedentCase.fact_signature``.

    The keys must mirror what :mod:`evidence` actually emits — signatures are
    only useful if the retriever can compute them from real facts.
    """
    sig: dict[str, Any] = {"dispute_type": case.dispute_type.value}
    if packet is None:
        return sig

    facts = {f.key: f.value for f in packet.facts}
    dtype = case.dispute_type

    if dtype == DisputeType.NO_SHOW_CHARGE:
        delta = _num(facts, "arrival_delta_min")
        wait = _num(facts, "driver_wait_minutes")
        attempts = _num(facts, "driver_contact_attempts")
        if delta is not None:
            # Arrived within 5 min of the scheduled pickup counts as on time.
            sig["driver_arrived"] = delta <= 5
        if wait is not None:
            sig["past_threshold"] = wait >= 8
        if attempts is not None:
            sig["made_contact"] = attempts >= 1

    elif dtype == DisputeType.ROUTE_DEVIATION:
        deviation = _num(facts, "route_deviation_pct")
        if deviation is not None:
            sig["exceeds_estimate"] = deviation >= 20
            # An explanation only justifies a *modest* detour — a 60% overrun
            # is not excused by "there was traffic".
            explained = any(
                facts.get(k) for k in ("driver_explanation", "traffic_evidence")
            )
            sig["justified"] = bool(explained) and deviation < 25

    elif dtype == DisputeType.PROPERTY_DAMAGE:
        ai_prob: Optional[float] = None
        delta_min: Optional[float] = None
        for key, value in facts.items():
            if key.endswith("_ai_probability") and isinstance(value, (int, float)):
                ai_prob = float(value)
            elif key.endswith("_exif_delta_min") and isinstance(value, (int, float)):
                delta_min = float(value)
        if delta_min is not None or ai_prob is not None:
            sig["media_admissible"] = (
                (delta_min is None or abs(delta_min) <= 45)
                and (ai_prob is None or ai_prob < 0.50)
            )

    elif dtype == DisputeType.FARE_DISPUTE:
        variance = _num(facts, "fare_variance_pct")
        if variance is not None:
            sig["exceeds_estimate"] = variance > 20

    return sig


def _similarity(signature: dict[str, Any], facts: dict[str, Any]) -> tuple[float, list[str]]:
    """Score a precedent against the live case; return ``(score, matched_keys)``."""
    if signature.get("dispute_type") != facts.get("dispute_type"):
        # Different category — still marginally informative, but not precedent.
        return 0.05, []

    matched: list[str] = []
    score = 0.45
    for key, expected in signature.items():
        if key == "dispute_type":
            continue
        actual = facts.get(key)
        if actual is None:
            continue
        if actual == expected:
            score += 0.22
            matched.append(f"{key}={actual}")
        else:
            score -= 0.10
            matched.append(f"{key}≠{actual}")
    return max(0.0, min(score, 1.0)), matched


# ===========================================================================
# 5. Escalation packet assembly
# ===========================================================================


def build_escalation_packet(
    run_id: str,
    case: DisputeCase,
    routing: Optional[SLARoutingDecision],
    packet: Optional[EvidencePacket],
    fraud: Optional[FraudAssessment],
    precedents: Optional[PrecedentBundle],
    ruling: Ruling,
    reason: str,
    *,
    confidence_threshold: float = 0.70,
) -> EscalationPacket:
    """Assemble the hand-off a human reviewer actually needs."""
    ticket = case.dispute_ticket

    evidence_digest: list[str] = []
    if packet is not None:
        evidence_digest = [
            f"{f.label}: {f.value}{(' ' + f.unit) if f.unit else ''}"
            + (f" ({f.note})" if f.note else "")
            for f in packet.facts[:8]
        ]
        evidence_digest += [
            f"[{c.ref}] {'PASS' if c.compliant else 'FAIL'} — {c.description}: "
            f"expected {c.expected}, observed {c.actual}"
            for c in packet.policy_checks
        ]

    risk_flags = []
    if fraud is not None:
        risk_flags.append(
            f"Bad-faith risk {fraud.risk_score:.2f} ({fraud.verdict}) — {fraud.reasoning}"
        )
        risk_flags += [f"{s.party}/{s.severity}: {s.signal} — {s.detail}" for s in fraud.signals]
    if packet is not None:
        risk_flags += [
            f"{s.party}/{s.severity}: {s.signal} — {s.detail}" for s in packet.risk_signals
        ]

    recommended_focus: list[str] = []
    if ruling.confidence < confidence_threshold:
        recommended_focus.append(
            f"Judge confidence was only {ruling.confidence:.0%} — confirm or replace the "
            "proposed decision."
        )
    if fraud is not None and fraud.verdict in ("likely", "confirmed"):
        recommended_focus.append(
            "Bad-faith indicators are strong — decide whether to refer to Trust & Safety."
        )
    if precedents is not None and len({m.precedent.ruling for m in precedents.matches}) > 1:
        recommended_focus.append(
            "Retrieved precedents diverge — document why this case follows one over the other."
        )
    if case.media_attachments:
        recommended_focus.append("Re-examine the submitted media by eye before ruling.")
    if not recommended_focus:
        recommended_focus.append("Verify the evidence digest below and issue a final decision.")

    case_summary = (
        f"{ticket.dispute_type.value.replace('_', ' ').title()} dispute {ticket.dispute_id} "
        f"(trip {ticket.trip_id}) filed by the {ticket.filed_by} on "
        f"{ticket.filed_at.strftime('%Y-%m-%d %H:%M')} UTC. "
        f"Party statement: \"{ticket.description.strip()}\" "
        f"Judge proposed {ruling.decision.value.replace('_', ' ')}"
        + (f" (S${ruling.amount:.2f})" if ruling.amount else "")
        + f" at {ruling.confidence:.0%} confidence. Halted because: {reason}"
    )

    return EscalationPacket(
        run_id=run_id,
        dispute_id=ticket.dispute_id,
        priority=routing.priority if routing else SLAPriority.NORMAL,
        queue=routing.queue if routing else "standard_arbitration",
        sla_due_at=routing.sla_due_at if routing else case.sla_due_at,
        routed_to="human_review_queue",
        case_summary=case_summary,
        evidence_digest=evidence_digest,
        conflicting_points=_conflicts(case, packet),
        risk_flags=risk_flags,
        judge_recommendation=ruling.reasoning,
        recommended_focus=recommended_focus,
    )


def _conflicts(case: DisputeCase, packet: Optional[EvidencePacket]) -> list[str]:
    """Pull out the facts the two sides disagree about."""
    conflicts: list[str] = []
    if packet is None:
        return conflicts
    contested = {"driver_arrived_at_pickup", "driver_wait_minutes", "contact_attempts"}
    for fact in packet.facts:
        if fact.key in contested:
            conflicts.append(
                f"Contested — {fact.label}: {fact.value}{(' ' + fact.unit) if fact.unit else ''} "
                f"({fact.source})"
            )
    if case.media_attachments:
        conflicts.append(
            f"{len(case.media_attachments)} media attachment(s) submitted — admissibility is "
            "the pivotal question."
        )
    return conflicts
