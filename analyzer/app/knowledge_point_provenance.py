"""知识点溯源写入：在创建/关联知识点时调用，供衍生层按 provenance 拉 grounded 语料。"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

SOURCE_KIND_KNOWLEDGE_BLOCK = "knowledge_block"


def record_knowledge_point_provenance(
    db: Session,
    *,
    knowledge_point_id: int,
    source_kind: str,
    source_id: int,
    package_id: Optional[int] = None,
    origin_step: str = "",
    is_primary: bool = True,
    extra: Optional[Mapping[str, Any]] = None,
) -> None:
    """若不存在 (kp, kind, source_id) 则插入一行；已存在则忽略。"""
    from sqlalchemy import and_
    from shared.models import KnowledgePointProvenance

    q = (
        db.query(KnowledgePointProvenance)
        .filter(
            and_(
                KnowledgePointProvenance.knowledge_point_id == knowledge_point_id,
                KnowledgePointProvenance.source_kind == source_kind,
                KnowledgePointProvenance.source_id == source_id,
            )
        )
        .first()
    )
    if q is not None:
        return
    row = KnowledgePointProvenance(
        knowledge_point_id=knowledge_point_id,
        source_kind=source_kind,
        source_id=source_id,
        package_id=package_id,
        origin_step=origin_step or "",
        is_primary=is_primary,
        extra_json=dict(extra) if extra else None,
    )
    db.add(row)
