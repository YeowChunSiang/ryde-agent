"""Built-in dispute dossiers used for demo, testing and judging.

Coverage against the Ryde problem statement:

=========  ============================  ==========================================
Case       Category                      Demonstrates
=========  ============================  ==========================================
DISP-002   no_show_charge                The official hackathon sample (expected: UPHELD)
DISP-001   route_deviation               Second required text category (expected: PARTIAL REFUND)
DISP-003   property_damage               Multi-modal vision agent *rejecting* fabricated evidence
DISP-004   property_damage               Multi-modal vision agent *accepting* valid evidence
DISP-005   safety_incident               CRITICAL SLA fast-track + mandatory human escalation
DISP-006   safety_incident               Audio evidence — TRTC ASR transcription of a verbal
                                         altercation (AC temperature dispute), routed HIGH
DISP-007   safety_incident               Video evidence — 1 fps keyframes from a low-light
                                         covert recording of physical/sexual harassment, CRITICAL
=========  ============================  ==========================================

DISP-003/004 exist as a pair on purpose: they prove the judge is not biased
against drivers — the same vision pipeline that voids a fabricated cleaning claim
also awards a legitimate one.

DISP-005 exercises the Phase 2 safety net end to end: the SLA & Routing Manager
tags it CRITICAL and jumps the queue, and the escalation protocol halts
autonomous arbitration regardless of how confident the Judge is.

DISP-006/007 are the Phase 3.2 multi-modal pair. Both are safety incidents, but
they sit in different triage bands on purpose: DISP-007 (physical/sexual
harassment) is CRITICAL and therefore the first thing a reviewer sees, while
DISP-006 (a verbal altercation over the cabin temperature) is pinned HIGH —
elevated and fast-tracked, but correctly behind an immediate physical-safety
threat. Each dossier carries ``escalation_directives``: the immediate actions
the escalation protocol hands the reviewer (apology note / reprimand / goodwill
voucher for the verbal case; instant suspension / safety ticket / law-enforcement
referral for the harassment case).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import CaseSummary, DisputeCase

CASES_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# DISP-002 — official No-Show Charge sample (expected: charge UPHELD)
# ---------------------------------------------------------------------------

DISP_002: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-002",
        "trip_id": "TRIP-2026-09945",
        "filed_by": "rider",
        "dispute_type": "no_show_charge",
        "description": (
            "I was at the pickup point at Tiong Bahru Plaza on time but the driver never showed up. "
            "I waited 10 minutes at the lobby and couldn't find the car. The app charged me a $5.00 "
            "cancellation fee for a 'no-show' which is completely unfair — I was there, the driver "
            "was not. I want the charge reversed immediately."
        ),
        "filed_at": "2026-09-13T09:20:00+08:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-7823",
        "name": "Michael Wong",
        "account_age_days": 210,
        "total_trips": 34,
        "avg_rating": 3.9,
        "dispute_history": {"total_disputes": 4, "upheld": 1, "rejected": 3},
        "fraud_flags": 1,
        "fraud_flag_details": "flagged_for_frequent_late_cancellations",
        "payment_method": "e-wallet",
    },
    "driver_profile": {
        "driver_id": "D-2398",
        "name": "Lim Wei Ming",
        "account_age_days": 900,
        "total_trips": 3201,
        "avg_rating": 4.9,
        "dispute_history": {"total_disputes": 1, "upheld_against": 0, "rejected": 1},
        "fraud_flags": 0,
        "vehicle": "Honda HR-V (SGP 4521 M)",
    },
    "trip_data": {
        "trip_id": "TRIP-2026-09945",
        "rider_id": "R-7823",
        "driver_id": "D-2398",
        "pickup_location": {"name": "Tiong Bahru Plaza", "lat": 1.2847, "lng": 103.8382},
        "dropoff_location": {"name": "VivoCity", "lat": 1.2648, "lng": 103.8223},
        "scheduled_time": "2026-09-13T08:45:00+08:00",
        "driver_arrival_time": "2026-09-13T08:43:00+08:00",
        "driver_wait_start": "2026-09-13T08:43:00+08:00",
        "cancellation_time": "2026-09-13T08:51:00+08:00",
        "cancellation_fee": 5.00,
        "cancellation_reason": "rider_no_show",
    },
    "gps_telemetry": [
        {"timestamp": "2026-09-13T08:31:00+08:00", "lat": 1.2920, "lng": 103.8450, "speed_kmh": 42, "status": "en_route"},
        {"timestamp": "2026-09-13T08:34:00+08:00", "lat": 1.2890, "lng": 103.8430, "speed_kmh": 38, "status": "en_route"},
        {"timestamp": "2026-09-13T08:38:00+08:00", "lat": 1.2865, "lng": 103.8400, "speed_kmh": 25, "status": "en_route"},
        {"timestamp": "2026-09-13T08:41:00+08:00", "lat": 1.2852, "lng": 103.8388, "speed_kmh": 12, "status": "en_route"},
        {"timestamp": "2026-09-13T08:43:00+08:00", "lat": 1.2847, "lng": 103.8382, "speed_kmh": 0, "status": "arrived"},
        {"timestamp": "2026-09-13T08:45:00+08:00", "lat": 1.2847, "lng": 103.8382, "speed_kmh": 0, "status": "waiting"},
        {"timestamp": "2026-09-13T08:48:00+08:00", "lat": 1.2847, "lng": 103.8382, "speed_kmh": 0, "status": "waiting"},
        {"timestamp": "2026-09-13T08:51:00+08:00", "lat": 1.2847, "lng": 103.8382, "speed_kmh": 0, "status": "cancelled"},
    ],
    "chat_logs": [
        {"timestamp": "2026-09-13T08:43:00+08:00", "sender": "driver", "type": "message", "content": "I've arrived at the pickup point, I'm at the lobby area."},
        {"timestamp": "2026-09-13T08:45:20+08:00", "sender": "driver", "type": "message", "content": "I'm waiting at the lobby area, white Honda HR-V plate SGP 4521 M."},
        {"timestamp": "2026-09-13T08:47:05+08:00", "sender": "driver", "type": "call", "content": "Outgoing call to rider — not answered (rang 22s, no response)."},
        {"timestamp": "2026-09-13T08:49:30+08:00", "sender": "driver", "type": "message", "content": "Hi, are you coming down? I've been waiting a while."},
        {"timestamp": "2026-09-13T08:50:45+08:00", "sender": "driver", "type": "message", "content": "Please let me know, otherwise I'll have to cancel the trip."},
        {"timestamp": "2026-09-13T08:51:00+08:00", "sender": "system", "type": "system", "content": "Trip cancelled by driver. Reason: rider_no_show. Cancellation fee of $5.00 applied."},
    ],
    "app_events": [
        {"timestamp": "2026-09-13T08:30:00+08:00", "event_type": "booking_confirmed", "details": "Rider R-7823 booked trip TRIP-2026-09945 from Tiong Bahru Plaza to VivoCity. Scheduled pickup 08:45."},
        {"timestamp": "2026-09-13T08:30:15+08:00", "event_type": "driver_assigned", "details": "Driver D-2398 (Lim Wei Ming, Honda HR-V SGP 4521 M) assigned. ETA 13 min."},
        {"timestamp": "2026-09-13T08:30:20+08:00", "event_type": "driver_en_route", "details": "Driver started navigating to pickup location. Live tracking enabled."},
        {"timestamp": "2026-09-13T08:43:00+08:00", "event_type": "driver_arrived", "details": "Driver GPS within 10m of pickup point. Speed 0 km/h. Auto-arrival confirmed."},
        {"timestamp": "2026-09-13T08:43:05+08:00", "event_type": "rider_notified", "details": "Push notification + in-app alert sent to rider: 'Your driver has arrived.'"},
        {"timestamp": "2026-09-13T08:43:10+08:00", "event_type": "wait_timer_started", "details": "Free wait timer started. 5 min free wait period ends at 08:48."},
        {"timestamp": "2026-09-13T08:47:05+08:00", "event_type": "driver_called_rider", "details": "Driver initiated in-app call to rider. Call rang 22s, no answer."},
        {"timestamp": "2026-09-13T08:48:10+08:00", "event_type": "wait_timer_expired", "details": "Free 5-min wait period expired. Rider had not boarded. Cancellation fee now applicable per policy."},
        {"timestamp": "2026-09-13T08:51:00+08:00", "event_type": "cancellation_fee_applied", "details": "No-show threshold (8 min) reached. $5.00 cancellation fee charged to rider payment method (e-wallet)."},
        {"timestamp": "2026-09-13T08:51:05+08:00", "event_type": "driver_released", "details": "Driver D-2398 released from trip. Trip status: cancelled (rider_no_show)."},
    ],
    "cancellation_policy": {
        "free_wait_time_min": 5,
        "cancellation_fee_after_wait": 5.00,
        "no_show_threshold_min": 8,
        "fee_goes_to": "driver_compensation",
    },
}


# ---------------------------------------------------------------------------
# DISP-001 — Route Deviation (expected: PARTIAL REFUND)
# ---------------------------------------------------------------------------

DISP_001: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-001",
        "trip_id": "TRIP-2026-08812",
        "filed_by": "rider",
        "dispute_type": "route_deviation",
        "description": (
            "The driver took a much longer route from Raffles Place to Paya Lebar and I was "
            "overcharged. The app quoted me $20.00 but I was charged $28.00. We went north through "
            "Toa Payoh which is completely the wrong direction, and he even stopped for about seven "
            "minutes somewhere. I want the difference refunded."
        ),
        "filed_at": "2026-09-14T19:05:00+08:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-4451",
        "name": "Priya Raman",
        "account_age_days": 640,
        "total_trips": 128,
        "avg_rating": 4.7,
        "dispute_history": {"total_disputes": 0, "upheld": 0, "rejected": 0},
        "fraud_flags": 0,
        "payment_method": "credit_card",
    },
    "driver_profile": {
        "driver_id": "D-7710",
        "name": "Abdul Rahman",
        "account_age_days": 1250,
        "total_trips": 1452,
        "avg_rating": 4.8,
        "dispute_history": {"total_disputes": 1, "upheld_against": 1, "rejected": 0},
        "fraud_flags": 0,
        "vehicle": "Toyota Prius (SGP 7710 A)",
    },
    "trip_data": {
        "trip_id": "TRIP-2026-08812",
        "rider_id": "R-4451",
        "driver_id": "D-7710",
        "pickup_location": {"name": "Raffles Place MRT", "lat": 1.2834, "lng": 103.8515},
        "dropoff_location": {"name": "Paya Lebar Square", "lat": 1.3176, "lng": 103.8920},
        "scheduled_time": "2026-09-14T18:15:00+08:00",
        "trip_start_time": "2026-09-14T18:15:00+08:00",
        "trip_end_time": "2026-09-14T18:53:00+08:00",
        "estimated_distance_km": 8.8,
        "estimated_duration_min": 22,
        "actual_duration_min": 38,
        "fare_estimate": 20.00,
        "fare_charged": 28.00,
        "surge_multiplier": 1.0,
        "fare_breakdown": [
            {"label": "Base fare", "amount": 3.20},
            {"label": "Distance (14.0 km)", "amount": 16.80},
            {"label": "Time (38 min)", "amount": 6.50},
            {"label": "Booking fee", "amount": 1.50},
        ],
    },
    "gps_telemetry": [
        {"timestamp": "2026-09-14T18:15:00+08:00", "lat": 1.2834, "lng": 103.8515, "speed_kmh": 0, "status": "trip_start"},
        {"timestamp": "2026-09-14T18:17:00+08:00", "lat": 1.2900, "lng": 103.8560, "speed_kmh": 30, "status": "en_route"},
        {"timestamp": "2026-09-14T18:19:00+08:00", "lat": 1.2980, "lng": 103.8620, "speed_kmh": 38, "status": "en_route"},
        {"timestamp": "2026-09-14T18:21:00+08:00", "lat": 1.3050, "lng": 103.8700, "speed_kmh": 42, "status": "en_route"},
        {"timestamp": "2026-09-14T18:23:00+08:00", "lat": 1.3120, "lng": 103.8790, "speed_kmh": 40, "status": "en_route"},
        {"timestamp": "2026-09-14T18:26:00+08:00", "lat": 1.3220, "lng": 103.8860, "speed_kmh": 35, "status": "en_route"},
        {"timestamp": "2026-09-14T18:29:00+08:00", "lat": 1.3340, "lng": 103.8820, "speed_kmh": 30, "status": "en_route"},
        {"timestamp": "2026-09-14T18:32:00+08:00", "lat": 1.3400, "lng": 103.8730, "speed_kmh": 28, "status": "en_route"},
        {"timestamp": "2026-09-14T18:35:00+08:00", "lat": 1.3360, "lng": 103.8640, "speed_kmh": 25, "status": "en_route"},
        {"timestamp": "2026-09-14T18:38:00+08:00", "lat": 1.3280, "lng": 103.8780, "speed_kmh": 22, "status": "en_route"},
        {"timestamp": "2026-09-14T18:41:00+08:00", "lat": 1.3300, "lng": 103.8900, "speed_kmh": 8, "status": "en_route"},
        {"timestamp": "2026-09-14T18:42:00+08:00", "lat": 1.3300, "lng": 103.8900, "speed_kmh": 0, "status": "stopped"},
        {"timestamp": "2026-09-14T18:49:00+08:00", "lat": 1.3300, "lng": 103.8900, "speed_kmh": 0, "status": "stopped"},
        {"timestamp": "2026-09-14T18:51:00+08:00", "lat": 1.3250, "lng": 103.8910, "speed_kmh": 20, "status": "en_route"},
        {"timestamp": "2026-09-14T18:53:00+08:00", "lat": 1.3176, "lng": 103.8920, "speed_kmh": 0, "status": "completed"},
    ],
    "chat_logs": [
        {"timestamp": "2026-09-14T18:26:00+08:00", "sender": "driver", "type": "message", "content": "There is heavy traffic on the usual route, I'm taking an alternative road to avoid the jam."},
        {"timestamp": "2026-09-14T18:33:00+08:00", "sender": "rider", "type": "message", "content": "Why are we going north? This is not the way to Paya Lebar."},
        {"timestamp": "2026-09-14T18:40:00+08:00", "sender": "driver", "type": "message", "content": "Almost there, just clearing the congestion."},
        {"timestamp": "2026-09-14T18:49:00+08:00", "sender": "rider", "type": "message", "content": "You just stopped for seven minutes at a petrol station. I am disputing this fare."},
    ],
    "app_events": [
        {"timestamp": "2026-09-14T18:14:00+08:00", "event_type": "booking_confirmed", "details": "Rider R-4451 booked trip TRIP-2026-08812 from Raffles Place MRT to Paya Lebar Square. Fare estimate $20.00, 8.8 km."},
        {"timestamp": "2026-09-14T18:15:00+08:00", "event_type": "trip_started", "details": "Trip started. Live tracking enabled."},
        {"timestamp": "2026-09-14T18:26:00+08:00", "event_type": "route_recalculated", "details": "Driver route recalculated; alternative route via MacPherson projected to add 5.2 km."},
        {"timestamp": "2026-09-14T18:30:00+08:00", "event_type": "traffic_incident_detected", "details": "Major congestion reported on the Sims Ave corridor; average speeds down 40%."},
        {"timestamp": "2026-09-14T18:42:00+08:00", "event_type": "stationary_detected", "details": "Vehicle stationary for 7 minutes at 1.3300, 103.8900 (nearest POI: fuel station)."},
        {"timestamp": "2026-09-14T18:53:00+08:00", "event_type": "trip_completed", "details": "Trip completed. 14.0 km, 38 min. Fare charged $28.00."},
        {"timestamp": "2026-09-14T19:05:00+08:00", "event_type": "dispute_filed", "details": "Rider filed a route deviation dispute requesting a $8.00 refund."},
    ],
    "cancellation_policy": {
        "free_wait_time_min": 5,
        "cancellation_fee_after_wait": 5.00,
        "no_show_threshold_min": 8,
        "fee_goes_to": "driver_compensation",
    },
}


# ---------------------------------------------------------------------------
# DISP-003 — Property Damage, fabricated photo (expected: NO ACTION + escalation)
# ---------------------------------------------------------------------------

DISP_003: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-003",
        "trip_id": "TRIP-2026-10433",
        "filed_by": "rider",
        "dispute_type": "property_damage",
        "description": (
            "The driver is claiming a $60 cleaning fee saying I spilled bubble tea in his car. "
            "I had no drinks with me at all — I was carrying a sealed umbrella and a laptop bag. "
            "The photo he uploaded looks fake and was clearly taken long after the trip ended. "
            "I refuse to pay this."
        ),
        "filed_at": "2026-09-15T10:12:00+08:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-9912",
        "name": "Daniel Tan",
        "account_age_days": 415,
        "total_trips": 76,
        "avg_rating": 4.6,
        "dispute_history": {"total_disputes": 1, "upheld": 0, "rejected": 1},
        "fraud_flags": 0,
        "payment_method": "e-wallet",
    },
    "driver_profile": {
        "driver_id": "D-5502",
        "name": "Kumar Subramaniam",
        "account_age_days": 380,
        "total_trips": 604,
        "avg_rating": 4.4,
        "dispute_history": {"total_disputes": 3, "upheld_against": 0, "rejected": 3},
        "fraud_flags": 1,
        "vehicle": "Hyundai Ioniq (SGP 5502 B)",
    },
    "trip_data": {
        "trip_id": "TRIP-2026-10433",
        "rider_id": "R-9912",
        "driver_id": "D-5502",
        "pickup_location": {"name": "Clarke Quay Central", "lat": 1.2889, "lng": 103.8462},
        "dropoff_location": {"name": "Tampines MRT", "lat": 1.3545, "lng": 103.9432},
        "scheduled_time": "2026-09-14T21:40:00+08:00",
        "trip_start_time": "2026-09-14T21:42:00+08:00",
        "trip_end_time": "2026-09-14T22:15:00+08:00",
        "actual_distance_km": 18.4,
        "actual_duration_min": 33,
        "fare_estimate": 26.00,
        "fare_charged": 26.00,
        "cleaning_fee_claimed": 60.00,
    },
    "gps_telemetry": [
        {"timestamp": "2026-09-14T21:42:00+08:00", "lat": 1.2889, "lng": 103.8462, "speed_kmh": 0, "status": "trip_start"},
        {"timestamp": "2026-09-14T21:50:00+08:00", "lat": 1.3051, "lng": 103.8790, "speed_kmh": 46, "status": "en_route"},
        {"timestamp": "2026-09-14T22:00:00+08:00", "lat": 1.3300, "lng": 103.9100, "speed_kmh": 58, "status": "en_route"},
        {"timestamp": "2026-09-14T22:10:00+08:00", "lat": 1.3480, "lng": 103.9350, "speed_kmh": 40, "status": "en_route"},
        {"timestamp": "2026-09-14T22:15:00+08:00", "lat": 1.3545, "lng": 103.9432, "speed_kmh": 0, "status": "completed"},
    ],
    "chat_logs": [
        {"timestamp": "2026-09-14T22:31:00+08:00", "sender": "driver", "type": "message", "content": "Your drink spilled all over my back seat, I am claiming the $60 cleaning fee."},
        {"timestamp": "2026-09-14T22:44:00+08:00", "sender": "rider", "type": "message", "content": "I had no drink with me. Please send a photo."},
        {"timestamp": "2026-09-14T23:45:00+08:00", "sender": "driver", "type": "message", "content": "Sent photos of the rear seat, the stain is very obvious."},
        {"timestamp": "2026-09-15T09:58:00+08:00", "sender": "rider", "type": "message", "content": "That photo was taken almost an hour and a half after my trip and looks AI generated. I am disputing it."},
    ],
    "app_events": [
        {"timestamp": "2026-09-14T22:15:00+08:00", "event_type": "trip_completed", "details": "Trip completed. 18.4 km, 33 min. Fare $26.00 charged."},
        {"timestamp": "2026-09-14T22:31:00+08:00", "event_type": "cleaning_claim_filed", "details": "Driver D-5502 filed a cleaning claim of $60.00 for alleged liquid spill."},
        {"timestamp": "2026-09-14T23:46:00+08:00", "event_type": "evidence_uploaded", "details": "Driver uploaded 1 image as evidence (cabin_photo_01.jpg). EXIF capture time 23:41."},
        {"timestamp": "2026-09-15T10:12:00+08:00", "event_type": "dispute_filed", "details": "Rider disputed the cleaning fee, alleging fabricated evidence."},
    ],
    "media_attachments": [
        {
            "attachment_id": "media-disp003-01",
            "media_type": "image",
            "url": "/assets/miora/disp003_fake_spill.png",
            "asset_key": "disp003_fake_spill",
            "uploaded_by": "driver",
            "captured_at": "2026-09-14T23:41:00+08:00",
            "device_model": "iPhone 15 Pro",
            "gps_lat": 1.3521,
            "gps_lng": 103.9418,
            "exif_present": True,
            "ai_generated_probability": 0.71,
            "caption": "Rider spilled bubble tea on the rear seat, sticky liquid everywhere",
        }
    ],
    "cancellation_policy": {
        "free_wait_time_min": 5,
        "cancellation_fee_after_wait": 5.00,
        "no_show_threshold_min": 8,
        "fee_goes_to": "driver_compensation",
    },
}


# ---------------------------------------------------------------------------
# DISP-004 — Property Damage, genuine photo (expected: COMPENSATE DRIVER)
# ---------------------------------------------------------------------------

DISP_004: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-004",
        "trip_id": "TRIP-2026-10510",
        "filed_by": "driver",
        "dispute_type": "property_damage",
        "description": (
            "A rider spilled bubble tea across the rear seat and floor mat during the trip. I had to "
            "take the car out of service for professional cleaning. I am claiming the $60 cleaning "
            "fee with photo evidence taken immediately at the dropoff point."
        ),
        "filed_at": "2026-09-16T20:35:00+08:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-3310",
        "name": "Amelia Ng",
        "account_age_days": 120,
        "total_trips": 19,
        "avg_rating": 4.2,
        "dispute_history": {"total_disputes": 1, "upheld": 0, "rejected": 1},
        "fraud_flags": 0,
        "payment_method": "credit_card",
    },
    "driver_profile": {
        "driver_id": "D-1188",
        "name": "Farah Idris",
        "account_age_days": 1500,
        "total_trips": 4210,
        "avg_rating": 4.95,
        "dispute_history": {"total_disputes": 0, "upheld_against": 0, "rejected": 0},
        "fraud_flags": 0,
        "vehicle": "Honda Vezel (SGP 1188 C)",
    },
    "trip_data": {
        "trip_id": "TRIP-2026-10510",
        "rider_id": "R-3310",
        "driver_id": "D-1188",
        "pickup_location": {"name": "Bugis Junction", "lat": 1.3005, "lng": 103.8555},
        "dropoff_location": {"name": "Tampines Mall", "lat": 1.3545, "lng": 103.9432},
        "scheduled_time": "2026-09-16T20:00:00+08:00",
        "trip_start_time": "2026-09-16T20:02:00+08:00",
        "trip_end_time": "2026-09-16T20:28:00+08:00",
        "actual_distance_km": 16.9,
        "actual_duration_min": 26,
        "fare_estimate": 24.50,
        "fare_charged": 24.50,
        "cleaning_fee_claimed": 60.00,
    },
    "gps_telemetry": [
        {"timestamp": "2026-09-16T20:02:00+08:00", "lat": 1.3005, "lng": 103.8555, "speed_kmh": 0, "status": "trip_start"},
        {"timestamp": "2026-09-16T20:12:00+08:00", "lat": 1.3220, "lng": 103.8890, "speed_kmh": 50, "status": "en_route"},
        {"timestamp": "2026-09-16T20:22:00+08:00", "lat": 1.3410, "lng": 103.9210, "speed_kmh": 44, "status": "en_route"},
        {"timestamp": "2026-09-16T20:28:00+08:00", "lat": 1.3545, "lng": 103.9432, "speed_kmh": 0, "status": "completed"},
    ],
    "chat_logs": [
        {"timestamp": "2026-09-16T20:29:00+08:00", "sender": "driver", "type": "message", "content": "Sorry, but the bubble tea spilled on the rear seat. I have to file a cleaning claim."},
        {"timestamp": "2026-09-16T20:31:00+08:00", "sender": "rider", "type": "message", "content": "It slipped out of my bag when we braked, I'm sorry."},
    ],
    "app_events": [
        {"timestamp": "2026-09-16T20:28:00+08:00", "event_type": "trip_completed", "details": "Trip completed. 16.9 km, 26 min. Fare $24.50 charged."},
        {"timestamp": "2026-09-16T20:33:00+08:00", "event_type": "evidence_uploaded", "details": "Driver uploaded 1 image as evidence (cabin_photo_02.jpg). EXIF capture time 20:33, GPS matches dropoff."},
        {"timestamp": "2026-09-16T20:35:00+08:00", "event_type": "cleaning_claim_filed", "details": "Driver D-1188 filed a cleaning claim of $60.00 for a liquid spill."},
    ],
    "media_attachments": [
        {
            "attachment_id": "media-disp004-01",
            "media_type": "image",
            "url": "/assets/miora/disp004_genuine_spill.png",
            "asset_key": "disp004_genuine_spill",
            "uploaded_by": "driver",
            "captured_at": "2026-09-16T20:33:00+08:00",
            "device_model": "Samsung Galaxy S24",
            "gps_lat": 1.3545,
            "gps_lng": 103.9432,
            "exif_present": True,
            "ai_generated_probability": 0.08,
            "caption": "Bubble tea spilled across the rear seat and floor mat immediately after dropoff",
        }
    ],
    "cancellation_policy": {
        "free_wait_time_min": 5,
        "cancellation_fee_after_wait": 5.00,
        "no_show_threshold_min": 8,
        "fee_goes_to": "driver_compensation",
    },
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Safety incident — exercises the CRITICAL fast-track and the always-escalate
#: rule. The rider is also a high-frequency disputant, so the fraud agent has
#: something to say while the escalation protocol still halts autonomous
#: arbitration: a safety allegation is never auto-resolved, whatever the risk
#: score says.
DISP_005: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-005",
        "trip_id": "RY-20240519-77120",
        "filed_by": "rider",
        "dispute_type": "safety_incident",
        "description": (
            "The driver was doing well over the speed limit on the CTE and brake-checked me "
            "twice after I asked him to slow down. I genuinely feared for my safety and want "
            "this driver reviewed before he hurts someone."
        ),
        "filed_at": "2024-05-19T22:10:00+00:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-55219",
        "name": "Wei Ling Tan",
        "account_age_days": 210,
        "total_trips": 48,
        "avg_rating": 4.7,
        "dispute_history": {"total_disputes": 7, "upheld": 2, "rejected": 5},
        "fraud_flags": 0,
        "payment_method": "visa_4412",
    },
    "driver_profile": {
        "driver_id": "D-30887",
        "name": "Ahmad bin Rahman",
        "account_age_days": 900,
        "total_trips": 3120,
        "avg_rating": 4.6,
        "dispute_history": {"total_disputes": 1, "upheld_against": 0, "rejected": 1},
        "fraud_flags": 0,
        "vehicle": "Toyota Prius (SLC 4521E)",
    },
    "trip_data": {
        "trip_id": "RY-20240519-77120",
        "rider_id": "R-55219",
        "driver_id": "D-30887",
        "pickup_location": {"name": "Clarke Quay MRT", "lat": 1.2886, "lng": 103.8460},
        "dropoff_location": {"name": "Bishan MRT", "lat": 1.3509, "lng": 103.8352},
        "trip_start_time": "2024-05-19T21:41:00+00:00",
        "trip_end_time": "2024-05-19T22:04:00+00:00",
        "estimated_distance_km": 11.2,
        "actual_distance_km": 11.6,
        "estimated_duration_min": 22,
        "actual_duration_min": 23,
        "fare_estimate": 23.00,
        "fare_charged": 24.50,
    },
    "gps_telemetry": [
        {
            "timestamp": "2024-05-19T21:42:00+00:00",
            "lat": 1.2901,
            "lng": 103.8452,
            "speed_kmh": 32,
            "status": "en_route",
        },
        {
            "timestamp": "2024-05-19T21:47:00+00:00",
            "lat": 1.3125,
            "lng": 103.8530,
            "speed_kmh": 96,
            "status": "en_route",
        },
        {
            "timestamp": "2024-05-19T21:50:00+00:00",
            "lat": 1.3261,
            "lng": 103.8577,
            "speed_kmh": 108,
            "status": "en_route",
        },
        {
            "timestamp": "2024-05-19T21:52:00+00:00",
            "lat": 1.3352,
            "lng": 103.8601,
            "speed_kmh": 21,
            "status": "harsh_braking",
        },
        {
            "timestamp": "2024-05-19T21:56:00+00:00",
            "lat": 1.3428,
            "lng": 103.8489,
            "speed_kmh": 88,
            "status": "en_route",
        },
        {
            "timestamp": "2024-05-19T21:59:00+00:00",
            "lat": 1.3481,
            "lng": 103.8402,
            "speed_kmh": 18,
            "status": "harsh_braking",
        },
        {
            "timestamp": "2024-05-19T22:03:00+00:00",
            "lat": 1.3509,
            "lng": 103.8352,
            "speed_kmh": 12,
            "status": "arrived_dropoff",
        },
    ],
    "chat_logs": [
        {
            "timestamp": "2024-05-19T21:49:00+00:00",
            "sender": "rider",
            "type": "message",
            "content": "Could you slow down a bit please? You're going really fast.",
        },
        {
            "timestamp": "2024-05-19T21:50:00+00:00",
            "sender": "driver",
            "type": "message",
            "content": "We're late, ma'am. I know this road well, don't worry.",
        },
        {
            "timestamp": "2024-05-19T21:53:00+00:00",
            "sender": "rider",
            "type": "message",
            "content": "That braking was deliberate. Please drive normally or let me out.",
        },
        {
            "timestamp": "2024-05-19T21:54:00+00:00",
            "sender": "driver",
            "type": "message",
            "content": "There was a car cutting in. I had to brake.",
        },
    ],
    "app_events": [
        {
            "timestamp": "2024-05-19T21:52:10+00:00",
            "event_type": "harsh_braking_detected",
            "details": "Deceleration 7.4 m/s² — flagged by the telematics SDK",
        },
        {
            "timestamp": "2024-05-19T21:59:05+00:00",
            "event_type": "harsh_braking_detected",
            "details": "Deceleration 6.9 m/s² — flagged by the telematics SDK",
        },
        {
            "timestamp": "2024-05-19T22:01:00+00:00",
            "event_type": "speed_limit_exceeded",
            "details": "108 km/h in a 90 km/h zone for 40 s",
        },
        {
            "timestamp": "2024-05-19T22:10:00+00:00",
            "event_type": "dispute_filed",
            "details": "Rider selected category 'safety_incident'",
        },
    ],
}


# ---------------------------------------------------------------------------
# DISP-006 — Safety Incident: verbal altercation over the cabin temperature
# ---------------------------------------------------------------------------
# Exercises the TRTC ASR pipeline: a passenger recording captured inside the
# trip window, transcribed into speaker turns, scored for hostility and handed
# to the Evidence Engine, the Fraud Agent and the Judge. Safety incidents are
# always outside the autonomy boundary, so the expected outcome is escalation
# with the transcript attached to the reviewer's packet.
#
# Triage: pinned HIGH (not CRITICAL) — a verbal altercation is a serious
# conduct matter but not an immediate physical threat, so it must queue behind
# DISP-007 while still jumping ahead of every standard ticket.

DISP_006: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-006",
        "trip_id": "TRIP-2026-11877",
        "filed_by": "rider",
        "dispute_type": "safety_incident",
        "description": (
            "I asked the driver to lower the air-conditioning because the cabin was "
            "uncomfortably hot. He refused aggressively, started shouting at me and insulted me "
            "for the rest of the ride. I recorded the whole argument on my phone. No passenger "
            "should be spoken to like that for asking to be comfortable — I want this driver "
            "reprimanded."
        ),
        "filed_at": "2026-09-18T23:55:00+08:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-4471",
        "name": "Priya Menon",
        "account_age_days": 640,
        "total_trips": 96,
        "avg_rating": 4.8,
        "dispute_history": {"total_disputes": 1, "upheld": 1, "rejected": 0},
        "fraud_flags": 0,
        "payment_method": "visa_8891",
    },
    "driver_profile": {
        "driver_id": "D-77312",
        "name": "Sulaiman bin Osman",
        "account_age_days": 420,
        "total_trips": 1180,
        "avg_rating": 4.1,
        "dispute_history": {"total_disputes": 3, "upheld_against": 2, "rejected": 1},
        "fraud_flags": 1,
        "vehicle": "Honda HR-V (SJB 7731 X)",
    },
    "trip_data": {
        "trip_id": "TRIP-2026-11877",
        "rider_id": "R-4471",
        "driver_id": "D-77312",
        "pickup_location": {"name": "Clarke Quay MRT", "lat": 1.2886, "lng": 103.8460},
        "dropoff_location": {"name": "Ang Mo Kio Ave 3", "lat": 1.3691, "lng": 103.8454},
        "trip_start_time": "2026-09-18T23:28:00+08:00",
        "trip_end_time": "2026-09-18T23:49:00+08:00",
        "actual_distance_km": 12.4,
        "actual_duration_min": 21,
        "fare_estimate": 22.00,
        "fare_charged": 22.00,
    },
    "gps_telemetry": [
        {"timestamp": "2026-09-18T23:28:00+08:00", "lat": 1.2886, "lng": 103.8460, "speed_kmh": 0, "status": "trip_start"},
        {"timestamp": "2026-09-18T23:35:00+08:00", "lat": 1.3120, "lng": 103.8471, "speed_kmh": 74, "status": "en_route"},
        {"timestamp": "2026-09-18T23:41:00+08:00", "lat": 1.3340, "lng": 103.8462, "speed_kmh": 88, "status": "en_route"},
        {"timestamp": "2026-09-18T23:44:00+08:00", "lat": 1.3521, "lng": 103.8459, "speed_kmh": 15, "status": "harsh_braking"},
        {"timestamp": "2026-09-18T23:49:00+08:00", "lat": 1.3691, "lng": 103.8454, "speed_kmh": 0, "status": "completed"},
    ],
    "chat_logs": [
        {"timestamp": "2026-09-18T23:36:00+08:00", "sender": "rider", "type": "message", "content": "Hi, could you turn the air-con down a little? It is very warm in the back."},
        {"timestamp": "2026-09-18T23:37:00+08:00", "sender": "driver", "type": "message", "content": "It is my car, I decide the temperature. Deal with it."},
        {"timestamp": "2026-09-18T23:39:00+08:00", "sender": "rider", "type": "message", "content": "I am just asking politely — you do not need to shout at me."},
        {"timestamp": "2026-09-18T23:50:00+08:00", "sender": "rider", "type": "message", "content": "I have recorded the whole argument, I am filing a safety report."},
    ],
    "app_events": [
        {"timestamp": "2026-09-18T23:41:00+08:00", "event_type": "safety_recording_started", "details": "Rider activated the in-app safety recorder; 8 s captured."},
        {"timestamp": "2026-09-18T23:44:00+08:00", "event_type": "harsh_braking_detected", "details": "Harsh braking logged at 88 km/h on the CTE exit."},
        {"timestamp": "2026-09-18T23:49:00+08:00", "event_type": "trip_completed", "details": "Trip completed. 12.4 km, 21 min. Fare $22.00 charged."},
        {"timestamp": "2026-09-18T23:55:00+08:00", "event_type": "safety_complaint_filed", "details": "Rider filed a safety complaint (verbal altercation / AC temperature) with an audio recording attached."},
    ],
    "media_attachments": [
        {
            "attachment_id": "media-disp006-audio",
            "media_type": "audio",
            "url": "/assets/miora/disp006_arguement.mp3",
            "uploaded_by": "rider",
            "captured_at": "2026-09-18T23:41:00+08:00",
            "device_model": "in-app safety recorder (iPhone 14)",
            "gps_lat": 1.3340,
            "gps_lng": 103.8462,
            "exif_present": True,
            "ai_generated_probability": 0.02,
            "duration_s": 8.2,
            "local_path": "../frontend/public/assets/miora/disp006_arguement.mp3",
            "asset_key": "disp006_arguement",
            "caption": "Covert cabin recording of the air-conditioning argument during the trip",
            # Scripted dialogue for the deterministic ASR: the same file always
            # transcribes to the same transcript, so the ruling is replayable.
            # With live TRTC credentials this hint is ignored and the real
            # waveform is transcribed instead.
            "transcript_hint": (
                "rider: Could you please lower the air-conditioning? It is really hot back here. | "
                "driver: No! I decide the temperature in my own car, you stupid passenger. | "
                "rider: Please, I am only asking you to turn it down a little. Why are you shouting at me? | "
                "driver: Shut up and sit there! Keep arguing and I will find you after this trip!"
            ),
        }
    ],
    # --- Phase 3.2: triage band + reviewer directives ----------------------
    "sla_priority": "high",
    "sla_priority_reason": (
        "Verbal-altercation safety escalation: the attached recording captures sustained "
        "shouting and insults, so the ticket is fast-tracked — but it is not an immediate "
        "physical threat, so it sits below CRITICAL."
    ),
    "financial_value": 22.00,
    "financial_note": "Fare charged, plus a goodwill voucher on review",
    "intake": "incoming",
    "escalation_directives": [
        "Issue a written apology note to the rider on behalf of the platform.",
        "Reprimand the driver and record a formal conduct warning on their profile.",
        "Release a goodwill ride voucher to the rider for the distress caused.",
        "Review the driver against the Driver Conduct & Anti-Harassment policy before their next trip.",
    ],
    "cancellation_policy": {
        "free_wait_time_min": 5,
        "cancellation_fee_after_wait": 5.00,
        "no_show_threshold_min": 8,
        "fee_goes_to": "driver_compensation",
    },
}


# ---------------------------------------------------------------------------
# DISP-007 — Critical Safety Incident: physical / sexual harassment (video)
# ---------------------------------------------------------------------------
# The most serious ticket in the queue, and the one the reviewer portal is
# built around. A female passenger films from the back seat at night; the clip
# is decoded at 1 fps and the Vision Agent flags both the physical boundary
# violation and the low-light capture conditions.
#
# Expected behaviour, end to end:
#   * SLA & Routing Manager assigns CRITICAL (highest band, queue position 1)
#   * the Judge triggers the escalation protocol — confidence floor overridden,
#     `escalated_to_human` is forced by the category rule
#   * the packet carries the immediate actions: instant suspension, safety
#     ticket, referral to human investigation / law-enforcement support

DISP_007: dict[str, Any] = {
    "dispute_ticket": {
        "dispute_id": "DISP-007",
        "trip_id": "TRIP-2026-12140",
        "filed_by": "rider",
        "dispute_type": "safety_incident",
        "description": (
            "While he was driving, the driver reached back over the seat and touched my thigh. "
            "I froze and then recorded him on my phone from the back seat — it is dark, but you "
            "can clearly see his arm coming back toward me. I want his account suspended "
            "immediately and this referred to the police. I am frightened to book another Ryde."
        ),
        "filed_at": "2026-09-20T23:20:00+08:00",
        "status": "open",
    },
    "rider_profile": {
        "rider_id": "R-8890",
        "name": "Amira Yusof",
        "account_age_days": 210,
        "total_trips": 64,
        "avg_rating": 4.9,
        "dispute_history": {"total_disputes": 0, "upheld": 0, "rejected": 0},
        "fraud_flags": 0,
        "payment_method": "credit_card",
    },
    "driver_profile": {
        "driver_id": "D-2290",
        "name": "Zulkifli bin Omar",
        "account_age_days": 980,
        "total_trips": 2640,
        "avg_rating": 4.72,
        "dispute_history": {"total_disputes": 2, "upheld_against": 1, "rejected": 1},
        "fraud_flags": 1,
        "vehicle": "Honda HR-V (SKT 2290 B)",
    },
    "trip_data": {
        "trip_id": "TRIP-2026-12140",
        "rider_id": "R-8890",
        "driver_id": "D-2290",
        "pickup_location": {"name": "Somerset 313", "lat": 1.3010, "lng": 103.8380},
        "dropoff_location": {"name": "Serangoon Nex", "lat": 1.3550, "lng": 103.8710},
        "trip_start_time": "2026-09-20T23:05:00+08:00",
        "trip_end_time": "2026-09-20T23:29:00+08:00",
        "actual_distance_km": 9.8,
        "actual_duration_min": 24,
        "fare_estimate": 18.50,
        "fare_charged": 18.50,
    },
    "gps_telemetry": [
        {"timestamp": "2026-09-20T23:05:00+08:00", "lat": 1.3010, "lng": 103.8380, "speed_kmh": 0, "status": "trip_start"},
        {"timestamp": "2026-09-20T23:13:00+08:00", "lat": 1.3220, "lng": 103.8510, "speed_kmh": 38, "status": "en_route"},
        {"timestamp": "2026-09-20T23:18:00+08:00", "lat": 1.3340, "lng": 103.8570, "speed_kmh": 44, "status": "en_route"},
        {"timestamp": "2026-09-20T23:22:00+08:00", "lat": 1.3410, "lng": 103.8630, "speed_kmh": 42, "status": "en_route"},
        {"timestamp": "2026-09-20T23:29:00+08:00", "lat": 1.3550, "lng": 103.8710, "speed_kmh": 0, "status": "completed"},
    ],
    "chat_logs": [
        {"timestamp": "2026-09-20T23:21:00+08:00", "sender": "rider", "type": "message", "content": "Please keep your hands on the wheel."},
        {"timestamp": "2026-09-20T23:22:00+08:00", "sender": "driver", "type": "message", "content": "Relax, I am just being friendly."},
        {"timestamp": "2026-09-20T23:30:00+08:00", "sender": "rider", "type": "message", "content": "You touched me. I have it on video and I am reporting you."},
    ],
    "app_events": [
        {"timestamp": "2026-09-20T23:19:00+08:00", "event_type": "safety_recording_started", "details": "Rider activated the in-app safety recorder from the back seat; 12 s captured."},
        {"timestamp": "2026-09-20T23:29:00+08:00", "event_type": "trip_completed", "details": "Trip completed. 9.8 km, 24 min. Fare $18.50 charged."},
        {"timestamp": "2026-09-20T23:31:00+08:00", "event_type": "evidence_uploaded", "details": "Rider uploaded 1 video as evidence (disp007_harassment.mp4, 12 s, 768x1258 portrait). Capture time 23:31."},
        {"timestamp": "2026-09-20T23:34:00+08:00", "event_type": "safety_complaint_filed", "details": "Rider filed a CRITICAL safety complaint alleging physical/sexual harassment."},
    ],
    "media_attachments": [
        {
            "attachment_id": "media-disp007-video",
            "media_type": "video",
            "url": "/assets/miora/disp007_harassment.mp4",
            "uploaded_by": "rider",
            "captured_at": "2026-09-20T23:31:00+08:00",
            "device_model": "iPhone 14 — covert back-seat recording",
            "gps_lat": 1.3550,
            "gps_lng": 103.8710,
            "exif_present": True,
            "ai_generated_probability": 0.04,
            "duration_s": 12.27,
            "local_path": "../frontend/public/assets/miora/disp007_harassment.mp4",
            "asset_key": "disp007_harassment",
            "caption": (
                "Low-light back-seat recording — the driver reaches back over the seat and "
                "touches the passenger's thigh while the car is moving"
            ),
        }
    ],
    # --- Phase 3.2: triage band + reviewer directives ----------------------
    "financial_value": 0.0,
    "financial_note": "Non-monetary — rider safety; no fare dispute",
    "intake": "incoming",
    "escalation_directives": [
        "Recommend instant suspension of the driver account pending investigation.",
        "Open a priority safety ticket with the Trust & Safety team.",
        "Refer to human investigation with law-enforcement support — alleged physical/sexual harassment.",
        "Proactively contact the rider with support resources and preserve the recording as evidence.",
    ],
    "cancellation_policy": {
        "free_wait_time_min": 5,
        "cancellation_fee_after_wait": 5.00,
        "no_show_threshold_min": 8,
        "fee_goes_to": "driver_compensation",
    },
}


CASE_REGISTRY: dict[str, dict[str, Any]] = {
    "DISP-001": DISP_001,
    "DISP-002": DISP_002,
    "DISP-003": DISP_003,
    "DISP-004": DISP_004,
    "DISP-005": DISP_005,
    "DISP-006": DISP_006,
    "DISP-007": DISP_007,
}

#: Miora-generated mock evidence rendered by the UI (``frontend/public/assets/miora``).
#: Image-only: audio and video payloads are played back by the Evidence panel's
#: own <audio>/<video> players straight from the dossier attachment, so DISP-006
#: (audio) and DISP-007 (video) carry no still image here.
MIORA_ASSETS: dict[str, list[str]] = {
    "DISP-001": ["/assets/miora/disp001_route_deviation.png"],
    "DISP-002": ["/assets/miora/disp002_no_show_chat.png"],
    "DISP-003": ["/assets/miora/disp003_fake_spill.png"],
    "DISP-004": ["/assets/miora/disp004_genuine_spill.png"],
}

#: Phase 3.2: queue metadata the Reviewer Portal sorts and badges on.
#: ``intake`` splits the seeded dataset into a live queue and a carried-over
#: history so the dashboard opens with both tabs populated.
CASE_META: dict[str, dict[str, Any]] = {
    "DISP-001": {
        "title": "Route Deviation — Raffles Place to Paya Lebar",
        "blurb": "Rider says the driver detoured north and inflated the fare from $20 to $28.",
        "expected_ruling": "PARTIAL REFUND — ~$5.60 (traffic justified part of the detour)",
        "financial_value": 8.00,
        "financial_note": "Fare difference under dispute",
        "intake": "historical",
    },
    "DISP-002": {
        "title": "No-Show Charge — Tiong Bahru Plaza",
        "blurb": "Rider claims the driver never arrived but was still charged the $5 no-show fee.",
        "expected_ruling": "UPHELD — driver waited the full 8-minute window and tried to call",
        "financial_value": 5.00,
        "financial_note": "No-show cancellation fee",
        "intake": "historical",
    },
    "DISP-003": {
        "title": "Property Damage — disputed cleaning fee",
        "blurb": "Driver claims $60 for a spilled drink; the photo fails forensic validation.",
        "expected_ruling": "NO ACTION — fee waived, claim escalated to Fraud & Safety",
        "financial_value": 60.00,
        "financial_note": "Cleaning fee claimed",
        "intake": "historical",
    },
    "DISP-004": {
        "title": "Property Damage — verified spill",
        "blurb": "Driver claims $60 with a photo taken at dropoff; rider admits the spill.",
        "expected_ruling": "COMPENSATE DRIVER — $60 cleaning fee awarded",
        "financial_value": 60.00,
        "financial_note": "Cleaning fee claimed",
        "intake": "incoming",
    },
    "DISP-005": {
        "title": "Safety Incident — alleged dangerous driving",
        "blurb": (
            "Rider alleges speeding and deliberate brake-checking; telematics logged two "
            "harsh-braking events. CRITICAL — fast-tracked and always human-reviewed."
        ),
        "expected_ruling": "ESCALATED TO HUMAN — safety incidents are never auto-resolved",
        "financial_value": 24.50,
        "financial_note": "Fare charged",
        "intake": "incoming",
    },
    "DISP-006": {
        "title": "Safety Incident — verbal altercation on tape",
        "blurb": (
            "Rider asks for a cooler cabin; the driver shouts back and insults her. The 8 s "
            "covert recording is transcribed by TRTC ASR. HIGH — fast-tracked, always human-reviewed."
        ),
        "expected_ruling": (
            "ESCALATED TO HUMAN — transcript shows shouting, insults and a threat (hostility ~1.0)"
        ),
        "financial_value": 22.00,
        "financial_note": "Fare charged, plus a goodwill voucher on review",
        "intake": "incoming",
    },
    "DISP-007": {
        "title": "Critical Safety Incident — physical/sexual harassment on video",
        "blurb": (
            "A passenger films from the back seat at night: the driver reaches back and touches "
            "her thigh. The 12 s portrait clip is sampled at 1 keyframe/s and flagged as low-light footage. "
            "CRITICAL — top of queue."
        ),
        "expected_ruling": (
            "ESCALATED TO HUMAN — instant suspension, safety ticket and law-enforcement referral"
        ),
        "financial_value": 0.0,
        "financial_note": "Non-monetary — rider safety; no fare dispute",
        "intake": "incoming",
    },
}


def list_cases() -> list[CaseSummary]:
    """Describe every built-in case for the UI case picker.

    Phase 3.2: the descriptor also carries the queue metadata the Reviewer
    Portal needs *before* a run exists — money at stake, whether the ticket is
    incoming or carried over, and the triage band intake pinned (or that the
    SLA & Routing Manager will derive from the dispute type).
    """
    summaries: list[CaseSummary] = []
    for case_id, payload in CASE_REGISTRY.items():
        meta = CASE_META[case_id]
        ticket = payload["dispute_ticket"]
        attachments = payload.get("media_attachments") or []
        sla_priority = payload.get("sla_priority")
        if not sla_priority:
            dtype = str(ticket["dispute_type"])
            if dtype == "safety_incident":
                sla_priority = "critical"
            elif dtype in {"property_damage", "fare_dispute"}:
                sla_priority = "high"
            else:
                sla_priority = "normal"

        summaries.append(
            CaseSummary(
                case_id=case_id,
                dispute_id=ticket["dispute_id"],
                dispute_type=ticket["dispute_type"],
                title=meta["title"],
                blurb=meta["blurb"],
                expected_ruling=meta["expected_ruling"],
                filed_by=ticket["filed_by"],
                filed_at=ticket["filed_at"],
                multimodal=bool(attachments),
                evidence_assets=MIORA_ASSETS.get(case_id, []),
                financial_value=float(meta.get("financial_value", 0.0)),
                financial_note=meta.get("financial_note"),
                intake=meta.get("intake", "incoming"),
                sla_priority=sla_priority,
                evidence_kind=attachments[0]["media_type"] if attachments else None,
            )
        )
    return summaries


def get_case(case_id: str) -> DisputeCase:
    """Load and validate a built-in case."""
    try:
        payload = CASE_REGISTRY[case_id]
    except KeyError as exc:
        raise KeyError(
            f"Unknown case '{case_id}'. Available: {', '.join(sorted(CASE_REGISTRY))}"
        ) from exc
    return DisputeCase.model_validate(payload)


def dump_case_json(case_id: str) -> str:
    """Pretty-print a case (handy for the README and for cURL demos)."""
    return json.dumps(CASE_REGISTRY[case_id], indent=2)
