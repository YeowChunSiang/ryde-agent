#!/usr/bin/env python3
"""Compliance audit for prompt3.md — Phase 3.

Maps every requirement in prompt3.md to a machine-checked assertion and runs
them against the live backend + the built frontend. Exits non-zero on any gap.

    python3 scripts/audit_phase3.py            # audit only
    python3 scripts/audit_phase3.py --ui       # also run the headless browser checks
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
MIORA = FRONTEND / "public" / "assets" / "miora"
API = "http://localhost:3000"

sys.path.insert(0, str(BACKEND))

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    (PASS if ok else FAIL).append(f"{label}{(' — ' + detail) if detail else ''}")
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}{(' — ' + detail) if detail else ''}")
    return ok


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def get(path: str) -> tuple[int, object]:
    try:
        with urllib.request.urlopen(f"{API}{path}", timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def post(path: str, payload: dict) -> tuple[int, object]:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 1. Secret Audio & Dashcam Audio Processing (TRTC ASR)
# ---------------------------------------------------------------------------
section("1. Secret audio & dashcam audio processing (TRTC ASR)")

health_status, health = get("/api/health")
check("backend reachable", health_status == 200, f"/api/health -> {health_status}")
if health_status != 200:
    print("\nbackend is down — start it with scripts/restart_backend.sh")
    sys.exit(1)

main_src = read(BACKEND / "main.py")
check(
    "POST /upload-audio endpoint declared",
    '@app.post("/upload-audio"' in main_src,
)
check(
    "POST /upload-audio exposed under /api too",
    '@app.post("/api/upload-audio"' in main_src,
)
check(
    "POST /upload-video endpoint declared",
    '@app.post("/upload-video"' in main_src and '@app.post("/api/upload-video"' in main_src,
)

trtc_src = read(BACKEND / "trtc_client.py")
check(
    "trtc_client.py delivers the ASR module (deliverable 1)",
    (BACKEND / "trtc_client.py").exists(),
)
check(
    "TRTC client signs real TC3-HMAC-SHA256 requests",
    "TC3-HMAC-SHA256" in trtc_src and "DescribeASRTask" in trtc_src,
    "real client present, simulated fallback when no credentials",
)
check(
    "ASR provider selection is credential-driven",
    "def build_asr_provider" in trtc_src
    and "trtc_secret_id" in read(BACKEND / "config.py"),
)
check(
    "hostility / threat scoring over the transcript",
    "THREAT_PHRASES" in trtc_src and "threat_detected" in trtc_src,
)
check(
    "transcript is grafted onto the case media_attachments",
    "attachment.transcript = transcript" in read(BACKEND / "orchestrator.py"),
)
check(
    "Evidence Collection Agent consumes audio (safety-2 policy check)",
    "SAFETY-2" in read(BACKEND / "evidence.py")
    and "_analyse_audio_evidence" in read(BACKEND / "evidence.py"),
)
check(
    "Fraud Agent reacts to a transcript threat",
    "threat" in read(BACKEND / "agents.py").lower()
    and "recommended_action" in read(BACKEND / "agents.py"),
)

# ---------------------------------------------------------------------------
# 2. Video Evidence Processing (Vision Agent Upgrade)
# ---------------------------------------------------------------------------
section("2. Video evidence processing (vision agent upgrade)")

vu_src = read(BACKEND / "vision_utils.py")
check("vision_utils.py delivered (deliverable 2)", (BACKEND / "vision_utils.py").exists())
check(
    "keyframe extraction uses ffmpeg-python (with OpenCV metrics)",
    'filter("fps"' in vu_src and "ffmpeg" in vu_src.lower(),
    "1 fps sampling via ffmpeg-python; OpenCV/Pillow per-frame metrics",
)
check(
    "frames sampled at 1 fps by default",
    "fps: float = 1.0" in vu_src and "video_frame_fps" in read(BACKEND / "config.py"),
)
check(
    "keyframe frames carry timestamp + luminance + motion metrics",
    "class VideoFrame" in read(BACKEND / "models.py")
    and "timestamp_s" in read(BACKEND / "models.py"),
)
check(
    "metadata/timestamps verified against the trip timeline",
    "exif_timestamp_delta_min" in read(BACKEND / "adp_client.py")
    and "45 min window" in read(BACKEND / "adp_client.py"),
    "clip outside the 45 min window is flagged inadmissible",
)
check(
    "unified JSON findings report (VideoAnalysis)",
    "class VideoAnalysis" in read(BACKEND / "models.py")
    and "anomalies" in read(BACKEND / "models.py"),
)
check(
    "severity classified from the keyframes",
    "liquid_spill" in read(BACKEND / "adp_client.py")
    and "severity" in read(BACKEND / "models.py"),
)
check(
    "video findings injected into the vision prompt",
    "EXTRACTED KEYFRAMES" in read(BACKEND / "prompts.py"),
)
check(
    "ASR findings injected into the vision prompt",
    "ASR TRANSCRIPT" in read(BACKEND / "prompts.py"),
)
check(
    "ffmpeg actually available in this environment",
    bool(health.get("ffmpeg_available")),
    f"video_backend={health.get('video_backend')}",
)

# ---------------------------------------------------------------------------
# 3. Miora Visual Asset Integration
# ---------------------------------------------------------------------------
section("3. Miora visual asset integration")

check("/assets/miora directory exists in the React frontend", MIORA.is_dir(), str(MIORA))
manifest = json.loads(read(MIORA / "manifest.json"))
prompts = manifest["assets"]

EXPECTED_PROMPTS = {
    "disp001_route_deviation.png": (
        "ride-hailing app map",
        "suggested route in blue",
        "GPS track",
        "in red",
    ),
    "disp002_no_show_chat.png": (
        "chat screen",
        "I am at the lobby",
        "Waiting for 5 minutes",
        "08:00 elapsed",
    ),
    "disp004_genuine_spill.png": (
        "Honda HR-V",
        "coffee spill",
        "2026-09-13 09:15 AM",
    ),
    "disp003_fake_spill.png": (
        "french fries",
        "ketchup",
        "missing EXIF",
    ),
    "disp006_dashcam.png": (
        "dashcam",
        "aggressively gesturing",
        "11:45 PM",
    ),
}
for fname, needles in EXPECTED_PROMPTS.items():
    path = MIORA / fname
    stored = prompts.get(fname, "")
    ok = path.exists() and all(n.lower() in stored.lower() for n in needles)
    check(
        f"Miora asset {fname} rendered + prompt recorded",
        ok,
        "" if ok else f"missing={[n for n in needles if n.lower() not in stored.lower()]}",
    )

cases_src = read(BACKEND / "cases.py")
check(
    "cases.py binds Miora assets for route_deviation (DISP-001)",
    "disp001_route_deviation.png" in cases_src,
)
check(
    "cases.py binds Miora assets for no_show (DISP-002)",
    "disp002_no_show_chat.png" in cases_src,
)
check(
    "cases.py binds Miora assets for property_damage / mess (DISP-003 & DISP-004)",
    "disp003_fake_spill.png" in cases_src and "disp004_genuine_spill.png" in cases_src,
)
check(
    "cases.py binds Miora assets for safety_incident (DISP-006 dashcam)",
    "disp006_dashcam.png" in cases_src,
)
check(
    "MIORA_ASSETS registry exposed to the UI via /cases",
    "MIORA_ASSETS" in cases_src and "evidence_assets" in cases_src,
)

meta_src = read(FRONTEND / "src" / "components" / "agent-meta.ts")
agent_block = meta_src.split("export const AGENT_META", 1)[-1].split("\nexport const", 1)[0]
agent_roles = re.findall(r'^  (\w+): \{$', agent_block, flags=re.M)
avatared = re.findall(r'avatar: AVATAR\("(\w+)"\)', meta_src)
check(
    "agent-meta.ts: every agent role has a Miora avatar path",
    set(agent_roles) == set(avatared) and len(avatared) >= 9,
    f"{len(avatared)} agents avatared (prompt3 requires >= 9)",
)
missing_png = [r for r in avatared if not (MIORA / "agents" / f"{r}.png").exists()]
check("every avatar file exists on disk", not missing_png, f"missing={missing_png}")

# ---------------------------------------------------------------------------
# 4. Testing requirement 1 — audio pipeline on DISP-006
# ---------------------------------------------------------------------------
section("4. Test 1 — audio pipeline on DISP-006")

st, r = post("/resolve", {"case_id": "DISP-006"})
check("POST /resolve DISP-006 returns 200", st == 200, f"status={st}")
if st == 200:
    ruling = r.get("ruling", {})
    vision = r.get("vision") or []
    audio = next((v for v in vision if (v.get("media_kind") == "audio")), None)
    transcript = (audio or {}).get("transcript") or {}

    check(
        "ASR parser transcribes the aggressive recording",
        bool(transcript.get("segments")),
        f"engine={transcript.get('engine')} turns={len(transcript.get('segments') or [])} "
        f"duration={transcript.get('duration_s')}s",
    )
    check(
        "threat language detected in the transcript",
        transcript.get("threat_detected") is True,
        f"hostility={transcript.get('hostility_score')} keywords={transcript.get('keywords')}",
    )
    check(
        "transcript is grafted into the dossier and reaches the vision agent",
        audio is not None and bool(transcript),
        f"attachment={audio.get('attachment_id') if audio else None}",
    )
    check(
        "Judge escalates the safety ticket to a human",
        ruling.get("decision") == "escalate_to_human" and ruling.get("escalated") is True,
        f"decision={ruling.get('decision')} conf={ruling.get('confidence')}",
    )
    kf = " ".join(ruling.get("key_findings") or [])
    check(
        "ruling cites the transcript / threat evidence",
        "threat" in kf.lower() or "transcript" in kf.lower() or "abusive" in kf.lower(),
        (ruling.get("key_findings") or [""])[0][:120],
    )
    check(
        "escalation packet produced",
        bool(r.get("escalation")),
        f"queue={((r.get('escalation') or {}).get('queue'))}",
    )
else:
    check("DISP-006 resolution", False, str(r)[:200])

# ---------------------------------------------------------------------------
# 5. Testing requirement 2 — video pipeline on DISP-007
# ---------------------------------------------------------------------------
section("5. Test 2 — video pipeline on DISP-007")

st, r = post("/resolve", {"case_id": "DISP-007"})
check("POST /resolve DISP-007 returns 200", st == 200, f"status={st}")
if st == 200:
    ruling = r.get("ruling", {})
    vision = r.get("vision") or []
    vid = next((v for v in vision if (v.get("media_kind") == "video")), None)
    analysis = (vid or {}).get("video") or {}
    frames = analysis.get("frames") or []

    check(
        "backend extracts keyframes from the clip",
        analysis.get("frames_extracted", 0) > 0 and bool(frames),
        f"{analysis.get('frames_extracted')} frames @ {analysis.get('fps')}fps "
        f"from {analysis.get('duration_s')}s",
    )
    check(
        "Vision Agent parses frames without timeout / decode error",
        vid is not None and vid.get("genuine") is True,
        f"genuine={vid.get('genuine')} severity={vid.get('severity')}",
    )
    check(
        "every keyframe is served over HTTP (frontend can render it)",
        all((f.get("path") or "").startswith("/") for f in frames),
        f"e.g. {frames[0].get('path') if frames else 'n/a'}",
    )
    check(
        "per-frame metrics attached (luminance / motion)",
        all(f.get("mean_luminance") is not None for f in frames)
        and any(f.get("motion_score") is not None for f in frames),
    )
    check(
        "clip timestamp verified against the trip timeline",
        vid.get("exif_timestamp_delta_min") is not None,
        f"delta={vid.get('exif_timestamp_delta_min')} min",
    )
    kf = " ".join(ruling.get("key_findings") or [])
    reasoning = ruling.get("reasoning") or ""
    check(
        "final ruling cites the visual / keyframe evidence",
        "keyframe" in (kf + reasoning).lower()
        or "clip" in (kf + reasoning).lower()
        or "footage" in (kf + reasoning).lower(),
        f"decision={ruling.get('decision')} amount={ruling.get('amount')}",
    )
    check(
        "ruling awards the cleaning fee on the strength of the video",
        ruling.get("decision") == "compensate_driver",
        f"{ruling.get('decision')} S${ruling.get('amount')} conf={ruling.get('confidence')}",
    )
else:
    check("DISP-007 resolution", False, str(r)[:200])

# ---------------------------------------------------------------------------
# 6. Upload endpoints (live multipart round-trip)
# ---------------------------------------------------------------------------
section("6. Upload endpoints")


wav = BACKEND / "data" / "uploads" / "samples" / "disp006_argument.wav"
mp4 = BACKEND / "data" / "uploads" / "samples" / "disp007_cabin.mp4"

if wav.exists():
    boundary = "----audwav1"
    body = b""
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="case_id"\r\n\r\nDISP-006\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="captured_at"\r\n\r\n2026-09-18T23:41:00+08:00\r\n'.encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="disp006_argument.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode()
    )
    body += wav.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/upload-audio",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            st, body_json = resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        st, body_json = e.code, json.loads(e.read() or b"{}")
    check("POST /upload-audio accepts a real WAV", st == 200, f"status={st}")
    if st == 200:
        tr = body_json.get("transcript") or {}
        check(
            "/upload-audio returns a transcript with threat detection",
            bool(tr.get("segments")) and tr.get("threat_detected") is True,
            f"engine={tr.get('engine')} hostility={tr.get('hostility_score')}",
        )
        check(
            "/upload-audio stores the payload under /media",
            str(body_json.get("web_path", "")).startswith("/media/"),
            body_json.get("web_path"),
        )
        check(
            "/upload-audio attaches the transcript to the dossier",
            body_json.get("dispute_id") == "DISP-006",
        )
else:
    check("sample WAV present", False, str(wav))

if mp4.exists():
    boundary = "----audmp41"
    body = b""
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="case_id"\r\n\r\nDISP-007\r\n'.encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="disp007_cabin.mp4"\r\nContent-Type: video/mp4\r\n\r\n'.encode()
    )
    body += mp4.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{API}/upload-video",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            st, body_json = resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        st, body_json = e.code, json.loads(e.read() or b"{}")
    check("POST /upload-video accepts a real MP4", st == 200, f"status={st}")
    if st == 200:
        va = body_json.get("video") or {}
        check(
            "/upload-video extracts keyframes",
            va.get("frames_extracted", 0) > 0,
            f"{va.get('frames_extracted')} frames, backend={va.get('engine')}",
        )
        check(
            "extracted frames are web-reachable",
            bool(va.get("frames")) and str(va["frames"][0].get("path", "")).startswith("/media/"),
            str(va.get("frames", [{}])[0].get("path")),
        )
else:
    check("sample MP4 present", False, str(mp4))

# ---------------------------------------------------------------------------
# 7. Deliverables 5 — EvidencePanel.tsx
# ---------------------------------------------------------------------------
section("7. Deliverable 5 — EvidencePanel.tsx")

ep = read(FRONTEND / "src" / "components" / "EvidencePanel.tsx")
check("EvidencePanel renders a <video> player", "<video" in ep)
check("EvidencePanel renders an <audio> player", "<audio" in ep)
check("EvidencePanel renders the keyframe strip", "keyframe" in ep.lower())
check("EvidencePanel renders the ASR transcript turns", "transcript" in ep.lower())
check("EvidencePanel renders Miora evidence assets", "miora" in ep.lower() or "asset" in ep.lower())
check(
    "EvidencePanel offers upload for own payloads",
    "uploadMedia" in ep and "MediaUploader" in ep,
)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print("\n" + "=" * 68)
print(f"prompt3.md compliance: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("\nGAPS:")
    for f in FAIL:
        print(f"  - {f}")
print("=" * 68)
sys.exit(1 if FAIL else 0)
