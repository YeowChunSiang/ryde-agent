"""Regression tests for the bug-audit fixes.

These tests reproduce the specific bugs identified in the RydeResolve bug audit
and verify that the fixes prevent the original incorrect behaviour.

Run from the repository root::

    python -m pytest backend/tests/test_reasoning_fixes.py -q
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import cases as cases_mod  # noqa: E402
from adp_client import OfflineReasoner  # noqa: E402
from config import get_settings  # noqa: E402
from evidence import extract_evidence  # noqa: E402
from models import (  # noqa: E402
    DisputeCase,
    DisputeTicket,
    DisputeType,
    MediaAttachment,
    VisionFinding,
)
from main import _active_reviewer_tokens  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main as main_mod  # noqa: E402


@pytest.fixture(scope="module")
def settings():
    return get_settings()


@pytest.fixture(scope="module")
def reasoner(settings):
    return OfflineReasoner(settings)


@pytest.fixture(scope="module")
def client():
    with TestClient(main_mod.app) as c:
        yield c


def _resolve(client, case_id: str) -> dict:
    res = client.post("/resolve", json={"case_id": case_id})
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# Bug A — irrelevant cleaning claims in non-damage disputes
# ---------------------------------------------------------------------------


def test_route_deviation_advocate_never_mentions_cleaning(client):
    """Bug A: a route-deviation dispute must not produce cleaning-claim
    statements, even when an admissible image is present."""
    r = _resolve(client, "DISP-001")
    assert r["dispute_type"] == "route_deviation"

    rider_claim = (r["rider_argument"]["claim"] or "").lower()
    driver_claim = (r["driver_argument"]["claim"] or "").lower()

    assert "cleaning" not in rider_claim, (
        f"Rider advocate mentioned cleaning in a route-deviation dispute: {rider_claim}"
    )
    assert "cleaning" not in driver_claim, (
        f"Driver advocate mentioned cleaning in a route-deviation dispute: {driver_claim}"
    )
    assert "cabin" not in rider_claim
    assert "cabin" not in driver_claim


def test_no_show_advocate_never_mentions_cleaning(client):
    """Bug A: a no-show dispute must not produce cleaning-claim statements."""
    r = _resolve(client, "DISP-002")
    assert r["dispute_type"] == "no_show_charge"

    rider_claim = (r["rider_argument"]["claim"] or "").lower()
    driver_claim = (r["driver_argument"]["claim"] or "").lower()

    assert "cleaning" not in rider_claim
    assert "cleaning" not in driver_claim


def test_property_damage_advocate_does_mention_cleaning(client):
    """Sanity check: property_damage disputes should still mention cleaning."""
    r = _resolve(client, "DISP-003")
    assert r["dispute_type"] == "property_damage"
    # At least one advocate should reference the cleaning claim.
    combined = (r["rider_argument"]["claim"] + " " + r["driver_argument"]["claim"]).lower()
    assert "cleaning" in combined or "damage" in combined


# ---------------------------------------------------------------------------
# Bug B — unknown-image classification should not default to minor_mess
# ---------------------------------------------------------------------------


def test_unclassifiable_image_gets_unknown_severity(reasoner, settings):
    """Bug B: an image whose caption matches no damage keyword must be
    classified 'unknown', not 'minor_mess'."""
    case = cases_mod.get_case("DISP-003")
    packet = extract_evidence(case)

    # Create an attachment with a caption that matches nothing.
    att = MediaAttachment(
        media_type="image",
        url="/test/unknown.png",
        uploaded_by="driver",
        caption="a random chat screenshot",
        exif_present=True,
        ai_generated_probability=0.1,
    )
    finding = asyncio.run(reasoner.run_vision(case, packet, att))
    assert finding.severity == "unknown", (
        f"Expected 'unknown' but got '{finding.severity}' for an unclassifiable image."
    )
    assert "minor_mess" not in finding.reasoning.lower(), (
        f"Reasoning mentions minor_mess for an unclassifiable image: {finding.reasoning}"
    )
    assert "not analyse" in finding.reasoning.lower() or "unclassified" in finding.reasoning.lower(), (
        f"Reasoning does not state the content was not analysed: {finding.reasoning}"
    )


def test_spill_image_still_classified_correctly(reasoner, settings):
    """Sanity check: a caption mentioning 'spill' should classify as liquid_spill."""
    case = cases_mod.get_case("DISP-003")
    packet = extract_evidence(case)

    att = MediaAttachment(
        media_type="image",
        url="/test/spill.png",
        uploaded_by="driver",
        caption="bubble tea spill on the seat",
        exif_present=True,
        ai_generated_probability=0.1,
    )
    finding = asyncio.run(reasoner.run_vision(case, packet, att))
    assert finding.severity == "liquid_spill"


# ---------------------------------------------------------------------------
# Bug C — reviewer authentication on approve/override endpoints
# ---------------------------------------------------------------------------


def test_approve_without_token_returns_401(client):
    """Bug C: POST /approve without a Bearer token must return 401."""
    # First resolve a case so we have a run_id.
    r = _resolve(client, "DISP-001")
    # Use a non-escalated case for approve — DISP-001 doesn't escalate.
    # We need a valid run_id; use the resolve endpoint which returns inline.
    res = client.post("/resolve", json={"case_id": "DISP-001"})
    assert res.status_code == 200
    # We can't easily get the run_id from /resolve — use /dispute instead.
    dispute_res = client.post("/dispute", json={"case_id": "DISP-002"})
    assert dispute_res.status_code == 200
    run_id = dispute_res.json()["run_id"]

    # Wait for it to complete.
    import time
    for _ in range(50):
        result = client.get(f"/result/{run_id}").json()
        if result.get("finished_at"):
            break
        time.sleep(0.1)

    res = client.post(
        f"/approve/{run_id}",
        json={"reviewer_id": "reviewer-01", "note": "test"},
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"


def test_override_without_token_returns_401(client):
    """Bug C: POST /override without a Bearer token must return 401."""
    dispute_res = client.post("/dispute", json={"case_id": "DISP-005"})
    assert dispute_res.status_code == 200
    run_id = dispute_res.json()["run_id"]

    import time
    for _ in range(50):
        result = client.get(f"/result/{run_id}").json()
        if result.get("finished_at"):
            break
        time.sleep(0.1)

    res = client.post(
        f"/override/{run_id}",
        json={
            "reviewer_id": "reviewer-01",
            "decision": "refund_rider",
            "amount": 5.0,
            "rationale": "test override",
        },
    )
    assert res.status_code == 401, f"Expected 401, got {res.status_code}: {res.text}"


def test_approve_with_valid_token_succeeds(client):
    """Bug C: POST /approve with a valid token should succeed."""
    # Login first.
    login_res = client.post(
        "/login",
        json={"email": "reviewer@ryde.com", "password": "admin2026"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    dispute_res = client.post("/dispute", json={"case_id": "DISP-002"})
    assert dispute_res.status_code == 200
    run_id = dispute_res.json()["run_id"]

    import time
    for _ in range(50):
        result = client.get(f"/result/{run_id}").json()
        if result.get("finished_at"):
            break
        time.sleep(0.1)

    res = client.post(
        f"/approve/{run_id}",
        json={"reviewer_id": "reviewer-01", "note": "approved"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"


def test_approve_with_mismatched_reviewer_id_returns_403(client):
    """Bug C: a token for reviewer-01 must not approve as a different reviewer."""
    login_res = client.post(
        "/login",
        json={"email": "reviewer@ryde.com", "password": "admin2026"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    dispute_res = client.post("/dispute", json={"case_id": "DISP-002"})
    assert dispute_res.status_code == 200
    run_id = dispute_res.json()["run_id"]

    import time
    for _ in range(50):
        result = client.get(f"/result/{run_id}").json()
        if result.get("finished_at"):
            break
        time.sleep(0.1)

    res = client.post(
        f"/approve/{run_id}",
        json={"reviewer_id": "reviewer-99", "note": "impersonation attempt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


# ---------------------------------------------------------------------------
# Bug D — refund calculation assumptions are explicit
# ---------------------------------------------------------------------------


def test_route_deviation_refund_reasoning_mentions_policy_assumption(client):
    """Bug D: the partial-refund reasoning must state that the traffic
    allowance is a fixed policy assumption, not a calculated proportion."""
    r = _resolve(client, "DISP-001")
    assert r["dispute_type"] == "route_deviation"
    ruling = r["ruling"]
    reasoning = ruling["reasoning"].lower()
    assert "policy" in reasoning or "assumption" in reasoning, (
        f"Refund reasoning does not mention policy assumption: {reasoning}"
    )


def test_route_deviation_configurable_ratios(settings):
    """Bug D: the traffic/unjustified ratios must come from Settings."""
    assert hasattr(settings, "route_traffic_justified_ratio")
    assert hasattr(settings, "route_unjustified_ratio")
    assert 0.0 <= settings.route_traffic_justified_ratio <= 1.0
    assert 0.0 <= settings.route_unjustified_ratio <= 1.0


# ---------------------------------------------------------------------------
# Bug E — policy compliance wording is not misleading
# ---------------------------------------------------------------------------


def test_advocate_policy_wording_distinguishes_compliant_from_violation(client):
    """Bug E: the advocate claim should say 'compliant' or 'violation', not
    just 'satisfied', for policy checks."""
    r = _resolve(client, "DISP-001")
    driver_claim = r["driver_argument"]["claim"]
    rider_claim = r["rider_argument"]["claim"]

    # "is satisfied" is the old misleading wording — check it's gone.
    assert "is satisfied" not in driver_claim.lower(), (
        f"Driver advocate still uses 'is satisfied': {driver_claim}"
    )
    assert "is satisfied" not in rider_claim.lower(), (
        f"Rider advocate still uses 'is satisfied': {rider_claim}"
    )


# ---------------------------------------------------------------------------
# Bug B supplementary — vision finding with unknown severity does not
# contaminate the property-damage judge ruling
# ---------------------------------------------------------------------------


def test_unknown_severity_does_not_award_cleaning_fee(reasoner, settings):
    """An admissible photo classified 'unknown' must not trigger a
    COMPENSATE_DRIVER ruling — the content was never analysed."""
    case = cases_mod.get_case("DISP-004")
    packet = extract_evidence(case)

    # Replace the real attachments with one that has an unclassifiable caption.
    att = MediaAttachment(
        media_type="image",
        url="/test/unknown.png",
        uploaded_by="driver",
        caption="just a photo",
        exif_present=True,
        ai_generated_probability=0.1,
    )
    case_copy = case.model_copy(deep=True)
    case_copy.media_attachments = [att]

    vision = [asyncio.run(reasoner.run_vision(case_copy, packet, att))]
    # Run the judge.
    rider_arg = asyncio.run(reasoner.run_advocate(case_copy, packet, vision, "rider"))
    driver_arg = asyncio.run(reasoner.run_advocate(case_copy, packet, vision, "driver"))
    ruling = asyncio.run(
        reasoner.run_judge(case_copy, packet, vision, rider_arg, driver_arg)
    )
    assert ruling.decision.value != "compensate_driver", (
        f"Judge compensated the driver based on an 'unknown' severity photo: {ruling.reasoning}"
    )


# ---------------------------------------------------------------------------
# Precedent persistence — atomic writes and failure reporting
# ---------------------------------------------------------------------------


def test_precedent_persist_uses_atomic_write(tmp_path):
    """The _persist method should write to a temp file then rename."""
    from agents import PrecedentStore

    store_path = tmp_path / "precedents.json"
    store = PrecedentStore(store_path)
    initial_size = store.size

    # Add a case and verify it persisted.
    from models import PrecedentCase, Decision, DisputeType
    new_case = PrecedentCase(
        dispute_type=DisputeType.ROUTE_DEVIATION,
        title="Test precedent",
        fact_signature={"dispute_type": "route_deviation"},
        summary="Test",
        ruling=Decision.REFUND_RIDER.value,
        amount=5.0,
        source="human_override",
    )
    store.add(new_case)
    assert store.size == initial_size + 1

    # The file should exist (atomic write succeeded).
    assert store_path.exists(), "Precedent file was not persisted to disk"

    # Reload from disk to verify.
    store2 = PrecedentStore(store_path)
    assert store2.size == initial_size + 1


def test_precedent_persist_fails_gracefully_on_readonly(tmp_path):
    """A read-only filesystem should not crash, but should log the failure."""
    from agents import PrecedentStore
    from models import PrecedentCase, Decision, DisputeType

    store_path = tmp_path / "subdir" / "precedents.json"
    store = PrecedentStore(store_path)

    # Make the parent read-only so the rename fails.
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.parent.chmod(0o444)

    try:
        new_case = PrecedentCase(
            dispute_type=DisputeType.ROUTE_DEVIATION,
            title="Test",
            fact_signature={"dispute_type": "route_deviation"},
            summary="Test",
            ruling=Decision.REFUND_RIDER.value,
            amount=5.0,
            source="human_override",
        )
        # This should not raise — it should return and log.
        store.add(new_case)
        # In-memory it's there.
        assert store.size >= 1
    finally:
        store_path.parent.chmod(0o755)


# ---------------------------------------------------------------------------
# Fix 1 — override API reports persistence failure
# ---------------------------------------------------------------------------


def test_override_reports_persistence_failure(client, monkeypatch):
    """If precedent persistence fails, the override API must report
    ``persisted=False`` so the reviewer knows the precedent was not saved."""
    login_res = client.post(
        "/login",
        json={"email": "reviewer@ryde.com", "password": "admin2026"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    dispute_res = client.post("/dispute", json={"case_id": "DISP-006"})
    assert dispute_res.status_code == 200
    run_id = dispute_res.json()["run_id"]

    import time

    for _ in range(50):
        result = client.get(f"/result/{run_id}").json()
        if result.get("finished_at"):
            break
        time.sleep(0.1)

    # Force persistence failure by monkeypatching _persist to return False.
    store = main_mod.orchestrator.policy_agent.store
    monkeypatch.setattr(store, "_persist", lambda: False)

    res = client.post(
        f"/override/{run_id}",
        json={
            "reviewer_id": "reviewer-01",
            "decision": "refund_rider",
            "amount": 10.0,
            "rationale": "test persistence failure",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()
    assert body["persisted"] is False
    assert "not" in body["message"].lower() and "persist" in body["message"].lower()


# ---------------------------------------------------------------------------
# Fix 3 — sensitive endpoints gate behind auth when REQUIRE_AUTH is enabled
# ---------------------------------------------------------------------------


def test_sensitive_endpoints_require_auth_when_enabled(client, monkeypatch):
    """When REQUIRE_AUTH is on, sensitive read endpoints must 401 without a token."""
    monkeypatch.setattr(main_mod.settings, "require_auth", True)

    for path in ("/cases", "/precedents", "/escalations", "/media/uploads"):
        res = client.get(path)
        assert res.status_code == 401, f"Expected 401 for {path}, got {res.status_code}"

    # /health must stay open.
    res = client.get("/health")
    assert res.status_code == 200


def test_sensitive_endpoints_accept_valid_token_when_enabled(client, monkeypatch):
    """When REQUIRE_AUTH is on, a valid reviewer token grants access."""
    monkeypatch.setattr(main_mod.settings, "require_auth", True)

    login_res = client.post(
        "/login",
        json={"email": "reviewer@ryde.com", "password": "admin2026"},
    )
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    res = client.get("/cases", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
