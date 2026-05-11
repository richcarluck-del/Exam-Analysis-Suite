from __future__ import annotations

import asyncio
import hashlib
import json

import logging
import mimetypes
import os
import shutil
import sys
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4


from fastapi import APIRouter, Body, Depends, HTTPException, Query, WebSocket
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload



project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from analyzer.app import crud, question_bank_views, schemas

from analyzer.app.config import QUESTION_BANK_UPLOAD_DIR
from analyzer.app.exam_session_importer import ExamSessionBundleImportService
from analyzer.app.knowledge_graph_projection import project_package

from analyzer.app.question_matcher import ExamSessionMatchingService
from analyzer.app.question_bank_parser import QuestionBankIngestionService
from shared import models
from shared.database import SessionLocal as MainSessionLocal

router = APIRouter(tags=["content-ingestion-admin"])
logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt"}
DEFAULT_TITLE = "2008年高考数学试卷（理）（全国卷Ⅰ）（解析卷）"

RUN_SCOPE_STEPS = {"documents": ["0", "1", "2"], "bundle": ["3", "4"], "full": ["0", "1", "2", "3", "4"]}
PIPELINE_STEPS = [
    {"id": 0, "key": "0", "name": "resolve_source", "label": "内容源选择", "description": "选择已有内容源"},
    {"id": 1, "key": "1", "name": "register_documents", "label": "批量文档登记", "description": "扫描目录并登记题库文档"},
    {"id": 2, "key": "2", "name": "ingest_documents", "label": "批量题库摄入", "description": "对已登记文档批量切题并建索引"},
    {"id": 3, "key": "3", "name": "import_bundle", "label": "Bundle 导入", "description": "导入 preprocessor 导出的分析包"},
    {"id": 4, "key": "4", "name": "match_exam_session", "label": "试卷匹配", "description": "将导入题目与题库进行匹配"},
]
STEP_FILE_MAP = {"0": "00_prepare_source.json", "1": "01_register_document.json", "2": "02_ingest_document.json", "3": "03_import_bundle.json", "4": "04_match_exam_session.json"}
MOCK_DATA_DIR = Path(project_root) / "analyzer" / "tests" / "mock_data"


def get_main_db():
    db = MainSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any, default: float) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _normalize_run_scope(value: Any) -> str:
    scope = _clean_text(value) or "full"
    return scope if scope in RUN_SCOPE_STEPS else "full"


def _serialize_source(source: models.ContentSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "source_name": source.source_name,
        "source_type": source.source_type,
        "provider_name": source.provider_name,
        "tenant_id": source.tenant_id,
        "commercial_allowed": bool(source.commercial_allowed),
        "ai_processing_allowed": bool(source.ai_processing_allowed),
        "training_allowed": bool(source.training_allowed),
        "remark": source.remark,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


def _serialize_document(document: models.SourceDocument) -> dict[str, Any]:
    source = document.content_source
    return {
        "id": document.id,
        "source_id": document.source_id,
        "source_name": source.source_name if source else None,
        "file_name": document.file_name,
        "file_ext": document.file_ext,
        "mime_type": document.mime_type,
        "storage_url": document.storage_url,
        "parse_profile": document.parse_profile,
        "subject": document.subject,
        "grade": document.grade,
        "year": document.year,
        "region": document.region,
        "title": document.title,
        "visibility_scope": document.visibility_scope,
        "parse_status": document.parse_status,
        "normalized_docx_url": document.normalized_docx_url,
        "normalized_pdf_url": document.normalized_pdf_url,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "parse_jobs": [
            {
                "id": job.id,
                "job_stage": job.job_stage,
                "tool_name": job.tool_name,
                "model_name": job.model_name,
                "status": job.status,
                "metrics_json": job.metrics_json,
                "error_message": job.error_message,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "ended_at": job.ended_at.isoformat() if job.ended_at else None,
            }
            for job in (document.parse_jobs or [])
        ],
    }


def _serialize_exam_session(session: models.ExamSession) -> dict[str, Any]:
    return {
        "id": session.id,
        "student_id": session.student_id,
        "source_document_id": session.source_document_id,
        "matched_paper_id": session.matched_paper_id,
        "exam_date": session.exam_date.isoformat() if session.exam_date else None,
        "subject": session.subject,
        "parse_status": session.parse_status,
        "matching_status": session.matching_status,
        "analysis_status": session.analysis_status,
        "visibility_scope": session.visibility_scope,
        "question_count": len(session.questions or []),
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


def _get_case_step_keys(case_path: Path) -> list[str]:
    return [step_key for step_key, filename in STEP_FILE_MAP.items() if (case_path / filename).exists()]


def _list_mock_cases() -> list[dict[str, Any]]:
    if not MOCK_DATA_DIR.exists():
        return []
    rows = []
    for case_path in MOCK_DATA_DIR.iterdir():
        if not case_path.is_dir():
            continue
        stat = case_path.stat()
        rows.append({
            "name": case_path.name,
            "created_at": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "created_at_ts": stat.st_ctime,
            "available_step_keys": _get_case_step_keys(case_path),
            "available_step_count": len(_get_case_step_keys(case_path)),
        })
    rows.sort(key=lambda item: item["created_at_ts"], reverse=True)
    for row in rows:
        row.pop("created_at_ts", None)
    return rows


def _resolve_mock_case_dir(case_name: str) -> Path:
    case_dir = MOCK_DATA_DIR / case_name
    if not case_dir.exists() or not case_dir.is_dir():
        raise FileNotFoundError(f"Mock case 不存在: {case_name}")
    return case_dir


def _load_step_record(case_dir: Path, step_key: str) -> Optional[dict[str, Any]]:
    step_file = case_dir / STEP_FILE_MAP[step_key]
    if not step_file.exists():
        return None
    return json.loads(step_file.read_text(encoding="utf-8"))


def _record_step(case_dir: Path, step_key: str, input_payload: dict[str, Any], result: dict[str, Any], context: dict[str, Any]) -> None:
    _write_json(case_dir / STEP_FILE_MAP[step_key], {"step_key": step_key, "recorded_at": datetime.now().isoformat(), "input": input_payload, "result": result, "context": context})


def _is_supported_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _calculate_sha256(path: Path) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _scan_paths(target_value: str) -> list[Path]:
    target = Path(target_value).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"文档路径不存在: {target}")
    if target.is_file():
        if not _is_supported_file(target):
            raise ValueError(f"不支持的文件类型: {target.suffix}")
        return [target]
    if not target.is_dir():
        raise ValueError(f"题库文档路径必须是文件或目录: {target}")
    files = sorted([item.resolve() for item in target.rglob("*") if _is_supported_file(item)], key=lambda item: str(item).lower())
    if not files:
        raise ValueError(f"目录下未找到可摄入文档: {target}。仅支持 {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    return files


def _serialize_scan_file(path: Path) -> dict[str, Any]:
    return {"path": str(path), "file_name": path.name, "file_ext": path.suffix.lower(), "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream", "size_bytes": path.stat().st_size}


def _copy_to_uploads(source_path: Path, source_id: int) -> tuple[str, str, str, str]:
    upload_dir = Path(QUESTION_BANK_UPLOAD_DIR) / f"source_{source_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix or ".txt"
    target = upload_dir / f"{source_path.stem}_{uuid4().hex}{suffix}"
    shutil.copy2(source_path, target)
    return str(target), _calculate_sha256(target), source_path.name, mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"


def _resolve_title(base_title: Optional[str], source_path: Path, batch_count: int) -> str:
    title = _clean_text(base_title) or DEFAULT_TITLE
    return title if batch_count <= 1 else f"{title} - {source_path.stem}"


def _get_selected_steps(config: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = set(RUN_SCOPE_STEPS[_normalize_run_scope(config.get("run_scope"))])
    return [step for step in PIPELINE_STEPS if step["key"] in allowed]


def _compute_mock_real_steps(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    run_scope = _normalize_run_scope(config.get("run_scope"))
    allowed = set(RUN_SCOPE_STEPS[run_scope])
    requested = {str(item).strip() for item in (config.get("real_steps") or []) if str(item).strip() in allowed}
    link_source_document = _normalize_bool(config.get("link_source_document"), default=False)
    bundle_source_document_id = _safe_int(config.get("bundle_source_document_id"))
    dependencies = {"0": set(), "1": {"0"}, "2": {"1"}, "3": {"2"} if run_scope == "full" and link_source_document and not bundle_source_document_id else set(), "4": {"3"}}
    effective = set(requested)
    changed = True
    while changed:
        changed = False
        for step_key in list(effective):
            missing = (dependencies.get(step_key, set()) & allowed) - effective
            if missing:
                effective.update(missing)
                changed = True
    ordered = [step["key"] for step in PIPELINE_STEPS if step["key"] in effective and step["key"] in allowed]
    promoted = [step_key for step_key in ordered if step_key not in requested]
    return ordered, promoted


def _preview_json(payload: Any, limit: int = 2000) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=_json_default) if not isinstance(payload, str) else payload
    return text if len(text) <= limit else f"{text[:limit]}...(truncated)"


def _format_duration(seconds: float) -> str:
    return f"{seconds:.2f}s"


def _describe_libreoffice_plan(file_ext: Optional[str]) -> str:
    normalized = (file_ext or "").strip().lower()
    if normalized and not normalized.startswith("."):
        normalized = f".{normalized}"
    if normalized == ".doc":
        return "将调用 LibreOffice 转 docx，并尝试额外转 pdf"
    if normalized == ".docx":
        return "不会转 docx；会尝试调用 LibreOffice 额外转 pdf"
    if normalized == ".pdf":
        return "不会调用 LibreOffice，直接按 pdf 处理"
    if normalized == ".txt":
        return "不会调用 LibreOffice，直接按 txt 处理"
    return "未识别文件类型，是否调用 LibreOffice 取决于后续归一化逻辑"


def _summarize_runtime_context(runtime_context: dict[str, Any]) -> str:
    important_keys = [
        "source_id",
        "source_document_ids",
        "source_document_id",
        "ingested_document_ids",
        "exam_session_id",
        "linked_source_document_id",
    ]
    summary = {
        key: runtime_context.get(key)
        for key in important_keys
        if runtime_context.get(key) not in (None, "", [], {})
    }
    return _preview_json(summary or {}, limit=800)


def _parse_exam_date(value: Any) -> Optional[date]:

    text = _clean_text(value)
    return date.fromisoformat(text[:10]) if text else None


def _execute_select_source(db: Session, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_id = _safe_int(config.get("existing_source_id"))
    if not source_id:
        raise ValueError("请选择内容源")
    source = crud.get_content_source(db, source_id)
    if not source:
        raise ValueError(f"ContentSource {source_id} 不存在")
    return _serialize_source(source), {"source_id": source.id}


def _find_existing_document(db: Session, source_id: int, file_sha256: str) -> Optional[models.SourceDocument]:
    return db.query(models.SourceDocument).filter(models.SourceDocument.source_id == source_id).filter(models.SourceDocument.file_sha256 == file_sha256).order_by(models.SourceDocument.id.desc()).first()


def _execute_register_documents(db: Session, config: dict[str, Any], runtime_context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_id = runtime_context.get("source_id") or _safe_int(config.get("existing_source_id"))
    if not source_id:
        raise ValueError("登记文档前必须先选择内容源")
    document_path = _clean_text(config.get("document_path"))
    if not document_path:
        raise ValueError("请提供题库文档目录")
    files = _scan_paths(document_path)
    documents: list[models.SourceDocument] = []
    created_count = 0
    reused_count = 0
    for file_path in files:
        file_sha256 = _calculate_sha256(file_path)
        existing = _find_existing_document(db, source_id, file_sha256)
        if existing:
            existing.parse_profile = _clean_text(config.get("parse_profile")) or "default"
            existing.subject = _clean_text(config.get("subject")) or "数学"
            existing.grade = _clean_text(config.get("grade")) or "3年级"
            existing.year = _safe_int(config.get("year")) or 2008
            existing.region = _clean_text(config.get("region")) or "全国"
            existing.title = _resolve_title(_clean_text(config.get("title")), file_path, len(files))
            existing.visibility_scope = _clean_text(config.get("document_visibility_scope")) or "public"
            db.commit()
            db.refresh(existing)
            documents.append(crud.get_source_document(db, existing.id) or existing)
            reused_count += 1
            continue
        storage_url, copied_sha256, file_name, mime_type = _copy_to_uploads(file_path, source_id)
        payload = schemas.SourceDocumentCreate(source_id=source_id, tenant_id=_safe_int(config.get("tenant_id")), file_name=file_name, file_ext=file_path.suffix.lstrip("."), mime_type=mime_type, storage_url=storage_url, file_sha256=copied_sha256, parse_profile=_clean_text(config.get("parse_profile")) or "default", subject=_clean_text(config.get("subject")) or "数学", grade=_clean_text(config.get("grade")) or "3年级", year=_safe_int(config.get("year")) or 2008, region=_clean_text(config.get("region")) or "全国", title=_resolve_title(_clean_text(config.get("title")), file_path, len(files)), visibility_scope=_clean_text(config.get("document_visibility_scope")) or "public")

        document = crud.create_source_document(db, payload)
        documents.append(crud.get_source_document(db, document.id) or document)
        created_count += 1
    document_ids = [item.id for item in documents]
    return {"summary": {"scanned_count": len(files), "created_count": created_count, "reused_count": reused_count, "document_count": len(documents)}, "documents": [_serialize_document(item) for item in documents], "scanned_files": [_serialize_scan_file(item) for item in files]}, {"source_document_ids": document_ids, "source_document_id": document_ids[0] if len(document_ids) == 1 else None}


async def _execute_ingest_documents(
    db: Session,
    config: dict[str, Any],
    runtime_context: dict[str, Any],
    emit_progress: Optional[Callable[[str], Awaitable[None]]] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_document_ids = [int(item) for item in (runtime_context.get("source_document_ids") or []) if item]
    if not source_document_ids:
        raise ValueError("题库摄入前没有可用文档，请先执行批量文档登记")

    force_reingest = _normalize_bool(config.get("force_reingest"))
    rows = []
    available_ids: list[int] = []
    stats = {"requested_count": len(source_document_ids), "success_count": 0, "skipped_count": 0, "failed_count": 0}
    sync_emit_progress: Optional[Callable[[str], None]] = None

    if emit_progress:
        await emit_progress(f"[STEP-2] 批量题库摄入准备开始：文档数={len(source_document_ids)}，force_reingest={force_reingest}")
        loop = asyncio.get_running_loop()

        def sync_emit_progress(message: str) -> None:
            try:
                future = asyncio.run_coroutine_threadsafe(emit_progress(message), loop)
                future.result()
            except Exception:
                pass

    for index, source_document_id in enumerate(source_document_ids, start=1):
        db.expire_all()
        document_before = crud.get_source_document(db, source_document_id)
        if emit_progress:
            if document_before:
                await emit_progress(
                    f"[STEP-2] 文档 {index}/{len(source_document_ids)} 开始摄入："
                    f"id={source_document_id}，file={document_before.file_name}，ext={document_before.file_ext}，"
                    f"当前 parse_status={document_before.parse_status}，LibreOffice策略={_describe_libreoffice_plan(document_before.file_ext)}"
                )
            else:
                await emit_progress(f"[STEP-2] 文档 {index}/{len(source_document_ids)} 开始摄入：id={source_document_id}，数据库记录不存在")

        started_at = time.perf_counter()
        result = await asyncio.to_thread(_ingest_source_document_in_worker, source_document_id, force_reingest, sync_emit_progress)
        elapsed = time.perf_counter() - started_at
        db.expire_all()
        document = crud.get_source_document(db, source_document_id)
        status = result.get("status")
        if status == "success":
            stats["success_count"] += 1
            available_ids.append(source_document_id)
        elif status == "skipped":
            stats["skipped_count"] += 1
            available_ids.append(source_document_id)
        else:
            stats["failed_count"] += 1

        logger.info(
            "Content ingestion document finished: index=%s/%s source_document_id=%s status=%s elapsed=%s result=%s",
            index,
            len(source_document_ids),
            source_document_id,
            status,
            _format_duration(elapsed),
            _preview_json(result, limit=1000),
        )
        if emit_progress:
            await emit_progress(
                f"[STEP-2] 文档 {index}/{len(source_document_ids)} 摄入结束："
                f"id={source_document_id}，status={status}，耗时={_format_duration(elapsed)}，"
                f"question_count={result.get('question_count')}，error={result.get('error')}"
            )

        rows.append({"source_document_id": source_document_id, "status": status, "result": result, "document": _serialize_document(document) if document else None})

    return {"summary": stats, "documents": rows}, {"ingested_document_ids": available_ids, "source_document_id": available_ids[0] if len(available_ids) == 1 else None}





def _build_bundle_input(config: dict[str, Any], runtime_context: dict[str, Any]) -> dict[str, Any]:
    link_source_document = _normalize_bool(config.get("link_source_document"), default=False)
    configured_document_id = _safe_int(config.get("bundle_source_document_id"))
    runtime_document_id = runtime_context.get("source_document_id") if link_source_document else None
    source_document_id = configured_document_id or runtime_document_id if link_source_document else None
    return {
        "bundle_dir": _clean_text(config.get("bundle_dir")),
        "student_id": _safe_int(config.get("student_id")),
        "tenant_id": _safe_int(config.get("tenant_id")),
        "source_document_id": source_document_id,
        "subject": _clean_text(config.get("subject")) or "数学",
        "exam_date": _clean_text(config.get("exam_date")),
        "visibility_scope": _clean_text(config.get("exam_visibility_scope")) or "private",
        "link_source_document": link_source_document,
    }


def _execute_import_bundle(db: Session, config: dict[str, Any], runtime_context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    payload_data = _build_bundle_input(config, runtime_context)
    if not payload_data["bundle_dir"]:
        raise ValueError("请提供 bundle 目录")
    if not payload_data["student_id"]:
        raise ValueError("导入 bundle 时 student_id 不能为空")
    payload = schemas.ExamSessionBundleImportRequest(bundle_dir=payload_data["bundle_dir"], student_id=payload_data["student_id"], tenant_id=payload_data["tenant_id"], source_document_id=payload_data["source_document_id"], exam_date=_parse_exam_date(payload_data["exam_date"]), subject=payload_data["subject"], visibility_scope=payload_data["visibility_scope"], auto_match=False)
    service = ExamSessionBundleImportService()
    result = service.import_bundle(db, payload)
    exam_session = result.get("exam_session")
    return {"bundle_id": result.get("bundle_id"), "run_id": result.get("run_id"), "question_count": result.get("question_count"), "warnings": result.get("warnings") or [], "exam_session": _serialize_exam_session(exam_session) if exam_session else None}, {"exam_session_id": exam_session.id if exam_session else None, "linked_source_document_id": payload_data["source_document_id"]}


def _execute_match(db: Session, config: dict[str, Any], runtime_context: dict[str, Any]) -> dict[str, Any]:
    exam_session_id = runtime_context.get("exam_session_id") or _safe_int(config.get("exam_session_id"))
    if not exam_session_id:
        raise ValueError("试卷匹配前必须先导入 bundle")
    service = ExamSessionMatchingService()
    result = service.match_exam_session(db=db, exam_session_id=exam_session_id, top_k=_safe_int(config.get("match_top_k")) or 5, accept_threshold=_safe_float(config.get("match_accept_threshold"), 0.78), min_gap=_safe_float(config.get("match_min_gap"), 0.05))
    exam_session = crud.get_exam_session(db, exam_session_id)
    return {"match_result": result, "exam_session": _serialize_exam_session(exam_session) if exam_session else None, "matches": crud.build_exam_session_match_views(db, exam_session_id)}


def _build_overview(db: Session) -> dict[str, Any]:
    sources = crud.get_content_sources(db, limit=100)
    documents = crud.get_source_documents(db, limit=100)
    exam_sessions = crud.get_exam_sessions(db, limit=100)
    return {"counts": {"sources": db.query(models.ContentSource).count(), "documents": db.query(models.SourceDocument).count(), "exam_sessions": db.query(models.ExamSession).count(), "mock_cases": len(_list_mock_cases())}, "sources": [_serialize_source(item) for item in sources], "documents": [_serialize_document(item) for item in documents], "exam_sessions": [_serialize_exam_session(item) for item in exam_sessions], "mock_cases": _list_mock_cases(), "supported_extensions": sorted(SUPPORTED_EXTENSIONS)}


@router.get("/api/content-ingestion/pipeline-steps")
def get_pipeline_steps():
    return PIPELINE_STEPS


@router.get("/api/content-ingestion/overview")
def get_overview(db: Session = Depends(get_main_db)):
    return _build_overview(db)


@router.get("/api/content-management/documents")
def list_content_management_documents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1),
    db: Session = Depends(get_main_db),
):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    def _to_beijing_iso(value):
        if value is None:
            return None
        if getattr(value, "tzinfo", None) is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()

    normalized_page_size = page_size if page_size in {10, 20, 50, 100} else 20
    offset = (page - 1) * normalized_page_size

    total_documents = db.query(models.SourceDocument).count()
    total_sources = db.query(models.ContentSource).count()

    documents = (
        db.query(models.SourceDocument)
        .options(
            selectinload(models.SourceDocument.content_source),
            selectinload(models.SourceDocument.papers),
            selectinload(models.SourceDocument.parse_jobs),
        )
        .order_by(models.SourceDocument.id.desc())
        .offset(offset)
        .limit(normalized_page_size)
        .all()
    )

    items = []
    for document in documents:
        latest_paper = None
        if document.papers:
            latest_paper = max(
                document.papers,
                key=lambda paper: (
                    getattr(paper, "created_at", None) or datetime.min,
                    paper.id or 0,
                ),
            )

        latest_success_job = None
        successful_jobs = [job for job in (document.parse_jobs or []) if (job.status or "").lower() == "success"]
        if successful_jobs:
            latest_success_job = max(
                successful_jobs,
                key=lambda job: (
                    getattr(job, "ended_at", None) or getattr(job, "started_at", None) or datetime.min,
                    job.id or 0,
                ),
            )

        question_count = int(latest_paper.total_questions or 0) if latest_paper else 0
        source = document.content_source
        items.append(
            {
                "id": document.id,
                "paper_id": latest_paper.id if latest_paper else None,
                "package_id": latest_paper.knowledge_package_id if latest_paper else None,
                "source_id": document.source_id,
                "source_name": source.source_name if source else None,
                "file_name": document.file_name,
                "parse_status": document.parse_status,
                "title": document.title,
                "created_at": document.created_at.isoformat() if document.created_at else None,
                "last_ingested_at": _to_beijing_iso(
                    latest_success_job.ended_at if latest_success_job and latest_success_job.ended_at else (
                        latest_success_job.started_at if latest_success_job else None
                    )
                ),
                "question_count": question_count,
            }
        )

    return {
        "stats": {
            "sources": total_sources,
            "documents": total_documents,
        },
        "pagination": {
            "page": page,
            "page_size": normalized_page_size,
            "total": total_documents,
        },
        "items": items,
    }


@router.get("/api/question-bank/documents/{source_document_id}/paper")
def get_question_bank_document_paper(source_document_id: int, db: Session = Depends(get_main_db)):
    paper_detail = question_bank_views.get_source_document_paper_detail(db, source_document_id)
    if not paper_detail:
        raise HTTPException(status_code=404, detail="Paper not found for source document")
    return paper_detail


@router.delete("/api/question-bank/documents/{source_document_id}/questions/{question_item_id}")
def delete_question_bank_document_question(
    source_document_id: int,
    question_item_id: int,
    db: Session = Depends(get_main_db),
):
    document = crud.get_source_document(db, source_document_id)
    if not document:
        raise HTTPException(status_code=404, detail=f"SourceDocument {source_document_id} 不存在")

    service = QuestionBankIngestionService()
    try:
        result = service.delete_question_items(
            db,
            source_document_id=source_document_id,
            question_item_ids=[question_item_id],
        )
        if int(result.get("deleted_questions") or 0) <= 0:
            raise HTTPException(status_code=404, detail=f"QuestionItem {question_item_id} 不存在或不属于该文档")
        for package_id in result.get("package_ids") or []:
            project_package(db, int(package_id), respect_flag=False)
        db.commit()
        return result
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Delete question failed: source_document_id=%s question_item_id=%s",
            source_document_id,
            question_item_id,
        )
        raise HTTPException(status_code=500, detail=f"删除题目失败：{exc}") from exc



@router.get("/api/content-ingestion/mock-cases")
def get_mock_cases():
    return _list_mock_cases()



@router.post("/api/content-ingestion/scan-documents")
def scan_documents(payload: dict[str, Any] = Body(...)):
    directory_path = _clean_text(payload.get("directory_path")) or _clean_text(payload.get("document_path"))
    if not directory_path:
        raise HTTPException(status_code=400, detail="请提供 directory_path")
    try:
        files = _scan_paths(directory_path)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"directory_path": str(Path(directory_path).expanduser().resolve()), "count": len(files), "supported_extensions": sorted(SUPPORTED_EXTENSIONS), "files": [_serialize_scan_file(item) for item in files]}


@router.get("/api/content-sources")
def list_sources(db: Session = Depends(get_main_db)):
    return [_serialize_source(item) for item in crud.get_content_sources(db, limit=200)]


@router.post("/api/content-sources")
def create_source(payload: schemas.ContentSourceCreate, db: Session = Depends(get_main_db)):
    if payload.tenant_id is not None:
        tenant = db.query(models.Tenant).filter(models.Tenant.id == payload.tenant_id).first()
        if not tenant:
            raise HTTPException(status_code=400, detail=f"Tenant ID 不存在: {payload.tenant_id}。请留空，或填写 tenants 表中已存在的数字 ID。")

    try:
        return _serialize_source(crud.create_content_source(db, payload))
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="内容源创建失败：请检查 Tenant ID 是否有效，或将其留空。") from exc



@router.get("/api/content-sources/{source_id}/documents")
def list_source_documents(source_id: int, db: Session = Depends(get_main_db)):
    source = crud.get_content_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"ContentSource {source_id} 不存在")
    documents = db.query(models.SourceDocument).filter(models.SourceDocument.source_id == source_id).order_by(models.SourceDocument.id.desc()).limit(200).all()
    return {"source": _serialize_source(source), "documents": [_serialize_document(item) for item in documents]}


@router.delete("/api/content-sources/{source_id}/documents/{document_id}")
def delete_source_document(source_id: int, document_id: int, db: Session = Depends(get_main_db)):
    source = crud.get_content_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"ContentSource {source_id} 不存在")

    document = crud.get_source_document(db, document_id)
    if not document or document.source_id != source_id:
        raise HTTPException(status_code=404, detail=f"SourceDocument {document_id} 不存在或不属于内容源 {source_id}")

    service = QuestionBankIngestionService()
    try:
        return service.delete_source_document(db, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        logger.exception("Delete source document failed: source_id=%s document_id=%s", source_id, document_id)
        raise HTTPException(status_code=500, detail=f"删除文档失败：{exc}") from exc


async def _emit(websocket: WebSocket, all_logs: list[str], message: str) -> None:

    await websocket.send_text(message)
    all_logs.append(message)
    await asyncio.sleep(0)


def _run_db_step_in_worker(step_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    db = MainSessionLocal()
    try:
        return step_func(db, *args, **kwargs)
    finally:
        db.close()


async def _run_db_step(step_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(_run_db_step_in_worker, step_func, *args, **kwargs)


def _ingest_source_document_in_worker(
    source_document_id: int,
    force_reingest: bool,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    from analyzer.app.question_bank_parser import QuestionBankIngestionService

    db = MainSessionLocal()
    try:
        service = QuestionBankIngestionService()
        return service.ingest_source_document(

            db,
            source_document_id,
            force_reingest=force_reingest,
            progress_callback=progress_callback,
        )
    finally:
        db.close()



@router.websocket("/ws/run-content-ingestion")
async def websocket_run_content_ingestion(websocket: WebSocket):

    await websocket.accept()
    all_logs: list[str] = []
    db = MainSessionLocal()

    async def emit_progress(message: str) -> None:
        await _emit(websocket, all_logs, message)

    try:
        await emit_progress("[SYSTEM-DEBUG] WebSocket 已建立，等待前端发送配置。")
        config = await websocket.receive_json()
        test_mode = _clean_text(config.get("test_mode")) or "real"
        run_scope = _normalize_run_scope(config.get("run_scope"))
        selected_steps = _get_selected_steps(config)
        selected_step_keys = [step["key"] for step in selected_steps]
        selected_step_labels = [f"{step['key']}:{step['label']}" for step in selected_steps]
        logger.info(
            "Content ingestion websocket started: mode=%s run_scope=%s selected_steps=%s config=%s",
            test_mode,
            run_scope,
            selected_step_keys,
            _preview_json(config, limit=1500),
        )
        await emit_progress(f"[SYSTEM] 内容摄入测试初始化完成。运行范围：{run_scope}")
        await emit_progress(f"[SYSTEM] 收到测试配置：{_preview_json(config, limit=2000)}")
        await emit_progress(f"[SYSTEM-DEBUG] test_mode={test_mode}，selected_steps={selected_step_labels}")

        case_dir: Optional[Path] = None
        mock_case_dir: Optional[Path] = None
        case_name: Optional[str] = None
        if test_mode == "record":
            case_name = _clean_text(config.get("case_name")) or f"case_{int(datetime.now().timestamp())}"
            case_dir = MOCK_DATA_DIR / case_name
            case_dir.mkdir(parents=True, exist_ok=True)
            _write_json(case_dir / "manifest.json", {"module": "analyzer", "pipeline": "content_ingestion", "created_at": datetime.now().isoformat(), "config": config, "run_scope": run_scope, "pipeline_steps": selected_steps})
            await emit_progress(f"[SYSTEM] 当前为录制模式，输出目录：{case_dir}")

        elif test_mode == "mock":
            case_name = _clean_text(config.get("mock_case"))
            if not case_name:
                raise HTTPException(status_code=400, detail="Mock 模式下必须选择 mock_case")
            mock_case_dir = _resolve_mock_case_dir(case_name)
            await emit_progress(f"[SYSTEM] 当前为 Mock 模式，使用案例：{mock_case_dir}")

        effective_real_steps, promoted_steps = _compute_mock_real_steps(config) if test_mode == "mock" else ([step["key"] for step in selected_steps], [])
        await emit_progress(f"[SYSTEM-DEBUG] effective_real_steps={effective_real_steps}，promoted_steps={promoted_steps}")
        if test_mode == "mock":
            await emit_progress(f"[SYSTEM] Mock 模式真实执行步骤：{effective_real_steps or []}")
            if promoted_steps:
                await emit_progress(f"[SYSTEM] 因依赖关系自动补齐真实步骤：{promoted_steps}")
        runtime_context: dict[str, Any] = {}
        await emit_progress(f"[SYSTEM-DEBUG] 即将进入 pipeline 循环，共 {len(selected_steps)} 个步骤。")
        for step in selected_steps:
            step_key = step["key"]
            step_label = step["label"]
            run_real = test_mode in {"real", "record"} or step_key in effective_real_steps
            recorded_step = _load_step_record(mock_case_dir, step_key) if mock_case_dir else None
            step_started_at = time.perf_counter()
            await emit_progress(f"[STEP-{step_key}] 开始：{step_label}（{'真实执行' if run_real else 'Mock 回放'}）")
            await emit_progress(f"[STEP-{step_key}] 上下文快照（开始前）：{_summarize_runtime_context(runtime_context)}")

            if not run_real:
                if not recorded_step:
                    raise FileNotFoundError(f"Mock case 缺少步骤 {step_label} 的录制文件")
                input_payload = dict(recorded_step.get("input") or {})
                result = dict(recorded_step.get("result") or {})
                result.update({"mock_replayed": True, "mock_case": case_name})
                runtime_context.update(recorded_step.get("context") or {})
            elif step_key == "0":
                input_payload = {"existing_source_id": config.get("existing_source_id")}
                await emit_progress(f"[STEP-{step_key}] 输入摘要：{_preview_json(input_payload, limit=1000)}")
                result, context_patch = await _run_db_step(_execute_select_source, config)
                db.expire_all()
                runtime_context.update(context_patch)
            elif step_key == "1":
                input_payload = {"existing_source_id": config.get("existing_source_id"), "document_path": config.get("document_path"), "parse_profile": config.get("parse_profile"), "subject": config.get("subject"), "grade": config.get("grade"), "year": config.get("year"), "region": config.get("region"), "title": config.get("title"), "document_visibility_scope": config.get("document_visibility_scope"), "tenant_id": config.get("tenant_id")}
                await emit_progress(f"[STEP-{step_key}] 输入摘要：{_preview_json(input_payload, limit=1200)}")
                result, context_patch = await _run_db_step(_execute_register_documents, config, runtime_context)
                db.expire_all()
                runtime_context.update(context_patch)

            elif step_key == "2":
                input_payload = {"source_document_ids": runtime_context.get("source_document_ids") or [], "force_reingest": _normalize_bool(config.get("force_reingest"))}
                await emit_progress(f"[STEP-{step_key}] 输入摘要：{_preview_json(input_payload, limit=1200)}")
                result, context_patch = await _execute_ingest_documents(db, config, runtime_context, emit_progress=emit_progress)
                db.expire_all()
                runtime_context.update(context_patch)
            elif step_key == "3":
                input_payload = _build_bundle_input(config, runtime_context)
                await emit_progress(f"[STEP-{step_key}] 输入摘要：{_preview_json(input_payload, limit=1200)}")
                if input_payload.get("link_source_document") and not input_payload.get("source_document_id"):
                    await emit_progress("[SYSTEM] 当前 Bundle 未绑定具体题库文档，将继续导入并按题库整体进行匹配。")
                result, context_patch = await _run_db_step(_execute_import_bundle, config, runtime_context)
                db.expire_all()
                runtime_context.update(context_patch)
            elif step_key == "4":
                input_payload = {"exam_session_id": runtime_context.get("exam_session_id"), "match_top_k": config.get("match_top_k"), "match_accept_threshold": config.get("match_accept_threshold"), "match_min_gap": config.get("match_min_gap")}
                await emit_progress(f"[STEP-{step_key}] 输入摘要：{_preview_json(input_payload, limit=1200)}")
                result = await _run_db_step(_execute_match, config, runtime_context)
                db.expire_all()

            else:
                raise ValueError(f"未知步骤：{step_key}")
            summary = _preview_json(result, limit=2000) if isinstance(result, dict) else str(result)
            await emit_progress(f"[STEP-{step_key}] 完成：{summary}")
            await emit_progress(f"[STEP-{step_key}] 上下文快照（完成后）：{_summarize_runtime_context(runtime_context)}")
            await emit_progress(f"[STEP-{step_key}] 耗时：{_format_duration(time.perf_counter() - step_started_at)}")
            if case_dir is not None:
                _record_step(case_dir, step_key, input_payload, result, runtime_context)
        await emit_progress("[SYSTEM] 内容摄入测试已完成。")
        if case_dir is not None:
            log_file_path = case_dir / "run_log.txt"
            log_file_path.write_text("\n".join(all_logs), encoding="utf-8")
            manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8")) if (case_dir / "manifest.json").exists() else {}
            manifest.update({"completed_at": datetime.now().isoformat(), "runtime_context": runtime_context, "available_step_keys": _get_case_step_keys(case_dir)})
            _write_json(case_dir / "manifest.json", manifest)
            await emit_progress(f"[SYSTEM] 日志已保存到：{log_file_path}")
    except Exception as exc:
        logger.exception("Content ingestion websocket failed")
        await emit_progress(f"[SYSTEM-ERROR] {exc.__class__.__name__}: {exc}")
    finally:
        logger.info("Content ingestion websocket closing")
        db.close()
        await websocket.close()
