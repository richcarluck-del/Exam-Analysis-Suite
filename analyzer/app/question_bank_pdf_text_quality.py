"""
PDF 文本层（PyMuPDF get_text）质量打分：用于决定「保留文本层」还是「整页走 Pix2Text OCR」。

启发式规则（无副作用，不依赖 torch）：
- 私用区 U+E000–U+F8FF、替换字符 U+FFFD：多为数学字体乱映射。
- 常见误映射拉丁字母（如 eth ð）：集合符号区经常抽成奇怪字符。
- 含较多中文时，若出现「逗号分隔数字串 + 空格 + 连续单字母拉丁」等模式，常见于顺序错乱的解析/公式碎片。

返回值 score ∈ [0, 1]，越大越建议对该页做 OCR。阈值由环境变量 QUESTION_BANK_PDF_OCR_THRESHOLD 控制。
"""

from __future__ import annotations

import re
from typing import Any, Dict


_PUA_RE = re.compile("[\U0000e000-\U0000f8ff]")
_REPLACEMENT_RE = re.compile("\ufffd")
# 数字/逗号片段后紧跟孤立的 A B 样式（印刷体 PDF 顺序错乱时较常见）
_DIGITS_THEN_LETTERS_RE = re.compile(
    r"(?:[\d，,\s]{3,})\s*[A-Za-zＡ-Ｚａ-ｚ]\s+[A-Za-zＡ-Ｚａ-ｚ]"
)
# 行内大量孤立单字拉丁字母（非英文单词）
_SINGLE_LATIN_RUN_RE = re.compile(r"\b[A-Za-z]{1}\b(?:\s+[A-Za-z]\b){4,}")


def score_pdf_text_layer_quality(raw_text: str) -> float:
    """对单页 get_text(sort=True) 原始串打分，0≈可用，1≈很可能是乱码/需 OCR。"""
    if raw_text is None:
        return 0.95
    s = raw_text
    if not s.strip():
        return 0.92

    n = max(len(s), 1)
    pua = len(_PUA_RE.findall(s))
    repl = len(_REPLACEMENT_RE.findall(s))

    penalties: list[float] = []
    penalties.append(min(0.55, (pua / n) * 12.0))
    penalties.append(min(0.35, (repl / n) * 10.0))

    bad_latin1 = sum(1 for c in s if c in "ðþÞß")
    penalties.append(min(0.2, bad_latin1 * 0.06))

    cjk = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    if cjk >= 4:
        if _DIGITS_THEN_LETTERS_RE.search(s):
            penalties.append(0.18)
        if _SINGLE_LATIN_RUN_RE.search(s):
            penalties.append(0.12)

    ctrl = sum(1 for c in s if ord(c) < 32 and c not in "\t\n\r")
    penalties.append(min(0.25, (ctrl / n) * 6.0))

    return float(min(1.0, sum(penalties)))


def explain_pdf_text_layer_quality(raw_text: str) -> Dict[str, Any]:
    """调试用：返回子项计数，便于对照阈值。"""
    if raw_text is None:
        return {"score": 0.95, "reason": "null"}
    s = raw_text
    n = max(len(s), 1)
    pua = len(_PUA_RE.findall(s))
    repl = len(_REPLACEMENT_RE.findall(s))
    cjk = sum(1 for c in s if "\u4e00" <= c <= "\u9fff")
    score = score_pdf_text_layer_quality(s)
    return {
        "score": round(score, 4),
        "chars": n,
        "pua_hits": pua,
        "replacement_hits": repl,
        "cjk_hits": cjk,
        "digit_letter_suspicious": bool(_DIGITS_THEN_LETTERS_RE.search(s)),
        "single_latin_run_suspicious": bool(_SINGLE_LATIN_RUN_RE.search(s)),
    }


def should_use_ocr_for_page(score: float, threshold: float) -> bool:
    return score >= threshold
