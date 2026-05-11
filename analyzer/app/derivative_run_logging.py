"""衍生层每次生成的文件日志：执行过程 + 单次 LLM 请求/响应 JSON。"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from .config import KNOWLEDGE_RUNS_DIR

logger = logging.getLogger(__name__)

DERIVATIVE_RUNS_ROOT = Path(KNOWLEDGE_RUNS_DIR) / "_derivative_runs"


def derivative_runs_root_resolved() -> str:
    return str(DERIVATIVE_RUNS_ROOT.resolve())


def _ensure_root() -> None:
    DERIVATIVE_RUNS_ROOT.mkdir(parents=True, exist_ok=True)


def sanitize_llm_config_for_log(llm_cfg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not llm_cfg:
        return {}
    out = dict(llm_cfg)
    if out.get("api_key"):
        out["api_key"] = "(redacted)"
    return out


class DerivativeRunSession:
    """单次「生成衍生」运行（按知识点或按包）对应一个子目录。"""

    def __init__(
        self,
        *,
        mode: str,
        knowledge_point_id: Optional[int] = None,
        package_id: Optional[int] = None,
    ) -> None:
        _ensure_root()
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:10]
        self.run_dir = DERIVATIVE_RUNS_ROOT / self.run_id
        self.run_dir.mkdir(parents=True)
        self.log_file = self.run_dir / "run.log"
        self._meta: Dict[str, Any] = {
            "run_id": self.run_id,
            "mode": mode,
            "knowledge_point_id": knowledge_point_id,
            "package_id": package_id,
            "started_at": datetime.now().isoformat(),
            "runs_root": derivative_runs_root_resolved(),
            "run_dir": str(self.run_dir.resolve()),
            "main_log": str(self.log_file.resolve()),
        }
        self._write_header()

    def _write_header(self) -> None:
        header = [
            "=" * 72,
            "衍生层执行日志 (Knowledge Derivative Layer)",
            f"日志根目录（所有次运行）: {self._meta['runs_root']}",
            f"本次运行目录: {self._meta['run_dir']}",
            f"主日志文件（本文件）: {self._meta['main_log']}",
            "元数据:",
            json.dumps(self._meta, ensure_ascii=False, indent=2),
            "=" * 72,
            "",
        ]
        self.log_file.write_text("\n".join(header), encoding="utf-8")

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
        except OSError as exc:
            logger.warning("derivative run log append failed: %s", exc)

    def log_snapshot_brief(self, snapshot: Any) -> None:
        blocks_n = len(getattr(snapshot, "blocks", None) or [])
        atoms_n = len(getattr(snapshot, "atoms", None) or [])
        summ = getattr(snapshot, "summary", None) or ""
        name = getattr(snapshot, "canonical_name", "") or ""
        self.log(
            f"源快照 kp_id={getattr(snapshot, 'knowledge_point_id', '')} "
            f"canonical_name={name!r} blocks={blocks_n} atoms={atoms_n} "
            f"canonical_summary_len={len(summ)}"
        )

    def log_llm_round(
        self,
        *,
        derivative_type: str,
        audience: str,
        messages: List[Dict[str, Any]],
        llm_cfg: Dict[str, Any],
        raw_response: Optional[str],
        parsed_content: Optional[Dict[str, Any]],
        error: Optional[str] = None,
    ) -> None:
        safe = sanitize_llm_config_for_log(llm_cfg)
        fname = f"llm_{derivative_type}_{audience}.json"
        path = self.run_dir / fname
        n = 1
        while path.exists():
            fname = f"llm_{derivative_type}_{audience}_{n}.json"
            path = self.run_dir / fname
            n += 1
        payload = {
            "derivative_type": derivative_type,
            "target_audience": audience,
            "llm_config": safe,
            "request_messages": messages,
            "response_raw": raw_response,
            "parsed_content": parsed_content,
            "error": error,
        }
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("derivative llm json log failed: %s", exc)
            self.log(f"写入 LLM 详情文件失败: {exc}")
            return
        ok = error is None and parsed_content is not None
        self.log(
            f"LLM 调用 type={derivative_type} audience={audience} ok={ok} "
            f"detail_json={str(path.resolve())}"
        )
        if error:
            self.log(f"ERROR: {error}")

    def to_public_dict(self) -> Dict[str, Any]:
        return dict(self._meta)


def list_recent_runs(limit: int = 40) -> List[Dict[str, Any]]:
    _ensure_root()
    rows: List[Dict[str, Any]] = []
    try:
        subdirs = sorted(
            [p for p in DERIVATIVE_RUNS_ROOT.iterdir() if p.is_dir()],
            key=lambda p: p.name,
            reverse=True,
        )[: max(1, limit)]
    except OSError:
        return []
    for p in subdirs:
        log_f = p / "run.log"
        try:
            st = log_f.stat() if log_f.is_file() else p.stat()
            mtime = st.st_mtime
        except OSError:
            mtime = 0
        rows.append(
            {
                "run_id": p.name,
                "run_dir": str(p.resolve()),
                "main_log": str(log_f.resolve()) if log_f.is_file() else None,
                "mtime": mtime,
            }
        )
    return rows


def read_run_log(run_id: str, *, max_chars: int = 256_000) -> Dict[str, Any]:
    safe = run_id.replace("..", "").strip("/\\")
    run_dir = DERIVATIVE_RUNS_ROOT / safe
    if not run_dir.is_dir():
        return {"error": "not_found", "run_id": run_id}
    log_path = run_dir / "run.log"
    text = ""
    if log_path.is_file():
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"error": str(exc), "run_id": run_id}
        if len(text) > max_chars:
            text = text[-max_chars:]
            text = "...(截断，仅保留末尾)...\n" + text
    return {
        "run_id": safe,
        "run_dir": str(run_dir.resolve()),
        "runs_root": derivative_runs_root_resolved(),
        "main_log": str(log_path.resolve()),
        "content": text,
    }
