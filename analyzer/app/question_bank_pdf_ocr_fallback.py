"""
可选依赖 Pix2Text：将 PDF 单页渲染为位图后做版面+公式 OCR，输出含 $...$ 的 Markdown 风格纯文本。

安装：pip install -r analyzer/requirements-ocr.txt
本项目建议在独立环境 `.venv_ocr` 安装 Pix2Text（避免污染主环境依赖），并通过子进程调用。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .config import QUESTION_BANK_ASSET_DIR, QUESTION_BANK_PDF_OCR_ENABLE_FORMULA

logger = logging.getLogger(__name__)

# 由知识点摄入线程注入：将诊断信息写入 run.log 并推到 WebSocket（与 progress_callback 同源）
_ingest_line_emitter: Optional[Callable[[str], None]] = None


def set_ingest_line_emitter(fn: Optional[Callable[[str], None]]) -> None:
    global _ingest_line_emitter
    _ingest_line_emitter = fn


def _emit_ingest_line(message: str) -> None:
    fn = _ingest_line_emitter
    if not fn or not (message or "").strip():
        return
    try:
        fn(message.strip())
    except Exception:
        pass

# RapidOCR/YOLO 等偶发仍写入真实 fd1；与正文混排时的典型片段（用于兜底剔除）
_OCR_CONSOLE_JUNK_RES = (
    re.compile(r"^\s*\d+:\s*\d+\s*x\s*\d+", re.I),
    re.compile(r"Speed:\s*[\d.]+\s*ms\s+preprocess", re.I),
    re.compile(r"preprocess,\s*[\d.]+ms\s+inference", re.I),
    re.compile(r"per image at shape\s*\(", re.I),
    re.compile(r"\d+\s+titles?,\s*\d+\s+plain texts?", re.I),
)


def _strip_ocr_worker_console_junk(text: str) -> str:
    """去掉误混入识别结果的检测器控制台行（子进程 stdout 曾与正文拼接）。"""
    if not (text or "").strip():
        return (text or "").strip()
    # 与正文同一行、无换行时：从「0: WxH」到「shape (…)」整段剔除
    text = re.sub(
        r"\b\d+:\s*\d+\s*x\s*\d+\s.{0,800}?per image at shape\s*\([^)]{0,120}\)",
        "",
        text,
        flags=re.I | re.DOTALL,
    )
    kept: list[str] = []
    for line in text.splitlines():
        if any(rx.search(line) for rx in _OCR_CONSOLE_JUNK_RES):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def _maybe_append_page_raster_markdown(path: Path, page_index_0: int, render_scale: float) -> str:
    """在 QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER=1 时，把本页 PDF 光栅存到静态资源目录并返回 Markdown 图链（供对照公式）。"""
    from .config import QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER

    if not QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER:
        return ""
    import fitz

    try:
        key = hashlib.sha256(str(path.resolve()).encode("utf-8", errors="surrogateescape")).hexdigest()[:16]
        scale_part = f"{render_scale:.2f}".rstrip("0").rstrip(".").replace(".", "p")
        fname = f"page_{page_index_0 + 1}_s{scale_part}.png"
        out_dir = Path(QUESTION_BANK_ASSET_DIR) / "ocr_rasters" / key
        out_path = out_dir / fname
        out_dir.mkdir(parents=True, exist_ok=True)
        if not out_path.exists():
            doc = fitz.open(path)
            try:
                page = doc[page_index_0]
                mat = fitz.Matrix(render_scale, render_scale)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                pix.save(str(out_path))
            finally:
                doc.close()
    except Exception as exc:
        logger.warning("OCR page raster save failed file=%s page=%s err=%s", path, page_index_0, exc)
        return ""
    url_path = f"/static/question-bank/assets/ocr_rasters/{key}/{fname}"
    pn = page_index_0 + 1
    return (
        f"\n\n---\n"
        f"> **本页 OCR 对照图**（PDF 第 **{pn}** 页整页渲染；上标、集合符号等以图为准）\n>\n"
        f"> ![PDF page {pn}]({url_path})\n"
    )


def _ocr_worker_timeout_seconds() -> float:
    try:
        return float(os.getenv("QUESTION_BANK_OCR_WORKER_TIMEOUT_SECONDS", "600"))
    except Exception:
        return 600.0


def pix2text_available() -> bool:
    python = _resolve_ocr_python()
    if not python or not Path(python).exists():
        return False
    try:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        probe = subprocess.run(
            [python, "-c", "import pix2text; print('ok')"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=30,
        )
        return probe.returncode == 0 and "ok" in (probe.stdout or "")
    except Exception:
        return False


def _resolve_ocr_python() -> str:
    """返回 OCR 子环境 python.exe 路径（可通过 QUESTION_BANK_OCR_PYTHON 覆盖）。"""
    configured = (os.getenv("QUESTION_BANK_OCR_PYTHON") or "").strip()
    if configured:
        return configured
    repo_root = Path(__file__).resolve().parents[2]
    return str(repo_root / ".venv_ocr" / "Scripts" / "python.exe")


def ocr_pdf_page_to_text(path: Path, page_index_0: int, render_scale: float = 2.0) -> str:
    """
    调用独立 OCR 环境运行 Pix2Text：将 path 中第 page_index_0 页（0 起）识别为文本。
    """
    python = _resolve_ocr_python()
    if not python or not Path(python).exists():
        return ""
    worker = Path(__file__).resolve().parent / "ocr_worker_pix2text.py"
    try:
        env = os.environ.copy()
        env["QUESTION_BANK_PDF_OCR_ENABLE_FORMULA"] = "true" if QUESTION_BANK_PDF_OCR_ENABLE_FORMULA else "false"
        # 避免 Windows 控制台默认编码导致 stderr/stdout 解码异常
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUTF8", "1")
        proc = subprocess.run(
            [python, str(worker), "--pdf", str(path), "--page", str(page_index_0), "--scale", str(render_scale)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=_ocr_worker_timeout_seconds(),
        )
        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "")[-4000:]
            logger.warning("Pix2Text OCR worker failed: code=%s stderr_tail=%s", proc.returncode, stderr_tail)
            _emit_ingest_line(
                f"[OCR] worker failed exit={proc.returncode} page={page_index_0 + 1} file={path.name} stderr_tail={stderr_tail}"
            )
            return ""
        text = _strip_ocr_worker_console_junk((proc.stdout or "").strip())
        text = (text + _maybe_append_page_raster_markdown(path, page_index_0, render_scale)).strip()
        return text
    except subprocess.TimeoutExpired:
        logger.warning("Pix2Text OCR worker timeout: file=%s page=%s", path, page_index_0)
        _emit_ingest_line(f"[OCR] worker timeout page={page_index_0 + 1} file={path.name}")
        return ""
    except Exception as exc:
        logger.exception("Pix2Text OCR worker error for %s page %s: %s", path, page_index_0, exc)
        return ""
