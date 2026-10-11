"""Generate the Phase 3 mock evidence assets + agent avatars.

The hackathon brief calls for Tencent Miora renders. When a Miora endpoint is
reachable, drop files with the exact names below into
``frontend/public/assets/miora/`` and this script's output is simply replaced —
``manifest.json`` records the prompt for every asset so the real renders can be
regenerated 1:1 later.

Until then the assets are drawn locally with Pillow/ffmpeg so the UI, the tests
and the demo never depend on an external image service:

    python3 scripts/generate_mock_assets.py

Outputs
-------
frontend/public/assets/miora/*.png    mock evidence + agent avatars
frontend/public/assets/miora/manifest.json  asset key -> Miora prompt
backend/data/uploads/samples/*.wav|mp4      ingestable audio/video payloads
"""

from __future__ import annotations

import json
import math
import random
import struct
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "frontend" / "public" / "assets" / "miora"
AVATARS = ASSETS / "agents"
SAMPLES = ROOT / "backend" / "data" / "uploads" / "samples"

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except Exception:  # pragma: no cover - fallback if fonts are missing
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Phone mockup helpers
# ---------------------------------------------------------------------------


def phone_base(width=900, height=1120):
    img = Image.new("RGB", (width, height), (15, 18, 26))
    d = ImageDraw.Draw(img)
    # device body
    d.rounded_rectangle([60, 40, width - 60, height - 40], radius=64, fill=(22, 26, 36))
    d.rounded_rectangle([80, 90, width - 80, height - 90], radius=40, fill=(247, 249, 252))
    # status bar
    d.text((120, 58), "9:41", font=font(26, True), fill=(226, 232, 240))
    d.text((width - 190, 58), "Ryde  5G  100%", font=font(24), fill=(226, 232, 240))
    return img, d


def route_deviation(path: Path) -> None:
    img, d = phone_base()
    # map background
    d.rectangle([90, 150, 810, 1010], fill=(228, 234, 242))
    rnd = random.Random(7)
    for _ in range(220):  # city blocks
        x, y = rnd.randint(95, 800), rnd.randint(155, 1005)
        w, h = rnd.randint(28, 90), rnd.randint(20, 70)
        d.rectangle([x, y, x + w, y + h], fill=(214, 222, 232), outline=(203, 213, 225))
    for _ in range(26):  # roads
        y = rnd.randint(155, 1005)
        d.line([(95, y), (805, y)], fill=(255, 255, 255), width=rnd.randint(6, 14))
    # suggested route (straight, blue)
    d.line([(170, 900), (760, 300)], fill=(37, 99, 235), width=16)
    # actual GPS track (wild loop, red)
    pts = [
        (170, 900), (250, 780), (420, 820), (560, 700), (470, 560),
        (620, 520), (700, 380), (560, 300), (700, 250), (760, 300),
    ]
    d.line(pts, fill=(220, 38, 38), width=16, joint="curve")
    for p in pts[:1] + pts[-1:]:
        d.ellipse([p[0] - 16, p[1] - 16, p[0] + 16, p[1] + 16], fill=(220, 38, 38), outline=(255, 255, 255), width=4)
    d.text((120, 170), "Trip  TRP-2026-08812", font=font(30, True), fill=(24, 32, 44))
    d.text((120, 215), "Suggested 12.4 km  vs  actual 18.9 km", font=font(26), fill=(71, 85, 105))
    d.rounded_rectangle([110, 930, 790, 1000], radius=18, fill=(255, 255, 255))
    d.text((130, 952), "Detour +6.5 km  ·  fare $20.00 → $28.40", font=font(28, True), fill=(185, 28, 28))
    img.save(path)


def no_show_chat(path: Path) -> None:
    img, d = phone_base()
    d.rectangle([90, 150, 810, 1010], fill=(241, 245, 250))
    d.rectangle([90, 150, 810, 232], fill=(255, 255, 255))
    d.text((120, 172), "Driver · Ahmad", font=font(30, True), fill=(17, 24, 39))
    d.text((120, 206), "Honda Vezel · SGP 1188 C", font=font(24), fill=(100, 116, 139))

    def bubble(text, y, mine=False):
        w = 12 * len(text) + 42
        x = 780 - w if mine else 120
        d.rounded_rectangle([x, y, x + w, y + 74], radius=22, fill=(37, 99, 235) if mine else (255, 255, 255))
        d.text((x + 20, y + 22), text, font=font(26), fill=(255, 255, 255) if mine else (17, 24, 39))

    bubble("I am at the lobby", 270, mine=True)
    bubble("Waiting for 5 minutes", 366, mine=True)
    bubble("I am at the lobby — please come down", 462, mine=True)
    d.text((130, 566), "No replies from the passenger", font=font(24), fill=(148, 163, 184))
    # wait timer overlay
    d.rounded_rectangle([170, 640, 730, 800], radius=28, fill=(17, 24, 39))
    d.text((215, 672), "WAIT TIMER", font=font(26, True), fill=(148, 163, 184))
    d.text((215, 712), "08:00", font=font(78, True), fill=(248, 113, 113))
    d.text((430, 742), "elapsed", font=font(34), fill=(226, 232, 240))
    d.rounded_rectangle([110, 860, 790, 940], radius=18, fill=(255, 255, 255))
    d.text((130, 882), "$5.00 no-show fee charged at 08:00", font=font(28, True), fill=(185, 28, 28))
    img.save(path)


def seat_base(d, w=900, h=1120):
    # car seat fabric
    d.rectangle([0, 0, w, h], fill=(58, 60, 66))
    rnd = random.Random(11)
    for _ in range(2600):
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        shade = rnd.randint(-14, 14)
        d.point((x, y), fill=(58 + shade, 60 + shade, 66 + shade))
    # seat seams
    for y in (260, 520, 780):
        d.line([(0, y), (w, y)], fill=(38, 40, 45), width=8)


def genuine_spill(path: Path) -> None:
    img = Image.new("RGB", (900, 1120), (58, 60, 66))
    d = ImageDraw.Draw(img)
    seat_base(d)
    # wet coffee stain
    d.ellipse([240, 400, 700, 820], fill=(86, 54, 30))
    d.ellipse([280, 440, 660, 780], fill=(104, 66, 36))
    d.ellipse([330, 480, 610, 740], fill=(72, 44, 24))
    d.ellipse([420, 520, 560, 640], fill=(126, 82, 46))
    # cup on its side
    d.rounded_rectangle([600, 300, 760, 430], radius=16, fill=(236, 238, 242))
    d.ellipse([600, 290, 760, 330], fill=(210, 214, 222))
    # puddle sheen
    d.ellipse([360, 560, 470, 640], fill=(150, 104, 62))
    # timestamp overlay + EXIF badge
    d.rounded_rectangle([40, 980, 560, 1060], radius=12, fill=(0, 0, 0))
    d.text((64, 1004), "2026-09-13 09:15 AM", font=font(40, True), fill=(255, 214, 102))
    d.rounded_rectangle([610, 990, 870, 1050], radius=12, fill=(16, 122, 87))
    d.text((636, 1008), "EXIF OK", font=font(30, True), fill=(255, 255, 255))
    img.save(path)


def fake_spill(path: Path) -> None:
    img = Image.new("RGB", (900, 1120), (58, 60, 66))
    d = ImageDraw.Draw(img)
    seat_base(d)
    rnd = random.Random(23)
    # fries: unnaturally uniform, plastic sheen
    for _ in range(70):
        x, y = rnd.randint(180, 720), rnd.randint(360, 820)
        d.rounded_rectangle([x, y, x + 62, y + 17], radius=8, fill=(247, 208, 74))
        d.rounded_rectangle([x, y, x + 62, y + 6], radius=3, fill=(255, 236, 170))
    # ketchup blobs with too-clean edges
    for centre in ((300, 520), (520, 640), (640, 470)):
        d.ellipse([centre[0] - 70, centre[1] - 46, centre[0] + 70, centre[1] + 46], fill=(198, 24, 24))
        d.ellipse([centre[0] - 40, centre[1] - 26, centre[0] + 40, centre[1] + 26], fill=(226, 44, 44))
    # synthetic-media artefacts: banding + checker ghosts
    for i in range(0, 900, 18):
        d.line([(i, 0), (i, 1120)], fill=(66, 68, 74))
    d.text((40, 60), "AI artifacts: texture banding, impossible specular highlights", font=font(24, True), fill=(255, 138, 138))
    # missing EXIF badge
    d.rounded_rectangle([610, 990, 870, 1050], radius=12, fill=(168, 32, 32))
    d.text((636, 1008), "NO EXIF", font=font(30, True), fill=(255, 255, 255))
    img.save(path)


def dashcam_frame(path: Path) -> None:
    img = Image.new("RGB", (1280, 720), (18, 20, 26))
    d = ImageDraw.Draw(img)
    # night cabin: windshield glow, dashboard
    d.rectangle([0, 0, 1280, 300], fill=(26, 30, 42))
    for i in range(60):  # street lights streaking past
        x = 40 + i * 21
        d.ellipse([x, 90, x + 40, 130], fill=(250, 214, 140))
    d.rectangle([0, 300, 1280, 460], fill=(34, 38, 50))
    d.rounded_rectangle([120, 320, 1160, 452], radius=24, fill=(22, 25, 33))  # dash
    # driver turning around: head/shoulder silhouette + gesturing arm
    d.ellipse([520, 430, 700, 610], fill=(30, 32, 40))  # torso
    d.ellipse([560, 300, 660, 400], fill=(214, 176, 140))  # head
    d.polygon([(660, 420), (880, 330), (900, 380), (680, 470)], fill=(30, 32, 40))  # arm
    d.ellipse([880, 300, 940, 360], fill=(214, 176, 140))  # hand
    # dashboard clock
    d.rounded_rectangle([980, 60, 1250, 150], radius=12, fill=(8, 10, 14))
    d.text([1010, 84], "11:45 PM", font=font(46, True), fill=(74, 222, 128))
    d.text((40, 60), "CH-01 · cabin cam · 23:45", font=font(28, True), fill=(148, 163, 184))
    d.text((40, 660), "REC ●", font=font(30, True), fill=(239, 68, 68))
    img.save(path)


def video_poster(path: Path) -> None:
    """Poster frame for DISP-007: a covert back-seat night recording.

    Deliberately dark and hand-held looking — the same low-light cabin the
    ingestion pipeline flags as "night footage, visual detail is limited".
    """
    img = Image.new("RGB", (1280, 720), (10, 11, 16))
    d = ImageDraw.Draw(img)
    rnd = random.Random(29)
    for _ in range(2400):  # sensor noise + crushed shadows
        x, y = rnd.randint(0, 1280), rnd.randint(0, 720)
        v = rnd.randint(8, 40)
        d.point((x, y), fill=(v, v + 1, v + 5))
    # windshield glow through the front screen
    d.rectangle([0, 0, 1280, 220], fill=(26, 30, 44))
    for i in range(40):
        x = 30 + i * 32
        d.ellipse([x, 70, x + 26, 104], fill=(222, 196, 140))
    # two front seats, seen from behind
    for cx in (330, 950):
        d.rounded_rectangle([cx - 150, 250, cx + 150, 720], radius=60, fill=(24, 25, 32))
    # driver's head + the arm reaching back over the seat
    d.ellipse([880, 300, 980, 400], fill=(96, 88, 84))
    d.polygon([(940, 380), (700, 520), (740, 570), (980, 440)], fill=(30, 30, 38))
    d.ellipse([660, 500, 730, 570], fill=(96, 88, 84))
    # recording overlay
    d.rounded_rectangle([60, 60, 700, 140], radius=12, fill=(0, 0, 0))
    d.text((84, 84), "disp007_harassment.mp4 · 00:03 / 00:06", font=font(38, True), fill=(255, 214, 102))
    d.text((40, 660), "REC ●", font=font(30, True), fill=(239, 68, 68))
    d.text((120, 664), "low-light · back seat · 23:12", font=font(24), fill=(148, 163, 184))
    img.save(path)


# ---------------------------------------------------------------------------
# Agent avatars
# ---------------------------------------------------------------------------

AGENT_STYLE = {
    "orchestrator": ("#94a3b8", "OR"),
    "sla_router": ("#fb7185", "SLA"),
    "evidence_collection": ("#2dd4bf", "COL"),
    "evidence": ("#22d3ee", "EVD"),
    "fraud": ("#ef4444", "FRD"),
    "policy": ("#818cf8", "PRC"),
    "asr": ("#f59e0b", "ASR"),
    "vision": ("#e879f9", "VIS"),
    "rider_advocate": ("#60a5fa", "RAD"),
    "driver_advocate": ("#fbbf24", "DAD"),
    "judge": ("#34d399", "JDG"),
    "escalation": ("#fb923c", "ESC"),
    "learning": ("#a3e635", "LRN"),
}


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def avatar(role: str, colour: str, code: str, path: Path, size: int = 192) -> None:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base = hex_rgb(colour)
    for y in range(size):  # vertical gradient
        t = y / size
        shade = tuple(int(c * (0.55 + 0.55 * t)) for c in base)
        d.line([(0, y), (size, y)], fill=shade + (255,))
    # rounded mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.28), fill=255)
    img.putalpha(mask)
    # glyph ring + initials
    d2 = ImageDraw.Draw(img)
    d2.ellipse(
        [int(size * 0.12), int(size * 0.12), int(size * 0.88), int(size * 0.88)],
        outline=(255, 255, 255, 90),
        width=max(2, size // 48),
    )
    f = font(int(size * 0.30), True)
    box = d2.textbbox((0, 0), code, font=f)
    d2.text(
        ((size - (box[2] - box[0])) / 2, (size - (box[3] - box[1])) / 2 - size * 0.02),
        code,
        font=f,
        fill=(255, 255, 255, 245),
    )
    img.save(path)


# ---------------------------------------------------------------------------
# Sample payloads for the upload endpoints
# ---------------------------------------------------------------------------


def write_argument_wav(path: Path, seconds: float = 42.0, rate: int = 16000) -> None:
    """Speech-like modulated noise (a placeholder for real recorded audio)."""
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            t = i / rate
            # two "voices": a low male-ish carrier and a higher reply, plus
            # amplitude bursts so the waveform looks like turn-taking speech.
            burst = 0.55 + 0.45 * math.sin(2 * math.pi * (t % 6.0) / 6.0)
            envelope = max(0.0, math.sin(2 * math.pi * 2.7 * t)) * burst
            carrier = math.sin(2 * math.pi * 145 * t) + 0.6 * math.sin(2 * math.pi * 290 * t)
            sample = int(9000 * envelope * carrier + 700 * math.sin(2 * math.pi * 60 * t))
            data += struct.pack("<h", max(-32768, min(32767, sample)))
        out.writeframes(bytes(data))

    # Sidecar dialogue script. Speech recognition cannot run offline, so the
    # mock recording carries its own transcript next to the waveform; the
    # simulated ASR provider reads it and the downstream agents score it.
    path.with_suffix(".txt").write_text(
        "driver: You stupid passenger, shut up and sit there!\n"
        "rider: Please slow down, you are scaring me.\n"
        "driver: I will find you after this trip, I know where you live!\n"
        "rider: I am recording this, stop the car.\n"
        "driver: Say one more word and I will break your phone.\n",
        encoding="utf-8",
    )


def write_cabin_mp4(path: Path, seconds: int = 6) -> None:
    """6-second cabin-camera style clip (synthetic, has motion + a counter).

    Encoders vary by host build (libx264 is often absent), so try a few until
    one works — the clip only has to decode and show visible motion.
    """
    if path.exists():
        return
    _encode_testsrc(path, seconds, "curves=all='0/0.15 0.5/0.45 1/0.85'")
    raise RuntimeError(f"no usable ffmpeg encoder for {path}")


def _encode_testsrc(
    path: Path, seconds: int, video_filter: str, bitrate: str = "600k"
) -> bool:
    """Encode a synthetic clip, trying every encoder the host build offers."""
    for encoder in ("libx264", "libopenh264", "mpeg4", "libvpx-vp9"):
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"testsrc=size=640x360:rate=25:duration={seconds}",
                "-vf",
                video_filter,
                "-c:v",
                encoder,
                "-b:v",
                bitrate,
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and path.exists():
            return True
    return False


def write_harassment_mp4(path: Path, seconds: int = 6) -> None:
    """DISP-007: a deliberately dark, hand-held night recording.

    The clip is crushed to a very low mean luminance on purpose so the vision
    agent's "night footage, visual detail is limited" integrity flag fires —
    that is exactly the finding a low-light covert cabin recording should
    produce, and it is what the reviewer sees in the escalation packet.
    """
    if path.exists():
        return
    dark = "curves=all='0/0.0 0.5/0.09 1/0.20',noise=alls=10:allf=t+u"
    if not _encode_testsrc(path, seconds, dark):
        raise RuntimeError(f"no usable ffmpeg encoder for {path}")


def write_argument_mp3(path: Path, seconds: float = 42.0, rate: int = 16000) -> None:
    """DISP-006: the heated verbal argument, encoded as MP3 for web playback.

    The waveform is generated as WAV first (the offline ASR can only probe a
    real audio stream), then transcoded to MP3 so browsers play it natively.
    The sidecar ``<name>.txt`` dialogue script follows the MP3 so the
    deterministic ASR still "hears" the argument without TRTC credentials.
    """
    wav = path.with_suffix(".wav")
    write_argument_wav(wav, seconds, rate)
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "64k", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not path.exists():
        raise RuntimeError(f"mp3 encoding failed for {path}: {result.stderr[-400:]}")
    wav.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Manifest of Miora prompts
# ---------------------------------------------------------------------------

MIORA_PROMPTS = {
    "disp001_route_deviation.png": (
        "A high-fidelity UI mockup of a ride-hailing app map on a smartphone. The map shows a "
        "straight-line suggested route in blue, but the actual GPS track taken by the car is in "
        "red, showing a wildly inefficient looping path through dense city traffic."
    ),
    "disp002_no_show_chat.png": (
        "A UI mockup of a ride-hailing chat screen. The driver has sent three messages saying 'I "
        "am at the lobby' and 'Waiting for 5 minutes', with no replies from the passenger. A "
        "prominent digital wait-timer overlay displays '08:00 elapsed'."
    ),
    "disp004_genuine_spill.png": (
        "A realistic smartphone photo of the back seat of a Honda HR-V. A large, wet coffee spill "
        "is soaking into the fabric seat. The photo has a visible digital timestamp overlay "
        "reading '2026-09-13 09:15 AM' to match the trip completion time."
    ),
    "disp003_fake_spill.png": (
        "An AI-generated, slightly unrealistic image of french fries and ketchup scattered on a "
        "car seat, with subtle visual artifacts and missing EXIF data, simulating a fraudulent "
        "'vomit fraud' cleaning fee claim."
    ),
    "disp006_arguement.mp3": (
        "An 8-second covert in-cabin audio recording of a heated verbal argument. The rider "
        "politely asks the driver to lower the air-conditioning temperature; the driver shouts "
        "back with insults and refuses, escalating into open hostility."
    ),
    "disp007_harassment.mp4": (
        "A 12-second low-light covert night recording shot from the back seat of a ride-hailing "
        "car by a female passenger, in portrait orientation (768x1258). The driver reaches back "
        "while driving and makes inappropriate physical contact with her leg."
    ),
    "agents/<role>.png": (
        "Flat vector avatar for a dispute-resolution AI agent: rounded square badge, gradient "
        "background in the agent's accent colour, three-letter monogram, thin white ring."
    ),
}


def render(renderer, path: Path, label: str) -> None:
    """Render ``path`` unless a real Miora asset has already been dropped in.

    The dossier assets are hand-supplied Miora renders (multi-megabyte photos,
    a recorded argument, a night video). Re-running the generator must never
    clobber them, so an existing non-empty file is always kept.
    """
    if path.exists() and path.stat().st_size > 0:
        print(f"skip    {path.name:34s} (existing asset preserved)")
        return
    renderer(path)
    print(f"wrote   {path.name:34s} {label}")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    AVATARS.mkdir(parents=True, exist_ok=True)
    SAMPLES.mkdir(parents=True, exist_ok=True)

    render(route_deviation, ASSETS / "disp001_route_deviation.png", "PNG")
    render(no_show_chat, ASSETS / "disp002_no_show_chat.png", "PNG")
    render(genuine_spill, ASSETS / "disp004_genuine_spill.png", "PNG")
    render(fake_spill, ASSETS / "disp003_fake_spill.png", "PNG")

    for role, (colour, code) in AGENT_STYLE.items():
        avatar(role, colour, code, AVATARS / f"{role}.png")

    render(write_argument_wav, SAMPLES / "disp006_argument.wav", "WAV (upload sample)")
    render(write_cabin_mp4, SAMPLES / "disp007_cabin.mp4", "MP4 (upload sample)")

    # --- Phase 3.2: the named dossier assets referenced by cases.py --------
    # Both live under frontend/public/assets/miora so the UI serves them at
    # /assets/miora/... and the backend resolves the same file for ingestion.
    render(write_argument_mp3, ASSETS / "disp006_arguement.mp3", "MP3")
    render(write_harassment_mp4, ASSETS / "disp007_harassment.mp4", "MP4")

    manifest = {
        "generator": "scripts/generate_mock_assets.py",
        "note": (
            "Assets are locally rendered stand-ins for Tencent Miora output. Replace any file "
            "with a real Miora render of the recorded prompt — the UI references them by name. "
            "The generator skips any file that already exists, so hand-supplied Miora renders "
            "survive re-running the script."
        ),
        "assets": MIORA_PROMPTS,
        "agent_avatars": {role: AGENT_STYLE[role][0] for role in AGENT_STYLE},
    }
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"assets  -> {ASSETS}")
    print(f"avatars -> {AVATARS} ({len(AGENT_STYLE)} agents)")
    print(f"samples -> {SAMPLES}")


if __name__ == "__main__":
    main()
