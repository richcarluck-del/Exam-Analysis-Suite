from __future__ import annotations

import io
import os
import sys
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analyzer.app.knowledge_point_dedup import concept_dedup_key, find_existing_knowledge_point


load_dotenv(ROOT / ".env")


def main() -> None:
    engine = create_engine(os.getenv("DATABASE_URL"), pool_pre_ping=True)
    session = sessionmaker(bind=engine)()
    cases = [
        "充分条件的判定",
        "必要条件的判定",
        "充分条件判断",
        "必要不充分条件",
        "全称量词（∀）及其常见表述",
        "全称命题真假的判定",
        "全称命题结构∀x∈M，p(x)",
        "充要条件的等价表示p⇔q",
    ]
    for name in cases:
        decision = find_existing_knowledge_point(session, canonical_name=name)
        if decision.point is None:
            print(f"{name} => NEW reason={decision.reason} key={concept_dedup_key(name)}")
        else:
            print(
                f"{name} => #{decision.point.id} {decision.point.canonical_name} "
                f"reason={decision.reason} score={decision.score:.3f} key={concept_dedup_key(name)}"
            )


if __name__ == "__main__":
    main()
