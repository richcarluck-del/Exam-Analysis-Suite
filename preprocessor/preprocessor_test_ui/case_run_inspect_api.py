"""
只读：检视 preprocessor run / mock 目录，聚合 bundle 合同、题目表与资源存在性，供测试 UI 人工核验。
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/case-run-inspect", tags=["case-run-inspect"])
# 与 main.py 中其他 router 一致，满足旧版 include_router 对 on_startup 的访问
if not hasattr(router, "on_startup"):
    router.on_startup = []
if not hasattr(router, "on_shutdown"):
    router.on_shutdown = []
if not hasattr(router, "lifespan_context"):
    router.lifespan_context = None


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _allowed_roots() -> List[Path]:
    root = _project_root()
    return [
        (root / "preprocessor").resolve(),
        (root / "preprocessor" / "tests" / "mock_data").resolve(),
        (root / "preprocessor" / "pictures").resolve(),
    ]


def _is_under_allowed(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for base in _allowed_roots():
        try:
            base_r = base.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(base_r)
            return True
        except ValueError:
            continue
    return False


def _parse_root_dir(raw: str) -> Path:
    text = (raw or "").strip()
    if not text:
        raise ValueError("root_dir 不能为空")
    p = Path(text).expanduser()
    if not p.is_absolute() and not text.startswith("~"):
        p = _project_root() / p
    return p.resolve()


def _strict_join(root: Path, rel: str) -> Path:
    if not rel or not str(rel).strip():
        raise ValueError("rel 不能为空")
    clean = str(rel).strip().replace("\\", "/")
    for part in Path(clean).parts:
        if part in ("", ".", "..") or part.startswith(".."):
            raise ValueError("非法相对路径")
    out = (root / clean).resolve()
    if not _is_under_allowed(out):
        raise ValueError("路径不在允许范围内")
    return out


def _safe_relpath(root: Path, child: Path) -> str:
    try:
        return str(child.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(child)


class SummaryRequest(BaseModel):
    root_dir: str = Field(..., description="run / mock 根目录（绝对路径或相对仓库根）")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _top_level_inventory(root: Path, limit: int = 200) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not root.is_dir():
        return items
    for i, p in enumerate(sorted(root.iterdir(), key=lambda x: (not x.is_file(), x.name.lower()))):
        if i >= limit:
            break
        try:
            st = p.stat()
            items.append(
                {
                    "name": p.name,
                    "is_file": p.is_file(),
                    "is_dir": p.is_dir(),
                    "size_bytes": st.st_size if p.is_file() else None,
                }
            )
        except OSError:
            items.append({"name": p.name, "is_file": p.is_file(), "is_dir": p.is_dir(), "size_bytes": None})
    return items


def _collect_relpaths_for_question(q: Dict[str, Any], root: Path) -> List[Tuple[str, str]]:
    """返回 (角色, 相对或绝对路径)。"""
    pairs: List[Tuple[str, str]] = []
    for key in (
        "question_image_path",
        "answer_image_path",
        "complete_unit_image_path",
    ):
        v = q.get(key)
        if isinstance(v, str) and v.strip():
            pairs.append((key, v.strip()))
    for ap in q.get("answer_image_paths") or []:
        if isinstance(ap, str) and ap.strip():
            pairs.append(("answer_image_paths", ap.strip()))
    src = q.get("source") or {}
    if isinstance(src, dict):
        for k in ("source_corrected_image", "source_part_image", "source_original_image"):
            v = src.get(k)
            if isinstance(v, str) and v.strip():
                pairs.append((f"source.{k}", v.strip()))
    return pairs


def _path_exists_on_disk(root: Path, pstr: str) -> bool:
    if not pstr:
        return False
    if os.path.isabs(pstr) or (len(pstr) > 1 and pstr[1] == ":"):
        return Path(pstr).is_file()
    return (root / pstr).is_file()


def _to_view_rel(root: Path, pstr: str) -> Optional[str]:
    """将题目中的路径规范为相对 root 的 URL 用 rel；无法映射则 None。"""
    pstr = (pstr or "").strip()
    if not pstr:
        return None
    try:
        r = root.resolve()
    except OSError:
        r = root
    if (not os.path.isabs(pstr)) and not (len(pstr) > 1 and pstr[1] == ":"):
        return pstr.replace("\\\\", "/")
    try:
        ap = Path(pstr).resolve()
        return str(ap.relative_to(r))
    except (ValueError, OSError):
        return None


def _build_questions_table(root: Path, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for q in questions:
        if not isinstance(q, dict):
            continue
        qn = str(q.get("question_no") or q.get("number") or "")
        rel_pairs = _collect_relpaths_for_question(q, root)
        missing: List[str] = []
        assets: Dict[str, bool] = {}
        thumb_rel: Optional[str] = None
        for role, p in rel_pairs:
            ok = _path_exists_on_disk(root, p)
            assets[role] = ok
            if not ok:
                missing.append(role)
            if ok and thumb_rel is None and role in (
                "question_image_path",
                "complete_unit_image_path",
            ):
                vr = _to_view_rel(root, p)
                if vr:
                    thumb_rel = vr.replace("\\", "/")
        if thumb_rel is None and rel_pairs:
            for role, p in rel_pairs:
                if _path_exists_on_disk(root, p):
                    vr = _to_view_rel(root, p)
                    if vr:
                        thumb_rel = vr.replace("\\", "/")
                        break
        conf = q.get("confidence") if isinstance(q.get("confidence"), dict) else {}
        rows.append(
            {
                "question_no": qn,
                "question_id": q.get("question_id"),
                "sheet_id": q.get("sheet_id"),
                "question_text_preview": (q.get("question_text") or "")[:280],
                "student_answer": q.get("student_answer"),
                "answer_source": q.get("answer_source"),
                "answer_status": q.get("answer_status"),
                "needs_manual_review": bool(q.get("needs_manual_review")),
                "confidence": conf,
                "assets_ok": len(missing) == 0,
                "missing_roles": missing,
                "thumb_rel": thumb_rel,
            }
        )
    return rows


@router.post("/summary")
def post_summary(body: SummaryRequest) -> Dict[str, Any]:
    try:
        root = _parse_root_dir(body.root_dir)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析目录：{exc}") from exc
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="目录不存在或不是文件夹")
    if not _is_under_allowed(root):
        raise HTTPException(
            status_code=403,
            detail="拒绝访问：仅允许 preprocessor、preprocessor/tests/mock_data、preprocessor/pictures 下的目录",
        )

    manifest_path = root / "manifest.json"
    questions_path = root / "questions.json"
    legacy_meta = root / "metadata.json"
    run_summary_path = root / "run_summary.json"
    complete_units_path = root / "complete_units.json"

    has_manifest = manifest_path.is_file()
    has_questions = questions_path.is_file()
    has_legacy = legacy_meta.is_file() and not has_questions

    manifest: Optional[Dict[str, Any]] = None
    questions_data: Any = None
    warnings: List[str] = []

    if has_manifest:
        try:
            manifest = _read_json(manifest_path)
            if not isinstance(manifest, dict):
                warnings.append("manifest.json 不是 JSON 对象")
        except Exception as exc:
            warnings.append(f"读取 manifest.json 失败：{exc}")
            manifest = None

    if has_questions:
        try:
            questions_data = _read_json(questions_path)
        except Exception as exc:
            warnings.append(f"读取 questions.json 失败：{exc}")
            questions_data = None
    elif has_legacy:
        try:
            questions_data = _read_json(legacy_meta)
            warnings.append("使用兼容格式 metadata.json；建议升级导出为 manifest+questions。")
        except Exception as exc:
            warnings.append(f"读取 metadata.json 失败：{exc}")

    questions_list: List[Dict[str, Any]] = []
    if isinstance(questions_data, list):
        questions_list = [q for q in questions_data if isinstance(q, dict)]
    else:
        if questions_data is not None:
            warnings.append("questions.json 不是数组，analyzer 标准 bundle 需为数组结构")

    manifest_total: Optional[int] = None
    if manifest and isinstance(manifest.get("stats"), dict):
        tq = manifest["stats"].get("total_questions")
        if tq is not None:
            try:
                manifest_total = int(tq)
            except (TypeError, ValueError):
                pass

    complete_units_n: Optional[int] = None
    if complete_units_path.is_file():
        try:
            cu = _read_json(complete_units_path)
            if isinstance(cu, dict):
                complete_units_n = len(cu)
            elif isinstance(cu, list):
                complete_units_n = len(cu)
        except Exception as exc:
            warnings.append(f"读取 complete_units.json 失败：{exc}")

    cross: Dict[str, Any] = {
        "questions_file_count": len(questions_list),
        "manifest_stats_total": manifest_total,
        "complete_units_count": complete_units_n,
        "aligns_with_manifest": None,
        "aligns_with_complete_units": None,
    }
    if manifest_total is not None:
        cross["aligns_with_manifest"] = len(questions_list) == manifest_total
    if complete_units_n is not None and questions_list:
        cross["aligns_with_complete_units"] = complete_units_n == len(questions_list)

    all_missing: List[Dict[str, str]] = []
    for q in questions_list:
        qn = str(q.get("question_no") or "")
        for role, p in _collect_relpaths_for_question(q, root):
            if p and not _path_exists_on_disk(root, p):
                all_missing.append({"question_no": qn, "role": role, "path": p})

    run_summary: Optional[Dict[str, Any]] = None
    if run_summary_path.is_file():
        try:
            rs = _read_json(run_summary_path)
            if isinstance(rs, dict):
                run_summary = rs
        except Exception as exc:
            warnings.append(f"读取 run_summary.json 失败：{exc}")

    contract = {
        "has_manifest": has_manifest,
        "has_questions": has_questions,
        "has_questions_array": has_questions and isinstance(questions_data, list),
        "has_metadata_legacy": has_legacy and not has_questions,
        "import_ready": has_manifest and has_questions and isinstance(questions_data, list),
    }

    return {
        "root_dir": str(root),
        "contract": contract,
        "cross_check": cross,
        "manifest_excerpt": {
            "schema_version": (manifest or {}).get("schema_version"),
            "bundle_id": (manifest or {}).get("bundle_id"),
            "run_id": (manifest or {}).get("run_id"),
            "status": (manifest or {}).get("status"),
            "manifest_warnings": (manifest or {}).get("warnings") or [],
            "stats": (manifest or {}).get("stats"),
            "exam_context": (manifest or {}).get("exam_context"),
            "producer": (manifest or {}).get("producer"),
            "sheet_count": len((manifest or {}).get("sheets") or []) if manifest else 0,
        }
        if manifest
        else None,
        "run_summary": run_summary,
        "file_inventory": _top_level_inventory(root),
        "summary_warnings": warnings,
        "resource_missing": {
            "count": len(all_missing),
            "items": all_missing[:500],
        },
        "questions": _build_questions_table(root, questions_list),
        "total_questions": len(questions_list),
    }


_ALLOWED_FILE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@router.get("/file")
def get_file(
    root: str = Query(..., description="已解析的 run 根目录"),
    rel: str = Query(..., description="相对 root 的正斜杠路径，或仓库内资源相对路径"),
):
    try:
        root_path = _parse_root_dir(root)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析 root：{exc}") from exc
    if not root_path.is_dir():
        raise HTTPException(status_code=404, detail="根目录不存在")
    if not _is_under_allowed(root_path):
        raise HTTPException(status_code=403, detail="拒绝访问该根目录")

    try:
        file_path = _strict_join(root_path, rel)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if file_path.suffix.lower() not in _ALLOWED_FILE_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅允许图片类型资源")

    media = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    return FileResponse(path=str(file_path), media_type=media, filename=file_path.name)
