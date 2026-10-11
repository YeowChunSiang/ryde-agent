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
import evidence as evidence_mod  # noqa: E402
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
    # The corrected script is a heated but non-threatening cabin-temperature
    # argument (3 turns), so the ASR must NOT flag a threat or abusive language.
    assert len(transcript.segments) == 3
    assert transcript.threat_detected is False
    assert transcript.hostility_score < 0.5
    assert any("get another car" in s.text.lower() for s in transcript.segments)
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


def test_upload_audio_reads_the_sidecar_script(client, sample_audio):
    """prompt3: "a mock audio file containing aggressive language" is transcribed.

    The clip ships its dialogue as ``<name>.txt`` so the offline ASR hears the
    argument without TRTC credentials — no form-field hint required.
    """
    with sample_audio.open("rb") as fh:
        res = client.post(
            "/upload-audio",
            files={"file": (sample_audio.name, fh, "audio/wav")},
            data={"case_id": "DISP-006", "captured_at": "2026-09-18T23:41:00+08:00"},
        )
    assert res.status_code == 200, res.text
    transcript = res.json()["transcript"]
    assert transcript["engine"] == "simulated"
    assert transcript["threat_detected"] is True
    assert transcript["hostility_score"] >= 0.8
    assert "find you after this trip" in transcript["full_text"].lower()


def test_sidecar_script_is_found_next_to_or_below_the_recording(settings, tmp_path):
    """The sidecar lookup survives upload de-duplication (`name-1.wav`)."""
    clip = tmp_path / "argument.wav"
    clip.write_bytes(b"RIFF")
    (tmp_path / "argument.txt").write_text("driver: I will find you!", encoding="utf-8")

    attachment = MediaAttachment(
        attachment_id="att-1",
        media_type="audio",
        url=str(clip),
        local_path=str(clip),
    )
    assert "I will find you" in asr._sidecar_script(attachment, settings)

    deduped = MediaAttachment(
        attachment_id="att-2",
        media_type="audio",
        url=str(tmp_path / "argument-3.wav"),
        local_path=str(tmp_path / "argument-3.wav"),
    )
    assert "I will find you" in asr._sidecar_script(deduped, settings)

    orphan = MediaAttachment(
        attachment_id="att-3",
        media_type="audio",
        url=str(tmp_path / "other.wav"),
        local_path=str(tmp_path / "other.wav"),
    )
    assert asr._sidecar_script(orphan, settings) == ""


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


def test_repeated_recordings_produce_one_policy_check_each():
    """Two recordings of the same incident must not emit duplicate clauses.

    A rider and a driver can both upload audio; the clause list is a
    compliance matrix, not a per-attachment log, and duplicate `ref`s also
    break React's reconciliation keys downstream.
    """
    case = _case("DISP-006")
    scripted = _attachment("DISP-006", "audio")
    # Transcripts are grafted on at run time by the orchestrator, so do it here.
    transcript = asyncio.run(asr.SimulatedASRClient(get_settings()).transcribe(scripted))
    clone = scripted.model_copy(
        update={"attachment_id": "media-disp006-audio-2", "transcript": transcript}
    )
    scripted.transcript = transcript
    case.media_attachments = [scripted, clone]

    packet = evidence_mod.extract_evidence(case)
    refs = [c.ref for c in packet.policy_checks]
    assert len(refs) == len(set(refs)), f"duplicate clause refs: {refs}"
    # The corrected script is a civil (non-abusive) dispute, so only the
    # always-on SAFETY-1 clause applies; the point of the test is that two
    # recordings of the same incident never emit duplicate clause refs.
    assert "SAFETY-1" in refs


def test_audio_pipeline_escalates_the_verbal_altercation(client):
    """prompt3.2 §1: DISP-006 is the AC-temperature argument on tape.

    The corrected script is a heated but civil cabin-temperature dispute
    (no threat, no abusive language). The SLA router still pins the ticket at
    ``HIGH`` (fast-tracked into the priority queue) because it is a
    safety_incident, and the judge escalates while recommending an apology
    note, a driver reprimand and a goodwill voucher.
    """
    # Isolate this test from uploads left in the media_store by earlier
    # upload tests, so we assert on the canonical dossier, not a grafted file.
    main_mod.media_store.clear("DISP-006")

    r = _resolve(client, "DISP-006")

    assert r["status"] == "escalated"
    assert r["routing"]["priority"] == "high"
    assert r["routing"]["queue"] == "priority_resolution"
    assert r["routing"]["fast_tracked"] is True

    audio = [v for v in r["vision"] if v["media_kind"] == "audio"]
    assert audio, "no audio finding was produced"
    transcript = audio[0]["transcript"]
    assert transcript["engine"] == "simulated"
    # Corrected transcript: a heated disagreement, not a threat.
    assert transcript["threat_detected"] is False
    assert transcript["hostility_score"] < 0.5
    assert len(transcript["segments"]) == 3
    assert transcript["source_url"].endswith("disp006_arguement.mp3")

    # The transcript reached the fact table (duration, in-trip-window, ...)...
    keys = {f["key"] for f in r["evidence"]["facts"]}
    assert any(k.startswith("audio_") and k.endswith("_duration_s") for k in keys)
    assert any(k.startswith("audio_") and k.endswith("_in_trip_window") for k in keys)
    # ...and because the clip carries no abusive or threatening language, no
    # abuse signal should fire, so the fraud agent renders a clean verdict...
    assert not any(
        s["signal"] == "abusive_or_threatening_language"
        for s in r["evidence"]["risk_signals"]
    )
    assert isinstance(r["fraud"]["recommended_action"], str)
    assert len(r["fraud"]["recommended_action"]) > 0
    # ...while the safety-incident category still forces human escalation
    # (verified above via status / ruling / recommended_focus).
    # ...and the judge's ruling.
    assert r["ruling"]["decision"] == "escalate_to_human"
    assert r["ruling"]["escalated"] is True
    assert any("TRTC ASR" in k for k in r["ruling"]["key_findings"])
    assert r["escalation"] is not None

    # prompt3.2: the escalation packet leads with the conduct remedies the
    # reviewer is expected to apply.
    focus = " ".join(r["escalation"]["recommended_focus"]).lower()
    assert "apolog" in focus
    assert "reprimand" in focus or "warning" in focus
    assert "voucher" in focus


def test_video_pipeline_flags_the_harassment_recording(client):
    """prompt3.2 §1: DISP-007 is the back-seat harassment clip.

    Keyframes are sampled at 1 fps, the Vision Agent reports a
    ``conduct_violation`` on low-light footage, the SLA router assigns
    ``CRITICAL`` and the Escalation Protocol fires immediately.
    """
    r = _resolve(client, "DISP-007")

    assert r["dispute_type"] == "safety_incident"
    assert r["status"] == "escalated"
    assert r["routing"]["priority"] == "critical"
    assert r["routing"]["queue"] == "safety_escalations"
    assert r["routing"]["queue_position"] == 1

    video = [v for v in r["vision"] if v["media_kind"] == "video"]
    assert video, "no video finding was produced"
    analysis = video[0]["video"]

    assert analysis["frames_extracted"] >= 5
    assert analysis["duration_s"] == pytest.approx(12.27, abs=0.8)
    assert analysis["engine"] in {"ffmpeg", "opencv"}
    assert analysis["source_url"].endswith("disp007_harassment.mp4")
    assert len(analysis["frames"]) == analysis["frames_extracted"]
    # No timeout / decode failure surfaced as an anomaly.
    assert not any("decoded" in a for a in analysis["anomalies"])
    # ...but the low-light capture is called out, because it limits detail.
    assert any("dark" in a.lower() or "low-light" in a.lower() for a in analysis["anomalies"])

    # Keyframes are reachable over HTTP, so the UI never renders a broken strip.
    for frame in analysis["frames"][:3]:
        assert client.get(frame["path"]).status_code == 200

    keys = {f["key"] for f in r["evidence"]["facts"]}
    assert any(k.startswith("video_") and k.endswith("_frames") for k in keys)

    assert video[0]["severity"] == "conduct_violation"
    assert r["ruling"]["decision"] == "escalate_to_human"
    assert r["ruling"]["escalated"] is True

    # prompt3.2: the packet demands the three immediate platform actions.
    focus = " ".join(r["escalation"]["recommended_focus"]).lower()
    assert "suspend" in focus or "suspension" in focus
    assert "safety ticket" in focus
    assert "law enforcement" in focus or "law-enforcement" in focus or "police" in focus


def test_property_damage_never_escalates_to_human(client):
    """Product rule: only safety disputes may be escalated.

    Property-damage disputes still require human approval/override in the UI,
    but must not enter the escalation packet flow.
    """
    for case_id in ("DISP-003", "DISP-004"):
        r = _resolve(client, case_id)
        assert r["dispute_type"] == "property_damage"
        assert r["status"] == "resolved"
        assert r["ruling"]["escalated"] is False
        assert r["escalation"] is None


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
    assert by_id["DISP-007"]["dispute_type"] == "safety_incident"
    assert by_id["DISP-006"]["evidence_kind"] == "audio"
    assert by_id["DISP-007"]["evidence_kind"] == "video"


def test_case_library_carries_the_reviewer_queue_metadata(client):
    """prompt3.2 §3.3: the queue sorts on SLA band then money, before any run."""
    by_id = {c["case_id"]: c for c in client.get("/cases").json()["cases"]}

    assert by_id["DISP-007"]["sla_priority"] == "critical"
    assert by_id["DISP-006"]["sla_priority"] == "high"
    assert by_id["DISP-007"]["financial_value"] == pytest.approx(0.0)
    assert by_id["DISP-006"]["financial_value"] == pytest.approx(22.0)

    # A balance of carried-over and freshly-intake tickets (prompt3.2 §4.1).
    intakes = {c["case_id"]: c["intake"] for c in by_id.values()}
    assert intakes["DISP-001"] == "historical"
    assert intakes["DISP-007"] == "incoming"
    assert "historical" in intakes.values()
    assert "incoming" in intakes.values()
    for case_id, intake in intakes.items():
        assert intake in {"historical", "incoming"}, case_id
        assert isinstance(by_id[case_id]["financial_value"], (int, float)), case_id


def test_dossier_media_points_at_the_named_phase32_assets():
    """prompt3.2 §4.1: the exact file names the prompt specifies are wired up."""
    audio = _attachment("DISP-006", "audio")
    assert audio.url == "/assets/miora/disp006_arguement.mp3"
    assert Path(audio.local_path).name == "disp006_arguement.mp3"
    assert Path(audio.local_path).exists()

    video = _attachment("DISP-007", "video")
    assert video.url == "/assets/miora/disp007_harassment.mp4"
    assert Path(video.local_path).name == "disp007_harassment.mp4"
    assert Path(video.local_path).exists()

    # Both dossiers are filed as safety incidents and carry the escalation
    # directives a human reviewer has to act on.
    for case_id in ("DISP-006", "DISP-007"):
        case = _case(case_id)
        assert case.dispute_type == "safety_incident"
        assert case.escalation_directives, f"{case_id} has no escalation directives"


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
