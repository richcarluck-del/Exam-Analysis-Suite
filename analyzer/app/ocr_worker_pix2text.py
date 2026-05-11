"""
Pix2Text OCR 子进程入口。

主进程（题库解析服务）通常运行在 `.venv_commercial`，而 Pix2Text 依赖栈较重、且会与主环境的 huggingface-hub 等版本产生冲突。
因此我们用独立环境 `.venv_ocr` 运行本 worker，通过 stdout 返回识别文本，避免污染主环境。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import tempfile
from pathlib import Path


def _render_pdf_page(pdf_path: Path, page_index_0: int, render_scale: float) -> "Image.Image":
    import fitz
    from PIL import Image

    doc = fitz.open(pdf_path)
    try:
        if page_index_0 < 0 or page_index_0 >= len(doc):
            raise ValueError(f"page_index out of range: {page_index_0} for {pdf_path}")
        page = doc[page_index_0]
        mat = fitz.Matrix(render_scale, render_scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        mode = "RGB" if pix.n == 3 else "RGBA"
        img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if mode == "RGBA":
            img = img.convert("RGB")
        return img
    finally:
        doc.close()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--page", type=int, required=True, help="0-based page index")
    parser.add_argument("--scale", type=float, default=2.0)
    args = parser.parse_args(argv)

    pdf_path = Path(args.pdf)
    img = _render_pdf_page(pdf_path, args.page, args.scale)

    # RapidOCR / 版面检测等会向 stdout 打印「0: 1024x768 … Speed: …ms」类日志；
    # 主进程 subprocess 会整段捕获 stdout，若不隔离则会与 Markdown 混在一起污染题库文本。
    _junk_out = io.StringIO()
    _junk_err = io.StringIO()
    md = ""
    with contextlib.redirect_stdout(_junk_out), contextlib.redirect_stderr(_junk_err):
        from pix2text import Pix2Text
        # 实际 patch：rapidocr TextDetector
        from rapidocr.ch_ppocr_det import main as rapid_det_main

        _orig_text_detector_init = rapid_det_main.TextDetector.__init__

        def _text_detector_init_patched(self, cfg, *args, **kwargs):
            try:
                root = str(Path(__import__("rapidocr").__file__).resolve().parent / "models")
                if isinstance(cfg, dict):
                    if cfg.get("model_root_dir") in (None, ""):
                        cfg["model_root_dir"] = root
                else:
                    # cnstd 传入的可能是类 dict 配置对象
                    cur = getattr(cfg, "get", None)
                    val = cur("model_root_dir") if callable(cur) else None
                    if val in (None, ""):
                        if hasattr(cfg, "__setitem__"):
                            cfg["model_root_dir"] = root
                        else:
                            setattr(cfg, "model_root_dir", root)
            except Exception:
                pass
            return _orig_text_detector_init(self, cfg, *args, **kwargs)

        rapid_det_main.TextDetector.__init__ = _text_detector_init_patched

        # 关闭公式识别：避免当前环境下 LatexOCR/ONNX 模型文件名不匹配导致的失败（先保证“可读文本”稳定）。
        total_configs = {
            "text_formula": {
                "languages": ("en", "ch_sim"),
            },
            "layout": None,
            "table": None,
        }
        want_formula = os.getenv("QUESTION_BANK_PDF_OCR_ENABLE_FORMULA", "").strip().lower() in {"1", "true", "yes", "on"}
        device = os.getenv("PIX2TEXT_DEVICE") or "cpu"
        try:
            if want_formula:
                try:
                    p2t = Pix2Text(
                        total_configs=total_configs,
                        enable_formula=True,
                        enable_table=False,
                        device=device,
                    )
                    page = p2t.recognize_page(img)
                except Exception:
                    p2t = Pix2Text(
                        total_configs=total_configs,
                        enable_formula=False,
                        enable_table=False,
                        device=device,
                    )
                    page = p2t.recognize_page(img)
            else:
                p2t = Pix2Text(
                    total_configs=total_configs,
                    enable_formula=False,
                    enable_table=False,
                    device=device,
                )
                page = p2t.recognize_page(img)
            tmp_dir = Path(tempfile.mkdtemp(prefix="p2t_md_"))
            md = page.to_markdown(out_dir=tmp_dir, markdown_fn=None) or ""
        finally:
            rapid_det_main.TextDetector.__init__ = _orig_text_detector_init

    sys.stdout.write(md.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

