import hashlib
import json
import os
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


_PAGE_OCR_MEMORY_CACHE: Dict[str, Dict[str, Any]] = {}
_RAPID_OCR_ENGINE = None

DEFAULT_PAGE_OCR_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "backend": "auto",
    "cache_to_disk": True,
    "detect_text_blocks": True,
    "detect_question_anchors": True,
    "min_block_area": 80,
    "min_block_width": 8,
    "min_block_height": 8,
    "merge_gap_x": 18,
    "merge_gap_y": 10,
    "anchor_min_score": 0.45,
    "anchor_patterns": [
        r"第\s*(\d{1,3})\s*题",
        r"^\s*(\d{1,3})\s*[\.、．:]",
        r"^\s*[（(]\s*(\d{1,3})\s*[)）]"
    ]
}


def get_page_ocr_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    merged = deepcopy(DEFAULT_PAGE_OCR_CONFIG)
    if config:
        for key, value in config.items():
            merged[key] = value
    return merged


def analyze_page_ocr(
    image_path: str,
    workspace_dir: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
    logger=None
) -> Dict[str, Any]:
    page_config = get_page_ocr_config(config)

    if not page_config.get("enabled", True):
        return {
            "image_path": image_path,
            "backend": "disabled",
            "text_blocks": [],
            "question_anchors": [],
            "cached": False
        }

    cache_key = _build_cache_key(image_path, page_config)
    if cache_key in _PAGE_OCR_MEMORY_CACHE:
        cached_result = deepcopy(_PAGE_OCR_MEMORY_CACHE[cache_key])
        cached_result["cached"] = True
        return cached_result

    cache_path = _get_cache_path(cache_key, workspace_dir, page_config)
    if cache_path and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached_result = json.load(f)
        _PAGE_OCR_MEMORY_CACHE[cache_key] = deepcopy(cached_result)
        cached_result["cached"] = True
        return cached_result

    image = cv2.imread(image_path)
    if image is None:
        result = {
            "image_path": image_path,
            "backend": "unavailable",
            "text_blocks": [],
            "question_anchors": [],
            "cached": False,
            "error": f"Failed to read image: {image_path}"
        }
        _persist_cache(cache_key, cache_path, result)
        return result

    backend = page_config.get("backend", "auto")
    result = None
    if backend in ("auto", "rapidocr"):
        result = _run_rapidocr(image, image_path, page_config)

    if not result:
        result = _run_opencv_fallback(image, image_path, page_config)

    if logger and hasattr(logger, "log_image_info"):
        logger.log_image_info(image_path, {
            "type": "page_ocr",
            "backend": result.get("backend"),
            "text_block_count": len(result.get("text_blocks", [])),
            "anchor_count": len(result.get("question_anchors", []))
        })

    _persist_cache(cache_key, cache_path, result)
    return result


def _build_cache_key(image_path: str, config: Dict[str, Any]) -> str:
    normalized_path = os.path.abspath(image_path)
    image_mtime = 0
    image_size = 0
    if os.path.exists(normalized_path):
        stat = os.stat(normalized_path)
        image_mtime = int(stat.st_mtime)
        image_size = stat.st_size

    cache_config = {
        "backend": config.get("backend"),
        "detect_text_blocks": config.get("detect_text_blocks"),
        "detect_question_anchors": config.get("detect_question_anchors"),
        "min_block_area": config.get("min_block_area"),
        "merge_gap_x": config.get("merge_gap_x"),
        "merge_gap_y": config.get("merge_gap_y"),
        "anchor_min_score": config.get("anchor_min_score")
    }
    raw = json.dumps({
        "path": normalized_path,
        "mtime": image_mtime,
        "size": image_size,
        "config": cache_config
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _get_cache_path(cache_key: str, workspace_dir: Optional[str], config: Dict[str, Any]) -> Optional[str]:
    if not workspace_dir or not config.get("cache_to_disk", True):
        return None
    cache_dir = os.path.join(workspace_dir, "page_ocr_cache")
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"{cache_key}.json")


def _persist_cache(cache_key: str, cache_path: Optional[str], result: Dict[str, Any]) -> None:
    _PAGE_OCR_MEMORY_CACHE[cache_key] = deepcopy(result)
    if cache_path:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)


def _run_rapidocr(image: np.ndarray, image_path: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    engine = _get_rapidocr_engine()
    if engine is None:
        return None

    try:
        ocr_result, _ = engine(image)
    except Exception:
        return None

    if ocr_result is None:
        ocr_result = []

    text_blocks = []
    for item in ocr_result:
        parsed = _parse_rapidocr_item(item)
        if not parsed:
            continue
        bbox, text, score = parsed
        text_blocks.append({
            "bbox": bbox,
            "text": text,
            "score": float(score),
            "source": "rapidocr"
        })

    text_blocks = _merge_text_blocks(text_blocks, config)
    question_anchors = _extract_question_anchors(text_blocks, config)

    return {
        "image_path": image_path,
        "backend": "rapidocr",
        "text_blocks": text_blocks,
        "question_anchors": question_anchors,
        "cached": False
    }


def _get_rapidocr_engine():
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is not None:
        return _RAPID_OCR_ENGINE

    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception:
        return None

    try:
        _RAPID_OCR_ENGINE = RapidOCR()
    except Exception:
        _RAPID_OCR_ENGINE = None
    return _RAPID_OCR_ENGINE


def _parse_rapidocr_item(item: Any) -> Optional[Tuple[List[int], str, float]]:
    if not isinstance(item, (list, tuple)) or len(item) < 2:
        return None

    points = item[0]
    text = item[1] if len(item) > 1 else ""
    score = item[2] if len(item) > 2 else 0.0

    bbox = _polygon_to_bbox(points)
    if not bbox:
        return None

    text = (text or "").strip()
    return bbox, text, float(score or 0.0)


def _polygon_to_bbox(points: Any) -> Optional[List[int]]:
    if not isinstance(points, (list, tuple)) or not points:
        return None

    xs = []
    ys = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        xs.append(int(round(float(point[0]))))
        ys.append(int(round(float(point[1]))))

    if not xs or not ys:
        return None

    return [min(xs), min(ys), max(xs), max(ys)]


def _run_opencv_fallback(image: np.ndarray, image_path: str, config: Dict[str, Any]) -> Dict[str, Any]:
    text_blocks = _detect_text_blocks_with_opencv(image, config)
    return {
        "image_path": image_path,
        "backend": "opencv_fallback",
        "text_blocks": text_blocks,
        "question_anchors": [],
        "cached": False
    }


def _detect_text_blocks_with_opencv(image: np.ndarray, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    binary = cv2.adaptiveThreshold(
        blur,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        31,
        11
    )

    kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3))
    kernel_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 3))
    processed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_close, iterations=1)
    processed = cv2.dilate(processed, kernel_dilate, iterations=1)

    contours, _ = cv2.findContours(processed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    h, w = image.shape[:2]
    max_area = max(1, int(h * w * 0.25))
    min_area = int(config.get("min_block_area", 80))
    min_width = int(config.get("min_block_width", 8))
    min_height = int(config.get("min_block_height", 8))

    blocks = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        area = bw * bh
        if area < min_area or area > max_area:
            continue
        if bw < min_width or bh < min_height:
            continue
        if bw / max(bh, 1) > 80:
            continue
        blocks.append({
            "bbox": [x, y, x + bw, y + bh],
            "text": "",
            "score": 0.0,
            "source": "opencv_fallback"
        })

    blocks.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return blocks



def _merge_text_blocks(blocks: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not blocks:
        return []

    merge_gap_x = int(config.get("merge_gap_x", 18))
    merge_gap_y = int(config.get("merge_gap_y", 10))

    pending = sorted(blocks, key=lambda item: (item["bbox"][1], item["bbox"][0]))
    merged: List[Dict[str, Any]] = []

    for block in pending:
        current = dict(block)
        changed = True
        while changed:
            changed = False
            remaining = []
            for existing in merged:
                if _should_merge_bbox(current["bbox"], existing["bbox"], merge_gap_x, merge_gap_y):
                    current = _combine_block(existing, current)
                    changed = True
                else:
                    remaining.append(existing)
            merged = remaining
        merged.append(current)

    merged.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return merged


def _should_merge_bbox(bbox_a: List[int], bbox_b: List[int], gap_x: int, gap_y: int) -> bool:
    ax1, ay1, ax2, ay2 = bbox_a
    bx1, by1, bx2, by2 = bbox_b

    horizontal_overlap = min(ax2, bx2) - max(ax1, bx1)
    vertical_overlap = min(ay2, by2) - max(ay1, by1)

    horizontal_gap = max(0, max(ax1, bx1) - min(ax2, bx2))
    vertical_gap = max(0, max(ay1, by1) - min(ay2, by2))

    same_line = vertical_overlap > 0 and horizontal_gap <= gap_x
    tight_overlap = horizontal_overlap > 0 and vertical_gap <= max(2, gap_y // 3)

    return same_line or tight_overlap



def _combine_block(block_a: Dict[str, Any], block_b: Dict[str, Any]) -> Dict[str, Any]:
    a = block_a["bbox"]
    b = block_b["bbox"]
    text_a = (block_a.get("text") or "").strip()
    text_b = (block_b.get("text") or "").strip()
    merged_text = " ".join(part for part in [text_a, text_b] if part)
    return {
        "bbox": [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])],
        "text": merged_text,
        "score": max(float(block_a.get("score", 0.0)), float(block_b.get("score", 0.0))),
        "source": block_a.get("source") or block_b.get("source") or "opencv_fallback"
    }


def _extract_question_anchors(text_blocks: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not config.get("detect_question_anchors", True):
        return []

    anchor_min_score = float(config.get("anchor_min_score", 0.45))
    patterns = [re.compile(pattern) for pattern in config.get("anchor_patterns", [])]
    anchors = []

    for block in text_blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue
        score = float(block.get("score", 0.0))
        if score < anchor_min_score:
            continue

        number = _extract_question_number(text, patterns)
        if not number:
            continue

        anchors.append({
            "number": number,
            "text": text,
            "bbox": block["bbox"],
            "score": score,
            "source": block.get("source", "rapidocr")
        })

    anchors.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return anchors


def _extract_question_number(text: str, patterns: List[re.Pattern]) -> Optional[str]:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return str(int(match.group(1)))
    return None
