from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, WebSocket
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from uuid import uuid4

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)

from analyzer.app.config import (
    KNOWLEDGE_DERIVATIVE_ENABLED,
    KNOWLEDGE_GRAPH_ENABLED,
    KNOWLEDGE_POINT_ENABLED,
    KNOWLEDGE_POINT_DEV_UI_ENABLED,
    KNOWLEDGE_POINTS_DIR,
    KNOWLEDGE_RAG_ENABLED,
    KNOWLEDGE_RUNS_DIR,
)
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService
from analyzer.app.knowledge_point_retriever import KNOWLEDGE_ENTITY_TYPES, vector_db
from analyzer.app import knowledge_derivative as knowledge_derivative_mod
from analyzer.app.derivative_run_logging import (
    derivative_runs_root_resolved,
    list_recent_runs,
    read_run_log,
)
from analyzer.app import knowledge_graph_projection as knowledge_graph_mod
from shared import models
from shared.database import SessionLocal as MainSessionLocal

router = APIRouter(tags=["knowledge-point-admin"])
logger = logging.getLogger(__name__)

_KNOWLEDGE_INGEST_TASKS: dict[str, dict[str, Any]] = {}

KNOWLEDGE_INGEST_RUNS_ROOT = Path(KNOWLEDGE_RUNS_DIR) / "_ingest_runs"


def _create_knowledge_ingest_run_dir() -> Path:
    KNOWLEDGE_INGEST_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:10]
    run_dir = KNOWLEDGE_INGEST_RUNS_ROOT / run_id
    (run_dir / "assets").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.log").write_text("", encoding="utf-8")
    return run_dir


def _append_run_log(run_dir: Path, message: str) -> str:
    ts = datetime.now().isoformat()
    line = f"[{ts}] {message}"
    with open(run_dir / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


class _RunDirLoggingHandler(logging.Handler):
    """把 logging 记录写入本次摄入的 run.log，并复用 emit_line（可同步 WebSocket）。"""

    def __init__(self, emit_line: Callable[[str], None]):
        super().__init__(level=logging.INFO)
        self._emit_line = emit_line
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit_line(self.format(record))
        except Exception:
            pass


class _StderrTee:
    """仅在摄入线程把 stderr 增量镜像到 run.log（避免 tqdm/第三方库刷屏拖垮磁盘时可再收紧）。"""

    def __init__(self, original, ingest_thread_id: int, emit_line: Callable[[str], None], max_line: int = 4000):
        self._original = original
        self._ingest_thread_id = ingest_thread_id
        self._emit_line = emit_line
        self._max_line = max_line
        self._buf = ""

    def write(self, data: str) -> int:
        try:
            self._original.write(data)
        except Exception:
            pass
        if threading.get_ident() != self._ingest_thread_id or not data:
            return len(data)
        self._buf += data
        if len(self._buf) > 200_000:
            self._emit_line(f"[STDERR] …(缓冲区超过 200KB，已截断丢弃中间内容)…")
            self._buf = self._buf[-20_000:]
        while "\n" in self._buf or "\r" in self._buf:
            if "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
            else:
                line, self._buf = self._buf.split("\r", 1)
            text = line.strip()
            if text:
                self._emit_line(f"[STDERR] {text[: self._max_line]}")
        return len(data)

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass

    def flush_remaining(self) -> None:
        text = self._buf.strip()
        self._buf = ""
        if text:
            self._emit_line(f"[STDERR] {text[: self._max_line]}")


class _IngestRunLogCapture:
    """在摄入线程安装 stderr 分流 + root logging handler，退出时恢复。"""

    def __init__(self, emit_line: Callable[[str], None]):
        self._emit_line = emit_line
        self._ingest_tid = threading.get_ident()
        self._orig_stderr = None
        self._tee = None
        self._handler: Optional[_RunDirLoggingHandler] = None
        self._root = logging.getLogger()

    def __enter__(self) -> "_IngestRunLogCapture":
        self._orig_stderr = sys.stderr
        self._tee = _StderrTee(self._orig_stderr, self._ingest_tid, self._emit_line)
        sys.stderr = self._tee  # type: ignore[assignment]
        self._handler = _RunDirLoggingHandler(self._emit_line)
        self._root.addHandler(self._handler)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self._handler is not None:
                self._root.removeHandler(self._handler)
        finally:
            if self._tee is not None:
                self._tee.flush_remaining()
            if self._orig_stderr is not None:
                sys.stderr = self._orig_stderr
        return False


def _ingest_with_logging(
    files: list[str],
    force_reingest: bool,
    run_dir: Path,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """在独立线程中执行摄入；progress_callback 收到带时间戳的行（与 run.log 一致）。"""

    def combined_progress(msg: str) -> None:
        line = _append_run_log(run_dir, msg)
        if progress_callback:
            progress_callback(line)

    from analyzer.app import question_bank_pdf_ocr_fallback as ocr_fb

    ocr_fb.set_ingest_line_emitter(combined_progress)
    db = MainSessionLocal()
    try:
        with _IngestRunLogCapture(combined_progress):
            service = KnowledgePointIngestionService()
            out = service.ingest_files_from_knowledge_points_dir(
                db=db,
                files=files,
                force_reingest=force_reingest,
                progress_callback=combined_progress,
                ingest_run_assets_dir=run_dir / "assets",
                ingest_run_dir=run_dir,
            )
            try:
                _write_ingestion_artifacts(run_dir, out if isinstance(out, dict) else {})
                tail = _append_run_log(
                    run_dir,
                    "落库明细已写入 ingestion_detail.json、question_item_ids.txt、question_id_range.txt（用于核对题目 ID）",
                )
                if progress_callback:
                    progress_callback(tail)
                _append_run_log(
                    run_dir,
                    "详细审计：见本目录 VERBOSE_README.txt；docx/、llm/、questions/、bridge/ 下为完整提示词、模型原始返回、切题与持久化、桥接统计与 question_bridge_llm_debug 快照。",
                )
            except Exception as exc:
                logger.warning("Write ingestion artifacts failed: %s", exc)
            return out
    finally:
        ocr_fb.set_ingest_line_emitter(None)
        db.close()


def _write_ingestion_artifacts(run_dir: Path, result: dict[str, Any]) -> None:
    """写入 ingestion_detail.json 与 question_item_ids.txt，便于核对 ID 是否更新。"""
    detail: dict[str, Any] = {
        "written_at": datetime.now().isoformat(),
        "note": "paper_summaries 内为本次新建专题材料卷与 question_item_id；旧 ID 已在 clear_topic_material_papers 时删除。",
        "processed": [],
    }
    all_qids: list[int] = []
    for item in result.get("processed") or []:
        if not isinstance(item, dict):
            continue
        tqm = item.get("topic_question_metrics") if isinstance(item.get("topic_question_metrics"), dict) else {}
        summaries = tqm.get("paper_summaries") or []
        for ps in summaries:
            qids = ps.get("question_item_ids") or []
            if isinstance(qids, list):
                for q in qids:
                    try:
                        all_qids.append(int(q))
                    except (TypeError, ValueError):
                        pass
        detail["processed"].append(
            {
                "file": item.get("file"),
                "status": item.get("status"),
                "source_document_id": item.get("source_document_id"),
                "topic_question_metrics": tqm,
            }
        )
    (run_dir / "ingestion_detail.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    all_qids_sorted = sorted(set(all_qids))
    (run_dir / "question_item_ids.txt").write_text(
        "\n".join(str(i) for i in all_qids_sorted),
        encoding="utf-8",
    )
    (run_dir / "question_id_range.txt").write_text(
        f"count={len(all_qids_sorted)}\nmin={all_qids_sorted[0] if all_qids_sorted else 'n/a'}\nmax={all_qids_sorted[-1] if all_qids_sorted else 'n/a'}\n",
        encoding="utf-8",
    )


def _set_task(task_id: str, **updates: Any) -> None:
    payload = _KNOWLEDGE_INGEST_TASKS.get(task_id) or {"task_id": task_id}
    payload.update(updates)
    _KNOWLEDGE_INGEST_TASKS[task_id] = payload


def _is_knowledge_admin_enabled() -> bool:
    return bool(KNOWLEDGE_POINT_ENABLED or KNOWLEDGE_POINT_DEV_UI_ENABLED)


@router.get("/api/knowledge-admin/_routes")
def debug_list_routes():
    return {"routes": sorted({getattr(item, "path", str(item)) for item in router.routes})}


def get_main_db():
    db = MainSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _serialize_point(point: models.KnowledgePoint) -> dict[str, Any]:
    return {
        "id": point.id,
        "canonical_name": point.canonical_name,
        "subject": point.subject,
        "grade_scope": point.grade_scope,
        "knowledge_type": point.knowledge_type,
        "review_status": point.review_status,
        "updated_at": point.updated_at.isoformat() if point.updated_at else None,
    }


def _serialize_package(package: models.KnowledgePackage) -> dict[str, Any]:
    return {
        "id": package.id,
        "package_title": package.package_title,
        "subject": package.subject,
        "grade": package.grade,
        "package_type": package.package_type,
        "parse_status": package.parse_status,
        "review_status": package.review_status,
        "updated_at": package.updated_at.isoformat() if package.updated_at else None,
    }


@router.get("/api/knowledge-admin/overview")
def get_knowledge_admin_overview(db: Session = Depends(get_main_db)):
    try:
        point_status_counts = {
            (status or "unknown"): count
            for status, count in db.query(
                models.KnowledgePoint.review_status,
                func.count(models.KnowledgePoint.id),
            )
            .group_by(models.KnowledgePoint.review_status)
            .all()
        }
        package_status_counts = {
            (status or "unknown"): count
            for status, count in db.query(
                models.KnowledgePackage.review_status,
                func.count(models.KnowledgePackage.id),
            )
            .group_by(models.KnowledgePackage.review_status)
            .all()
        }
        parse_status_counts = {
            (status or "unknown"): count
            for status, count in db.query(
                models.KnowledgePackage.parse_status,
                func.count(models.KnowledgePackage.id),
            )
            .group_by(models.KnowledgePackage.parse_status)
            .all()
        }

        recent_points = (
            db.query(models.KnowledgePoint)
            .order_by(models.KnowledgePoint.id.desc())
            .limit(8)
            .all()
        )
        recent_packages = (
            db.query(models.KnowledgePackage)
            .order_by(models.KnowledgePackage.id.desc())
            .limit(8)
            .all()
        )

        point_subjects = {
            str(value).strip()
            for (value,) in db.query(models.KnowledgePoint.subject)
            .filter(models.KnowledgePoint.subject.isnot(None))
            .distinct()
            .all()
            if str(value).strip()
        }
        package_subjects = {
            str(value).strip()
            for (value,) in db.query(models.KnowledgePackage.subject)
            .filter(models.KnowledgePackage.subject.isnot(None))
            .distinct()
            .all()
            if str(value).strip()
        }

        retrieval_documents = db.query(models.RetrievalDocument).filter(
            models.RetrievalDocument.entity_type.in_(KNOWLEDGE_ENTITY_TYPES)
        )
        embedding_points = (
            db.query(models.EmbeddingPoint)
            .join(
                models.RetrievalDocument,
                models.RetrievalDocument.id == models.EmbeddingPoint.retrieval_document_id,
            )
            .filter(models.RetrievalDocument.entity_type.in_(KNOWLEDGE_ENTITY_TYPES))
        )

        return {
            "flags": {
                "knowledge_point_enabled": KNOWLEDGE_POINT_ENABLED,
                "knowledge_rag_enabled": KNOWLEDGE_RAG_ENABLED,
                "knowledge_graph_enabled": KNOWLEDGE_GRAPH_ENABLED,
                "knowledge_derivative_enabled": KNOWLEDGE_DERIVATIVE_ENABLED,
            },
            "counts": {
                "knowledge_points": db.query(models.KnowledgePoint).count(),
                "knowledge_packages": db.query(models.KnowledgePackage).count(),
                "knowledge_blocks": db.query(models.KnowledgeBlock).count(),
                "knowledge_atoms": db.query(models.KnowledgeAtom).count(),
                "knowledge_question_links": db.query(models.KnowledgeQuestionLink).count(),
                "knowledge_package_questions": db.query(models.KnowledgePackageQuestion).count(),
                "knowledge_point_relations": db.query(models.KnowledgePointRelation).count(),
                "retrieval_documents": retrieval_documents.count(),
                "embedding_points": embedding_points.count(),
                "entity_graph_edges": db.query(models.EntityGraphEdge).count(),
                "knowledge_derivatives": db.query(models.KnowledgeDerivative).count(),
                "knowledge_derivatives_approved": (
                    db.query(models.KnowledgeDerivative)
                    .filter(models.KnowledgeDerivative.review_status == "approved")
                    .count()
                ),
            },
            "status_breakdown": {
                "point_review_status": point_status_counts,
                "package_review_status": package_status_counts,
                "package_parse_status": parse_status_counts,
            },
            "subjects": sorted(point_subjects | package_subjects),
            "recent_points": [_serialize_point(item) for item in recent_points],
            "recent_packages": [_serialize_package(item) for item in recent_packages],
            "backends": vector_db.db.backend_summary,
        }
    except SQLAlchemyError as exc:
        logger.exception("Load knowledge admin overview failed")
        raise HTTPException(
            status_code=500,
            detail="加载知识点后台概览失败，请确认知识点迁移已执行且数据库可用。",
        ) from exc


@router.get("/api/knowledge-admin/ingest/files")
def list_knowledge_points_files():
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")
    base_dir = Path(KNOWLEDGE_POINTS_DIR)
    if not base_dir.exists():
        return {"directory": str(base_dir), "files": []}
    files = []
    for item in sorted(base_dir.iterdir(), key=lambda p: p.name.lower()):
        if not item.is_file():
            continue
        lower = item.name.lower()
        if lower.endswith((".pdf", ".docx", ".txt")):
            files.append(item.name)
    return {"directory": str(base_dir), "files": files}


@router.get("/api/knowledge-admin/ingest/tasks/{task_id}")
def get_knowledge_points_ingest_task(task_id: str):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")
    payload = _KNOWLEDGE_INGEST_TASKS.get(task_id)
    if not payload:
        raise HTTPException(status_code=404, detail="未找到摄入任务")
    return payload


@router.post("/api/knowledge-admin/ingest", status_code=202)
async def start_knowledge_points_ingest(payload: dict, background_tasks: BackgroundTasks):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")

    files = payload.get("files") or []
    if not isinstance(files, list) or not all(isinstance(item, str) and item.strip() for item in files):
        raise HTTPException(status_code=400, detail="files 必须是非空字符串数组")

    force_reingest = bool(payload.get("force_reingest") or payload.get("forceReingest"))

    model_id = payload.get("model_id")
    if model_id is not None:
        try:
            model_id = int(model_id)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="model_id 必须是整数或为空")

    task_id = uuid4().hex
    _set_task(task_id, status="running", started_at=datetime.now().isoformat(), processed_files=[], error=None)

    async def _run():
        try:
            run_dir = _create_knowledge_ingest_run_dir()
            _append_run_log(run_dir, f"HTTP 异步任务启动 task_id={task_id} files={files} force_reingest={force_reingest}")

            def _do():
                out = _ingest_with_logging(files, force_reingest, run_dir, progress_callback=None)
                if isinstance(out, dict) and model_id is not None:
                    return {**out, "model_id": model_id}
                return out

            result = await asyncio.to_thread(_do)
            processed = result.get("processed") if isinstance(result, dict) else None
            manifest = {
                "task_id": task_id,
                "run_dir": str(run_dir),
                "result": result,
                "ended_at": datetime.now().isoformat(),
            }
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            _append_run_log(run_dir, f"完成，manifest 已写入：{run_dir / 'manifest.json'}")
            _set_task(
                task_id,
                status="success",
                ended_at=datetime.now().isoformat(),
                result=result,
                run_dir=str(run_dir),
                processed_files=processed or [],
            )
        except Exception as exc:
            logger.exception("Knowledge points ingest task failed")
            _set_task(task_id, status="failed", ended_at=datetime.now().isoformat(), error=str(exc))

    background_tasks.add_task(_run)
    return {"task_id": task_id}


@router.websocket("/ws/run-knowledge-ingest")
async def websocket_run_knowledge_ingest(websocket: WebSocket):
    if not _is_knowledge_admin_enabled():
        await websocket.close(code=4403)
        return
    await websocket.accept()
    run_dir: Optional[Path] = None
    try:
        await websocket.send_text("[SYSTEM] WebSocket 已连接，等待配置…")
        config = await websocket.receive_json()
        files = config.get("files") or []
        if not isinstance(files, list) or not files or not all(isinstance(item, str) and item.strip() for item in files):
            await websocket.send_text("[ERROR] files 必须为非空字符串数组")
            return
        force_reingest = bool(config.get("force_reingest") or config.get("forceReingest"))

        run_dir = _create_knowledge_ingest_run_dir()
        await websocket.send_text(f"[SYSTEM] 本次运行目录：{run_dir}")
        await websocket.send_text(f"[SYSTEM] run.log / assets/ 将写入上述目录（PDF 内嵌图会导出到 assets/<文件名>/）")
        _append_run_log(run_dir, f"WebSocket 摄入开始 files={files} force_reingest={force_reingest}")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def progress_callback(line: str) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, line)

        result_holder: dict[str, Any] = {}
        error_holder: list[BaseException] = []

        def worker() -> None:
            try:
                result_holder["result"] = _ingest_with_logging(files, force_reingest, run_dir, progress_callback=progress_callback)
            except BaseException as exc:
                error_holder.append(exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            await websocket.send_text(item)

        if error_holder:
            err = error_holder[0]
            await websocket.send_text(f"[ERROR] {err.__class__.__name__}: {err}")
            _append_run_log(run_dir, f"摄入失败：{err}")
            logger.exception("WebSocket knowledge ingest failed")
        else:
            manifest = {
                "run_dir": str(run_dir),
                "result": result_holder.get("result"),
                "ended_at": datetime.now().isoformat(),
            }
            (run_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            _append_run_log(run_dir, f"完成，manifest：{run_dir / 'manifest.json'}")
            await websocket.send_text(f"[SYSTEM] 已写入 manifest.json，运行目录：{run_dir}")
    except Exception as exc:
        logger.exception("WebSocket knowledge ingest handler failed")
        try:
            await websocket.send_text(f"[SYSTEM-ERROR] {exc.__class__.__name__}: {exc}")
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.post("/api/knowledge-admin/packages/{package_id}/question-links")
def link_question_to_knowledge_package(
    package_id: int,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_main_db),
):
    """将已有题目挂到专题包（多专题多行；同一 package+question 唯一）。"""
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")
    pkg = db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="专题包不存在")
    try:
        qid = int(payload.get("question_item_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="question_item_id 必须为整数")
    qitem = db.query(models.QuestionItem).filter(models.QuestionItem.id == qid).first()
    if not qitem:
        raise HTTPException(status_code=404, detail="题目不存在")
    dup = (
        db.query(models.KnowledgePackageQuestion)
        .filter(
            models.KnowledgePackageQuestion.package_id == package_id,
            models.KnowledgePackageQuestion.question_item_id == qid,
        )
        .first()
    )
    if dup:
        return {"ok": True, "link_id": dup.id, "deduplicated": True}
    rel_type = str(payload.get("relation_type") or "supplement").strip()[:32]
    disp = payload.get("display_order")
    disp_int = int(disp) if disp is not None and str(disp).strip() != "" else None
    row = models.KnowledgePackageQuestion(
        package_id=package_id,
        question_item_id=qid,
        display_order=disp_int,
        relation_type=rel_type or "supplement",
        source_origin="explicit",
        approved_status="pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"ok": True, "link_id": row.id}


@router.delete("/api/knowledge-admin/packages/{package_id}/question-links/{link_id}")
def unlink_question_from_knowledge_package(
    package_id: int,
    link_id: int,
    db: Session = Depends(get_main_db),
):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")
    row = (
        db.query(models.KnowledgePackageQuestion)
        .filter(
            models.KnowledgePackageQuestion.id == link_id,
            models.KnowledgePackageQuestion.package_id == package_id,
        )
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="关联不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/api/knowledge-admin/packages/{package_id}/question-links")
def list_package_question_links(package_id: int, db: Session = Depends(get_main_db)):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")
    pkg = db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="专题包不存在")
    rows = (
        db.query(models.KnowledgePackageQuestion)
        .filter(models.KnowledgePackageQuestion.package_id == package_id)
        .order_by(models.KnowledgePackageQuestion.display_order.asc(), models.KnowledgePackageQuestion.id.asc())
        .all()
    )
    return {
        "package_id": package_id,
        "items": [
            {
                "link_id": r.id,
                "question_item_id": r.question_item_id,
                "display_order": r.display_order,
                "relation_type": r.relation_type,
            }
            for r in rows
        ],
    }


def _require_graph_enabled():
    if not KNOWLEDGE_GRAPH_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="图谱开关未启用：请设置 .env 中 KNOWLEDGE_GRAPH_ENABLED=true 并重启 test UI 后再试。",
        )


def _require_derivative_enabled():
    if not KNOWLEDGE_DERIVATIVE_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="衍生层开关未启用：请设置 .env 中 KNOWLEDGE_DERIVATIVE_ENABLED=true 并重启 test UI 后再试。",
        )


@router.get("/api/knowledge-admin/graph/summary")
def get_graph_summary(db: Session = Depends(get_main_db)):
    """返回 entity_graph_edges 的计数摘要（不受开关限制，用于前端提示）。"""
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    total = db.query(models.EntityGraphEdge).count()
    summary = knowledge_graph_mod.summarize_edges(db)
    return {
        "flag": {"knowledge_graph_enabled": KNOWLEDGE_GRAPH_ENABLED},
        "total": int(total),
        "groups": summary.get("groups", []),
    }


@router.post("/api/knowledge-admin/graph/projection/package/{package_id}")
def project_graph_for_package(package_id: int, db: Session = Depends(get_main_db)):
    _require_graph_enabled()
    try:
        return knowledge_graph_mod.project_package(db, package_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SQLAlchemyError as exc:
        logger.exception("Project graph for package failed")
        raise HTTPException(status_code=500, detail="图谱投影失败，详见后端日志") from exc


@router.post("/api/knowledge-admin/graph/projection/knowledge-point/{knowledge_point_id}")
def project_graph_for_knowledge_point(knowledge_point_id: int, db: Session = Depends(get_main_db)):
    _require_graph_enabled()
    try:
        return knowledge_graph_mod.project_knowledge_point(db, knowledge_point_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SQLAlchemyError as exc:
        logger.exception("Project graph for knowledge_point failed")
        raise HTTPException(status_code=500, detail="图谱投影失败，详见后端日志") from exc


@router.post("/api/knowledge-admin/graph/projection/all")
def project_graph_all(db: Session = Depends(get_main_db)):
    """扫全库：对每个专题包执行一次投影。生产环境谨慎使用。"""
    _require_graph_enabled()
    try:
        return knowledge_graph_mod.project_all(db)
    except SQLAlchemyError as exc:
        logger.exception("Project graph all failed")
        raise HTTPException(status_code=500, detail="图谱全量投影失败，详见后端日志") from exc


@router.get("/api/knowledge-admin/graph/edges")
def list_graph_edges(
    knowledge_point_id: Optional[int] = None,
    package_id: Optional[int] = None,
    limit: int = 200,
    db: Session = Depends(get_main_db),
):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    if knowledge_point_id is not None:
        items = knowledge_graph_mod.list_edges_for_knowledge_point(db, knowledge_point_id, limit=limit)
        return {"scope": "knowledge_point", "knowledge_point_id": knowledge_point_id, "items": items}
    if package_id is not None:
        items = knowledge_graph_mod.list_edges_for_package(db, package_id, limit=limit)
        return {"scope": "package", "package_id": package_id, "items": items}
    raise HTTPException(status_code=400, detail="必须提供 knowledge_point_id 或 package_id 其中之一")


@router.get("/api/knowledge-admin/derivatives/summary")
def get_derivative_summary(db: Session = Depends(get_main_db)):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    summary = knowledge_derivative_mod.count_derivatives(db)
    return {
        "flag": {
            "knowledge_derivative_enabled": KNOWLEDGE_DERIVATIVE_ENABLED,
            "knowledge_rag_enabled": KNOWLEDGE_RAG_ENABLED,
        },
        "derivative_runs_root": derivative_runs_root_resolved(),
        "total": summary.get("total", 0),
        "groups": summary.get("groups", []),
        "supported_types": list(knowledge_derivative_mod.DERIVATIVE_TYPES),
        "supported_audiences": list(knowledge_derivative_mod.TARGET_AUDIENCES),
    }


@router.get("/api/knowledge-admin/derivatives/logging-info")
def get_derivative_logging_info():
    """衍生层文件日志根目录（绝对路径），供管理端展示。"""
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    return {
        "runs_root": derivative_runs_root_resolved(),
        "note": "每次生成会在该目录下新建子目录，含 run.log 与各组合 llm_*.json（请求+响应）。",
    }


@router.get("/api/knowledge-admin/derivatives/runs")
def list_derivative_run_dirs(limit: int = 30):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    return {
        "runs_root": derivative_runs_root_resolved(),
        "items": list_recent_runs(limit=limit),
    }


@router.get("/api/knowledge-admin/derivatives/runs/{run_id}")
def get_derivative_run_log(run_id: str, max_chars: int = 256000):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    payload = read_run_log(run_id, max_chars=max_chars)
    if payload.get("error") == "not_found":
        raise HTTPException(status_code=404, detail="运行目录不存在")
    if payload.get("error") and payload.get("error") != "not_found":
        raise HTTPException(status_code=500, detail=str(payload.get("error")))
    return payload


@router.get("/api/knowledge-admin/derivatives")
def list_derivatives(
    knowledge_point_id: Optional[int] = None,
    package_id: Optional[int] = None,
    review_status: Optional[str] = None,
    derivative_type: Optional[str] = None,
    target_audience: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_main_db),
):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    return knowledge_derivative_mod.list_derivatives(
        db,
        knowledge_point_id=knowledge_point_id,
        package_id=package_id,
        review_status=review_status,
        derivative_type=derivative_type,
        target_audience=target_audience,
        limit=limit,
        offset=offset,
    )


@router.post("/api/knowledge-admin/derivatives/generate")
def generate_derivatives(payload: dict[str, Any] = Body(...), db: Session = Depends(get_main_db)):
    _require_derivative_enabled()
    knowledge_point_id = payload.get("knowledge_point_id")
    package_id = payload.get("package_id")
    raw_types = payload.get("derivative_types") or list(knowledge_derivative_mod.DERIVATIVE_TYPES)
    raw_audiences = payload.get("target_audiences") or ["student"]
    if not isinstance(raw_types, list) or not isinstance(raw_audiences, list):
        raise HTTPException(status_code=400, detail="derivative_types / target_audiences 必须是字符串数组")
    derivative_types = tuple(str(item) for item in raw_types if isinstance(item, str) and item.strip())
    target_audiences = tuple(str(item) for item in raw_audiences if isinstance(item, str) and item.strip())

    try:
        if knowledge_point_id is not None:
            return knowledge_derivative_mod.generate_for_point(
                db,
                int(knowledge_point_id),
                derivative_types=derivative_types,
                target_audiences=target_audiences,
            )
        if package_id is not None:
            return knowledge_derivative_mod.generate_for_package(
                db,
                int(package_id),
                derivative_types=derivative_types,
                target_audiences=target_audiences,
            )
    except knowledge_derivative_mod.DerivativeEvidenceError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "derivative_evidence",
                "message": str(exc),
                "knowledge_point_id": getattr(exc, "knowledge_point_id", None),
                "run_id": getattr(exc, "run_id", None),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    raise HTTPException(status_code=400, detail="必须提供 knowledge_point_id 或 package_id 其中之一")


@router.post("/api/knowledge-admin/derivatives/{derivative_id}/review")
def review_derivative(
    derivative_id: int,
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_main_db),
):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    status = str(payload.get("review_status") or "").strip().lower()
    if status not in knowledge_derivative_mod.REVIEW_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"review_status 必须是 {knowledge_derivative_mod.REVIEW_STATUSES} 之一",
        )
    try:
        return knowledge_derivative_mod.set_review_status(db, derivative_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/knowledge-admin/derivatives/{derivative_id}/retry")
def retry_derivative(derivative_id: int, db: Session = Depends(get_main_db)):
    _require_derivative_enabled()
    record = (
        db.query(models.KnowledgeDerivative)
        .filter(models.KnowledgeDerivative.id == derivative_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="衍生内容不存在")
    try:
        return knowledge_derivative_mod.generate_for_point(
            db,
            record.knowledge_point_id,
            derivative_types=(record.derivative_type,),
            target_audiences=(record.target_audience,),
        )
    except knowledge_derivative_mod.DerivativeEvidenceError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "derivative_evidence",
                "message": str(exc),
                "knowledge_point_id": getattr(exc, "knowledge_point_id", None),
                "run_id": getattr(exc, "run_id", None),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.delete("/api/knowledge-admin/derivatives/{derivative_id}")
def delete_derivative(derivative_id: int, db: Session = Depends(get_main_db)):
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    record = (
        db.query(models.KnowledgeDerivative)
        .filter(models.KnowledgeDerivative.id == derivative_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="衍生内容不存在")
    # 删除前把检索文档一并清掉
    try:
        knowledge_derivative_mod._remove_derivative_retrieval(db, derivative_id)
    except Exception:
        logger.warning("Remove derivative retrieval before delete failed", exc_info=True)
    db.delete(record)
    db.commit()
    return {"ok": True, "derivative_id": derivative_id}


@router.get("/api/knowledge-admin/packages/{package_id}/blocks")
def list_package_blocks(package_id: int, db: Session = Depends(get_main_db)):
    """返回专题包下所有知识块（含完整 rich_content_json，供前端 QuestionRichRenderer 渲染）。"""
    if not _is_knowledge_admin_enabled():
        raise HTTPException(status_code=503, detail="知识点功能未启用（可在测试后台开启开发开关）")
    pkg = db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == package_id).first()
    if not pkg:
        raise HTTPException(status_code=404, detail="专题包不存在")

    from analyzer.app.question_bank_views import _decorate_render_payload

    rows = (
        db.query(models.KnowledgeBlock)
        .filter(models.KnowledgeBlock.package_id == package_id)
        .order_by(models.KnowledgeBlock.block_order.asc())
        .all()
    )
    return {
        "package_id": package_id,
        "package_title": pkg.package_title,
        "blocks": [
            {
                "id": b.id,
                "block_order": b.block_order,
                "block_role": b.block_role,
                "section_path": b.section_path,
                "content_format": b.content_format,
                "raw_text": b.raw_text,
                "rich_content_json": _decorate_render_payload(b.rich_content_json),
                "source_page_no": b.source_page_no,
                "is_primary": bool(b.is_primary),
            }
            for b in rows
        ],
    }
