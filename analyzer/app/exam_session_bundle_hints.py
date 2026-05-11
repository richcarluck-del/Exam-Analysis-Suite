"""Infer bundle directory path for ExamSession rows where bundle_dir was never persisted."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from shared import models


def _nearest_bundle_root_from_file(path: Path) -> Optional[str]:
    """Walk parents until a directory containing manifest.json is found."""
    try:
        p = path
        if p.is_dir():
            cur = p
        else:
            cur = p.parent
        for _ in range(32):
            if (cur / "manifest.json").is_file():
                return str(cur.resolve())
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
    except OSError:
        return None
    return None


def _guess_bundle_from_storage_url(raw: Optional[str]) -> Optional[str]:
    if not raw or not isinstance(raw, str):
        return None
    s = raw.strip()
    if s.startswith(("http://", "https://", "data:")):
        return None
    if s.startswith("file://"):
        s = s[7:]
    try:
        p = Path(str(s).replace("/", "\\"))
    except Exception:
        return None
    if not p.is_absolute():
        return None
    return _nearest_bundle_root_from_file(p)


def infer_bundle_dir_for_session(db: Session, exam_session_id: int) -> Optional[str]:
    first_q = (
        db.query(models.ExamSessionQuestion)
        .filter(models.ExamSessionQuestion.exam_session_id == exam_session_id)
        .order_by(models.ExamSessionQuestion.id.asc())
        .first()
    )
    if not first_q:
        return None

    asset = (
        db.query(models.Asset)
        .filter(
            models.Asset.owner_type == "exam_question",
            models.Asset.owner_id == first_q.id,
            models.Asset.asset_role == "question_crop",
        )
        .order_by(models.Asset.id.asc())
        .first()
    )
    if not asset or not asset.storage_url:
        return None
    return _guess_bundle_from_storage_url(asset.storage_url)


def batch_infer_bundle_dirs(db: Session, exam_session_ids: List[int]) -> Dict[int, str]:
    """For sessions missing bundle_dir in DB, infer raw root path from first question image."""
    out: Dict[int, str] = {}
    for sid in exam_session_ids:
        guessed = infer_bundle_dir_for_session(db, sid)
        if guessed:
            out[sid] = guessed
    return out


def display_bundle_dir(
    db: Session,
    es: models.ExamSession,
    inferred_map: Optional[Dict[int, str]] = None,
) -> Optional[str]:
    """Return stored bundle_dir, or inferred path with suffix for testers."""
    if es.bundle_dir:
        return es.bundle_dir
    raw = (inferred_map or {}).get(es.id) if inferred_map is not None else infer_bundle_dir_for_session(db, es.id)
    if raw:
        return f"{raw}（推断自首张题图路径）"
    return None
