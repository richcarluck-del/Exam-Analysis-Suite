"""
C：KP 清洗迁移脚本（PostgreSQL + 可选向量库清理）。

  --dry-run   默认：只打印将执行的动作与 SQL 条数预览，不写库。
  --apply     在同一 PG 事务中执行迁移；成功后写入 rollback JSONL。
  --csv PATH       仅用 CSV 中列出的 KP 行（与子集 `--only-actions` 可合用）
  --enforce-csv-name   CSV 中 canonical_name 必须与库一致
  --purge-vectors-after-commit  COMMIT PG 后对涉及的 KP 逐个调用 analyzer 的 purge（会删 Qdrant/Chroma）。

执行顺序：
  1 MERGE_INTO_CANONICAL
  2 DEMOTE_TO_ATOM
  3 DELETE_EMPTY_IN_PKG
  4 DELETE_ORPHAN

注意：Neo4j 不在 PG 事务内；apply 完成后请按需调用 Analyzer API `/api/neo4j/sync/knowledge` 全量重建。

Rollback 文件为 JSONL：`forward_*` 行记录可重做信息；manual undo 时需按文件中说明逆序补数据（复杂边见「restore_edges」行）。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPTS_DIR))

import os

from dotenv import load_dotenv
from sqlalchemy import bindparam, create_engine, text

load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    sys.stderr.write("缺少 DATABASE_URL\n")
    sys.exit(1)


import kp_cleanup_common as kcc
from sqlalchemy.orm import sessionmaker


def augment_aliases(existing: Any, new_alias: str) -> list[Any]:
    if not new_alias or not str(new_alias).strip():
        return existing if isinstance(existing, list) else []
    nm = str(new_alias).strip()
    if isinstance(existing, list):
        lst = list(existing)
    elif isinstance(existing, str):
        try:
            lst = json.loads(existing)
            if not isinstance(lst, list):
                lst = [existing]
        except json.JSONDecodeError:
            lst = [existing]
    elif existing is None:
        lst = []
    else:
        lst = [existing]
    strs = [str(x).strip() for x in lst if x is not None and str(x).strip()]
    if nm not in strs:
        strs.append(nm)
    return strs


class RollbackJSONL:
    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.fh = path.open("a", encoding="utf-8") if path else None

    def emit(self, record: dict[str, Any]) -> None:
        if self.fh:
            self.fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self.fh.flush()

    def close(self) -> None:
        if self.fh:
            self.fh.close()


def row_to_plain(m: Any) -> dict[str, Any]:
    return dict(m)


def purge_retrieval_docs_pg(conn, kp_id: int, log: RollbackJSONL) -> int:
    """Postgres-only：删 retrieval_documents + embedding_points。

    PG 不提供 `json` 列的等值算子，所以先按 id 圈出需要删的行，再分两步读快照。
    """
    rd_ids = list(
        conn.execute(
            text(
                """
WITH block_ids AS (
    SELECT id FROM knowledge_blocks WHERE knowledge_point_id = :kid
),
atom_ids AS (
    SELECT id FROM knowledge_atoms WHERE knowledge_point_id = :kid
),
kql_ids AS (
    SELECT id FROM knowledge_question_links WHERE knowledge_point_id = :kid
)
SELECT rd.id FROM retrieval_documents rd
WHERE (rd.entity_type = 'knowledge_point' AND rd.entity_id = :kid)
   OR (rd.entity_type = 'knowledge_block' AND rd.entity_id IN (SELECT id FROM block_ids))
   OR (rd.entity_type = 'knowledge_atom' AND rd.entity_id IN (SELECT id FROM atom_ids))
   OR (rd.entity_type = 'knowledge_question_bridge' AND rd.entity_id IN (SELECT id FROM kql_ids))
                """,
            ),
            {"kid": kp_id},
        ).scalars().all(),
    )
    if not rd_ids:
        return 0

    exp = bindparam("ids", expanding=True)
    pre_docs = (
        conn.execute(
            text(
                """
SELECT id, tenant_id, entity_type, entity_id,
       text_for_bm25, text_for_embedding, metadata_json::text AS metadata_json_text,
       is_active, content_hash
FROM retrieval_documents
WHERE id IN :ids
                """,
            ).bindparams(exp),
            {"ids": rd_ids},
        )
        .mappings()
        .all()
    )
    pre_emb = (
        conn.execute(
            text("SELECT * FROM embedding_points WHERE retrieval_document_id IN :ids").bindparams(exp),
            {"ids": rd_ids},
        )
        .mappings()
        .all()
    )
    log.emit(
        {
            "undo_hint": "restore_embed_rows_then_retrieval_documents",
            "kp_id": kp_id,
            "embedding_points_snapshots": [row_to_plain(x) for x in pre_emb],
            "retrieval_documents_snapshots": [row_to_plain(x) for x in pre_docs],
        },
    )

    conn.execute(
        text("DELETE FROM embedding_points WHERE retrieval_document_id IN :ids").bindparams(exp),
        {"ids": rd_ids},
    )
    conn.execute(
        text("DELETE FROM retrieval_documents WHERE id IN :ids").bindparams(exp),
        {"ids": rd_ids},
    )
    return len(rd_ids)


def fetch_ege_for_kp(conn, kp_id: int) -> list[dict]:
    rows = conn.execute(
        text(
            """
SELECT * FROM entity_graph_edges WHERE
  (source_entity_type='knowledge_point' AND source_entity_id=:kid)
 OR (target_entity_type='knowledge_point' AND target_entity_id=:kid)
            """
        ),
        {"kid": kp_id},
    ).mappings().all()
    return [row_to_plain(r) for r in rows]


def delete_ege_for_kp(conn, kp_id: int, log: RollbackJSONL) -> int:
    snap = fetch_ege_for_kp(conn, kp_id)
    if snap:
        log.emit({"undo_hint": "reinsert_entity_graph_edges", "rows": snap})
    res = conn.execute(
        text(
            """
DELETE FROM entity_graph_edges WHERE
  (source_entity_type='knowledge_point' AND source_entity_id=:kid)
 OR (target_entity_type='knowledge_point' AND target_entity_id=:kid)
            """
        ),
        {"kid": kp_id},
    )
    return res.rowcount or 0


def snapshot_knowledge_point(conn, kp_id: int, log: RollbackJSONL) -> dict:
    row = conn.execute(
        text("SELECT * FROM knowledge_points WHERE id = :id"),
        {"id": kp_id},
    ).mappings().one()
    d = row_to_plain(row)
    log.emit({"undo_hint": "restore_knowledge_points_row", "row": d})
    return d


def merge_alias_on_target(conn, tgt_id: int, alias_src_name: str, log: RollbackJSONL) -> None:
    row = conn.execute(
        text("SELECT aliases_json FROM knowledge_points WHERE id=:id"),
        {"id": tgt_id},
    ).scalar()
    merged = augment_aliases(row, alias_src_name)
    before_txt = json.dumps(row if row is not None else [], ensure_ascii=False)
    after_txt = json.dumps(merged, ensure_ascii=False)
    conn.execute(
        text("UPDATE knowledge_points SET aliases_json = CAST(:blob AS json) WHERE id=:id"),
        {"blob": after_txt, "id": tgt_id},
    )
    log.emit(
        {
            "undo_hint": "set_aliases_json",
            "knowledge_point_id": tgt_id,
            "aliases_json_before_snapshot": row,
            "aliases_json_sql_before_text": before_txt,
        },
    )


def migrate_question_links(conn, src: int, tgt: int, log: RollbackJSONL) -> tuple[int, int]:
    rows = conn.execute(
        text("SELECT * FROM knowledge_question_links WHERE knowledge_point_id=:s"),
        {"s": src},
    ).mappings().all()
    n_up = n_del = 0
    for r in rows:
        rid = r["id"]
        qid = r["question_item_id"]
        rtype = r["relation_type"]
        clash = conn.execute(
            text(
                """
SELECT id FROM knowledge_question_links WHERE knowledge_point_id=:t
  AND question_item_id=:q AND relation_type=:r LIMIT 1
                """
            ),
            {"t": tgt, "q": qid, "r": rtype},
        ).scalar()
        log.emit({"undo_hint": "knowledge_question_link_row_restore_or_update", "before": row_to_plain(r)})
        if clash:
            conn.execute(text("DELETE FROM knowledge_question_links WHERE id=:i"), {"i": rid})
            n_del += 1
        else:
            conn.execute(
                text("UPDATE knowledge_question_links SET knowledge_point_id=:t WHERE id=:i"),
                {"t": tgt, "i": rid},
            )
            n_up += 1
    return n_up, n_del


def retarget_foreign_blocks_atoms_derivatives(conn, src: int, tgt: int, log: RollbackJSONL) -> None:
    b_rows = conn.execute(
        text("SELECT id FROM knowledge_blocks WHERE knowledge_point_id=:s"),
        {"s": src},
    ).scalars().all()
    if b_rows:
        log.emit(
            {
                "undo_hint": "reset_knowledge_blocks_knowledge_point_id",
                "pairs": [{"id": bid, "from": tgt, "to": src} for bid in b_rows],
            },
        )
    conn.execute(
        text("UPDATE knowledge_blocks SET knowledge_point_id=:t WHERE knowledge_point_id=:s"),
        {"t": tgt, "s": src},
    )
    atom_rows_before = conn.execute(
        text("SELECT * FROM knowledge_atoms WHERE knowledge_point_id=:s"),
        {"s": src},
    ).mappings().all()
    if atom_rows_before:
        log.emit(
            {
                "undo_hint": "restore_knowledge_atoms_knowledge_point_id",
                "rows": [row_to_plain(x) for x in atom_rows_before],
            },
        )
    conn.execute(
        text("UPDATE knowledge_atoms SET knowledge_point_id=:t WHERE knowledge_point_id=:s"),
        {"t": tgt, "s": src},
    )
    drv = conn.execute(
        text("SELECT * FROM knowledge_derivatives WHERE knowledge_point_id=:s"),
        {"s": src},
    ).mappings().all()
    if drv:
        log.emit(
            {"undo_hint": "restore_knowledge_derivatives_kp_col", "rows": [row_to_plain(x) for x in drv]},
        )
    conn.execute(
        text("UPDATE knowledge_derivatives SET knowledge_point_id=:t WHERE knowledge_point_id=:s"),
        {"t": tgt, "s": src},
    )


def cleanup_knowledge_point_relations(conn, kp_id: int, log: RollbackJSONL) -> None:
    rows = conn.execute(
        text(
            """
SELECT * FROM knowledge_point_relations WHERE
 source_knowledge_point_id=:kid OR target_knowledge_point_id=:kid
            """
        ),
        {"kid": kp_id},
    ).mappings().all()
    if rows:
        log.emit(
            {"undo_hint": "reinsert_knowledge_point_relations", "rows": [row_to_plain(x) for x in rows]},
        )
    conn.execute(
        text(
            """
DELETE FROM knowledge_point_relations WHERE
 source_knowledge_point_id=:kid OR target_knowledge_point_id=:kid
            """
        ),
        {"kid": kp_id},
    )


def delete_kpp_for_kp(conn, kp_id: int, log: RollbackJSONL) -> int:
    rows = conn.execute(
        text("SELECT * FROM knowledge_package_points WHERE knowledge_point_id=:kid"),
        {"kid": kp_id},
    ).mappings().all()
    if rows:
        log.emit(
            {
                "undo_hint": "reinsert_knowledge_package_points",
                "rows": [row_to_plain(x) for x in rows],
            },
        )
    r = conn.execute(text("DELETE FROM knowledge_package_points WHERE knowledge_point_id=:kid"), {"kid": kp_id})
    return int(r.rowcount or 0)


def delete_kp_row(conn, kp_id: int, log: RollbackJSONL) -> None:
    snapshot_knowledge_point(conn, kp_id, log)
    r = conn.execute(text("DELETE FROM knowledge_points WHERE id=:id"), {"id": kp_id})
    log.emit({"forward_deleted_knowledge_points_id": kp_id, "rowcount": r.rowcount})


def op_merge_into_canonical(conn, src_id: int, tgt_id: int, src_name: str, log: RollbackJSONL) -> None:
    merge_alias_on_target(conn, tgt_id, src_name, log)
    purge_retrieval_docs_pg(conn, src_id, log)
    migrate_question_links(conn, src_id, tgt_id, log)
    retarget_foreign_blocks_atoms_derivatives(conn, src_id, tgt_id, log)
    delete_ege_for_kp(conn, src_id, log)
    cleanup_knowledge_point_relations(conn, src_id, log)
    delete_kpp_for_kp(conn, src_id, log)
    delete_kp_row(conn, src_id, log)


def op_demote_to_atom(conn, kp_id: int, parent_id: int, name: str, log: RollbackJSONL) -> None:
    pkg_hint = conn.execute(
        text("SELECT package_id FROM knowledge_atoms WHERE knowledge_point_id=:kid LIMIT 1"),
        {"kid": kp_id},
    ).scalar()
    if pkg_hint is None:
        pkg_hint = conn.execute(
            text("SELECT package_id FROM knowledge_package_points WHERE knowledge_point_id=:kid LIMIT 1"),
            {"kid": kp_id},
        ).scalar()
    pkg_col = pkg_hint if pkg_hint is not None else None
    merge_alias_on_target(conn, parent_id, name, log)
    purge_retrieval_docs_pg(conn, kp_id, log)
    migrate_question_links(conn, kp_id, parent_id, log)
    retarget_foreign_blocks_atoms_derivatives(conn, kp_id, parent_id, log)
    ins = conn.execute(
        text(
            """
INSERT INTO knowledge_atoms (
  knowledge_point_id, package_id, atom_type, canonical_text,
  normalized_json, source_origin, review_status,
  confidence, created_at, updated_at
) VALUES (
  :pid, :pkg, 'method',
  :txt, CAST('{"origin":"demoted_kp"}' AS JSON), 'kp_cleanup', 'draft',
  1.00, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
) RETURNING id
            """
        ),
        {"pid": parent_id, "pkg": pkg_col, "txt": name.strip()},
    )
    atom_new_id = ins.scalar()
    log.emit(
        {
            "undo_hint": "delete_knowledge_atom_created_by_demotion",
            "created_atom_id": atom_new_id,
        },
    )
    delete_ege_for_kp(conn, kp_id, log)
    cleanup_knowledge_point_relations(conn, kp_id, log)
    delete_kpp_for_kp(conn, kp_id, log)
    delete_kp_row(conn, kp_id, log)


def op_delete_kp_only(conn, kp_id: int, log: RollbackJSONL) -> None:
    purge_retrieval_docs_pg(conn, kp_id, log)
    delete_ege_for_kp(conn, kp_id, log)
    cleanup_knowledge_point_relations(conn, kp_id, log)
    delete_kpp_for_kp(conn, kp_id, log)
    delete_kp_row(conn, kp_id, log)


def purge_vectors_postgres_committed(kp_ids: list[int]) -> None:
    """在 PG 已提交后，用 analyzer ORM 删向量后端中的点。"""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    from sqlalchemy.orm import sessionmaker as sm

    eng = create_engine(DATABASE_URL, pool_pre_ping=True)
    Sess = sm(bind=eng)
    session = Sess()
    try:
        from analyzer.app.knowledge_point_retriever import purge_knowledge_point_retrieval_documents

        for kid in sorted(set(kp_ids)):
            n = purge_knowledge_point_retrieval_documents(session, kid)
            print(f"    [vectors] purge_knowledge_point_retrieval_documents(kp={kid}) → {n} docs")
        session.commit()
    finally:
        session.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="KP 清洗迁移（PG 事务 + rollback JSONL）")
    ap.add_argument("--dry-run", action="store_true", help="显式演练（默认不写库，仅需不加 --apply 即可）")
    ap.add_argument("--apply", action="store_true", help="真正执行（单事务）")
    ap.add_argument("--csv", type=Path, help="由 kp_cleanup_proposal 生成的 CSV 路径")
    ap.add_argument(
        "--only-actions",
        type=str,
        default="",
        help="逗号分隔：MERGE_INTO_CANONICAL,DEMOTE_TO_ATOM,DELETE_EMPTY_IN_PKG,DELETE_ORPHAN",
    )
    ap.add_argument(
        "--purge-vectors-after-commit",
        action="store_true",
        help="PG commit 后调用 analyzer purge（需可 import analyzer）",
    )
    ap.add_argument(
        "--rollback-log",
        type=Path,
        default=None,
        help="rollback JSONL 路径；默认 scripts/_out/kp_cleanup_rollback_<ts>.jsonl",
    )
    ap.add_argument(
        "--enforce-csv-name",
        action="store_true",
        help="CSV 与库中 canonical_name 不一致则中止（防手改 CSV 错行）",
    )
    args = ap.parse_args()
    dry_run = not args.apply

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        if args.csv:
            with args.csv.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.DictReader(f))
            decisions = kcc.load_decisions_from_csv(rows)
        else:
            decisions, action_counter, kp_total = kcc.build_kp_cleanup_decisions(session)
            print(f"已从数据库重算决策，KP 总数={kp_total}，动作分布：{dict(action_counter)}")

        only = frozenset(a.strip() for a in args.only_actions.split(",") if a.strip())
        if only:
            decisions = kcc.filter_allowed_actions(decisions, only)

        work = [d for d in decisions if str(d["proposed_action"]) not in ("KEEP", "KEEP_AS_CANONICAL")]

        if args.enforce_csv_name and args.csv:
            for d in work:
                db_name = session.execute(
                    text("SELECT canonical_name FROM knowledge_points WHERE id=:i"),
                    {"i": int(d["id"])},
                ).scalar()
                if db_name is None:
                    raise SystemExit(f"CSV 中 KP #{d['id']} 在库中不存在")
                if (db_name or "").strip() != str(d.get("name") or "").strip():
                    raise SystemExit(f"KP #{d['id']} 名称不一致 CSV={d.get('name')!r} DB={db_name!r}")

        merges = [d for d in work if str(d["proposed_action"]) == "MERGE_INTO_CANONICAL"]
        demotes = [d for d in work if str(d["proposed_action"]) == "DEMOTE_TO_ATOM"]
        deletes_e = [d for d in work if str(d["proposed_action"]) == "DELETE_EMPTY_IN_PKG"]
        deletes_o = [d for d in work if str(d["proposed_action"]) == "DELETE_ORPHAN"]

        merges.sort(key=lambda x: int(x["id"]))
        demotes.sort(key=lambda x: int(x["id"]))
        deletes_e.sort(key=lambda x: int(x["id"]))
        deletes_o.sort(key=lambda x: int(x["id"]))

        print("\n待执行工作包：")
        print(f"  MERGE_INTO_CANONICAL   {len(merges)}")
        print(f"  DEMOTE_TO_ATOM         {len(demotes)}")
        print(f"  DELETE_EMPTY_IN_PKG    {len(deletes_e)}")
        print(f"  DELETE_ORPHAN          {len(deletes_o)}")
        print(f"  模式：{'DRY-RUN' if dry_run else 'APPLY（单事务）'}")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        rb_path = args.rollback_log or (SCRIPTS_DIR / "_out" / f"kp_cleanup_rollback_{ts}.jsonl")
        rb_path.parent.mkdir(parents=True, exist_ok=True)
        log = RollbackJSONL(None if dry_run else rb_path)

        affected_for_vector: list[int] = []

        if dry_run:
            for d in merges:
                src = int(d["id"])
                cc = str(d.get("cluster_canonical_id") or "").strip()
                tgt = int(cc) if cc.isdigit() else -1
                nm = str(d["name"])
                print(
                    f"  [演练] MERGE #{src} → #{tgt} "
                    f"({nm[:40]}…)" if len(nm) > 40 else f"  [演练] MERGE #{src} → #{tgt} {nm!r}",
                )
            for d in demotes:
                src = int(d["id"])
                pid = int(str(d["proposed_parent_kp_id"]).strip())
                nm = str(d["name"])
                print(
                    f"  [演练] DEMOTE #{src} → #{pid} "
                    f"({nm[:40]}…)" if len(nm) > 40 else f"  [演练] DEMOTE #{src} → #{pid} {nm!r}",
                )
            for d in deletes_e:
                print(f"  [演练] DELETE_EMPTY_IN_PKG #{int(d['id'])}")
            for d in deletes_o:
                print(f"  [演练] DELETE_ORPHAN #{int(d['id'])}")
            print("\n（dry-run：未执行写操作；加 --apply 提交单事务）")
        else:
            with engine.begin() as conn:
                log.emit({"meta": "kp_cleanup_start", "dry_run": False, "ts": ts})
                for d in merges:
                    src = int(d["id"])
                    cc = str(d.get("cluster_canonical_id") or "").strip()
                    if not cc.isdigit():
                        raise SystemExit(f"MERGE 行缺少 cluster_canonical_id：KP #{src}")
                    tgt = int(cc)
                    if src == tgt:
                        continue
                    affected_for_vector.extend([src, tgt])
                    print(
                        f"  MERGE #{src} → #{tgt} "
                        f"({str(d['name'])[:40]}…)" if len(str(d["name"])) > 40 else f"  MERGE #{src} → #{tgt} {d['name']!r}",
                    )
                    op_merge_into_canonical(conn, src, tgt, str(d["name"]), log)
                for d in demotes:
                    src = int(d["id"])
                    pid = int(str(d["proposed_parent_kp_id"]).strip())
                    affected_for_vector.extend([src, pid])
                    nm = str(d["name"])
                    print(
                        f"  DEMOTE #{src} → #{pid} "
                        f"({nm[:40]}…)" if len(nm) > 40 else f"  DEMOTE #{src} → #{pid} {nm!r}",
                    )
                    op_demote_to_atom(conn, src, pid, nm, log)
                for d in deletes_e:
                    kid = int(d["id"])
                    affected_for_vector.append(kid)
                    print(f"  DELETE_EMPTY_IN_PKG #{kid}")
                    op_delete_kp_only(conn, kid, log)
                for d in deletes_o:
                    kid = int(d["id"])
                    affected_for_vector.append(kid)
                    print(f"  DELETE_ORPHAN #{kid}")
                    op_delete_kp_only(conn, kid, log)
                log.emit({"meta": "kp_cleanup_end", "dry_run": False})
            log.close()
            print(f"\nRollback 日志已写入：{rb_path}")
            print("逆序人工恢复请参考 JSONL 中 undo_hint 字段（含整行快照）。")

        if args.purge_vectors_after_commit and not dry_run:
            print("\n--purge-vectors-after-commit：清理向量后端 …")
            purge_vectors_postgres_committed(affected_for_vector)

    finally:
        session.close()

    print("\n--- DONE ---")


if __name__ == "__main__":
    main()
