from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker

from analyzer.app.package_point_purity import reclassify_package_point_purity
from shared.database import engine


OUT_DIR = ROOT / "scripts" / "_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-id", type=int, action="append", required=True)
    parser.add_argument("--apply", action="store_true", help="Persist the new purity labels")
    args = parser.parse_args()

    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    results = []
    try:
        for package_id in args.package_id:
            result = reclassify_package_point_purity(session, package_id, apply=args.apply)
            results.append(result)
            print(
                f"package={package_id} title={result.get('package_title')}\n"
                f"  core={result.get('core')} adjacent={result.get('adjacent')} dependency={result.get('dependency')}\n"
                f"  changed={result.get('changed')} reason_counts={result.get('reason_counts')}\n"
            )
        if args.apply:
            session.commit()
        else:
            session.rollback()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUT_DIR / f"package_point_purity_audit_{stamp}.json"
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {out_path}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
