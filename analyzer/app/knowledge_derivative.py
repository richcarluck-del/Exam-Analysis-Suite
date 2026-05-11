"""知识点衍生层（Derivative Layer）

"衍生层" 的目标：在已入库的 KnowledgePoint + KnowledgeBlock + KnowledgeAtom 之上，
生成 **面向不同受众、不同用途** 的再创作内容，并受人工审核控制是否进入检索 (RAG)。

数据模型：shared.models.KnowledgeDerivative
  id, knowledge_point_id, derivative_type, target_audience,
  prompt_version, source_snapshot_json, generated_content(JSON), review_status

  review_status: draft | approved | rejected
  derivative_type:
    - concept_explainer  面向学生的通俗讲解
    - exam_cheatsheet    考点速记卡
    - common_pitfalls    易错/陷阱
    - comparison         易混对比
    - memory_tip         记忆口诀

  target_audience:
    - student  学生
    - teacher  教师/命题
    - parent   家长

生成链路：
  generate_for_point(db, knowledge_point_id, derivative_type, target_audience)
    → 拼 source_snapshot（知识点 + 归属的 KnowledgeBlock 主块/段落 + KnowledgeAtom）
    → resolve_step_prompt("analyzer.knowledge_derivative_generation")
    → resolve_step_llm_config("analyzer.knowledge_derivative_generation")
    → call_llm(JSON mode)
    → 解析 JSON → upsert 到 knowledge_derivatives（以 (kp_id, type, audience, prompt_version) 为幂等键）

审核与检索：
  set_review_status(db, derivative_id, "approved")
    → 同步写入 RetrievalDocument（entity_type="knowledge_derivative"），受 KNOWLEDGE_RAG_ENABLED 控制。
  set_review_status(db, derivative_id, "rejected"|"draft")
    → 从 RetrievalDocument 中移除（如果已写过）。

此模块只依赖 analyzer.app.llm_client 与 shared.prompt/llm_step_config，
与 knowledge_graph_projection.py 相互独立，可单独开关。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from shared import models
from shared.llm_step_config import resolve_step_llm_config
from shared.prompt_step_config import resolve_step_prompt

from . import vector_db
from .config import KNOWLEDGE_DERIVATIVE_ENABLED, KNOWLEDGE_RAG_ENABLED
from .derivative_run_logging import DerivativeRunSession
from .llm_client import call_llm


logger = logging.getLogger(__name__)

# Qdrant 仅接受无符号整数或 UUID 作为 point id；用确定性 UUID 承载业务键。
_DERIVATIVE_QDRANT_NS = uuid.UUID("8c4e2f10-9a3b-5d7e-8f1a-2b4c6d8e0f12")


STEP_KEY = "analyzer.knowledge_derivative_generation"
PROMPT_STEP_KEY = "analyzer.knowledge_derivative_generation"

DERIVATIVE_TYPES = (
    "concept_explainer",
    "exam_cheatsheet",
    "common_pitfalls",
    "comparison",
    "memory_tip",
)

TARGET_AUDIENCES = (
    "student",
    "teacher",
    "parent",
)

REVIEW_STATUSES = ("draft", "approved", "rejected")


class DerivativeEvidenceError(Exception):
    """无有效溯源语料时拒绝衍生生成（fail-hard）。"""

    def __init__(
        self,
        message: str,
        *,
        knowledge_point_id: Optional[int] = None,
        run_id: Optional[str] = None,
    ):
        super().__init__(message)
        self.knowledge_point_id = knowledge_point_id
        self.run_id = run_id


# =============================================================================
# 源快照构造
# =============================================================================


@dataclass
class SourceSnapshot:
    knowledge_point_id: int
    canonical_name: str
    subject: Optional[str]
    grade_scope: Optional[str]
    summary: Optional[str]
    aliases: List[str]
    blocks: List[Dict[str, Any]]
    atoms: List[Dict[str, Any]]

    def as_json(self) -> Dict[str, Any]:
        return {
            "knowledge_point_id": self.knowledge_point_id,
            "canonical_name": self.canonical_name,
            "subject": self.subject,
            "grade_scope": self.grade_scope,
            "summary": self.summary,
            "aliases": self.aliases,
            "blocks": self.blocks,
            "atoms": self.atoms,
        }

    def digest(self) -> str:
        payload = json.dumps(self.as_json(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_block_text(block: models.KnowledgeBlock) -> str:
    """专题 DOCX 块常见：正文同时存在于列字段与 rich_content_json.plain_text；衍生快照须两边都试。"""
    text = (block.normalized_text or block.raw_text or "").strip()
    if text:
        return re.sub(r"\s+", " ", text)
    rich = block.rich_content_json
    if isinstance(rich, dict):
        pt = rich.get("plain_text")
        if isinstance(pt, str) and pt.strip():
            return re.sub(r"\s+", " ", pt.strip())
        for key in ("section_title", "text"):
            v = rich.get(key)
            if isinstance(v, str) and v.strip():
                return re.sub(r"\s+", " ", v.strip())
    return ""


def build_source_snapshot(db: Session, knowledge_point_id: int, *, block_limit: int = 12) -> SourceSnapshot:
    point = (
        db.query(models.KnowledgePoint)
        .filter(models.KnowledgePoint.id == knowledge_point_id)
        .first()
    )
    if not point:
        raise ValueError(f"KnowledgePoint {knowledge_point_id} 不存在")

    lim = int(block_limit)
    prov_rows = (
        db.query(models.KnowledgePointProvenance)
        .filter(models.KnowledgePointProvenance.knowledge_point_id == knowledge_point_id)
        .filter(models.KnowledgePointProvenance.source_kind == "knowledge_block")
        .order_by(
            models.KnowledgePointProvenance.is_primary.desc(),
            models.KnowledgePointProvenance.id.asc(),
        )
        .all()
    )
    ordered_block_ids: List[int] = []
    seen_ids: set[int] = set()
    for pr in prov_rows:
        bid = int(pr.source_id)
        if bid in seen_ids:
            continue
        seen_ids.add(bid)
        ordered_block_ids.append(bid)

    block_payload: List[Dict[str, Any]] = []
    if ordered_block_ids:
        rows = (
            db.query(models.KnowledgeBlock)
            .filter(models.KnowledgeBlock.id.in_(ordered_block_ids))
            .all()
        )
        by_id = {b.id: b for b in rows}
        for bid in ordered_block_ids:
            if len(block_payload) >= lim:
                break
            block = by_id.get(bid)
            if block is None:
                continue
            text = _normalize_block_text(block)
            if not text:
                continue
            block_payload.append(
                {
                    "block_id": block.id,
                    "package_id": block.package_id,
                    "block_role": block.block_role,
                    "section_path": block.section_path,
                    "text": text[:1600],
                }
            )
    else:
        # 无溯源行：兼容迁移前数据（仅按块上 FK）
        blocks = (
            db.query(models.KnowledgeBlock)
            .filter(models.KnowledgeBlock.knowledge_point_id == knowledge_point_id)
            .order_by(
                models.KnowledgeBlock.is_primary.desc(),
                models.KnowledgeBlock.block_order.asc(),
                models.KnowledgeBlock.id.asc(),
            )
            .limit(lim)
            .all()
        )
        for block in blocks:
            text = _normalize_block_text(block)
            if not text:
                continue
            block_payload.append(
                {
                    "block_id": block.id,
                    "package_id": block.package_id,
                    "block_role": block.block_role,
                    "section_path": block.section_path,
                    "text": text[:1600],
                }
            )

    atom_rows = (
        db.query(models.KnowledgeAtom)
        .filter(models.KnowledgeAtom.knowledge_point_id == knowledge_point_id)
        .order_by(models.KnowledgeAtom.id.asc())
        .limit(24)
        .all()
    )
    atom_payload: List[Dict[str, Any]] = []
    for atom in atom_rows:
        atom_payload.append(
            {
                "atom_id": atom.id,
                "atom_type": atom.atom_type,
                "text": (atom.canonical_text or "").strip()[:800],
                "formula_signature": atom.formula_signature,
                "review_status": atom.review_status,
            }
        )

    aliases_raw = point.aliases_json if isinstance(point.aliases_json, list) else []
    aliases = [str(item).strip() for item in aliases_raw if str(item).strip()]

    summary_ok = bool((point.canonical_summary or "").strip())
    any_atom_text = any((atom.canonical_text or "").strip() for atom in atom_rows)
    if not block_payload and not any_atom_text and not summary_ok:
        raise DerivativeEvidenceError(
            f"知识点 {knowledge_point_id} 无有效溯源语料（无块正文、无原子句、无摘要），无法生成衍生内容",
            knowledge_point_id=knowledge_point_id,
        )

    return SourceSnapshot(
        knowledge_point_id=point.id,
        canonical_name=point.canonical_name,
        subject=point.subject,
        grade_scope=point.grade_scope,
        summary=point.canonical_summary,
        aliases=aliases,
        blocks=block_payload,
        atoms=atom_payload,
    )


# =============================================================================
# LLM 调用 + JSON 解析
# =============================================================================


def _render_prompt_variables(
    snapshot: SourceSnapshot,
    *,
    derivative_type: str,
    target_audience: str,
) -> Dict[str, Any]:
    subject_grade = "/".join(
        [part for part in (snapshot.subject or "", snapshot.grade_scope or "") if part]
    ) or "（未指定学科/学段）"
    return {
        "knowledge_point_name": snapshot.canonical_name,
        "derivative_type": derivative_type,
        "target_audience": target_audience,
        "subject_grade": subject_grade,
        "source_snapshot": json.dumps(snapshot.as_json(), ensure_ascii=False, indent=2),
    }


_JSON_OBJECT_PATTERN = re.compile(r"\{[\s\S]*\}")


def _parse_llm_json(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_]*\n?", "", text).rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        match = _JSON_OBJECT_PATTERN.search(text)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _clamp01(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN guard
        return None
    return max(0.0, min(1.0, v))


def _normalize_generated_content(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    bullets = raw.get("bullets") or []
    if not isinstance(bullets, list):
        bullets = []
    bullets = [str(item).strip() for item in bullets if str(item).strip()]
    quality = raw.get("quality") or {}
    if not isinstance(quality, dict):
        quality = {}
    groundedness = _clamp01(quality.get("groundedness"))
    coverage = _clamp01(quality.get("coverage"))
    normalized = {
        "title": str(raw.get("title") or "").strip(),
        "summary": str(raw.get("summary") or "").strip(),
        "bullets": bullets[:12],
        "body": str(raw.get("body") or "").strip(),
        "quality": {
            "groundedness": groundedness,
            "coverage": coverage,
        },
        "notes": str(raw.get("notes") or "").strip(),
    }
    if not normalized["title"] and not normalized["body"] and not normalized["summary"]:
        return None
    return normalized


def _call_derivative_llm(
    db: Session,
    snapshot: SourceSnapshot,
    *,
    derivative_type: str,
    target_audience: str,
    run_session: Optional[DerivativeRunSession] = None,
) -> Dict[str, Any]:
    variables = _render_prompt_variables(
        snapshot,
        derivative_type=derivative_type,
        target_audience=target_audience,
    )
    prompt_cfg = resolve_step_prompt(db, PROMPT_STEP_KEY, variables=variables)
    if not prompt_cfg or not prompt_cfg.get("prompt_text"):
        raise RuntimeError("衍生层提示词未配置（analyzer.knowledge_derivative_generation）")

    llm_cfg = resolve_step_llm_config(db, STEP_KEY, allow_generic_fallback=True)
    if not llm_cfg:
        raise RuntimeError("衍生层 LLM 未配置（analyzer.knowledge_derivative_generation）")

    messages = [
        {
            "role": "system",
            "content": "你是一名中学教研/命题/讲解助手，擅长在已有教材内容基础上做贴合受众的再创作。只输出 JSON。",
        },
        {"role": "user", "content": prompt_cfg["prompt_text"]},
    ]
    raw = call_llm(messages, llm_cfg, json_mode=True)
    parsed = _parse_llm_json(raw)
    normalized = _normalize_generated_content(parsed)
    log_err: Optional[str] = None
    if not normalized:
        if raw is None:
            log_err = (
                "衍生层 LLM 调用失败（无返回内容）。请查看本运行目录下 run.log 与控制台；"
                "常见原因：API 密钥/网络、模型名错误、或网关不支持 json_object（已自动回退重试）。"
            )
        else:
            log_err = f"衍生层模型返回无法解析：raw={str(raw)[:800]}"
        if run_session:
            run_session.log_llm_round(
                derivative_type=derivative_type,
                audience=target_audience,
                messages=messages,
                llm_cfg=llm_cfg,
                raw_response=raw,
                parsed_content=None,
                error=log_err,
            )
        raise RuntimeError(log_err or "")

    if run_session:
        run_session.log_llm_round(
            derivative_type=derivative_type,
            audience=target_audience,
            messages=messages,
            llm_cfg=llm_cfg,
            raw_response=raw,
            parsed_content=normalized,
            error=None,
        )

    return {
        "prompt_version": prompt_cfg.get("resolved_version"),
        "prompt_key": prompt_cfg.get("prompt_key"),
        "llm_provider": llm_cfg.get("provider_name"),
        "llm_model": llm_cfg.get("model_name"),
        "raw_response": raw,
        "content": normalized,
    }


# =============================================================================
# 幂等 upsert
# =============================================================================


def _upsert_derivative(
    db: Session,
    *,
    knowledge_point_id: int,
    derivative_type: str,
    target_audience: str,
    snapshot: SourceSnapshot,
    llm_result: Dict[str, Any],
) -> models.KnowledgeDerivative:
    prompt_version_token = str(llm_result.get("prompt_version") or "").strip() or "system"
    source_snapshot_json = {
        "digest": snapshot.digest(),
        "snapshot": snapshot.as_json(),
        "llm_provider": llm_result.get("llm_provider"),
        "llm_model": llm_result.get("llm_model"),
    }
    generated_content = {
        **(llm_result.get("content") or {}),
        "prompt_key": llm_result.get("prompt_key"),
        "prompt_version": llm_result.get("prompt_version"),
    }

    record = (
        db.query(models.KnowledgeDerivative)
        .filter(
            models.KnowledgeDerivative.knowledge_point_id == knowledge_point_id,
            models.KnowledgeDerivative.derivative_type == derivative_type,
            models.KnowledgeDerivative.target_audience == target_audience,
            models.KnowledgeDerivative.prompt_version == prompt_version_token,
        )
        .first()
    )
    if record is None:
        record = models.KnowledgeDerivative(
            knowledge_point_id=knowledge_point_id,
            derivative_type=derivative_type,
            target_audience=target_audience,
            prompt_version=prompt_version_token,
            source_snapshot_json=source_snapshot_json,
            generated_content=generated_content,
            review_status="draft",
        )
        db.add(record)
    else:
        record.source_snapshot_json = source_snapshot_json
        record.generated_content = generated_content
        # 重新生成后把审核态打回 draft；已 approved 的条目人工再审。
        record.review_status = "draft"
    db.flush()
    return record


# =============================================================================
# 对外入口：生成
# =============================================================================


def _execute_derivative_generations(
    db: Session,
    *,
    knowledge_point_id: int,
    snapshot: SourceSnapshot,
    valid_types: List[str],
    valid_audiences: List[str],
    session: DerivativeRunSession,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """同一快照下按类型×受众循环生成并落库。"""
    generated: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for derivative_type in valid_types:
        for audience in valid_audiences:
            try:
                session.log(f"--- 组合 kp={knowledge_point_id} type={derivative_type} audience={audience} ---")
                llm_result = _call_derivative_llm(
                    db,
                    snapshot,
                    derivative_type=derivative_type,
                    target_audience=audience,
                    run_session=session,
                )
                record = _upsert_derivative(
                    db,
                    knowledge_point_id=knowledge_point_id,
                    derivative_type=derivative_type,
                    target_audience=audience,
                    snapshot=snapshot,
                    llm_result=llm_result,
                )
                db.commit()
                db.refresh(record)
                generated.append(
                    {
                        "id": record.id,
                        "derivative_type": derivative_type,
                        "target_audience": audience,
                        "review_status": record.review_status,
                        "prompt_version": record.prompt_version,
                    }
                )
                session.log(
                    f"已落库 kp={knowledge_point_id} derivative_id={record.id} review_status={record.review_status}"
                )
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "Generate derivative failed: kp=%s type=%s audience=%s",
                    knowledge_point_id,
                    derivative_type,
                    audience,
                )
                session.log(f"失败 kp={knowledge_point_id} type={derivative_type} audience={audience}: {exc}")
                errors.append(
                    {
                        "derivative_type": derivative_type,
                        "target_audience": audience,
                        "knowledge_point_id": knowledge_point_id,
                        "error": str(exc),
                    }
                )

    return generated, errors


def generate_for_point(
    db: Session,
    knowledge_point_id: int,
    *,
    derivative_types: Sequence[str] = DERIVATIVE_TYPES,
    target_audiences: Sequence[str] = ("student",),
    respect_flag: bool = True,
) -> Dict[str, Any]:
    """对单个知识点生成一组衍生内容。"""

    if respect_flag and not KNOWLEDGE_DERIVATIVE_ENABLED:
        return {
            "status": "skipped",
            "reason": "KNOWLEDGE_DERIVATIVE_ENABLED=false",
            "knowledge_point_id": knowledge_point_id,
            "generated": [],
            "run": None,
        }

    valid_types = [t for t in derivative_types if t in DERIVATIVE_TYPES]
    valid_audiences = [a for a in target_audiences if a in TARGET_AUDIENCES]
    if not valid_types or not valid_audiences:
        raise ValueError("derivative_types / target_audiences 为空或全部不合法")

    session = DerivativeRunSession(
        mode="knowledge_point",
        knowledge_point_id=knowledge_point_id,
        package_id=None,
    )
    try:
        session.log(
            f"开始 generate_for_point kp={knowledge_point_id} types={valid_types} audiences={valid_audiences}"
        )
        snapshot = build_source_snapshot(db, knowledge_point_id)
        session.log_snapshot_brief(snapshot)

        generated, errors = _execute_derivative_generations(
            db,
            knowledge_point_id=knowledge_point_id,
            snapshot=snapshot,
            valid_types=valid_types,
            valid_audiences=valid_audiences,
            session=session,
        )

        session.log(
            f"结束 ok={not errors} generated={len(generated)} errors={len(errors)}"
        )
        return {
            "status": "ok" if not errors else "partial",
            "knowledge_point_id": knowledge_point_id,
            "generated": generated,
            "errors": errors,
            "run": session.to_public_dict(),
        }
    except DerivativeEvidenceError as exc:
        session.log(
            f"源快照准入失败 DerivativeEvidenceError: {exc} "
            f"(run_id={session.run_id} kp_id={knowledge_point_id})"
        )
        raise DerivativeEvidenceError(
            str(exc),
            knowledge_point_id=exc.knowledge_point_id or knowledge_point_id,
            run_id=session.run_id,
        ) from exc
    except Exception as exc:
        session.log(f"运行中止 {type(exc).__name__}: {exc} (run_id={session.run_id})")
        raise


def generate_for_package(
    db: Session,
    package_id: int,
    *,
    derivative_types: Sequence[str] = DERIVATIVE_TYPES,
    target_audiences: Sequence[str] = ("student",),
    respect_flag: bool = True,
) -> Dict[str, Any]:
    """对专题包下的全部知识点批量生成。"""

    if respect_flag and not KNOWLEDGE_DERIVATIVE_ENABLED:
        return {
            "status": "skipped",
            "reason": "KNOWLEDGE_DERIVATIVE_ENABLED=false",
            "package_id": package_id,
            "generated": 0,
            "run": None,
        }

    package = (
        db.query(models.KnowledgePackage)
        .filter(models.KnowledgePackage.id == package_id)
        .first()
    )
    if not package:
        raise ValueError(f"KnowledgePackage {package_id} 不存在")

    point_ids = [
        pid
        for (pid,) in db.query(models.KnowledgePackagePoint.knowledge_point_id)
        .filter(models.KnowledgePackagePoint.package_id == package_id)
        .distinct()
        .all()
    ]
    if not point_ids:
        return {
            "status": "skipped",
            "reason": "该专题包没有关联知识点",
            "package_id": package_id,
            "generated": 0,
            "run": None,
        }

    valid_types_pkg = [t for t in derivative_types if t in DERIVATIVE_TYPES]
    valid_audiences_pkg = [a for a in target_audiences if a in TARGET_AUDIENCES]
    if not valid_types_pkg or not valid_audiences_pkg:
        raise ValueError("derivative_types / target_audiences 为空或全部不合法")

    session = DerivativeRunSession(
        mode="package",
        knowledge_point_id=None,
        package_id=package_id,
    )
    session.log(
        f"包级批量开始 package_id={package_id} point_ids={point_ids} "
        f"types={valid_types_pkg} audiences={valid_audiences_pkg}"
    )

    all_generated: List[Dict[str, Any]] = []
    total_errors: List[Dict[str, Any]] = []
    for pid in point_ids:
        session.log(f"\n######## 知识点 kp_id={pid} ########")
        try:
            snapshot = build_source_snapshot(db, pid)
        except DerivativeEvidenceError as exc:
            session.log(f"跳过 kp={pid}（无溯源语料）：{exc}")
            total_errors.append(
                {
                    "knowledge_point_id": pid,
                    "error": str(exc),
                    "stage": "source_snapshot",
                }
            )
            continue
        session.log_snapshot_brief(snapshot)
        g, e = _execute_derivative_generations(
            db,
            knowledge_point_id=pid,
            snapshot=snapshot,
            valid_types=valid_types_pkg,
            valid_audiences=valid_audiences_pkg,
            session=session,
        )
        all_generated.extend(g)
        total_errors.extend(e)

    session.log(
        f"包级批量结束 package_id={package_id} generated={len(all_generated)} errors={len(total_errors)}"
    )
    return {
        "status": "ok" if not total_errors else "partial",
        "package_id": package_id,
        "point_count": len(point_ids),
        "generated": len(all_generated),
        "generated_items": all_generated,
        "errors": total_errors,
        "run": session.to_public_dict(),
    }


# =============================================================================
# 审核 & 检索联动
# =============================================================================


def _serialize_derivative_text(
    record: models.KnowledgeDerivative,
    point: models.KnowledgePoint,
) -> str:
    content = record.generated_content or {}
    parts = [
        f"知识点：{point.canonical_name}",
        f"衍生类型：{record.derivative_type}（受众：{record.target_audience}）",
    ]
    if content.get("title"):
        parts.append(f"标题：{content['title']}")
    if content.get("summary"):
        parts.append(f"摘要：{content['summary']}")
    bullets = content.get("bullets") or []
    if bullets:
        parts.append("要点：" + "；".join(str(item) for item in bullets))
    if content.get("body"):
        parts.append(f"正文：{content['body']}")
    return "\n".join(parts).strip()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _remove_derivative_retrieval(db: Session, derivative_id: int) -> int:
    documents = (
        db.query(models.RetrievalDocument)
        .filter(
            models.RetrievalDocument.entity_type == "knowledge_derivative",
            models.RetrievalDocument.entity_id == derivative_id,
        )
        .all()
    )
    if not documents:
        return 0
    doc_ids = [d.id for d in documents]
    embedding_points = (
        db.query(models.EmbeddingPoint)
        .filter(models.EmbeddingPoint.retrieval_document_id.in_(doc_ids))
        .all()
    )
    vector_ids = [ep.point_id for ep in embedding_points if ep.point_id]
    if not vector_ids:
        vector_ids = [
            str((doc.metadata_json or {}).get("vector_id") or "")
            for doc in documents
            if (doc.metadata_json or {}).get("vector_id")
        ]
    if vector_ids:
        try:
            vector_db.db.delete_documents(vector_ids)
        except Exception:
            logger.exception("Remove vector points for derivative %s failed", derivative_id)
    db.query(models.EmbeddingPoint).filter(
        models.EmbeddingPoint.retrieval_document_id.in_(doc_ids)
    ).delete(synchronize_session=False)
    db.query(models.RetrievalDocument).filter(
        models.RetrievalDocument.id.in_(doc_ids)
    ).delete(synchronize_session=False)
    db.flush()
    return len(doc_ids)


def _sync_derivative_retrieval(db: Session, derivative_id: int) -> Dict[str, Any]:
    if not KNOWLEDGE_RAG_ENABLED:
        return {"status": "skipped", "reason": "KNOWLEDGE_RAG_ENABLED=false"}

    record = (
        db.query(models.KnowledgeDerivative)
        .filter(models.KnowledgeDerivative.id == derivative_id)
        .first()
    )
    if not record:
        return {"status": "error", "reason": "derivative not found"}
    if (record.review_status or "").lower() != "approved":
        return {"status": "skipped", "reason": "review_status != approved"}

    point = (
        db.query(models.KnowledgePoint)
        .filter(models.KnowledgePoint.id == record.knowledge_point_id)
        .first()
    )
    if not point:
        return {"status": "error", "reason": "knowledge point not found"}

    _remove_derivative_retrieval(db, derivative_id)

    text = _serialize_derivative_text(record, point)
    content_hash = _hash_text(text)
    logical_key = f"knowledge_derivative:{derivative_id}:{content_hash}"
    vector_id = str(uuid.uuid5(_DERIVATIVE_QDRANT_NS, logical_key))
    metadata = {
        "source": f"knowledge_derivative:{derivative_id}",
        "knowledge_point_id": point.id,
        "knowledge_point_name": point.canonical_name,
        "subject": point.subject,
        "grade": point.grade_scope,
        "derivative_type": record.derivative_type,
        "target_audience": record.target_audience,
        "view_type": "kp_derivative",
        "title": (record.generated_content or {}).get("title") or point.canonical_name,
        "review_status": record.review_status,
        "vector_id": vector_id,
        "logical_key": logical_key,
    }
    doc = models.RetrievalDocument(
        tenant_id=point.tenant_id,
        entity_type="knowledge_derivative",
        entity_id=derivative_id,
        text_for_bm25=text,
        text_for_embedding=text,
        metadata_json=metadata,
        is_active=True,
        content_hash=content_hash,
    )
    db.add(doc)
    db.flush()

    try:
        sync_result = vector_db.db.upsert_retrieval_documents(
            [{"document": text, "metadata": metadata, "id": vector_id}]
        )
        db.add(
            models.EmbeddingPoint(
                retrieval_document_id=doc.id,
                backend_type=sync_result["vector_backend"],
                point_id=vector_id,
                model_name=sync_result["embedding_model"],
                vector_dim=sync_result["vector_dim"],
                content_hash=content_hash,
            )
        )
        db.commit()
        return {
            "status": "ok",
            "derivative_id": derivative_id,
            "retrieval_document_id": doc.id,
            **sync_result,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Sync derivative retrieval failed: derivative_id=%s", derivative_id)
        return {"status": "error", "reason": str(exc)}


def set_review_status(
    db: Session,
    derivative_id: int,
    status: str,
) -> Dict[str, Any]:
    status = (status or "").strip().lower()
    if status not in REVIEW_STATUSES:
        raise ValueError(f"review_status 必须是 {REVIEW_STATUSES} 之一")

    record = (
        db.query(models.KnowledgeDerivative)
        .filter(models.KnowledgeDerivative.id == derivative_id)
        .first()
    )
    if not record:
        raise ValueError(f"KnowledgeDerivative {derivative_id} 不存在")

    prev_status = (record.review_status or "").lower()
    record.review_status = status
    db.commit()

    if status == "approved":
        sync_result = _sync_derivative_retrieval(db, derivative_id)
    else:
        removed = _remove_derivative_retrieval(db, derivative_id)
        db.commit()
        sync_result = {"status": "ok", "removed_documents": removed}

    return {
        "status": "ok",
        "derivative_id": derivative_id,
        "previous_status": prev_status,
        "current_status": status,
        "retrieval_sync": sync_result,
    }


# =============================================================================
# 查询
# =============================================================================


def _serialize_derivative(record: models.KnowledgeDerivative) -> Dict[str, Any]:
    content = record.generated_content or {}
    return {
        "id": record.id,
        "knowledge_point_id": record.knowledge_point_id,
        "derivative_type": record.derivative_type,
        "target_audience": record.target_audience,
        "prompt_version": record.prompt_version,
        "review_status": record.review_status,
        "title": content.get("title"),
        "summary": content.get("summary"),
        "bullets": content.get("bullets") or [],
        "body": content.get("body"),
        "quality": content.get("quality") or {},
        "notes": content.get("notes"),
        "updated_at": record.updated_at.isoformat() if getattr(record, "updated_at", None) else None,
    }


def list_derivatives(
    db: Session,
    *,
    knowledge_point_id: Optional[int] = None,
    package_id: Optional[int] = None,
    review_status: Optional[str] = None,
    derivative_type: Optional[str] = None,
    target_audience: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    query = db.query(models.KnowledgeDerivative)
    if knowledge_point_id is not None:
        query = query.filter(models.KnowledgeDerivative.knowledge_point_id == knowledge_point_id)
    if package_id is not None:
        point_ids = [
            pid
            for (pid,) in db.query(models.KnowledgePackagePoint.knowledge_point_id)
            .filter(models.KnowledgePackagePoint.package_id == package_id)
            .distinct()
            .all()
        ]
        if not point_ids:
            return {"total": 0, "items": []}
        query = query.filter(models.KnowledgeDerivative.knowledge_point_id.in_(point_ids))
    if review_status:
        query = query.filter(models.KnowledgeDerivative.review_status == review_status.strip().lower())
    if derivative_type:
        query = query.filter(models.KnowledgeDerivative.derivative_type == derivative_type.strip())
    if target_audience:
        query = query.filter(models.KnowledgeDerivative.target_audience == target_audience.strip())

    total = query.count()
    rows = (
        query.order_by(models.KnowledgeDerivative.id.desc())
        .offset(max(0, int(offset)))
        .limit(max(1, min(int(limit), 500)))
        .all()
    )
    return {
        "total": int(total),
        "items": [_serialize_derivative(r) for r in rows],
    }


def count_derivatives(db: Session) -> Dict[str, Any]:
    from sqlalchemy import func

    rows = (
        db.query(
            models.KnowledgeDerivative.review_status,
            models.KnowledgeDerivative.derivative_type,
            func.count(models.KnowledgeDerivative.id),
        )
        .group_by(
            models.KnowledgeDerivative.review_status,
            models.KnowledgeDerivative.derivative_type,
        )
        .all()
    )
    groups = [
        {
            "review_status": status,
            "derivative_type": dtype,
            "count": int(cnt),
        }
        for status, dtype, cnt in rows
    ]
    total = sum(item["count"] for item in groups)
    return {"total": total, "groups": groups}


__all__ = [
    "DERIVATIVE_TYPES",
    "TARGET_AUDIENCES",
    "REVIEW_STATUSES",
    "build_source_snapshot",
    "generate_for_point",
    "generate_for_package",
    "set_review_status",
    "list_derivatives",
    "count_derivatives",
]
