import json
import os
from typing import Optional

import fitz
import httpx
from docx import Document
from sqlalchemy.orm import Session

from shared import models
from shared.database import SessionLocal
from shared.llm_step_config import resolve_model_config_by_id, resolve_step_llm_config
from shared.prompt_step_config import resolve_step_prompt, sync_prompt_step_configs

from . import vector_db

from .config import KNOWLEDGE_BASE_DIR, KNOWLEDGE_POINTS_DIR
from .graph_db import db as graph_db
from .knowledge_point_parser import KnowledgePointIngestionService
from .question_bank_parser import QuestionBankIngestionService
from .question_matcher import ExamSessionMatchingService
from .worker import celery_app


def call_llm_for_extraction(prompt_text: str, model_name: str, api_url: str, api_key: str):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": prompt_text},
        ],
        "response_format": {"type": "json_object"},
    }


    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(api_url, headers=headers, json=payload)
            response.raise_for_status()
            json_string = response.json()["choices"][0]["message"]["content"]
            return json.loads(json_string)
    except httpx.HTTPStatusError as exc:
        print(f"HTTP error occurred: {exc.response.status_code} - {exc.response.text}")
    except Exception as exc:
        print(f"An error occurred during LLM call: {exc}")
    return None


def _split_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 150):
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - chunk_overlap
    return chunks


@celery_app.task
def ingest_knowledge_base(model_id: Optional[int] = None):
    db_session: Session = SessionLocal()
    try:
        print(f"开始知识库摄入：model_id={model_id}")
        sync_prompt_step_configs(db_session)

        llm_config = None

        if model_id is not None:
            llm_config = resolve_model_config_by_id(db_session, model_id)
            if not llm_config:
                print(f"未找到模型：model_id={model_id}，跳过摄入。")
                return {"status": "skipped", "reason": "未找到模型"}
        else:
            llm_config = resolve_step_llm_config(
                db_session,
                "analyzer.knowledge_extraction",
                allow_generic_fallback=True,
            )
            if not llm_config:
                print("未找到知识抽取模型配置，跳过摄入。")
                return {"status": "skipped", "reason": "未找到模型配置"}

        api_url = llm_config["api_url"]
        api_key = llm_config["api_key"]
        resolved_model_name = llm_config["model_name"]

        processed_files = []

        for filename in os.listdir(KNOWLEDGE_BASE_DIR):
            filepath = os.path.join(KNOWLEDGE_BASE_DIR, filename)
            if not os.path.isfile(filepath):
                continue

            print(f"正在处理文件：{filepath}")
            content_for_llm = ""
            full_content_for_vector = ""

            try:
                if filename.lower().endswith(".pdf"):
                    doc = fitz.open(filepath)
                    for index, page in enumerate(doc):
                        page_text = page.get_text() or ""
                        full_content_for_vector += page_text
                        if index < 10:
                            content_for_llm += page_text
                    doc.close()
                elif filename.lower().endswith(".docx"):
                    doc = Document(filepath)
                    for para in doc.paragraphs:
                        para_text = para.text + "\n"
                        full_content_for_vector += para_text
                    content_for_llm = full_content_for_vector[:5000]
                elif filename.lower().endswith(".txt"):
                    with open(filepath, "r", encoding="utf-8") as file_obj:
                        full_content_for_vector = file_obj.read()
                    content_for_llm = full_content_for_vector[:5000]
                else:
                    print(f"跳过不支持的文件类型：{filename}")
                    continue

                if content_for_llm:
                    prompt_config = resolve_step_prompt(
                        db_session,
                        "analyzer.knowledge_extraction",
                        variables={"text": content_for_llm},
                    )
                    if not prompt_config or not prompt_config.get("prompt_text"):
                        raise ValueError("未找到 analyzer.knowledge_extraction 提示词配置")

                    extracted_data = call_llm_for_extraction(
                        prompt_config["prompt_text"],
                        resolved_model_name,
                        api_url,
                        api_key,
                    )

                    if extracted_data:
                        graph_db.add_entities_and_relationships(extracted_data)


                if full_content_for_vector:
                    chunks = _split_text(full_content_for_vector)
                    if chunks:
                        metadatas = [{"source": filename} for _ in chunks]
                        ids = [f"{filename}_{index}" for index in range(len(chunks))]
                        vector_db.db.upsert_documents(documents=chunks, metadatas=metadatas, ids=ids)

                processed_files.append(filename)
            except Exception as exc:
                print(f"处理文件失败：{filename}，错误：{exc}")

        return {"status": "complete", "processed_files": processed_files}
    finally:
        db_session.close()


@celery_app.task(name="knowledge_points.ingest_files")
def ingest_knowledge_points_documents(
    files: list[str],
    model_id: Optional[int] = None,
    force_reingest: bool = False,
    sync_retrieval: bool = False,
):
    db_session: Session = SessionLocal()
    try:
        service = KnowledgePointIngestionService()
        result = service.ingest_files_from_knowledge_points_dir(
            db=db_session,
            files=files,
            force_reingest=force_reingest,
            sync_retrieval=sync_retrieval,
        )
        result["model_id"] = model_id
        return result
    finally:
        db_session.close()


@celery_app.task(name="knowledge_points.ingest_source_document")
def ingest_knowledge_points_source_document(
    source_document_id: int,
    force_reingest: bool = False,
    sync_retrieval: bool = False,
):
    db_session: Session = SessionLocal()
    try:
        service = KnowledgePointIngestionService()
        return service.ingest_source_document(
            db=db_session,
            source_document_id=source_document_id,
            force_reingest=force_reingest,
            sync_retrieval=sync_retrieval,
        )
    finally:
        db_session.close()


@celery_app.task(name="knowledge_points.sync_source_document_retrieval")
def sync_knowledge_points_source_document_retrieval(source_document_id: int):
    db_session: Session = SessionLocal()
    try:
        service = KnowledgePointIngestionService()
        return service.sync_source_document_retrieval(
            db=db_session,
            source_document_id=source_document_id,
        )
    finally:
        db_session.close()


@celery_app.task(name="question_bank.ingest_source_document")
def ingest_source_document(source_document_id: int, force_reingest: bool = False):
    db_session: Session = SessionLocal()
    try:
        service = QuestionBankIngestionService()
        return service.ingest_source_document(
            db=db_session,
            source_document_id=source_document_id,
            force_reingest=force_reingest,
        )
    finally:
        db_session.close()


@celery_app.task(name="exam_session.match")
def match_exam_session(
    exam_session_id: int,
    top_k: int = 5,
    accept_threshold: float = 0.78,
    min_gap: float = 0.05,
):
    db_session: Session = SessionLocal()
    try:
        service = ExamSessionMatchingService()
        return service.match_exam_session(
            db=db_session,
            exam_session_id=exam_session_id,
            top_k=top_k,
            accept_threshold=accept_threshold,
            min_gap=min_gap,
        )
    finally:
        db_session.close()
