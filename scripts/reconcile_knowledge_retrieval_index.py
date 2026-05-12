"""Audit and reconcile knowledge retrieval documents and search indexes.

This script is intentionally scoped to knowledge-package retrieval data:

  - report active RetrievalDocument coverage per current KnowledgePackage
  - detect active docs that still point at deleted/old packages
  - optionally delete stale retrieval docs from PG + vector/text backends
  - optionally rebuild missing/all current package retrieval docs
  - optionally probe hybrid retrieval with a small query

Default mode is read-only. Use --apply with --clean-stale / --rebuild-* to write.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterable

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine, or_, text
from sqlalchemy.orm import Session, sessionmaker

load_dotenv(ROOT / ".env")

from shared import models
from analyzer.app import vector_db
from analyzer.app.knowledge_point_retriever import (
    KNOWLEDGE_ENTITY_TYPES,
    _delete_existing_documents,
    sync_knowledge_package_retrieval,
)


DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def _as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _package_id_from_doc(doc: models.RetrievalDocument) -> int | None:
    metadata = dict(doc.metadata_json or {})
    package_id = _as_int(metadata.get("package_id"))
    if package_id is not None:
        return package_id
    if doc.entity_type == "knowledge_package":
        return int(doc.entity_id)
    return None


def _knowledge_doc_predicate():
    return or_(
        models.RetrievalDocument.entity_type.in_(
            [
                "knowledge_package",
                "knowledge_point",
                "knowledge_package_point",
                "knowledge_block",
                "knowledge_atom",
                "knowledge_question_bridge",
                "knowledge_derivative",
            ]
        ),
        models.RetrievalDocument.metadata_json["entity_type"].as_string().in_(
            [
                "knowledge_package",
                "knowledge_point",
                "knowledge_package_point",
                "knowledge_block",
                "knowledge_atom",
                "knowledge_question_bridge",
                "knowledge_derivative",
            ]
        ),
    )


def _vector_ids(docs: Iterable[models.RetrievalDocument]) -> list[str]:
    ids: list[str] = []
    for doc in docs:
        metadata = dict(doc.metadata_json or {})
        vector_id = str(metadata.get("vector_id") or "").strip()
        if vector_id:
            ids.append(vector_id)
    return ids


def _backend_presence(vector_ids: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "vector_backend": getattr(vector_db.db.vector_backend, "backend_type", None),
        "text_backend": getattr(vector_db.db.text_backend, "backend_type", None) if vector_db.db.text_backend else None,
        "checked": len(vector_ids),
        "qdrant_present": None,
        "opensearch_present": None,
        "errors": [],
    }
    if not vector_ids:
        return result

    vector_backend = getattr(vector_db.db, "vector_backend", None)
    if getattr(vector_backend, "backend_type", None) == "qdrant":
        try:
            point_ids = [vector_backend._to_point_id(item) for item in vector_ids]
            found = vector_backend.client.retrieve(
                collection_name=vector_backend.collection_name,
                ids=point_ids,
                with_payload=False,
                with_vectors=False,
            )
            result["qdrant_present"] = len(found)
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"qdrant: {exc}")
    elif getattr(vector_backend, "backend_type", None) == "chroma":
        try:
            found = vector_backend.collection.get(ids=vector_ids)
            result["qdrant_present"] = len(found.get("ids") or [])
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"chroma: {exc}")

    text_backend = getattr(vector_db.db, "text_backend", None)
    if text_backend:
        try:
            response = text_backend.client.mget(
                index=text_backend.index_name,
                body={"ids": vector_ids},
            )
            result["opensearch_present"] = sum(1 for item in response.get("docs", []) if item.get("found"))
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"opensearch: {exc}")
    return result


def _current_packages(db: Session, requested_ids: list[int] | None = None) -> list[models.KnowledgePackage]:
    query = db.query(models.KnowledgePackage).order_by(models.KnowledgePackage.id.asc())
    if requested_ids:
        query = query.filter(models.KnowledgePackage.id.in_(requested_ids))
    return list(query.all())


def _active_docs_for_package(db: Session, package_id: int) -> list[models.RetrievalDocument]:
    docs = (
        db.query(models.RetrievalDocument)
        .filter(models.RetrievalDocument.is_active.is_(True))
        .filter(_knowledge_doc_predicate())
        .all()
    )
    return [doc for doc in docs if _package_id_from_doc(doc) == package_id]


def _stale_active_knowledge_docs(db: Session, alive_package_ids: set[int]) -> list[models.RetrievalDocument]:
    docs = (
        db.query(models.RetrievalDocument)
        .filter(models.RetrievalDocument.is_active.is_(True))
        .filter(_knowledge_doc_predicate())
        .all()
    )
    stale: list[models.RetrievalDocument] = []
    for doc in docs:
        package_id = _package_id_from_doc(doc)
        if package_id is not None and package_id not in alive_package_ids:
            stale.append(doc)
    return stale


def _print_package_report(db: Session, packages: list[models.KnowledgePackage]) -> dict[int, dict[str, Any]]:
    print("\n[Package retrieval coverage]")
    report: dict[int, dict[str, Any]] = {}
    for package in packages:
        docs = _active_docs_for_package(db, int(package.id))
        retrieval_ids = [int(doc.id) for doc in docs]
        embedding_count = 0
        if retrieval_ids:
            embedding_count = (
                db.query(models.EmbeddingPoint)
                .filter(models.EmbeddingPoint.retrieval_document_id.in_(retrieval_ids))
                .count()
            )
        by_type: dict[str, int] = {}
        for doc in docs:
            by_type[doc.entity_type] = by_type.get(doc.entity_type, 0) + 1
        backend = _backend_presence(_vector_ids(docs))
        status = "OK" if docs and embedding_count >= len(docs) else "MISSING"
        print(
            f"  package_id={package.id:<5} {status:<8} docs={len(docs):<3} "
            f"embedding_points={embedding_count:<3} qdrant={backend.get('qdrant_present')} "
            f"opensearch={backend.get('opensearch_present')} title={package.package_title}"
        )
        if by_type:
            print(f"    by_type={json.dumps(by_type, ensure_ascii=False, sort_keys=True)}")
        if backend["errors"]:
            print(f"    backend_errors={backend['errors']}")
        report[int(package.id)] = {
            "doc_count": len(docs),
            "embedding_count": embedding_count,
            "by_type": by_type,
            "backend": backend,
        }
    return report


def _probe_hybrid(query: str, top_k: int, *, enable_rerank: bool | None = None) -> None:
    print("\n[Hybrid probe]")
    started = time.perf_counter()
    probe = vector_db.db.hybrid_search_with_debug(
        query_text=query,
        n_results=top_k,
        entity_types=KNOWLEDGE_ENTITY_TYPES,
        metadata_filters=None,
        expanded_query=None,
        enable_rerank=enable_rerank,
    )
    hits = probe.get("hits") or []
    diagnostics = probe.get("diagnostics") or {}
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    print(f"  query={query!r} hits={len(hits)} elapsed_ms={elapsed_ms:.1f}")
    if diagnostics:
        print(f"  diagnostics={json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)}")
    for item in hits[:top_k]:
        metadata = item.get("metadata") or {}
        print(
            "  - "
            f"score={float(item.get('score') or 0.0):.4f} "
            f"source_type={item.get('source_type')} "
            f"entity={metadata.get('entity_type')}:{metadata.get('entity_id')} "
            f"kp={metadata.get('knowledge_point_id')} "
            f"title={metadata.get('title') or metadata.get('knowledge_point_name') or metadata.get('package_title') or ''}"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", type=int, action="append", help="只处理指定 package，可重复")
    ap.add_argument("--clean-stale", action="store_true", help="清理指向旧/已删除 package_id 的 active 知识库检索文档")
    ap.add_argument("--rebuild-missing", action="store_true", help="重建没有 active 检索文档的当前 package")
    ap.add_argument("--rebuild-all", action="store_true", help="重建当前 package 的检索文档")
    ap.add_argument("--probe-query", default=None, help="执行一次 hybrid 探测查询")
    ap.add_argument("--probe-top-k", type=int, default=5)
    ap.add_argument("--disable-rerank", action="store_true", help="probe 时跳过 rerank，仅观察召回阶段")
    ap.add_argument("--apply", action="store_true", help="执行写操作；默认只报告")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        packages = _current_packages(db, args.package_id)
        alive_package_ids = {int(item.id) for item in db.query(models.KnowledgePackage.id).all()}
        print(f"Current packages: {sorted(int(item.id) for item in packages)}")
        report = _print_package_report(db, packages)

        stale_docs = _stale_active_knowledge_docs(db, alive_package_ids)
        print("\n[Stale active knowledge retrieval docs]")
        print(f"  count={len(stale_docs)}")
        stale_by_package: dict[int | None, int] = {}
        for doc in stale_docs:
            pid = _package_id_from_doc(doc)
            stale_by_package[pid] = stale_by_package.get(pid, 0) + 1
        if stale_by_package:
            print(
                "  by_package="
                + json.dumps({str(key): value for key, value in stale_by_package.items()}, ensure_ascii=False, sort_keys=True)
            )

        if args.clean_stale:
            if not args.apply:
                print("  dry-run: add --apply to delete stale docs from PG + search backends")
            else:
                print("  deleting stale docs ...")
                _delete_existing_documents(db, stale_docs)
                db.commit()
                print(f"  deleted={len(stale_docs)}")

        rebuild_ids: list[int] = []
        if args.rebuild_all:
            rebuild_ids = [int(item.id) for item in packages]
        elif args.rebuild_missing:
            rebuild_ids = [pid for pid, item in report.items() if int(item.get("doc_count") or 0) == 0]

        if rebuild_ids:
            print("\n[Rebuild packages]")
            if not args.apply:
                print(f"  dry-run: would rebuild {rebuild_ids}; add --apply to execute")
            else:
                for package_id in rebuild_ids:
                    print(f"  rebuilding package_id={package_id} ...")
                    result = sync_knowledge_package_retrieval(db, package_id)
                    print(f"    result={json.dumps(result, ensure_ascii=False, default=str)}")

        if args.probe_query:
            _probe_hybrid(
                args.probe_query,
                args.probe_top_k,
                enable_rerank=False if args.disable_rerank else None,
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
