from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from shared import models


_PLACEHOLDER_POINT_NAMES = {
    "llm_pending",
    "fallback",
    "placeholder",
    "unclassified",
    "\u672a\u5f52\u7c7b\u77e5\u8bc6\u70b9",
    "\u4e13\u9898\u6b63\u6587",
}


_STOP_TERMS = {
    "第一节",
    "第二节",
    "第三节",
    "第四节",
    "第五节",
    "第六节",
    "第七节",
    "第八节",
    "第九节",
    "第十节",
    "教材拓展",
    "专题正文",
}
_GENERIC_ANCHOR_TERMS = {
    "函数",
    "方程",
    "不等式",
    "应用",
    "定义",
    "解法",
    "证明",
    "条件",
}
_DEPENDENCY_EXTERNAL_RE = re.compile(r"集合|分式|绝对值|逻辑|函数与方程")
_DEPENDENCY_TRANSFER_RE = re.compile(r"结合|建模|分类讨论|分离参数|主参换位|给定区间|给定参数范围")
_DEPENDENCY_UMBRELLA_RE = re.compile(r"^利用.+求最值$|^利用.+求参数(?:的值或)?范围$")
_ADJACENT_THEORY_RE = re.compile(r"定义|性质|证明|条件|判别式|图象|解集|平均数|等号|充要|关系|步骤|注意事项|恒成立|重要不等式")
_ADJACENT_LOCAL_METHOD_RE = re.compile(r"配凑法|常数代换法|换元法|消元法")
_ANCHOR_SUFFIX_RE = re.compile(r"(定义|解法|求解|充要条件|注意事项|四个步骤|步骤|证明|实际应用|条件)$")


@dataclass
class PackagePointPurityFeature:
    package_point_id: int
    knowledge_point_id: int
    name: str
    current_relation_type: str
    current_status: str
    direct_block_count: int
    provenance_block_count: int
    atom_count: int
    atom_backed_block_count: int
    question_count: int
    relation_signal_count: int
    current_anchor_hits: int
    current_anchor_ratio: float
    external_anchor_hits: int


def _normalize_text(text: Optional[str]) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


_PLACEHOLDER_POINT_NAME_KEYS = {_normalize_text(value) for value in _PLACEHOLDER_POINT_NAMES}


def _is_placeholder_point_name(text: Optional[str]) -> bool:
    return _normalize_text(text) in _PLACEHOLDER_POINT_NAME_KEYS


def _tokenize_anchor_terms(text: Optional[str]) -> List[str]:
    raw = str(text or "")
    raw = re.sub(r"第[一二三四五六七八九十百零\d]+[章节讲专题]", " ", raw)
    raw = re.sub(r"[、和及其与]", " ", raw)
    raw = re.sub(r"[()（）\[\]【】,，。；;:：/\\\-—_]+", " ", raw)
    parts = [part.strip() for part in raw.split() if part.strip()]
    terms: List[str] = []
    for part in parts:
        if part in _STOP_TERMS:
            continue
        if len(part) < 2:
            continue
        if part in _GENERIC_ANCHOR_TERMS:
            continue
        terms.append(part)
        if "的" in part:
            for sub in part.split("的"):
                sub = sub.strip()
                if len(sub) >= 2 and sub not in _STOP_TERMS and sub not in _GENERIC_ANCHOR_TERMS:
                    terms.append(sub)
        trimmed = _ANCHOR_SUFFIX_RE.sub("", part).strip()
        if len(trimmed) >= 4 and trimmed not in _STOP_TERMS and trimmed not in _GENERIC_ANCHOR_TERMS:
            terms.append(trimmed)
    deduped: List[str] = []
    seen = set()
    for term in sorted(terms, key=lambda item: (-len(item), item)):
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _anchor_hits(name: str, anchor_terms: Iterable[str]) -> tuple[int, float]:
    normalized_name = _normalize_text(name)
    if not normalized_name:
        return 0, 0.0
    matched_lengths: List[int] = []
    for term in anchor_terms:
        norm_term = _normalize_text(term)
        if len(norm_term) < 2:
            continue
        if norm_term in normalized_name:
            matched_lengths.append(len(norm_term))
    if not matched_lengths:
        return 0, 0.0
    return len(matched_lengths), max(matched_lengths) / max(len(normalized_name), 1)


def _collect_package_rows(db: Session, package_id: int):
    return (
        db.query(models.KnowledgePackagePoint, models.KnowledgePoint)
        .join(models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .order_by(models.KnowledgePackagePoint.order_in_package.asc(), models.KnowledgePackagePoint.id.asc())
        .all()
    )


def build_package_purity_features(db: Session, package_id: int) -> tuple[models.KnowledgePackage, List[PackagePointPurityFeature], List[str]]:
    package = (
        db.query(models.KnowledgePackage)
        .filter(models.KnowledgePackage.id == package_id)
        .first()
    )
    if not package:
        raise ValueError(f"KnowledgePackage {package_id} not found")

    package_rows = _collect_package_rows(db, package_id)
    point_ids = [int(link.knowledge_point_id) for link, _ in package_rows if link.knowledge_point_id is not None]
    if not point_ids:
        return package, [], _tokenize_anchor_terms(package.package_title)
    placeholder_point_ids = {
        int(link.knowledge_point_id)
        for link, point in package_rows
        if link.knowledge_point_id is not None and _is_placeholder_point_name(point.canonical_name)
    }

    direct_block_count: Dict[int, int] = Counter(
        int(pid)
        for (pid,) in db.query(models.KnowledgeBlock.knowledge_point_id)
        .filter(
            models.KnowledgeBlock.package_id == package_id,
            models.KnowledgeBlock.knowledge_point_id.in_(point_ids),
        )
        .all()
        if pid is not None
    )

    provenance_map: Dict[int, set[int]] = defaultdict(set)
    for pid, source_id in (
        db.query(models.KnowledgePointProvenance.knowledge_point_id, models.KnowledgePointProvenance.source_id)
        .filter(
            models.KnowledgePointProvenance.package_id == package_id,
            models.KnowledgePointProvenance.source_kind == "knowledge_block",
            models.KnowledgePointProvenance.knowledge_point_id.in_(point_ids),
        )
        .all()
    ):
        if pid is not None and source_id is not None:
            provenance_map[int(pid)].add(int(source_id))

    atom_count: Dict[int, int] = Counter()
    atom_backed_block_map: Dict[int, set[int]] = defaultdict(set)
    for pid, evidence_block_id in (
        db.query(models.KnowledgeAtom.knowledge_point_id, models.KnowledgeAtom.evidence_block_id)
        .filter(
            models.KnowledgeAtom.package_id == package_id,
            models.KnowledgeAtom.knowledge_point_id.in_(point_ids),
        )
        .all()
    ):
        if pid is None:
            continue
        pid_i = int(pid)
        atom_count[pid_i] += 1
        if evidence_block_id is not None:
            atom_backed_block_map[pid_i].add(int(evidence_block_id))

    question_count: Dict[int, int] = Counter(
        int(pid)
        for (pid,) in db.query(models.KnowledgeQuestionLink.knowledge_point_id)
        .join(
            models.KnowledgePackageQuestion,
            models.KnowledgePackageQuestion.question_item_id == models.KnowledgeQuestionLink.question_item_id,
        )
        .filter(
            models.KnowledgePackageQuestion.package_id == package_id,
            models.KnowledgeQuestionLink.knowledge_point_id.in_(point_ids),
        )
        .all()
        if pid is not None
    )

    core_point_ids = {
        int(link.knowledge_point_id)
        for link, _ in package_rows
        if int(link.knowledge_point_id) not in placeholder_point_ids
        and (
            direct_block_count.get(int(link.knowledge_point_id), 0) > 0
            or (atom_count.get(int(link.knowledge_point_id), 0) > 0)
            or (len(atom_backed_block_map.get(int(link.knowledge_point_id), set())) > 0)
        )
    }

    relation_signal_count: Dict[int, int] = Counter()
    if core_point_ids:
        relation_rows = (
            db.query(
                models.KnowledgePointRelation.source_knowledge_point_id,
                models.KnowledgePointRelation.target_knowledge_point_id,
                models.KnowledgePointRelation.confidence,
            )
            .filter(
                models.KnowledgePointRelation.source_knowledge_point_id.in_(point_ids),
                models.KnowledgePointRelation.target_knowledge_point_id.in_(point_ids),
            )
            .all()
        )
        for source_id, target_id, confidence in relation_rows:
            if source_id is None or target_id is None:
                continue
            if float(confidence or 0) < 0.85:
                continue
            source_i = int(source_id)
            target_i = int(target_id)
            if source_i in core_point_ids and target_i not in core_point_ids:
                relation_signal_count[target_i] += 1
            if target_i in core_point_ids and source_i not in core_point_ids:
                relation_signal_count[source_i] += 1

    current_anchor_terms: List[str] = []
    current_anchor_terms.extend(_tokenize_anchor_terms(package.package_title))
    for _, point in package_rows:
        if point.id in core_point_ids:
            current_anchor_terms.extend(_tokenize_anchor_terms(point.canonical_name))
    current_anchor_terms = list(dict.fromkeys(current_anchor_terms))

    other_package_terms: List[str] = []
    for other_id, other_title in (
        db.query(models.KnowledgePackage.id, models.KnowledgePackage.package_title)
        .filter(models.KnowledgePackage.id != package_id)
        .all()
    ):
        if other_title:
            other_package_terms.extend(_tokenize_anchor_terms(other_title))
    other_package_terms = list(dict.fromkeys(other_package_terms))

    features: List[PackagePointPurityFeature] = []
    for link, point in package_rows:
        point_id = int(link.knowledge_point_id)
        current_hits, current_ratio = _anchor_hits(point.canonical_name, current_anchor_terms)
        external_hits, _ = _anchor_hits(point.canonical_name, other_package_terms)
        features.append(
            PackagePointPurityFeature(
                package_point_id=int(link.id),
                knowledge_point_id=point_id,
                name=point.canonical_name or "",
                current_relation_type=(link.relation_type or "").strip().lower(),
                current_status=(link.approved_status or "").strip().lower(),
                direct_block_count=direct_block_count.get(point_id, 0),
                provenance_block_count=len(provenance_map.get(point_id, set())),
                atom_count=atom_count.get(point_id, 0),
                atom_backed_block_count=len(atom_backed_block_map.get(point_id, set())),
                question_count=question_count.get(point_id, 0),
                relation_signal_count=relation_signal_count.get(point_id, 0),
                current_anchor_hits=current_hits,
                current_anchor_ratio=current_ratio,
                external_anchor_hits=external_hits,
            )
        )
    return package, features, current_anchor_terms


def classify_package_point(feature: PackagePointPurityFeature) -> tuple[str, str]:
    name = feature.name

    if _is_placeholder_point_name(name):
        return "placeholder", "placeholder_point_name"

    if feature.direct_block_count > 0 or feature.atom_count > 0 or feature.atom_backed_block_count > 0:
        return "core", "direct_material_support"

    if feature.provenance_block_count <= 0:
        return "dependency", "no_package_grounding"

    if _DEPENDENCY_EXTERNAL_RE.search(name) and feature.current_anchor_ratio < 0.55:
        return "dependency", "external_topic_keyword"

    if _DEPENDENCY_TRANSFER_RE.search(name) and feature.current_anchor_ratio < 0.8:
        return "dependency", "transfer_or_cross_topic_method"

    if _DEPENDENCY_UMBRELLA_RE.search(name):
        return "dependency", "umbrella_teaching_goal"

    if feature.external_anchor_hits > feature.current_anchor_hits and feature.current_anchor_ratio < 0.55:
        return "dependency", "matches_other_package_better"

    if feature.relation_signal_count > 0:
        return "adjacent", "linked_to_core_point"

    if feature.current_anchor_ratio >= 0.55:
        return "adjacent", "strong_current_topic_anchor"

    if feature.current_anchor_hits > 0 and feature.question_count > 0:
        return "adjacent", "anchored_in_current_topic_questions"

    if _ADJACENT_THEORY_RE.search(name):
        return "adjacent", "theory_side_point"

    if _ADJACENT_LOCAL_METHOD_RE.search(name) and feature.question_count >= 0:
        return "adjacent", "local_method_variant"

    if (
        feature.question_count >= 3
        and feature.external_anchor_hits == 0
        and not _DEPENDENCY_EXTERNAL_RE.search(name)
        and not _DEPENDENCY_TRANSFER_RE.search(name)
        and not _DEPENDENCY_UMBRELLA_RE.search(name)
    ):
        return "adjacent", "repeatedly_used_inside_package"

    return "dependency", "weak_topic_purity"


def reclassify_package_point_purity(
    db: Session,
    package_id: int,
    *,
    apply: bool = False,
) -> dict:
    package, features, anchor_terms = build_package_purity_features(db, package_id)
    if not features:
        return {
            "status": "ok",
            "package_id": package_id,
            "package_title": package.package_title,
            "core": 0,
            "adjacent": 0,
            "dependency": 0,
            "placeholder": 0,
            "anchor_terms": anchor_terms,
            "changed": 0,
        }

    point_link_map = {
        int(link.id): link
        for link, _ in _collect_package_rows(db, package_id)
    }

    counts = Counter()
    reason_counts = Counter()
    changed = 0
    rows = []
    for feature in features:
        label, reason = classify_package_point(feature)
        counts[label] += 1
        reason_counts[reason] += 1
        if apply:
            link = point_link_map[feature.package_point_id]
            if (link.relation_type or "").strip().lower() != label:
                changed += 1
            link.relation_type = label
            if label == "placeholder":
                link.approved_status = "placeholder"
            elif feature.provenance_block_count > 0 or feature.direct_block_count > 0 or feature.atom_count > 0:
                link.approved_status = "grounded"
            else:
                link.approved_status = "candidate"
        else:
            if feature.current_relation_type != label:
                changed += 1
        rows.append(
            {
                "knowledge_point_id": feature.knowledge_point_id,
                "name": feature.name,
                "before": feature.current_relation_type,
                "after": label,
                "reason": reason,
                "direct_block_count": feature.direct_block_count,
                "provenance_block_count": feature.provenance_block_count,
                "atom_count": feature.atom_count,
                "question_count": feature.question_count,
                "relation_signal_count": feature.relation_signal_count,
                "current_anchor_hits": feature.current_anchor_hits,
                "current_anchor_ratio": round(feature.current_anchor_ratio, 4),
                "external_anchor_hits": feature.external_anchor_hits,
            }
        )

    return {
        "status": "ok",
        "package_id": package_id,
        "package_title": package.package_title,
        "core": counts["core"],
        "adjacent": counts["adjacent"],
        "dependency": counts["dependency"],
        "placeholder": counts["placeholder"],
        "changed": changed,
        "anchor_terms": anchor_terms[:12],
        "reason_counts": dict(reason_counts),
        "rows": rows,
    }
