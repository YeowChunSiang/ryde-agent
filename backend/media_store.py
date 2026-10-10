"""Registry for multi-modal payloads uploaded through ``/upload-*`` (Phase 3).

Audio and video evidence arrives *before* arbitration: a rider attaches a
recording when they file the safety complaint, a driver attaches a dashcam clip
when they claim damage. Uploads therefore have to be parked somewhere until the
case is loaded, then grafted onto the dossier's ``media_attachments``.

The store keeps:

* the raw payload on disk (``Settings.media_dir``)
* the derived analysis (ASR transcript / extracted keyframes)
* the association ``case_id -> [attachment]``

so ``POST /dispute`` can enrich the dossier without the caller re-uploading
anything.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from config import Settings
from models import DisputeCase, MediaAttachment

AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac", ".opus"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def media_type_for(filename: str) -> str:
    """Classify an uploaded payload by extension (audio / video / image)."""
    suffix = Path(filename).suffix.lower()
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    return "image"


def resolve_media_path(path: str | Path, settings: Settings) -> Optional[Path]:
    """Resolve a stored media reference to an absolute path.

    Accepts absolute paths, paths relative to the backend root (used by the
    packaged sample assets) and paths relative to the upload directory.
    """
    raw = Path(str(path))
    candidates = [raw]
    if not raw.is_absolute():
        backend_root = Path(__file__).resolve().parent
        candidates.extend(
            [
                backend_root / raw,
                Path(settings.media_dir).expanduser() / raw,
                backend_root / Path(settings.media_dir).expanduser() / raw,
            ]
        )
    for candidate in candidates:
        try:
            if candidate.exists():
                return candidate.resolve()
        except OSError:  # pragma: no cover - defensive
            continue
    return None


class MediaStore:
    """In-memory index of uploaded payloads, keyed by case / dispute id."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = Path(settings.media_dir).expanduser()
        if not self.root.is_absolute():
            self.root = (Path(__file__).resolve().parent / self.root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._by_case: dict[str, list[MediaAttachment]] = {}

    # --- persistence ------------------------------------------------------
    def save(self, filename: str, payload: bytes, kind: str) -> Path:
        """Persist an upload under ``media_dir/<kind>/<filename>``."""
        target_dir = self.root / kind
        target_dir.mkdir(parents=True, exist_ok=True)
        safe = filename.replace("\\", "_").replace("/", "_")
        target = target_dir / safe
        if target.exists():  # keep uploads deterministic and collision-free
            stem, suffix = target.stem, target.suffix
            counter = 1
            while target.exists():
                target = target_dir / f"{stem}-{counter}{suffix}"
                counter += 1
        target.write_bytes(payload)
        return target

    # --- registry ---------------------------------------------------------
    def attach(self, key: str, attachment: MediaAttachment) -> None:
        self._by_case.setdefault(key, []).append(attachment)

    def pending(self, key: str) -> list[MediaAttachment]:
        return list(self._by_case.get(key, []))

    def all_keys(self) -> list[str]:
        return sorted(self._by_case)

    def clear(self, key: Optional[str] = None) -> None:
        if key is None:
            self._by_case.clear()
        else:
            self._by_case.pop(key, None)

    def merge_into(self, case: DisputeCase) -> list[MediaAttachment]:
        """ graft uploaded payloads onto a freshly-loaded dossier."""
        keys = {case.dispute_id, case.case_id} if hasattr(case, "case_id") else {case.dispute_id}
        merged: list[MediaAttachment] = []
        for key in keys:
            for att in self.pending(str(key)):
                if all(a.attachment_id != att.attachment_id for a in case.media_attachments):
                    case.media_attachments.append(att)
                    merged.append(att)
        return merged

    # --- helpers ----------------------------------------------------------
    def web_path(self, path: Path) -> str:
        """``/media/<relative path>`` — the URL FastAPI serves the file at."""
        try:
            rel = path.relative_to(self.root)
        except ValueError:
            rel = Path(path.name)
        return f"/media/{rel.as_posix()}"

    def prune_frames(self, keep: int = 6) -> int:
        """Delete old keyframe directories (housekeeping for long-lived demos)."""
        frame_root = Path(self.settings.frame_dir).expanduser()
        if not frame_root.is_absolute():
            frame_root = (Path(__file__).resolve().parent / frame_root).resolve()
        if not frame_root.exists():
            return 0
        dirs = sorted((d for d in frame_root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
        removed = 0
        for directory in dirs[:-keep] if len(dirs) > keep else []:
            shutil.rmtree(directory, ignore_errors=True)
            removed += 1
        return removed
