#!/usr/bin/env python3
"""Export the WorkBuddy / CodeBuddy conversation transcript into a clean,
human-readable Markdown log for submission evidence.

- Reads the session .jsonl transcript.
- Keeps only role == user / assistant turns (skips the ~4800 internal
  tool-call / system events whose role is null).
- Redacts GitHub PATs so secrets are never written into a shareable file.
- Strips <system-reminder> noise blocks.
"""
import json
import re
import sys
from datetime import datetime, timezone

SRC = "/root/.codebuddy/projects/workspace/2f8a7d30-9c21-4f0b-1d42-035542466000.jsonl"
OUT = "/workspace/docs/chat_history.md"

PAT_RE = re.compile(r"github_pat_[A-Za-z0-9_]+")
SYS_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)


def clean(text: str) -> str:
    if not text:
        return ""
    text = SYS_RE.sub("", text)
    text = PAT_RE.sub("github_pat_***REDACTED***", text)
    return text.strip()


def extract_user(content) -> str:
    parts = []
    if isinstance(content, str):
        content = [{"type": "input_text", "text": content}]
    for p in content or []:
        if not isinstance(p, dict):
            continue
        t = p.get("text", "")
        if not t:
            continue
        s = t.strip()
        if s.startswith("{"):
            try:
                j = json.loads(t)
                if isinstance(j, dict) and isinstance(j.get("text"), str):
                    parts.append(j["text"].strip())
            except Exception:
                pass
            continue
        parts.append(s)
    return "\n".join(x for x in (clean(p) for p in parts) if x)


def extract_assistant(content) -> str:
    parts = []
    if isinstance(content, str):
        content = [{"type": "output_text", "text": content}]
    for p in content or []:
        if isinstance(p, dict) and p.get("type") == "output_text":
            t = p.get("text", "")
            if t:
                parts.append(clean(t))
    return "\n\n".join(x for x in parts if x)


def ts_to_str(ms):
    try:
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "?"


def main():
    entries = []
    with open(SRC) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            role = o.get("role")
            if role not in ("user", "assistant"):
                continue
            content = o.get("content")
            if role == "user":
                text = extract_user(content)
            else:
                text = extract_assistant(content)
            if not text:
                continue
            entries.append((role, ts_to_str(o.get("timestamp", 0)), text))

    # header
    n_user = sum(1 for r, _, _ in entries if r == "user")
    n_asst = sum(1 for r, _, _ in entries if r == "assistant")
    first_ts = entries[0][1] if entries else "?"
    last_ts = entries[-1][1] if entries else "?"

    lines = []
    lines.append("# RydeResolve / RYsolve — WorkBuddy Conversation History")
    lines.append("")
    lines.append("> Exported from the development session for submission evidence.")
    lines.append("> GitHub PATs have been redacted (`github_pat_***REDACTED***`).")
    lines.append("> Internal tool-call / system events are omitted; only user and")
    lines.append("> assistant dialogue turns are retained.")
    lines.append("")
    lines.append(f"- **User turns:** {n_user}")
    lines.append(f"- **Assistant turns:** {n_asst}")
    lines.append(f"- **Date range:** {first_ts} → {last_ts}")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, (role, ts, text) in enumerate(entries, 1):
        who = "👤 User" if role == "user" else "🤖 Assistant"
        lines.append(f"### {i}. {who} · {ts}")
        lines.append("")
        lines.append(text)
        lines.append("")

    out = "\n".join(lines)
    with open(OUT, "w") as f:
        f.write(out)

    print(f"wrote {OUT}")
    print(f"user={n_user} assistant={n_asst} total_lines={len(lines)} bytes={len(out)}")


if __name__ == "__main__":
    main()
