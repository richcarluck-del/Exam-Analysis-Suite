from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from sqlalchemy.orm import Session

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from analyzer.app import crud, schemas
from analyzer.app.config import QUESTION_BANK_UPLOAD_DIR
from analyzer.app.exam_session_importer import BundleImportError, ExamSessionBundleImportService
from analyzer.app.question_bank_parser import QuestionBankIngestionService
from analyzer.app.question_matcher import ExamSessionMatchingService
from shared import models
from shared.database import SessionLocal as MainSessionLocal

router = APIRouter(tags=["content-ingestion-test"])

CONTENT_INGESTION_PIPELINE_STEPS = [
    {"id": 0, "key": "0", "name": "prepare_source", "label": "内容源准备", "description": "创建或选择题库内容源"},
    {"id": 1, "key": "1", "name": "register_document", "label": "文档登记", "description": "根据本地路径登记题库文档"},
    {"id": 2, "key": "2", "name": "ingest_document", "label": "题库摄入", "description": "切题、建索引并生成题库资产"},
    {"id": 3, "key": "3", "name": "import_bundle", "label": "Bundle 导入", "description": "导入 preprocessor 导出的分析包"},
    {"id": 4, "key": "4", "name": "match_exam_session", "label": "试卷匹配", "description": "将导入题目与题库进行匹配"},
]

STEP_FILE_MAP = {
    "0": "00_prepare_source.json",
    "1": "01_register_document.json",
    "2": "02_ingest_document.json",
    "3": "03_import_bundle.json",
    "4": "04_match_exam_session.json",
}

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



def _normalize_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)



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



def _serialize_content_source(source: models.ContentSource) -> dict[str, Any]:
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



def _serialize_parse_job(job: models.DocumentParseJob) -> dict[str, Any]:
    return {
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



def _serialize_source_document(document: models.SourceDocument) -> dict[str, Any]:
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
        "parse_jobs": [_serialize_parse_job(job) for job in (document.parse_jobs or [])],
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



def _get_available_step_keys(case_path: Path) -> list[str]:
    return [step_key for step_key, filename in STEP_FILE_MAP.items() if (case_path / filename).exists()]



def _list_mock_cases() -> list[dict[str, Any]]:
    if not MOCK_DATA_DIR.exists():
        return []

    cases = []
    for case_path in MOCK_DATA_DIR.iterdir():
        if not case_path.is_dir():
            continue
        stat = case_path.stat()
        cases.append(
            {
                "name": case_path.name,
                "created_at": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
                "created_at_ts": stat.st_ctime,
                "available_step_keys": _get_available_step_keys(case_path),
                "available_step_count": len(_get_available_step_keys(case_path)),
            }
        )

    cases.sort(key=lambda item: item["created_at_ts"], reverse=True)
    for case in cases:
        case.pop("created_at_ts", None)
    return cases



def _load_step_record(case_dir: Path, step_key: str) -> Optional[dict[str, Any]]:
    step_file = case_dir / STEP_FILE_MAP[step_key]
    if not step_file.exists():
        return None
    return json.loads(step_file.read_text(encoding="utf-8"))



def _resolve_mock_case_dir(case_name: str) -> Path:
    case_dir = MOCK_DATA_DIR / case_name
    if not case_dir.exists() or not case_dir.is_dir():
        raise FileNotFoundError(f"Mock case 不存在: {case_name}")
    return case_dir



def _copy_document_to_uploads(source_path: str, source_id: int) -> tuple[str, str, str, str]:
    source = Path(source_path).expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"文档路径不存在: {source}")

    upload_dir = Path(QUESTION_BANK_UPLOAD_DIR) / f"source_{source_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = source.suffix or ".txt"
    target = upload_dir / f"{source.stem}_{uuid4().hex}{suffix}"
    shutil.copy2(source, target)

    sha256 = hashlib.sha256()
    with target.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            sha256.update(chunk)

    mime_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    return str(target), sha256.hexdigest(), target.name, mime_type



def _record_step(case_dir: Path, step_key: str, input_payload: dict[str, Any], result: dict[str, Any], context: dict[str, Any]) -> None:
    _write_json(
        case_dir / STEP_FILE_MAP[step_key],
        {
            "step_key": step_key,
            "recorded_at": datetime.now().isoformat(),
            "input": input_payload,
            "result": result,
            "context": context,
        },
    )



def _load_case_manifest(case_dir: Path) -> dict[str, Any]:
    manifest_path = case_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {}



def _normalize_requested_real_steps(requested_steps: Any) -> set[str]:
    normalized = set()
    for value in requested_steps or []:
        key = str(value).strip()
        if key in STEP_FILE_MAP:
            normalized.add(key)
    return normalized



def _compute_effective_real_steps(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    requested = _normalize_requested_real_steps(config.get("real_steps"))
    link_source_document = _normalize_bool(config.get("link_source_document"), default=True)

    dependencies = {
        "0": set(),
        "1": {"0"},
        "2": {"1"},
        "3": {"1"} if link_source_document else set(),
        "4": {"2", "3"},
    }

    effective = set(requested)
    changed = True
    while changed:
        changed = False
        snapshot = set(effective)
        for step_key in snapshot:
            required_steps = dependencies.get(step_key, set())
            missing = required_steps - effective
            if missing:
                effective.update(missing)
                changed = True

    ordered = [step["key"] for step in CONTENT_INGESTION_PIPELINE_STEPS if step["key"] in effective]
    promoted = [step for step in ordered if step not in requested]
    return ordered, promoted



def _parse_exam_date(value: Any) -> Optional[date]:
    text = _clean_text(value)
    if not text:
        return None
    return date.fromisoformat(text[:10])



def _build_source_input(config: dict[str, Any], recorded_input: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = recorded_input or {}
    return {
        "source_mode": _clean_text(config.get("source_mode")) or base.get("source_mode") or "new",
        "existing_source_id": _safe_int(config.get("existing_source_id")) or _safe_int(base.get("existing_source_id")),
        "tenant_id": _safe_int(config.get("tenant_id")) or _safe_int(base.get("tenant_id")),
        "source_name": _clean_text(config.get("source_name")) or base.get("source_name") or "内容摄入测试源",
        "source_type": _clean_text(config.get("source_type")) or base.get("source_type") or "question_bank",
        "provider_name": _clean_text(config.get("provider_name")) or base.get("provider_name"),
        "commercial_allowed": _normalize_bool(config.get("commercial_allowed"), default=_normalize_bool(base.get("commercial_allowed"))),
        "ai_processing_allowed": _normalize_bool(config.get("ai_processing_allowed"), default=_normalize_bool(base.get("ai_processing_allowed"), True)),
        "training_allowed": _normalize_bool(config.get("training_allowed"), default=_normalize_bool(base.get("training_allowed"))),
        "remark": _clean_text(config.get("remark")) or base.get("remark"),
    }



def _build_document_input(config: dict[str, Any], context: dict[str, Any], recorded_input: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = recorded_input or {}
    return {
        "document_mode": _clean_text(config.get("document_mode")) or base.get("document_mode") or "path",
        "existing_document_id": _safe_int(config.get("existing_document_id")) or _safe_int(base.get("existing_document_id")),
        "source_id": context.get("source_id"),
        "document_path": _clean_text(config.get("document_path")) or base.get("document_path"),
        "tenant_id": _safe_int(config.get("tenant_id")) or _safe_int(base.get("tenant_id")),
        "parse_profile": _clean_text(config.get("parse_profile")) or base.get("parse_profile") or "default",
        "subject": _clean_text(config.get("subject")) or base.get("subject"),
        "grade": _clean_text(config.get("grade")) or base.get("grade"),
        "year": _safe_int(config.get("year")) or _safe_int(base.get("year")),
        "region": _clean_text(config.get("region")) or base.get("region"),
        "title": _clean_text(config.get("title")) or base.get("title"),
        "visibility_scope": _clean_text(config.get("document_visibility_scope")) or base.get("visibility_scope") or "tenant_private",
    }



def _build_bundle_input(config: dict[str, Any], context: dict[str, Any], recorded_input: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = recorded_input or {}
    link_source_document = _normalize_bool(config.get("link_source_document"), default=_normalize_bool(base.get("link_source_document"), True))
    source_document_id = context.get("source_document_id") if link_source_document else None
    return {
        "bundle_dir": _clean_text(config.get("bundle_dir")) or base.get("bundle_dir"),
        "student_id": _safe_int(config.get("student_id")) or _safe_int(base.get("student_id")),
        "tenant_id": _safe_int(config.get("tenant_id")) or _safe_int(base.get("tenant_id")),
        "source_document_id": source_document_id,
        "subject": _clean_text(config.get("subject")) or base.get("subject"),
        "exam_date": _clean_text(config.get("exam_date")) or base.get("exam_date"),
        "visibility_scope": _clean_text(config.get("exam_visibility_scope")) or base.get("visibility_scope") or "private",
        "link_source_document": link_source_document,
    }



def _build_match_input(config: dict[str, Any], context: dict[str, Any], recorded_input: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    base = recorded_input or {}
    return {
        "exam_session_id": context.get("exam_session_id"),
        "top_k": _safe_int(config.get("match_top_k")) or _safe_int(base.get("top_k")) or 5,
        "accept_threshold": _safe_float(config.get("match_accept_threshold"), _safe_float(base.get("accept_threshold"), 0.78)),
        "min_gap": _safe_float(config.get("match_min_gap"), _safe_float(base.get("min_gap"), 0.05)),
    }



def _execute_prepare_source(db: Session, input_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if input_payload["source_mode"] == "existing" and input_payload.get("existing_source_id"):
        source = crud.get_content_source(db, input_payload["existing_source_id"])
        if not source:
            raise ValueError(f"ContentSource {input_payload['existing_source_id']} 不存在")
        return _serialize_content_source(source), {"source_id": source.id}

    source_payload = schemas.ContentSourceCreate(
        tenant_id=input_payload.get("tenant_id"),
        source_name=input_payload["source_name"],
        source_type=input_payload["source_type"],
        provider_name=input_payload.get("provider_name"),
        commercial_allowed=bool(input_payload.get("commercial_allowed")),
        ai_processing_allowed=bool(input_payload.get("ai_processing_allowed", True)),
        training_allowed=bool(input_payload.get("training_allowed")),
        remark=input_payload.get("remark"),
    )
    source = crud.create_content_source(db, source_payload)
    return _serialize_content_source(source), {"source_id": source.id}



def _execute_register_document(db: Session, input_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_id = input_payload.get("source_id")
    if not source_id:
        raise ValueError("登记文档前必须先准备内容源")

    if input_payload["document_mode"] == "existing" and input_payload.get("existing_document_id"):
        document = crud.get_source_document(db, input_payload["existing_document_id"])
        if not document:
            raise ValueError(f"SourceDocument {input_payload['existing_document_id']} 不存在")
        return _serialize_source_document(document), {"source_document_id": document.id}

    document_path = input_payload.get("document_path")
    if not document_path:
        raise ValueError("请提供题库文档路径")

    storage_url, file_sha256, file_name, mime_type = _copy_document_to_uploads(document_path, source_id)
    document_payload = schemas.SourceDocumentCreate(
        source_id=source_id,
        tenant_id=input_payload.get("tenant_id"),
        file_name=file_name,
        file_ext=Path(file_name).suffix.lstrip("."),
        mime_type=mime_type,
        storage_url=storage_url,
        file_sha256=file_sha256,
        parse_profile=input_payload.get("parse_profile") or "default",
        subject=input_payload.get("subject"),
        grade=input_payload.get("grade"),
        year=input_payload.get("year"),
        region=input_payload.get("region"),
        title=input_payload.get("title"),
        visibility_scope=input_payload.get("visibility_scope") or "tenant_private",
    )
    document = crud.create_source_document(db, document_payload)
    document = crud.get_source_document(db, document.id)
    return _serialize_source_document(document), {"source_document_id": document.id}



def _execute_ingest_document(db: Session, source_document_id: int, force_reingest: bool) -> dict[str, Any]:
    if not source_document_id:
        raise ValueError("题库摄入前必须先准备 SourceDocument")

    service = QuestionBankIngestionService()
    ingest_result = service.ingest_source_document(db, source_document_id, force_reingest=force_reingest)
    document = crud.get_source_document(db, source_document_id)
    return {
        "ingest_result": ingest_result,
        "document": _serialize_source_document(document) if document else None,
    }



def _execute_import_bundle(db: Session, input_payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle_dir = input_payload.get("bundle_dir")
    student_id = input_payload.get("student_id")
    if not bundle_dir:
        raise ValueError("请提供 bundle 目录")
    if not student_id:
        raise ValueError("导入 bundle 时 student_id 不能为空")

    service = ExamSessionBundleImportService()
    payload = schemas.ExamSessionBundleImportRequest(
        bundle_dir=bundle_dir,
        student_id=student_id,
        tenant_id=input_payload.get("tenant_id"),
        source_document_id=input_payload.get("source_document_id"),
        subject=input_payload.get("subject"),
        exam_date=_parse_exam_date(input_payload.get("exam_date")),
        visibility_scope=input_payload.get("visibility_scope") or "private",
        auto_match=False,
    )
    result = service.import_bundle(db, payload)
    exam_session = result.get("exam_session")
    exam_session_id = exam_session.id if exam_session else None
    return {
        "bundle_id": result.get("bundle_id"),
        "run_id": result.get("run_id"),
        "question_count": result.get("question_count"),
        "warnings": result.get("warnings") or [],
        "match_result": result.get("match_result"),
        "match_error": result.get("match_error"),
        "exam_session": _serialize_exam_session(exam_session) if exam_session else None,
    }, {"exam_session_id": exam_session_id}



def _execute_match_exam_session(db: Session, input_payload: dict[str, Any]) -> dict[str, Any]:
    exam_session_id = input_payload.get("exam_session_id")
    if not exam_session_id:
        raise ValueError("试卷匹配前必须先导入 bundle")

    service = ExamSessionMatchingService()
    result = service.match_exam_session(
        db=db,
        exam_session_id=exam_session_id,
        top_k=input_payload.get("top_k") or 5,
        accept_threshold=input_payload.get("accept_threshold") or 0.78,
        min_gap=input_payload.get("min_gap") or 0.05,
    )
    exam_session = crud.get_exam_session(db, exam_session_id)
    return {
        "match_result": result,
        "exam_session": _serialize_exam_session(exam_session) if exam_session else None,
        "matches": crud.build_exam_session_match_views(db, exam_session_id),
    }



def _get_step_label(step_key: str) -> str:
    for step in CONTENT_INGESTION_PIPELINE_STEPS:
        if step["key"] == step_key:
            return step["label"]
    return step_key


@router.get("/api/content-ingestion/pipeline-steps")
def get_content_ingestion_pipeline_steps():
    return CONTENT_INGESTION_PIPELINE_STEPS


@router.get("/api/content-ingestion/mock-cases")
def get_content_ingestion_mock_cases():
    return _list_mock_cases()


@router.get("/api/content-ingestion/overview")
def get_content_ingestion_overview(db: Session = Depends(get_main_db)):
    sources = crud.get_content_sources(db, limit=20)
    documents = crud.get_source_documents(db, limit=20)
    exam_sessions = crud.get_exam_sessions(db, limit=20)
    return {
        "counts": {
            "sources": db.query(models.ContentSource).count(),
            "documents": db.query(models.SourceDocument).count(),
            "exam_sessions": db.query(models.ExamSession).count(),
            "mock_cases": len(_list_mock_cases()),
        },
        "sources": [_serialize_content_source(item) for item in sources],
        "documents": [_serialize_source_document(item) for item in documents],
        "exam_sessions": [_serialize_exam_session(item) for item in exam_sessions],
        "mock_cases": _list_mock_cases(),
    }


async def _emit(websocket: WebSocket, all_logs: list[str], message: str) -> None:
    await websocket.send_text(message)
    all_logs.append(message)


@router.websocket("/ws/run-content-ingestion")
async def websocket_run_content_ingestion(websocket: WebSocket):
    await websocket.accept()
    all_logs: list[str] = []
    db = MainSessionLocal()
    try:
        await _emit(websocket, all_logs, "[SYSTEM] 内容摄入测试初始化完成。")
        config = await websocket.receive_json()
        await _emit(websocket, all_logs, f"[SYSTEM] 收到测试配置：{json.dumps(config, ensure_ascii=False)}")

        test_mode = _clean_text(config.get("test_mode")) or "real"
        case_dir: Optional[Path] = None
        mock_case_dir: Optional[Path] = None
        case_name: Optional[str] = None

        if test_mode == "record":
            case_name = _clean_text(config.get("case_name")) or f"case_{int(datetime.now().timestamp())}"
            case_dir = MOCK_DATA_DIR / case_name
            case_dir.mkdir(parents=True, exist_ok=True)
            _write_json(
                case_dir / "manifest.json",
                {
                    "module": "analyzer",
                    "pipeline": "content_ingestion",
                    "created_at": datetime.now().isoformat(),
                    "config": config,
                    "pipeline_steps": CONTENT_INGESTION_PIPELINE_STEPS,
                },
            )
            await _emit(websocket, all_logs, f"[SYSTEM] 当前为录制模式，输出目录：{case_dir}")
        elif test_mode == "mock":
            case_name = _clean_text(config.get("mock_case"))
            if not case_name:
                raise HTTPException(status_code=400, detail="Mock 模式下必须选择 mock_case")
            mock_case_dir = _resolve_mock_case_dir(case_name)
            await _emit(websocket, all_logs, f"[SYSTEM] 当前为 Mock 模式，使用案例：{mock_case_dir}")

        effective_real_steps, promoted_steps = _compute_effective_real_steps(config) if test_mode == "mock" else ([step["key"] for step in CONTENT_INGESTION_PIPELINE_STEPS], [])
        if test_mode == "mock":
            await _emit(websocket, all_logs, f"[SYSTEM] Mock 模式真实执行步骤：{effective_real_steps or []}")
            if promoted_steps:
                promoted_labels = [f"{key}:{_get_step_label(key)}" for key in promoted_steps]
                await _emit(websocket, all_logs, f"[SYSTEM] 因依赖关系自动补齐真实步骤：{promoted_labels}")

        runtime_context: dict[str, Any] = {}

        for step in CONTENT_INGESTION_PIPELINE_STEPS:
            step_key = step["key"]
            step_label = step["label"]
            run_real = test_mode in {"real", "record"} or step_key in effective_real_steps
            recorded_step = _load_step_record(mock_case_dir, step_key) if mock_case_dir else None

            await _emit(websocket, all_logs, f"[STEP-{step_key}] 开始：{step_label}（{'真实执行' if run_real else 'Mock 回放'}）")

            if step_key == "0":
                input_payload = _build_source_input(config, recorded_step.get("input") if recorded_step else None)
                result, context_patch = _execute_prepare_source(db, input_payload)
                if not run_real:
                    result = {**result, "mock_replayed": True, "mock_case": case_name}
            elif step_key == "1":
                input_payload = _build_document_input(config, runtime_context, recorded_step.get("input") if recorded_step else None)
                result, context_patch = _execute_register_document(db, input_payload)
                if not run_real:
                    result = {**result, "mock_replayed": True, "mock_case": case_name}
            elif step_key == "2":
                input_payload = {
                    "source_document_id": runtime_context.get("source_document_id"),
                    "force_reingest": _normalize_bool(config.get("force_reingest")),
                }
                if run_real:
                    result = _execute_ingest_document(db, runtime_context.get("source_document_id"), _normalize_bool(config.get("force_reingest")))
                else:
                    if not recorded_step:
                        raise FileNotFoundError(f"Mock case 缺少步骤 {step_label} 的录制文件")
                    result = dict(recorded_step.get("result") or {})
                    result.update({"mock_replayed": True, "mock_case": case_name})
                context_patch = {}
            elif step_key == "3":
                input_payload = _build_bundle_input(config, runtime_context, recorded_step.get("input") if recorded_step else None)
                if run_real:
                    result, context_patch = _execute_import_bundle(db, input_payload)
                else:
                    if not recorded_step:
                        raise FileNotFoundError(f"Mock case 缺少步骤 {step_label} 的录制文件")
                    result = dict(recorded_step.get("result") or {})
                    result.update({"mock_replayed": True, "mock_case": case_name})
                    context_patch = {}
            elif step_key == "4":
                input_payload = _build_match_input(config, runtime_context, recorded_step.get("input") if recorded_step else None)
                if run_real:
                    result = _execute_match_exam_session(db, input_payload)
                else:
                    if not recorded_step:
                        raise FileNotFoundError(f"Mock case 缺少步骤 {step_label} 的录制文件")
                    result = dict(recorded_step.get("result") or {})
                    result.update({"mock_replayed": True, "mock_case": case_name})
                context_patch = {}
            else:
                raise ValueError(f"未知步骤：{step_key}")

            runtime_context.update(context_patch)

            summary = result
            if isinstance(result, dict):
                summary = json.dumps(result, ensure_ascii=False, default=_json_default)[:1000]
            await _emit(websocket, all_logs, f"[STEP-{step_key}] 完成：{summary}")

            if case_dir is not None:
                _record_step(case_dir, step_key, input_payload, result, runtime_context)

        await _emit(websocket, all_logs, "[SYSTEM] 内容摄入测试已完成。")

        if case_dir is not None:
            log_file_path = case_dir / "run_log.txt"
            log_file_path.write_text("\n".join(all_logs), encoding="utf-8")
            manifest = _load_case_manifest(case_dir)
            manifest.update(
                {
                    "completed_at": datetime.now().isoformat(),
                    "runtime_context": runtime_context,
                    "available_step_keys": _get_available_step_keys(case_dir),
                }
            )
            _write_json(case_dir / "manifest.json", manifest)
            await _emit(websocket, all_logs, f"[SYSTEM] 日志已保存到：{log_file_path}")

    except Exception as exc:
        await _emit(websocket, all_logs, f"[SYSTEM-ERROR] {exc}")
    finally:
        db.close()
        await websocket.close()
