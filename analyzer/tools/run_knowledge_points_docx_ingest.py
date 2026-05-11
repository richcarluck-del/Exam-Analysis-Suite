"""一次性脚本：强制摄入 analyzer/knowledge_points 目录下所有 .docx（供本地验证）。"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv

# 项目根：.../Exam-Analysis-Suite
ROOT = Path(__file__).resolve().parents[2]
KP_DIR = ROOT / "analyzer" / "knowledge_points"
RUNS_DIR = ROOT / "analyzer" / "_runs"


def _create_ingest_run_dir() -> Path:
    """与 preprocessor knowledge_point_admin 一致：在 _ingest_runs 下建本次目录并初始化 run.log。"""
    root = RUNS_DIR / "_ingest_runs"
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:10]
    run_dir = root / run_id
    (run_dir / "assets").mkdir(parents=True, exist_ok=True)
    (run_dir / "run.log").write_text("", encoding="utf-8")
    return run_dir


def _append_run_log(run_dir: Path, message: str) -> None:
    ts = datetime.now().isoformat()
    with open(run_dir / "run.log", "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="强制摄入 knowledge_points 目录下全部 .docx")
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="开启块级知识点大模型抽取（KNOWLEDGE_POINT_LLM_EXTRACT_ENABLED）",
    )
    parser.add_argument(
        "--no-verbose-run-dir",
        action="store_true",
        help="不创建 _ingest_runs 子目录（不写 docx/、llm/、questions/ 等详细审计文件）",
    )
    args = parser.parse_args()

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    load_dotenv(ROOT / ".env")
    if args.with_llm:
        os.environ["KNOWLEDGE_POINT_LLM_EXTRACT_ENABLED"] = "true"

    docxs = sorted(p.name for p in KP_DIR.glob("*.docx") if p.is_file())
    if not docxs:
        print(f"未找到 .docx：{KP_DIR}")
        return 2

    print(f"目录: {KP_DIR}")
    print("待摄入:", docxs)

    run_dir = None if args.no_verbose_run_dir else _create_ingest_run_dir()
    if run_dir:
        print(f"详细审计目录: {run_dir}")

    from shared.database import SessionLocal
    from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService

    def cb(msg: str) -> None:
        print(msg)
        if run_dir is not None:
            _append_run_log(run_dir, msg)

    db = SessionLocal()
    try:
        svc = KnowledgePointIngestionService(str(KP_DIR))
        result = svc.ingest_files_from_knowledge_points_dir(
            db,
            files=docxs,
            force_reingest=True,
            progress_callback=cb,
            ingest_run_assets_dir=run_dir / "assets" if run_dir else None,
            ingest_run_dir=run_dir,
        )
        print("status:", result.get("status"))
        print("processed_count:", result.get("processed_count"))
        for item in result.get("processed") or []:
            print("---", item)
            pkg_id = item.get("package_id")
            if pkg_id and args.with_llm:
                from shared import models

                db.expire_all()
                pkg = db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == pkg_id).first()
                if pkg and pkg.outline_json:
                    oj = pkg.outline_json
                    dbg = oj.get("llm_ingest_debug") if isinstance(oj, dict) else None
                    if isinstance(dbg, dict) and dbg.get("raw_responses"):
                        print("=== LLM raw (from outline_json.llm_ingest_debug) ===")
                        print(json.dumps(dbg["raw_responses"], ensure_ascii=False, indent=2))
                    qbd = oj.get("question_bridge_llm_debug") if isinstance(oj, dict) else None
                    if isinstance(qbd, dict) and qbd.get("raw_responses"):
                        qr = qbd["raw_responses"]
                        print(
                            "=== 按题桥接 LLM 审计 (outline_json.question_bridge_llm_debug) ==="
                            f" step={qbd.get('step_key')} rank_mode={qbd.get('rank_mode')} 条数={len(qr)}"
                        )
                        preview = qr[:2] if len(qr) > 2 else qr
                        print(json.dumps(preview, ensure_ascii=False, indent=2))
                        if len(qr) > 2:
                            print(f"... 其余 {len(qr) - 2} 条略")
        return 0 if result.get("status") == "complete" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
