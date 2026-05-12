"""KP-KP 关系冷启动（Phase P1）。

默认 dry-run，只打印建议关系；加 --apply 才写入 knowledge_point_relations。

关系方向约定：
  prerequisite: source 是 target 的前置概念
  specializes : target 是 source 的特化 / 下位概念
  equivalent  : 两者近似等价或命名等价，保留双向遍历时可视为同义
  related     : 强相关但方向性较弱
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from shared import models


load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL")
OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class RelationSeed:
    source_name: str
    target_name: str
    relation_type: str
    strength: float
    confidence: float
    reason: str


SEEDS: tuple[RelationSeed, ...] = (
    # 集合基础
    RelationSeed("集合的含义与元素属性", "元素与集合的属于关系", "prerequisite", 0.82, 0.86, "元素属于关系依赖集合与元素的基本含义"),
    RelationSeed("集合的含义与元素属性", "集合的表示法（列举法、描述法、图示法）", "prerequisite", 0.82, 0.86, "集合表示法依赖集合基本含义"),
    RelationSeed("集合的含义与元素属性", "子集、真子集与集合相等", "prerequisite", 0.86, 0.88, "子集关系依赖集合与元素属性"),
    RelationSeed("元素与集合的属于关系", "子集、真子集与集合相等", "prerequisite", 0.78, 0.82, "子集判断通常基于元素归属"),
    RelationSeed("子集、真子集与集合相等", "空集是任何集合的子集", "specializes", 0.86, 0.88, "空集子集性质是子集概念的特例"),
    RelationSeed("子集、真子集与集合相等", "有限集子集个数公式", "prerequisite", 0.84, 0.86, "子集个数公式依赖子集概念"),
    RelationSeed("有限集子集个数公式", "真子集个数与元素个数关系（2ⁿ⁻¹）", "specializes", 0.90, 0.90, "真子集个数公式是有限集子集个数的特化"),
    RelationSeed("子集、真子集与集合相等", "真子集个数与元素个数关系（2ⁿ⁻¹）", "prerequisite", 0.84, 0.86, "真子集个数依赖真子集概念"),
    RelationSeed("集合的表示法（列举法、描述法、图示法）", "利用Venn图与补集分析阴影区域", "prerequisite", 0.74, 0.78, "Venn 图分析依赖集合图示法"),
    RelationSeed("集合的表示法（列举法、描述法、图示法）", "常用数集符号（N, N+, Z, Q, R）", "related", 0.62, 0.70, "二者均属于集合表示与符号系统"),
    # 集合运算
    RelationSeed("集合相交的定义", "集合运算的等价转化关系", "prerequisite", 0.80, 0.82, "集合运算转化依赖交集等基本定义"),
    RelationSeed("德摩根定律", "集合运算的等价转化关系", "prerequisite", 0.86, 0.88, "德摩根定律是集合运算转化的核心规则"),
    RelationSeed("集合运算的等价转化关系", "集合运算中端点取舍与验证", "prerequisite", 0.78, 0.80, "端点取舍需要先完成集合运算转化"),
    RelationSeed("集合运算的等价转化关系", "集合运算与不等式结合求解", "prerequisite", 0.76, 0.80, "集合运算与不等式结合求解依赖运算转化"),
    RelationSeed("新定义集合运算（如A⊗B）", "集合运算与不等式结合求解", "related", 0.62, 0.70, "新定义运算常与集合运算综合题相关"),
    RelationSeed("集合的含义与元素属性", "含参集合中元素互异性的验证", "prerequisite", 0.72, 0.78, "含参集合元素互异依赖元素属性理解"),
    RelationSeed("子集、真子集与集合相等", "由集合关系求参数的方法", "prerequisite", 0.82, 0.84, "由集合关系求参数依赖子集/相等关系"),
    RelationSeed("集合运算的等价转化关系", "由集合关系求参数的方法", "related", 0.68, 0.74, "集合关系参数题常需运算等价转化"),
    # 条件与命题
    RelationSeed("定义与条件关系", "充分条件", "prerequisite", 0.72, 0.78, "充分条件概念依赖定义与条件关系"),
    RelationSeed("定义与条件关系", "必要条件", "prerequisite", 0.72, 0.78, "必要条件概念依赖定义与条件关系"),
    RelationSeed("充分条件", "充要条件", "prerequisite", 0.92, 0.94, "充要条件同时依赖充分条件"),
    RelationSeed("必要条件", "充要条件", "prerequisite", 0.92, 0.94, "充要条件同时依赖必要条件"),
    RelationSeed("充分条件", "充分不必要条件", "specializes", 0.88, 0.88, "充分不必要条件是充分条件分类下的特例"),
    RelationSeed("必要条件", "必要不充分条件", "specializes", 0.88, 0.88, "必要不充分条件是必要条件分类下的特例"),
    RelationSeed("充分条件", "既不充分也不必要条件", "related", 0.62, 0.70, "同属条件关系分类体系"),
    RelationSeed("必要条件", "既不充分也不必要条件", "related", 0.62, 0.70, "同属条件关系分类体系"),
    RelationSeed("充分不必要条件", "充分不必要条件的逆否等价", "prerequisite", 0.84, 0.84, "逆否等价讨论依赖充分不必要条件"),
    RelationSeed("逆命题", "充分不必要条件的逆否等价", "prerequisite", 0.76, 0.80, "逆否等价依赖逆命题相关概念"),
    RelationSeed("判定定理与条件关系", "充分条件", "related", 0.64, 0.72, "判定定理常用于充分性判断"),
    RelationSeed("性质定理与条件关系", "必要条件", "related", 0.64, 0.72, "性质定理常用于必要性分析"),
    # 量词与命题
    RelationSeed("全称量词", "全称命题", "prerequisite", 0.90, 0.92, "全称命题依赖全称量词"),
    RelationSeed("存在量词", "特称命题", "prerequisite", 0.90, 0.92, "特称命题依赖存在量词"),
    RelationSeed("全称量词", "全称量词命题", "specializes", 0.86, 0.88, "全称量词命题是全称量词的命题化应用"),
    RelationSeed("存在量词", "存在量词命题", "specializes", 0.86, 0.88, "存在量词命题是存在量词的命题化应用"),
    RelationSeed("全称命题", "全称量词命题", "equivalent", 0.88, 0.86, "二者在当前教材语境中近似同义"),
    RelationSeed("特称命题", "存在量词命题", "equivalent", 0.88, 0.86, "二者在当前教材语境中近似同义"),
    RelationSeed("全称命题", "含量词命题的否定", "prerequisite", 0.88, 0.90, "含量词命题否定依赖全称命题"),
    RelationSeed("特称命题", "含量词命题的否定", "prerequisite", 0.88, 0.90, "含量词命题否定依赖特称命题"),
    RelationSeed("全称量词", "含量词命题的否定", "prerequisite", 0.82, 0.86, "量词互换是否定规则核心"),
    RelationSeed("存在量词", "含量词命题的否定", "prerequisite", 0.82, 0.86, "量词互换是否定规则核心"),
    RelationSeed("含量词命题的否定", "命题与否定的真假关系", "prerequisite", 0.86, 0.88, "否定命题真假关系依赖命题否定"),
    RelationSeed("全称命题", "双量词命题的类型", "prerequisite", 0.72, 0.78, "双量词命题类型依赖单量词命题"),
    RelationSeed("特称命题", "双量词命题的类型", "prerequisite", 0.72, 0.78, "双量词命题类型依赖单量词命题"),
    RelationSeed("恒成立与存在性问题", "恒成立转化最值", "prerequisite", 0.90, 0.92, "最值转化是恒成立问题的典型方法"),
)


def _load_name_map(session) -> dict[str, models.KnowledgePoint]:
    rows = session.query(models.KnowledgePoint).filter(models.KnowledgePoint.is_active.is_(True)).all()
    return {str(row.canonical_name): row for row in rows}


def _resolve_seeds(session) -> list[dict]:
    by_name = _load_name_map(session)
    resolved: list[dict] = []
    missing: list[dict] = []
    seen: set[tuple[int, int, str]] = set()
    for seed in SEEDS:
        src = by_name.get(seed.source_name)
        tgt = by_name.get(seed.target_name)
        if not src or not tgt:
            missing.append(
                {
                    "source_name": seed.source_name,
                    "target_name": seed.target_name,
                    "relation_type": seed.relation_type,
                    "missing": "source" if not src else "target",
                }
            )
            continue
        key = (int(src.id), int(tgt.id), seed.relation_type)
        if key in seen or src.id == tgt.id:
            continue
        seen.add(key)
        resolved.append(
            {
                "source_id": int(src.id),
                "source_name": src.canonical_name,
                "target_id": int(tgt.id),
                "target_name": tgt.canonical_name,
                "relation_type": seed.relation_type,
                "strength_score": seed.strength,
                "confidence": seed.confidence,
                "reason": seed.reason,
            }
        )
    if missing:
        print(f"[warn] 有 {len(missing)} 条 seed 因 KP 名不存在被跳过")
    return resolved


def _existing_signatures(session) -> set[tuple[int, int, str]]:
    rows = session.query(
        models.KnowledgePointRelation.source_knowledge_point_id,
        models.KnowledgePointRelation.target_knowledge_point_id,
        models.KnowledgePointRelation.relation_type,
    ).all()
    return {(int(a), int(b), str(c)) for a, b, c in rows}


def _write_csv(rows: Iterable[dict], path: Path) -> None:
    rows = list(rows)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "source_id",
                "source_name",
                "relation_type",
                "target_id",
                "target_name",
                "strength_score",
                "confidence",
                "reason",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _print_summary(rows: list[dict]) -> None:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["relation_type"]] = counts.get(row["relation_type"], 0) + 1
    print("\nKP-KP 冷启动候选关系：")
    for relation_type, count in sorted(counts.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {relation_type:<14} {count}")
    print(f"  {'TOTAL':<14} {len(rows)}")
    print("\n前 20 条：")
    for row in rows[:20]:
        print(
            f"  #{row['source_id']} {row['source_name']} "
            f"-[{row['relation_type']}]-> "
            f"#{row['target_id']} {row['target_name']} "
            f"(strength={row['strength_score']:.2f}, conf={row['confidence']:.2f})"
        )


def apply_rows(session, rows: list[dict], rollback_path: Path) -> int:
    existing = _existing_signatures(session)
    to_insert = [row for row in rows if (row["source_id"], row["target_id"], row["relation_type"]) not in existing]
    if not to_insert:
        return 0

    created_ids: list[int] = []
    for row in to_insert:
        rel = models.KnowledgePointRelation(
            source_knowledge_point_id=row["source_id"],
            target_knowledge_point_id=row["target_id"],
            relation_type=row["relation_type"],
            strength_score=row["strength_score"],
            evidence_block_id=None,
            source_origin="cold_start",
            confidence=row["confidence"],
            approved_status="pending",
        )
        session.add(rel)
        session.flush()
        created_ids.append(int(rel.id))
    with rollback_path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "ts": datetime.now().isoformat(),
                    "undo_hint": "delete_created_knowledge_point_relations",
                    "created_relation_ids": created_ids,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return len(to_insert)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写入 knowledge_point_relations（默认 dry-run）")
    ap.add_argument("--csv", type=Path, default=None, help="输出候选关系 CSV")
    ap.add_argument("--rollback-log", type=Path, default=None, help="rollback JSONL 输出路径")
    args = ap.parse_args()

    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    session = Session()

    rows = _resolve_seeds(session)
    existing = _existing_signatures(session)
    for row in rows:
        row["status"] = "exists" if (row["source_id"], row["target_id"], row["relation_type"]) in existing else "new"

    _print_summary(rows)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = args.csv or OUT_DIR / f"kp_relation_cold_start_{ts}.csv"
    _write_csv(rows, csv_path)
    print(f"\nCSV 已写入：{csv_path}")

    if not args.apply:
        print("\n（dry-run：未写库；加 --apply 真写）")
        return

    rollback_path = args.rollback_log or OUT_DIR / f"kp_relation_cold_start_rollback_{ts}.jsonl"
    try:
        inserted = apply_rows(session, rows, rollback_path)
        session.commit()
    except Exception:
        session.rollback()
        raise
    print(f"\n已写入新关系：{inserted}")
    print(f"Rollback 日志：{rollback_path}")
    print("--- DONE ---")


if __name__ == "__main__":
    main()
