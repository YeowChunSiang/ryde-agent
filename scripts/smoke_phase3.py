"""Phase 3 end-to-end smoke: audio (DISP-006) + video (DISP-007) pipelines."""

from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://localhost:3000"


def _get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as resp:
        return json.loads(resp.read().decode())


def _post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode())


def report(case_id: str) -> None:
    print(f"\n{'=' * 74}\n{case_id}\n{'=' * 74}")
    started = time.time()
    r = _post("/resolve", {"case_id": case_id})
    elapsed = time.time() - started
    print(f"status={r.get('status')} engine={r.get('engine')} elapsed={elapsed:.1f}s")

    routing = r.get("routing") or {}
    print(f"routing: priority={routing.get('priority')} queue={routing.get('queue')} "
          f"fast_tracked={routing.get('fast_tracked')}")

    # ---------- vision findings ----------
    vision = r.get("vision") or []
    print(f"\nvision findings ({len(vision)}):")
    for v in vision:
        print(f"  - media_kind={v.get('media_kind')} genuine={v.get('genuine')} "
              f"severity={v.get('severity')} conf={v.get('confidence')}")
        va = v.get("video") or {}
        if va:
            frames = va.get("frames") or []
            print(f"    video: dur={va.get('duration_s')}s fps={va.get('fps')} "
                  f"frames={va.get('frames_extracted')} severity={va.get('severity')} "
                  f"engine={va.get('engine')}")
            for f in frames[:4]:
                print(f"      frame #{f.get('index')} t={f.get('timestamp_s')}s "
                      f"lum={f.get('mean_luminance')} motion={f.get('motion_score')} "
                      f"path={f.get('path')}")
            if len(frames) > 4:
                print(f"      ...(+{len(frames) - 4} more)")
            for a in va.get("anomalies") or []:
                print(f"    anomaly: {a}")
        tr = v.get("transcript") or {}
        if tr:
            print(f"    transcript: engine={tr.get('engine')} dur={tr.get('duration_s')}s "
                  f"hostility={tr.get('hostility_score')} threat={tr.get('threat_detected')}")
            print(f"      keywords={tr.get('keywords')}")
            print(f"      summary: {str(tr.get('summary'))[:220]}")
            for seg in (tr.get("segments") or [])[:6]:
                print(f"      [{seg.get('start_s')}s-{seg.get('end_s')}s] "
                      f"{seg.get('speaker')} (h={seg.get('hostility')}): {seg.get('text')}")
        print(f"    reasoning: {str(v.get('reasoning'))[:320]}")

    # ---------- evidence facts ----------
    ev = r.get("evidence") or {}
    facts = ev.get("facts") or []
    audio_facts = [f for f in facts if str(f.get("key", "")).startswith("audio_")]
    video_facts = [f for f in facts if str(f.get("key", "")).startswith("video_")]
    if audio_facts:
        print("\naudio facts:")
        for f in audio_facts:
            print(f"  {f['key']} = {f['value']}  ({f.get('supports')})")
    if video_facts:
        print("\nvideo facts:")
        for f in video_facts:
            print(f"  {f['key']} = {f['value']}  ({f.get('supports')})")

    checks = ev.get("policy_checks") or []
    if checks:
        print("\npolicy checks:")
        for c in checks:
            print(f"  {c.get('ref')} compliant={c.get('compliant')} ({c.get('supports')}): "
                  f"{c.get('description')} | expected={c.get('expected')} actual={c.get('actual')}")

    signals = ev.get("risk_signals") or []
    if signals:
        print("\nrisk signals:")
        for s in signals:
            print(f"  [{s.get('severity')}] {s.get('party')}: {s.get('signal')} — {s.get('detail')}")

    # ---------- fraud ----------
    fraud = r.get("fraud") or {}
    if fraud:
        print(f"\nfraud: verdict={fraud.get('verdict')} score={fraud.get('risk_score')} "
              f"rider={fraud.get('rider_risk')} driver={fraud.get('driver_risk')}")
        print(f"  action: {fraud.get('recommended_action')}")

    # ---------- ruling ----------
    ruling = r.get("ruling") or {}
    print(f"\nruling: {ruling.get('decision')} S${ruling.get('amount')} "
          f"conf={ruling.get('confidence')} escalated={ruling.get('escalated')}")
    if ruling.get("escalation_reason"):
        print(f"  escalation_reason: {ruling['escalation_reason']}")
    print(f"  reasoning: {str(ruling.get('reasoning'))[:420]}")
    print("  key_findings:")
    for kf in ruling.get("key_findings") or []:
        print(f"    - {kf}")

    esc = r.get("escalation") or {}
    if esc:
        print(f"\nescalation packet: priority={esc.get('priority')} queue={esc.get('queue')} "
              f"due={esc.get('sla_due_at')}")
        print(f"  case_summary: {str(esc.get('case_summary'))[:200]}")
        for flag in esc.get("risk_flags") or []:
            print(f"    risk flag: {flag}")
        for focus in esc.get("recommended_focus") or []:
            print(f"    focus: {focus}")

    if r.get("errors"):
        print(f"\nERRORS: {r['errors']}")


if __name__ == "__main__":
    for cid in sys.argv[1:] or ["DISP-006", "DISP-007"]:
        try:
            report(cid)
        except Exception as exc:  # noqa: BLE001
            print(f"\n[{cid}] FAILED: {exc!r}")
    print("\ndone")
