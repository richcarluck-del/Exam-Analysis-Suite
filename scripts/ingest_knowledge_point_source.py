"""
按当前工作目录下 .env（与生产相同的知识点/LLM/DOCX 开关）对指定 SourceDocument 做知识点专题摄入。

示例（仓库根目录）：
  .venv\\Scripts\\python scripts\\ingest_knowledge_point_source.py 185 --force

环境变量由 shared.database 加载项目根 .env，勿在命令行覆盖 KNOWLEDGE_POINT_DOCX_POINT_MODE=regex，
除非有意只做规则链路。
"""
from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 先于 shared.database：避免继承到的外层 shell 里残留 KNOWLEDGE_POINT_* 覆盖掉项目根 .env
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

from shared.database import SessionLocal  # noqa: E402
from analyzer.app.knowledge_point_parser import KnowledgePointIngestionService  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="知识点专题摄入（读取项目根 .env）")
    p.add_argument("source_document_id", type=int, help="source_documents.id")
    p.add_argument("--force", action="store_true", help="强制重摄入（清旧包后再写）")
    args = p.parse_args()

    def cb(msg: str) -> None:
        print(msg, flush=True)

    db = SessionLocal()
    try:
        r = KnowledgePointIngestionService().ingest_source_document(
            db, args.source_document_id, force_reingest=args.force, progress_callback=cb
        )
        print("RESULT", r, flush=True)
    finally:
        db.close()


if __name__ == "__main__":
    main()
