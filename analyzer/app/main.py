import hashlib
import logging
import mimetypes
import re
import sys

logger = logging.getLogger(__name__)
from datetime import timedelta
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import httpx
from celery.result import AsyncResult
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter as FastAPIRouter
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.responses import FileResponse
from starlette.routing import Router as StarletteRouter

from shared import models
from shared.database import SessionLocal, get_db
from shared.prompt_step_config import resolve_step_prompt, sync_prompt_step_configs
from . import crud, question_bank_views, schemas, security, vector_db

from .config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    KNOWLEDGE_POINT_ENABLED,
    KNOWLEDGE_POINTS_DIR,
    NORMALIZED_DOCUMENTS_DIR,
    QUESTION_BANK_ASSET_DIR,
    QUESTION_BANK_UPLOAD_DIR,
)

if not getattr(StarletteRouter.__init__, "_codebuddy_compat", False):
    _original_starlette_router_init = StarletteRouter.__init__

    def _starlette_router_init_compat(self, *args, **kwargs):
        kwargs.pop("on_startup", None)
        kwargs.pop("on_shutdown", None)
        kwargs.pop("lifespan", None)
        kwargs.pop("middleware", None)
        return _original_starlette_router_init(self, *args, **kwargs)

    _starlette_router_init_compat._codebuddy_compat = True
    StarletteRouter.__init__ = _starlette_router_init_compat

if not hasattr(FastAPIRouter, "add_event_handler"):
    def _router_add_event_handler(self, event_type, func):
        if event_type == "startup":
            if not hasattr(self, "on_startup"):
                self.on_startup = []
            self.on_startup.append(func)
        elif event_type == "shutdown":
            if not hasattr(self, "on_shutdown"):
                self.on_shutdown = []
            self.on_shutdown.append(func)

    FastAPIRouter.add_event_handler = _router_add_event_handler


from .exam_session_bundle_hints import batch_infer_bundle_dirs, display_bundle_dir
from .exam_session_importer import BundleImportError, ExamSessionBundleImportService
from .exam_session_analysis_service import service as exam_analysis_service
from .llm_client import FatalRateLimitError
from .academic_graph_service import service as academic_graph_service



from .knowledge_point_api import register_knowledge_point_routes
from .retriever import hybrid_search

from .tasks import (
    ingest_knowledge_base,
    ingest_knowledge_points_documents,
    ingest_source_document,
    match_exam_session,
    sync_knowledge_points_source_document_retrieval,
)
from .worker import celery_app





app = FastAPI()
if not hasattr(app.router, "on_startup"):
    app.router.on_startup = []
if not hasattr(app.router, "on_shutdown"):
    app.router.on_shutdown = []
if not hasattr(app.router, "lifespan_context"):
    app.router.lifespan_context = None

bundle_import_service = ExamSessionBundleImportService()


for directory in [QUESTION_BANK_UPLOAD_DIR, QUESTION_BANK_ASSET_DIR, NORMALIZED_DOCUMENTS_DIR]:
    Path(directory).mkdir(parents=True, exist_ok=True)

app.mount("/static/question-bank/uploads", StaticFiles(directory=QUESTION_BANK_UPLOAD_DIR), name="question-bank-uploads")
app.mount("/static/question-bank/assets", StaticFiles(directory=QUESTION_BANK_ASSET_DIR), name="question-bank-assets")
app.mount("/static/question-bank/normalized", StaticFiles(directory=NORMALIZED_DOCUMENTS_DIR), name="question-bank-normalized")


@app.get("/api/images")
def serve_image(path: str = Query(..., description="Absolute path to image file")):
    file_path = Path(path).resolve()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {path}")
    try:
        file_path.relative_to(_REPO_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied: path outside project root")
    return FileResponse(str(file_path))


@app.on_event("startup")
def sync_prompt_configs_on_startup():

    db = SessionLocal()
    try:
        sync_prompt_step_configs(db)
    finally:
        db.close()
    # Sync Neo4j entities into the semantic entity index
    try:
        from . import vector_db as vdb
        count = vdb.db.ensure_entity_index()
        if count:
            logger.info("Entity index synced: %d entities", count)
    except Exception as exc:
        logger.warning("Entity index sync skipped: %s", exc)


origins = ["http://localhost:5173", "http://localhost:5174", "http://localhost:8001"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



SUPPORTED_QUESTION_BANK_FILE_EXTENSIONS = {".doc", ".docx", ".pdf", ".txt"}


def get_llm_config():
    db = SessionLocal()
    try:
        providers = crud.get_api_providers(db)
        if not providers or not providers[0].models:
            return None
        provider = providers[0]
        model = provider.models[0]
        api_key = security.decrypt_api_key(provider.encrypted_api_key)
        api_url = str(provider.api_url)
        return {"model_name": model.name, "api_url": api_url, "api_key": api_key}
    finally:
        db.close()


def call_llm(messages: list, llm_config: dict, json_mode: bool = False):
    headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
    payload = {"model": llm_config["model_name"], "messages": messages}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(llm_config["api_url"], headers=headers, json=payload)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except Exception as exc:
        print(f"Error calling LLM: {exc}")
        return None


def _sanitize_upload_stem(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value or "document")
    return cleaned.strip(" ._") or "document"


def _guess_upload_suffix(filename: str, content_type: Optional[str]) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in SUPPORTED_QUESTION_BANK_FILE_EXTENSIONS:
        return suffix

    guessed_suffix = (mimetypes.guess_extension(content_type or "") or "").lower()
    if guessed_suffix == ".text":
        guessed_suffix = ".txt"
    if guessed_suffix in SUPPORTED_QUESTION_BANK_FILE_EXTENSIONS:
        return guessed_suffix
    return suffix


async def _save_question_bank_upload(file: UploadFile, source_id: int) -> tuple[Path, str, str, Optional[str]]:
    original_name = Path(file.filename or "uploaded_document").name
    suffix = _guess_upload_suffix(original_name, file.content_type)
    if suffix not in SUPPORTED_QUESTION_BANK_FILE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix or 'unknown'}")

    upload_dir = Path(QUESTION_BANK_UPLOAD_DIR) / f"source_{source_id}"
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = _sanitize_upload_stem(Path(original_name).stem)
    stored_path = upload_dir / f"{safe_stem}_{uuid4().hex}{suffix}"
    file_hash = hashlib.sha256()

    try:
        with stored_path.open("wb") as target_file:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                target_file.write(chunk)
                file_hash.update(chunk)
    except Exception:
        if stored_path.exists():
            stored_path.unlink()
        raise
    finally:
        await file.close()

    mime_type = file.content_type or mimetypes.guess_type(original_name)[0]
    return stored_path, file_hash.hexdigest(), original_name, mime_type


def _build_task_status_payload(task_id: str):
    async_result = AsyncResult(task_id, app=celery_app)
    payload = {"task_id": task_id, "status": async_result.status}
    if async_result.successful():
        payload["result"] = async_result.result
    elif async_result.failed():
        payload["error"] = str(async_result.result)
    return payload


@app.post("/api/register/")
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    return crud.create_user(db=db, user=user)


@app.post("/api/token")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_phone_number(db, phone_number=form_data.username)
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect phone number or password")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={"sub": user.phone_number},
        expires_delta=access_token_expires,
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/api/providers/", response_model=schemas.APIProvider)
def create_api_provider(provider: schemas.APIProviderCreate, db: Session = Depends(get_db)):
    return crud.create_api_provider(db=db, provider=provider)


@app.get("/api/providers/", response_model=List[schemas.APIProvider])
def read_api_providers(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    providers_from_db = crud.get_api_providers(db, skip=skip, limit=limit)
    response_providers = []
    for provider in providers_from_db:
        response_provider = schemas.APIProvider.from_orm(provider)
        if hasattr(provider, "encrypted_api_key") and provider.encrypted_api_key:
            try:
                decrypted_key = security.decrypt_api_key(provider.encrypted_api_key)
                if len(decrypted_key) > 8:
                    response_provider.display_api_key = f"{decrypted_key[:5]}...{decrypted_key[-4:]}"
                else:
                    response_provider.display_api_key = "Key too short"
            except Exception:
                response_provider.display_api_key = "Decryption failed"
        response_providers.append(response_provider)
    return response_providers


@app.post("/api/providers/{provider_id}/models/", response_model=schemas.LLMModel)
def create_llm_model_for_provider(
    provider_id: int,
    model: schemas.LLMModelCreate,
    db: Session = Depends(get_db),
):
    return crud.create_llm_model(db=db, model=model, provider_id=provider_id)


@app.get("/api/models/", response_model=List[schemas.LLMModel])
def read_llm_models(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_llm_models(db, skip=skip, limit=limit)


@app.post("/api/prompts/", response_model=schemas.Prompt)
def create_prompt(prompt: schemas.PromptCreate, db: Session = Depends(get_db)):
    return crud.create_prompt(db=db, prompt=prompt)


@app.get("/api/prompts/", response_model=List[schemas.Prompt])
def read_prompts(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_prompts(db, skip=skip, limit=limit)


@app.post("/api/prompts/{prompt_id}/versions/", response_model=schemas.PromptVersion)
def create_prompt_version_for_prompt(
    prompt_id: int,
    version: schemas.PromptVersionCreate,
    db: Session = Depends(get_db),
):
    return crud.create_prompt_version(db=db, version=version, prompt_id=prompt_id)


@app.get("/api/all-models", response_model=List[schemas.LLMModel])
def get_all_models(db: Session = Depends(get_db)):
    return crud.get_all_llm_models_with_provider(db)


@app.post("/api/ask")
def ask_question(request: schemas.QuestionRequest, db: Session = Depends(get_db)):
    model = db.query(models.LLMModel).filter(models.LLMModel.id == request.model_id).first()
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    provider = model.provider
    api_key = security.decrypt_api_key(provider.encrypted_api_key)
    api_url = str(provider.api_url)
    llm_config = {"model_name": model.name, "api_url": api_url, "api_key": api_key}

    retrieval = hybrid_search(
        request.question,
        top_k=5,
        llm_config=llm_config,
        llm_caller=call_llm,
    )
    merged_results = retrieval.get("merged_results") or []
    context = retrieval.get("context") or ""

    if not merged_results:
        return {
            "answer": "I couldn't find any information related to your question in the knowledge base.",
            "context": None,
            "retrieval": {
                "keywords": retrieval.get("keywords") or [],
                "warnings": retrieval.get("warnings") or [],
                "merged_results": [],
            },
        }

    prompt_config = resolve_step_prompt(
        db,
        "analyzer.ask.answer_generation",
        variables={"context": context, "question": request.question},
    )
    if not prompt_config or not prompt_config.get("prompt_text"):
        raise HTTPException(status_code=500, detail="未找到 analyzer.ask.answer_generation 提示词配置")

    answer_generation_messages = [
        {
            "role": "user",
            "content": prompt_config.get("prompt_text"),
        },
    ]

    final_answer = call_llm(answer_generation_messages, llm_config)


    return {
        "answer": final_answer,
        "context": context,
        "retrieval": {
            "keywords": retrieval.get("keywords") or [],
            "warnings": retrieval.get("warnings") or [],
            "vector_hits": len(retrieval.get("vector_results") or []),
            "graph_hits": len(retrieval.get("graph_results") or []),
            "merged_results": merged_results,
        },
    }


@app.post("/api/ingest-knowledge", status_code=202)
def trigger_ingestion(request: schemas.IngestRequest):
    task = ingest_knowledge_base.delay(request.model_id)
    return {"task_id": task.id}


@app.get("/api/knowledge-points/ingest/files")
def list_knowledge_points_ingest_files():
    if not KNOWLEDGE_POINT_ENABLED:
        raise HTTPException(status_code=503, detail="知识点功能未启用")
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


@app.post("/api/knowledge-points/ingest", status_code=202)
def ingest_knowledge_points(payload: schemas.KnowledgePointsIngestRequest):
    if not KNOWLEDGE_POINT_ENABLED:
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    task = ingest_knowledge_points_documents.delay(
        payload.files,
        payload.model_id,
        payload.force_reingest,
        payload.sync_retrieval,
    )
    return {"task_id": task.id}


@app.get("/api/knowledge-points/ingest/tasks/{task_id}")
def get_knowledge_points_ingest_task(task_id: str):
    if not KNOWLEDGE_POINT_ENABLED:
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    return _build_task_status_payload(task_id)


@app.post(
    "/api/knowledge-points/documents/{source_document_id}/sync-retrieval",
    response_model=schemas.SourceDocumentTaskResponse,
    status_code=202,
)
def sync_knowledge_points_document_retrieval(source_document_id: int, db: Session = Depends(get_db)):
    if not KNOWLEDGE_POINT_ENABLED:
        raise HTTPException(status_code=503, detail="知识点功能未启用")
    document = crud.get_source_document(db, source_document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Source document not found")
    task = sync_knowledge_points_source_document_retrieval.delay(source_document_id)
    return schemas.SourceDocumentTaskResponse(task_id=task.id, source_document_id=source_document_id)


@app.post("/api/question-bank/sources/", response_model=schemas.ContentSource)
def create_content_source(payload: schemas.ContentSourceCreate, db: Session = Depends(get_db)):
    return crud.create_content_source(db, payload)


@app.get("/api/question-bank/sources/", response_model=List[schemas.ContentSource])
def list_content_sources(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_content_sources(db, skip=skip, limit=limit)


@app.post("/api/question-bank/documents/upload", response_model=schemas.SourceDocument, status_code=201)
async def upload_source_document(
    source_id: int = Form(...),
    file: UploadFile = File(...),
    tenant_id: Optional[int] = Form(None),
    parse_profile: str = Form("default"),
    subject: Optional[str] = Form(None),
    grade: Optional[str] = Form(None),
    year: Optional[int] = Form(None),
    region: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    visibility_scope: str = Form("tenant_private"),
    db: Session = Depends(get_db),
):
    source = crud.get_content_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Content source not found")

    stored_path, file_sha256, original_name, mime_type = await _save_question_bank_upload(file, source_id)

    try:
        payload = schemas.SourceDocumentCreate(
            source_id=source_id,
            tenant_id=tenant_id,
            file_name=original_name,
            file_ext=stored_path.suffix.lstrip("."),
            mime_type=mime_type,
            storage_url=str(stored_path),
            file_sha256=file_sha256,
            parse_profile=parse_profile,
            subject=subject,
            grade=grade,
            year=year,
            region=region,
            title=title,
            visibility_scope=visibility_scope,
        )
        return crud.create_source_document(db, payload)
    except Exception:
        if stored_path.exists():
            stored_path.unlink()
        raise


@app.post("/api/question-bank/documents/", response_model=schemas.SourceDocument)
def create_source_document(payload: schemas.SourceDocumentCreate, db: Session = Depends(get_db)):
    source = crud.get_content_source(db, payload.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Content source not found")
    return crud.create_source_document(db, payload)


@app.get("/api/question-bank/documents/", response_model=List[schemas.SourceDocument])
def list_source_documents(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.get_source_documents(db, skip=skip, limit=limit)


@app.get("/api/question-bank/documents/{source_document_id}", response_model=schemas.SourceDocument)
def get_source_document(source_document_id: int, db: Session = Depends(get_db)):
    document = crud.get_source_document(db, source_document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Source document not found")
    return document


@app.get("/api/question-bank/questions/{question_item_id}", response_model=schemas.QuestionBankQuestionDetail)
def get_question_bank_question(question_item_id: int, db: Session = Depends(get_db)):
    question_detail = question_bank_views.get_question_detail(db, question_item_id)
    if not question_detail:
        raise HTTPException(status_code=404, detail="Question item not found")
    return question_detail


@app.get("/api/question-bank/documents/{source_document_id}/paper", response_model=schemas.QuestionBankPaperDetail)
def get_question_bank_document_paper(source_document_id: int, db: Session = Depends(get_db)):
    paper_detail = question_bank_views.get_source_document_paper_detail(db, source_document_id)
    if not paper_detail:
        raise HTTPException(status_code=404, detail="Paper not found for source document")
    return paper_detail


@app.get("/api/question-bank/papers/{paper_id}", response_model=schemas.QuestionBankPaperDetail)
def get_question_bank_paper(paper_id: int, db: Session = Depends(get_db)):
    paper_detail = question_bank_views.get_paper_detail(db, paper_id)
    if not paper_detail:
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper_detail



@app.post(

    "/api/question-bank/documents/{source_document_id}/ingest",
    response_model=schemas.SourceDocumentTaskResponse,
    status_code=202,
)
def trigger_source_document_ingestion(
    source_document_id: int,
    force_reingest: bool = Query(False),
    db: Session = Depends(get_db),
):
    document = crud.get_source_document(db, source_document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Source document not found")
    task = ingest_source_document.delay(source_document_id, force_reingest)
    return schemas.SourceDocumentTaskResponse(task_id=task.id, source_document_id=source_document_id)


@app.get("/api/question-bank/tasks/{task_id}")
def get_question_bank_task(task_id: str):
    return _build_task_status_payload(task_id)


@app.post("/api/question-bank/search")
def search_question_bank(request: schemas.QuestionBankSearchRequest):
    results = vector_db.db.hybrid_search_with_scores(
        request.query,
        n_results=max(request.top_k * 3, request.top_k),
        entity_types=[
            "question_stem",
            "question_answer",
            "question_analysis",
            "question_solution",
            "question_comment",
            "question_knowledge",
            "question_topic",
        ],
    )
    return {
        "query": request.query,
        "results": results[: request.top_k],
        "backends": vector_db.db.backend_summary,
    }





@app.post("/api/exam-sessions/import-bundle", response_model=schemas.ExamSessionBundleImportResponse, status_code=201)
def import_exam_session_bundle(payload: schemas.ExamSessionBundleImportRequest, db: Session = Depends(get_db)):
    if payload.source_document_id:
        source_document = crud.get_source_document(db, payload.source_document_id)
        if not source_document:
            raise HTTPException(status_code=404, detail="Linked source document not found")
    try:
        return bundle_import_service.import_bundle(db, payload)
    except BundleImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/exam-sessions/", response_model=schemas.ExamSessionDetail, status_code=201)
def create_exam_session(payload: schemas.ExamSessionCreate, db: Session = Depends(get_db)):
    if payload.source_document_id:
        source_document = crud.get_source_document(db, payload.source_document_id)
        if not source_document:
            raise HTTPException(status_code=404, detail="Linked source document not found")
    return crud.create_exam_session(db, payload)



@app.get("/api/exam-sessions/", response_model=List[schemas.ExamSessionListItem])
def list_exam_sessions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    rows = crud.get_exam_sessions(db, skip=skip, limit=limit)
    need_infer = [r.id for r in rows if not r.bundle_dir]
    inferred = batch_infer_bundle_dirs(db, need_infer) if need_infer else {}
    result: List[schemas.ExamSessionListItem] = []
    for r in rows:
        d = schemas.ExamSessionListItem.from_orm(r).dict()
        d["bundle_dir"] = display_bundle_dir(db, r, inferred)
        result.append(schemas.ExamSessionListItem(**d))
    return result


@app.get("/api/exam-sessions/{exam_session_id}", response_model=schemas.ExamSessionDetail)
def get_exam_session(exam_session_id: int, db: Session = Depends(get_db)):
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    merged = display_bundle_dir(db, exam_session, None)
    if merged == exam_session.bundle_dir:
        return exam_session
    data = schemas.ExamSessionDetail.from_orm(exam_session).dict()
    data["bundle_dir"] = merged
    return schemas.ExamSessionDetail(**data)


@app.get("/api/exam-sessions/{exam_session_id}/matches", response_model=List[schemas.ExamSessionQuestionMatchView])
def get_exam_session_matches(exam_session_id: int, db: Session = Depends(get_db)):
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    return crud.build_exam_session_match_views(db, exam_session_id)


@app.post(
    "/api/exam-sessions/{exam_session_id}/match",
    response_model=schemas.ExamSessionTaskResponse,
    status_code=202,
)
def trigger_exam_session_matching(
    exam_session_id: int,
    request: schemas.ExamSessionMatchRequest,
    db: Session = Depends(get_db),
):
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    task = match_exam_session.delay(
        exam_session_id,
        request.top_k,
        request.accept_threshold,
        request.min_gap,
    )
    return schemas.ExamSessionTaskResponse(task_id=task.id, exam_session_id=exam_session_id)


@app.get("/api/exam-sessions/tasks/{task_id}")
def get_exam_session_task(task_id: str):
    return _build_task_status_payload(task_id)


@app.post(
    "/api/exam-sessions/{exam_session_id}/analysis/generate",
    response_model=schemas.AnalysisGenerateResponse,
)
def generate_exam_session_analysis(
    exam_session_id: int,
    sync_neo4j: bool = Query(True),
    db: Session = Depends(get_db),
):
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    try:
        result = exam_analysis_service.generate_reports(
            db,
            exam_session_id,
            sync_neo4j=sync_neo4j,
            persist_snapshot=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FatalRateLimitError as exc:
        raise HTTPException(status_code=503, detail=f"模型限流/额度耗尽，报告生成中断: {exc}")
    if result.get("fatal_error"):
        raise HTTPException(
            status_code=503,
            detail=f"报告生成因模型限流而中断（部分题目已完成并持久化）: {result['fatal_error']}",
        )
    return {
        "exam_session_id": exam_session_id,
        "diagnosis_snapshot_id": result.get("diagnosis_snapshot_id"),
        "surfaces": {
            "student": f"/api/exam-sessions/{exam_session_id}/analysis/student-report",
            "teacher": f"/api/exam-sessions/{exam_session_id}/analysis/teacher-report",
            "governance": f"/api/exam-sessions/{exam_session_id}/analysis/governance-report",
        },
        "summary": result.get("summary") or {},
    }


def _load_or_generate_surface(
    db: Session,
    exam_session_id: int,
    *,
    sync_neo4j: bool,
    force_regenerate: bool = False,
) -> dict:
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")

    if not force_regenerate and exam_session.analysis_status == "completed":
        cached = exam_analysis_service.load_report_surfaces(db, exam_session_id)
        if cached is not None:
            return cached

    result = exam_analysis_service.generate_reports(
        db,
        exam_session_id,
        sync_neo4j=sync_neo4j,
        persist_snapshot=True,
    )
    if result.get("fatal_error"):
        raise HTTPException(
            status_code=503,
            detail=f"报告生成因模型限流而中断（部分题目已完成并持久化）: {result['fatal_error']}",
        )
    return result


@app.get(
    "/api/exam-sessions/{exam_session_id}/analysis/student-report",
    response_model=schemas.StudentReportResponse,
)
def get_exam_session_student_report(
    exam_session_id: int,
    sync_neo4j: bool = Query(True),
    db: Session = Depends(get_db),
):
    result = _load_or_generate_surface(db, exam_session_id, sync_neo4j=sync_neo4j)
    return result["surfaces"]["student"]


@app.get(
    "/api/exam-sessions/{exam_session_id}/analysis/teacher-report",
    response_model=schemas.TeacherReportResponse,
)
def get_exam_session_teacher_report(
    exam_session_id: int,
    sync_neo4j: bool = Query(True),
    db: Session = Depends(get_db),
):
    result = _load_or_generate_surface(db, exam_session_id, sync_neo4j=sync_neo4j)
    return result["surfaces"]["teacher"]


@app.get(
    "/api/exam-sessions/{exam_session_id}/analysis/governance-report",
    response_model=schemas.GovernanceReportResponse,
)
def get_exam_session_governance_report(
    exam_session_id: int,
    sync_neo4j: bool = Query(True),
    db: Session = Depends(get_db),
):
    result = _load_or_generate_surface(db, exam_session_id, sync_neo4j=sync_neo4j)
    return result["surfaces"]["governance"]


@app.post(
    "/api/exam-sessions/{exam_session_id}/analysis/regenerate",
    status_code=202,
)
def regenerate_exam_session_analysis(
    exam_session_id: int,
    sync_neo4j: bool = Query(True),
    db: Session = Depends(get_db),
):
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    exam_session.analysis_status = "pending"
    db.flush()
    try:
        result = exam_analysis_service.generate_reports(
            db,
            exam_session_id,
            sync_neo4j=sync_neo4j,
            persist_snapshot=True,
        )
    except Exception as exc:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"分析重新生成失败: {exc}")
    if result.get("fatal_error"):
        return {
            "exam_session_id": exam_session_id,
            "diagnosis_snapshot_id": result.get("diagnosis_snapshot_id"),
            "status": "partial",
            "message": f"部分题目分析完成，但因模型限流中断: {result['fatal_error']}",
        }
    return {
        "exam_session_id": exam_session_id,
        "diagnosis_snapshot_id": result["diagnosis_snapshot_id"],
        "status": "completed",
        "message": "分析已重新生成并持久化",
    }


@app.post("/api/neo4j/sync/knowledge")
def sync_knowledge_graph_to_neo4j(db: Session = Depends(get_db)):
    try:
        return academic_graph_service.sync_all_knowledge_projection(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Neo4j 知识图同步失败: {exc}") from exc


@app.post("/api/neo4j/sync/exam-sessions/{exam_session_id}")
def sync_exam_session_graph_to_neo4j(exam_session_id: int, db: Session = Depends(get_db)):
    exam_session = crud.get_exam_session(db, exam_session_id)
    if not exam_session:
        raise HTTPException(status_code=404, detail="Exam session not found")
    try:
        analysis_result = exam_analysis_service.generate_reports(
            db,
            exam_session_id,
            sync_neo4j=False,
            persist_snapshot=False,
        )
        if analysis_result.get("fatal_error"):
            raise HTTPException(
                status_code=503,
                detail=f"报告生成因模型限流中断，Neo4j 同步未完成: {analysis_result['fatal_error']}",
            )
        return academic_graph_service.sync_exam_session_state(
            db,
            exam_session_id,
            question_analyses=analysis_result["surfaces"]["student"]["question_analyses"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Neo4j 学情图同步失败: {exc}") from exc


if KNOWLEDGE_POINT_ENABLED:
    register_knowledge_point_routes(app)
