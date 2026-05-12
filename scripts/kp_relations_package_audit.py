"""Audit KP-KP relation quality for a specific knowledge package.

Read-only script. It inspects real PostgreSQL data and produces:
1. a human-readable console summary
2. a JSON report under scripts/_out

Scope:
- coverage points only: relation_type in {"core", "adjacent"}
- relations touching those points through either:
  - evidence blocks inside the package, or
  - no-evidence relations whose source/target touches the coverage set
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

def _ensure_utf8_stdio() -> None:
    try:
        base_stdout = getattr(sys, "__stdout__", None) or sys.stdout
        base_stderr = getattr(sys, "__stderr__", None) or sys.stderr
        if getattr(sys.stdout, "encoding", None) != "utf-8" and hasattr(base_stdout, "buffer"):
            sys.stdout = io.TextIOWrapper(base_stdout.buffer, encoding="utf-8")
        if getattr(sys.stderr, "encoding", None) != "utf-8" and hasattr(base_stderr, "buffer"):
            sys.stderr = io.TextIOWrapper(base_stderr.buffer, encoding="utf-8")
    except Exception:
        pass


_ensure_utf8_stdio()

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import and_, or_
from sqlalchemy.orm import aliased, sessionmaker

from shared import models
from shared.database import engine as shared_engine


load_dotenv(ROOT / ".env")

OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

COVERAGE_RELATION_TYPES = {"core", "adjacent"}
PROJECTABLE_KP_RELATION_STATUSES = {"approved", "explicit"}
PROJECTABLE_PENDING_LLM_MIN_CONFIDENCE = 0.90
FOCUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("求最值", re.compile(r"求最值")),
    ("求参数范围", re.compile(r"求参数范围")),
    ("恒成立", re.compile(r"恒成立")),
    ("充要条件", re.compile(r"充要条件")),
    ("定义", re.compile(r"定义")),
    ("证明", re.compile(r"证明")),
    ("解法", re.compile(r"解法")),
    ("应用", re.compile(r"实际应用|应用")),
    ("分类讨论", re.compile(r"分类讨论")),
    ("判别式", re.compile(r"判别式")),
    ("换元", re.compile(r"换元")),
    ("消元", re.compile(r"消元")),
    ("配凑", re.compile(r"配凑")),
    ("步骤", re.compile(r"步骤")),
)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE).lower()


def _name_fragments(name: str | None) -> list[str]:
    if not name:
        return []
    raw_parts = re.split(r"[，,。；;：:（）()\[\]【】、/\s]+", str(name))
    out: list[str] = []
    for part in raw_parts:
        normalized = _normalize_text(part)
        if len(normalized) >= 2:
            out.append(normalized)
        normalized_no_de = _normalize_text(str(part).replace("的", ""))
        if len(normalized_no_de) >= 2:
            out.append(normalized_no_de)
    if not out:
        normalized_name = _normalize_text(name)
        if len(normalized_name) >= 2:
            out.append(normalized_name)
    suffix_trimmed = re.sub(
        r"(定义|性质|关系|方法|解法|应用|步骤|证明|条件|问题|公式|定理|探究|总结)$",
        "",
        str(name or ""),
    ).strip()
    normalized_trimmed = _normalize_text(suffix_trimmed)
    if len(normalized_trimmed) >= 2:
        out.append(normalized_trimmed)
        trimmed_no_de = _normalize_text(suffix_trimmed.replace("的", ""))
        if len(trimmed_no_de) >= 2:
            out.append(trimmed_no_de)
    return list(dict.fromkeys(out))


def _text_mentions_name(text: str | None, name: str | None) -> bool:
    normalized_text = _normalize_text(text)
    relaxed_text = _normalize_text((text or "").replace("的", ""))
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
        normalized = _normalize_text(value)
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
    normalized_text = _normalize_text(text)
    relaxed_text = _normalize_text((text or "").replace("\u7684", ""))
    fragments = _name_fragments(name)
    strong_fragments = [fragment for fragment in fragments if len(fragment) >= 3]
    if not strong_fragments:
        normalized_name = _normalize_text(name)
        if len(normalized_name) >= 2:
            strong_fragments = [normalized_name]
    for fragment in strong_fragments:
        if fragment in normalized_text or fragment in relaxed_text:
            return True
    return False


def _shared_char_ratio(a: str | None, b: str | None) -> float:
    na = _normalize_text(a)
    nb = _normalize_text(b)
    if not na or not nb:
        return 0.0
    a_set = set(na)
    b_set = set(nb)
    denom = max(len(a_set | b_set), 1)
    return len(a_set & b_set) / denom


def _contains_family(a: str | None, b: str | None) -> bool:
    na = _normalize_text(a)
    nb = _normalize_text(b)
    return bool(na and nb and (na in nb or nb in na))


def _looks_more_specific(candidate: str | None, parent: str | None) -> bool:
    nc = _normalize_text(candidate)
    np = _normalize_text(parent)
    if not nc or not np:
        return False
    if np and np in nc and len(nc) > len(np):
        return True
    return len(nc) >= len(np) + 3 and _shared_char_ratio(candidate, parent) >= 0.45


def _focus_tokens(name: str | None) -> set[str]:
    text = name or ""
    return {label for label, pattern in FOCUS_PATTERNS if pattern.search(text)}


def _preview_text(
    text: str | None,
    limit: int = 160,
    *,
    source_name: str | None = None,
    target_name: str | None = None,
) -> str:
    raw = re.sub(r"\s+", " ", (text or "")).strip()
    if len(raw) <= limit:
        return raw

    normalized_raw = _normalize_text(raw)
    best_pos: int | None = None
    for name in (source_name, target_name):
        for fragment in _name_fragments(name):
            idx = normalized_raw.find(fragment)
            if idx >= 0 and (best_pos is None or idx < best_pos):
                best_pos = idx

    if best_pos is None:
        return raw[: limit - 3] + "..."

    start = max(best_pos - limit // 3, 0)
    end = min(start + limit, len(raw))
    snippet = raw[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(raw):
        snippet = snippet + "..."
    return snippet

def _passes_pending_llm_projection_guard(
    row: models.KnowledgePointRelation,
    *,
    source_name: str,
    target_name: str,
    evidence_preview: str,
    evidence_block_id: int | None,
    evidence_package_id: int | None,
    package_id: int,
) -> bool:
    status = (row.approved_status or "").strip().lower()
    relation_type = (row.relation_type or "").strip().lower()
    source_origin = (row.source_origin or "").strip().lower()
    if (
        status in PROJECTABLE_KP_RELATION_STATUSES
        and not (relation_type == "related" and source_origin == "cold_start" and evidence_block_id is None)
    ):
        return True
    if status != "pending":
        return False
    confidence = _to_float(row.confidence) or 0.0
    if source_origin != "llm" or confidence < PROJECTABLE_PENDING_LLM_MIN_CONFIDENCE:
        return False
    if evidence_block_id is None or evidence_package_id != package_id:
        return False

    mentions_source = _text_mentions_name(evidence_preview, source_name)
    mentions_target = _text_mentions_name(evidence_preview, target_name)
    if not (mentions_source or mentions_target):
        return False

    same_family = _contains_family(source_name, target_name) or _shared_char_ratio(source_name, target_name) >= 0.50
    same_family_variant = same_family and (
        _looks_more_specific(source_name, target_name) or _looks_more_specific(target_name, source_name)
    )
    if relation_type == "related" and same_family_variant:
        return False
    return True


@dataclass
class PointCoverageInfo:
    point_id: int
    name: str
    package_relation_type: str
    block_count: int
    provenance_block_count: int
    question_link_count: int


@dataclass
class RelationAuditRow:
    relation_id: int
    source_point_id: int
    source_name: str
    target_point_id: int
    target_name: str
    relation_type: str
    strength_score: float | None
    confidence: float | None
    approved_status: str | None
    source_origin: str | None
    evidence_block_id: int | None
    evidence_block_role: str | None
    evidence_block_preview: str
    evidence_block_package_id: int | None
    evidence_mentions_source: bool
    evidence_mentions_target: bool
    source_in_coverage: bool
    target_in_coverage: bool
    source_package_relation_type: str | None
    target_package_relation_type: str | None
    source_block_count: int
    target_block_count: int
    source_question_link_count: int
    target_question_link_count: int
    projectable: bool
    projected: bool
    anomaly_flags: list[str]
    anomaly_notes: list[str]


def _build_point_info(session, package_id: int) -> tuple[dict[int, PointCoverageInfo], set[int], set[int]]:
    package_points = (
        session.query(models.KnowledgePackagePoint, models.KnowledgePoint.canonical_name)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .filter(models.KnowledgePackagePoint.relation_type.in_(sorted(COVERAGE_RELATION_TYPES)))
        .all()
    )
    coverage_ids = {int(row.KnowledgePackagePoint.knowledge_point_id) for row in package_points}

    block_rows = (
        session.query(
            models.KnowledgeBlock.knowledge_point_id,
            models.KnowledgeBlock.id,
        )
        .filter(models.KnowledgeBlock.package_id == package_id)
        .filter(models.KnowledgeBlock.knowledge_point_id.isnot(None))
        .all()
    )
    block_counts: Counter[int] = Counter(int(kp_id) for kp_id, _ in block_rows if kp_id is not None)
    package_block_ids = {int(block_id) for _, block_id in block_rows}

    provenance_rows = (
        session.query(
            models.KnowledgePointProvenance.knowledge_point_id,
            models.KnowledgePointProvenance.source_id,
        )
        .filter(models.KnowledgePointProvenance.package_id == package_id)
        .filter(models.KnowledgePointProvenance.source_kind == "knowledge_block")
        .all()
    )
    provenance_block_counts: Counter[int] = Counter(
        int(kp_id) for kp_id, _ in provenance_rows if kp_id is not None
    )
    package_block_ids.update(int(source_id) for _, source_id in provenance_rows if source_id is not None)

    question_link_rows = (
        session.query(
            models.KnowledgeQuestionLink.knowledge_point_id,
            models.KnowledgeQuestionLink.id,
        )
        .join(
            models.KnowledgePackageQuestion,
            and_(
                models.KnowledgePackageQuestion.question_item_id == models.KnowledgeQuestionLink.question_item_id,
                models.KnowledgePackageQuestion.package_id == package_id,
            ),
        )
        .all()
    )
    question_link_counts: Counter[int] = Counter(int(kp_id) for kp_id, _ in question_link_rows if kp_id is not None)

    info: dict[int, PointCoverageInfo] = {}
    for package_point, canonical_name in package_points:
        point_id = int(package_point.knowledge_point_id)
        info[point_id] = PointCoverageInfo(
            point_id=point_id,
            name=str(canonical_name),
            package_relation_type=str(package_point.relation_type),
            block_count=int(block_counts.get(point_id, 0)),
            provenance_block_count=int(provenance_block_counts.get(point_id, 0)),
            question_link_count=int(question_link_counts.get(point_id, 0)),
        )
    return info, coverage_ids, package_block_ids


def _load_projected_signatures(session) -> set[tuple[int, int, str]]:
    rows = (
        session.query(
            models.EntityGraphEdge.source_entity_id,
            models.EntityGraphEdge.target_entity_id,
            models.EntityGraphEdge.relation_type,
        )
        .filter(models.EntityGraphEdge.source_entity_type == "knowledge_point")
        .filter(models.EntityGraphEdge.target_entity_type == "knowledge_point")
        .all()
    )
    return {(int(src), int(tgt), str(rel)) for src, tgt, rel in rows}


def _build_anomalies(
    *,
    relation_type: str,
    source_name: str,
    target_name: str,
    evidence_block_id: int | None,
    evidence_preview: str,
    evidence_package_id: int | None,
    package_id: int,
    source_in_coverage: bool,
    target_in_coverage: bool,
    projectable: bool,
    projected: bool,
    evidence_mentions_source: bool,
    evidence_mentions_target: bool,
) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    notes: list[str] = []

    if evidence_block_id is None:
        flags.append("no_evidence_block")
        notes.append("relation has no evidence_block_id")
    elif evidence_package_id not in (None, package_id):
        flags.append("evidence_block_outside_package")
        notes.append(f"evidence block belongs to package {evidence_package_id}, not {package_id}")

    if evidence_block_id is not None:
        if len(_normalize_text(evidence_preview)) < 12:
            flags.append("evidence_preview_too_short")
            notes.append("evidence block preview is too short for reliable review")
        if not (evidence_mentions_source or evidence_mentions_target):
            flags.append("evidence_no_endpoint_mention")
            notes.append("evidence preview does not mention either endpoint name fragments")

    if not (source_in_coverage and target_in_coverage):
        flags.append("touches_outside_coverage")
        notes.append("at least one endpoint is outside coverage points")

    overlap = _shared_char_ratio(source_name, target_name)
    focus_overlap = _focus_tokens(source_name) & _focus_tokens(target_name)
    same_family = _contains_family(source_name, target_name) or overlap >= 0.50 or bool(focus_overlap)

    if relation_type == "equivalent" and not same_family:
        flags.append("equivalent_low_name_overlap")
        notes.append("equivalent relation has weak lexical family overlap")

    if relation_type == "related" and same_family:
        flags.append("related_same_family")
        notes.append("related relation looks like same-family concept; may deserve specializes/equivalent review")

    if relation_type == "prerequisite" and _looks_more_specific(source_name, target_name):
        flags.append("prerequisite_direction_possible_reverse")
        notes.append("source looks more specific than target under current prerequisite direction convention")

    if relation_type == "specializes":
        if _looks_more_specific(source_name, target_name):
            flags.append("specializes_direction_possible_reverse")
            notes.append("source looks more specific than target under current specializes convention")
        elif not same_family:
            flags.append("specializes_weak_family")
            notes.append("specializes relation endpoints do not look like a close concept family")

    if projectable and not projected:
        flags.append("projectable_but_not_projected")
        notes.append("relation meets projection rule but corresponding entity_graph_edge is missing")

    return flags, notes


def _audit_package(session, package_id: int) -> dict[str, Any]:
    package = (
        session.query(models.KnowledgePackage)
        .filter(models.KnowledgePackage.id == package_id)
        .first()
    )
    if not package:
        raise ValueError(f"KnowledgePackage {package_id} not found")

    point_info, coverage_ids, package_block_ids = _build_point_info(session, package_id)
    projected_signatures = _load_projected_signatures(session)

    if not coverage_ids:
        return {
            "package_id": package_id,
            "package_title": package.package_title,
            "coverage_points": [],
            "coverage_point_count": 0,
            "relations": [],
            "summary": {
                "total_relations": 0,
                "projectable": 0,
                "projected": 0,
                "by_relation_type": {},
                "by_anomaly_flag": {},
            },
        }

    src = aliased(models.KnowledgePoint)
    tgt = aliased(models.KnowledgePoint)

    rel_rows = (
        session.query(
            models.KnowledgePointRelation,
            src.canonical_name.label("source_name"),
            tgt.canonical_name.label("target_name"),
            models.KnowledgeBlock.id.label("block_id"),
            models.KnowledgeBlock.package_id.label("block_package_id"),
            models.KnowledgeBlock.block_role.label("block_role"),
            models.KnowledgeBlock.normalized_text.label("block_text"),
            models.KnowledgeBlock.raw_text.label("block_raw_text"),
        )
        .join(src, src.id == models.KnowledgePointRelation.source_knowledge_point_id)
        .join(tgt, tgt.id == models.KnowledgePointRelation.target_knowledge_point_id)
        .outerjoin(models.KnowledgeBlock, models.KnowledgeBlock.id == models.KnowledgePointRelation.evidence_block_id)
        .filter(
            or_(
                models.KnowledgePointRelation.evidence_block_id.in_(list(package_block_ids)) if package_block_ids else False,
                and_(
                    models.KnowledgePointRelation.evidence_block_id.is_(None),
                    models.KnowledgePointRelation.source_knowledge_point_id.in_(list(coverage_ids)),
                    models.KnowledgePointRelation.target_knowledge_point_id.in_(list(coverage_ids)),
                ),
            )
        )
        .order_by(models.KnowledgePointRelation.id.asc())
        .all()
    )

    results: list[RelationAuditRow] = []
    type_counter: Counter[str] = Counter()
    anomaly_counter: Counter[str] = Counter()
    projectable_signatures: set[tuple[int, int, str]] = set()
    projected_signatures_seen: set[tuple[int, int, str]] = set()

    for rel, source_name, target_name, block_id, block_package_id, block_role, block_text, block_raw_text in rel_rows:
        source_id = int(rel.source_knowledge_point_id)
        target_id = int(rel.target_knowledge_point_id)
        source_in_coverage = source_id in coverage_ids
        target_in_coverage = target_id in coverage_ids
        evidence_preview = _preview_text(block_text or block_raw_text, source_name=str(source_name), target_name=str(target_name))

        source_fragments = _name_fragments(str(source_name))
        target_fragments = _name_fragments(str(target_name))
        evidence_mentions_source = _text_mentions_name(evidence_preview, str(source_name))
        evidence_mentions_target = _text_mentions_name(evidence_preview, str(target_name))

        projectable = _passes_pending_llm_projection_guard(
            rel,
            source_name=str(source_name),
            target_name=str(target_name),
            evidence_preview=evidence_preview,
            evidence_block_id=int(block_id) if block_id is not None else None,
            evidence_package_id=int(block_package_id) if block_package_id is not None else None,
            package_id=package_id,
        )
        projected = (source_id, target_id, str(rel.relation_type)) in projected_signatures
        signature = (source_id, target_id, str(rel.relation_type))
        if projectable:
            projectable_signatures.add(signature)
        if projected:
            projected_signatures_seen.add(signature)

        anomaly_flags, anomaly_notes = _build_anomalies(
            relation_type=str(rel.relation_type),
            source_name=str(source_name),
            target_name=str(target_name),
            evidence_block_id=int(block_id) if block_id is not None else None,
            evidence_preview=evidence_preview,
            evidence_package_id=int(block_package_id) if block_package_id is not None else None,
            package_id=package_id,
            source_in_coverage=source_in_coverage,
            target_in_coverage=target_in_coverage,
            projectable=projectable,
            projected=projected,
            evidence_mentions_source=evidence_mentions_source,
            evidence_mentions_target=evidence_mentions_target,
        )

        for flag in anomaly_flags:
            anomaly_counter[flag] += 1
        type_counter[str(rel.relation_type)] += 1

        source_cov = point_info.get(source_id)
        target_cov = point_info.get(target_id)
        results.append(
            RelationAuditRow(
                relation_id=int(rel.id),
                source_point_id=source_id,
                source_name=str(source_name),
                target_point_id=target_id,
                target_name=str(target_name),
                relation_type=str(rel.relation_type),
                strength_score=_to_float(rel.strength_score),
                confidence=_to_float(rel.confidence),
                approved_status=rel.approved_status,
                source_origin=rel.source_origin,
                evidence_block_id=int(block_id) if block_id is not None else None,
                evidence_block_role=str(block_role) if block_role is not None else None,
                evidence_block_preview=evidence_preview,
                evidence_block_package_id=int(block_package_id) if block_package_id is not None else None,
                evidence_mentions_source=evidence_mentions_source,
                evidence_mentions_target=evidence_mentions_target,
                source_in_coverage=source_in_coverage,
                target_in_coverage=target_in_coverage,
                source_package_relation_type=source_cov.package_relation_type if source_cov else None,
                target_package_relation_type=target_cov.package_relation_type if target_cov else None,
                source_block_count=source_cov.block_count if source_cov else 0,
                target_block_count=target_cov.block_count if target_cov else 0,
                source_question_link_count=source_cov.question_link_count if source_cov else 0,
                target_question_link_count=target_cov.question_link_count if target_cov else 0,
                projectable=projectable,
                projected=projected,
                anomaly_flags=anomaly_flags,
                anomaly_notes=anomaly_notes,
            )
        )

    coverage_points = [asdict(row) for _, row in sorted(point_info.items(), key=lambda item: item[1].name)]

    return {
        "package_id": package_id,
        "package_title": package.package_title,
        "coverage_points": coverage_points,
        "coverage_point_count": len(coverage_points),
        "relations": [asdict(row) for row in results],
        "summary": {
            "total_relations": len(results),
            "projectable": len(projectable_signatures),
            "projected": len(projected_signatures_seen),
            "by_relation_type": dict(sorted(type_counter.items())),
            "by_anomaly_flag": dict(sorted(anomaly_counter.items())),
        },
    }


def _print_report(report: dict[str, Any]) -> None:
    print(f"\nPackage {report['package_id']} - {report['package_title']}")
    print(f"Coverage points: {report['coverage_point_count']}")
    print(f"Relations in audit scope: {report['summary']['total_relations']}")
    print(
        "Projectable / projected: "
        f"{report['summary']['projectable']} / {report['summary']['projected']}"
    )

    print("\nBy relation type:")
    for rel_type, count in report["summary"]["by_relation_type"].items():
        print(f"  {rel_type:<14} {count}")

    print("\nTop anomaly flags:")
    anomaly_items = list(report["summary"]["by_anomaly_flag"].items())
    if not anomaly_items:
        print("  (none)")
    else:
        for flag, count in sorted(anomaly_items, key=lambda item: (-item[1], item[0]))[:12]:
            print(f"  {flag:<34} {count}")

    suspicious = [
        row for row in report["relations"] if row["anomaly_flags"]
    ]
    suspicious.sort(key=lambda row: (-len(row["anomaly_flags"]), row["relation_id"]))
    print("\nSample suspicious relations:")
    if not suspicious:
        print("  (none)")
        return
    for row in suspicious[:12]:
        print(
            f"  #{row['relation_id']} {row['source_name']} -[{row['relation_type']}]-> {row['target_name']}"
        )
        print(
            f"    flags={', '.join(row['anomaly_flags'])} | "
            f"status={row['approved_status']} origin={row['source_origin']} "
            f"conf={row['confidence']} projected={row['projected']}"
        )
        if row["evidence_block_id"] is not None:
            print(
                f"    block={row['evidence_block_id']} role={row['evidence_block_role']} "
                f"pkg={row['evidence_block_package_id']} preview={row['evidence_block_preview']}"
            )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, action="append", required=True, help="KnowledgePackage id")
    args = ap.parse_args()

    session_factory = sessionmaker(bind=shared_engine)
    session = session_factory()
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        for package_id in args.package_id:
            report = _audit_package(session, package_id)
            out_path = OUT_DIR / f"kp_relations_package_audit_pkg{package_id}_{ts}.json"
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            _print_report(report)
            print(f"\nJSON report: {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
