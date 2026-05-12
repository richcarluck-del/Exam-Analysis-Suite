from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyzer.app import vector_db
from analyzer.app.knowledge_point_retriever import KNOWLEDGE_ENTITY_TYPES


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True, help="测试查询")
    ap.add_argument("--runs", type=int, default=3, help="连续跑几次")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--sleep-seconds", type=float, default=0.0, help="每次之间等待秒数")
    ap.add_argument("--disable-rerank", action="store_true", help="跳过 cross-encoder rerank")
    ap.add_argument("--disable-lightweight-rerank", action="store_true", help="跳过轻量重排")
    ap.add_argument("--mode", choices=["hybrid", "vector"], default="hybrid", help="hybrid 看整链路；vector 只测向量分支")
    args = ap.parse_args()

    for index in range(args.runs):
        started = time.perf_counter()
        if args.mode == "vector":
            hits = vector_db.db.search_with_scores(
                query_text=args.query,
                n_results=args.top_k,
                entity_types=KNOWLEDGE_ENTITY_TYPES,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            print(
                json.dumps(
                    {
                        "run": index + 1,
                        "mode": args.mode,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "hit_count": len(hits),
                        "vector_debug": getattr(vector_db.db.vector_backend, "last_search_debug", {}),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            result = vector_db.db.hybrid_search_with_debug(
                query_text=args.query,
                n_results=args.top_k,
                entity_types=KNOWLEDGE_ENTITY_TYPES,
                enable_rerank=False if args.disable_rerank else None,
                enable_lightweight_rerank=False if args.disable_lightweight_rerank else None,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            diagnostics = result.get("diagnostics") or {}
            print(
                json.dumps(
                    {
                        "run": index + 1,
                        "mode": args.mode,
                        "elapsed_ms": round(elapsed_ms, 3),
                        "vector": diagnostics.get("branches", {}).get("vector"),
                        "text": diagnostics.get("branches", {}).get("text"),
                        "lightweight_rerank": diagnostics.get("branches", {}).get("lightweight_rerank"),
                        "rerank": diagnostics.get("branches", {}).get("rerank"),
                    },
                    ensure_ascii=False,
                )
            )
        if args.sleep_seconds > 0 and index < args.runs - 1:
            time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    main()
