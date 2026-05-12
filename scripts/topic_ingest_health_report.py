"""Comprehensive topic ingestion health report with 5-layer scoring.

Produces a weighted health score (0-100) across five quality dimensions:
  L1: Question Quality        (25%)
  L2: Knowledge Point Quality (20%)
  L3: Relation & Graph Quality(25%)
  L4: Retrieval & Vector      (20%)
  L5: Data Integrity          (10%)

Read-only. Outputs both terminal report and JSON.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


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
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, sessionmaker

load_dotenv(ROOT / ".env")

from shared import models
from shared.database import engine

OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Enums and data types
# ---------------------------------------------------------------------------


class ScoreGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    CRITICAL = "CRITICAL"


class Severity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    SUGGESTION = "suggestion"


@dataclass
class CheckItem:
    code: str
    label: str
    score: float
    grade: ScoreGrade
    severity: Severity
    detail: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass
class LayerResult:
    layer_code: str
    layer_name: str
    weight: float
    score: float
    grade: ScoreGrade
    checks: list[CheckItem] = field(default_factory=list)


@dataclass
class HealthReport:
    package_id: int
    package_title: str
    parse_status: str | None
    review_status: str | None
    generated_at: str
    overall_score: float
    overall_grade: ScoreGrade
    layers: list[LayerResult] = field(default_factory=list)
    critical_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ReportThresholds:
    min_points: int = 3
    min_questions: int = 5
    min_question_link_coverage: float = 0.75
    min_retrieval_docs: int = 1
    max_pending_ratio: float = 0.20
    require_full_embeddings: bool = True
    min_grounded_llm_relations: int = 1
    min_neo4j_relationships: int = 1


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _score_to_grade(score: float) -> ScoreGrade:
    if score >= 90:
        return ScoreGrade.EXCELLENT
    if score >= 75:
        return ScoreGrade.GOOD
    if score >= 60:
        return ScoreGrade.FAIR
    if score >= 40:
        return ScoreGrade.POOR
    return ScoreGrade.CRITICAL


def _ratio(part: float, whole: float) -> float:
    return float(part) / float(whole) if whole else 0.0


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _empty_check(code: str, label: str, detail: dict | None = None) -> CheckItem:
    return CheckItem(
        code=code,
        label=label,
        score=100.0,
        grade=ScoreGrade.EXCELLENT,
        severity=Severity.SUGGESTION,
        detail=detail or {},
        message="No data to check",
    )


def _compute_layer_score(checks: list[CheckItem], weights: dict[str, float] | None = None) -> float:
    if not checks:
        return 100.0
    if weights is None:
        return sum(c.score for c in checks) / len(checks)
    total_weight = sum(weights.get(c.code, 1.0) for c in checks)
    if total_weight == 0:
        return 100.0
    return sum(c.score * weights.get(c.code, 1.0) for c in checks) / total_weight


def _compute_overall_score(layers: list[LayerResult]) -> float:
    weights = {"L1": 0.25, "L2": 0.20, "L3": 0.25, "L4": 0.20, "L5": 0.10}
    total = sum(weights.get(l.layer_code, 0.0) for l in layers)
    if total == 0:
        return 100.0
    return sum(l.score * weights.get(l.layer_code, 0.0) for l in layers) / total


def _stable_hash(payload: object) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _package_point_ids(session: Session, package_id: int) -> list[int]:
    rows = (
        session.query(models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .all()
    )
    return sorted({int(pid) for (pid,) in rows if pid is not None})


def _package_question_ids(session: Session, package_id: int) -> list[int]:
    rows = (
        session.query(models.KnowledgePackageQuestion.question_item_id)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .all()
    )
    return sorted({int(qid) for (qid,) in rows if qid is not None})


def _package_block_ids(session: Session, package_id: int) -> list[int]:
    rows = (
        session.query(models.KnowledgeBlock.id)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .all()
    )
    return sorted({int(bid) for (bid,) in rows if bid is not None})


def _knowledge_docs_for_package(session: Session, package_id: int) -> list[models.RetrievalDocument]:
    knowledge_types = {
        "knowledge_package", "knowledge_point", "knowledge_package_point",
        "knowledge_block", "knowledge_atom", "knowledge_question_bridge",
        "knowledge_derivative",
    }
    docs = (
        session.query(models.RetrievalDocument)
        .filter(models.RetrievalDocument.is_active.is_(True))
        .filter(
            or_(
                models.RetrievalDocument.entity_type.in_(sorted(knowledge_types)),
                models.RetrievalDocument.metadata_json["entity_type"].as_string().in_(sorted(knowledge_types)),
            )
        )
        .all()
    )

    def _doc_package_id(doc: models.RetrievalDocument) -> int | None:
        meta = dict(doc.metadata_json or {})
        pid = _safe_int(meta.get("package_id"))
        if pid is not None:
            return pid
        if doc.entity_type == "knowledge_package":
            return int(doc.entity_id)
        return None

    return [doc for doc in docs if _doc_package_id(doc) == package_id]


def _resolve_package_ids(
    session: Session,
    package_ids: list[int] | None,
    source_document_ids: list[int] | None,
    title_keywords: list[str] | None,
) -> list[int]:
    resolved: list[int] = []

    for pid in package_ids or []:
        exists = (
            session.query(models.KnowledgePackage.id)
            .filter(models.KnowledgePackage.id == pid)
            .scalar()
        )
        if not exists:
            raise SystemExit(f"KnowledgePackage {pid} not found")
        resolved.append(int(pid))

    for sdid in source_document_ids or []:
        rows = (
            session.query(models.KnowledgePackage.id)
            .filter(models.KnowledgePackage.source_document_id == sdid)
            .order_by(models.KnowledgePackage.id.desc())
            .all()
        )
        if not rows:
            raise SystemExit(f"No KnowledgePackage found for source_document_id={sdid}")
        resolved.append(int(rows[0][0]))

    for keyword in title_keywords or []:
        rows = (
            session.query(models.KnowledgePackage.id, models.KnowledgePackage.package_title)
            .filter(models.KnowledgePackage.package_title.ilike(f"%{keyword}%"))
            .order_by(models.KnowledgePackage.id.desc())
            .all()
        )
        if not rows:
            raise SystemExit(f"No KnowledgePackage title matched keyword={keyword!r}")
        if len(rows) > 1:
            pairs = ", ".join(f"{pid}:{title}" for pid, title in rows[:8])
            raise SystemExit(
                f"Keyword {keyword!r} matched multiple packages; refine it or pass --package-id explicitly: {pairs}"
            )
        resolved.append(int(rows[0][0]))

    deduped: list[int] = []
    seen: set[int] = set()
    for pid in resolved:
        if pid not in seen:
            deduped.append(pid)
            seen.add(pid)
    if not deduped:
        raise SystemExit("Provide at least one of --package-id, --source-document-id, or --package-title-like")
    return deduped


# ---------------------------------------------------------------------------
# L1: Question Quality (25%)
# ---------------------------------------------------------------------------

_L1_WEIGHTS = {
    "L1.1": 0.12, "L1.2": 0.12, "L1.3": 0.06,
    "L1.4": 0.10, "L1.5": 0.10, "L1.6": 0.06, "L1.7": 0.06,
    "L1.8": 0.15, "L1.9": 0.08, "L1.10": 0.10, "L1.11": 0.05,
}


def _check_l1_1_extraction_completeness(
    session: Session, question_ids: list[int], thresholds: ReportThresholds,
) -> CheckItem:
    count = len(question_ids)
    score = min(100.0, (count / max(thresholds.min_questions, 1)) * 100.0)
    severity = Severity.CRITICAL if count < thresholds.min_questions else Severity.SUGGESTION
    return CheckItem(
        code="L1.1", label="Extraction completeness", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"count": count, "threshold": thresholds.min_questions},
        message=f"{count} questions (min: {thresholds.min_questions})",
    )


def _check_l1_2_structure_integrity(
    session: Session, question_ids: list[int],
) -> CheckItem:
    if not question_ids:
        return _empty_check("L1.2", "Structure integrity")

    questions = session.query(models.QuestionItem).filter(
        models.QuestionItem.id.in_(question_ids)
    ).all()

    total = len(questions)
    empty_stem = sum(1 for q in questions if not (q.stem_plain_text or "").strip())
    empty_answer = sum(1 for q in questions if not (q.answer_text or "").strip())
    empty_solution = sum(1 for q in questions if not (q.solution_summary or "").strip())

    stem_rate = (total - empty_stem) / total
    answer_rate = (total - empty_answer) / total
    solution_rate = (total - empty_solution) / total

    score = stem_rate * 100 * 0.40 + answer_rate * 100 * 0.35 + solution_rate * 100 * 0.25

    severity = Severity.CRITICAL if empty_stem > 0 or empty_answer > 0 else (
        Severity.WARNING if empty_solution > 0 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L1.2", label="Structure integrity", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total": total, "empty_stem": empty_stem, "empty_answer": empty_answer,
            "empty_solution": empty_solution,
            "stem_rate": round(stem_rate, 4), "answer_rate": round(answer_rate, 4),
            "solution_rate": round(solution_rate, 4),
        },
        message=f"stem={stem_rate:.0%} answer={answer_rate:.0%} solution={solution_rate:.0%}",
    )


def _check_l1_3_type_distribution(
    session: Session, question_ids: list[int],
) -> CheckItem:
    if not question_ids:
        return _empty_check("L1.3", "Type distribution")

    type_rows = session.query(
        models.QuestionItem.question_type,
        func.count(models.QuestionItem.id),
    ).filter(
        models.QuestionItem.id.in_(question_ids),
    ).group_by(models.QuestionItem.question_type).all()

    type_counts = {str(t or "unknown"): int(c) for t, c in type_rows}
    total = sum(type_counts.values())
    if total == 0:
        return _empty_check("L1.3", "Type distribution")

    diversity = len(type_counts)
    max_ratio = max(type_counts.values()) / total if type_counts else 1.0

    score = min(diversity / 3.0, 1.0) * 50.0 + (1.0 - max_ratio) * 50.0
    severity = Severity.WARNING if diversity < 2 else Severity.SUGGESTION
    return CheckItem(
        code="L1.3", label="Type distribution", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"type_counts": type_counts, "diversity": diversity, "max_ratio": round(max_ratio, 4)},
        message=f"{diversity} types: {', '.join(f'{k}={v}' for k, v in sorted(type_counts.items()))}",
    )


def _check_l1_4_kp_link_coverage(
    session: Session, question_ids: list[int],
) -> CheckItem:
    if not question_ids:
        return _empty_check("L1.4", "KP-link coverage")

    linked_ids = {
        int(row.question_item_id)
        for row in session.query(models.KnowledgeQuestionLink.question_item_id)
        .filter(models.KnowledgeQuestionLink.question_item_id.in_(question_ids))
        .all()
    }
    coverage = _ratio(len(linked_ids & set(question_ids)), len(question_ids))
    score = coverage * 100.0
    unlinked = len(set(question_ids) - linked_ids)
    severity = Severity.CRITICAL if coverage < 0.50 else (
        Severity.WARNING if coverage < 0.75 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L1.4", label="KP-link coverage", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"linked": len(linked_ids & set(question_ids)), "total": len(question_ids),
                "coverage": round(coverage, 4), "unlinked": unlinked},
        message=f"{coverage:.1%} questions linked to KPs ({unlinked} unlinked)",
    )


def _check_l1_5_link_quality(
    session: Session, question_ids: list[int],
) -> CheckItem:
    if not question_ids:
        return _empty_check("L1.5", "Link quality")

    links = session.query(models.KnowledgeQuestionLink).filter(
        models.KnowledgeQuestionLink.question_item_id.in_(question_ids),
    ).all()

    type_map = Counter(row.relation_type for row in links)
    total = len(links)
    if total == 0:
        return CheckItem(
            code="L1.5", label="Link quality", score=0.0,
            grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
            detail={"total_links": 0},
            message="No question links at all",
        )

    strong = type_map.get("topic_strong", 0)
    adjacent = type_map.get("topic_adjacent", 0)
    fallback = type_map.get("topic_fallback", 0)
    score = ((strong * 1.0 + adjacent * 0.6 + fallback * 0.2) / total) * 100.0

    severity = Severity.WARNING if fallback > strong else Severity.SUGGESTION
    return CheckItem(
        code="L1.5", label="Link quality", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total": total, "strong": strong, "adjacent": adjacent, "fallback": fallback},
        message=f"strong={strong} adjacent={adjacent} fallback={fallback}",
    )


def _check_l1_6_dedup_check(
    session: Session, question_ids: list[int],
) -> CheckItem:
    if not question_ids:
        return _empty_check("L1.6", "Dedup check")

    dup_rows = session.query(
        models.QuestionItem.canonical_hash,
        func.count(models.QuestionItem.id),
    ).filter(
        models.QuestionItem.id.in_(question_ids),
        models.QuestionItem.canonical_hash.isnot(None),
    ).group_by(models.QuestionItem.canonical_hash).having(
        func.count(models.QuestionItem.id) > 1,
    ).all()

    duplicate_count = sum(count - 1 for _, count in dup_rows)
    total = len(question_ids)
    score = max(0.0, 100.0 - (duplicate_count / max(total, 1)) * 200.0)
    severity = Severity.CRITICAL if duplicate_count > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L1.6", label="Dedup check", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total": total, "duplicate_count": duplicate_count, "dup_groups": len(dup_rows)},
        message=f"{duplicate_count} duplicate questions in {len(dup_rows)} groups",
    )


def _check_l1_7_review_readiness(
    session: Session, question_ids: list[int],
) -> CheckItem:
    if not question_ids:
        return _empty_check("L1.7", "Review readiness")

    pkg_qs = session.query(models.KnowledgePackageQuestion).filter(
        models.KnowledgePackageQuestion.question_item_id.in_(question_ids),
    ).all()

    total = len(pkg_qs)
    if total == 0:
        return _empty_check("L1.7", "Review readiness")

    approved = sum(1 for q in pkg_qs if q.approved_status == "approved")
    score = _ratio(approved, total) * 100.0
    severity = Severity.WARNING if score < 80 else Severity.SUGGESTION
    return CheckItem(
        code="L1.7", label="Review readiness", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total": total, "approved": approved, "pending": total - approved},
        message=f"{approved}/{total} approved ({_ratio(approved, total):.0%})",
    )


def _check_l1_8_option_extraction_integrity(
    session: Session, question_ids: list[int],
) -> CheckItem:
    """Verify choice questions have properly extracted options in QuestionOption table."""
    choice_qs = (
        session.query(models.QuestionItem)
        .filter(models.QuestionItem.id.in_(question_ids))
        .filter(models.QuestionItem.question_type == "choice")
        .all()
    )
    if not choice_qs:
        return _empty_check("L1.8", "Option extraction integrity")

    total = len(choice_qs)
    missing_options: list[int] = []
    options_embedded_in_stem: list[int] = []
    contaminated_options: list[int] = []

    for q in choice_qs:
        opt_count = (
            session.query(models.QuestionOption)
            .filter(models.QuestionOption.question_item_id == q.id)
            .count()
        )
        if opt_count == 0:
            missing_options.append(int(q.id))
            # Check if options are embedded in stem instead
            stem = q.stem_plain_text or ""
            if re.search(r'[A-D][．、\.]\s*\S', stem):
                options_embedded_in_stem.append(int(q.id))

        # Check each option for contamination (sub-question text, answer numbers, etc.)
        for opt in session.query(models.QuestionOption).filter(
            models.QuestionOption.question_item_id == q.id,
        ).all():
            text = opt.option_text or ""
            # Options longer than 80 chars likely contain sub-question content
            if len(text) > 80:
                contaminated_options.append(int(q.id))
                break
            # Check for sub-question patterns in option text.
            # Negative lookbehind excludes math function notation like f(1), g(2).
            if re.search(r'(?<![a-zA-Z0-9])\(\d+\)|^[-–]\d|已知函数|则下列|解集为|g\(x\)', text):
                contaminated_options.append(int(q.id))
                break

    issue_count = len(set(missing_options) | set(contaminated_options))
    score = max(0.0, 100.0 - issue_count / max(total, 1) * 100.0 * 1.5)

    detail = {
        "total_choice": total,
        "missing_options": missing_options,
        "options_embedded_in_stem": options_embedded_in_stem,
        "contaminated_options": contaminated_options,
        "clean_count": total - issue_count,
    }
    severity = Severity.CRITICAL if missing_options else (
        Severity.WARNING if contaminated_options else Severity.SUGGESTION
    )
    msg_parts = []
    if missing_options:
        msg_parts.append(f"{len(missing_options)} choice Qs missing options")
    if options_embedded_in_stem:
        msg_parts.append(f"{len(options_embedded_in_stem)} have options in stem only")
    if contaminated_options:
        msg_parts.append(f"{len(contaminated_options)} have contaminated options")
    return CheckItem(
        code="L1.8", label="Option extraction integrity", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail=detail,
        message="; ".join(msg_parts) if msg_parts else f"All {total} choice Qs OK",
    )


_MULTI_PART_ANSWER_RE = re.compile(r'\(\d+\)')
_SOLUTION_PATTERNS_RE = re.compile(
    r'(故选|因此|综上|由题意|所以|综上所述|证明：|解：|故[，。]|'
    r'由.*可知|根据.*可得|令.*则|设.*则|则.*故选)'
)
_OPTION_IN_STEM_RE = re.compile(r'[A-D][．、\.]\s*\S')


def _check_l1_9_sub_question_splitting(
    session: Session, question_ids: list[int],
) -> CheckItem:
    """Detect multi-part questions incorrectly merged into a single QuestionItem.

    When answer is like '(1)C (2)A' but stem only shows one sub-question,
    the sub-questions were not properly split during ingestion.
    """
    if not question_ids:
        return _empty_check("L1.9", "Sub-question splitting")

    questions = session.query(models.QuestionItem).filter(
        models.QuestionItem.id.in_(question_ids),
    ).all()

    merged_count = 0
    merged_qids: list[int] = []
    examples: list[str] = []

    for q in questions:
        ans = q.answer_text or ""
        stem = q.stem_plain_text or ""

        ans_parts = _MULTI_PART_ANSWER_RE.findall(ans)
        stem_parts = _MULTI_PART_ANSWER_RE.findall(stem)

        # Answer has more sub-parts than stem → sub-questions merged
        if len(ans_parts) > len(stem_parts):
            merged_count += 1
            merged_qids.append(int(q.id))
            if len(examples) < 5:
                examples.append(
                    f"Q{int(q.id)}: ans_has={len(ans_parts)}parts stem_has={len(stem_parts)}parts "
                    f"ans={ans[:100]}"
                )

    total = len(questions)
    score = max(0.0, 100.0 - merged_count / max(total, 1) * 100.0 * 2.0)

    severity = Severity.CRITICAL if merged_count > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L1.9", label="Sub-question splitting", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total": total, "merged": merged_count,
            "merged_qids": merged_qids, "examples": examples,
        },
        message=f"{merged_count}/{total} questions have merged sub-questions"
        if merged_count else f"All {total} Qs properly split",
    )


def _check_l1_10_stem_solution_confusion(
    session: Session, question_ids: list[int],
) -> CheckItem:
    """Detect stems that are actually solutions/analysis text.

    This happens when the DOCX parser confuses solution text with question stems,
    creating QuestionItems where the 'stem' is really a detailed answer derivation.
    """
    if not question_ids:
        return _empty_check("L1.10", "Stem/solution confusion")

    questions = session.query(models.QuestionItem).filter(
        models.QuestionItem.id.in_(question_ids),
    ).all()

    confused_count = 0
    confused_qids: list[int] = []
    examples: list[str] = []

    for q in questions:
        stem = q.stem_plain_text or ""
        stem_len = len(stem)

        # Check 1: Stem contains solution conclusion patterns
        has_solution_pattern = bool(_SOLUTION_PATTERNS_RE.search(stem))

        # Check 2: Stem is very long and has no corresponding answer (likely a solution, not a question)
        has_answer = bool((q.answer_text or "").strip())
        is_long_without_answer = stem_len > 300 and not has_answer

        # Check 3: Stem ends with typical answer selection patterns
        ends_with_answer = bool(re.search(r'(故选[ABCD]|答案为[ABCD]|综上[，,]选[ABCD])', stem))

        if has_solution_pattern and (is_long_without_answer or ends_with_answer or not has_answer):
            confused_count += 1
            confused_qids.append(int(q.id))
            if len(examples) < 5:
                snippet = stem[:150]
                examples.append(f"Q{int(q.id)} [{q.question_type}]: {snippet}")

    total = len(questions)
    score = max(0.0, 100.0 - confused_count / max(total, 1) * 100.0 * 2.0)

    severity = Severity.CRITICAL if confused_count > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L1.10", label="Stem/solution confusion", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total": total, "confused": confused_count,
            "confused_qids": confused_qids, "examples": examples,
        },
        message=f"{confused_count}/{total} stems appear to be solutions"
        if confused_count else f"All {total} stems look correct",
    )


def _check_l1_11_option_content_sanity(
    session: Session, question_ids: list[int],
) -> CheckItem:
    """Deep-dive option text quality: length anomalies, formula integrity, cross-contamination."""
    if not question_ids:
        return _empty_check("L1.11", "Option content sanity")

    choice_qs = session.query(models.QuestionItem).filter(
        models.QuestionItem.id.in_(question_ids),
        models.QuestionItem.question_type == "choice",
    ).all()

    if not choice_qs:
        return _empty_check("L1.11", "Option content sanity")

    issues: list[str] = []
    total_options = 0
    anomalous_options = 0

    for q in choice_qs:
        opts = session.query(models.QuestionOption).filter(
            models.QuestionOption.question_item_id == q.id,
        ).order_by(models.QuestionOption.option_key).all()

        if not opts:
            continue

        opt_lengths = [len(opt.option_text or "") for opt in opts]
        total_options += len(opts)

        # Check: option length ratio too extreme (one option > 3x the median)
        if len(opt_lengths) >= 3:
            median_len = sorted(opt_lengths)[len(opt_lengths) // 2]
            if median_len > 0:
                for i, opt_len in enumerate(opt_lengths):
                    if opt_len > median_len * 3:
                        anomalous_options += 1
                        if len(issues) < 10:
                            issues.append(
                                f"Q{int(q.id)} opt{chr(65+i)}: len={opt_len} vs median={median_len}"
                            )

        # Check: options contain sub-question markers
        for opt in opts:
            text = opt.option_text or ""
            if re.search(r'\(\d+\)', text) or re.search(r'已知.*函数|则下列|解集为|的值域为', text):
                if int(q.id) not in {_parse_issue_qid(iss) for iss in issues}:
                    anomalous_options += 1
                    if len(issues) < 10:
                        issues.append(
                            f"Q{int(q.id)} opt{opt.option_key}: "
                            f"contains sub-question content"
                        )

    if total_options == 0:
        return _empty_check("L1.11", "Option content sanity")

    anomaly_ratio = anomalous_options / total_options
    score = max(0.0, 100.0 - anomaly_ratio * 100.0 * 2.0)
    severity = Severity.CRITICAL if anomaly_ratio > 0.10 else (
        Severity.WARNING if anomalous_options > 0 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L1.11", label="Option content sanity", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total_options": total_options,
            "anomalous_options": anomalous_options,
            "issues": issues,
        },
        message=f"{anomalous_options}/{total_options} options anomalous"
        if anomalous_options else f"All {total_options} options look sane",
    )


def _parse_issue_qid(issue_text: str) -> int:
    """Extract question ID from issue description like 'Q9381 optD: ...'"""
    m = re.search(r'Q(\d+)', issue_text)
    return int(m.group(1)) if m else -1


def _audit_l1_questions(
    session: Session, package_id: int, thresholds: ReportThresholds,
) -> LayerResult:
    question_ids = _package_question_ids(session, package_id)
    checks = [
        _check_l1_1_extraction_completeness(session, question_ids, thresholds),
        _check_l1_2_structure_integrity(session, question_ids),
        _check_l1_3_type_distribution(session, question_ids),
        _check_l1_4_kp_link_coverage(session, question_ids),
        _check_l1_5_link_quality(session, question_ids),
        _check_l1_6_dedup_check(session, question_ids),
        _check_l1_7_review_readiness(session, question_ids),
        _check_l1_8_option_extraction_integrity(session, question_ids),
        _check_l1_9_sub_question_splitting(session, question_ids),
        _check_l1_10_stem_solution_confusion(session, question_ids),
        _check_l1_11_option_content_sanity(session, question_ids),
    ]
    score = _compute_layer_score(checks, _L1_WEIGHTS)
    return LayerResult(
        layer_code="L1", layer_name="Question Quality", weight=0.25,
        score=score, grade=_score_to_grade(score), checks=checks,
    )


# ---------------------------------------------------------------------------
# L2: Knowledge Point Quality (20%)
# ---------------------------------------------------------------------------

_L2_WEIGHTS = {
    "L2.1": 0.15, "L2.2": 0.20, "L2.3": 0.15,
    "L2.4": 0.15, "L2.5": 0.20, "L2.6": 0.15,
}


def _check_l2_1_extraction_completeness(
    point_ids: list[int], thresholds: ReportThresholds,
) -> CheckItem:
    count = len(point_ids)
    score = min(100.0, (count / max(thresholds.min_points, 1)) * 100.0)
    severity = Severity.CRITICAL if count < thresholds.min_points else Severity.SUGGESTION
    return CheckItem(
        code="L2.1", label="Extraction completeness", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"count": count, "threshold": thresholds.min_points},
        message=f"{count} knowledge points (min: {thresholds.min_points})",
    )


def _check_l2_2_purity_stability(
    session: Session, package_id: int,
) -> CheckItem:
    try:
        from analyzer.app.package_point_purity import reclassify_package_point_purity
        hashes: list[str] = []
        summary: dict[str, Any] = {}
        for _ in range(2):
            result = reclassify_package_point_purity(session, package_id, apply=False)
            payload = {
                "core": result["core"], "adjacent": result["adjacent"],
                "dependency": result["dependency"],
                "placeholder": result.get("placeholder", 0),
                "changed": result["changed"],
                "reason_counts": result["reason_counts"],
            }
            summary = payload
            hashes.append(_stable_hash(payload))
            session.rollback()

        stable = len(set(hashes)) == 1
        score = 100.0 if stable else 60.0
        severity = Severity.CRITICAL if not stable else Severity.SUGGESTION
        return CheckItem(
            code="L2.2", label="Purity stability", score=score,
            grade=_score_to_grade(score), severity=severity,
            detail={"stable": stable, "hashes": hashes, "summary": summary},
            message="Stable across 2 runs" if stable else "UNSTABLE - classification changed between runs",
        )
    except Exception as exc:
        return CheckItem(
            code="L2.2", label="Purity stability", score=0.0,
            grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
            detail={"error": str(exc)},
            message=f"Purity check failed: {exc}",
        )


_VAGUE_NAME_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("only_digits", re.compile(r"^\d+$")),
    ("too_short_one_char", re.compile(r"^.{1}$")),
    ("placeholder_like", re.compile(r"(未归类|待分类|fallback|placeholder|temp|TODO|未命名)", re.I)),
    ("only_punctuation", re.compile(r"^[\s\W_]+$")),
]


def _check_l2_3_naming_quality(
    session: Session, point_ids: list[int],
) -> CheckItem:
    if not point_ids:
        return _empty_check("L2.3", "Naming quality")

    points = session.query(models.KnowledgePoint).filter(
        models.KnowledgePoint.id.in_(point_ids),
    ).all()

    total = len(points)
    vague_count = 0
    too_short = 0
    too_long = 0
    grain_dist: Counter[str] = Counter()

    for point in points:
        name = point.canonical_name or ""
        length = len(name)

        if length <= 2:
            too_short += 1
        elif length > 30:
            too_long += 1

        for label, pattern in _VAGUE_NAME_PATTERNS:
            if pattern.search(name):
                vague_count += 1
                break

        # Inline grain classification to avoid import dependency
        grain = _classify_grain_inline(name)
        grain_dist[grain] += 1

    vague_penalty = (vague_count / total) * 100.0
    length_penalty = ((too_short + too_long) / total) * 30.0
    demotable = grain_dist.get("解题方法", 0) + grain_dist.get("运算/计算", 0)
    grain_penalty = (demotable / total) * 20.0

    score = max(0.0, 100.0 - vague_penalty - length_penalty - grain_penalty)
    severity = Severity.WARNING if vague_count > 0 or too_short > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L2.3", label="Naming quality", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total": total, "vague": vague_count, "too_short": too_short,
            "too_long": too_long, "grain_distribution": dict(grain_dist),
        },
        message=f"vague={vague_count} short={too_short} long={too_long} demotable={demotable}",
    )


def _classify_grain_inline(name: str) -> str:
    if re.search(r"(的定义|的概念|的含义|什么是)", name):
        return "概念定义"
    if re.search(r"(公式|定理|法则)", name):
        return "公式定理"
    if re.search(r"(方法|思路|步骤|策略|技巧)", name):
        return "解题方法"
    if re.search(r"(性质|特点|特征|规律)", name):
        return "性质规律"
    if re.search(r"(判定|判断|辨析|识别|证明)", name):
        return "判定/识别"
    if re.search(r"(运算|计算|求解|化简|求|解)", name):
        return "运算/计算"
    if re.search(r"(应用|结合|综合)", name):
        return "应用/综合"
    if re.search(r"(易错|误区|陷阱|注意|常见错)", name):
        return "易错点"
    if re.search(r"(关系|结构|分类)", name):
        return "结构关系"
    if re.search(r"[∀∃∈⊆⊇⇒⇔]", name) or re.search(r"[a-zA-Z]\([a-zA-Z]+\)", name):
        return "符号公式型"
    return "纯概念名词"


def _check_l2_4_block_grounding(
    session: Session, point_ids: list[int], package_id: int,
) -> CheckItem:
    if not point_ids:
        return _empty_check("L2.4", "Block grounding")

    pid_set = set(point_ids)

    # Direct grounding: blocks and atoms
    block_counts = dict(
        session.query(
            models.KnowledgeBlock.knowledge_point_id,
            func.count(models.KnowledgeBlock.id),
        ).filter(
            models.KnowledgeBlock.package_id == package_id,
            models.KnowledgeBlock.knowledge_point_id.in_(list(pid_set)),
        ).group_by(models.KnowledgeBlock.knowledge_point_id).all()
    )
    atom_counts = dict(
        session.query(
            models.KnowledgeAtom.knowledge_point_id,
            func.count(models.KnowledgeAtom.id),
        ).filter(
            models.KnowledgeAtom.package_id == package_id,
            models.KnowledgeAtom.knowledge_point_id.in_(list(pid_set)),
        ).group_by(models.KnowledgeAtom.knowledge_point_id).all()
    )
    # Indirect grounding: provenance links
    provenance_kps = {
        int(row[0])
        for row in session.query(models.KnowledgePointProvenance.knowledge_point_id)
        .filter(models.KnowledgePointProvenance.package_id == package_id)
        .all()
        if row[0] is not None
    }

    grounded: set[int] = set()
    for pid in pid_set:
        if block_counts.get(pid, 0) > 0 or atom_counts.get(pid, 0) > 0 or pid in provenance_kps:
            grounded.add(pid)
    ungrounded = len(pid_set - grounded)

    score = _ratio(len(grounded), len(pid_set)) * 100.0
    severity = Severity.CRITICAL if ungrounded > 0 else Severity.SUGGESTION
    total_blocks = sum(block_counts.values())
    total_atoms = sum(atom_counts.values())
    return CheckItem(
        code="L2.4", label="Block grounding", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total_kps": len(pid_set), "ungrounded": ungrounded,
            "total_blocks": total_blocks, "total_atoms": total_atoms,
            "provenance_kps": len(provenance_kps & pid_set),
            "grounded_by_direct": len({pid for pid in pid_set if block_counts.get(pid, 0) > 0 or atom_counts.get(pid, 0) > 0}),
            "grounded_by_provenance_only": len((provenance_kps & pid_set) - grounded.union(
                {pid for pid in pid_set if block_counts.get(pid, 0) > 0 or atom_counts.get(pid, 0) > 0}
            )),
        },
        message=f"{len(grounded)}/{len(pid_set)} KPs grounded, {ungrounded} ungrounded",
    )


def _check_l2_5_placeholder_residue(
    session: Session, package_id: int,
) -> CheckItem:
    try:
        from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService
        service = KnowledgePointIngestionService()

        placeholder_package_points = sum(
            1 for row in session.query(
                models.KnowledgePackagePoint.id, models.KnowledgePoint.canonical_name,
            ).join(
                models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgePackagePoint.knowledge_point_id,
            ).filter(models.KnowledgePackagePoint.package_id == package_id).all()
            if service._is_placeholder_point_name(row[1])
        )
        placeholder_blocks = sum(
            1 for row in session.query(
                models.KnowledgeBlock.id, models.KnowledgePoint.canonical_name,
            ).join(
                models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgeBlock.knowledge_point_id,
            ).filter(models.KnowledgeBlock.package_id == package_id).all()
            if service._is_placeholder_point_name(row[1])
        )
        placeholder_atoms = sum(
            1 for row in session.query(
                models.KnowledgeAtom.id, models.KnowledgePoint.canonical_name,
            ).join(
                models.KnowledgePoint, models.KnowledgePoint.id == models.KnowledgeAtom.knowledge_point_id,
            ).filter(models.KnowledgeAtom.package_id == package_id).all()
            if service._is_placeholder_point_name(row[1])
        )

        total = placeholder_package_points + placeholder_blocks + placeholder_atoms
        score = max(0.0, 100.0 - total * 25.0)
        severity = Severity.CRITICAL if total > 0 else Severity.SUGGESTION
        return CheckItem(
            code="L2.5", label="Placeholder residue", score=score,
            grade=_score_to_grade(score), severity=severity,
            detail={
                "package_points": placeholder_package_points,
                "blocks": placeholder_blocks, "atoms": placeholder_atoms,
            },
            message=f"{total} placeholder items (pp={placeholder_package_points} blk={placeholder_blocks} atm={placeholder_atoms})",
        )
    except Exception as exc:
        return CheckItem(
            code="L2.5", label="Placeholder residue", score=0.0,
            grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
            detail={"error": str(exc)},
            message=f"Check failed: {exc}",
        )


def _check_l2_6_kp_coverage(
    session: Session, point_ids: list[int], package_id: int,
) -> CheckItem:
    if not point_ids:
        return _empty_check("L2.6", "KP coverage")

    linked_point_ids = {
        int(row.knowledge_point_id)
        for row in session.query(models.KnowledgeQuestionLink.knowledge_point_id)
        .join(
            models.KnowledgePackageQuestion,
            models.KnowledgePackageQuestion.question_item_id == models.KnowledgeQuestionLink.question_item_id,
        )
        .filter(
            models.KnowledgePackageQuestion.package_id == package_id,
            models.KnowledgeQuestionLink.knowledge_point_id.in_(point_ids),
        ).all()
    }

    pid_set = set(point_ids)
    score = _ratio(len(linked_point_ids & pid_set), len(pid_set)) * 100.0
    unlinked = len(pid_set - linked_point_ids)
    severity = Severity.CRITICAL if unlinked > len(pid_set) * 0.5 else (
        Severity.WARNING if unlinked > 0 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L2.6", label="KP coverage", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total": len(pid_set), "linked": len(linked_point_ids & pid_set), "unlinked": unlinked},
        message=f"{len(linked_point_ids & pid_set)}/{len(pid_set)} KPs have question links ({unlinked} uncovered)",
    )


def _audit_l2_knowledge_points(
    session: Session, package_id: int, thresholds: ReportThresholds,
) -> LayerResult:
    point_ids = _package_point_ids(session, package_id)
    checks = [
        _check_l2_1_extraction_completeness(point_ids, thresholds),
        _check_l2_2_purity_stability(session, package_id),
        _check_l2_3_naming_quality(session, point_ids),
        _check_l2_4_block_grounding(session, point_ids, package_id),
        _check_l2_5_placeholder_residue(session, package_id),
        _check_l2_6_kp_coverage(session, point_ids, package_id),
    ]
    score = _compute_layer_score(checks, _L2_WEIGHTS)
    return LayerResult(
        layer_code="L2", layer_name="Knowledge Point Quality", weight=0.20,
        score=score, grade=_score_to_grade(score), checks=checks,
    )


# ---------------------------------------------------------------------------
# L3: Relation & Graph Quality (25%)
# ---------------------------------------------------------------------------

_L3_WEIGHTS = {
    "L3.1": 0.15, "L3.2": 0.10, "L3.3": 0.15, "L3.4": 0.15,
    "L3.5": 0.15, "L3.6": 0.15, "L3.7": 0.15,
}


def _check_l3_1_relation_coverage(
    session: Session, point_ids: list[int],
) -> CheckItem:
    if not point_ids:
        return _empty_check("L3.1", "Relation coverage")

    pid_set = set(point_ids)
    related: set[int] = set()
    for row in session.query(models.KnowledgePointRelation.source_knowledge_point_id).filter(
        models.KnowledgePointRelation.source_knowledge_point_id.in_(list(pid_set)),
    ).all():
        related.add(int(row[0]))
    for row in session.query(models.KnowledgePointRelation.target_knowledge_point_id).filter(
        models.KnowledgePointRelation.target_knowledge_point_id.in_(list(pid_set)),
    ).all():
        related.add(int(row[0]))

    coverage = _ratio(len(related & pid_set), len(pid_set))
    score = coverage * 100.0
    isolated = len(pid_set - related)
    severity = Severity.CRITICAL if isolated > len(pid_set) * 0.5 else (
        Severity.WARNING if isolated > 0 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L3.1", label="Relation coverage", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total_kps": len(pid_set), "related": len(related & pid_set), "isolated": isolated},
        message=f"{len(related & pid_set)}/{len(pid_set)} KPs in relations, {isolated} isolated",
    )


def _check_l3_2_relation_type_balance(
    session: Session, point_ids: list[int],
) -> CheckItem:
    if not point_ids:
        return _empty_check("L3.2", "Relation type balance")

    relations = session.query(models.KnowledgePointRelation).filter(
        models.KnowledgePointRelation.source_knowledge_point_id.in_(list(point_ids)),
        models.KnowledgePointRelation.target_knowledge_point_id.in_(list(point_ids)),
    ).all()

    type_counts = Counter(r.relation_type for r in relations)
    total = len(relations)

    if total == 0:
        return CheckItem(
            code="L3.2", label="Relation type balance", score=0.0,
            grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
            detail={"total": 0},
            message="No relations to evaluate",
        )

    types_present = len(type_counts)
    max_ratio = max(type_counts.values()) / total if total else 0
    type_score = min(types_present / 4.0, 1.0) * 50.0
    balance_score = max(0.0, (1.0 - max_ratio)) * 50.0

    score = type_score + balance_score
    severity = Severity.WARNING if types_present < 3 else Severity.SUGGESTION
    return CheckItem(
        code="L3.2", label="Relation type balance", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total": total, "type_counts": dict(type_counts), "types_present": types_present,
                "max_ratio": round(max_ratio, 4)},
        message=f"{types_present}/4 types: {dict(type_counts)}",
    )


def _check_l3_3_evidence_quality(
    session: Session, point_ids: list[int],
) -> CheckItem:
    if not point_ids:
        return _empty_check("L3.3", "Evidence quality")

    relations = (
        session.query(
            models.KnowledgePointRelation,
            models.KnowledgeBlock.normalized_text,
            models.KnowledgeBlock.raw_text,
        )
        .outerjoin(
            models.KnowledgeBlock,
            models.KnowledgeBlock.id == models.KnowledgePointRelation.evidence_block_id,
        )
        .filter(
            models.KnowledgePointRelation.source_knowledge_point_id.in_(list(point_ids)),
            models.KnowledgePointRelation.target_knowledge_point_id.in_(list(point_ids)),
        )
        .all()
    )

    total = len(relations)
    if total == 0:
        return _empty_check("L3.3", "Evidence quality")

    has_evidence = 0
    has_min_text = 0
    for rel, norm_text, raw_text in relations:
        if rel.evidence_block_id is not None:
            has_evidence += 1
            text = norm_text or raw_text or ""
            if len(re.sub(r"\s+", "", text)) >= 12:
                has_min_text += 1

    evidence_rate = _ratio(has_evidence, total)
    text_rate = _ratio(has_min_text, total)
    score = evidence_rate * 100 * 0.4 + text_rate * 100 * 0.6
    severity = Severity.WARNING if evidence_rate < 0.5 else Severity.SUGGESTION
    return CheckItem(
        code="L3.3", label="Evidence quality", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total": total, "with_evidence_block": has_evidence,
            "with_min_text": has_min_text,
            "evidence_rate": round(evidence_rate, 4), "text_rate": round(text_rate, 4),
        },
        message=f"evidence_block={evidence_rate:.0%} min_text={text_rate:.0%}",
    )


def _check_l3_4_projection_success(
    session: Session, package_id: int,
) -> CheckItem:
    try:
        from scripts.kp_relations_package_audit import _audit_package as audit_kp_relations
        relation_audit = audit_kp_relations(session, package_id)
        summary = relation_audit.get("summary", {})
        projectable = int(summary.get("projectable", 0) or 0)
        projected = int(summary.get("projected", 0) or 0)

        if projectable == 0:
            return _empty_check("L3.4", "Projection success", {"projectable": 0, "projected": 0})

        score = _ratio(projected, projectable) * 100.0
        unprojected = max(projectable - projected, 0)
        severity = Severity.CRITICAL if unprojected > 0 else Severity.SUGGESTION
        return CheckItem(
            code="L3.4", label="Projection success", score=score,
            grade=_score_to_grade(score), severity=severity,
            detail={"projectable": projectable, "projected": projected, "unprojected": unprojected},
            message=f"{projected}/{projectable} projectable relations projected, {unprojected} missing",
        )
    except Exception as exc:
        return CheckItem(
            code="L3.4", label="Projection success", score=0.0,
            grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
            detail={"error": str(exc)},
            message=f"Check failed: {exc}",
        )


def _check_l3_5_neo4j_sync(
    session: Session, point_ids: list[int],
) -> CheckItem:
    if not point_ids:
        return _empty_check("L3.5", "Neo4j sync")

    # Count PG KP-KP edges (entity_id is Integer column)
    pg_edges = session.query(models.EntityGraphEdge).filter(
        models.EntityGraphEdge.source_entity_type == "knowledge_point",
        models.EntityGraphEdge.target_entity_type == "knowledge_point",
        models.EntityGraphEdge.source_entity_id.in_(point_ids),
        models.EntityGraphEdge.target_entity_id.in_(point_ids),
    ).all()
    pg_count = len(pg_edges)

    try:
        from analyzer.app.graph_db import db as neo4j_db
        # Count Neo4j KP-KP relationships for these specific point IDs
        # Neo4j uses entity_key = "knowledge_point:{id}"
        neo4j_count = 0
        if point_ids:
            keys = [f"knowledge_point:{pid}" for pid in point_ids]
            neo4j_result = neo4j_db.run_query(
                "MATCH (a:KnowledgePoint)-[r]-(b:KnowledgePoint) "
                "WHERE a.entity_key IN $keys AND b.entity_key IN $keys "
                "RETURN count(r) AS count",
                {"keys": keys},
            )
            neo4j_count = int(neo4j_result[0]["count"]) if neo4j_result else 0
    except Exception as exc:
        return CheckItem(
            code="L3.5", label="Neo4j sync", score=70.0,
            grade=ScoreGrade.FAIR, severity=Severity.WARNING,
            detail={"pg_edge_count": pg_count, "neo4j_error": str(exc)},
            message=f"Neo4j unreachable: {exc}",
        )

    if pg_count == 0 and neo4j_count == 0:
        score = 100.0
    elif pg_count == 0:
        score = 100.0  # nothing to sync from PG
    else:
        sync_ratio = min(neo4j_count / max(pg_count, 1), 1.0)
        score = sync_ratio * 100.0

    gap = pg_count - neo4j_count
    severity = Severity.CRITICAL if gap > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L3.5", label="Neo4j sync", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"pg_edge_count": pg_count, "neo4j_relationship_count": neo4j_count, "gap": gap},
        message=f"PG: {pg_count} edges, Neo4j: {neo4j_count} relationships (gap={gap})",
    )


def _check_l3_6_graph_connectivity(
    session: Session, point_ids: list[int],
) -> CheckItem:
    if not point_ids:
        return _empty_check("L3.6", "Graph connectivity")

    pid_set = set(point_ids)
    edges = session.query(models.EntityGraphEdge).filter(
        models.EntityGraphEdge.source_entity_type == "knowledge_point",
        models.EntityGraphEdge.target_entity_type == "knowledge_point",
        models.EntityGraphEdge.source_entity_id.in_(list(pid_set)),
        models.EntityGraphEdge.target_entity_id.in_(list(pid_set)),
    ).all()

    adjacency: dict[int, set[int]] = defaultdict(set)
    for edge in edges:
        try:
            src, tgt = int(edge.source_entity_id), int(edge.target_entity_id)
            adjacency[src].add(tgt)
            adjacency[tgt].add(src)
        except (ValueError, TypeError):
            continue

    visited: set[int] = set()
    components = 0
    for pid in pid_set:
        if pid not in visited:
            components += 1
            if pid in adjacency:
                stack = [pid]
                while stack:
                    node = stack.pop()
                    if node not in visited:
                        visited.add(node)
                        stack.extend(adjacency[node] - visited)
            else:
                visited.add(pid)

    isolated = sum(1 for pid in pid_set if pid not in adjacency)
    total = len(pid_set)
    if total == 0:
        return _empty_check("L3.6", "Graph connectivity")

    if components == 1 and isolated == 0:
        score = 100.0
    else:
        component_penalty = (components - 1) / total * 100.0
        isolated_penalty = isolated / total * 100.0
        score = max(0.0, 100.0 - component_penalty - isolated_penalty * 0.5)

    severity = Severity.CRITICAL if isolated > total * 0.3 else (
        Severity.WARNING if isolated > 0 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L3.6", label="Graph connectivity", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total_kps": total, "components": components, "isolated": isolated,
                "edges": len(edges)},
        message=f"{components} components, {isolated}/{total} isolated KPs",
    )


def _check_l3_7_anomaly_count(
    session: Session, package_id: int,
) -> CheckItem:
    try:
        from scripts.kp_relations_package_audit import _audit_package as audit_kp_relations
        relation_audit = audit_kp_relations(session, package_id)
        summary = relation_audit.get("summary", {})
        anomaly_counts = summary.get("by_anomaly_flag", {})
        total_flags = sum(anomaly_counts.values())
        total_relations = int(summary.get("total_relations", 0) or 0)

        if total_relations == 0:
            return _empty_check("L3.7", "Anomaly count", {"anomaly_counts": {}})

        flags_per_relation = total_flags / max(total_relations, 1)
        score = max(0.0, 100.0 - flags_per_relation * 100.0)
        severity = Severity.CRITICAL if total_flags > total_relations else (
            Severity.WARNING if total_flags > 0 else Severity.SUGGESTION
        )
        return CheckItem(
            code="L3.7", label="Anomaly count", score=score,
            grade=_score_to_grade(score), severity=severity,
            detail={
                "total_relations": total_relations, "total_flags": total_flags,
                "anomaly_counts": anomaly_counts,
            },
            message=f"{total_flags} flags across {total_relations} relations",
        )
    except Exception as exc:
        return CheckItem(
            code="L3.7", label="Anomaly count", score=0.0,
            grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
            detail={"error": str(exc)},
            message=f"Check failed: {exc}",
        )


def _audit_l3_relations(
    session: Session, package_id: int, thresholds: ReportThresholds,
) -> LayerResult:
    point_ids = _package_point_ids(session, package_id)
    checks = [
        _check_l3_1_relation_coverage(session, point_ids),
        _check_l3_2_relation_type_balance(session, point_ids),
        _check_l3_3_evidence_quality(session, point_ids),
        _check_l3_4_projection_success(session, package_id),
        _check_l3_5_neo4j_sync(session, point_ids),
        _check_l3_6_graph_connectivity(session, point_ids),
        _check_l3_7_anomaly_count(session, package_id),
    ]
    score = _compute_layer_score(checks, _L3_WEIGHTS)
    return LayerResult(
        layer_code="L3", layer_name="Relation & Graph Quality", weight=0.25,
        score=score, grade=_score_to_grade(score), checks=checks,
    )


# ---------------------------------------------------------------------------
# L4: Retrieval & Vector Quality (20%)
# ---------------------------------------------------------------------------

_L4_WEIGHTS = {
    "L4.1": 0.20, "L4.2": 0.20, "L4.3": 0.20,
    "L4.4": 0.15, "L4.5": 0.15, "L4.6": 0.10,
}

KNOWLEDGE_ENTITY_TYPES = {
    "knowledge_package", "knowledge_point", "knowledge_package_point",
    "knowledge_block", "knowledge_atom", "knowledge_question_bridge",
    "knowledge_derivative",
}


def _check_l4_1_retrieval_doc_coverage(
    session: Session, package_id: int,
) -> CheckItem:
    docs = _knowledge_docs_for_package(session, package_id)
    by_type = Counter(doc.entity_type for doc in docs)

    covered = sum(1 for t in KNOWLEDGE_ENTITY_TYPES if by_type.get(t, 0) > 0)
    score = _ratio(covered, len(KNOWLEDGE_ENTITY_TYPES)) * 100.0
    missing_types = sorted(KNOWLEDGE_ENTITY_TYPES - set(by_type.keys()))
    severity = Severity.WARNING if missing_types else Severity.SUGGESTION
    return CheckItem(
        code="L4.1", label="Retrieval doc coverage", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "total_docs": len(docs), "by_type": dict(by_type),
            "covered_types": covered, "missing_types": missing_types,
        },
        message=f"{covered}/{len(KNOWLEDGE_ENTITY_TYPES)} entity types covered, {len(docs)} docs",
    )


def _check_l4_2_embedding_coverage(
    session: Session, package_id: int,
) -> CheckItem:
    docs = _knowledge_docs_for_package(session, package_id)
    doc_ids = [int(doc.id) for doc in docs]

    if not doc_ids:
        return _empty_check("L4.2", "Embedding coverage")

    embedded = session.query(
        func.count(func.distinct(models.EmbeddingPoint.retrieval_document_id))
    ).filter(
        models.EmbeddingPoint.retrieval_document_id.in_(doc_ids),
    ).scalar() or 0

    score = _ratio(embedded, len(doc_ids)) * 100.0
    gap = len(doc_ids) - embedded
    severity = Severity.CRITICAL if gap > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L4.2", label="Embedding coverage", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total_docs": len(doc_ids), "embedded": embedded, "gap": gap},
        message=f"{embedded}/{len(doc_ids)} docs have embeddings (gap={gap})",
    )


def _check_l4_3_qdrant_cross_check(
    session: Session, package_id: int,
) -> CheckItem:
    docs = _knowledge_docs_for_package(session, package_id)
    doc_ids = [int(doc.id) for doc in docs]
    if not doc_ids:
        return _empty_check("L4.3", "Qdrant cross-check")

    pg_count = session.query(func.count(models.EmbeddingPoint.id)).filter(
        models.EmbeddingPoint.retrieval_document_id.in_(doc_ids),
    ).scalar() or 0

    vector_ids: list[str] = []
    for doc in docs:
        meta = dict(doc.metadata_json or {})
        vid = str(meta.get("vector_id") or "").strip()
        if vid:
            vector_ids.append(vid)

    if not vector_ids or pg_count == 0:
        return _empty_check("L4.3", "Qdrant cross-check", {"pg_count": pg_count})

    qdrant_count = 0
    qdrant_error = None
    try:
        from analyzer.app.vector_db import db as search_db
        backend = getattr(search_db, "vector_backend", None)
        if backend and hasattr(backend, "_to_point_id"):
            point_ids = [backend._to_point_id(vid) for vid in vector_ids]
            found = backend.client.retrieve(
                collection_name=backend.collection_name,
                ids=point_ids,
                with_payload=False,
                with_vectors=False,
            )
            qdrant_count = len(found)
    except Exception as exc:
        qdrant_error = str(exc)

    if qdrant_error:
        return CheckItem(
            code="L4.3", label="Qdrant cross-check", score=70.0,
            grade=ScoreGrade.FAIR, severity=Severity.WARNING,
            detail={"pg_embedding_count": pg_count, "qdrant_error": qdrant_error},
            message=f"Qdrant unreachable: {qdrant_error}",
        )

    sync_ratio = _ratio(qdrant_count, pg_count) if qdrant_count > 0 else 0.0
    score = sync_ratio * 100.0
    severity = Severity.CRITICAL if sync_ratio < 0.90 else (
        Severity.WARNING if sync_ratio < 1.0 else Severity.SUGGESTION
    )
    return CheckItem(
        code="L4.3", label="Qdrant cross-check", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "pg_embedding_count": pg_count, "qdrant_point_count": qdrant_count,
            "vector_ids_checked": len(vector_ids), "sync_ratio": round(sync_ratio, 4),
        },
        message=f"PG: {pg_count} embeddings, Qdrant: {qdrant_count} points ({sync_ratio:.1%} synced)",
    )


def _check_l4_4_content_hash_consistency(
    session: Session, package_id: int,
) -> CheckItem:
    docs = _knowledge_docs_for_package(session, package_id)
    if not docs:
        return _empty_check("L4.4", "Hash consistency")

    mismatched = 0
    total = 0
    for doc in docs:
        eps = session.query(models.EmbeddingPoint).filter(
            models.EmbeddingPoint.retrieval_document_id == doc.id,
        ).all()
        for ep in eps:
            total += 1
            if ep.content_hash != doc.content_hash:
                mismatched += 1

    if total == 0:
        return _empty_check("L4.4", "Hash consistency")

    score = _ratio(total - mismatched, total) * 100.0
    severity = Severity.CRITICAL if mismatched > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L4.4", label="Hash consistency", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"total_pairs": total, "mismatched": mismatched},
        message=f"{mismatched}/{total} hash mismatches",
    )


def _check_l4_5_vector_search_sanity(
    session: Session, package_id: int,
) -> CheckItem:
    point_ids = _package_point_ids(session, package_id)
    if not point_ids:
        return _empty_check("L4.5", "Vector search sanity")

    point_names = [
        row[0] for row in session.query(models.KnowledgePoint.canonical_name)
        .filter(models.KnowledgePoint.id.in_(point_ids[:20]))
        .all()
        if row[0]
    ]
    if not point_names:
        return _empty_check("L4.5", "Vector search sanity")

    import random
    sample_count = min(3, len(point_names))
    samples = random.sample(point_names, sample_count)

    hits_found = 0
    error_detail = None
    try:
        from analyzer.app.vector_db import db as search_db
        for name in samples:
            results = search_db.hybrid_search_with_scores(
                query_text=name, n_results=10,
                entity_types=["knowledge_point"],
            )
            for result in results:
                content = str(result.get("content") or "")
                metadata = result.get("metadata") or {}
                kp_name = str(metadata.get("knowledge_point_name") or "")
                title = str(metadata.get("title") or "")
                if name in content or name in kp_name or name in title:
                    hits_found += 1
                    break
    except Exception as exc:
        error_detail = str(exc)

    if error_detail:
        return CheckItem(
            code="L4.5", label="Vector search sanity", score=70.0,
            grade=ScoreGrade.FAIR, severity=Severity.WARNING,
            detail={"error": error_detail},
            message=f"Vector search unreachable: {error_detail}",
        )

    score = _ratio(hits_found, len(samples)) * 100.0
    severity = Severity.WARNING if score < 100 else Severity.SUGGESTION
    return CheckItem(
        code="L4.5", label="Vector search sanity", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"samples": samples, "hits": hits_found},
        message=f"{hits_found}/{len(samples)} KP name searches returned self in top 10",
    )


def _check_l4_6_stale_doc_check(
    session: Session, package_id: int,
) -> CheckItem:
    knowledge_types = {
        "knowledge_package", "knowledge_point", "knowledge_package_point",
        "knowledge_block", "knowledge_atom", "knowledge_question_bridge",
        "knowledge_derivative",
    }
    all_docs = (
        session.query(models.RetrievalDocument)
        .filter(
            or_(
                models.RetrievalDocument.entity_type.in_(sorted(knowledge_types)),
                models.RetrievalDocument.metadata_json["entity_type"].as_string().in_(sorted(knowledge_types)),
            )
        )
        .all()
    )

    active_docs = [d for d in all_docs if d.is_active and _safe_int(
        (dict(d.metadata_json or {})).get("package_id")
    ) == package_id]
    inactive_docs = [d for d in all_docs if not d.is_active and _safe_int(
        (dict(d.metadata_json or {})).get("package_id")
    ) == package_id]

    total = len(active_docs) + len(inactive_docs)
    if total == 0:
        return _empty_check("L4.6", "Stale doc check")

    stale_ratio = _ratio(len(inactive_docs), total)
    score = max(0.0, 100.0 - stale_ratio * 100.0)
    severity = Severity.WARNING if inactive_docs else Severity.SUGGESTION
    return CheckItem(
        code="L4.6", label="Stale doc check", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"active": len(active_docs), "inactive": len(inactive_docs)},
        message=f"{len(inactive_docs)} inactive / {total} total retrieval docs",
    )


def _audit_l4_retrieval(
    session: Session, package_id: int, thresholds: ReportThresholds,
    skip_qdrant: bool = False, skip_vector_sanity: bool = False,
) -> LayerResult:
    checks = [
        _check_l4_1_retrieval_doc_coverage(session, package_id),
        _check_l4_2_embedding_coverage(session, package_id),
    ]
    if not skip_qdrant:
        checks.append(_check_l4_3_qdrant_cross_check(session, package_id))
    else:
        checks.append(CheckItem(
            code="L4.3", label="Qdrant cross-check", score=100.0,
            grade=ScoreGrade.EXCELLENT, severity=Severity.SUGGESTION,
            message="Skipped (--skip-qdrant)",
        ))
    checks.append(_check_l4_4_content_hash_consistency(session, package_id))
    if not skip_vector_sanity:
        checks.append(_check_l4_5_vector_search_sanity(session, package_id))
    else:
        checks.append(CheckItem(
            code="L4.5", label="Vector search sanity", score=100.0,
            grade=ScoreGrade.EXCELLENT, severity=Severity.SUGGESTION,
            message="Skipped (--skip-vector-sanity)",
        ))
    checks.append(_check_l4_6_stale_doc_check(session, package_id))

    score = _compute_layer_score(checks, _L4_WEIGHTS)
    return LayerResult(
        layer_code="L4", layer_name="Retrieval & Vector Quality", weight=0.20,
        score=score, grade=_score_to_grade(score), checks=checks,
    )


# ---------------------------------------------------------------------------
# L5: Data Integrity (10%)
# ---------------------------------------------------------------------------

_L5_WEIGHTS = {"L5.1": 0.25, "L5.2": 0.25, "L5.3": 0.25, "L5.4": 0.25}


def _check_l5_1_fk_integrity(
    session: Session, package_id: int,
) -> CheckItem:
    point_ids = _package_point_ids(session, package_id)
    issues: list[str] = []

    # Check KnowledgePackagePoint -> KnowledgePoint
    kpp_rows = session.query(models.KnowledgePackagePoint).filter(
        models.KnowledgePackagePoint.package_id == package_id,
    ).all()
    for row in kpp_rows:
        if row.knowledge_point_id is None:
            issues.append(f"KPP#{row.id}: NULL knowledge_point_id")
        else:
            exists = session.query(models.KnowledgePoint.id).filter(
                models.KnowledgePoint.id == row.knowledge_point_id,
            ).scalar()
            if not exists:
                issues.append(f"KPP#{row.id}: KP#{row.knowledge_point_id} not found")

    # Check KnowledgeQuestionLink -> QuestionItem
    for row in session.query(models.KnowledgeQuestionLink).filter(
        models.KnowledgeQuestionLink.knowledge_point_id.in_(point_ids),
    ).all():
        exists = session.query(models.QuestionItem.id).filter(
            models.QuestionItem.id == row.question_item_id,
        ).scalar()
        if not exists:
            issues.append(f"KQL#{row.id}: Q#{row.question_item_id} not found")

    # Check KnowledgeBlock -> KnowledgePoint
    blocks = session.query(models.KnowledgeBlock).filter(
        models.KnowledgeBlock.package_id == package_id,
    ).all()
    for block in blocks:
        if block.knowledge_point_id is not None:
            exists = session.query(models.KnowledgePoint.id).filter(
                models.KnowledgePoint.id == block.knowledge_point_id,
            ).scalar()
            if not exists:
                issues.append(f"KB#{block.id}: KP#{block.knowledge_point_id} not found")

    score = max(0.0, 100.0 - len(issues) * 10.0)
    severity = Severity.CRITICAL if issues else Severity.SUGGESTION
    return CheckItem(
        code="L5.1", label="FK referential integrity", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"issues": issues, "issue_count": len(issues)},
        message=f"{len(issues)} FK violations" if issues else "All FKs valid",
    )


def _check_l5_2_status_consistency(
    session: Session, package_id: int,
) -> CheckItem:
    package = session.query(models.KnowledgePackage).filter(
        models.KnowledgePackage.id == package_id,
    ).first()

    issues: list[str] = []
    if package:
        if package.parse_status in ("failed", "error"):
            issues.append(f"Package parse_status={package.parse_status}")
        if package.parse_status == "success" and package.parse_status != "success":
            pass
        if package.review_status not in ("published", "approved", None):
            if package.review_status == "draft":
                pass  # draft is normal for new packages
            else:
                issues.append(f"Package review_status={package.review_status}")

    score = max(0.0, 100.0 - len(issues) * 25.0)
    severity = Severity.CRITICAL if issues else Severity.SUGGESTION
    return CheckItem(
        code="L5.2", label="Status consistency", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={
            "parse_status": package.parse_status if package else None,
            "review_status": package.review_status if package else None,
            "issues": issues,
        },
        message=f"parse={package.parse_status if package else '?'} review={package.review_status if package else '?'}",
    )


def _check_l5_3_dangling_edges(
    session: Session, package_id: int,
) -> CheckItem:
    main_entity_models = {
        "knowledge_point": models.KnowledgePoint,
        "question_item": models.QuestionItem,
        "knowledge_block": models.KnowledgeBlock,
        "knowledge_atom": models.KnowledgeAtom,
        "knowledge_package": models.KnowledgePackage,
    }

    dangling_by_type: dict[str, int] = {}
    for entity_type, model in main_entity_models.items():
        source_ids = {
            int(row[0])
            for row in session.query(models.EntityGraphEdge.source_entity_id)
            .filter(models.EntityGraphEdge.source_entity_type == entity_type)
            .distinct().all()
        }
        target_ids = {
            int(row[0])
            for row in session.query(models.EntityGraphEdge.target_entity_id)
            .filter(models.EntityGraphEdge.target_entity_type == entity_type)
            .distinct().all()
        }
        edge_ids = source_ids | target_ids
        if not edge_ids:
            dangling_by_type[entity_type] = 0
            continue
        alive_ids = {
            int(row[0])
            for row in session.query(model.id).filter(model.id.in_(list(edge_ids))).all()
        }
        dangling_by_type[entity_type] = len(edge_ids - alive_ids)

    total_dangling = sum(dangling_by_type.values())
    score = max(0.0, 100.0 - total_dangling * 5.0) if total_dangling > 0 else 100.0
    severity = Severity.CRITICAL if total_dangling > 0 else Severity.SUGGESTION
    return CheckItem(
        code="L5.3", label="Dangling edges", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"dangling_by_type": dangling_by_type, "total": total_dangling},
        message=f"{total_dangling} dangling EntityGraphEdges" if total_dangling else "No dangling edges",
    )


def _check_l5_4_cross_table_consistency(
    session: Session, package_id: int,
) -> CheckItem:
    issues: list[str] = []
    point_ids = set(_package_point_ids(session, package_id))

    # KnowledgePackageQuestion questions should have QuestionItems
    pkg_qs = session.query(models.KnowledgePackageQuestion).filter(
        models.KnowledgePackageQuestion.package_id == package_id,
    ).all()
    for pq in pkg_qs:
        if pq.question_item_id:
            exists = session.query(models.QuestionItem.id).filter(
                models.QuestionItem.id == pq.question_item_id,
            ).scalar()
            if not exists:
                issues.append(f"KPQ#{pq.id}: Q#{pq.question_item_id} missing")

    # KnowledgePointRelation endpoints should both exist
    if point_ids:
        rels = session.query(models.KnowledgePointRelation).filter(
            models.KnowledgePointRelation.source_knowledge_point_id.in_(list(point_ids)),
            models.KnowledgePointRelation.target_knowledge_point_id.in_(list(point_ids)),
        ).all()
        for rel in rels:
            src = session.query(models.KnowledgePoint.id).filter(
                models.KnowledgePoint.id == rel.source_knowledge_point_id,
            ).scalar()
            tgt = session.query(models.KnowledgePoint.id).filter(
                models.KnowledgePoint.id == rel.target_knowledge_point_id,
            ).scalar()
            if not src or not tgt:
                issues.append(f"KPR#{rel.id}: endpoint missing (src={src}, tgt={tgt})")

    score = max(0.0, 100.0 - len(issues) * 15.0)
    severity = Severity.CRITICAL if issues else Severity.SUGGESTION
    return CheckItem(
        code="L5.4", label="Cross-table consistency", score=score,
        grade=_score_to_grade(score), severity=severity,
        detail={"issues": issues, "issue_count": len(issues)},
        message=f"{len(issues)} consistency violations" if issues else "All cross-checks pass",
    )


def _audit_l5_integrity(
    session: Session, package_id: int, thresholds: ReportThresholds,
) -> LayerResult:
    checks = [
        _check_l5_1_fk_integrity(session, package_id),
        _check_l5_2_status_consistency(session, package_id),
        _check_l5_3_dangling_edges(session, package_id),
        _check_l5_4_cross_table_consistency(session, package_id),
    ]
    score = _compute_layer_score(checks, _L5_WEIGHTS)
    return LayerResult(
        layer_code="L5", layer_name="Data Integrity", weight=0.10,
        score=score, grade=_score_to_grade(score), checks=checks,
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _build_report(
    session: Session,
    package_id: int,
    thresholds: ReportThresholds,
    skip_neo4j: bool = False,
    skip_qdrant: bool = False,
    skip_vector_sanity: bool = False,
) -> HealthReport:
    package = session.query(models.KnowledgePackage).filter(
        models.KnowledgePackage.id == package_id,
    ).first()
    if not package:
        raise ValueError(f"KnowledgePackage {package_id} not found")

    layer_builders = [
        lambda: _audit_l1_questions(session, package_id, thresholds),
        lambda: _audit_l2_knowledge_points(session, package_id, thresholds),
        lambda: _audit_l3_relations(session, package_id, thresholds),
        lambda: _audit_l4_retrieval(session, package_id, thresholds,
                                    skip_qdrant=skip_qdrant,
                                    skip_vector_sanity=skip_vector_sanity),
        lambda: _audit_l5_integrity(session, package_id, thresholds),
    ]

    layers: list[LayerResult] = []
    for builder in layer_builders:
        try:
            layers.append(builder())
        except Exception as exc:
            session.rollback()
            layers.append(LayerResult(
                layer_code="L?", layer_name="Error", weight=0.0,
                score=0.0, grade=ScoreGrade.CRITICAL,
                checks=[CheckItem(
                    code="ERR", label="Exception", score=0.0,
                    grade=ScoreGrade.CRITICAL, severity=Severity.CRITICAL,
                    detail={"error": str(exc)},
                    message=str(exc),
                )],
            ))

    overall_score = _compute_overall_score(layers)
    overall_grade = _score_to_grade(overall_score)

    critical_issues: list[str] = []
    warnings: list[str] = []
    suggestions: list[str] = []

    for layer in layers:
        for check in layer.checks:
            msg = f"{check.code} {check.label}: {check.message}"
            if check.severity == Severity.CRITICAL and check.score < 90:
                critical_issues.append(msg)
            elif check.severity == Severity.WARNING and check.score < 90:
                warnings.append(msg)
            elif check.severity == Severity.SUGGESTION and check.score < 75:
                suggestions.append(msg)

    return HealthReport(
        package_id=package_id,
        package_title=str(package.package_title or ""),
        parse_status=package.parse_status,
        review_status=package.review_status,
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        overall_score=overall_score,
        overall_grade=overall_grade,
        layers=layers,
        critical_issues=critical_issues,
        warnings=warnings,
        suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# Terminal renderer
# ---------------------------------------------------------------------------


_ANSI_COLORS: dict[ScoreGrade, str] = {
    ScoreGrade.EXCELLENT: "\033[32m",
    ScoreGrade.GOOD: "\033[34m",
    ScoreGrade.FAIR: "\033[33m",
    ScoreGrade.POOR: "\033[38;5;214m",
    ScoreGrade.CRITICAL: "\033[31m",
}
_ANSI_RESET = "\033[0m"
_ANSI_BOLD = "\033[1m"
_ANSI_DIM = "\033[2m"


def _color_text(text: str, grade: ScoreGrade | None = None, bold: bool = False) -> str:
    parts: list[str] = []
    if bold:
        parts.append(_ANSI_BOLD)
    if grade:
        parts.append(_ANSI_COLORS.get(grade, ""))
    parts.append(str(text))
    if grade:
        parts.append(_ANSI_RESET)
    if bold and not grade:
        parts.append(_ANSI_RESET)
    return "".join(parts)


def _grade_bar(score: float) -> str:
    bar_width = 20
    filled = int(round(score / 100.0 * bar_width))
    if filled > bar_width:
        filled = bar_width
    empty = bar_width - filled
    grade = _score_to_grade(score)
    fill_char = "="
    return _color_text(fill_char * filled + "-" * empty, grade)


def _render_terminal(report: HealthReport) -> str:
    lines: list[str] = []

    # Header
    lines.append("")
    lines.append(_color_text("=" * 70, bold=True))
    lines.append(_color_text("  TOPIC INGESTION HEALTH REPORT", bold=True))
    lines.append(_color_text(f"  Package: {report.package_id} - {report.package_title}", bold=True))
    lines.append(_color_text(f"  Generated: {report.generated_at}", bold=False))
    lines.append(_color_text("=" * 70, bold=True))
    lines.append("")

    # Overall score
    overall_bar = _grade_bar(report.overall_score)
    lines.append(
        f"  OVERALL SCORE: {_color_text(f'{report.overall_score:.1f}/100', report.overall_grade, bold=True)}  "
        f"[{_color_text(report.overall_grade.value, report.overall_grade, bold=True)}]  {overall_bar}"
    )
    lines.append("")

    # Layer scores
    for layer in report.layers:
        bar = _grade_bar(layer.score)
        lines.append(
            f"  {layer.layer_code} {layer.layer_name:<28} "
            f"{_color_text(f'{layer.score:.1f}', layer.grade, bold=True)}  "
            f"[{_color_text(layer.grade.value, layer.grade)}]  {bar}"
        )
    lines.append("")

    # Critical issues
    if report.critical_issues:
        lines.append(_color_text("  --- CRITICAL ISSUES (must fix) ---", bold=True))
        for issue in report.critical_issues:
            lines.append(f"  {_color_text('X', ScoreGrade.CRITICAL, bold=True)} {issue}")
        lines.append("")

    # Warnings
    if report.warnings:
        lines.append(_color_text("  --- WARNINGS (should fix) ---", bold=True))
        for warning in report.warnings:
            lines.append(f"  {_color_text('!', ScoreGrade.FAIR, bold=True)} {warning}")
        lines.append("")

    # Suggestions
    if report.suggestions:
        lines.append(_color_text("  --- SUGGESTIONS (nice to have) ---", bold=True))
        for suggestion in report.suggestions:
            lines.append(f"  o {suggestion}")
        lines.append("")

    # Per-check detail (compact)
    lines.append(_color_text("  --- DETAIL BY LAYER ---", bold=True))
    for layer in report.layers:
        lines.append(f"  {_ANSI_BOLD}{layer.layer_code} {layer.layer_name} ({layer.weight:.0%}):{_ANSI_RESET}")
        for check in layer.checks:
            check_color = _ANSI_COLORS.get(check.grade, "")
            indent = "      "
            lines.append(
                f"  {check_color}{check.score:5.1f}{_ANSI_RESET} {check.code} {check.label:<30} "
                f"{_ANSI_DIM}{check.message}{_ANSI_RESET}"
            )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------


def _report_to_json(report: HealthReport, thresholds: ReportThresholds) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "generated_at": report.generated_at,
        "thresholds": {
            "min_points": thresholds.min_points,
            "min_questions": thresholds.min_questions,
            "min_question_link_coverage": thresholds.min_question_link_coverage,
            "min_retrieval_docs": thresholds.min_retrieval_docs,
            "max_pending_ratio": thresholds.max_pending_ratio,
        },
        "package": {
            "package_id": report.package_id,
            "package_title": report.package_title,
            "parse_status": report.parse_status,
            "review_status": report.review_status,
            "overall_score": round(report.overall_score, 2),
            "overall_grade": report.overall_grade.value,
        },
        "layers": [
            {
                "code": layer.layer_code,
                "name": layer.layer_name,
                "weight": layer.weight,
                "score": round(layer.score, 2),
                "grade": layer.grade.value,
                "checks": [
                    {
                        "code": check.code,
                        "label": check.label,
                        "score": round(check.score, 2),
                        "grade": check.grade.value,
                        "severity": check.severity.value,
                        "message": check.message,
                        "detail": check.detail,
                    }
                    for check in layer.checks
                ],
            }
            for layer in report.layers
        ],
        "issues": {
            "critical": report.critical_issues,
            "warnings": report.warnings,
            "suggestions": report.suggestions,
        },
    }


# ---------------------------------------------------------------------------
# CLI and main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Comprehensive topic ingestion health report with 5-layer scoring"
    )
    ap.add_argument("--package-id", type=int, action="append", help="KnowledgePackage id (repeatable)")
    ap.add_argument("--source-document-id", type=int, action="append",
                    help="Resolve latest package for source_documents.id")
    ap.add_argument("--package-title-like", action="append",
                    help="Resolve package by unique title keyword")
    ap.add_argument("--all-packages", action="store_true",
                    help="Audit all packages")

    ap.add_argument("--json-out", default=None, help="JSON output path")
    ap.add_argument("--json-only", action="store_true", help="Only output JSON, no terminal report")

    ap.add_argument("--skip-neo4j", action="store_true", help="Skip Neo4j sync check (L3.5)")
    ap.add_argument("--skip-qdrant", action="store_true", help="Skip Qdrant cross-check (L4.3)")
    ap.add_argument("--skip-vector-sanity", action="store_true",
                    help="Skip vector search sanity check (L4.5)")

    # Threshold overrides
    ap.add_argument("--threshold-min-questions", type=int, default=5)
    ap.add_argument("--threshold-min-points", type=int, default=3)
    ap.add_argument("--threshold-question-link-coverage", type=float, default=0.75)
    ap.add_argument("--threshold-min-retrieval-docs", type=int, default=1)
    ap.add_argument("--threshold-max-pending-ratio", type=float, default=0.20)
    ap.add_argument("--threshold-require-full-embeddings", action="store_true", default=True)
    ap.add_argument("--allow-embedding-gap", action="store_true",
                    help="Don't require all retrieval docs to have embeddings")

    args = ap.parse_args()

    thresholds = ReportThresholds(
        min_points=args.threshold_min_points,
        min_questions=args.threshold_min_questions,
        min_question_link_coverage=args.threshold_question_link_coverage,
        min_retrieval_docs=args.threshold_min_retrieval_docs,
        max_pending_ratio=args.threshold_max_pending_ratio,
        require_full_embeddings=not args.allow_embedding_gap,
    )

    session_factory = sessionmaker(bind=engine)
    session = session_factory()

    try:
        if args.all_packages:
            package_ids = [
                int(row[0])
                for row in session.query(models.KnowledgePackage.id)
                .order_by(models.KnowledgePackage.id.asc()).all()
            ]
            if not package_ids:
                raise SystemExit("No packages found in database")
        else:
            package_ids = _resolve_package_ids(
                session,
                package_ids=args.package_id,
                source_document_ids=args.source_document_id,
                title_keywords=args.package_title_like,
            )

        reports: list[HealthReport] = []
        for package_id in package_ids:
            report = _build_report(
                session, package_id, thresholds,
                skip_neo4j=args.skip_neo4j,
                skip_qdrant=args.skip_qdrant,
                skip_vector_sanity=args.skip_vector_sanity,
            )
            reports.append(report)

            if not args.json_only:
                print(_render_terminal(report))

        # JSON output
        all_json = {
            "schema_version": "1.0",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "thresholds": {
                "min_points": thresholds.min_points,
                "min_questions": thresholds.min_questions,
                "min_question_link_coverage": thresholds.min_question_link_coverage,
                "min_retrieval_docs": thresholds.min_retrieval_docs,
                "max_pending_ratio": thresholds.max_pending_ratio,
            },
            "package_count": len(reports),
            "packages": [_report_to_json(r, thresholds)["package"] for r in reports],
            "layers_summary": [
                {
                    "code": r.layers[0].layer_code if r.layers else "?",
                    "overall_score": round(r.overall_score, 2),
                    "overall_grade": r.overall_grade.value,
                }
                for r in reports
            ] if len(reports) > 1 else [],
            "full_reports": [_report_to_json(r, thresholds) for r in reports],
        }

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = (
            Path(args.json_out)
            if args.json_out
            else (OUT_DIR / f"topic_ingest_health_report_{stamp}.json")
        )
        if not out_path.is_absolute():
            out_path = ROOT / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(all_json, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {out_path}")

        # Return exit code
        any_critical = any(
            any(check.severity == Severity.CRITICAL and check.score < 90 for check in layer.checks)
            for r in reports for layer in r.layers
        )
        return 1 if any_critical else 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
