"""一次性扫描：题库 SourceDocument 与 专题包 在 向量(检索文档+嵌入) 与 图谱 上的就绪情况。
运行：仓库根目录  .\\.venv\\Scripts\\python scripts/scan_vector_graph_readiness.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional, Set

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from shared.database import SessionLocal
from shared import models


def _sid_from_metadata(meta: Any) -> Optional[int]:
    if not meta:
        return None
    if isinstance(meta, dict):
        v = meta.get("source_document_id")
    else:
        return None
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def main() -> None:
    session: Session = SessionLocal()
    try:
        # --- source_documents 概览 ---
        rows = (
            session.query(
                models.SourceDocument.parse_profile,
                models.SourceDocument.parse_status,
                func.count(models.SourceDocument.id),
            )
            .group_by(models.SourceDocument.parse_profile, models.SourceDocument.parse_status)
            .all()
        )
        by_prof: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for prof, st, c in rows:
            by_prof[prof or ""][(st or "")] += int(c)
        total_sd = session.query(func.count(models.SourceDocument.id)).scalar() or 0

        # 逐条 source_document：便于归类「题库 / 专题」
        sdocs = (
            session.query(
                models.SourceDocument.id,
                models.SourceDocument.parse_profile,
                models.SourceDocument.parse_status,
                models.SourceDocument.file_name,
            )
            .order_by(models.SourceDocument.id)
            .all()
        )

        # 所有 retrieval_document：按 metadata 里的 source_document_id 建索引
        rdocs = (
            session.query(models.RetrievalDocument.id, models.RetrievalDocument.metadata_json)
            .filter(models.RetrievalDocument.is_active.is_(True))
            .all()
        )
        sid_to_rd: Dict[int, Set[int]] = defaultdict(set)
        for rid, meta in rdocs:
            sid = _sid_from_metadata(meta)
            if sid is not None:
                sid_to_rd[sid].add(rid)

        # embedding 覆盖
        if rdocs:
            rd_ids = [r[0] for r in rdocs]
            emb_counts = (
                session.query(
                    models.EmbeddingPoint.retrieval_document_id,
                    func.count(models.EmbeddingPoint.id),
                )
                .filter(models.EmbeddingPoint.retrieval_document_id.in_(rd_ids))
                .group_by(models.EmbeddingPoint.retrieval_document_id)
                .all()
            )
            rd_to_emb: Dict[int, int] = {r[0]: int(r[1]) for r in emb_counts}
        else:
            rd_to_emb = {}

        def class_doc(prof: Optional[str], name: str) -> str:
            p = (prof or "default").lower()
            if p == "knowledge_point" or "专题" in (name or ""):
                return "专题资料"
            return "题库"

        # 题库：向量就绪 = parse success + 有 sid 命中的 rd + 每条 rd 至少 1 个 embedding（实践：有任意 emb 即算已入向量库）
        qb_stats: List[Dict[str, Any]] = []
        for sid, prof, st, fn in sdocs:
            if class_doc(prof, fn) != "题库":
                continue
            rids = list(sid_to_rd.get(sid, []))
            n_rd = len(rids)
            n_rd_with_vec = sum(1 for r in rids if rd_to_emb.get(r, 0) > 0)
            if n_rd == 0:
                vector_state = "无检索文档(无法入向量，除非重切题/补写 RetrievalDocument)"
            elif n_rd_with_vec < n_rd:
                vector_state = f"部分已向量化: {n_rd_with_vec}/{n_rd} 条有 EmbeddingPoint"
            elif n_rd_with_vec == n_rd and n_rd > 0:
                vector_state = f"已向量化: {n_rd} 条检索块均有向量"
            else:
                vector_state = "有检索文档但未发现 Embedding（可跑 index_document_questions 补量）" if n_rd else "无"

            qb_stats.append(
                {
                    "id": sid,
                    "file_name": (fn or "")[:80],
                    "parse_status": st,
                    "retrieval_rows": n_rd,
                    "embedding_covered": n_rd_with_vec,
                    "vector_state": vector_state,
                }
            )

        # 专题包：1 个或更多
        pkgs = session.query(
            models.KnowledgePackage.id,
            models.KnowledgePackage.package_title,
            models.KnowledgePackage.source_document_id,
            models.KnowledgePackage.parse_status,
        ).order_by(models.KnowledgePackage.id).all()

        def edge_count_for_package(db: Session, package_id: int) -> int:
            return (
                db.query(func.count(models.EntityGraphEdge.id))
                .filter(
                    or_(
                        (models.EntityGraphEdge.source_entity_type == "knowledge_package")
                        & (models.EntityGraphEdge.source_entity_id == package_id),
                    )
                )
                .scalar()
                or 0
            )

        pkg_stats = []
        for pid, title, sdoc_id, pst in pkgs:
            ne = edge_count_for_package(session, int(pid))
            if ne == 0:
                gstate = "无包级图谱边(可 POST graph/projection/package/{id} 或 projection/all)"
            else:
                gstate = f"已有 {ne} 条以包为起点的边"
            # RAG: 有知识点则可能有 retrieval（entity_type 以 knowledge_ 开头），粗略统计
            n_kp = (
                session.query(func.count())
                .select_from(models.KnowledgePackagePoint)
                .filter(models.KnowledgePackagePoint.package_id == int(pid))
                .scalar()
                or 0
            )
            pkg_stats.append(
                {
                    "package_id": int(pid),
                    "title": (title or "")[:80],
                    "source_document_id": sdoc_id,
                    "parse_status": pst,
                    "package_point_count": int(n_kp or 0),
                    "package_graph_edges": int(ne),
                    "graph_state": gstate,
                }
            )

        # 知识点侧检索文档数量（RAG 侧，不按 sid）
        k_rd = (
            session.query(func.count())
            .select_from(models.RetrievalDocument)
            .filter(
                models.RetrievalDocument.entity_type.in_(
                    [
                        "knowledge_point",
                        "knowledge_package",
                        "knowledge_block",
                        "knowledge_atom",
                        "knowledge_question_bridge",
                        "knowledge_derivative",
                    ]
                )
            )
            .scalar()
            or 0
        )
        k_rd_emb = (
            session.query(func.count(func.distinct(models.RetrievalDocument.id)))
            .select_from(models.RetrievalDocument)
            .join(
                models.EmbeddingPoint,
                models.EmbeddingPoint.retrieval_document_id == models.RetrievalDocument.id,
            )
            .filter(
                models.RetrievalDocument.entity_type.in_(
                    [
                        "knowledge_point",
                        "knowledge_package",
                        "knowledge_block",
                        "knowledge_atom",
                        "knowledge_question_bridge",
                        "knowledge_derivative",
                    ]
                )
            )
            .scalar()
            or 0
        )

        total_edges = int(session.query(func.count(models.EntityGraphEdge.id)).scalar() or 0)

        # 汇总句（最有利学情：题库向量 + 专题 RAG + 包投影）
        qb_success = [x for x in qb_stats if (x.get("parse_status") or "") == "success"]
        qb_vec_full = [x for x in qb_success if "已向量化" in (x.get("vector_state") or "")]
        qb_vec_partial = [x for x in qb_success if "部分" in (x.get("vector_state") or "")]
        qb_vec_none = [x for x in qb_success if "无检索文档" in (x.get("vector_state") or "")]
        pkg_g_ok = [p for p in pkg_stats if p["package_graph_edges"] > 0]
        pkg_g_empty = [p for p in pkg_stats if p["package_graph_edges"] == 0]

        out = {
            "source_document_total": int(total_sd),
            "source_by_profile_status": {k: dict(v) for k, v in by_prof.items()},
            "question_bank_docs": {
                "count": len(qb_stats),
                "parse_success": len(qb_success),
                "vector_looks_complete": len(qb_vec_full),
                "vector_partial": len(qb_vec_partial),
                "vector_no_retrieval_docs": len(qb_vec_none),
                "vector_needs_reindex": len(
                    [x for x in qb_success if x.get("retrieval_rows", 0) > 0 and x not in qb_vec_full and "部分" in (x.get("vector_state") or "")]
                ),
            },
            "knowledge_packages": {
                "count": len(pkg_stats),
                "with_graph_edges": len(pkg_g_ok),
                "without_graph_edges": len(pkg_g_empty),
            },
            "global": {
                "retrieval_rows_knowledge_entity_types": int(k_rd),
                "retrieval_knowledge_with_embedding": int(k_rd_emb),
                "entity_graph_edges_total": int(total_edges),
            },
        }

        print(json.dumps(out, ensure_ascii=False, indent=2))
        print("---\n样例(题库前 3 条):", file=sys.stderr)
        for x in qb_stats[:3]:
            print(x, file=sys.stderr)
    finally:
        session.close()


if __name__ == "__main__":
    main()
