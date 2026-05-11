"""知识点图谱投影（Graph Layer）

把 PostgreSQL 业务表里已经存在的结构化关联，统一投影到 `entity_graph_edges`：

  (source_entity_type, source_entity_id) --relation_type--> (target_entity_type, target_entity_id)

投影规则（与 docs/knowledge-point-system-technical-design.md 保持一致）：

    KnowledgeBlock.knowledge_point_id
        knowledge_point -contains-> knowledge_block

    KnowledgePackagePoint
        knowledge_package -covers-> knowledge_point

    KnowledgePackageQuestion
        knowledge_package -includes_question-> question_item

    KnowledgeQuestionLink（按 relation_type 细分）
        knowledge_point -relates_strong|relates_adjacent|relates_fallback-> question_item
        question_item -tests-> knowledge_point

    KnowledgePointRelation
        knowledge_point -<relation_type>-> knowledge_point

投影语义：
  - 写入受 KNOWLEDGE_GRAPH_ENABLED 控制；关闭时投影函数直接跳过。
  - 对同一 (source,target,relation_type) 采用 upsert（先删后插），避免脏残留。
  - 关系的权重统一存到 weight_score（来自 relevance_score / strength_score），
    置信度存到 confidence，其余证据（link_id、审核态、外键等）放到 evidence_json。
  - source_origin：business_projection（由业务表投影），未来如果有外部抽取
    可另写 source_origin="llm_extract" 与之合并。

Neo4j 同步：
  - 本模块不直接依赖 Neo4j 客户端，避免强耦合。
  - 若需要把投影结果同步到 Neo4j，可以在 project_* 后调用
    `sync_edges_to_neo4j(edges)`（由外部脚本实现）。保留回调钩子 ``neo4j_sink``。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from shared import models

from .config import KNOWLEDGE_GRAPH_ENABLED


logger = logging.getLogger(__name__)


Neo4jSink = Callable[[List[Dict[str, Any]]], None]


# =============================================================================
# 枚举 / 常量
# =============================================================================

ENTITY_KNOWLEDGE_POINT = "knowledge_point"
ENTITY_KNOWLEDGE_PACKAGE = "knowledge_package"
ENTITY_KNOWLEDGE_BLOCK = "knowledge_block"
ENTITY_KNOWLEDGE_ATOM = "knowledge_atom"
ENTITY_KNOWLEDGE_DERIVATIVE = "knowledge_derivative"
ENTITY_QUESTION_ITEM = "question_item"

REL_POINT_CONTAINS_BLOCK = "contains_block"
REL_POINT_CONTAINS_ATOM = "contains_atom"
REL_PACKAGE_COVERS_POINT = "covers_point"
REL_PACKAGE_INCLUDES_QUESTION = "includes_question"
REL_POINT_DERIVES = "derives"
REL_POINT_RELATES_STRONG = "relates_strong"
REL_POINT_RELATES_ADJACENT = "relates_adjacent"
REL_POINT_RELATES_FALLBACK = "relates_fallback"
REL_POINT_RELATES_GENERIC = "relates_generic"
REL_QUESTION_TESTS_POINT = "tests"

SOURCE_ORIGIN = "business_projection"
_PROJECTABLE_KP_RELATION_STATUSES = {"approved", "explicit"}
_PROJECTABLE_PENDING_KP_RELATION_MIN_CONFIDENCE = 0.90


_QUESTION_LINK_TIER_MAP = {
    "topic_strong": REL_POINT_RELATES_STRONG,
    "topic_adjacent": REL_POINT_RELATES_ADJACENT,
    "topic_evidence": REL_POINT_RELATES_ADJACENT,
    "topic_fallback": REL_POINT_RELATES_FALLBACK,
}


# =============================================================================
# 边结构
# =============================================================================


@dataclass
class EdgeRow:
    source_entity_type: str
    source_entity_id: int
    target_entity_type: str
    target_entity_id: int
    relation_type: str
    weight_score: Optional[float] = None
    confidence: Optional[float] = None
    evidence: Optional[Dict[str, Any]] = None

    def as_model_kwargs(self) -> Dict[str, Any]:
        return {
            "source_entity_type": self.source_entity_type,
            "source_entity_id": int(self.source_entity_id),
            "target_entity_type": self.target_entity_type,
            "target_entity_id": int(self.target_entity_id),
            "relation_type": self.relation_type,
            "weight_score": self.weight_score,
            "confidence": self.confidence,
            "evidence_json": self.evidence or {},
            "source_origin": SOURCE_ORIGIN,
        }

    def signature(self) -> Tuple[str, int, str, int, str]:
        return (
            self.source_entity_type,
            int(self.source_entity_id),
            self.target_entity_type,
            int(self.target_entity_id),
            self.relation_type,
        )


# =============================================================================
# 内部工具
# =============================================================================


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_relation_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).lower()


def _name_fragments(name: str | None) -> list[str]:
    if not name:
        return []
    raw_parts = re.split(r"[，。、；;：:（）()\\[\\]【】/\\s]+", str(name))
    out: list[str] = []
    for part in raw_parts:
        normalized = _normalize_relation_text(part)
        if len(normalized) >= 2:
            out.append(normalized)
        normalized_no_de = _normalize_relation_text(str(part).replace("的", ""))
        if len(normalized_no_de) >= 2:
            out.append(normalized_no_de)
    if not out:
        normalized = _normalize_relation_text(name)
        if len(normalized) >= 2:
            out.append(normalized)
    suffix_trimmed = re.sub(
        r"(定义|性质|关系|方法|解法|应用|步骤|证明|条件|问题|公式|定理|探究|总结)$",
        "",
        str(name or ""),
    ).strip()
    normalized_trimmed = _normalize_relation_text(suffix_trimmed)
    if len(normalized_trimmed) >= 2:
        out.append(normalized_trimmed)
        trimmed_no_de = _normalize_relation_text(suffix_trimmed.replace("的", ""))
        if len(trimmed_no_de) >= 2:
            out.append(trimmed_no_de)
    return list(dict.fromkeys(out))


def _text_mentions_name(text: str | None, name: str | None) -> bool:
    normalized_text = _normalize_relation_text(text)
    relaxed_text = _normalize_relation_text((text or "").replace("的", ""))
    for fragment in _name_fragments(name):
        if fragment in normalized_text or fragment in relaxed_text:
            return True
    return False


def _name_fragments(name: str | None) -> list[str]:
    if not name:
        return []
    raw = str(name)
    raw_parts = re.split(r"[()\uFF08\uFF09\[\]\u3010\u3011,\uFF0C\u3001/\\\\;\uFF1B:\uFF1A\s]+", raw)
    out: list[str] = []
    suffix_re = re.compile(
        r"(\u5b9a\u4e49|\u6027\u8d28|\u5173\u7cfb|\u65b9\u6cd5|\u89e3\u6cd5|\u5e94\u7528|\u6b65\u9aa4|\u8bc1\u660e|\u6761\u4ef6|\u95ee\u9898|\u516c\u5f0f|\u5b9a\u7406|\u63a2\u7a76|\u603b\u7ed3)$"
    )

    def add_fragment(value: str | None) -> None:
        normalized = _normalize_relation_text(value)
        if len(normalized) >= 2:
            out.append(normalized)

    for part in raw_parts:
        text = str(part or "").strip()
        if not text:
            continue
        add_fragment(text)
        add_fragment(text.replace("\u7684", ""))
        stripped = re.sub(r"^(?:\u5229\u7528|\u5173\u4e8e|\u6709\u5173|\u57fa\u4e8e)", "", text).strip()
        if stripped != text:
            add_fragment(stripped)
        for sub in re.split(r"[\u4e0e\u548c\u53ca\u6216\u3001]|\u4ee5\u53ca", text):
            add_fragment(sub)
            add_fragment(str(sub or "").replace("\u7684", ""))
        suffix_trimmed = suffix_re.sub("", text).strip()
        if suffix_trimmed != text:
            add_fragment(suffix_trimmed)
            add_fragment(suffix_trimmed.replace("\u7684", ""))
        if "\u7684" in text:
            left, right = text.split("\u7684", 1)
            add_fragment(left)
            add_fragment(right)
        method_chunk_match = re.match(
            r"^\s*((?:\u56fe\u8c61|\u5b9a\u4e49|\u590d\u5408\u51fd\u6570|\u5b9e\u6570|\u5bfc\u6570|\u6027\u8d28|\u914d\u65b9|\u6d88\u5143|\u6362\u5143|.*?))\u6cd5(?:\u6c42|\u89e3|\u5224\u65ad|\u8bc1\u660e|\u6bd4\u8f83|\u8ba8\u8bba|\u786e\u5b9a)",
            text,
        )
        if method_chunk_match:
            add_fragment(f"{method_chunk_match.group(1)}\u6cd5")
        if "\u65b9\u6cd5" in text:
            method_prefix = text.split("\u65b9\u6cd5", 1)[0].strip()
            add_fragment(method_prefix)
    if not out:
        add_fragment(raw)
    generic_fragments = {
        "\u6982\u5ff5",
        "\u5b9a\u4e49",
        "\u6027\u8d28",
        "\u5173\u7cfb",
        "\u65b9\u6cd5",
        "\u89e3\u6cd5",
        "\u5e94\u7528",
        "\u6b65\u9aa4",
        "\u8bc1\u660e",
        "\u6761\u4ef6",
        "\u95ee\u9898",
        "\u516c\u5f0f",
        "\u5b9a\u7406",
        "\u63a2\u7a76",
        "\u603b\u7ed3",
        "\u6c42\u6cd5",
        "\u6c42\u89e3",
    }
    filtered: list[str] = []
    for fragment in out:
        if fragment in generic_fragments:
            continue
        if fragment.endswith("\u7684") and len(fragment) <= 6:
            continue
        filtered.append(fragment)
    return list(dict.fromkeys(filtered))


def _text_mentions_name(text: str | None, name: str | None) -> bool:
    normalized_text = _normalize_relation_text(text)
    relaxed_text = _normalize_relation_text((text or "").replace("\u7684", ""))
    fragments = _name_fragments(name)
    strong_fragments = [fragment for fragment in fragments if len(fragment) >= 3]
    if not strong_fragments:
        normalized_name = _normalize_relation_text(name)
        if len(normalized_name) >= 2:
            strong_fragments = [normalized_name]
    for fragment in strong_fragments:
        if fragment in normalized_text or fragment in relaxed_text:
            return True
    return False


def _shared_char_ratio(a: str | None, b: str | None) -> float:
    na = _normalize_relation_text(a)
    nb = _normalize_relation_text(b)
    if not na or not nb:
        return 0.0
    a_set = set(na)
    b_set = set(nb)
    denom = max(len(a_set | b_set), 1)
    return len(a_set & b_set) / denom


def _contains_family(a: str | None, b: str | None) -> bool:
    na = _normalize_relation_text(a)
    nb = _normalize_relation_text(b)
    return bool(na and nb and (na in nb or nb in na))


def _looks_more_specific(candidate: str | None, parent: str | None) -> bool:
    nc = _normalize_relation_text(candidate)
    np = _normalize_relation_text(parent)
    if not nc or not np:
        return False
    if np in nc and len(nc) > len(np):
        return True
    return len(nc) >= len(np) + 3 and _shared_char_ratio(candidate, parent) >= 0.45


def _question_link_relation_type(link: models.KnowledgeQuestionLink) -> str:
    rel = (link.relation_type or "").strip().lower()
    return _QUESTION_LINK_TIER_MAP.get(rel, REL_POINT_RELATES_GENERIC)


def _is_projectable_kp_relation(row: models.KnowledgePointRelation) -> bool:
    """Allow reviewed relations, plus high-confidence pending LLM relations."""
    status = (row.approved_status or "").strip().lower()
    relation_type = (getattr(row, "relation_type", "") or "").strip().lower()
    source_origin = (getattr(row, "source_origin", "") or "").strip().lower()
    if (
        status in _PROJECTABLE_KP_RELATION_STATUSES
        and not (relation_type == "related" and source_origin == "cold_start" and row.evidence_block_id is None)
    ):
        return True
    if status != "pending":
        return False
    confidence = _to_float(row.confidence) or 0.0
    return source_origin == "llm" and confidence >= _PROJECTABLE_PENDING_KP_RELATION_MIN_CONFIDENCE


def _passes_pending_llm_projection_guard(
    row: models.KnowledgePointRelation,
    *,
    source_name: str | None,
    target_name: str | None,
    evidence_preview: str | None,
    evidence_package_id: int | None,
    package_id: int,
) -> bool:
    status = (row.approved_status or "").strip().lower()
    if status in _PROJECTABLE_KP_RELATION_STATUSES:
        return True
    if status != "pending":
        return False
    confidence = _to_float(row.confidence) or 0.0
    source_origin = (getattr(row, "source_origin", "") or "").strip().lower()
    if source_origin != "llm" or confidence < _PROJECTABLE_PENDING_KP_RELATION_MIN_CONFIDENCE:
        return False
    if row.evidence_block_id is None or evidence_package_id != package_id:
        return False

    mentions_source = _text_mentions_name(evidence_preview, source_name)
    mentions_target = _text_mentions_name(evidence_preview, target_name)
    if not (mentions_source or mentions_target):
        return False

    relation_type = (row.relation_type or "").strip().lower()
    same_family = _contains_family(source_name, target_name) or _shared_char_ratio(source_name, target_name) >= 0.50
    same_family_variant = same_family and (
        _looks_more_specific(source_name, target_name) or _looks_more_specific(target_name, source_name)
    )
    if relation_type == "related" and same_family_variant:
        return False
    return True


def _is_projectable_package_point(row: models.KnowledgePackagePoint) -> bool:
    status = (row.approved_status or "").strip().lower()
    rel_type = (row.relation_type or "").strip().lower()
    return status != "placeholder" and rel_type not in {"placeholder", "fallback", "dependency"}


def _append_block_edge(
    edges: List[EdgeRow],
    seen_signatures: set,
    *,
    source_point_id: int,
    block: models.KnowledgeBlock,
    confidence: Optional[float] = None,
    evidence: Optional[Dict[str, Any]] = None,
) -> None:
    edge = EdgeRow(
        source_entity_type=ENTITY_KNOWLEDGE_POINT,
        source_entity_id=int(source_point_id),
        target_entity_type=ENTITY_KNOWLEDGE_BLOCK,
        target_entity_id=block.id,
        relation_type=REL_POINT_CONTAINS_BLOCK,
        confidence=confidence,
        evidence=evidence or {},
    )
    signature = edge.signature()
    if signature in seen_signatures:
        return
    seen_signatures.add(signature)
    edges.append(edge)


def _delete_edges_by_filter(
    db: Session,
    *,
    source_type: Optional[str] = None,
    source_ids: Optional[Sequence[int]] = None,
    target_type: Optional[str] = None,
    target_ids: Optional[Sequence[int]] = None,
    relation_types: Optional[Sequence[str]] = None,
) -> int:
    query = db.query(models.EntityGraphEdge)
    if source_type is not None:
        query = query.filter(models.EntityGraphEdge.source_entity_type == source_type)
    if source_ids is not None:
        if not source_ids:
            return 0
        query = query.filter(models.EntityGraphEdge.source_entity_id.in_(list(source_ids)))
    if target_type is not None:
        query = query.filter(models.EntityGraphEdge.target_entity_type == target_type)
    if target_ids is not None:
        if not target_ids:
            return 0
        query = query.filter(models.EntityGraphEdge.target_entity_id.in_(list(target_ids)))
    if relation_types is not None:
        if not relation_types:
            return 0
        query = query.filter(models.EntityGraphEdge.relation_type.in_(list(relation_types)))
    return int(query.delete(synchronize_session=False) or 0)


def _insert_edges(db: Session, edges: Sequence[EdgeRow]) -> int:
    if not edges:
        return 0
    seen: set = set()
    inserted = 0
    for edge in edges:
        sig = edge.signature()
        if sig in seen:
            continue
        seen.add(sig)
        db.add(models.EntityGraphEdge(**edge.as_model_kwargs()))
        inserted += 1
    if inserted:
        db.flush()
    return inserted


# =============================================================================
# 收集边：单专题包
# =============================================================================


def _collect_edges_for_package(db: Session, package_id: int) -> List[EdgeRow]:
    edges: List[EdgeRow] = []

    # 1) 专题包 ↔ 知识点
    cov_rows = (
        db.query(models.KnowledgePackagePoint)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    )
    cov_rows = [row for row in cov_rows if _is_projectable_package_point(row)]
    point_ids = {int(row.knowledge_point_id) for row in cov_rows if row.knowledge_point_id is not None}
    for row in cov_rows:
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_KNOWLEDGE_PACKAGE,
                source_entity_id=row.package_id,
                target_entity_type=ENTITY_KNOWLEDGE_POINT,
                target_entity_id=row.knowledge_point_id,
                relation_type=REL_PACKAGE_COVERS_POINT,
                weight_score=_to_float(row.weight_score),
                confidence=_to_float(row.confidence),
                evidence={
                    "package_point_id": row.id,
                    "relation_type": row.relation_type,
                    "order_in_package": row.order_in_package,
                    "approved_status": row.approved_status,
                    "source_origin": row.source_origin,
                },
            )
        )

    # 2) 专题包 ↔ 题目
    pq_rows = (
        db.query(models.KnowledgePackageQuestion)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    )
    for row in pq_rows:
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_KNOWLEDGE_PACKAGE,
                source_entity_id=row.package_id,
                target_entity_type=ENTITY_QUESTION_ITEM,
                target_entity_id=row.question_item_id,
                relation_type=REL_PACKAGE_INCLUDES_QUESTION,
                weight_score=None,
                confidence=_to_float(row.confidence),
                evidence={
                    "package_question_id": row.id,
                    "relation_type": row.relation_type,
                    "display_order": row.display_order,
                    "approved_status": row.approved_status,
                },
            )
        )

    # 3) 知识点 ↔ 知识块（只投影本包内的块，避免一次写入过多无关边）
    block_edge_signatures: set = set()
    blocks: List[models.KnowledgeBlock] = []
    if point_ids:
        blocks = (
            db.query(models.KnowledgeBlock)
            .filter(
                models.KnowledgeBlock.package_id == package_id,
                models.KnowledgeBlock.knowledge_point_id.in_(point_ids),
            )
            .all()
        )
        for row in blocks:
            _append_block_edge(
                edges,
                block_edge_signatures,
                source_point_id=int(row.knowledge_point_id),
                block=row,
                evidence={
                    "package_id": row.package_id,
                    "block_role": row.block_role,
                    "section_path": row.section_path,
                    "is_primary": bool(getattr(row, "is_primary", False)),
                    "grounding_source": "block_fk",
                },
            )

        provenance_rows = (
            db.query(models.KnowledgePointProvenance, models.KnowledgeBlock)
            .join(
                models.KnowledgeBlock,
                models.KnowledgeBlock.id == models.KnowledgePointProvenance.source_id,
            )
            .filter(
                models.KnowledgePointProvenance.package_id == package_id,
                models.KnowledgePointProvenance.source_kind == "knowledge_block",
                models.KnowledgePointProvenance.knowledge_point_id.in_(point_ids),
                models.KnowledgeBlock.package_id == package_id,
            )
            .all()
        )
        for provenance, block in provenance_rows:
            _append_block_edge(
                edges,
                block_edge_signatures,
                source_point_id=int(provenance.knowledge_point_id),
                block=block,
                evidence={
                    "package_id": block.package_id,
                    "block_role": block.block_role,
                    "section_path": block.section_path,
                    "is_primary": bool(getattr(provenance, "is_primary", False)),
                    "grounding_source": "knowledge_point_provenance",
                    "origin_step": provenance.origin_step,
                    "provenance_id": provenance.id,
                },
            )

    # 4) 知识点 ↔ 知识原子（本包内）
    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.package_id == package_id)
        .all()
    )
    for row in atoms:
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_KNOWLEDGE_POINT,
                source_entity_id=int(row.knowledge_point_id),
                target_entity_type=ENTITY_KNOWLEDGE_ATOM,
                target_entity_id=row.id,
                relation_type=REL_POINT_CONTAINS_ATOM,
                confidence=_to_float(row.confidence),
                evidence={
                    "package_id": row.package_id,
                    "atom_type": row.atom_type,
                    "review_status": row.review_status,
                    "importance_level": row.importance_level,
                },
            )
        )

    # 5) 知识点 ↔ 题目（经由 KnowledgeQuestionLink 细分 tier）
    #    只投影与「本包内题目」相关的链接（KnowledgePackageQuestion.question_item_id）
    question_ids = [row.question_item_id for row in pq_rows]
    if question_ids:
        q_links = (
            db.query(models.KnowledgeQuestionLink)
            .filter(models.KnowledgeQuestionLink.question_item_id.in_(question_ids))
            .all()
        )
        for row in q_links:
            edges.append(
                EdgeRow(
                    source_entity_type=ENTITY_KNOWLEDGE_POINT,
                    source_entity_id=row.knowledge_point_id,
                    target_entity_type=ENTITY_QUESTION_ITEM,
                    target_entity_id=row.question_item_id,
                    relation_type=_question_link_relation_type(row),
                    weight_score=_to_float(row.relevance_score),
                    confidence=_to_float(row.confidence),
                    evidence={
                        "question_link_id": row.id,
                        "raw_relation_type": row.relation_type,
                        "approved_status": row.approved_status,
                        "entry_point_text": row.entry_point_text,
                    },
                )
            )
            edges.append(
                EdgeRow(
                    source_entity_type=ENTITY_QUESTION_ITEM,
                    source_entity_id=row.question_item_id,
                    target_entity_type=ENTITY_KNOWLEDGE_POINT,
                    target_entity_id=row.knowledge_point_id,
                    relation_type=REL_QUESTION_TESTS_POINT,
                    weight_score=_to_float(row.relevance_score),
                    confidence=_to_float(row.confidence),
                    evidence={
                        "question_link_id": row.id,
                        "raw_relation_type": row.relation_type,
                        "approved_status": row.approved_status,
                        "entry_point_text": row.entry_point_text,
                    },
                )
            )

    # 6) 知识点 ↔ 知识点
    #    evidence_block_id 为空的冷启动关系只在其端点属于本包时投影，避免被每个包重复写入。
    block_ids = [row.id for row in blocks]
    point_id_list = list({int(pid) for pid in point_ids if pid is not None})
    if block_ids or point_id_list:
        rel_predicates = []
        if block_ids:
            rel_predicates.append(models.KnowledgePointRelation.evidence_block_id.in_(block_ids))
        if point_id_list:
            rel_predicates.append(
                and_(
                    models.KnowledgePointRelation.evidence_block_id.is_(None),
                    models.KnowledgePointRelation.source_knowledge_point_id.in_(point_id_list),
                    models.KnowledgePointRelation.target_knowledge_point_id.in_(point_id_list),
                )
            )
        rel_rows = (
            db.query(models.KnowledgePointRelation)
            .filter(or_(*rel_predicates))
            .all()
        )
        relation_point_ids = {
            int(pid)
            for row in rel_rows
            for pid in (row.source_knowledge_point_id, row.target_knowledge_point_id)
            if pid is not None
        }
        point_name_map = {
            int(point.id): str(point.canonical_name or "")
            for point in db.query(models.KnowledgePoint)
            .filter(models.KnowledgePoint.id.in_(list(relation_point_ids)))
            .all()
        } if relation_point_ids else {}
        evidence_block_ids = {int(row.evidence_block_id) for row in rel_rows if row.evidence_block_id is not None}
        evidence_block_map = {
            int(block.id): block
            for block in db.query(models.KnowledgeBlock)
            .filter(models.KnowledgeBlock.id.in_(list(evidence_block_ids)))
            .all()
        } if evidence_block_ids else {}
        seen_rel: set = set()
        for row in rel_rows:
            if not _is_projectable_kp_relation(row):
                continue
            evidence_block = evidence_block_map.get(int(row.evidence_block_id)) if row.evidence_block_id is not None else None
            if not _passes_pending_llm_projection_guard(
                row,
                source_name=point_name_map.get(int(row.source_knowledge_point_id)),
                target_name=point_name_map.get(int(row.target_knowledge_point_id)),
                evidence_preview=getattr(evidence_block, "raw_text", None),
                evidence_package_id=getattr(evidence_block, "package_id", None),
                package_id=package_id,
            ):
                continue
            key = (row.source_knowledge_point_id, row.target_knowledge_point_id, row.relation_type)
            if key in seen_rel:
                continue
            seen_rel.add(key)
            edges.append(
                EdgeRow(
                    source_entity_type=ENTITY_KNOWLEDGE_POINT,
                    source_entity_id=row.source_knowledge_point_id,
                    target_entity_type=ENTITY_KNOWLEDGE_POINT,
                    target_entity_id=row.target_knowledge_point_id,
                    relation_type=row.relation_type or REL_POINT_RELATES_GENERIC,
                    weight_score=_to_float(row.strength_score),
                    confidence=_to_float(row.confidence),
                    evidence={
                        "relation_id": row.id,
                        "approved_status": row.approved_status,
                        "evidence_block_id": row.evidence_block_id,
                    },
                )
            )

    return edges


# =============================================================================
# 对外入口
# =============================================================================


def project_package(
    db: Session,
    package_id: int,
    *,
    neo4j_sink: Optional[Neo4jSink] = None,
    respect_flag: bool = True,
) -> Dict[str, Any]:
    """把一个专题包涉及的全部业务关系投影到 entity_graph_edges。"""

    if respect_flag and not KNOWLEDGE_GRAPH_ENABLED:
        return {
            "status": "skipped",
            "reason": "KNOWLEDGE_GRAPH_ENABLED=false",
            "package_id": package_id,
            "inserted": 0,
            "deleted": 0,
        }

    package = (
        db.query(models.KnowledgePackage)
        .filter(models.KnowledgePackage.id == package_id)
        .first()
    )
    if not package:
        raise ValueError(f"KnowledgePackage {package_id} 不存在")

    edges = _collect_edges_for_package(db, package_id)

    # 先删除与本包相关的旧边，保证幂等
    block_ids = [
        bid
        for (bid,) in db.query(models.KnowledgeBlock.id)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
    ]
    atom_ids = [
        aid
        for (aid,) in db.query(models.KnowledgeAtom.id)
        .filter(models.KnowledgeAtom.package_id == package_id)
        .all()
    ]
    question_ids = [
        qid
        for (qid,) in db.query(models.KnowledgePackageQuestion.question_item_id)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    ]
    point_ids = {
        pid
        for (pid,) in db.query(models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    }

    deleted = 0

    deleted += _delete_edges_by_filter(
        db,
        source_type=ENTITY_KNOWLEDGE_PACKAGE,
        source_ids=[package_id],
    )

    if block_ids:
        deleted += _delete_edges_by_filter(
            db,
            target_type=ENTITY_KNOWLEDGE_BLOCK,
            target_ids=block_ids,
        )

    if atom_ids:
        deleted += _delete_edges_by_filter(
            db,
            target_type=ENTITY_KNOWLEDGE_ATOM,
            target_ids=atom_ids,
        )

    if question_ids and point_ids:
        deleted += _delete_edges_by_filter(
            db,
            source_type=ENTITY_KNOWLEDGE_POINT,
            source_ids=list(point_ids),
            target_type=ENTITY_QUESTION_ITEM,
            target_ids=question_ids,
            relation_types=[
                REL_POINT_RELATES_STRONG,
                REL_POINT_RELATES_ADJACENT,
                REL_POINT_RELATES_FALLBACK,
                REL_POINT_RELATES_GENERIC,
            ],
        )
        deleted += _delete_edges_by_filter(
            db,
            source_type=ENTITY_QUESTION_ITEM,
            source_ids=question_ids,
            target_type=ENTITY_KNOWLEDGE_POINT,
            target_ids=list(point_ids),
            relation_types=[REL_QUESTION_TESTS_POINT],
        )

    if point_ids:
        deleted += _delete_edges_by_filter(
            db,
            source_type=ENTITY_KNOWLEDGE_POINT,
            source_ids=list(point_ids),
            target_type=ENTITY_KNOWLEDGE_POINT,
        )
        deleted += _delete_edges_by_filter(
            db,
            source_type=ENTITY_KNOWLEDGE_POINT,
            target_type=ENTITY_KNOWLEDGE_POINT,
            target_ids=list(point_ids),
        )

    inserted = _insert_edges(db, edges)
    db.commit()

    if neo4j_sink is not None and edges:
        try:
            neo4j_sink([edge.as_model_kwargs() for edge in edges])
        except Exception:
            logger.exception("Neo4j sink failed for package=%s", package_id)

    return {
        "status": "ok",
        "package_id": package_id,
        "deleted": deleted,
        "inserted": inserted,
        "edge_count": len(edges),
    }


def project_knowledge_point(
    db: Session,
    knowledge_point_id: int,
    *,
    neo4j_sink: Optional[Neo4jSink] = None,
    respect_flag: bool = True,
) -> Dict[str, Any]:
    """把单个知识点相关的关系全量投影（忽略跨包）。"""

    if respect_flag and not KNOWLEDGE_GRAPH_ENABLED:
        return {
            "status": "skipped",
            "reason": "KNOWLEDGE_GRAPH_ENABLED=false",
            "knowledge_point_id": knowledge_point_id,
            "inserted": 0,
            "deleted": 0,
        }

    point = (
        db.query(models.KnowledgePoint)
        .filter(models.KnowledgePoint.id == knowledge_point_id)
        .first()
    )
    if not point:
        raise ValueError(f"KnowledgePoint {knowledge_point_id} 不存在")

    edges: List[EdgeRow] = []

    # 本知识点下的块 / 原子
    block_edge_signatures: set = set()
    blocks = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.knowledge_point_id == knowledge_point_id)
        .all()
    )
    for row in blocks:
        _append_block_edge(
            edges,
            block_edge_signatures,
            source_point_id=knowledge_point_id,
            block=row,
            evidence={
                "package_id": row.package_id,
                "block_role": row.block_role,
                "is_primary": bool(getattr(row, "is_primary", False)),
                "grounding_source": "block_fk",
            },
        )

    provenance_rows = (
        db.query(models.KnowledgePointProvenance, models.KnowledgeBlock)
        .join(
            models.KnowledgeBlock,
            models.KnowledgeBlock.id == models.KnowledgePointProvenance.source_id,
        )
        .filter(
            models.KnowledgePointProvenance.knowledge_point_id == knowledge_point_id,
            models.KnowledgePointProvenance.source_kind == "knowledge_block",
        )
        .all()
    )
    for provenance, block in provenance_rows:
        _append_block_edge(
            edges,
            block_edge_signatures,
            source_point_id=knowledge_point_id,
            block=block,
            evidence={
                "package_id": block.package_id,
                "block_role": block.block_role,
                "is_primary": bool(getattr(provenance, "is_primary", False)),
                "grounding_source": "knowledge_point_provenance",
                "origin_step": provenance.origin_step,
                "provenance_id": provenance.id,
            },
        )

    atoms = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.knowledge_point_id == knowledge_point_id)
        .all()
    )
    for row in atoms:
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_KNOWLEDGE_POINT,
                source_entity_id=knowledge_point_id,
                target_entity_type=ENTITY_KNOWLEDGE_ATOM,
                target_entity_id=row.id,
                relation_type=REL_POINT_CONTAINS_ATOM,
                confidence=_to_float(row.confidence),
                evidence={
                    "package_id": row.package_id,
                    "atom_type": row.atom_type,
                    "review_status": row.review_status,
                },
            )
        )

    # 知识点 ↔ 知识点
    relations = (
        db.query(models.KnowledgePointRelation)
        .filter(
            or_(
                models.KnowledgePointRelation.source_knowledge_point_id == knowledge_point_id,
                models.KnowledgePointRelation.target_knowledge_point_id == knowledge_point_id,
            )
        )
        .all()
    )
    for row in relations:
        if not _is_projectable_kp_relation(row):
            continue
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_KNOWLEDGE_POINT,
                source_entity_id=row.source_knowledge_point_id,
                target_entity_type=ENTITY_KNOWLEDGE_POINT,
                target_entity_id=row.target_knowledge_point_id,
                relation_type=row.relation_type or REL_POINT_RELATES_GENERIC,
                weight_score=_to_float(row.strength_score),
                confidence=_to_float(row.confidence),
                evidence={
                    "relation_id": row.id,
                    "approved_status": row.approved_status,
                },
            )
        )

    # 知识点 ↔ 题目
    q_links = (
        db.query(models.KnowledgeQuestionLink)
        .filter(models.KnowledgeQuestionLink.knowledge_point_id == knowledge_point_id)
        .all()
    )
    for row in q_links:
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_KNOWLEDGE_POINT,
                source_entity_id=knowledge_point_id,
                target_entity_type=ENTITY_QUESTION_ITEM,
                target_entity_id=row.question_item_id,
                relation_type=_question_link_relation_type(row),
                weight_score=_to_float(row.relevance_score),
                confidence=_to_float(row.confidence),
                evidence={
                    "question_link_id": row.id,
                    "raw_relation_type": row.relation_type,
                    "approved_status": row.approved_status,
                },
            )
        )
        edges.append(
            EdgeRow(
                source_entity_type=ENTITY_QUESTION_ITEM,
                source_entity_id=row.question_item_id,
                target_entity_type=ENTITY_KNOWLEDGE_POINT,
                target_entity_id=knowledge_point_id,
                relation_type=REL_QUESTION_TESTS_POINT,
                weight_score=_to_float(row.relevance_score),
                confidence=_to_float(row.confidence),
                evidence={
                    "question_link_id": row.id,
                    "raw_relation_type": row.relation_type,
                    "approved_status": row.approved_status,
                },
            )
        )

    # 删除与该 point 相关的旧边（以 point 为端点的全部边；知识点↔块/原子/题目；以及 point↔point）
    deleted = 0
    deleted += _delete_edges_by_filter(
        db,
        source_type=ENTITY_KNOWLEDGE_POINT,
        source_ids=[knowledge_point_id],
    )
    deleted += _delete_edges_by_filter(
        db,
        target_type=ENTITY_KNOWLEDGE_POINT,
        target_ids=[knowledge_point_id],
    )

    inserted = _insert_edges(db, edges)
    db.commit()

    if neo4j_sink is not None and edges:
        try:
            neo4j_sink([edge.as_model_kwargs() for edge in edges])
        except Exception:
            logger.exception("Neo4j sink failed for knowledge_point=%s", knowledge_point_id)

    return {
        "status": "ok",
        "knowledge_point_id": knowledge_point_id,
        "deleted": deleted,
        "inserted": inserted,
        "edge_count": len(edges),
    }


def project_all(
    db: Session,
    *,
    neo4j_sink: Optional[Neo4jSink] = None,
    respect_flag: bool = True,
) -> Dict[str, Any]:
    """扫全库：按专题包逐个投影。适合首次启用或维护任务。"""

    if respect_flag and not KNOWLEDGE_GRAPH_ENABLED:
        return {
            "status": "skipped",
            "reason": "KNOWLEDGE_GRAPH_ENABLED=false",
            "package_count": 0,
            "inserted": 0,
            "deleted": 0,
        }

    rows = db.query(models.KnowledgePackage.id).order_by(models.KnowledgePackage.id.asc()).all()
    inserted_total = 0
    deleted_total = 0
    package_count = 0
    for (pid,) in rows:
        result = project_package(
            db, pid, neo4j_sink=neo4j_sink, respect_flag=False
        )
        inserted_total += int(result.get("inserted") or 0)
        deleted_total += int(result.get("deleted") or 0)
        package_count += 1

    return {
        "status": "ok",
        "package_count": package_count,
        "inserted": inserted_total,
        "deleted": deleted_total,
    }


# =============================================================================
# 查询辅助（给 admin API 用）
# =============================================================================


def summarize_edges(db: Session) -> Dict[str, Any]:
    """按 (source_entity_type, target_entity_type, relation_type) 聚合计数。"""

    from sqlalchemy import func

    rows = (
        db.query(
            models.EntityGraphEdge.source_entity_type,
            models.EntityGraphEdge.target_entity_type,
            models.EntityGraphEdge.relation_type,
            func.count(models.EntityGraphEdge.id),
        )
        .group_by(
            models.EntityGraphEdge.source_entity_type,
            models.EntityGraphEdge.target_entity_type,
            models.EntityGraphEdge.relation_type,
        )
        .all()
    )
    groups = [
        {
            "source_entity_type": src,
            "target_entity_type": tgt,
            "relation_type": rel,
            "count": int(cnt),
        }
        for src, tgt, rel, cnt in rows
    ]
    total = sum(item["count"] for item in groups)
    return {
        "total": total,
        "groups": sorted(
            groups,
            key=lambda item: (-item["count"], item["relation_type"], item["source_entity_type"]),
        ),
    }


def list_edges_for_knowledge_point(
    db: Session,
    knowledge_point_id: int,
    *,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    """返回某个知识点作为任一端点的边列表（便于前端画局部图）。"""

    records = (
        db.query(models.EntityGraphEdge)
        .filter(
            or_(
                and_(
                    models.EntityGraphEdge.source_entity_type == ENTITY_KNOWLEDGE_POINT,
                    models.EntityGraphEdge.source_entity_id == knowledge_point_id,
                ),
                and_(
                    models.EntityGraphEdge.target_entity_type == ENTITY_KNOWLEDGE_POINT,
                    models.EntityGraphEdge.target_entity_id == knowledge_point_id,
                ),
            )
        )
        .order_by(models.EntityGraphEdge.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "id": r.id,
            "source_entity_type": r.source_entity_type,
            "source_entity_id": r.source_entity_id,
            "target_entity_type": r.target_entity_type,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
            "weight_score": _to_float(r.weight_score),
            "confidence": _to_float(r.confidence),
            "source_origin": r.source_origin,
            "evidence": r.evidence_json,
        }
        for r in records
    ]


def list_edges_for_package(
    db: Session,
    package_id: int,
    *,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    point_ids = [
        pid
        for (pid,) in db.query(models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    ]
    block_ids = [
        bid
        for (bid,) in db.query(models.KnowledgeBlock.id)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
    ]
    question_ids = [
        qid
        for (qid,) in db.query(models.KnowledgePackageQuestion.question_item_id)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    ]

    predicates = [
        and_(
            models.EntityGraphEdge.source_entity_type == ENTITY_KNOWLEDGE_PACKAGE,
            models.EntityGraphEdge.source_entity_id == package_id,
        ),
    ]
    if point_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.source_entity_type == ENTITY_KNOWLEDGE_POINT,
                models.EntityGraphEdge.source_entity_id.in_(point_ids),
            )
        )
    if block_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.target_entity_type == ENTITY_KNOWLEDGE_BLOCK,
                models.EntityGraphEdge.target_entity_id.in_(block_ids),
            )
        )
    if question_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.target_entity_type == ENTITY_QUESTION_ITEM,
                models.EntityGraphEdge.target_entity_id.in_(question_ids),
            )
        )
    if question_ids and point_ids:
        predicates.append(
            and_(
                models.EntityGraphEdge.source_entity_type == ENTITY_QUESTION_ITEM,
                models.EntityGraphEdge.source_entity_id.in_(question_ids),
                models.EntityGraphEdge.target_entity_type == ENTITY_KNOWLEDGE_POINT,
                models.EntityGraphEdge.target_entity_id.in_(point_ids),
                models.EntityGraphEdge.relation_type == REL_QUESTION_TESTS_POINT,
            )
        )

    records = (
        db.query(models.EntityGraphEdge)
        .filter(or_(*predicates))
        .order_by(models.EntityGraphEdge.id.desc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [
        {
            "id": r.id,
            "source_entity_type": r.source_entity_type,
            "source_entity_id": r.source_entity_id,
            "target_entity_type": r.target_entity_type,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
            "weight_score": _to_float(r.weight_score),
            "confidence": _to_float(r.confidence),
            "source_origin": r.source_origin,
            "evidence": r.evidence_json,
        }
        for r in records
    ]


__all__ = [
    "ENTITY_KNOWLEDGE_POINT",
    "ENTITY_KNOWLEDGE_PACKAGE",
    "ENTITY_KNOWLEDGE_BLOCK",
    "ENTITY_KNOWLEDGE_ATOM",
    "ENTITY_KNOWLEDGE_DERIVATIVE",
    "ENTITY_QUESTION_ITEM",
    "REL_POINT_CONTAINS_BLOCK",
    "REL_POINT_CONTAINS_ATOM",
    "REL_PACKAGE_COVERS_POINT",
    "REL_PACKAGE_INCLUDES_QUESTION",
    "REL_POINT_DERIVES",
    "REL_POINT_RELATES_STRONG",
    "REL_POINT_RELATES_ADJACENT",
    "REL_POINT_RELATES_FALLBACK",
    "REL_POINT_RELATES_GENERIC",
    "REL_QUESTION_TESTS_POINT",
    "EdgeRow",
    "project_package",
    "project_knowledge_point",
    "project_all",
    "summarize_edges",
    "list_edges_for_knowledge_point",
    "list_edges_for_package",
]
