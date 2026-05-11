"""批量补齐 KnowledgePackage 的题目—知识点桥接（KnowledgeQuestionLink）。

使用场景：
- 历史专题包在 _sync_docx_topic_question_knowledge_links 上线前完成摄入，
  KnowledgePackageQuestion 已存在但未写入 KnowledgeQuestionLink；
- 或链接目标知识点未落入本包 KnowledgePackagePoint 集合，导致
  list_package_related_questions 的 INNER JOIN 过滤后分析链缺失。

用法：
  python analyzer/tools/backfill_package_question_bridge.py --package-id 12
  python analyzer/tools/backfill_package_question_bridge.py --all
  python analyzer/tools/backfill_package_question_bridge.py --all --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.database import SessionLocal  # noqa: E402
from shared import models  # noqa: E402
from analyzer.app.knowledge_point_service import backfill_package_question_bridge  # noqa: E402


def _iter_package_ids(db, specified: List[int], all_flag: bool) -> List[int]:
    if specified:
        return list(dict.fromkeys(int(x) for x in specified))
    if all_flag:
        return [int(r[0]) for r in db.query(models.KnowledgePackage.id).order_by(models.KnowledgePackage.id.asc()).all()]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="批量补齐专题包题目—知识点桥接")
    parser.add_argument("--package-id", action="append", type=int, help="指定包 ID；可多次传入")
    parser.add_argument("--all", action="store_true", help="遍历全部知识包")
    parser.add_argument("--dry-run", action="store_true", help="仅输出缺口统计，不写库")
    args = parser.parse_args()

    if not args.package_id and not args.all:
        parser.error("请指定 --package-id 或 --all")

    db = SessionLocal()
    try:
        targets = _iter_package_ids(db, args.package_id or [], args.all)
        if not targets:
            print("未找到任何专题包。")
            return 0

        total_new = 0
        total_fallback = 0
        total_packages_with_gap = 0
        for pid in targets:
            if args.dry_run:
                # 纯统计，不写库：使用 detail 已有字段组装
                from analyzer.app.knowledge_point_service import build_knowledge_package_detail
                pkg = db.query(models.KnowledgePackage).filter(models.KnowledgePackage.id == pid).first()
                if pkg is None:
                    print(f"[{pid}] 不存在，跳过。")
                    continue
                detail = build_knowledge_package_detail(db, pkg)
                gap = int(detail.get("orphan_in_material_count") or 0)
                if gap:
                    total_packages_with_gap += 1
                print(
                    f"[{pid}] {pkg.package_title}: "
                    f"material={detail.get('material_question_count')} "
                    f"bridged={detail.get('bridged_question_count')} "
                    f"gap={gap}"
                )
                continue

            try:
                result = backfill_package_question_bridge(db, pid)
            except ValueError as exc:
                print(f"[{pid}] 错误：{exc}")
                continue

            new_links = int(result.get("new_links") or 0)
            fallback = int(result.get("fallback_links") or 0)
            total_new += new_links
            total_fallback += fallback
            if new_links:
                total_packages_with_gap += 1
            note = result.get("note")
            suffix = f"（{note}）" if note else ""
            print(
                f"[{pid}] material={result.get('material_question_count')} "
                f"bridged={result.get('bridged_question_count')} "
                f"new_links={new_links} fallback={fallback}{suffix}"
            )

        if args.dry_run:
            print(f"\n共 {total_packages_with_gap} 个包存在缺口（dry-run，未写库）。")
        else:
            print(
                f"\n补链完成：新增 KnowledgeQuestionLink={total_new}（其中保底 {total_fallback}），"
                f"涉及包 {total_packages_with_gap} 个。"
            )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
