from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from shared import models


_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[，,。；;：:、（）()【】\[\]{}《》<>“”\"'‘’·•\-—_]+")
_MATH_RE = re.compile(r"[∀∃∈∉⇒⇔↔→←=<>≤≥+\-*/^0-9a-zA-Z]+")
_SUFFIX_PATTERNS = (
    re.compile(r"(?:及其)?常见表述$"),
    re.compile(r"真假$"),
    re.compile(r"的(?:定义|概念|含义|意义|判定|判断|方法|规律|规则|性质|公式|定理|结构|常见表述|等价表示|参数求解)$"),
    re.compile(r"(?:定义|概念|判定|判断|方法|规律|规则|公式|定理|结构|求解|验证|运算)$"),
)


@dataclass(frozen=True)
class DedupDecision:
    point: Optional[models.KnowledgePoint]
    reason: str
    score: float = 0.0


def _dedup_enabled() -> bool:
    return os.environ.get("KNOWLEDGE_POINT_DEDUP_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _trgm_threshold() -> float:
    try:
        value = float(os.environ.get("KNOWLEDGE_POINT_DEDUP_TRGM_THRESHOLD", "0.92"))
    except (TypeError, ValueError):
        value = 0.92
    return max(0.75, min(value, 0.99))


def normalize_knowledge_point_name(value: str) -> str:
    """Normalize a KP name for exact dedup checks.

    This is intentionally conservative: it removes whitespace/punctuation and
    normalizes full-width chars, but does not collapse semantic qualifiers.
    """
    text_value = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text_value = _SPACE_RE.sub("", text_value)
    text_value = _PUNCT_RE.sub("", text_value)
    return text_value


def concept_dedup_key(value: str) -> str:
    """A stricter concept key used for common LLM suffix variants.

    Examples:
      充分条件的判定 -> 充分条件
      全称命题真假的判定 -> 全称命题真假

    The key is only used when it exactly matches an existing canonical/alias key;
    it is not used for broad fuzzy merging.
    """
    key = normalize_knowledge_point_name(value)
    # Drop standalone formula tails like p⇒q only after punctuation has been normalized.
    key = _MATH_RE.sub("", key) if any(ch in key for ch in "∀∃∈∉⇒⇔↔→←") else key
    changed = True
    while changed:
        changed = False
        for pattern in _SUFFIX_PATTERNS:
            next_key = pattern.sub("", key)
            if next_key != key:
                key = next_key
                changed = True
    return key or normalize_knowledge_point_name(value)


def _scope_compatible_query(query, *, subject: Optional[str], tenant_id: Optional[int]):
    if tenant_id is not None:
        query = query.filter(or_(models.KnowledgePoint.tenant_id == tenant_id, models.KnowledgePoint.tenant_id.is_(None)))
    if subject:
        query = query.filter(or_(models.KnowledgePoint.subject == subject, models.KnowledgePoint.subject.is_(None)))
    return query


def _aliases(point: models.KnowledgePoint) -> list[str]:
    raw = point.aliases_json
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item or "").strip()]
    return []


def add_alias_if_missing(point: models.KnowledgePoint, alias: str) -> bool:
    alias = str(alias or "").strip()
    if not alias or alias == (point.canonical_name or ""):
        return False
    existing = _aliases(point)
    existing_norms = {normalize_knowledge_point_name(item) for item in existing}
    alias_norm = normalize_knowledge_point_name(alias)
    if not alias_norm or alias_norm == normalize_knowledge_point_name(point.canonical_name or ""):
        return False
    if alias_norm in existing_norms:
        return False
    point.aliases_json = [*existing, alias]
    return True


def _fill_missing_scope(point: models.KnowledgePoint, *, subject: Optional[str], grade_scope: Optional[str]) -> bool:
    changed = False
    if subject and not point.subject:
        point.subject = subject
        changed = True
    if grade_scope and not point.grade_scope:
        point.grade_scope = grade_scope
        changed = True
    return changed


def _candidate_points(
    db: Session,
    *,
    subject: Optional[str],
    tenant_id: Optional[int],
    limit: int = 500,
) -> list[models.KnowledgePoint]:
    query = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.is_active.is_(True))
    query = _scope_compatible_query(query, subject=subject, tenant_id=tenant_id)
    return query.order_by(models.KnowledgePoint.id.asc()).limit(limit).all()


def _find_by_normalized_key(
    db: Session,
    *,
    name: str,
    subject: Optional[str],
    tenant_id: Optional[int],
) -> DedupDecision:
    exact_key = normalize_knowledge_point_name(name)
    concept_key = concept_dedup_key(name)
    if not exact_key:
        return DedupDecision(None, "empty_name")

    best: Optional[models.KnowledgePoint] = None
    best_reason = ""
    for point in _candidate_points(db, subject=subject, tenant_id=tenant_id):
        canon_key = normalize_knowledge_point_name(point.canonical_name or "")
        alias_keys = {normalize_knowledge_point_name(alias) for alias in _aliases(point)}
        concept_keys = {concept_dedup_key(point.canonical_name or "")}
        concept_keys.update(concept_dedup_key(alias) for alias in _aliases(point))

        if exact_key == canon_key:
            return DedupDecision(point, "exact_canonical_name", 1.0)
        if exact_key in alias_keys:
            return DedupDecision(point, "exact_alias", 1.0)
        if concept_key and concept_key == canon_key:
            best = point
            best_reason = "concept_key_canonical"
            break
        if concept_key and concept_key in alias_keys.union(concept_keys):
            best = point
            best_reason = "concept_key_alias"
            break

    if best is not None:
        return DedupDecision(best, best_reason, 0.98)
    return DedupDecision(None, "no_normalized_match")


def _pg_trgm_available(db: Session) -> bool:
    try:
        return bool(db.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='pg_trgm')")).scalar())
    except Exception:
        return False


def _find_by_trgm(
    db: Session,
    *,
    name: str,
    subject: Optional[str],
    tenant_id: Optional[int],
) -> DedupDecision:
    if not _pg_trgm_available(db):
        return DedupDecision(None, "pg_trgm_unavailable")

    threshold = _trgm_threshold()
    params: dict[str, Any] = {"name": name, "threshold": threshold}
    filters = ["kp.is_active IS TRUE", "similarity(kp.canonical_name, :name) >= :threshold"]
    if subject:
        filters.append("(kp.subject = :subject OR kp.subject IS NULL)")
        params["subject"] = subject
    if tenant_id is not None:
        filters.append("(kp.tenant_id = :tenant_id OR kp.tenant_id IS NULL)")
        params["tenant_id"] = tenant_id

    rows = db.execute(
        text(
            f"""
            SELECT kp.id, similarity(kp.canonical_name, :name) AS score
            FROM knowledge_points kp
            WHERE {' AND '.join(filters)}
            ORDER BY score DESC, kp.id ASC
            LIMIT 5
            """,
        ),
        params,
    ).all()
    if not rows:
        return DedupDecision(None, "no_trgm_match")

    name_key = normalize_knowledge_point_name(name)
    for kp_id, score in rows:
        point = db.query(models.KnowledgePoint).filter(models.KnowledgePoint.id == int(kp_id)).first()
        if not point:
            continue
        point_key = normalize_knowledge_point_name(point.canonical_name or "")
        if not point_key:
            continue
        length_ratio = min(len(name_key), len(point_key)) / max(len(name_key), len(point_key))
        # Guard against false positives like "充分条件" vs "必要不充分条件".
        if float(score or 0.0) >= threshold and length_ratio >= 0.78:
            return DedupDecision(point, "pg_trgm_high_similarity", float(score or 0.0))
    return DedupDecision(None, "trgm_guard_rejected")


def find_existing_knowledge_point(
    db: Session,
    *,
    canonical_name: str,
    subject: Optional[str] = None,
    tenant_id: Optional[int] = None,
) -> DedupDecision:
    if not _dedup_enabled():
        return DedupDecision(None, "dedup_disabled")

    normalized = _find_by_normalized_key(db, name=canonical_name, subject=subject, tenant_id=tenant_id)
    if normalized.point is not None:
        return normalized
    return _find_by_trgm(db, name=canonical_name, subject=subject, tenant_id=tenant_id)


def get_or_create_knowledge_point(
    db: Session,
    *,
    canonical_name: str,
    subject: Optional[str] = None,
    grade_scope: Optional[str] = None,
    source_origin: str = "model",
    tenant_id: Optional[int] = None,
    extra_fields: Optional[dict[str, Any]] = None,
) -> models.KnowledgePoint:
    name = str(canonical_name or "").strip()
    if not name:
        raise ValueError("canonical_name 不能为空")

    decision = find_existing_knowledge_point(
        db,
        canonical_name=name,
        subject=subject,
        tenant_id=tenant_id,
    )
    if decision.point is not None:
        changed = add_alias_if_missing(decision.point, name)
        changed = _fill_missing_scope(decision.point, subject=subject, grade_scope=grade_scope) or changed
        if changed:
            db.flush()
        return decision.point

    payload = {
        "canonical_name": name,
        "subject": subject,
        "grade_scope": grade_scope,
        "knowledge_type": "concept",
        "source_origin": source_origin,
        "review_status": "draft",
        "is_active": True,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    if extra_fields:
        payload.update({k: v for k, v in extra_fields.items() if v is not None})

    point = models.KnowledgePoint(**payload)
    db.add(point)
    db.flush()
    return point
