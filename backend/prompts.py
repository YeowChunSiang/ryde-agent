"""System prompts and prompt builders for the RydeResolve agent pipeline.

Each agent is pinned to a strict JSON output contract so the orchestrator can
parse, validate and stream its output without brittle regex scraping. The
contracts are declared once here and reused by both the ADP-backed client and
the offline reasoner, guaranteeing identical shapes in either engine mode.
"""

from __future__ import annotations

import json
from typing import Sequence

from models import (
    AdvocateArgument,
    DisputeCase,
    EvidencePacket,
    Fact,
    MediaAttachment,
    PolicyCheck,
    VisionFinding,
)

# ---------------------------------------------------------------------------
# Agent system prompts
# ---------------------------------------------------------------------------

IMAGE_ANALYSIS_SYSTEM = (
    "You are an expert forensic anomaly detection AI. Analyze this vehicle cabin photo. "
    "Verify if the image is genuine and not AI-generated. Cross-reference the EXIF timestamp "
    "against the trip timestamp. Classify the mess severity (e.g., normal wear-and-tear vs. "
    "liquid spill). Output your findings as strict JSON."
)

RIDER_ADVOCATE_SYSTEM = (
    "You are the Rider Advocate Agent. Review the GPS telemetry, chat logs, and any vision agent "
    "findings. Articulate the rider's claim based on company policy, heavily weighting factors like "
    "driver no-shows, route deviations, and wait times. Argue for a rider-favorable outcome."
)

DRIVER_ADVOCATE_SYSTEM = (
    "You are the Driver Advocate Agent. Gather driver-side evidence from the telemetry and chat logs. "
    "Defend the driver based on policy, highlighting the driver's arrival time, wait duration, and "
    "communication attempts. Argue for a driver-favorable outcome."
)

JUDGE_SYSTEM = (
    "You are the impartial Judge Agent. Weigh the evidence presented by the Rider Advocate and Driver "
    "Advocate. Apply company policy strictly. You must issue a final ruling containing a decision "
    "(e.g., refund, compensation, upheld), a confidence score, and a natural language explanation of "
    "your reasoning. Output strictly in JSON format."
)

SYSTEM_PROMPTS = {
    "vision": IMAGE_ANALYSIS_SYSTEM,
    "rider_advocate": RIDER_ADVOCATE_SYSTEM,
    "driver_advocate": DRIVER_ADVOCATE_SYSTEM,
    "judge": JUDGE_SYSTEM,
}

# ---------------------------------------------------------------------------
# JSON output contracts
# ---------------------------------------------------------------------------

VISION_JSON_CONTRACT = {
    "attachment_id": "string",
    "genuine": "boolean",
    "authenticity_confidence": "number 0..1",
    "ai_generated_probability": "number 0..1",
    "exif_timestamp_delta_min": "number (signed minutes from trip end; null if unknown)",
    "severity": "one of: none | normal_wear | minor_mess | liquid_spill | major_damage",
    "anomalies": ["string"],
    "reasoning": "string (2-4 sentences)",
}

ADVOCATE_JSON_CONTRACT = {
    "headline": "string (<= 12 words)",
    "claim": "string (the full argument, 3-6 sentences)",
    "cited_facts": ["fact keys you relied on"],
    "policy_refs": ["policy clause ids, e.g. CANCEL-2"],
    "requested_outcome": "string (what you want the judge to order)",
    "confidence": "number 0..1",
    "weaknesses": ["honest weaknesses in your own case (required — you are not a propagandist)"],
}

JUDGE_JSON_CONTRACT = {
    "decision": "one of: refund_rider | partial_refund | uphold_charge | compensate_driver | no_action | escalate_to_human",
    "amount": "number (SGD to refund or compensate; 0 if none)",
    "confidence": "number 0..1",
    "reasoning": "string (4-8 sentences of natural language reasoning)",
    "key_findings": ["string"],
    "policy_applied": ["policy clause ids"],
    "rider_summary": "string (1-2 sentences written to the rider)",
    "driver_summary": "string (1-2 sentences written to the driver)",
}

_JSON_RULE = (
    "Respond with a single JSON object only — no markdown fences, no prose before or after. "
    "Never invent facts that are not present in the evidence block; cite fact keys instead."
)


# ---------------------------------------------------------------------------
# Evidence rendering
# ---------------------------------------------------------------------------


def _render_fact(fact: Fact) -> str:
    unit = f" {fact.unit}" if fact.unit else ""
    note = f" — {fact.note}" if fact.note else ""
    return f"- [{fact.key}] ({fact.supports}/{fact.source}) {fact.label}: {fact.value}{unit}{note}"


def _render_check(check: PolicyCheck) -> str:
    flag = "PASS" if check.compliant else "FAIL"
    return (
        f"- [{check.ref}] {flag} ({check.supports}) {check.description}: "
        f"expected {check.expected}, observed {check.actual}"
    )


def render_evidence(packet: EvidencePacket) -> str:
    """Flatten an evidence packet into a compact, citation-friendly text block."""
    lines: list[str] = ["## VERIFIED FACTS (computed deterministically — do not recompute)"]
    lines += [_render_fact(f) for f in packet.facts] or ["- none"]

    lines.append("\n## POLICY COMPLIANCE CHECKS")
    lines += [_render_check(c) for c in packet.policy_checks] or ["- none"]

    if packet.risk_signals:
        lines.append("\n## BEHAVIOURAL RISK SIGNALS")
        lines += [
            f"- ({s.party}/{s.severity}) {s.signal}: {s.detail}" for s in packet.risk_signals
        ]

    return "\n".join(lines)


def _render_case_context(case: DisputeCase) -> str:
    ticket = case.dispute_ticket
    trip = case.trip_data
    lines = [
        "## DISPUTE",
        f"- id: {ticket.dispute_id} (trip {ticket.trip_id})",
        f"- type: {ticket.dispute_type.value}",
        f"- filed_by: {ticket.filed_by} at {ticket.filed_at.isoformat()}",
        f"- rider statement: {ticket.description.strip()}",
    ]
    if case.rider_profile:
        r = case.rider_profile
        lines.append(
            f"- rider: {r.name} ({r.rider_id}), {r.total_trips} trips, "
            f"rating {r.avg_rating}, disputes {r.dispute_history.total_disputes} "
            f"({r.dispute_history.rejected} rejected), fraud flags {r.fraud_flags}"
        )
    if case.driver_profile:
        d = case.driver_profile
        lines.append(
            f"- driver: {d.name} ({d.driver_id}), {d.total_trips} trips, "
            f"rating {d.avg_rating}, disputes against {d.dispute_history.upheld_count}, "
            f"fraud flags {d.fraud_flags}"
        )
    if trip.pickup_location:
        lines.append(
            f"- route: {trip.pickup_location.name or 'pickup'} -> "
            f"{trip.dropoff_location.name if trip.dropoff_location else 'dropoff'}"
        )
    if trip.cancellation_fee is not None:
        lines.append(f"- disputed amount: S${trip.cancellation_fee:.2f}")
    if trip.fare_charged is not None:
        lines.append(
            f"- fare: S${trip.fare_charged:.2f} charged vs S${trip.fare_estimate or 0:.2f} estimated"
        )
    if trip.cleaning_fee_claimed is not None:
        lines.append(f"- cleaning fee claimed: S${trip.cleaning_fee_claimed:.2f}")
    return "\n".join(lines)


def _render_chat(case: DisputeCase) -> str:
    if not case.chat_logs:
        return "## CHAT LOG\n- (empty)"
    lines = ["## CHAT LOG"]
    lines += [
        f"- {m.timestamp.strftime('%H:%M')} {m.sender} [{m.type}]: {m.content}"
        for m in case.chat_logs
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_vision_prompt(case: DisputeCase, attachment: MediaAttachment) -> str:
    trip = case.trip_data
    return "\n".join(
        [
            _render_case_context(case),
            "\n## MEDIA UNDER ANALYSIS",
            f"- attachment_id: {attachment.attachment_id}",
            f"- url: {attachment.url}",
            f"- uploaded_by: {attachment.uploaded_by}",
            f"- exif_captured_at: {attachment.captured_at.isoformat() if attachment.captured_at else 'missing'}",
            f"- exif_present: {attachment.exif_present}",
            f"- device: {attachment.device_model or 'unknown'}",
            f"- heuristic ai_generated_probability: {attachment.ai_generated_probability}",
            f"- caption/claim: {attachment.caption or 'n/a'}",
            f"- trip_end: {trip.trip_end_time.isoformat() if trip.trip_end_time else 'n/a'}",
            "\n## OUTPUT CONTRACT",
            json.dumps(VISION_JSON_CONTRACT, indent=2),
            _JSON_RULE,
        ]
    )


def build_advocate_prompt(
    case: DisputeCase,
    packet: EvidencePacket,
    vision: Sequence[VisionFinding],
    party: str,
) -> str:
    parts = [
        _render_case_context(case),
        "",
        render_evidence(packet),
        "",
        _render_chat(case),
    ]
    if vision:
        parts.append("\n## VISION AGENT FINDINGS")
        parts += [
            f"- [{v.attachment_id}] genuine={v.genuine} severity={v.severity} "
            f"ai_prob={v.ai_generated_probability} exif_delta_min={v.exif_timestamp_delta_min} "
            f"anomalies={v.anomalies}"
            for v in vision
        ]
    parts.append(
        "\n## YOUR BRIEF\n"
        f"You represent the {party}. Build the strongest *honest* case the evidence supports. "
        "Cite fact keys and policy clause ids. You must also list at least one genuine weakness — "
        "a ruling produced from one-sided advocacy is not defensible."
    )
    parts.append("\n## OUTPUT CONTRACT")
    parts.append(json.dumps(ADVOCATE_JSON_CONTRACT, indent=2))
    parts.append(_JSON_RULE)
    return "\n".join(parts)


def build_judge_prompt(
    case: DisputeCase,
    packet: EvidencePacket,
    vision: Sequence[VisionFinding],
    rider_argument: AdvocateArgument,
    driver_argument: AdvocateArgument,
) -> str:
    parts = [
        _render_case_context(case),
        "",
        render_evidence(packet),
        "",
        "## RIDER ADVOCATE SUBMISSION",
        f"- headline: {rider_argument.headline}",
        f"- claim: {rider_argument.claim}",
        f"- cited facts: {rider_argument.cited_facts}",
        f"- policy refs: {rider_argument.policy_refs}",
        f"- requested: {rider_argument.requested_outcome}",
        f"- self-declared weaknesses: {rider_argument.weaknesses}",
        "",
        "## DRIVER ADVOCATE SUBMISSION",
        f"- headline: {driver_argument.headline}",
        f"- claim: {driver_argument.claim}",
        f"- cited facts: {driver_argument.cited_facts}",
        f"- policy refs: {driver_argument.policy_refs}",
        f"- requested: {driver_argument.requested_outcome}",
        f"- self-declared weaknesses: {driver_argument.weaknesses}",
    ]
    if vision:
        parts.append("\n## VISION AGENT FINDINGS")
        parts += [
            f"- [{v.attachment_id}] genuine={v.genuine} severity={v.severity} "
            f"ai_prob={v.ai_generated_probability} exif_delta_min={v.exif_timestamp_delta_min} "
            f"anomalies={v.anomalies} reasoning={v.reasoning}"
            for v in vision
        ]
    parts.append(
        "\n## YOUR BRIEF\n"
        "Weigh both submissions against the verified facts and the policy checks. Failed policy "
        "checks are decisive unless a stronger, evidenced counterweight exists. Set confidence to "
        "reflect how well the evidence pins down the outcome — be honest, because any ruling below "
        "0.65 is automatically escalated to a human reviewer."
    )
    parts.append("\n## OUTPUT CONTRACT")
    parts.append(json.dumps(JUDGE_JSON_CONTRACT, indent=2))
    parts.append(_JSON_RULE)
    return "\n".join(parts)
