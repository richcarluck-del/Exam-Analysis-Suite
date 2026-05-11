"""
PDF 结构化文本提取器：直接从 PDF 嵌入文本层读取内容，避免 OCR。

核心能力：
- SymbolMT / MT-Extra 等符号字体的 PUA（U+F0xx）→ 标准 Unicode 查表映射
- 使用 rawdict 字符级 bbox 排序，精确还原视觉阅读顺序
- 偏导数 ∂：按 PUA（如 F0B6）及数学字母表中的 PARTIAL DIFFERENTIAL 码位归一为 U+2202，不用几何猜符号
- 通过字号 + y 坐标差检测上标/下标
- 通过字体名判断斜体/粗体
- 按 y 坐标聚行，还原阅读顺序
- 输出两份结果：
    1. plain_text —— 可检索纯文本（PUA 已映射，上标用 Unicode ² ³ 等）
    2. rich_paragraphs —— QuestionRichRenderer 兼容的结构化 JSON
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SymbolMT PUA (U+F0xx) → 标准 Unicode 映射
# ---------------------------------------------------------------------------
_SYMBOL_PUA_MAP: Dict[int, str] = {
    0xF020: " ",
    0xF021: "!",
    0xF022: "\u2200",  # ∀
    0xF023: "#",
    0xF025: "%",
    0xF026: "&",
    0xF027: "\u220B",  # ∋
    0xF028: "(",
    0xF029: ")",
    0xF02A: "\u2217",  # ∗
    0xF02B: "+",
    0xF02C: ",",
    0xF02D: "\u2212",  # −
    0xF02E: ".",
    0xF02F: "/",
    0xF030: "0", 0xF031: "1", 0xF032: "2", 0xF033: "3", 0xF034: "4",
    0xF035: "5", 0xF036: "6", 0xF037: "7", 0xF038: "8", 0xF039: "9",
    0xF03A: ":",
    0xF03B: ";",
    0xF03C: "<",
    0xF03D: "=",
    0xF03E: ">",
    0xF03F: "?",
    0xF040: "\u2245",  # ≅
    # Greek uppercase
    0xF041: "\u0391", 0xF042: "\u0392", 0xF043: "\u03A7", 0xF044: "\u0394",
    0xF045: "\u0395", 0xF046: "\u03A6", 0xF047: "\u0393", 0xF048: "\u0397",
    0xF049: "\u0399", 0xF04A: "\u03D1", 0xF04B: "\u039A", 0xF04C: "\u039B",
    0xF04D: "\u039C", 0xF04E: "\u039D", 0xF04F: "\u039F", 0xF050: "\u03A0",
    0xF051: "\u0398", 0xF052: "\u03A1", 0xF053: "\u03A3", 0xF054: "\u03A4",
    0xF055: "\u03A5", 0xF056: "\u03C2", 0xF057: "\u03A9", 0xF058: "\u039E",
    0xF059: "\u03A8", 0xF05A: "\u0396",
    0xF05B: "[",
    0xF05C: "\u2234",  # ∴
    0xF05D: "]",
    0xF05E: "\u22A5",  # ⊥
    0xF05F: "_",
    0xF060: "\u203E",  # ‾ (overline)
    # Greek lowercase
    0xF061: "\u03B1", 0xF062: "\u03B2", 0xF063: "\u03C7", 0xF064: "\u03B4",
    0xF065: "\u03B5", 0xF066: "\u03C6", 0xF067: "\u03B3", 0xF068: "\u03B7",
    0xF069: "\u03B9", 0xF06A: "\u03D5", 0xF06B: "\u03BA", 0xF06C: "\u03BB",
    0xF06D: "\u03BC", 0xF06E: "\u03BD", 0xF06F: "\u03BF", 0xF070: "\u03C0",
    0xF071: "\u03B8", 0xF072: "\u03C1", 0xF073: "\u03C3", 0xF074: "\u03C4",
    0xF075: "\u03C5", 0xF076: "\u03D6", 0xF077: "\u03C9", 0xF078: "\u03BE",
    0xF079: "\u03C8", 0xF07A: "\u03B6",
    0xF07B: "{",
    0xF07C: "|",
    0xF07D: "}",
    0xF07E: "~",
    # Math operators & relations
    0xF0A0: "\u20AC",  # €
    0xF0A1: "\u03D2",
    0xF0A2: "\u2032",  # ′ (prime)
    0xF0A3: "\u2264",  # ≤
    0xF0A4: "\u2044",  # ⁄
    0xF0A5: "\u221E",  # ∞
    0xF0A6: "\u0192",
    0xF0A7: "\u2663",  # ♣
    0xF0A8: "\u2666",  # ♦
    0xF0A9: "\u2665",  # ♥
    0xF0AA: "\u2660",  # ♠
    0xF0AB: "\u2194",  # ↔
    0xF0AC: "\u2190",  # ←
    0xF0AD: "\u2191",  # ↑
    0xF0AE: "\u2192",  # →
    0xF0AF: "\u2193",  # ↓
    0xF0B0: "\u00B0",  # °
    0xF0B1: "\u00B1",  # ±
    0xF0B2: "\u2033",  # ″
    0xF0B3: "\u2265",  # ≥
    0xF0B4: "\u00D7",  # ×
    0xF0B5: "\u221D",  # ∝
    0xF0B6: "\u2202",  # ∂
    0xF0B7: "\u2022",  # •
    0xF0B8: "\u00F7",  # ÷
    0xF0B9: "\u2260",  # ≠
    0xF0BA: "\u2261",  # ≡
    0xF0BB: "\u2248",  # ≈
    0xF0BC: "\u2026",  # …
    0xF0BD: "\u23D0",
    0xF0BE: "\u23AF",
    0xF0BF: "\u21B5",  # ↵
    0xF0C0: "\u2135",  # ℵ
    0xF0C1: "\u2111",  # ℑ
    0xF0C2: "\u211C",  # ℜ
    0xF0C3: "\u2118",  # ℘
    0xF0C4: "\u2297",  # ⊗
    0xF0C5: "\u2295",  # ⊕
    0xF0C6: "\u2205",  # ∅
    0xF0C7: "\u2229",  # ∩
    0xF0C8: "\u222A",  # ∪
    0xF0C9: "\u2283",  # ⊃
    0xF0CA: "\u2287",  # ⊇
    0xF0CB: "\u2284",  # ⊄
    0xF0CC: "\u2282",  # ⊂
    0xF0CD: "\u2286",  # ⊆
    0xF0CE: "\u2208",  # ∈
    0xF0CF: "\u2209",  # ∉
    0xF0D0: "\u2220",  # ∠
    0xF0D1: "\u2207",  # ∇
    0xF0D2: "\u00AE",  # ®
    0xF0D3: "\u00A9",  # ©
    0xF0D4: "\u2122",  # ™
    0xF0D5: "\u220F",  # ∏
    0xF0D6: "\u221A",  # √
    0xF0D7: "\u22C5",  # ⋅
    0xF0D8: "\u00AC",  # ¬
    0xF0D9: "\u2227",  # ∧
    0xF0DA: "\u2228",  # ∨
    0xF0DB: "\u21D4",  # ⇔
    0xF0DC: "\u21D0",  # ⇐
    0xF0DD: "\u21D1",  # ⇑
    0xF0DE: "\u21D2",  # ⇒
    0xF0DF: "\u21D3",  # ⇓
    0xF0E0: "\u25CA",  # ◊
    0xF0E1: "\u2329",  # ⟨
    0xF0E5: "\u2211",  # ∑
    # 多行定界符：仅保留中间部件，顶底部件映射为空 → 在 _map_char 中丢弃
    0xF0E8: "",        # ⎛ 大圆括号顶 → 丢弃
    0xF0E9: "(",       # ⎜ 大圆括号中 → (
    0xF0EA: "",        # ⎝ 大圆括号底 → 丢弃
    0xF0EB: "",        # ⎡ 大方括号顶 → 丢弃
    0xF0EC: "",        # ⎧ 大花括号顶 → 丢弃
    0xF0ED: "{",       # ⎨ 大花括号中 → {
    0xF0EE: "",        # ⎩ 大花括号底 → 丢弃
    0xF0EF: "",        # ⎪ 括号延伸线 → 丢弃
    0xF0F0: "\u20AC",
    0xF0F1: "\u232A",  # ⟩
    0xF0F2: "\u222B",  # ∫
    0xF0F4: "",        # ⌠ 积分顶 → 丢弃
    0xF0F5: "",        # ⎮ 积分中线 → 丢弃
    0xF0F6: "",        # ⌡ 积分底 → 丢弃
    0xF0F8: "",        # ⎞ 大圆括号顶 → 丢弃
    0xF0F9: ")",       # ⎟ 大圆括号中 → )
    0xF0FA: "",        # ⎠ 大圆括号底 → 丢弃
    0xF0FB: "",        # ⎤ 大方括号顶 → 丢弃
    0xF0FC: "",        # ⎫ 大花括号顶 → 丢弃
    0xF0FD: "}",       # ⎬ 大花括号中 → }
    0xF0FE: "",        # ⎭ 大花括号底 → 丢弃
}

# MT-Extra 字体专用覆盖映射（与 SymbolMT 编码不同）
_MT_EXTRA_PUA_OVERRIDES: Dict[int, str] = {
    0xF055: "\u222A",  # ∪ (union, not Υ)
    0xF04E: "\u2229",  # ∩ (intersection)
}

# 非 PUA 范围的已知替代字符映射（某些 PDF 生成器的特殊编码）
_NON_PUA_SUBSTITUTIONS: Dict[int, str] = {
    0x00F0: "\u2201",  # ð → ∁ (complement)
}

# 偏导数符号：仅按 Unicode 数学字形/别名归一到 U+2202（∂），不用 bbox/字号推断
_PARTIAL_DIFFERENTIAL_ALIASES: Dict[int, str] = {
    0x1D6DB: "\u2202",  # 𝛛 MATHEMATICAL BOLD PARTIAL DIFFERENTIAL
    0x1D715: "\u2202",  # 𝜕 MATHEMATICAL ITALIC PARTIAL DIFFERENTIAL
    0x1D74F: "\u2202",  # 𝝏 MATHEMATICAL BOLD ITALIC PARTIAL DIFFERENTIAL
    0x1D789: "\u2202",  # 𝞉 MATHEMATICAL SANS-SERIF BOLD PARTIAL DIFFERENTIAL
    0x1D7C3: "\u2202",  # 𝟃 MATHEMATICAL SANS-SERIF BOLD ITALIC PARTIAL DIFFERENTIAL
}

# Unicode 上标 / 下标数字映射
_SUPERSCRIPT_DIGITS = str.maketrans("0123456789+-−=()", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾")
_SUBSCRIPT_DIGITS = str.maketrans("0123456789+-−=()", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎")

_SYMBOL_FONT_KEYWORDS = ("symbol", "mt-extra", "wingding", "zapfdingbats")


def _is_symbol_font(font_name: str) -> bool:
    return any(kw in font_name.lower() for kw in _SYMBOL_FONT_KEYWORDS)


def _is_mt_extra(font_name: str) -> bool:
    return "mt-extra" in font_name.lower()


def _map_char(ch: str, font_name: str) -> str:
    """将单个字符映射为正确的 Unicode，考虑字体差异和 PUA 区域。

    偏导数 ∂：归一为 U+2202 仅依据编码（PUA F0B6、数学字母表中的 PARTIAL DIFFERENTIAL 等），
    不依据笔画形状或与下标字母的相对位置做启发式判断。
    """
    code = ord(ch)
    if 0xE000 <= code <= 0xF8FF:
        if _is_mt_extra(font_name) and code in _MT_EXTRA_PUA_OVERRIDES:
            return _MT_EXTRA_PUA_OVERRIDES[code]
        mapped_sym = _SYMBOL_PUA_MAP.get(code, ch)
        # PUA F049 等表映射到 U+0399，在数学 PDF 中几乎总是「∩」而非希腊大写 ι
        if mapped_sym == "\u0399" and _is_symbol_font(font_name):
            return "\u2229"
        return mapped_sym
    if code in _NON_PUA_SUBSTITUTIONS:
        return _NON_PUA_SUBSTITUTIONS[code]
    if code in _PARTIAL_DIFFERENTIAL_ALIASES:
        return _PARTIAL_DIFFERENTIAL_ALIASES[code]
    # MT-Extra 常用希腊大写 ι（U+0399）排印「∩」字形，与拉丁 I 混淆
    if _is_mt_extra(font_name) and code == 0x0399:
        return "\u2229"  # ∩
    return ch


# ---------------------------------------------------------------------------
# 字符级数据结构
# ---------------------------------------------------------------------------
@dataclass
class _RichChar:
    """单个字符及其位置 / 样式信息。"""
    char: str
    font: str
    size: float
    bold: bool
    italic: bool
    origin_x: float
    origin_y: float
    bbox: Tuple[float, float, float, float]


@dataclass
class RichSpan:
    text: str
    font: str
    size: float
    bold: bool
    italic: bool
    bbox: Tuple[float, float, float, float]
    is_superscript: bool = False
    is_subscript: bool = False

    @property
    def x0(self) -> float:
        return self.bbox[0]

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class StructuredLine:
    spans: List[RichSpan]
    bbox: Tuple[float, float, float, float]
    plain_text: str = ""

    @property
    def y_mid(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0


@dataclass
class PageStructuredContent:
    page_no: int
    plain_text: str
    rich_paragraphs: List[Dict[str, Any]]
    lines: List[StructuredLine] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 字符级提取
# ---------------------------------------------------------------------------

def _extract_chars_from_page(page: fitz.Page) -> List[_RichChar]:
    """使用 rawdict 获取字符级 bbox + 样式信息。"""
    data = page.get_text("rawdict", sort=True)
    chars: List[_RichChar] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font = span.get("font", "")
                size = span.get("size", 0.0)
                flags = span.get("flags", 0)
                bold = bool(flags & (1 << 4)) or "bold" in font.lower()
                italic = bool(flags & (1 << 1)) or "italic" in font.lower()
                for c in span.get("chars", []):
                    raw_ch = c.get("c", "")
                    if not raw_ch or not raw_ch.strip():
                        continue
                    mapped = _map_char(raw_ch, font)
                    if not mapped:
                        continue
                    ox, oy = c.get("origin", (0, 0))
                    bbox = tuple(c.get("bbox", (0, 0, 0, 0)))
                    chars.append(_RichChar(
                        char=mapped, font=font, size=size,
                        bold=bold, italic=italic,
                        origin_x=ox, origin_y=oy, bbox=bbox,
                    ))
    return chars


# ---------------------------------------------------------------------------
# 行聚合：按 y 坐标分行，行内按 x 排序
# ---------------------------------------------------------------------------

def _group_chars_into_lines(
    chars: List[_RichChar], y_tolerance: float = 3.0,
) -> List[List[_RichChar]]:
    """按字符 origin_y 聚行，行内按 origin_x 排序。"""
    if not chars:
        return []

    sorted_chars = sorted(chars, key=lambda c: (c.origin_y, c.origin_x))
    lines: List[List[_RichChar]] = []
    cur: List[_RichChar] = [sorted_chars[0]]
    cur_y = sorted_chars[0].origin_y

    for ch in sorted_chars[1:]:
        if abs(ch.origin_y - cur_y) <= y_tolerance:
            cur.append(ch)
            n = len(cur)
            cur_y += (ch.origin_y - cur_y) / n
        else:
            cur.sort(key=lambda c: c.origin_x)
            lines.append(cur)
            cur = [ch]
            cur_y = ch.origin_y

    if cur:
        cur.sort(key=lambda c: c.origin_x)
        lines.append(cur)

    return lines


# ---------------------------------------------------------------------------
# 将同行字符合并为 RichSpan 列表
# ---------------------------------------------------------------------------

def _merge_chars_to_spans(chars: List[_RichChar]) -> List[RichSpan]:
    """将同一行中样式相同且位置相邻的字符合并为 RichSpan。

    间距阈值随字号自适应（max(8, size * 1.05)），防止分散在不同位置的
    同样式字符（如分数分子/分母）被错误合并。
    """
    if not chars:
        return []

    def _style_key(c: _RichChar) -> Tuple:
        return (c.font, round(c.size, 1), c.bold, c.italic)

    spans: List[RichSpan] = []
    buf_chars = [chars[0]]
    buf_key = _style_key(chars[0])

    for ch in chars[1:]:
        k = _style_key(ch)
        x_gap = ch.origin_x - buf_chars[-1].origin_x
        effective_gap = max(8.0, buf_chars[0].size * 1.05)
        if k == buf_key and x_gap < effective_gap:
            buf_chars.append(ch)
        else:
            spans.append(_flush_span(buf_chars))
            buf_chars = [ch]
            buf_key = k

    spans.append(_flush_span(buf_chars))
    return spans


def _flush_span(buf: List[_RichChar]) -> RichSpan:
    text = "".join(c.char for c in buf)
    x0 = min(c.bbox[0] for c in buf)
    y0 = min(c.bbox[1] for c in buf)
    x1 = max(c.bbox[2] for c in buf)
    y1 = max(c.bbox[3] for c in buf)
    return RichSpan(
        text=text, font=buf[0].font, size=buf[0].size,
        bold=buf[0].bold, italic=buf[0].italic,
        bbox=(x0, y0, x1, y1),
    )


def _build_structured_line(chars: List[_RichChar]) -> StructuredLine:
    spans = _merge_chars_to_spans(chars)
    x0 = min(c.bbox[0] for c in chars)
    y0 = min(c.bbox[1] for c in chars)
    x1 = max(c.bbox[2] for c in chars)
    y1 = max(c.bbox[3] for c in chars)
    return StructuredLine(spans=spans, bbox=(x0, y0, x1, y1))


# ---------------------------------------------------------------------------
# 孤立行合并（上标 / 下标被 y 坐标拆出的情况）
# ---------------------------------------------------------------------------

def _merge_bboxes(bboxes: List[Tuple[float, ...]]) -> Tuple[float, float, float, float]:
    x0 = min(b[0] for b in bboxes)
    y0 = min(b[1] for b in bboxes)
    x1 = max(b[2] for b in bboxes)
    y1 = max(b[3] for b in bboxes)
    return (x0, y0, x1, y1)


def _merge_fraction_lines(lines: List[StructuredLine]) -> List[StructuredLine]:
    """将分数的分子/分母短行合并回最近的主行，表示为 num/denom。

    检测模式：连续 2~3 行中，上行和下行都很短（≤ 少量字符），
    中间行是正常长行。上行中的字符为分子，下行中的字符为分母，
    按 x 坐标配对后插入主行。
    """
    if len(lines) < 2:
        return lines

    char_counts = [sum(len(s.text) for s in line.spans) for line in lines]

    absorbed: List[bool] = [False] * len(lines)
    result_lines = list(lines)

    i = 0
    while i < len(lines):
        if absorbed[i]:
            i += 1
            continue

        # 三行模式：top(短行) - main(长行) - bottom(短行)
        if i + 2 >= len(lines):
            i += 1
            continue

        top_idx, main_idx, bot_idx = i, i + 1, i + 2
        if absorbed[main_idx] or absorbed[bot_idx]:
            i += 1
            continue

        top_cc = char_counts[top_idx]
        main_cc = char_counts[main_idx]
        bot_cc = char_counts[bot_idx]

        if not (top_cc <= 8 and bot_cc <= 8 and main_cc > max(top_cc, bot_cc) * 3):
            i += 1
            continue

        y_gap_top = abs(lines[main_idx].y_mid - lines[top_idx].y_mid)
        y_gap_bot = abs(lines[bot_idx].y_mid - lines[main_idx].y_mid)
        if y_gap_top > 15 or y_gap_bot > 15:
            i += 1
            continue

        top_line = result_lines[top_idx]
        bot_line = result_lines[bot_idx]

        # 将卫星行 span 展开为单字符 span，实现精确 x 坐标配对
        def _explode_spans(spans: List[RichSpan]) -> List[RichSpan]:
            singles: List[RichSpan] = []
            for sp in spans:
                if len(sp.text) <= 1:
                    singles.append(sp)
                else:
                    w = (sp.bbox[2] - sp.bbox[0]) / max(len(sp.text), 1)
                    for ci, ch in enumerate(sp.text):
                        cx0 = sp.bbox[0] + ci * w
                        cx1 = cx0 + w
                        singles.append(RichSpan(
                            text=ch, font=sp.font, size=sp.size,
                            bold=sp.bold, italic=sp.italic,
                            bbox=(cx0, sp.bbox[1], cx1, sp.bbox[3]),
                        ))
            return singles

        top_atoms = _explode_spans(top_line.spans)
        bot_atoms = _explode_spans(bot_line.spans)

        # 按 x 坐标配对分子/分母
        used_bot: List[bool] = [False] * len(bot_atoms)
        pairs: List[Tuple[RichSpan, RichSpan]] = []
        unpaired_top: List[RichSpan] = []

        for ts in top_atoms:
            matched = False
            for bi, bs in enumerate(bot_atoms):
                if used_bot[bi]:
                    continue
                if abs(ts.x0 - bs.x0) < 10:
                    pairs.append((ts, bs))
                    used_bot[bi] = True
                    matched = True
                    break
            if not matched:
                unpaired_top.append(ts)

        unpaired_bot = [bs for bi, bs in enumerate(bot_atoms) if not used_bot[bi]]

        # 至少需要 1 个配对，且配对比例 > 50%
        total_atoms = len(top_atoms) + len(bot_atoms)
        if len(pairs) == 0 or (len(pairs) * 2) / max(total_atoms, 1) < 0.5:
            i += 1
            continue

        main_line = result_lines[main_idx]

        # 将相邻的配对合并为多字符分数（如连续两个配对 a/c, b/d → ab/cd）
        fraction_spans: List[RichSpan] = []
        pairs.sort(key=lambda p: p[0].x0)
        group_top: List[RichSpan] = [pairs[0][0]]
        group_bot: List[RichSpan] = [pairs[0][1]]
        for pi in range(1, len(pairs)):
            ts, bs = pairs[pi]
            prev_ts = group_top[-1]
            if ts.x0 - (prev_ts.bbox[2]) < 5:
                group_top.append(ts)
                group_bot.append(bs)
            else:
                num = "".join(s.text for s in group_top)
                den = "".join(s.text for s in group_bot)
                fb = _merge_bboxes([s.bbox for s in group_top] + [s.bbox for s in group_bot])
                fraction_spans.append(RichSpan(
                    text=num + "/" + den, font=group_top[0].font, size=group_top[0].size,
                    bold=group_top[0].bold, italic=group_top[0].italic, bbox=fb,
                ))
                group_top = [ts]
                group_bot = [bs]
        num = "".join(s.text for s in group_top)
        den = "".join(s.text for s in group_bot)
        fb = _merge_bboxes([s.bbox for s in group_top] + [s.bbox for s in group_bot])
        fraction_spans.append(RichSpan(
            text=num + "/" + den, font=group_top[0].font, size=group_top[0].size,
            bold=group_top[0].bold, italic=group_top[0].italic, bbox=fb,
        ))
        fraction_spans.extend(unpaired_top)
        fraction_spans.extend(unpaired_bot)

        for fs in fraction_spans:
            insert_pos = len(main_line.spans)
            for k, ms in enumerate(main_line.spans):
                if ms.x0 > fs.x0:
                    insert_pos = k
                    break
            main_line.spans.insert(insert_pos, fs)

        main_line.bbox = _merge_bboxes([s.bbox for s in main_line.spans])
        absorbed[top_idx] = True
        absorbed[bot_idx] = True

        i = bot_idx + 1

    return [line for j, line in enumerate(result_lines) if not absorbed[j]]


def _merge_orphan_lines(lines: List[StructuredLine]) -> List[StructuredLine]:
    """将只包含极小字号 span 的孤立行合并回最近的正常行。"""
    if len(lines) < 2:
        return lines

    all_sizes = [s.size for line in lines for s in line.spans]
    if not all_sizes:
        return lines
    median_size = sorted(all_sizes)[len(all_sizes) // 2]
    if median_size <= 0:
        return lines

    orphan_threshold = median_size * 0.72

    is_orphan_flags = []
    for line in lines:
        max_span_size = max(s.size for s in line.spans) if line.spans else 0
        is_orphan_flags.append(max_span_size <= orphan_threshold and len(line.spans) <= 4)

    merged: List[StructuredLine] = list(lines)
    absorbed: List[bool] = [False] * len(merged)

    for i, is_orph in enumerate(is_orphan_flags):
        if not is_orph:
            continue
        orph = merged[i]
        orph_y = orph.y_mid

        prev_idx = next(
            (j for j in range(i - 1, -1, -1) if not is_orphan_flags[j] and not absorbed[j]),
            None,
        )
        next_idx = next(
            (j for j in range(i + 1, len(merged)) if not is_orphan_flags[j] and not absorbed[j]),
            None,
        )

        target_idx = None
        if prev_idx is not None and next_idx is not None:
            d_prev = abs(orph_y - merged[prev_idx].y_mid)
            d_next = abs(orph_y - merged[next_idx].y_mid)
            target_idx = prev_idx if d_prev <= d_next else next_idx
        elif prev_idx is not None:
            target_idx = prev_idx
        elif next_idx is not None:
            target_idx = next_idx

        if target_idx is not None:
            target = merged[target_idx]
            for orph_span in orph.spans:
                insert_pos = len(target.spans)
                for k, ts in enumerate(target.spans):
                    if ts.x0 > orph_span.x0:
                        insert_pos = k
                        break
                target.spans.insert(insert_pos, orph_span)
            absorbed[i] = True

    result: List[StructuredLine] = []
    for i, line in enumerate(merged):
        if absorbed[i]:
            continue
        line.bbox = _merge_bboxes([s.bbox for s in line.spans])
        result.append(line)

    return result


# ---------------------------------------------------------------------------
# 上标 / 下标检测
# ---------------------------------------------------------------------------

def _detect_super_subscript(lines: List[StructuredLine]) -> None:
    for line in lines:
        if len(line.spans) < 2:
            continue
        sizes = [s.size for s in line.spans]
        dominant_size = max(set(sizes), key=sizes.count)
        if dominant_size <= 0:
            continue
        threshold = dominant_size * 0.78

        line_y_bottom = max(s.y1 for s in line.spans)
        line_y_top = min(s.y0 for s in line.spans)
        line_height = line_y_bottom - line_y_top
        if line_height <= 0:
            continue

        for span in line.spans:
            if span.size >= threshold:
                continue
            y_bottom_offset = line_y_bottom - span.y1
            y_top_offset = span.y0 - line_y_top
            if y_bottom_offset > line_height * 0.2:
                span.is_superscript = True
            elif y_top_offset > line_height * 0.2:
                span.is_subscript = True
            else:
                span.is_superscript = True


# ---------------------------------------------------------------------------
# 去重：检测 bbox 高度重叠的重复行
# ---------------------------------------------------------------------------

def _deduplicate_lines(lines: List[StructuredLine]) -> List[StructuredLine]:
    """去除因 PDF 多次渲染产生的重复行。"""
    if len(lines) < 2:
        return lines
    result: List[StructuredLine] = [lines[0]]
    for line in lines[1:]:
        prev = result[-1]
        prev_text = "".join(s.text for s in prev.spans).strip()
        cur_text = "".join(s.text for s in line.spans).strip()
        if cur_text and cur_text == prev_text:
            continue
        y_overlap = min(prev.bbox[3], line.bbox[3]) - max(prev.bbox[1], line.bbox[1])
        prev_h = prev.bbox[3] - prev.bbox[1]
        if prev_h > 0 and y_overlap / prev_h > 0.5 and cur_text == prev_text:
            continue
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# 纯文本 / 富文本构建
# ---------------------------------------------------------------------------

def _build_plain_text_for_line(line: StructuredLine) -> str:
    parts: List[str] = []
    for span in line.spans:
        text = span.text
        if span.is_superscript:
            translated = text.translate(_SUPERSCRIPT_DIGITS)
            parts.append(translated)
        elif span.is_subscript:
            translated = text.translate(_SUBSCRIPT_DIGITS)
            parts.append(translated)
        else:
            parts.append(text)
    return "".join(parts)


def _build_rich_paragraph(line: StructuredLine) -> Dict[str, Any]:
    children: List[Dict[str, Any]] = []
    for span in line.spans:
        marks: Dict[str, Any] = {}
        if span.bold:
            marks["bold"] = True
        if span.italic:
            marks["italic"] = True
        if span.is_superscript:
            marks["superscript"] = True
        if span.is_subscript:
            marks["subscript"] = True
        child: Dict[str, Any] = {"type": "text", "text": span.text}
        if marks:
            child["marks"] = marks
        children.append(child)
    return {"type": "paragraph", "children": children}


# ---------------------------------------------------------------------------
# 数学符号 span → 小图（PDF 栅格裁切，不依赖客户端数学字体）
# ---------------------------------------------------------------------------

# 含下列码位之一的短 span 优先裁成 PNG（端上无数学字体时仍可忠实显示 PDF 字形）
_MATH_CLIP_TRIGGER_ORDS: frozenset[int] = frozenset(
    {
        0x2201,  # ∁
        0x2202,  # ∂
        0x2205,  # ∅
        0x2207,  # ∇
        0x2208,
        0x2209,  # ∉
        0x220A,  # ∊
        0x2211,  # ∑
        0x221A,  # √
        0x221D,  # ∝
        0x221E,  # ∞
        0x2220,  # ∠
        0x2227,  # ∧
        0x2228,  # ∨
        0x2229,  # ∩
        0x222A,  # ∪
        0x222B,  # ∫
        0x222C,
        0x222D,
        0x2234,  # ∴
        0x2235,  # ∵
        0x2236,  # ∶
        0x2237,  # ∷
        0x2248,  # ≈
        0x2260,  # ≠
        0x2264,  # ≤
        0x2265,  # ≥
        0x2282,  # ⊂
        0x2283,  # ⊃
        0x2286,  # ⊆
        0x2287,  # ⊇
        0x2295,  # ⊕
        0x2297,  # ⊗
        0x22A5,  # ⊥
        0x22C5,  # ⋅
        0x22EE,  # ⋮
        0x22EF,  # ⋯
        0x22F0,
        0x22F1,
        0x2308,
        0x2309,
        0x230A,
        0x230B,
        0x2320,
        0x2321,
        0x2329,
        0x232A,
        0x27E8,  # ⟨
        0x27E9,  # ⟩
        0x27F5,
        0x27F6,
        0x27F7,
        0x27F8,
        0x27F9,
        0x27FA,
        0x27FC,
        0x27FF,
    }
)


def _span_text_should_be_math_clip(text: str) -> bool:
    if not text or not text.strip():
        return False
    if len(text) > 80:
        return False
    for ch in text:
        if ord(ch) in _MATH_CLIP_TRIGGER_ORDS:
            return True
    return False


def _write_span_clip_png(
    page: fitz.Page,
    bbox: Tuple[float, float, float, float],
    out_path: Path,
    dpi: int,
) -> Optional[Tuple[int, int]]:
    x0, y0, x1, y1 = bbox
    if x1 <= x0 or y1 <= y0:
        return None
    pad = 0.8
    clip = fitz.Rect(x0 - pad, y0 - pad, x1 + pad, y1 + pad) & page.rect
    if clip.is_empty:
        return None
    scale = max(72, min(dpi, 300)) / 72.0
    mat = fitz.Matrix(scale, scale)
    try:
        pix = page.get_pixmap(matrix=mat, clip=clip, alpha=False)
    except Exception:
        logger.debug("math clip pixmap failed clip=%s", clip, exc_info=True)
        return None
    if pix.width < 2 or pix.height < 2:
        return None
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
    except Exception:
        logger.warning("math clip save failed path=%s", out_path, exc_info=True)
        return None
    return pix.width, pix.height


def _apply_math_clip_images_to_paragraphs(
    page: fitz.Page,
    page_no: int,
    rich_paragraphs: List[Dict[str, Any]],
    lines: List[StructuredLine],
    output_dir: Path,
    dpi: int,
) -> None:
    counter = 0
    for para, line in zip(rich_paragraphs, lines):
        children = para.get("children")
        if not isinstance(children, list) or len(children) != len(line.spans):
            continue
        new_children: List[Dict[str, Any]] = []
        for span, child in zip(line.spans, children):
            if not isinstance(child, dict) or child.get("type") != "text":
                new_children.append(child)
                continue
            text = str(child.get("text") or "")
            if not _span_text_should_be_math_clip(text):
                new_children.append(child)
                continue
            fname = f"m_p{page_no}_{counter}.png"
            counter += 1
            out_path = output_dir / fname
            dims = _write_span_clip_png(page, span.bbox, out_path, dpi)
            if not dims:
                new_children.append(child)
                continue
            w, h = dims
            try:
                digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
            except Exception:
                digest = ""
            img_node: Dict[str, Any] = {
                "type": "image",
                "storage_url": str(out_path.resolve()),
                "width": w,
                "height": h,
                "alt_text": text,
            }
            if digest:
                img_node["file_hash"] = digest
            new_children.append(img_node)
        para["children"] = new_children


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def extract_page_structured(
    page: fitz.Page,
    page_no: int = 1,
    *,
    math_clip_output_dir: Optional[Path] = None,
) -> PageStructuredContent:
    """
    从 PDF 单页结构化提取内容（字符级排序，精确还原阅读顺序）。

    math_clip_output_dir：若提供且环境变量 QUESTION_BANK_PDF_MATH_CLIP_IMAGES 开启，
    则对命中规则的数学符号 span 裁切为 PNG 并写入该目录，rich 中对应为 image 节点。

    Returns PageStructuredContent，含：
    - plain_text：可检索纯文本
    - rich_paragraphs：QuestionRichRenderer 兼容的 paragraph 节点列表
    - lines：StructuredLine 列表
    """
    chars = _extract_chars_from_page(page)
    if not chars:
        raw_text = (page.get_text("text") or "").strip()
        return PageStructuredContent(
            page_no=page_no, plain_text=raw_text,
            rich_paragraphs=[], lines=[],
        )

    char_lines = _group_chars_into_lines(chars)
    lines = [_build_structured_line(cl) for cl in char_lines]
    lines = _deduplicate_lines(lines)
    lines = _merge_fraction_lines(lines)
    lines = _merge_orphan_lines(lines)
    _detect_super_subscript(lines)

    plain_lines: List[str] = []
    rich_paragraphs: List[Dict[str, Any]] = []
    for line in lines:
        line_text = _build_plain_text_for_line(line)
        line.plain_text = line_text
        plain_lines.append(line_text)
        rich_paragraphs.append(_build_rich_paragraph(line))

    plain_text = "\n".join(plain_lines)

    if math_clip_output_dir is not None:
        from analyzer.app.config import QUESTION_BANK_PDF_MATH_CLIP_DPI, QUESTION_BANK_PDF_MATH_CLIP_IMAGES

        if QUESTION_BANK_PDF_MATH_CLIP_IMAGES:
            clip_dpi = int(QUESTION_BANK_PDF_MATH_CLIP_DPI)
            clip_dpi = max(96, min(clip_dpi, 300))
            _apply_math_clip_images_to_paragraphs(
                page, page_no, rich_paragraphs, lines, math_clip_output_dir, clip_dpi,
            )

    return PageStructuredContent(
        page_no=page_no, plain_text=plain_text,
        rich_paragraphs=rich_paragraphs, lines=lines,
    )


def build_rich_content_json(
    paragraphs: List[Dict[str, Any]], plain_text: str = "",
) -> Dict[str, Any]:
    return {
        "type": "block_group",
        "plain_text": plain_text,
        "blocks": paragraphs,
    }


def is_page_text_based(page: fitz.Page, min_spans: int = 5) -> bool:
    """判断页面是否有足够多的嵌入文本 span（而非纯图片）。"""
    data = page.get_text("dict", sort=True)
    count = 0
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if (span.get("text") or "").strip():
                    count += 1
                    if count >= min_spans:
                        return True
    return False
