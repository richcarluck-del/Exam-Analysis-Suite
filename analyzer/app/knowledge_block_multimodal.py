"""
将 KnowledgeBlock 的 rich_docx 结构（段落 / 表格 / 嵌套表 / 图片）组装为
OpenAI 兼容的多模态 user.content（text + image_url），供阿里云百炼等接口使用。

本地图片使用 data URL（与 llm_client.call_vlm_on_image 一致）；https 外链原样传递。
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

OpenAIContentPart = Dict[str, Any]


def resolve_local_media_path(storage_url: str, search_roots: Sequence[Path]) -> Optional[Path]:
    """将 render 中的 storage_url 解析为可读本地文件；外链返回 None。"""
    raw = (storage_url or "").strip()
    if not raw or raw.startswith("data:"):
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return None
    if raw.startswith("file://"):
        raw = raw[7:]
    p = Path(raw)
    if p.is_file():
        return p.resolve()
    for root in search_roots:
        if not root:
            continue
        cand = (Path(root) / raw).resolve()
        if cand.is_file():
            return cand
    return None


def storage_url_to_openai_image_url(
    storage_url: str,
    *,
    search_roots: Sequence[Path],
    max_bytes: int,
) -> Optional[str]:
    """
    返回可写入 OpenAI 兼容 payload 的 image_url：
    - 公网 http(s)：原样返回（需对端可拉取）
    - 本地文件：转为 data:image/...;base64,...
    """
    su = (storage_url or "").strip()
    if not su:
        return None
    if su.startswith("http://") or su.startswith("https://"):
        return su
    path = resolve_local_media_path(su, search_roots)
    if path is None or not path.is_file():
        return None
    try:
        sz = path.stat().st_size
    except OSError:
        return None
    if sz > max_bytes:
        return None
    from analyzer.app.llm_client import build_image_data_url

    return build_image_data_url(str(path))


def _append_text_merge(parts: List[OpenAIContentPart], s: str) -> None:
    if not s:
        return
    if parts and parts[-1].get("type") == "text":
        parts[-1]["text"] += s
    else:
        parts.append({"type": "text", "text": s})


class _ImageBudget:
    __slots__ = ("max_images", "used")

    def __init__(self, max_images: int) -> None:
        self.max_images = max(0, int(max_images))
        self.used = 0

    def try_consume(self) -> bool:
        if self.used >= self.max_images:
            return False
        self.used += 1
        return True


def _walk_paragraph_children(
    children: Sequence[Any],
    parts: List[OpenAIContentPart],
    *,
    search_roots: Sequence[Path],
    max_image_bytes: int,
    budget: _ImageBudget,
) -> None:
    for ch in children or []:
        if not isinstance(ch, dict):
            continue
        ct = ch.get("type")
        if ct == "text":
            _append_text_merge(parts, str(ch.get("text") or ""))
        elif ct == "formula":
            _append_text_merge(parts, str(ch.get("text") or ""))
        elif ct == "line_break":
            _append_text_merge(parts, "\n")
        elif ct == "image":
            url = storage_url_to_openai_image_url(
                str(ch.get("storage_url") or ""),
                search_roots=search_roots,
                max_bytes=max_image_bytes,
            )
            if not url:
                alt = str(ch.get("alt_text") or "").strip() or "[图片]"
                _append_text_merge(parts, f"（图片未解析或过大，占位：{alt}）\n")
                continue
            if not budget.try_consume():
                _append_text_merge(parts, "[图：本请求图片配额已满，已省略]\n")
                continue
            _append_text_merge(parts, f"[图#{budget.used}]\n")
            parts.append({"type": "image_url", "image_url": {"url": url}})
        else:
            for v in ch.values():
                if isinstance(v, list):
                    _walk_paragraph_children(v, parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)
                elif isinstance(v, dict):
                    _walk_paragraph_children([v], parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)


def _walk_render_tree(
    render: Any,
    parts: List[OpenAIContentPart],
    *,
    search_roots: Sequence[Path],
    max_image_bytes: int,
    budget: _ImageBudget,
) -> None:
    if not isinstance(render, dict):
        return
    t = render.get("type")
    if t == "block_group":
        for sub in render.get("blocks") or []:
            _walk_render_tree(sub, parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)
        return
    if t == "paragraph":
        _walk_paragraph_children(
            render.get("children") or [],
            parts,
            search_roots=search_roots,
            max_image_bytes=max_image_bytes,
            budget=budget,
        )
        return
    if t == "table":
        rows = render.get("rows") or []
        for ri, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            cells = row.get("cells") or []
            for ci, cell in enumerate(cells):
                if not isinstance(cell, dict):
                    continue
                _append_text_merge(parts, f"\n[表 R{ri + 1} C{ci + 1}]")
                for blk in cell.get("blocks") or []:
                    _walk_render_tree(blk, parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)
        return
    for v in render.values():
        if isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and item.get("type") in {"paragraph", "table", "block_group"}:
                    _walk_render_tree(item, parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)
                elif isinstance(item, dict):
                    _walk_paragraph_children([item], parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)


def build_openai_content_parts_from_rich_json(
    rich_content_json: Optional[Dict[str, Any]],
    *,
    search_roots: Sequence[Path],
    max_images: int = 24,
    max_image_bytes: int = 4 * 1024 * 1024,
    preamble: str = "",
) -> List[OpenAIContentPart]:
    """
    从 KnowledgeBlock.rich_content_json（通常为 block_group）生成 OpenAI 兼容的 content 数组。
    仅包含结构化 walk 结果；外层 system/user 提示需调用方自行拼接。
    """
    parts: List[OpenAIContentPart] = []
    if preamble:
        _append_text_merge(parts, preamble)
    if not isinstance(rich_content_json, dict) or not rich_content_json:
        return parts if parts else [{"type": "text", "text": ""}]
    budget = _ImageBudget(max_images)
    root = copy.deepcopy(rich_content_json)
    if root.get("type") != "block_group":
        root = {"type": "block_group", "blocks": [root]}
    _walk_render_tree(root, parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)
    return parts if parts else [{"type": "text", "text": ""}]


def append_topic_batch_multimodal_image_parts(
    parts: List[OpenAIContentPart],
    *,
    batch: Sequence[Dict[str, Any]],
    content_segments: Sequence[Any],
    search_roots: Sequence[Path],
    max_images: int,
    max_image_bytes: int,
) -> int:
    """
    在已有 OpenAI content parts 末尾追加本批各块的「行列标注文本 + 内嵌图」。
    content_segments 为 TopicContentSegment 序列（仅使用 blocks 与 section_title）。

    Returns:
        追加的 image_url 段数量。
    """
    before = sum(1 for p in parts if isinstance(p, dict) and p.get("type") == "image_url")
    budget = _ImageBudget(max_images)
    for item in batch:
        if not isinstance(item, dict):
            continue
        if budget.used >= budget.max_images:
            _append_text_merge(parts, f"\n[本请求图片配额已满（{budget.max_images}），后续块不再附带 image_url]\n")
            break
        try:
            block_order = int(item.get("block_order"))
        except (TypeError, ValueError):
            continue
        if block_order < 1 or block_order > len(content_segments):
            continue
        seg = content_segments[block_order - 1]
        blocks = getattr(seg, "blocks", None) or []
        section_title = str(getattr(seg, "section_title", "") or "")
        _append_text_merge(
            parts,
            "\n\n"
            + "=" * 12
            + "\n"
            + f"[嵌入多模态资源 block_order={block_order} section_title={section_title!r}]\n"
            + "以下为该块内表格/段落阅读顺序；[图#n] 与紧随其后的 image_url 一一对应。\n"
            + "=" * 12
            + "\n",
        )
        mini: Dict[str, Any] = {"type": "block_group", "blocks": []}
        for b in blocks:
            if isinstance(b, dict) and b.get("render"):
                mini["blocks"].append(copy.deepcopy(b["render"]))
        if mini["blocks"]:
            _walk_render_tree(mini, parts, search_roots=search_roots, max_image_bytes=max_image_bytes, budget=budget)
    after = sum(1 for p in parts if isinstance(p, dict) and p.get("type") == "image_url")
    return max(0, after - before)


def openai_user_content_for_call(
    *,
    prompt_text: str,
    extra_parts: Optional[Sequence[OpenAIContentPart]] = None,
) -> Union[str, List[OpenAIContentPart]]:
    """若 extra_parts 仅空或只有与 prompt 可合并的文本，则返回纯字符串以兼容旧接口。"""
    parts: List[OpenAIContentPart] = []
    _append_text_merge(parts, prompt_text)
    if extra_parts:
        for p in extra_parts:
            if not isinstance(p, dict):
                continue
            if p.get("type") == "text" and isinstance(p.get("text"), str):
                _append_text_merge(parts, p["text"])
            else:
                parts.append(p)
    has_image = any(isinstance(p, dict) and p.get("type") == "image_url" for p in parts)
    if not has_image and len(parts) == 1 and parts[0].get("type") == "text":
        return str(parts[0].get("text") or "")
    return parts


def redact_openai_messages_for_audit(messages: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """脱敏 data URL，便于写入 run 日志。"""
    out = copy.deepcopy(list(messages))
    for msg in out:
        c = msg.get("content")
        if not isinstance(c, list):
            continue
        for part in c:
            if not isinstance(part, dict):
                continue
            if part.get("type") != "image_url":
                continue
            iu = part.get("image_url")
            if not isinstance(iu, dict):
                continue
            url = iu.get("url")
            if isinstance(url, str) and url.startswith("data:"):
                iu["url"] = f"<data_url base64 chars={len(url)}>"
    return out


def summarize_multimodal_content_for_log(content: Union[str, List[OpenAIContentPart], None]) -> Dict[str, Any]:
    """生成轻量摘要，避免把 base64 写入日志。"""
    if content is None:
        return {"mode": "null"}
    if isinstance(content, str):
        return {"mode": "text", "chars": len(content)}
    if not isinstance(content, list):
        return {"mode": "unknown", "repr": type(content).__name__}
    n_text = sum(1 for p in content if isinstance(p, dict) and p.get("type") == "text")
    n_img = sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")
    text_chars = sum(len(str(p.get("text") or "")) for p in content if isinstance(p, dict) and p.get("type") == "text")
    return {"mode": "multipart", "parts": len(content), "text_parts": n_text, "image_parts": n_img, "text_chars": text_chars}
