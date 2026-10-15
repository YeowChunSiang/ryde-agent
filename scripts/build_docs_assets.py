"""Generate the project architecture diagram and the cover image.

Outputs
-------
docs/architecture.svg  + docs/architecture.png
docs/cover.svg         + docs/cover.png     (overwrites the old one)

Run from the repo root:
    python3 scripts/build_docs_assets.py
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import cairosvg

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs"
OUT.mkdir(exist_ok=True)


# ---------- shared design tokens -----------------------------------------

BG       = "#0b1220"   # page background
PANEL    = "#111c2f"   # panel fill
PANEL2   = "#18243d"   # nested panel
BORDER   = "#2a3958"
TEXT     = "#e6edf6"
MUTED    = "#94a3b8"
DIM      = "#64748b"
ACCENT   = "#f59e0b"   # amber (brand)
ACCENT2  = "#fb923c"   # orange

# Per-role colours, aligned with the AGENT_META palette in the frontend.
ROLE = {
    "orchestrator":         "#a1a1aa",  # zinc
    "sla_router":           "#fb7185",  # rose
    "asr":                  "#38bdf8",  # sky
    "evidence":             "#2dd4bf",  # teal
    "evidence_collection":  "#14b8a6",  # teal-500
    "fraud":                "#f87171",  # red
    "policy":               "#c084fc",  # purple
    "vision":               "#34d399",  # emerald
    "rider_advocate":       "#fbbf24",  # amber
    "driver_advocate":      "#f59e0b",  # amber-500
    "judge":                "#818cf8",  # indigo
    "escalation":           "#f472b6",  # pink
    "learning":             "#60a5fa",  # blue
}

# The 10 pipeline stages, in execution order.  Each tuple is
# (id, short label, sub-caption, role key).  Keep sub-captions short so they
# fit inside a 120 px chip without bleeding into the next stage.
STAGES = [
    ("intake",     "Intake",      "ORC",              "orchestrator"),
    ("sla",        "SLA",         "router",           "sla_router"),
    ("media",      "Media",       "ASR + frames",     "asr"),
    ("evidence",   "Evidence",    "engine",           "evidence"),
    ("collection", "Collection",  "external",         "evidence_collection"),
    ("risk",       "Fraud + RAG", "parallel",         "fraud"),
    ("vision",     "Vision",      "img + video",      "vision"),
    ("advocacy",   "Advocacy",    "Rider ⊕ Driver",   "rider_advocate"),
    ("judge",      "Arbitration", "judge",            "judge"),
    ("escalation", "Escalation",  "gate",             "escalation"),
]


# ---------- helpers --------------------------------------------------------

def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def panel(x: int, y: int, w: int, h: int, title: str | None = None,
          fill: str = PANEL, stroke: str = BORDER) -> str:
    """A rounded panel with an optional title bar."""
    body = (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>'
    )
    if not title:
        return body
    title_h = 28
    bar = (
        f'<rect x="{x}" y="{y}" width="{w}" height="{title_h}" rx="14" '
        f'fill="{PANEL2}" stroke="none"/>'
        # Square the bottom corners of the title bar.
        f'<rect x="{x}" y="{y + title_h - 14}" width="{w}" height="14" '
        f'fill="{PANEL2}" stroke="none"/>'
        f'<text x="{x + 16}" y="{y + title_h / 2 + 5}" '
        f'font-family="Inter, Segoe UI, system-ui, sans-serif" '
        f'font-size="13" font-weight="600" fill="{TEXT}">{esc(title)}</text>'
    )
    return body + bar


def chip(x: int, y: int, w: int, h: int, label: str, role: str,
         sub: str | None = None) -> str:
    """A pipeline-stage chip with a coloured left bar + label + optional sub."""
    c = ROLE[role]
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" '
        f'fill="{PANEL2}" stroke="{BORDER}" stroke-width="1"/>'
        f'<rect x="{x}" y="{y}" width="4" height="{h}" rx="2" fill="{c}"/>'
        f'<text x="{x + 14}" y="{y + h/2 - (4 if sub else 0)}" '
        f'font-family="Inter, Segoe UI, system-ui, sans-serif" '
        f'font-size="13" font-weight="600" fill="{TEXT}">{esc(label)}</text>'
        + (
            f'<text x="{x + 14}" y="{y + h/2 + 12}" '
            f'font-family="Inter, Segoe UI, system-ui, sans-serif" '
            f'font-size="10" fill="{MUTED}">{esc(sub)}</text>'
            if sub else ""
        )
    )


def arrow(x1: int, y1: int, x2: int, y2: int, color: str = DIM,
          marker: bool = True) -> str:
    """A thin arrow line with an optional arrowhead."""
    head = ""
    if marker:
        head = (
            f'<polygon points="{x2-6},{y2-4} {x2+2},{y2} {x2-6},{y2+4}" '
            f'fill="{color}"/>'
        )
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
        f'marker-end="url(#arr)"/>'
    ) if marker else (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{color}" stroke-width="1.6" stroke-linecap="round"/>'
    )


# ---------- architecture diagram -----------------------------------------

def build_architecture() -> str:
    W, H = 1500, 1080
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}">'
    )
    parts.append(f'<rect width="{W}" height="{H}" fill="{BG}"/>')

    # arrow markers
    parts.append(
        '<defs>'
        f'<marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 Z" fill="{DIM}"/>'
        '</marker>'
        f'<marker id="arr-acc" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 Z" fill="{ACCENT}"/>'
        '</marker>'
        '</defs>'
    )

    # --- header ---
    parts.append(
        f'<text x="40" y="44" font-family="Inter, system-ui, sans-serif" '
        f'font-size="26" font-weight="700" fill="{TEXT}">'
        f'RydeResolve — System Architecture</text>'
    )
    parts.append(
        f'<text x="40" y="68" font-family="Inter, system-ui, sans-serif" '
        f'font-size="13" fill="{MUTED}">'
        f'13 agents · 10 stages · 7 built-in cases · pure Python + FastAPI '
        f'+ React/Vite · SSE-driven observability</text>'
    )
    # status pills (top-right) — tightened so they fit within the canvas
    pill_specs = [
        ("reasoner: offline", 100, "#a1a1aa"),
        ("ADP: offline",       90, "#a1a1aa"),
        ("ASR: simulated",    100, "#38bdf8"),
        ("keyframes: ffmpeg", 110, "#2dd4bf"),
        ("KB: 9 precedents",  120, ACCENT),
    ]
    pill_x = W - 30 - sum(w for _, w, _ in pill_specs) - 6 * (len(pill_specs) - 1)
    pill_y = 32
    for label, w_chip, col in pill_specs:
        parts.append(
            f'<rect x="{pill_x}" y="{pill_y}" width="{w_chip}" height="26" '
            f'rx="13" fill="{PANEL2}" stroke="{BORDER}"/>'
            f'<circle cx="{pill_x + 14}" cy="{pill_y + 13}" r="4" fill="{col}"/>'
            f'<text x="{pill_x + 24}" y="{pill_y + 17}" '
            f'font-family="Inter, system-ui, sans-serif" font-size="11" '
            f'fill="{TEXT}">{esc(label)}</text>'
        )
        pill_x += w_chip + 6

    # --- Frontend band (y 90-220) ---
    parts.append(panel(30, 90, W - 60, 130, "Frontend — React 19 + Vite + shadcn/ui"))
    fc = [
        ("Login",        "Mock auth (reviewer@ryde.com / admin2026) → session id in localStorage", 0),
        ("Dashboard",    "KPI cards · New/Archived tabs · SLA-sorted queue (DisputeTable)",         1),
        ("Case Detail",  "PipelineRail · Evidence · Risk & RAG · Advocates · Verdict · Escalation", 2),
    ]
    fw = 460
    fgap = 14
    fx0 = 50
    fy = 132
    for label, sub, idx in fc:
        x = fx0 + idx * (fw + fgap)
        parts.append(
            f'<rect x="{x}" y="{fy}" width="{fw}" height="70" rx="10" '
            f'fill="{PANEL2}" stroke="{BORDER}"/>'
            f'<text x="{x + 14}" y="{fy + 24}" '
            f'font-family="Inter, system-ui, sans-serif" font-size="14" '
            f'font-weight="600" fill="{TEXT}">{esc(label)}</text>'
            f'<text x="{x + 14}" y="{fy + 46}" '
            f'font-family="Inter, system-ui, sans-serif" font-size="11" '
            f'fill="{MUTED}">{esc(sub)}</text>'
        )
    for i in range(2):
        x = fx0 + (i + 1) * fw + i * fgap
        parts.append(
            f'<line x1="{x + 4}" y1="{fy + 35}" x2="{x + fgap - 4}" '
            f'y2="{fy + 35}" stroke="{DIM}" stroke-width="1.6" '
            f'marker-end="url(#arr)"/>'
        )
    parts.append(
        f'<text x="{W/2 - 50}" y="244" '
        f'font-family="Inter, system-ui, sans-serif" font-size="12" '
        f'fill="{MUTED}">HTTPS · SSE  ▾</text>'
    )

    # --- API band (y 260-340) ---
    parts.append(panel(30, 260, W - 60, 80, "Backend — FastAPI on :3000  (also serves built frontend at /)"))
    api_y = 294
    api_x = 50
    apis = [
        "/api/login", "/api/cases", "/api/resolve", "/api/stream/{run_id}",
        "/api/result/{run_id}", "/api/approve", "/api/override",
        "/api/upload-audio", "/api/upload-image", "/api/upload-video",
        "/api/precedents", "/api/escalations", "/api/health",
    ]
    for a in apis:
        parts.append(
            f'<rect x="{api_x}" y="{api_y}" width="105" height="24" rx="5" '
            f'fill="{PANEL2}" stroke="{BORDER}"/>'
            f'<text x="{api_x + 52}" y="{api_y + 16}" '
            f'font-family="ui-monospace, SFMono-Regular, monospace" '
            f'font-size="10" fill="{TEXT}" text-anchor="middle">{esc(a)}</text>'
        )
        api_x += 110
    parts.append(
        f'<line x1="{W/2}" y1="345" x2="{W/2}" y2="378" stroke="{DIM}" '
        f'stroke-width="1.8" marker-end="url(#arr)"/>'
    )

    # --- Orchestrator band (y 370-790) ---
    parts.append(panel(30, 370, W - 60, 420, "Orchestrator — async state pipeline (orchestrator.py)"))

    # 10 stages in a single row, centred.
    sw, sh, sgap = 120, 56, 10
    total = 10 * sw + 9 * sgap  # 1290
    sx0 = (W - total) // 2
    sy = 408
    for i, (sid, short, sub, role) in enumerate(STAGES):
        x = sx0 + i * (sw + sgap)
        # short label as primary, sub-caption underneath
        parts.append(chip(x, sy, sw, sh, short, role, sub=sub))
        if i < 9:
            parts.append(
                f'<line x1="{x + sw}" y1="{sy + sh/2}" x2="{x + sw + sgap}" '
                f'y2="{sy + sh/2}" stroke="{DIM}" stroke-width="1.6" '
                f'marker-end="url(#arr)"/>'
            )

    # parallel wedge: stages 5..7 (collection, fraud+risk, vision) share data
    par_y = sy + sh + 8
    par_l = sx0 + 4 * (sw + sgap)  # under stage 5
    par_r = sx0 + 7 * (sw + sgap)  # under stage 7
    for k in range(3):
        cx_k = par_l + k * (sw + sgap) + sw / 2
        parts.append(
            f'<line x1="{cx_k}" y1="{sy + sh}" x2="{cx_k}" '
            f'y2="{par_y + 14}" stroke="{DIM}" stroke-width="1.4" '
            f'marker-end="url(#arr)"/>'
        )
    parts.append(
        f'<line x1="{par_l + sw/2}" y1="{par_y + 18}" '
        f'x2="{par_r + sw/2}" y2="{par_y + 18}" stroke="{DIM}" '
        f'stroke-width="1.4" stroke-dasharray="3,3"/>'
    )
    parts.append(
        f'<text x="{(par_l + par_r + sw)/2}" y="{par_y + 32}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="11" '
        f'fill="{MUTED}" text-anchor="middle">'
        f'asyncio.gather — collection · fraud · precedent · vision in parallel</text>'
    )

    # pipeline → decision diamond (arrow down from middle of pipeline)
    pd_y = par_y + 60
    pd_cx = W // 2
    parts.append(
        f'<line x1="{pd_cx}" y1="{par_y + 40}" x2="{pd_cx}" y2="{pd_y - 28}" '
        f'stroke="{DIM}" stroke-width="1.6" marker-end="url(#arr)"/>'
    )
    # decision diamond
    dec_w, dec_h = 140, 60
    parts.append(
        f'<polygon points="'
        f'{pd_cx},{pd_y - dec_h/2} '
        f'{pd_cx + dec_w/2},{pd_y} '
        f'{pd_cx},{pd_y + dec_h/2} '
        f'{pd_cx - dec_w/2},{pd_y}" '
        f'fill="{PANEL2}" stroke="{BORDER}" stroke-width="1.4"/>'
    )
    parts.append(
        f'<text x="{pd_cx}" y="{pd_y - 6}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="12" '
        f'font-weight="700" fill="{TEXT}" text-anchor="middle">'
        f'Confidence gate</text>'
        f'<text x="{pd_cx}" y="{pd_y + 12}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="11" '
        f'fill="{MUTED}" text-anchor="middle">'
        f'≥ 0.70 ?</text>'
    )

    # two outcomes side by side below the diamond
    oy = pd_y + 70
    box_w, box_h, gap = 280, 64, 40
    auto_x = pd_cx - gap // 2 - box_w
    esc_x = pd_cx + gap // 2
    # arrow from diamond down
    parts.append(
        f'<line x1="{pd_cx}" y1="{pd_y + dec_h/2}" x2="{pd_cx}" '
        f'y2="{oy - 8}" stroke="{DIM}" stroke-width="1.6" '
        f'marker-end="url(#arr)"/>'
    )
    # splitter
    parts.append(
        f'<line x1="{auto_x + box_w/2}" y1="{oy - 8}" '
        f'x2="{esc_x + box_w/2}" y2="{oy - 8}" stroke="{DIM}" '
        f'stroke-width="1.6"/>'
    )
    parts.append(
        f'<line x1="{auto_x + box_w/2}" y1="{oy - 8}" '
        f'x2="{auto_x + box_w/2}" y2="{oy - 2}" stroke="{DIM}" '
        f'stroke-width="1.6" marker-end="url(#arr)"/>'
    )
    parts.append(
        f'<line x1="{esc_x + box_w/2}" y1="{oy - 8}" '
        f'x2="{esc_x + box_w/2}" y2="{oy - 2}" stroke="{DIM}" '
        f'stroke-width="1.6" marker-end="url(#arr)"/>'
    )
    # auto-resolved box
    parts.append(
        f'<rect x="{auto_x}" y="{oy}" width="{box_w}" height="{box_h}" '
        f'rx="10" fill="{PANEL2}" stroke="{BORDER}"/>'
        f'<circle cx="{auto_x + 18}" cy="{oy + box_h/2}" r="6" fill="#34d399"/>'
        f'<text x="{auto_x + 34}" y="{oy + 26}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="14" '
        f'font-weight="700" fill="{TEXT}">Auto-resolved</text>'
        f'<text x="{auto_x + 34}" y="{oy + 46}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="11" '
        f'fill="{MUTED}">standard determinations · DisputeTable row</text>'
    )
    # escalated box
    parts.append(
        f'<rect x="{esc_x}" y="{oy}" width="{box_w}" height="{box_h}" '
        f'rx="10" fill="{PANEL2}" stroke="{BORDER}"/>'
        f'<circle cx="{esc_x + 18}" cy="{oy + box_h/2}" r="6" fill="#f472b6"/>'
        f'<text x="{esc_x + 34}" y="{oy + 26}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="14" '
        f'font-weight="700" fill="{TEXT}">Escalated to human</text>'
        f'<text x="{esc_x + 34}" y="{oy + 46}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="11" '
        f'fill="{MUTED}">confidence &lt; 0.70 OR safety_incident</text>'
    )

    # arrows from each outcome into the Reviewer panel
    rev_y = oy + box_h + 40
    rev_h = 80
    parts.append(
        f'<line x1="{auto_x + box_w/2}" y1="{oy + box_h}" '
        f'x2="{auto_x + box_w/2}" y2="{rev_y - 8}" stroke="{DIM}" '
        f'stroke-width="1.4" marker-end="url(#arr)"/>'
    )
    parts.append(
        f'<line x1="{esc_x + box_w/2}" y1="{oy + box_h}" '
        f'x2="{esc_x + box_w/2}" y2="{rev_y - 8}" stroke="{DIM}" '
        f'stroke-width="1.4" marker-end="url(#arr)"/>'
    )
    # reviewer panel
    parts.append(panel(380, rev_y, W - 760, rev_h,
                       "Reviewer — Approve / Override  (Phase 3.2 portal)"))
    parts.append(
        f'<text x="400" y="{rev_y + 52}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="12" '
        f'fill="{TEXT}">'
        f'· Approve  →  POST /api/approve/{{run_id}}  —  archives case, '
        f'logs reviewer</text>'
    )
    parts.append(
        f'<text x="400" y="{rev_y + 70}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="12" '
        f'fill="{TEXT}">'
        f'· Override  →  POST /api/override/{{run_id}}  —  writes new '
        f'precedent into the KB</text>'
    )

    # learning loop arrow back to KB
    loop_y = rev_y + rev_h + 22
    parts.append(
        f'<line x1="{W/2}" y1="{rev_y + rev_h}" x2="{W/2}" '
        f'y2="{loop_y - 6}" stroke="{ACCENT}" stroke-width="1.8" '
        f'marker-end="url(#arr-acc)"/>'
    )
    parts.append(
        f'<text x="{W/2 + 8}" y="{loop_y - 12}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="12" '
        f'font-weight="600" fill="{ACCENT}">'
        f'Learning feedback loop  →  precedents.json</text>'
    )

    # --- Side services band (y 800-980) ---
    sy0 = 800
    parts.append(panel(30, sy0, W - 60, 180, "Side services · fallbacks · data"))
    cols = [
        ("LLM",
         [("Tencent Cloud ADP", "wss.lke.tencentcloud.com/adp/v2/chat"),
          ("Offline reasoner",  "deterministic, no creds needed"),
          ("TC3-HMAC-SHA256",   "auth · VisitorId · ConversationId")]),
        ("Multi-modal",
         [("TRTC ASR",         "Tencent Cloud speech-to-text"),
          ("Simulated ASR",    "driven by cases.py + sidecar .txt"),
          ("ffmpeg → OpenCV",  "keyframe extraction + integrity flags"),
          ("Pillow",           "thumbnail / mock-asset generation")]),
        ("State & assets",
         [("Miora avatars",    "13 PNGs under /assets/miora/agents/"),
          ("Miora evidence",   "4 case images + 1 mp3 + 1 mp4"),
          ("precedents.json",  "KB grows at runtime · gitignored"),
          ("localStorage",     "ryderesolve.case-store.v3")]),
    ]
    col_w = (W - 90) / 3
    for ci, (title, rows) in enumerate(cols):
        cx = 45 + ci * col_w
        parts.append(
            f'<text x="{cx + 14}" y="{sy0 + 52}" '
            f'font-family="Inter, system-ui, sans-serif" font-size="13" '
            f'font-weight="700" fill="{TEXT}">{esc(title)}</text>'
        )
        for ri, (k, v) in enumerate(rows):
            ry = sy0 + 76 + ri * 24
            parts.append(
                f'<text x="{cx + 14}" y="{ry}" '
                f'font-family="ui-monospace, monospace" font-size="11" '
                f'fill="{ACCENT}">{esc(k)}</text>'
                f'<text x="{cx + 140}" y="{ry}" '
                f'font-family="Inter, system-ui, sans-serif" font-size="11" '
                f'fill="{MUTED}">{esc(v)}</text>'
            )

    # --- footer ---
    parts.append(
        f'<text x="40" y="{H - 18}" '
        f'font-family="Inter, system-ui, sans-serif" font-size="11" '
        f'fill="{DIM}">'
        f'Rendered from scripts/build_docs_assets.py · '
        f'commit 2b82bb7 · 31 pytest · pnpm build</text>'
    )
    parts.append("</svg>")
    return "".join(parts)



# ---------- cover image ---------------------------------------------------

def build_cover() -> str:
    W, H = 760, 432  # 2x of 380x216 for crisp raster
    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}">'
    )
    # background with subtle vertical gradient
    parts.append(
        '<defs>'
        f'<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0%" stop-color="#0b1220"/>'
        f'<stop offset="100%" stop-color="#10182a"/>'
        '</linearGradient>'
        f'<linearGradient id="logo" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0%" stop-color="#fbbf24"/>'
        f'<stop offset="100%" stop-color="#f97316"/>'
        '</linearGradient>'
        f'<linearGradient id="bar" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0%" stop-color="{ACCENT}"/>'
        f'<stop offset="100%" stop-color="#a855f7"/>'
        '</linearGradient>'
        '</defs>'
        f'<rect width="{W}" height="{H}" fill="url(#bg)"/>'
    )

    # logo box
    parts.append(
        f'<rect x="32" y="40" width="60" height="60" rx="12" '
        f'fill="url(#logo)"/>'
        f'<text x="62" y="83" font-family="Inter, system-ui, sans-serif" '
        f'font-size="32" font-weight="800" fill="#0b1220" '
        f'text-anchor="middle">Ry</text>'
    )
    # title
    parts.append(
        f'<text x="108" y="78" font-family="Inter, system-ui, sans-serif" '
        f'font-size="36" font-weight="800" fill="{TEXT}">'
        f'RydeResolve</text>'
    )
    parts.append(
        f'<text x="108" y="100" font-family="Inter, system-ui, sans-serif" '
        f'font-size="14" fill="{MUTED}">'
        f'Multi-agent autonomous dispute arbitration</text>'
    )

    # ruling card (representative: DISP-002, 88% UPHELD)
    parts.append(
        f'<rect x="32" y="130" width="320" height="58" rx="9" '
        f'fill="{PANEL2}" stroke="{ACCENT}" stroke-width="1.4"/>'
        f'<rect x="32" y="130" width="4" height="58" fill="{ACCENT}"/>'
        f'<text x="50" y="156" font-family="Inter, system-ui, sans-serif" '
        f'font-size="13" font-weight="700" fill="{ACCENT}">'
        f'RULING · CHARGE UPHELD</text>'
        f'<text x="50" y="178" font-family="Inter, system-ui, sans-serif" '
        f'font-size="12" fill="{TEXT}">'
        f'DISP-002 · confidence 88%</text>'
    )

    # stats row
    stats = [("13", "agents"), ("10", "stages"), ("7", "cases"),
             ("31", "pytest"), ("SSE", "live")]
    sx = 32
    for n, lab in stats:
        parts.append(
            f'<text x="{sx}" y="226" font-family="Inter, system-ui, sans-serif" '
            f'font-size="22" font-weight="800" fill="{TEXT}">{n}</text>'
            f'<text x="{sx + 38}" y="226" font-family="Inter, system-ui, '
            f'sans-serif" font-size="11" fill="{MUTED}">{lab}</text>'
        )
        sx += 80 if n != "SSE" else 90

    # pipeline mini-chips: 10 stages in a single row
    labels = ["Intake", "SLA", "Media", "Evidence", "Collect",
              "Fraud", "Vision", "Advocacy", "Judge", "Escalate"]
    cw, ch, gap = 64, 22, 6
    px0 = 32
    py = 252
    for i, lab in enumerate(labels):
        x = px0 + i * (cw + gap)
        c = list(ROLE.values())[i]
        parts.append(
            f'<rect x="{x}" y="{py}" width="{cw}" height="{ch}" rx="11" '
            f'fill="{PANEL2}" stroke="{BORDER}"/>'
            f'<circle cx="{x + 11}" cy="{py + ch/2}" r="3" fill="{c}"/>'
            f'<text x="{x + 19}" y="{py + ch/2 + 4}" '
            f'font-family="Inter, system-ui, sans-serif" font-size="10" '
            f'fill="{TEXT}">{esc(lab)}</text>'
        )
        if i < 9:
            parts.append(
                f'<line x1="{x + cw + 1}" y1="{py + ch/2}" '
                f'x2="{x + cw + gap - 1}" y2="{py + ch/2}" '
                f'stroke="{DIM}" stroke-width="1.2"/>'
            )

    # gradient bar separator
    parts.append(
        f'<rect x="32" y="290" width="{W - 64}" height="2" '
        f'fill="url(#bar)"/>'
    )

    # tech stack row
    tech = ["FastAPI", "Pydantic v2", "React 19", "Vite", "Tencent ADP",
            "TRTC ASR", "ffmpeg→OpenCV", "shadcn/ui"]
    tx = 32
    ty = 318
    for t in tech:
        w = 8 * len(t) + 16
        parts.append(
            f'<rect x="{tx}" y="{ty}" width="{w}" height="22" rx="11" '
            f'fill="{PANEL2}" stroke="{BORDER}"/>'
            f'<text x="{tx + w/2}" y="{ty + 15}" '
            f'font-family="ui-monospace, monospace" font-size="10" '
            f'fill="{TEXT}" text-anchor="middle">{esc(t)}</text>'
        )
        tx += w + 6
        if tx > W - 100 and t != tech[-1]:
            tx = 32
            ty += 26

    # footer
    parts.append(
        f'<text x="32" y="408" font-family="Inter, system-ui, sans-serif" '
        f'font-size="11" fill="{MUTED}">'
        f'Tencent Cloud AI Singapore Hackathon 2026  ·  AI Agent · '
        f'Digital Native Track  ·  Ryde problem</text>'
    )
    parts.append(
        f'<text x="{W - 32}" y="408" font-family="Inter, system-ui, sans-serif" '
        f'font-size="11" fill="{MUTED}" text-anchor="end">'
        f'origin/main · commit 2b82bb7</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


# ---------- main ----------------------------------------------------------

def render(svg: str, png: Path, width: int) -> None:
    cairosvg.svg2png(
        bytestring=svg.encode("utf-8"),
        write_to=str(png),
        output_width=width,
    )
    png_size = png.stat().st_size
    print(f"  wrote {png.relative_to(REPO)}  ({png_size // 1024} KB)")


def main() -> None:
    print("Building docs/architecture.* ...")
    arch_svg = build_architecture()
    (OUT / "architecture.svg").write_text(arch_svg, encoding="utf-8")
    render(arch_svg, OUT / "architecture.png", width=1500)

    print("Building docs/cover.* ...")
    cover_svg = build_cover()
    (OUT / "cover.svg").write_text(cover_svg, encoding="utf-8")
    render(cover_svg, OUT / "cover.png", width=380)


if __name__ == "__main__":
    main()
