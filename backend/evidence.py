"""Deterministic evidence extraction.

Design note (this is the architectural spine of RydeResolve):

Advocates and the judge are **never** handed the raw dispute JSON and asked to
"figure it out". Every quantitative claim is computed here in plain Python first,
so that:

* the same dossier always produces the same facts (no LLM drift),
* every fact carries a ``source`` and a ``supports`` party tag, which makes the
  ruling fully auditable — a human reviewer can replay the arithmetic,
* the system still produces correct, defensible rulings when no LLM credential
  is configured (the offline reasoner argues over these facts).

The LLM's job is rhetoric and weighing, not arithmetic.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Iterable, Optional, Sequence

from models import (
    ChatMessage,
    DisputeCase,
    EvidencePacket,
    Fact,
    GeoPoint,
    GpsPoint,
    MediaAttachment,
    PolicyCheck,
    RiskSignal,
)

# --- Tunable constants ------------------------------------------------------

EARTH_RADIUS_KM = 6371.0088
ARRIVAL_RADIUS_M = 60.0          # GPS within 60m of the pin counts as "arrived"
STOP_SPEED_KMH = 2.0             # below this the vehicle is considered parked
STOP_MIN_DURATION_MIN = 2.0      # a parked cluster shorter than this is traffic
ROAD_FACTOR = 1.30               # straight-line -> road distance proxy (Singapore)
ROUTE_TOLERANCE_PCT = 15.0       # tolerated deviation before it is "unjustified"
FARE_TOLERANCE_PCT = 10.0
EXIF_TOLERANCE_MIN = 45.0        # photo may be taken up to 45 min after trip end
AI_GENERATED_FLAG = 0.50


# --- Geometry / helpers -----------------------------------------------------


def haversine_km(a: GeoPoint, b: GeoPoint) -> float:
    """Great-circle distance between two coordinates, in kilometres."""
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _as_point(lat: float, lng: float) -> GeoPoint:
    return GeoPoint(lat=lat, lng=lng)


def distance_m(a: GeoPoint, b: GeoPoint) -> float:
    return haversine_km(a, b) * 1000.0


def minutes_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() / 60.0, 2)


def polyline_km(points: Sequence[GpsPoint]) -> float:
    """Sum of consecutive GPS hops — the distance actually driven."""
    total = 0.0
    for prev, cur in zip(points, points[1:]):
        total += haversine_km(_as_point(prev.lat, prev.lng), _as_point(cur.lat, cur.lng))
    return round(total, 3)


def _first(pred, items: Iterable):
    for item in items:
        if pred(item):
            return item
    return None


def _fmt_dt(dt: Optional[datetime]) -> str:
    return dt.strftime("%H:%M") if dt else "n/a"


# --- Communication analysis -------------------------------------------------


def _contact_stats(chat_logs: Sequence[ChatMessage]) -> dict[str, int]:
    driver_msgs = sum(1 for c in chat_logs if c.sender == "driver" and c.type == "message")
    driver_calls = sum(1 for c in chat_logs if c.sender == "driver" and c.type == "call")
    rider_msgs = sum(1 for c in chat_logs if c.sender == "rider" and c.type == "message")
    rider_calls = sum(1 for c in chat_logs if c.sender == "rider" and c.type == "call")
    return {
        "driver_messages": driver_msgs,
        "driver_calls": driver_calls,
        "driver_attempts": driver_msgs + driver_calls,
        "rider_messages": rider_msgs,
        "rider_calls": rider_calls,
        "rider_responses": rider_msgs + rider_calls,
    }


# --- Per-category analysers -------------------------------------------------


def _analyse_no_show(case: DisputeCase, packet: EvidencePacket) -> None:
    trip = case.trip_data
    policy = case.cancellation_policy
    pickup = trip.pickup_location
    logs = case.chat_logs

    # --- Arrival detection: trust GPS first, declared timestamp second -------
    gps_arrival = None
    if pickup:
        gps_arrival = _first(
            lambda p: distance_m(_as_point(p.lat, p.lng), pickup) <= ARRIVAL_RADIUS_M
            and (p.status in {"arrived", "waiting"} or p.speed_kmh <= STOP_SPEED_KMH),
            case.gps_telemetry,
        )
    declared_arrival = trip.driver_arrival_time
    arrival = gps_arrival.timestamp if gps_arrival else declared_arrival
    arrival_source = "gps_telemetry" if gps_arrival else "trip_data"

    if arrival:
        packet.facts.append(
            Fact(
                key="driver_arrival_time",
                label="Driver arrived at pickup",
                value=_fmt_dt(arrival),
                source=arrival_source,
                supports="driver",
                note="First GPS ping within 60 m of the pickup pin at ~0 km/h"
                if gps_arrival
                else "Declared arrival timestamp",
            )
        )

    scheduled = trip.scheduled_time
    if arrival and scheduled:
        delta = minutes_between(scheduled, arrival)  # negative => early
        if delta is not None:
            packet.facts.append(
                Fact(
                    key="arrival_delta_min",
                    label="Arrival vs. scheduled pickup",
                    value=delta,
                    unit="min",
                    source="trip_data",
                    supports="driver" if delta <= 0 else "rider",
                    note=f"{'Early' if delta <= 0 else 'Late'} by {abs(delta):.1f} min",
                )
            )

    # --- Waiting -------------------------------------------------------------
    wait_start = trip.driver_wait_start or arrival
    wait_end = trip.cancellation_time
    waited = minutes_between(wait_start, wait_end)
    if waited is not None:
        packet.facts.append(
            Fact(
                key="driver_wait_minutes",
                label="Driver waited on site",
                value=waited,
                unit="min",
                source="trip_data",
                supports="driver" if waited >= 5 else "rider",
            )
        )

    # --- Was the driver actually parked at the pin? ---------------------------
    if pickup and case.gps_telemetry:
        near = [
            p
            for p in case.gps_telemetry
            if distance_m(_as_point(p.lat, p.lng), pickup) <= ARRIVAL_RADIUS_M
        ]
        stationary = [p for p in near if p.speed_kmh <= STOP_SPEED_KMH]
        if near:
            packet.facts.append(
                Fact(
                    key="gps_pings_at_pickup",
                    label="GPS pings within 60 m of pickup pin",
                    value=len(near),
                    source="gps_telemetry",
                    supports="driver",
                    note=f"{len(stationary)} of them at 0 km/h (parked, not driving past)",
                )
            )
            drift = max(distance_m(_as_point(p.lat, p.lng), pickup) for p in near)
            packet.facts.append(
                Fact(
                    key="max_drift_from_pickup_m",
                    label="Max drift from pickup pin while on site",
                    value=round(drift, 1),
                    unit="m",
                    source="gps_telemetry",
                    supports="driver" if drift <= ARRIVAL_RADIUS_M else "rider",
                )
            )

    # --- Contact attempts ------------------------------------------------------
    stats = _contact_stats(logs)
    packet.facts.append(
        Fact(
            key="driver_contact_attempts",
            label="Driver contact attempts",
            value=stats["driver_attempts"],
            unit="attempts",
            source="chat_logs",
            supports="driver" if stats["driver_attempts"] > 0 else "rider",
            note=f"{stats['driver_messages']} messages, {stats['driver_calls']} calls",
        )
    )
    packet.facts.append(
        Fact(
            key="rider_responses",
            label="Rider replies in chat",
            value=stats["rider_responses"],
            unit="replies",
            source="chat_logs",
            supports="driver" if stats["rider_responses"] == 0 else "rider",
            note="Rider never responded" if stats["rider_responses"] == 0 else None,
        )
    )

    # --- Policy ---------------------------------------------------------------
    if policy:
        packet.policy_checks.append(
            PolicyCheck(
                ref="CANCEL-1",
                description="Driver must reach the pickup point",
                expected="GPS within 60 m of pin at 0 km/h",
                actual="Confirmed" if arrival else "Not evidenced",
                compliant=bool(arrival),
                supports="driver" if arrival else "rider",
            )
        )
        if waited is not None:
            packet.policy_checks.append(
                PolicyCheck(
                    ref="CANCEL-2",
                    description=f"Free wait period of {policy.free_wait_time_min:g} min must elapse",
                    expected=f">= {policy.free_wait_time_min:g} min",
                    actual=f"{waited:g} min",
                    compliant=waited >= policy.free_wait_time_min,
                    supports="driver" if waited >= policy.free_wait_time_min else "rider",
                )
            )
            packet.policy_checks.append(
                PolicyCheck(
                    ref="CANCEL-3",
                    description=f"No-show fee only after {policy.no_show_threshold_min:g} min on site",
                    expected=f">= {policy.no_show_threshold_min:g} min",
                    actual=f"{waited:g} min",
                    compliant=waited >= policy.no_show_threshold_min,
                    supports="driver" if waited >= policy.no_show_threshold_min else "rider",
                )
            )
        packet.policy_checks.append(
            PolicyCheck(
                ref="CANCEL-4",
                description="Driver must attempt to contact the rider before cancelling",
                expected=">= 1 attempt",
                actual=f"{stats['driver_attempts']} attempts",
                compliant=stats["driver_attempts"] >= 1,
                supports="driver" if stats["driver_attempts"] >= 1 else "rider",
            )
        )
        fee = trip.cancellation_fee
        if fee is not None:
            packet.policy_checks.append(
                PolicyCheck(
                    ref="CANCEL-5",
                    description="Charged fee must match the published cancellation fee",
                    expected=f"S${policy.cancellation_fee_after_wait:.2f}",
                    actual=f"S${fee:.2f}",
                    compliant=abs(fee - policy.cancellation_fee_after_wait) < 0.01,
                    supports="driver"
                    if abs(fee - policy.cancellation_fee_after_wait) < 0.01
                    else "rider",
                )
            )


def _analyse_route_deviation(case: DisputeCase, packet: EvidencePacket) -> None:
    trip = case.trip_data
    pickup, dropoff = trip.pickup_location, trip.dropoff_location

    gps_dist = polyline_km(case.gps_telemetry) if case.gps_telemetry else None
    declared = trip.actual_distance_km
    baseline = trip.estimated_distance_km
    if baseline is None and pickup and dropoff:
        baseline = round(haversine_km(pickup, dropoff) * ROAD_FACTOR, 2)

    actual = declared if declared is not None else gps_dist

    if gps_dist is not None:
        packet.facts.append(
            Fact(
                key="gps_distance_km",
                label="Distance driven (summed from GPS trace)",
                value=gps_dist,
                unit="km",
                source="gps_telemetry",
                supports="rider",
            )
        )
    if declared is not None:
        packet.facts.append(
            Fact(
                key="declared_distance_km",
                label="Distance driven (declared by platform)",
                value=declared,
                unit="km",
                source="trip_data",
                supports="rider",
            )
        )
    if baseline is not None:
        packet.facts.append(
            Fact(
                key="optimal_distance_km",
                label="Optimal route distance",
                value=baseline,
                unit="km",
                source="trip_data",
                supports="driver",
                note="Platform estimate" if trip.estimated_distance_km else "Straight-line x 1.30 road factor",
            )
        )

    deviation_pct = None
    if actual is not None and baseline:
        deviation_pct = round((actual - baseline) / baseline * 100.0, 1)
        packet.facts.append(
            Fact(
                key="route_deviation_pct",
                label="Route deviation vs. optimal",
                value=deviation_pct,
                unit="%",
                source="derived",
                supports="rider" if deviation_pct > ROUTE_TOLERANCE_PCT else "driver",
                note=f"{abs(actual - baseline):.2f} km of extra distance",
            )
        )

    # --- Unexpected stops ------------------------------------------------------
    stops = _detect_stops(case.gps_telemetry, pickup, dropoff)
    total_stop_min = round(sum(s["duration_min"] for s in stops), 1)
    packet.facts.append(
        Fact(
            key="unexplained_stops",
            label="Unexplained stops away from pickup/dropoff",
            value=len(stops),
            unit="stops",
            source="gps_telemetry",
            supports="rider" if stops else "driver",
            note=f"{total_stop_min} min stationary in total" if stops else None,
        )
    )
    for i, stop in enumerate(stops, start=1):
        packet.facts.append(
            Fact(
                key=f"stop_{i}",
                label=f"Stop #{i}",
                value=f"{stop['duration_min']:.0f} min stationary",
                source="gps_telemetry",
                supports="rider",
                note=f"Around {stop['lat']:.4f}, {stop['lng']:.4f}",
            )
        )

    # --- Duration & fare -------------------------------------------------------
    duration_actual = trip.actual_duration_min
    duration_est = trip.estimated_duration_min
    if duration_actual is None and case.gps_telemetry:
        duration_actual = minutes_between(
            case.gps_telemetry[0].timestamp, case.gps_telemetry[-1].timestamp
        )
    if duration_actual is not None and duration_est is not None:
        packet.facts.append(
            Fact(
                key="duration_overrun_min",
                label="Trip duration vs. estimate",
                value=round(duration_actual - duration_est, 1),
                unit="min",
                source="trip_data",
                supports="rider" if duration_actual > duration_est * 1.25 else "driver",
                note=f"{duration_actual:g} min actual vs {duration_est:g} min estimated",
            )
        )

    overcharge = None
    if trip.fare_charged is not None and trip.fare_estimate is not None:
        overcharge = round(trip.fare_charged - trip.fare_estimate, 2)
        packet.facts.append(
            Fact(
                key="fare_variance",
                label="Fare charged vs. estimate",
                value=overcharge,
                unit="SGD",
                source="trip_data",
                supports="rider" if overcharge > 0 else "driver",
                note=f"S${trip.fare_charged:.2f} charged vs S${trip.fare_estimate:.2f} estimated",
            )
        )
        if trip.fare_estimate:
            packet.facts.append(
                Fact(
                    key="fare_variance_pct",
                    label="Fare overcharge ratio",
                    value=round(overcharge / trip.fare_estimate * 100.0, 1),
                    unit="%",
                    source="derived",
                    supports="rider" if overcharge > 0 else "driver",
                )
            )

    # --- Was the detour justified? -----------------------------------------------
    justification = _find_justification(case)
    packet.facts.append(
        Fact(
            key="driver_explanation",
            label="Driver explanation for the detour",
            value=justification or "None provided",
            source="chat_logs",
            supports="driver" if justification else "rider",
        )
    )
    traffic = _find_traffic_evidence(case)
    if traffic:
        packet.facts.append(
            Fact(
                key="traffic_evidence",
                label="External congestion evidence",
                value=traffic,
                source="app_events",
                supports="driver",
            )
        )

    # --- Policy --------------------------------------------------------------------
    if deviation_pct is not None:
        packet.policy_checks.append(
            PolicyCheck(
                ref="ROUTE-1",
                description=f"Driver must follow the optimal route (+/- {ROUTE_TOLERANCE_PCT:g}% tolerance)",
                expected=f"<= {ROUTE_TOLERANCE_PCT:g}% deviation",
                actual=f"{deviation_pct:g}% deviation",
                compliant=deviation_pct <= ROUTE_TOLERANCE_PCT,
                supports="driver" if deviation_pct <= ROUTE_TOLERANCE_PCT else "rider",
            )
        )
    packet.policy_checks.append(
        PolicyCheck(
            ref="ROUTE-2",
            description="Any material detour must be communicated to the rider",
            expected="Explanation in chat",
            actual=justification or "No explanation",
            compliant=bool(justification),
            supports="driver" if justification else "rider",
        )
    )
    packet.policy_checks.append(
        PolicyCheck(
            ref="ROUTE-3",
            description="Unexpected stops must be justified",
            expected="No unexplained stops > 2 min",
            actual=f"{len(stops)} unexplained stop(s)",
            compliant=len(stops) == 0,
            supports="driver" if not stops else "rider",
        )
    )


def _analyse_property_damage(case: DisputeCase, packet: EvidencePacket) -> None:
    trip = case.trip_data
    trip_end = trip.trip_end_time or trip.cancellation_time

    fee = trip.cleaning_fee_claimed
    if fee is not None:
        packet.facts.append(
            Fact(
                key="cleaning_fee_claimed",
                label="Cleaning fee claimed by driver",
                value=fee,
                unit="SGD",
                source="trip_data",
                supports="driver",
            )
        )

    stats = _contact_stats(case.chat_logs)
    packet.facts.append(
        Fact(
            key="driver_contact_attempts",
            label="Driver contact attempts",
            value=stats["driver_attempts"],
            unit="attempts",
            source="chat_logs",
            supports="driver" if stats["driver_attempts"] else "rider",
        )
    )

    if not case.media_attachments:
        packet.facts.append(
            Fact(
                key="no_photo_evidence",
                label="Photo evidence submitted",
                value="None",
                source="media_attachments",
                supports="rider",
                note="Cleaning claim unsupported by any visual evidence",
            )
        )
        packet.policy_checks.append(
            PolicyCheck(
                ref="DAMAGE-1",
                description="Cleaning claims require photo evidence taken during/near the trip",
                expected=">= 1 valid photo",
                actual="0 photos",
                compliant=False,
                supports="rider",
            )
        )
        return

    for att in case.media_attachments:
        delta = minutes_between(trip_end, att.captured_at) if att.captured_at else None
        packet.facts.append(
            Fact(
                key=f"photo_{att.attachment_id}_captured_at",
                label="Photo EXIF capture time",
                value=_fmt_dt(att.captured_at),
                source="media_exif",
                supports="driver",
            )
        )
        if delta is not None:
            packet.facts.append(
                Fact(
                    key=f"photo_{att.attachment_id}_exif_delta_min",
                    label="EXIF timestamp vs. trip end",
                    value=delta,
                    unit="min",
                    source="media_exif",
                    supports="rider" if abs(delta) > EXIF_TOLERANCE_MIN else "driver",
                    note="Photo taken well after the trip ended"
                    if abs(delta) > EXIF_TOLERANCE_MIN
                    else "Consistent with the trip window",
                )
            )
        if att.ai_generated_probability is not None:
            packet.facts.append(
                Fact(
                    key=f"photo_{att.attachment_id}_ai_probability",
                    label="Probability the photo is AI-generated",
                    value=round(att.ai_generated_probability, 2),
                    source="vision_forensics",
                    supports="rider" if att.ai_generated_probability >= AI_GENERATED_FLAG else "driver",
                    note="Above the 0.50 authenticity flag threshold"
                    if att.ai_generated_probability >= AI_GENERATED_FLAG
                    else "Below the 0.50 authenticity flag threshold",
                )
            )
        if not att.exif_present:
            packet.facts.append(
                Fact(
                    key=f"photo_{att.attachment_id}_exif_missing",
                    label="EXIF metadata stripped",
                    value=True,
                    source="media_exif",
                    supports="rider",
                    note="Stripped EXIF is a common sign of a reused or synthesised image",
                )
            )

    packet.policy_checks.append(
        PolicyCheck(
            ref="DAMAGE-1",
            description="Photo evidence must be captured within 45 min of trip end",
            expected=f"<= {EXIF_TOLERANCE_MIN:g} min delta",
            actual=_exif_actual(case, trip_end),
            compliant=_exif_compliant(case, trip_end),
            supports="driver" if _exif_compliant(case, trip_end) else "rider",
        )
    )
    packet.policy_checks.append(
        PolicyCheck(
            ref="DAMAGE-2",
            description="Photo must be authentic (not AI-generated or reused)",
            expected=f"AI probability < {AI_GENERATED_FLAG:.2f}",
            actual=_ai_actual(case),
            compliant=_ai_compliant(case),
            supports="driver" if _ai_compliant(case) else "rider",
        )
    )


# --- Stop / justification detection ------------------------------------------


def _detect_stops(
    telemetry: Sequence[GpsPoint],
    pickup: Optional[GeoPoint],
    dropoff: Optional[GeoPoint],
) -> list[dict]:
    """Find clusters of stationary pings that are neither pickup nor dropoff."""
    stops: list[dict] = []
    cluster: list[GpsPoint] = []

    def far_from_endpoints(p: GpsPoint) -> bool:
        for endpoint in (pickup, dropoff):
            if endpoint and distance_m(_as_point(p.lat, p.lng), endpoint) <= 150:
                return False
        return True

    for point in list(telemetry) + [None]:  # type: ignore[list-item]
        if point is not None and point.speed_kmh <= STOP_SPEED_KMH and far_from_endpoints(point):
            cluster.append(point)
            continue
        if len(cluster) >= 2:
            duration = (cluster[-1].timestamp - cluster[0].timestamp).total_seconds() / 60.0
            if duration >= STOP_MIN_DURATION_MIN:
                stops.append(
                    {
                        "duration_min": duration,
                        "lat": cluster[0].lat,
                        "lng": cluster[0].lng,
                        "from": cluster[0].timestamp,
                        "to": cluster[-1].timestamp,
                    }
                )
        cluster = []
    return stops


def _find_justification(case: DisputeCase) -> Optional[str]:
    for msg in case.chat_logs:
        if msg.sender == "driver":
            low = msg.content.lower()
            if any(
                kw in low
                for kw in ("jam", "traffic", "congestion", "roadwork", "diversion", "accident", "closed")
            ):
                return msg.content
    return None


def _find_traffic_evidence(case: DisputeCase) -> Optional[str]:
    for ev in case.app_events:
        low = (ev.details or "").lower()
        if any(kw in low for kw in ("traffic", "congestion", "roadwork", "accident", "diversion")):
            return ev.details
    return None


def _exif_actual(case: DisputeCase, trip_end: Optional[datetime]) -> str:
    deltas = [
        minutes_between(trip_end, a.captured_at)
        for a in case.media_attachments
        if a.captured_at is not None
    ]
    deltas = [d for d in deltas if d is not None]
    if not deltas:
        return "No EXIF timestamp"
    return f"max |delta| {max(abs(d) for d in deltas):g} min"


def _exif_compliant(case: DisputeCase, trip_end: Optional[datetime]) -> bool:
    deltas = [
        minutes_between(trip_end, a.captured_at)
        for a in case.media_attachments
        if a.captured_at is not None
    ]
    deltas = [d for d in deltas if d is not None]
    if not deltas:
        return False
    return all(abs(d) <= EXIF_TOLERANCE_MIN for d in deltas)


def _ai_actual(case: DisputeCase) -> str:
    probs = [
        a.ai_generated_probability
        for a in case.media_attachments
        if a.ai_generated_probability is not None
    ]
    if not probs:
        return "Not scored"
    return f"max {max(probs):.2f}"


def _ai_compliant(case: DisputeCase) -> bool:
    probs = [
        a.ai_generated_probability
        for a in case.media_attachments
        if a.ai_generated_probability is not None
    ]
    if not probs:
        return True
    return all(p < AI_GENERATED_FLAG for p in probs)


# --- Risk / behavioural signals -----------------------------------------------


def _analyse_risk(case: DisputeCase, packet: EvidencePacket) -> None:
    rider = case.rider_profile
    if rider:
        if rider.fraud_flags > 0:
            packet.risk_signals.append(
                RiskSignal(
                    party="rider",
                    signal="Fraud flag on rider account",
                    severity="high" if rider.fraud_flags >= 2 else "medium",
                    detail=rider.fraud_flag_details or f"{rider.fraud_flags} active flag(s)",
                )
            )
        if rider.dispute_history.total_disputes >= 3 and rider.dispute_history.success_rate <= 0.34:
            packet.risk_signals.append(
                RiskSignal(
                    party="rider",
                    signal="Pattern of rejected disputes",
                    severity="medium",
                    detail=(
                        f"{rider.dispute_history.total_disputes} disputes filed, "
                        f"{rider.dispute_history.rejected} rejected"
                    ),
                )
            )
        if rider.account_age_days < 90:
            packet.risk_signals.append(
                RiskSignal(
                    party="rider",
                    signal="New account",
                    severity="low",
                    detail=f"Account is {rider.account_age_days} days old",
                )
            )

    driver = case.driver_profile
    if driver:
        if driver.fraud_flags > 0:
            packet.risk_signals.append(
                RiskSignal(
                    party="driver",
                    signal="Fraud flag on driver account",
                    severity="high" if driver.fraud_flags >= 2 else "medium",
                    detail=f"{driver.fraud_flags} active flag(s)",
                )
            )
        if driver.dispute_history.upheld_count >= 2:
            packet.risk_signals.append(
                RiskSignal(
                    party="driver",
                    signal="Repeated claims upheld against driver",
                    severity="medium",
                    detail=f"{driver.dispute_history.upheld_count} prior rulings against this driver",
                )
            )


# --- Public entrypoint ---------------------------------------------------------


def _analyse_safety_incident(case: DisputeCase, packet: EvidencePacket) -> None:
    """Corroborate (or undercut) a safety allegation against the telematics.

    This never produces a verdict — safety is outside the autonomy boundary —
    but it hands the human investigator the sensor facts up front.
    """
    speeds = [p.speed_kmh for p in case.gps_telemetry if p.speed_kmh is not None]
    peak = max(speeds) if speeds else 0.0
    if speeds:
        packet.facts.append(
            Fact(
                key="peak_recorded_speed",
                label="Peak speed recorded during the trip",
                value=round(peak, 1),
                unit="km/h",
                source="gps_telemetry",
                supports="rider" if peak >= 90 else "neutral",
                note="Above the 90 km/h expressway limit" if peak >= 90 else None,
            )
        )

    braking = [e for e in case.app_events if e.event_type == "harsh_braking_detected"]
    packet.facts.append(
        Fact(
            key="harsh_braking_events",
            label="Harsh-braking events logged by telematics",
            value=len(braking),
            unit="events",
            source="app_events",
            supports="rider" if braking else "driver",
            note=braking[0].details if braking and braking[0].details else None,
        )
    )

    speeding = [e for e in case.app_events if e.event_type == "speed_limit_exceeded"]
    if speeding:
        packet.facts.append(
            Fact(
                key="speed_limit_breaches",
                label="Speed-limit breaches logged by telematics",
                value=len(speeding),
                unit="events",
                source="app_events",
                supports="rider",
                note=speeding[0].details if speeding[0].details else None,
            )
        )

    # Did the rider actually ask the driver to slow down? That distinguishes a
    # safety complaint from a post-hoc fare grievance.
    asked = [
        m
        for m in case.chat_logs
        if m.sender == "rider" and any(k in m.content.lower() for k in ("slow", "speed", "fast"))
    ]
    packet.facts.append(
        Fact(
            key="rider_speed_complaints",
            label="In-trip complaints about speed from the rider",
            value=len(asked),
            unit="messages",
            source="chat_logs",
            supports="rider" if asked else "driver",
            note=asked[0].content if asked else "No in-trip speed complaint found in the chat log",
        )
    )

    packet.policy_checks.append(
        PolicyCheck(
            ref="SAFETY-1",
            description="Safety incidents must be escalated to a human reviewer",
            expected="Routed to human review, no autonomous ruling",
            actual=(
                f"{len(braking)} harsh-braking and {len(speeding)} speeding event(s) logged"
                if (braking or speeding)
                else "No telematics corroboration found"
            ),
            compliant=False,
            supports="neutral",
        )
    )


def _analyse_audio_evidence(case: DisputeCase, packet: EvidencePacket) -> None:
    """Turn ASR transcripts into auditable facts (Phase 3).

    The recording is not "vibes" — the transcript, its hostility score and
    whether the audio actually covers the trip window are all computed facts a
    reviewer can replay.
    """
    for att in case.media_attachments:
        if att.media_type != "audio" or att.transcript is None:
            continue
        tr = att.transcript
        packet.facts.append(
            Fact(
                key=f"audio_{att.attachment_id}_duration_s",
                label="Recording duration (ASR)",
                value=round(tr.duration_s, 1),
                unit="s",
                source="trtc_asr",
                supports="neutral",
                note=f"{tr.engine} engine · {len(tr.segments)} speaker turn(s)",
            )
        )
        packet.facts.append(
            Fact(
                key=f"audio_{att.attachment_id}_hostility",
                label="Verbal hostility score (ASR transcript)",
                value=round(tr.hostility_score, 2),
                source="trtc_asr",
                supports="rider" if tr.hostility_score >= 0.45 else "neutral",
                note=tr.summary,
            )
        )
        packet.facts.append(
            Fact(
                key=f"audio_{att.attachment_id}_threat",
                label="Explicit threat detected in recording",
                value=bool(tr.threat_detected),
                source="trtc_asr",
                supports="rider" if tr.threat_detected else "driver",
                note=(", ".join(tr.keywords) if tr.keywords else "no threat language matched"),
            )
        )

        trip = case.trip_data
        window_ok = (
            att.captured_at is not None
            and trip.trip_start_time is not None
            and (trip.trip_end_time or trip.cancellation_time) is not None
            and trip.trip_start_time
            <= att.captured_at
            <= (trip.trip_end_time or trip.cancellation_time)
        )
        packet.facts.append(
            Fact(
                key=f"audio_{att.attachment_id}_in_trip_window",
                label="Recording falls inside the trip window",
                value=bool(window_ok),
                source="trtc_asr",
                supports="rider" if window_ok else "driver",
                note=(
                    "Recorded while the trip was in progress"
                    if window_ok
                    else "Recording timestamp falls outside the trip window"
                ),
            )
        )

        if tr.threat_detected or tr.hostility_score >= 0.45:
            packet.policy_checks.append(
                PolicyCheck(
                    ref="SAFETY-2",
                    description="Verified recordings containing threats or abuse require human review",
                    expected="Escalated to Safety & Fraud, no autonomous ruling",
                    actual=(
                        f"hostility {tr.hostility_score:.2f}"
                        + (", explicit threat" if tr.threat_detected else "")
                    ),
                    compliant=False,
                    supports="neutral",
                )
            )
            packet.risk_signals.append(
                RiskSignal(
                    party="driver" if att.uploaded_by == "rider" else "rider",
                    signal="abusive_or_threatening_language",
                    severity="high" if tr.threat_detected else "medium",
                    detail=tr.summary,
                )
            )


def _analyse_video_evidence(case: DisputeCase, packet: EvidencePacket) -> None:
    """Turn extracted keyframes into auditable facts (Phase 3)."""
    for att in case.media_attachments:
        if att.media_type != "video" or att.video is None:
            continue
        vid = att.video
        packet.facts.append(
            Fact(
                key=f"video_{att.attachment_id}_duration_s",
                label="Video duration",
                value=round(vid.duration_s, 1),
                unit="s",
                source="video_ingest",
                supports="neutral",
                note=f"{vid.width}x{vid.height} @ {vid.fps} fps"
                if vid.width and vid.fps
                else None,
            )
        )
        packet.facts.append(
            Fact(
                key=f"video_{att.attachment_id}_frames",
                label="Keyframes extracted for visual analysis",
                value=vid.frames_extracted,
                unit="frames",
                source="video_ingest",
                supports="neutral",
                note=f"{vid.engine} backend · 1 frame/s sampling",
            )
        )
        delta = minutes_between(
            case.trip_data.trip_end_time or case.trip_data.cancellation_time, att.captured_at
        )
        if delta is not None:
            packet.facts.append(
                Fact(
                    key=f"video_{att.attachment_id}_exif_delta_min",
                    label="Video timestamp vs. trip end",
                    value=round(delta, 1),
                    unit="min",
                    source="media_exif",
                    supports="driver" if abs(delta) <= EXIF_TOLERANCE_MIN else "rider",
                    note="Consistent with the trip window"
                    if abs(delta) <= EXIF_TOLERANCE_MIN
                    else "Recorded well after the trip ended",
                )
            )
        for anomaly in vid.anomalies:
            packet.risk_signals.append(
                RiskSignal(
                    party="driver" if att.uploaded_by == "driver" else "rider",
                    signal="video_integrity_anomaly",
                    severity="medium",
                    detail=anomaly,
                )
            )


def extract_evidence(case: DisputeCase) -> EvidencePacket:
    """Build the auditable evidence packet for a dispute dossier."""
    packet = EvidencePacket(
        dispute_id=case.dispute_id, dispute_type=case.dispute_type
    )

    dtype = case.dispute_type
    if dtype == "no_show_charge":
        _analyse_no_show(case, packet)
    elif dtype == "route_deviation":
        _analyse_route_deviation(case, packet)
    elif dtype == "property_damage":
        _analyse_property_damage(case, packet)
    elif dtype == "safety_incident":
        _analyse_safety_incident(case, packet)
    else:
        _analyse_no_show(case, packet)

    _analyse_audio_evidence(case, packet)
    _analyse_video_evidence(case, packet)
    _analyse_risk(case, packet)
    _dedupe_policy_checks(packet)
    packet.summary = _summarise(case, packet)
    return packet


def _dedupe_policy_checks(packet: EvidencePacket) -> None:
    """Collapse repeated clause references into one entry.

    A dossier can carry several recordings of the same incident (a rider and a
    driver both upload audio), which would otherwise emit the same clause once
    per attachment. One clause = one row, and the least compliant outcome wins
    so a single breach can never be diluted by a passing duplicate.
    """
    seen: dict[str, PolicyCheck] = {}
    for check in packet.policy_checks:
        prior = seen.get(check.ref)
        if prior is None:
            seen[check.ref] = check
            continue
        if not check.compliant and prior.compliant:
            seen[check.ref] = check
    if len(seen) != len(packet.policy_checks):
        packet.policy_checks[:] = list(seen.values())


def _summarise(case: DisputeCase, packet: EvidencePacket) -> str:
    rider_facts = len(packet.facts_for("rider"))
    driver_facts = len(packet.facts_for("driver"))
    neutral = len(packet.facts) - rider_facts - driver_facts
    failed = [c for c in packet.policy_checks if not c.compliant]
    return (
        f"{len(packet.facts)} verified facts ({driver_facts} favour the driver, "
        f"{rider_facts} favour the rider, {neutral} neutral). "
        f"{len(packet.policy_checks) - len(failed)}/{len(packet.policy_checks)} policy checks pass; "
        f"{len(packet.risk_signals)} behavioural risk signal(s)."
    )
