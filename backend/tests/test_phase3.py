"""Phase 3 regression suite: TRTC ASR, video keyframes, upload endpoints, Miora assets.

Run from the repository root::

    python3 -m pytest backend/tests -q

The suite is deliberately credential-free: it exercises the deterministic
simulated ASR and the ffmpeg keyframe pipeline, so it passes in CI exactly the
same way it passes on a judge's laptop.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import cases as cases_mod  # noqa: E402
import main as main_mod  # noqa: E402
import trtc_client as asr  # noqa: E402
import vision_utils as vu  # noqa: E402
from config import get_settings  # noqa: E402
from models import DisputeCase, MediaAttachment  # noqa: E402

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    with TestClient(main_mod.app) as c:
        yield c


@pytest.fixture(scope="module")
def settings():
    return get_settings()


@pytest.fixture(scope="module")
def sample_audio() -> Path:
    p = Path(BACKEND) / "data" / "uploads" / "samples" / "disp006_argument.wav"
    if not p.exists():
        pytest.skip("sample audio not generated — run scripts/generate_mock_assets.py")
    return p


@pytest.fixture(scope="module")
def sample_video() -> Path:
    p = Path(BACKEND) / "data" / "uploads" / "samples" / "disp007_cabin.mp4"
    if not p.exists():
        pytest.skip("sample video not generated — run scripts/generate_mock_assets.py")
    return p


def _case(case_id: str) -> DisputeCase:
    return cases_mod.get_case(case_id)


def _attachment(case_id: str, media_type: str) -> MediaAttachment:
    case = _case(case_id)
    for att in case.media_attachments:
        if att.media_type == media_type:
            return att
    raise AssertionError(f"{case_id} has no {media_type} attachment")


# ---------------------------------------------------------------------------
# 1. ASR scoring and segmentation
# ---------------------------------------------------------------------------


def test_score_text_flags_explicit_threat():
    score, threat, keywords = asr._score_text(
        "I will find you after this trip, I know where you live!"
    )
    assert threat is True
    assert score >= 0.8
    assert "i know where you live" in keywords


def test_score_text_is_quiet_on_polite_speech():
    score, threat, keywords = asr._score_text("Thanks for the ride, have a good evening.")
    assert threat is False
    assert score < 0.2
    assert keywords == []


def test_score_text_flags_abuse_without_threat():
    score, threat, _ = asr._score_text("You are so stupid, shut up.")
    assert threat is False
    assert score >= 0.3


def test_simulated_asr_transcribes_the_scripted_argument(settings):
    att = _attachment("DISP-006", "audio")
    provider = asr.SimulatedASRClient(settings)
    transcript = asyncio.run(provider.transcribe(att))

    assert transcript.attachment_id == att.attachment_id
    assert len(transcript.segments) == 5
    assert transcript.threat_detected is True
    assert transcript.hostility_score >= 0.8
    assert any("where you live" in s.text for s in transcript.segments)
    # Turns are laid out end to end across the clip, never overlapping backwards.
    assert transcript.segments[0].start_s == 0.0
    for prev, nxt in zip(transcript.segments, transcript.segments[1:]):
        assert nxt.start_s >= prev.start_s
    assert transcript.segments[-1].end_s <= transcript.duration_s + 0.01


def test_asr_provider_falls_back_to_simulation_without_credentials(settings):
    provider = asr.build_asr_provider(settings)
    # No TRTC keys in the test environment -> deterministic simulation.
    assert isinstance(provider, (asr.SimulatedASRClient, asr.TRTCASRClient))


def test_probe_audio_duration_matches_the_case_dossier(sample_audio):
    duration = asr.probe_audio_duration(sample_audio)
    assert 40.0 <= duration <= 44.0


# ---------------------------------------------------------------------------
# 2. Video keyframe extraction
# ---------------------------------------------------------------------------


def test_ffmpeg_is_the_active_backend():
    assert vu.ffmpeg_available() is True
    assert vu.backend_name() in {"ffmpeg", "opencv"}


def test_probe_reads_video_metadata(sample_video):
    info = vu.probe(sample_video)
    assert info["duration_s"] == pytest.approx(6.0, abs=0.5)
    assert info["width"] == 640
    assert info["height"] == 360


def test_extract_frames_samples_one_frame_per_second(sample_video, tmp_path):
    frames = vu.extract_frames(sample_video, tmp_path, fps=1.0, max_frames=12)
    assert 5 <= len(frames) <= 7  # a 6 s clip yields ~6 keyframes
    for frame in frames:
        assert Path(frame.path).exists()
        assert frame.path.endswith(".jpg")
    # one frame per second, in order
    assert [round(f.timestamp_s) for f in frames] == list(range(len(frames)))


def test_extract_frames_respects_the_cap(sample_video, tmp_path):
    frames = vu.extract_frames(sample_video, tmp_path / "capped", fps=1.0, max_frames=3)
    assert len(frames) == 3


def test_analyse_video_reports_frames_and_duration(sample_video, settings):
    analysis = vu.analyse_video(sample_video, settings, "test-clip")
    assert analysis.attachment_id == "test-clip"
    assert analysis.frames_extracted >= 5
    assert analysis.duration_s == pytest.approx(6.0, abs=0.5)
    assert analysis.engine in {"ffmpeg", "opencv"}
    assert all(f.mean_luminance is None or 0.0 <= f.mean_luminance <= 1.0 for f in analysis.frames)


def test_analyse_video_rejects_a_non_video_file(tmp_path, settings):
    junk = tmp_path / "notavideo.mp4"
    junk.write_bytes(b"this is definitely not an mp4")
    with pytest.raises(vu.VideoProcessingError):
        vu.analyse_video(junk, settings, "junk")


# ---------------------------------------------------------------------------
# 3. Upload endpoints
# ---------------------------------------------------------------------------


def test_upload_audio_transcribes_and_attaches(client, sample_audio):
    with sample_audio.open("rb") as fh:
        res = client.post(
            "/upload-audio",
            files={"file": ("argument.wav", fh, "audio/wav")},
            data={
                "case_id": "DISP-006",
                "captured_at": "2026-09-18T23:41:00+08:00",
                # Simulation knob: the deterministic ASR needs a script to hear.
                "transcript_hint": (
                    "driver: You stupid passenger, shut up and sit there! | "
                    "driver: I will find you after this trip, I know where you live!"
                ),
            },
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["media_type"] == "audio"
    assert body["dispute_id"] == "DISP-006"
    assert body["web_path"].startswith("/media/")
    assert body["transcript"]["threat_detected"] is True
    assert len(body["transcript"]["segments"]) == 2
    assert body["duration_s"] == pytest.approx(42.0, abs=2.0)

    # The registry remembers it, so the next run arbitrates the real payload.
    index = client.get("/media/uploads").json()
    assert "DISP-006" in index["cases"]


def test_upload_audio_without_a_hint_still_transcribes(client, sample_audio):
    """No TRTC keys and no script: the clip is still transcribed, just cleanly."""
    with sample_audio.open("rb") as fh:
        res = client.post(
            "/upload-audio",
            files={"file": ("quiet.wav", fh, "audio/wav")},
            data={"case_id": "DISP-005"},
        )
    assert res.status_code == 200, res.text
    transcript = res.json()["transcript"]
    assert transcript["segments"]
    assert transcript["threat_detected"] is False


def test_upload_video_extracts_keyframes(client, sample_video):
    with sample_video.open("rb") as fh:
        res = client.post(
            "/upload-video",
            files={"file": ("cabin.mp4", fh, "video/mp4")},
            data={"case_id": "DISP-007", "captured_at": "2026-09-20T21:36:00+08:00"},
        )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["media_type"] == "video"
    assert body["video"]["frames_extracted"] >= 5
    assert body["video"]["duration_s"] == pytest.approx(6.0, abs=0.5)


def test_upload_rejects_a_mismatched_payload(client, sample_video):
    with sample_video.open("rb") as fh:
        res = client.post(
            "/upload-audio",
            files={"file": ("cabin.mp4", fh, "video/mp4")},
            data={"case_id": "DISP-006"},
        )
    assert res.status_code == 415


def test_uploaded_media_is_served_over_http(client, sample_video):
    with sample_video.open("rb") as fh:
        body = client.post(
            "/upload-video",
            files={"file": ("cabin.mp4", fh, "video/mp4")},
            data={"case_id": "DISP-007"},
        ).json()
    served = client.get(body["web_path"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("video/")


# ---------------------------------------------------------------------------
# 4. End-to-end pipelines
# ---------------------------------------------------------------------------


def _resolve(client, case_id: str) -> dict:
    res = client.post("/resolve", json={"case_id": case_id})
    assert res.status_code == 200, res.text
    return res.json()


def test_audio_pipeline_escalates_the_safety_case(client):
    """Prompt3 test 1: ASR transcribes the threat and the judge escalates."""
    r = _resolve(client, "DISP-006")

    assert r["status"] == "escalated"
    assert r["routing"]["priority"] == "critical"
    assert r["routing"]["queue"] == "safety_escalations"

    audio = [v for v in r["vision"] if v["media_kind"] == "audio"]
    assert audio, "no audio finding was produced"
    transcript = audio[0]["transcript"]
    assert transcript["engine"] == "simulated"
    assert transcript["threat_detected"] is True
    assert transcript["hostility_score"] >= 0.8
    assert len(transcript["segments"]) == 5
    assert transcript["source_url"]

    # The transcript reached the fact table...
    keys = {f["key"] for f in r["evidence"]["facts"]}
    assert any(k.startswith("audio_") and k.endswith("_threat") for k in keys)
    # ...the fraud agent...
    assert any(
        s["signal"] == "abusive_or_threatening_language"
        for s in r["evidence"]["risk_signals"]
    )
    assert "Safety" in r["fraud"]["recommended_action"]
    # ...and the judge's ruling.
    assert r["ruling"]["decision"] == "escalate_to_human"
    assert r["ruling"]["escalated"] is True
    assert any("TRTC ASR" in k for k in r["ruling"]["key_findings"])
    assert r["escalation"] is not None


def test_video_pipeline_extracts_frames_and_cites_them(client):
    """Prompt3 test 2: frames are extracted and the ruling cites visual evidence."""
    r = _resolve(client, "DISP-007")

    assert r["status"] == "resolved"
    video = [v for v in r["vision"] if v["media_kind"] == "video"]
    assert video, "no video finding was produced"
    analysis = video[0]["video"]

    assert analysis["frames_extracted"] >= 5
    assert analysis["duration_s"] == pytest.approx(6.0, abs=0.5)
    assert analysis["engine"] in {"ffmpeg", "opencv"}
    assert analysis["source_url"]
    assert len(analysis["frames"]) == analysis["frames_extracted"]
    # No timeout / decode failure surfaced as an anomaly.
    assert not any("decoded" in a for a in analysis["anomalies"])

    # Keyframes are reachable over HTTP, so the UI never renders a broken strip.
    for frame in analysis["frames"][:3]:
        assert client.get(frame["path"]).status_code == 200

    keys = {f["key"] for f in r["evidence"]["facts"]}
    assert any(k.startswith("video_") and k.endswith("_frames") for k in keys)

    assert r["ruling"]["decision"] == "compensate_driver"
    assert r["ruling"]["amount"] == pytest.approx(60.0)
    cited = " ".join(r["ruling"]["key_findings"]) + " " + r["ruling"]["reasoning"]
    assert "keyframe" in cited.lower()
    assert "liquid_spill" in cited


# ---------------------------------------------------------------------------
# 5. Case registry + Miora asset bindings
# ---------------------------------------------------------------------------


def test_all_seven_cases_arbitrate_without_error(client):
    for case_id in ["DISP-001", "DISP-002", "DISP-003", "DISP-004", "DISP-005", "DISP-006", "DISP-007"]:
        r = _resolve(client, case_id)
        assert r["errors"] == [], f"{case_id} reported errors: {r['errors']}"
        assert r["ruling"] is not None, f"{case_id} produced no ruling"
        assert r["ruling"]["decision"]


def test_case_library_exposes_the_new_multimodal_dossiers(client):
    body = client.get("/cases").json()
    ids = {c["case_id"] for c in body["cases"]}
    assert {"DISP-006", "DISP-007"} <= ids
    by_id = {c["case_id"]: c for c in body["cases"]}
    assert by_id["DISP-006"]["dispute_type"] == "safety_incident"
    assert by_id["DISP-007"]["dispute_type"] == "property_damage"


def test_miora_assets_are_bound_and_present():
    """Every asset referenced by cases.py must exist under frontend/public."""
    public = BACKEND.parent / "frontend" / "public"
    for case_id, assets in cases_mod.MIORA_ASSETS.items():
        assert assets, f"{case_id} has no Miora asset bound"
        for asset in assets:
            assert asset.startswith("/assets/miora/"), f"{asset} is not a Miora path"
            assert (public / asset.lstrip("/")).exists(), f"missing asset {asset}"


def test_miora_manifest_records_every_prompt():
    manifest = BACKEND.parent / "frontend" / "public" / "assets" / "miora" / "manifest.json"
    assert manifest.exists(), "Miora manifest missing"
    data = json.loads(manifest.read_text())
    assert isinstance(data, dict) and data


def test_agent_avatars_exist_for_every_role():
    """The UI renders one avatar per agent role — none may 404."""
    roles = {
        "orchestrator",
        "sla_router",
        "asr",
        "evidence_collection",
        "evidence",
        "fraud",
        "policy",
        "vision",
        "rider_advocate",
        "driver_advocate",
        "judge",
        "escalation",
        "learning",
    }
    avatar_dir = BACKEND.parent / "frontend" / "public" / "assets" / "miora" / "agents"
    for role in roles:
        assert (avatar_dir / f"{role}.png").exists(), f"missing avatar for {role}"


def test_health_reports_the_phase3_backends(client):
    body = client.get("/health").json()
    assert body["asr_engine"] in {"trtc", "simulated"}
    assert body["video_backend"] in {"ffmpeg", "opencv", "unavailable"}
    assert isinstance(body["ffmpeg_available"], bool)
