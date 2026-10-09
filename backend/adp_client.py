"""LLM providers: Tencent Cloud ADP (HTTP SSE) and a deterministic offline reasoner.

Both providers satisfy the same interface, so the orchestrator is engine-agnostic:

    async def run_vision(...)   -> VisionFinding
    async def run_advocate(...) -> AdvocateArgument
    async def run_judge(...)    -> Ruling

``ADPClient`` talks to ADP over Server-Sent Events and parses the strict JSON
contract declared in ``prompts.py``.

``OfflineReasoner`` computes the same structures in pure Python from the
evidence packet. It exists for two reasons:

1. **Demo resilience** — a hackathon demo must not die because a credential is
   missing, a network is firewalled, or ADP rate-limits us mid-presentation.
2. **Responsible AI** — it gives us a deterministic, replayable baseline ruling
   to compare the model against, which is exactly the "consistent rulings" pain
   point in the Ryde problem statement.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import httpx

from config import Settings
from models import (
    AdvocateArgument,
    Decision,
    DisputeCase,
    EvidencePacket,
    Fact,
    Ruling,
    VisionFinding,
)
from prompts import (
    DRIVER_ADVOCATE_SYSTEM,
    IMAGE_ANALYSIS_SYSTEM,
    JUDGE_SYSTEM,
    RIDER_ADVOCATE_SYSTEM,
    build_advocate_prompt,
    build_judge_prompt,
    build_vision_prompt,
)


class LLMError(Exception):
    """Base error for provider failures."""


class ADPNotConfigured(LLMError):
    """Raised when ADP is requested but no AppKey is present."""


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_loose(raw: str) -> dict[str, Any]:
    """Extract a JSON object from a possibly chatty model response."""
    if not raw:
        raise LLMError("empty model response")

    text = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the outermost {...} span.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"model returned malformed JSON: {exc}") from exc
    raise LLMError("model response contained no JSON object")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(high, value)), 3)


def _f(value: float) -> str:
    return f"{value:.2f}"


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Contract every reasoning backend must satisfy."""

    engine: str

    async def complete(
        self,
        system: str,
        user: str,
        *,
        visitor_id: str,
        conversation_id: Optional[str] = None,
        agent: str = "agent",
    ) -> str: ...

    async def run_vision(
        self, case: DisputeCase, packet: EvidencePacket, attachment: Any
    ) -> VisionFinding: ...

    async def run_advocate(
        self,
        case: DisputeCase,
        packet: EvidencePacket,
        vision: Sequence[VisionFinding],
        party: str,
    ) -> AdvocateArgument: ...

    async def run_judge(
        self,
        case: DisputeCase,
        packet: EvidencePacket,
        vision: Sequence[VisionFinding],
        rider_argument: AdvocateArgument,
        driver_argument: AdvocateArgument,
    ) -> Ruling: ...


# ---------------------------------------------------------------------------
# Tencent Cloud ADP provider
# ---------------------------------------------------------------------------


class ADPClient:
    """Asynchronous SSE client for ``/adp/v2/chat``."""

    engine = "adp"

    # Keys ADP / LKE-style payloads use to carry streamed text.
    _CONTENT_KEYS = (
        "Content",
        "content",
        "Delta",
        "delta",
        "Reply",
        "reply",
        "Answer",
        "answer",
        "Text",
        "text",
        "Data",
        "data",
    )

    def __init__(self, settings: Settings) -> None:
        if not settings.adp_configured:
            raise ADPNotConfigured("ADP_APP_KEY is not set")
        self.settings = settings
        self._client: Optional[httpx.AsyncClient] = None

    # --- lifecycle ---------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.adp_timeout_s, connect=10.0),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # --- raw chat ----------------------------------------------------------
    async def complete(
        self,
        system: str,
        user: str,
        *,
        visitor_id: str,
        conversation_id: Optional[str] = None,
        agent: str = "agent",
    ) -> str:
        payload: dict[str, Any] = {
            "AppKey": self.settings.adp_app_key,
            "VisitorId": f"{self.settings.adp_visitor_id_prefix}-{visitor_id}",
            "Content": f"{system.strip()}\n\n{user.strip()}",
            "Streaming": 1,
        }
        if conversation_id:
            payload["ConversationId"] = conversation_id

        last_error: Optional[Exception] = None
        for attempt in range(self.settings.adp_max_retries + 1):
            try:
                return await self._stream(payload)
            except (httpx.HTTPError, LLMError) as exc:
                last_error = exc
                if attempt >= self.settings.adp_max_retries:
                    break
        raise LLMError(f"ADP call failed for {agent}: {last_error}")

    async def _stream(self, payload: dict[str, Any]) -> str:
        client = await self._get_client()
        chunks: list[str] = []
        async with client.stream(
            "POST", self.settings.adp_endpoint, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                chunks.append(self._extract_text(data))
        text = "".join(chunks).strip()
        if not text:
            raise LLMError("ADP returned an empty stream")
        return text

    def _extract_text(self, data: str) -> str:
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            return data
        if isinstance(event, dict):
            for key in self._CONTENT_KEYS:
                value = event.get(key)
                if isinstance(value, str) and value:
                    return value
            # Some deployments nest the payload under Payload / Choices / Data.
            for wrapper in ("Payload", "payload", "Choices", "choices", "Result"):
                nested = event.get(wrapper)
                if isinstance(nested, str) and nested:
                    return nested
                if isinstance(nested, dict):
                    for key in self._CONTENT_KEYS:
                        value = nested.get(key)
                        if isinstance(value, str) and value:
                            return value
            return ""
        return str(event)

    # --- structured agent calls ---------------------------------------------
    async def run_vision(
        self, case: DisputeCase, packet: EvidencePacket, attachment: Any
    ) -> VisionFinding:
        raw = await self.complete(
            IMAGE_ANALYSIS_SYSTEM,
            build_vision_prompt(case, attachment),
            visitor_id=f"{case.dispute_id}-vision",
            agent="vision",
        )
        data = parse_json_loose(raw)
        return VisionFinding(
            attachment_id=str(data.get("attachment_id", attachment.attachment_id)),
            genuine=bool(data.get("genuine", False)),
            authenticity_confidence=_clamp(
                float(data.get("authenticity_confidence", 0.5) or 0.5)
            ),
            ai_generated_probability=(
                _clamp(float(data["ai_generated_probability"]))
                if data.get("ai_generated_probability") is not None
                else None
            ),
            exif_timestamp_delta_min=(
                float(data["exif_timestamp_delta_min"])
                if data.get("exif_timestamp_delta_min") is not None
                else None
            ),
            severity=data.get("severity", "none"),
            anomalies=[str(a) for a in data.get("anomalies", [])] or [],
            reasoning=str(data.get("reasoning", "")),
        )

    async def run_advocate(
        self,
        case: DisputeCase,
        packet: EvidencePacket,
        vision: Sequence[VisionFinding],
        party: str,
    ) -> AdvocateArgument:
        system = RIDER_ADVOCATE_SYSTEM if party == "rider" else DRIVER_ADVOCATE_SYSTEM
        raw = await self.complete(
            system,
            build_advocate_prompt(case, packet, vision, party),
            visitor_id=f"{case.dispute_id}-{party}",
            agent=f"{party}_advocate",
        )
        data = parse_json_loose(raw)
        return AdvocateArgument(
            agent=f"{party}_advocate",
            headline=str(data.get("headline", f"{party.title()} case")),
            claim=str(data.get("claim", "")),
            cited_facts=[str(k) for k in data.get("cited_facts", [])],
            policy_refs=[str(k) for k in data.get("policy_refs", [])],
            requested_outcome=str(data.get("requested_outcome", "")),
            confidence=_clamp(float(data.get("confidence", 0.5) or 0.5)),
            weaknesses=[str(w) for w in data.get("weaknesses", [])],
        )

    async def run_judge(
        self,
        case: DisputeCase,
        packet: EvidencePacket,
        vision: Sequence[VisionFinding],
        rider_argument: AdvocateArgument,
        driver_argument: AdvocateArgument,
    ) -> Ruling:
        raw = await self.complete(
            JUDGE_SYSTEM,
            build_judge_prompt(case, packet, vision, rider_argument, driver_argument),
            visitor_id=f"{case.dispute_id}-judge",
            agent="judge",
        )
        data = parse_json_loose(raw)
        decision = str(data.get("decision", "no_action"))
        if decision not in Decision._value2member_map_:
            decision = "no_action"
        return Ruling(
            dispute_id=case.dispute_id,
            decision=Decision(decision),
            amount=round(float(data.get("amount", 0) or 0), 2),
            confidence=_clamp(float(data.get("confidence", 0.5) or 0.5)),
            reasoning=str(data.get("reasoning", "")),
            key_findings=[str(k) for k in data.get("key_findings", [])],
            policy_applied=[str(k) for k in data.get("policy_applied", [])],
            rider_summary=str(data.get("rider_summary", "")),
            driver_summary=str(data.get("driver_summary", "")),
        )


# ---------------------------------------------------------------------------
# Deterministic offline reasoner
# ---------------------------------------------------------------------------


def _fact(packet: EvidencePacket, key: str) -> Optional[Fact]:
    for fact in packet.facts:
        if fact.key == key:
            return fact
    return None


def _num(packet: EvidencePacket, key: str, default: float = 0.0) -> float:
    fact = _fact(packet, key)
    if fact is None or not isinstance(fact.value, (int, float)):
        return default
    return float(fact.value)


class OfflineReasoner:
    """Evidence-driven reasoning with no network dependency.

    The rhetoric is generated from the computed facts; the verdict is produced by
    an explicit, reviewable scoring rule rather than by a generative model.
    """

    engine = "offline"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def aclose(self) -> None:  # symmetry with ADPClient
        return None

    # --- interface ----------------------------------------------------------
    async def complete(
        self,
        system: str,
        user: str,
        *,
        visitor_id: str,
        conversation_id: Optional[str] = None,
        agent: str = "agent",
    ) -> str:
        raise LLMError("OfflineReasoner does not serve free-form completions")

    async def run_vision(
        self, case: DisputeCase, packet: EvidencePacket, attachment: Any
    ) -> VisionFinding:
        trip_end = case.trip_data.trip_end_time or case.trip_data.cancellation_time
        delta: Optional[float] = None
        if trip_end and attachment.captured_at:
            delta = round((attachment.captured_at - trip_end).total_seconds() / 60.0, 1)

        ai_prob = attachment.ai_generated_probability
        anomalies: list[str] = []

        exif_ok = True
        if not attachment.exif_present or attachment.captured_at is None:
            exif_ok = False
            anomalies.append("EXIF metadata missing — capture time cannot be verified")
        elif delta is not None and abs(delta) > 45:
            exif_ok = False
            anomalies.append(
                f"EXIF capture time is {abs(delta):.0f} min after trip end — outside the 45 min window"
            )

        ai_ok = True
        if ai_prob is not None and ai_prob >= 0.50:
            ai_ok = False
            anomalies.append(
                f"AI-generation probability {ai_prob:.2f} exceeds the 0.50 admissibility threshold"
            )

        caption = (attachment.caption or "").lower()
        if any(k in caption for k in ("spill", "drink", "liquid", "bubble tea", "coffee")):
            severity = "liquid_spill"
        elif any(k in caption for k in ("mess", "rubbish", "litter", "stain", "food")):
            severity = "minor_mess"
        elif any(k in caption for k in ("damage", "torn", "broken", "vomit")):
            severity = "major_damage"
        else:
            severity = "minor_mess"

        genuine = exif_ok and ai_ok
        if not genuine:
            anomalies.append("Evidence marked inadmissible — excluded from the ruling")

        confidence = 0.9 if (exif_ok and ai_ok) else 0.86
        reasoning = (
            "EXIF timestamp is consistent with the trip window and the image passed the "
            "synthetic-media screen; the cabin condition is admissible evidence."
            if genuine
            else "The photo fails forensic validation: "
            + "; ".join(anomalies[:2])
            + ". Under policy DAMAGE-2 the claim cannot rely on it, so the cleaning charge is "
            "not supported by admissible evidence."
        )

        return VisionFinding(
            attachment_id=attachment.attachment_id,
            genuine=genuine,
            authenticity_confidence=confidence,
            ai_generated_probability=ai_prob,
            exif_timestamp_delta_min=delta,
            severity=severity,
            anomalies=anomalies,
            reasoning=reasoning,
        )

    async def run_advocate(
        self,
        case: DisputeCase,
        packet: EvidencePacket,
        vision: Sequence[VisionFinding],
        party: str,
    ) -> AdvocateArgument:
        other = "driver" if party == "rider" else "rider"
        mine = packet.facts_for(party)
        theirs = packet.facts_for(other)
        checks_mine = [c for c in packet.policy_checks if c.supports == party]
        checks_theirs = [c for c in packet.policy_checks if c.supports == other]

        total = max(len(packet.facts), 1)
        share = len(mine) / total
        confidence = _clamp(0.35 + 0.55 * share + 0.05 * len(checks_mine))

        claim_parts: list[str] = [self._opening(case, packet, party)]
        for fact in mine[:5]:
            claim_parts.append(
                f"{fact.label} is {fact.value}{' ' + fact.unit if fact.unit else ''}"
                f"{' (' + fact.note + ')' if fact.note else ''}."
            )
        for check in checks_mine[:3]:
            claim_parts.append(f"Policy {check.ref} is satisfied — {check.description}.")
        if not claim_parts[1:]:
            claim_parts.append(
                "The verified evidence offers limited direct support for this party, so the case "
                "rests on the absence of proof against them rather than on affirmative proof."
            )

        weaknesses = [
            f"{f.label}: {f.value}{' ' + f.unit if f.unit else ''}" for f in theirs[:2]
        ] + [f"Policy {c.ref} cuts against this party ({c.description})." for c in checks_theirs[:1]]
        if not weaknesses:
            weaknesses = ["No material contradicting evidence was found in the packet."]

        vision_line = ""
        admissible = [v for v in vision if v.genuine]
        rejected = [v for v in vision if not v.genuine]
        if vision:
            if admissible and party == "driver":
                vision_line = (
                    f" The vision agent admitted the submitted photo at severity "
                    f"'{admissible[0].severity}', which corroborates the cleaning claim."
                )
            elif rejected and party == "rider":
                vision_line = (
                    f" The vision agent rejected the photo as inadmissible "
                    f"({rejected[0].anomalies[0] if rejected[0].anomalies else 'failed forensic checks'}), "
                    "so the cleaning claim rests on no admissible evidence."
                )
            elif rejected and party == "driver":
                vision_line = (
                    " The photo submitted in support of the claim did not clear forensic "
                    "validation, which weakens this party's position."
                )
        if vision_line:
            claim_parts.append(vision_line.strip())

        return AdvocateArgument(
            agent=f"{party}_advocate",
            headline=self._headline(case, party),
            claim=" ".join(claim_parts),
            cited_facts=[f.key for f in mine][:6],
            policy_refs=[c.ref for c in checks_mine],
            requested_outcome=self._requested_outcome(case, packet, party),
            confidence=confidence,
            weaknesses=weaknesses,
        )

    async def run_judge(
        self,
        case: DisputeCase,
        packet: EvidencePacket,
        vision: Sequence[VisionFinding],
        rider_argument: AdvocateArgument,
        driver_argument: AdvocateArgument,
    ) -> Ruling:
        dtype = case.dispute_type
        if dtype == "no_show_charge":
            return _judge_no_show(case, packet)
        if dtype == "route_deviation":
            return _judge_route_deviation(case, packet)
        if dtype == "property_damage":
            return _judge_property_damage(case, packet, vision)
        return _judge_generic(case, packet)

    # --- rhetoric helpers ----------------------------------------------------
    def _headline(self, case: DisputeCase, party: str) -> str:
        if party == "rider":
            return {
                "no_show_charge": "Rider was never served — charge should be reversed",
                "route_deviation": "Unjustified detour inflated the fare",
                "property_damage": "Cleaning claim is unsupported by valid evidence",
            }.get(case.dispute_type.value, "Rider's position")
        return {
            "no_show_charge": "Driver fulfilled every policy obligation",
            "route_deviation": "Detour was a necessary, communicated response to traffic",
            "property_damage": "Documented mess warrants the cleaning fee",
        }.get(case.dispute_type.value, "Driver's position")

    def _opening(self, case: DisputeCase, packet: EvidencePacket, party: str) -> str:
        who = "rider" if party == "rider" else "driver"
        return (
            f"On behalf of the {who} in dispute {case.dispute_id} "
            f"({case.dispute_type.value.replace('_', ' ')}), the verified evidence establishes the "
            "following."
        )

    def _requested_outcome(self, case: DisputeCase, packet: EvidencePacket, party: str) -> str:
        fee = case.trip_data.cancellation_fee or 0.0
        if case.dispute_type == "no_show_charge":
            return (
                f"Reverse the S${fee:.2f} cancellation charge in full."
                if party == "rider"
                else f"Uphold the S${fee:.2f} cancellation charge as driver compensation."
            )
        if case.dispute_type == "route_deviation":
            over = max(
                (case.trip_data.fare_charged or 0) - (case.trip_data.fare_estimate or 0), 0.0
            )
            return (
                f"Refund the full S${over:.2f} overcharge."
                if party == "rider"
                else "Uphold the fare as charged — the detour was justified."
            )
        if case.dispute_type == "property_damage":
            fee_claim = case.trip_data.cleaning_fee_claimed or 0.0
            return (
                f"Waive the S${fee_claim:.2f} cleaning fee entirely."
                if party == "rider"
                else f"Award the S${fee_claim:.2f} cleaning fee."
            )
        return "Rule in favour of this party."


# ---------------------------------------------------------------------------
# Adjudication rules (explicit, reviewable, type-specific)
# ---------------------------------------------------------------------------


def _judge_no_show(case: DisputeCase, packet: EvidencePacket) -> Ruling:
    policy = case.cancellation_policy
    fee = case.trip_data.cancellation_fee or policy.cancellation_fee_after_wait if policy else (
        case.trip_data.cancellation_fee or 0.0
    )
    threshold = policy.no_show_threshold_min if policy else 8.0
    free_wait = policy.free_wait_time_min if policy else 5.0

    arrived = _fact(packet, "driver_arrival_time") is not None
    waited = _num(packet, "driver_wait_minutes")
    attempts = _num(packet, "driver_contact_attempts")
    rider_replies = _num(packet, "rider_responses")
    rider_flags = case.rider_profile.fraud_flags if case.rider_profile else 0
    driver_flags = case.driver_profile.fraud_flags if case.driver_profile else 0

    merit = 0.0
    merit += 0.35 if arrived else -0.30
    if waited >= threshold:
        merit += 0.35
    elif waited >= free_wait:
        merit += 0.15
    else:
        merit -= 0.20
    merit += 0.15 if attempts >= 1 else -0.15
    merit += 0.15 if rider_replies == 0 else -0.05
    merit += 0.05 if rider_flags else 0.0
    merit -= 0.15 if driver_flags else 0.0
    fee_matches = any(c.ref == "CANCEL-5" and c.compliant for c in packet.policy_checks)
    merit += 0.05 if fee_matches else -0.20

    findings = [
        f"Driver arrival {'confirmed by GPS' if arrived else 'not evidenced'}.",
        f"Driver waited {waited:g} min on site against a {threshold:g} min no-show threshold.",
        f"Driver made {attempts:g} contact attempt(s); rider replied {rider_replies:g} time(s).",
    ]
    if rider_flags:
        findings.append(f"Rider carries {rider_flags} fraud flag(s) on their account.")

    if merit >= 0.75:
        decision, amount = Decision.UPHOLD_CHARGE, 0.0
    elif merit >= 0.35:
        decision, amount = Decision.PARTIAL_REFUND, round(fee / 2, 2)
    elif merit >= 0.0:
        decision, amount = Decision.REFUND_RIDER, round(fee, 2)
    else:
        decision, amount = Decision.REFUND_RIDER, round(fee, 2)

    confidence = _clamp(0.55 + 0.30 * merit - (0.08 if len(packet.facts) < 5 else 0.0))

    reasoning = {
        Decision.UPHOLD_CHARGE: (
            f"The driver's GPS places them within the pickup radius from the moment of arrival, and "
            f"they remained stationary for {waited:g} minutes — clearing both the {free_wait:g} minute "
            f"free-wait period and the {threshold:g} minute no-show threshold. They made "
            f"{attempts:g} attempts to contact the rider and received no reply. Every cancellation "
            f"policy clause was satisfied, so the S${fee:.2f} charge stands."
        ),
        Decision.PARTIAL_REFUND: (
            f"The driver met part of the cancellation procedure but the evidence does not fully "
            f"support the no-show threshold of {threshold:g} minutes (observed wait {waited:g} minutes). "
            f"The charge is therefore split — S${amount:.2f} refunded to the rider."
        ),
        Decision.REFUND_RIDER: (
            f"The evidence does not establish that the driver completed the no-show procedure: wait "
            f"time was {waited:g} minutes against a required {threshold:g} minutes"
            + ("" if arrived else ", and arrival at the pickup point is not evidenced")
            + f". The S${fee:.2f} cancellation charge is reversed in full."
        ),
    }[decision]

    return Ruling(
        dispute_id=case.dispute_id,
        decision=decision,
        amount=amount,
        confidence=confidence,
        reasoning=reasoning,
        key_findings=findings,
        policy_applied=[c.ref for c in packet.policy_checks],
        rider_summary={
            Decision.UPHOLD_CHARGE: (
                "Our review found the driver was at your pickup point on time and waited the full "
                "grace period while trying to reach you. The cancellation fee stands."
            ),
            Decision.PARTIAL_REFUND: (
                f"We found the driver met only part of the required no-show procedure, so "
                f"S${amount:.2f} of the S${fee:.2f} charge has been refunded."
            ),
            Decision.REFUND_RIDER: (
                f"The driver did not complete the required no-show procedure, so your S${fee:.2f} "
                "cancellation charge has been reversed in full."
            ),
        }[decision],
        driver_summary={
            Decision.UPHOLD_CHARGE: (
                "Your GPS, wait time and call log fully satisfied the no-show policy. The "
                f"S${fee:.2f} cancellation fee is upheld as compensation."
            ),
            Decision.PARTIAL_REFUND: (
                f"Only part of the no-show procedure was evidenced, so S${amount:.2f} of the fee "
                "was refunded to the rider."
            ),
            Decision.REFUND_RIDER: (
                "The telemetry did not evidence the full no-show procedure, so the cancellation fee "
                "was reversed. Please ensure the wait timer runs its full course before cancelling."
            ),
        }[decision],
    )


def _judge_route_deviation(case: DisputeCase, packet: EvidencePacket) -> Ruling:
    deviation = _num(packet, "route_deviation_pct")
    overcharge = _num(packet, "fare_variance")
    stops = int(_num(packet, "unexplained_stops"))
    overrun = _num(packet, "duration_overrun_min")
    explained = _fact(packet, "driver_explanation") is not None and _fact(
        packet, "driver_explanation"
    ).value not in (None, "None provided")
    traffic = _fact(packet, "traffic_evidence") is not None
    est_duration = case.trip_data.estimated_duration_min or 0.0

    merit = 0.0
    if deviation > 30:
        merit += 0.50
    elif deviation > 15:
        merit += 0.35
    merit += min(stops, 2) * 0.10
    merit += 0.20 if overcharge > 0 else -0.10
    merit += 0.10 if est_duration and overrun > est_duration * 0.25 else 0.0
    merit += 0.0 if explained else 0.15
    merit -= 0.10 if explained else 0.0
    merit -= 0.25 if traffic else 0.0

    justified_ratio = 0.30 if traffic else 0.15
    refund = round(max(overcharge, 0.0) * (1 - justified_ratio), 2)

    findings = [
        f"Route deviation of {deviation:g}% against a 15% tolerance.",
        f"{stops} unexplained stop(s) detected away from pickup and dropoff.",
        f"Fare overcharge of S${overcharge:.2f} versus the estimate."
        if overcharge > 0
        else "Fare charged is within the estimate.",
        "External congestion was recorded on the corridor." if traffic else
        "No external congestion evidence was recorded.",
    ]

    if merit >= 0.80 and not traffic:
        decision, amount = Decision.REFUND_RIDER, round(max(overcharge, 0.0), 2)
    elif merit >= 0.35:
        decision, amount = Decision.PARTIAL_REFUND, refund
    else:
        decision, amount = Decision.UPHOLD_CHARGE, 0.0

    confidence = _clamp(0.55 + 0.30 * merit)

    reasoning = {
        Decision.REFUND_RIDER: (
            f"The GPS trace shows the driven route exceeded the optimal route by {deviation:g}%, with "
            f"{stops} stop(s) that neither the pickup nor the dropoff explains. The driver offered no "
            f"valid justification and no congestion was recorded, so the S${amount:.2f} overcharge is "
            "refunded in full."
        ),
        Decision.PARTIAL_REFUND: (
            f"The route exceeded the optimal distance by {deviation:g}% and the fare by "
            f"S${overcharge:.2f}, which the rider did not agree to. However, independent congestion "
            f"data confirms traffic on the corridor, which legitimately accounts for roughly "
            f"{int(justified_ratio * 100)}% of the excess. The remaining S${amount:.2f} is refunded "
            "to the rider, and the balance of the fare stands."
        ),
        Decision.UPHOLD_CHARGE: (
            f"The deviation of {deviation:g}% falls within operational tolerance and is explained by "
            "recorded traffic conditions, so the fare as charged is upheld."
        ),
    }[decision]

    return Ruling(
        dispute_id=case.dispute_id,
        decision=decision,
        amount=amount,
        confidence=confidence,
        reasoning=reasoning,
        key_findings=findings,
        policy_applied=[c.ref for c in packet.policy_checks],
        rider_summary={
            Decision.REFUND_RIDER: (
                f"The detour was not justified, so S${amount:.2f} of overcharge has been refunded."
            ),
            Decision.PARTIAL_REFUND: (
                f"Part of the detour was caused by verified traffic. S${amount:.2f} has been "
                "refunded to you and the remaining fare stands."
            ),
            Decision.UPHOLD_CHARGE: "The route taken was reasonable and the fare stands.",
        }[decision],
        driver_summary={
            Decision.REFUND_RIDER: (
                f"A {deviation:g}% detour without rider agreement or traffic justification is not "
                f"chargeable; S${amount:.2f} was refunded to the rider."
            ),
            Decision.PARTIAL_REFUND: (
                f"Traffic justified part of the detour, so only S${amount:.2f} was refunded. In "
                "future, confirm detours with the rider in chat."
            ),
            Decision.UPHOLD_CHARGE: "Your routing was reasonable; the fare stands as charged.",
        }[decision],
    )


def _judge_property_damage(
    case: DisputeCase, packet: EvidencePacket, vision: Sequence[VisionFinding]
) -> Ruling:
    fee_claim = case.trip_data.cleaning_fee_claimed or 0.0
    admissible = [v for v in vision if v.genuine]
    rejected = [v for v in vision if not v.genuine]

    severity_ok = any(v.severity in {"liquid_spill", "major_damage"} for v in admissible)
    severity_mid = any(v.severity == "minor_mess" for v in admissible)

    findings = [
        f"Cleaning fee claimed: S${fee_claim:.2f}.",
        f"{len(admissible)} of {len(vision)} submitted photo(s) passed forensic validation."
        if vision
        else "No photo evidence was submitted with the claim.",
    ]
    for v in rejected:
        findings.extend(f"Rejected photo {v.attachment_id}: {a}" for a in v.anomalies[:2])

    policy_applied = [c.ref for c in packet.policy_checks]

    if admissible and severity_ok:
        decision = Decision.COMPENSATE_DRIVER
        amount = round(min(fee_claim, 80.0), 2)
        confidence = 0.82
        reasoning = (
            "The submitted photo passed forensic validation — its EXIF timestamp sits within the "
            f"trip window and it cleared the synthetic-media screen — and the vision agent classified "
            f"the cabin condition as '{admissible[0].severity}'. The cleaning claim is therefore "
            f"supported by admissible evidence and S${amount:.2f} is awarded to the driver."
        )
        rider_summary = (
            f"The cleaning evidence was verified, so S${amount:.2f} has been charged to your account."
        )
        driver_summary = f"Your verified cleaning claim is approved — S${amount:.2f} awarded."
    elif admissible and severity_mid:
        decision = Decision.PARTIAL_REFUND
        amount = round(fee_claim * 0.5, 2)
        confidence = 0.70
        reasoning = (
            "The photo is admissible but the condition it shows amounts to ordinary mess rather than "
            "a spill requiring professional cleaning. The claim is therefore halved, and the rider "
            f"is charged S${amount:.2f} rather than the full S${fee_claim:.2f}."
        )
        rider_summary = (
            f"The mess was judged ordinary rather than a spill, so the fee was reduced to S${amount:.2f}."
        )
        driver_summary = (
            f"Only ordinary mess was evidenced, so the claim was reduced to S${amount:.2f}."
        )
    else:
        decision = Decision.NO_ACTION
        amount = 0.0
        confidence = 0.85
        if rejected:
            detail = ". ".join(a.rstrip(".") for v in rejected for a in v.anomalies[:2]) + "."
        else:
            detail = "No admissible photo evidence was submitted at all."
        reasoning = (
            "The cleaning claim rests on photo evidence that failed forensic validation. "
            f"{detail} Under policy DAMAGE-1/DAMAGE-2 the claim cannot succeed, so the "
            f"S${fee_claim:.2f} cleaning fee is waived and not charged to the rider."
        )
        rider_summary = (
            "The cleaning evidence did not pass verification, so no cleaning fee has been charged "
            "to you."
        )
        driver_summary = (
            "Your photo did not pass forensic validation, so the cleaning fee cannot be charged. "
            "Submit photos taken at the time of the trip."
        )

    escalated = bool(rejected)
    escalation_reason = None
    if escalated:
        escalation_reason = (
            "Submitted photo evidence failed forensic validation — referred to Fraud & Safety for "
            "review of the claim."
        )

    return Ruling(
        dispute_id=case.dispute_id,
        decision=decision,
        amount=amount,
        confidence=confidence,
        reasoning=reasoning,
        key_findings=findings,
        policy_applied=policy_applied,
        rider_summary=rider_summary,
        driver_summary=driver_summary,
        escalated=escalated,
        escalation_reason=escalation_reason,
    )


def _judge_generic(case: DisputeCase, packet: EvidencePacket) -> Ruling:
    rider_facts = len(packet.facts_for("rider"))
    driver_facts = len(packet.facts_for("driver"))
    decision = Decision.NO_ACTION if rider_facts == driver_facts else (
        Decision.REFUND_RIDER if rider_facts > driver_facts else Decision.UPHOLD_CHARGE
    )
    return Ruling(
        dispute_id=case.dispute_id,
        decision=decision,
        amount=0.0,
        confidence=0.5,
        reasoning=(
            "This dispute category has no dedicated adjudication rule yet, so a provisional ruling "
            f"was issued by weighing the balance of verified facts ({rider_facts} rider vs "
            f"{driver_facts} driver). Human review is recommended."
        ),
        key_findings=[packet.summary],
        policy_applied=[],
        rider_summary="A provisional ruling has been issued pending human review.",
        driver_summary="A provisional ruling has been issued pending human review.",
        escalated=True,
        escalation_reason="Dispute category has no dedicated adjudication rule.",
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_provider(settings: Settings) -> LLMProvider:
    """Pick the reasoning backend according to configuration and availability."""
    if settings.engine_mode == "offline":
        return OfflineReasoner(settings)
    if settings.engine_mode == "adp":
        return ADPClient(settings)  # raises ADPNotConfigured if no key
    if settings.adp_configured:
        return ADPClient(settings)
    return OfflineReasoner(settings)
