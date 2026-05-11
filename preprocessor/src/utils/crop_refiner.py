import re
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np


def refine_region_and_crop(
    image: np.ndarray,
    points: Dict[str, List[float]],
    crop_area: Optional[List[int]] = None,
    question_number: Optional[str] = None,
    mode: str = "question",
    page_ocr_result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    peer_points_list: Optional[List[Dict[str, List[float]]]] = None
) -> Dict[str, Any]:
    if image is None or points is None:
        raise ValueError("image and points are required")

    image_h, image_w = image.shape[:2]
    crop_area = _normalize_crop_area(crop_area, image_w, image_h)
    refine_config = deepcopy(config or {})

    original_box = points_to_page_box(points, crop_area)
    peer_boxes = [
        points_to_page_box(peer_points, crop_area)
        for peer_points in (peer_points_list or [])
        if isinstance(peer_points, dict)
    ]
    hard_guard_bounds = _build_guard_bounds(original_box, peer_boxes, crop_area, mode, refine_config)
    soft_guard_bounds = _build_soft_guard_bounds(original_box, hard_guard_bounds, crop_area, mode, refine_config)

    box = original_box[:]
    refine_flags: List[str] = []

    box = _expand_box(box, hard_guard_bounds, mode, refine_config)
    if box != original_box:
        refine_flags.append("dynamic_expand")

    text_block_config = (refine_config.get("text_block_expansion") or {})
    text_blocks = (page_ocr_result or {}).get("text_blocks", [])
    page_ocr_backend = (page_ocr_result or {}).get("backend", "none")
    disable_text_block_expand = (
        page_ocr_backend == "opencv_fallback"
        and text_block_config.get("disable_on_opencv_fallback", True)
    )
    if text_block_config.get("enabled", True) and text_blocks and not disable_text_block_expand:
        expanded_box = _compensate_with_text_blocks(
            box,
            text_blocks,
            hard_guard_bounds,
            overlap_margin=int(text_block_config.get("overlap_margin", 12)),
            backend=page_ocr_backend,
            config=text_block_config
        )
        if expanded_box != box:
            refine_flags.append("text_block_expand")
            box = expanded_box

    anchor_config = refine_config.get("question_anchor") or {}
    anchors = (page_ocr_result or {}).get("question_anchors", [])
    if mode == "question" and anchor_config.get("enabled", True) and anchors:
        anchor_box = _apply_question_anchor_fix(box, anchors, question_number, anchor_config, soft_guard_bounds)
        if anchor_box != box:
            refine_flags.append("question_anchor_fix")
            box = anchor_box

    if text_block_config.get("enabled", True) and text_blocks and not disable_text_block_expand:
        rescued_box = _override_guard_with_text_blocks(
            box,
            text_blocks,
            hard_guard_bounds,
            soft_guard_bounds,
            backend=page_ocr_backend,
            config=text_block_config
        )
        if rescued_box != box:
            refine_flags.append("text_block_guard_override")
            box = rescued_box

    edge_config = refine_config.get("edge_safety") or {}
    if edge_config.get("enabled", True):
        safe_box, edge_flags = _auto_expand_until_safe(box, image, edge_config, soft_guard_bounds)
        if edge_flags:
            refine_flags.extend(edge_flags)
            box = safe_box

    trim_enabled = bool(refine_config.get("trim_whitespace", True))
    if trim_enabled:
        trimmed_box = _trim_whitespace_box(box, image, refine_config, soft_guard_bounds)
        if trimmed_box != box:
            refine_flags.append("trim_whitespace")
            box = trimmed_box

    box = _clamp_box(box, soft_guard_bounds)
    crop = crop_image_by_box(image, box)
    refined_points = page_box_to_points(box, crop_area)

    return {
        "points": refined_points,
        "crop": crop,
        "page_box": box,
        "original_page_box": original_box,
        "refine_flags": sorted(set(refine_flags)),
        "crop_debug": {
            "mode": mode,
            "crop_area": list(crop_area),
            "hard_guard_bounds": list(hard_guard_bounds),
            "soft_guard_bounds": list(soft_guard_bounds),
            "peer_box_count": len(peer_boxes),
            "original_page_box": original_box,
            "refined_page_box": box,
            "page_ocr_backend": page_ocr_backend,
            "text_block_count": len(text_blocks),
            "question_anchor_count": len(anchors)
        }
    }




def points_to_page_box(points: Dict[str, List[float]], crop_area: List[int]) -> List[int]:
    left, top, right, bottom = crop_area
    part_w = max(1, right - left)
    part_h = max(1, bottom - top)

    xs = [
        float(points["top_left"][0]),
        float(points["top_right"][0]),
        float(points["bottom_right"][0]),
        float(points["bottom_left"][0])
    ]
    ys = [
        float(points["top_left"][1]),
        float(points["top_right"][1]),
        float(points["bottom_right"][1]),
        float(points["bottom_left"][1])
    ]

    x1 = int(round(left + min(xs) / 1000.0 * part_w))
    y1 = int(round(top + min(ys) / 1000.0 * part_h))
    x2 = int(round(left + max(xs) / 1000.0 * part_w))
    y2 = int(round(top + max(ys) / 1000.0 * part_h))
    return [x1, y1, x2, y2]


def page_box_to_points(box: List[int], crop_area: List[int]) -> Dict[str, List[int]]:
    left, top, right, bottom = crop_area
    part_w = max(1, right - left)
    part_h = max(1, bottom - top)
    x1, y1, x2, y2 = _clamp_box(box, crop_area)

    return {
        "top_left": [_to_normalized(x1 - left, part_w), _to_normalized(y1 - top, part_h)],
        "top_right": [_to_normalized(x2 - left, part_w), _to_normalized(y1 - top, part_h)],
        "bottom_right": [_to_normalized(x2 - left, part_w), _to_normalized(y2 - top, part_h)],
        "bottom_left": [_to_normalized(x1 - left, part_w), _to_normalized(y2 - top, part_h)]
    }


def crop_image_by_box(image: np.ndarray, box: List[int]) -> np.ndarray:
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2]


def _build_guard_bounds(
    box: List[int],
    peer_boxes: List[List[int]],
    crop_area: List[int],
    mode: str,
    config: Dict[str, Any]
) -> List[int]:
    guard_config = config.get("neighbor_guard") or {}
    if not guard_config.get("enabled", True) or not peer_boxes:
        return list(crop_area)

    x1, y1, x2, y2 = box
    base_min_gap_px = int(guard_config.get("min_gap_px", 8 if mode == "question" else 6))
    horizontal_min_gap_px = int(guard_config.get("horizontal_min_gap_px", base_min_gap_px))
    vertical_min_gap_px = int(guard_config.get("vertical_min_gap_px", 2 if mode == "question" else 4))
    row_overlap_ratio = float(guard_config.get("same_row_overlap_ratio", 0.28))
    column_overlap_ratio = float(guard_config.get("same_column_overlap_ratio", 0.20))
    horizontal_mid_gap_ratio = float(guard_config.get("horizontal_mid_gap_ratio", 0.50))
    vertical_gap_keep_ratio_key = "vertical_gap_keep_ratio_question" if mode == "question" else "vertical_gap_keep_ratio_answer"
    vertical_gap_keep_ratio = float(guard_config.get(vertical_gap_keep_ratio_key, 0.15 if mode == "question" else 0.25))

    left_bound, top_bound, right_bound, bottom_bound = crop_area

    for peer in peer_boxes:
        px1, py1, px2, py2 = peer
        overlap_y_ratio = _axis_overlap_ratio(y1, y2, py1, py2)
        overlap_x_ratio = _axis_overlap_ratio(x1, x2, px1, px2)

        if overlap_y_ratio >= row_overlap_ratio:
            if px2 <= x1:
                gap = max(0, x1 - px2)
                keep_gap = max(horizontal_min_gap_px, int(gap * horizontal_mid_gap_ratio))
                left_bound = max(left_bound, px2 + keep_gap)
            elif px1 >= x2:
                gap = max(0, px1 - x2)
                keep_gap = max(horizontal_min_gap_px, int(gap * horizontal_mid_gap_ratio))
                right_bound = min(right_bound, px1 - keep_gap)

        if overlap_x_ratio >= column_overlap_ratio:
            if py2 <= y1:
                gap = max(0, y1 - py2)
                keep_gap = max(vertical_min_gap_px, int(gap * vertical_gap_keep_ratio))
                top_bound = max(top_bound, py2 + keep_gap)
            elif py1 >= y2:
                gap = max(0, py1 - y2)
                keep_gap = max(vertical_min_gap_px, int(gap * vertical_gap_keep_ratio))
                bottom_bound = min(bottom_bound, py1 - keep_gap)

    guarded = [
        min(left_bound, x1),
        min(top_bound, y1),
        max(right_bound, x2),
        max(bottom_bound, y2)
    ]
    return _clamp_box(guarded, crop_area)



def _build_soft_guard_bounds(
    box: List[int],
    hard_bounds: List[int],
    crop_area: List[int],
    mode: str,
    config: Dict[str, Any]
) -> List[int]:
    guard_config = config.get("neighbor_guard") or {}
    relax_config = guard_config.get("priority_relax_question") or {}
    if mode != "question" or not relax_config.get("enabled", True):
        return list(hard_bounds)

    relaxed = [
        max(crop_area[0], hard_bounds[0] - int(relax_config.get("left_px", 18))),
        max(crop_area[1], hard_bounds[1] - int(relax_config.get("top_px", 12))),
        min(crop_area[2], hard_bounds[2] + int(relax_config.get("right_px", 0))),
        min(crop_area[3], hard_bounds[3] + int(relax_config.get("bottom_px", 0)))
    ]
    return [
        min(relaxed[0], box[0]),
        min(relaxed[1], box[1]),
        max(relaxed[2], box[2]),
        max(relaxed[3], box[3])
    ]



def _expand_box(box: List[int], bounds: List[int], mode: str, config: Dict[str, Any]) -> List[int]:

    padding_ratio_key = "question_padding_ratio" if mode == "question" else "answer_padding_ratio"
    padding_ratio = config.get(padding_ratio_key) or {}
    min_padding = config.get("min_padding_pixels") or {}

    x1, y1, x2, y2 = box
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)

    left_pad = max(int(round(width * float(padding_ratio.get("left", 0.08)))), int(min_padding.get("left", 10)))
    right_pad = max(int(round(width * float(padding_ratio.get("right", 0.08)))), int(min_padding.get("right", 10)))
    top_pad = max(int(round(height * float(padding_ratio.get("top", 0.10)))), int(min_padding.get("top", 10)))
    bottom_pad = max(int(round(height * float(padding_ratio.get("bottom", 0.12)))), int(min_padding.get("bottom", 12)))

    short_box_config = config.get("question_short_box") or {}
    if mode == "question" and short_box_config.get("enabled", True) and height <= int(short_box_config.get("max_height_px", 110)):
        top_pad = max(top_pad, int(short_box_config.get("top_padding_px", 18)))
        bottom_pad = max(bottom_pad, int(short_box_config.get("bottom_padding_px", 22)))

    expanded = [x1 - left_pad, y1 - top_pad, x2 + right_pad, y2 + bottom_pad]
    return _clamp_box(expanded, bounds)




def _compensate_with_text_blocks(
    box: List[int],
    text_blocks: List[Dict[str, Any]],
    bounds: List[int],
    overlap_margin: int = 12,
    backend: str = "none",
    config: Optional[Dict[str, Any]] = None
) -> List[int]:
    config = config or {}
    seed_box = box[:]
    expanded = box[:]
    seed_width = max(1, seed_box[2] - seed_box[0])
    seed_height = max(1, seed_box[3] - seed_box[1])
    seed_area = seed_width * seed_height

    side_expand_ratio_x = float(config.get("max_side_expand_ratio_x", 0.22 if backend == "opencv_fallback" else 0.40))
    side_expand_ratio_y = float(config.get("max_side_expand_ratio_y", 0.18 if backend == "opencv_fallback" else 0.35))
    min_overlap_ratio_x = float(config.get("min_overlap_ratio_x", 0.55))
    min_overlap_ratio_y = float(config.get("min_overlap_ratio_y", 0.55))

    for block in text_blocks:
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        block_width = max(1, int(bbox[2]) - int(bbox[0]))
        block_height = max(1, int(bbox[3]) - int(bbox[1]))
        block_area = block_width * block_height

        if block_width > seed_width * 1.8:
            continue
        if block_height > seed_height * 1.8:
            continue
        if block_area > seed_area * 2.2:
            continue
        if not _intersects_or_near(seed_box, bbox, overlap_margin):
            continue

        overlap_x_ratio = _axis_overlap_ratio(seed_box[0], seed_box[2], int(bbox[0]), int(bbox[2]))
        overlap_y_ratio = _axis_overlap_ratio(seed_box[1], seed_box[3], int(bbox[1]), int(bbox[3]))

        if (int(bbox[0]) < seed_box[0] or int(bbox[2]) > seed_box[2]) and overlap_y_ratio < min_overlap_ratio_y:
            continue
        if (int(bbox[1]) < seed_box[1] or int(bbox[3]) > seed_box[3]) and overlap_x_ratio < min_overlap_ratio_x:
            continue

        if (seed_box[0] - int(bbox[0])) > int(seed_width * side_expand_ratio_x):
            continue
        if (int(bbox[2]) - seed_box[2]) > int(seed_width * side_expand_ratio_x):
            continue
        if (seed_box[1] - int(bbox[1])) > int(seed_height * side_expand_ratio_y):
            continue
        if (int(bbox[3]) - seed_box[3]) > int(seed_height * side_expand_ratio_y):
            continue

        expanded = [
            min(expanded[0], int(bbox[0])),
            min(expanded[1], int(bbox[1])),
            max(expanded[2], int(bbox[2])),
            max(expanded[3], int(bbox[3]))
        ]

    return _clamp_box(expanded, bounds)



def _override_guard_with_text_blocks(
    box: List[int],
    text_blocks: List[Dict[str, Any]],
    hard_bounds: List[int],
    soft_bounds: List[int],
    backend: str = "none",
    config: Optional[Dict[str, Any]] = None
) -> List[int]:
    config = config or {}
    override_config = config.get("guard_override") or {}
    if not override_config.get("enabled", True) or hard_bounds == soft_bounds:
        return box

    seed_box = box[:]
    expanded = box[:]
    seed_width = max(1, seed_box[2] - seed_box[0])
    seed_height = max(1, seed_box[3] - seed_box[1])
    seed_area = seed_width * seed_height

    overlap_margin = int(override_config.get("overlap_margin", config.get("overlap_margin", 12) + 6))
    side_expand_ratio_x = float(override_config.get("max_side_expand_ratio_x", 0.28 if backend == "opencv_fallback" else 0.34))
    side_expand_ratio_y = float(override_config.get("max_side_expand_ratio_y", 0.24 if backend == "opencv_fallback" else 0.30))
    min_overlap_ratio_x = float(override_config.get("min_overlap_ratio_x", 0.70))
    min_overlap_ratio_y = float(override_config.get("min_overlap_ratio_y", 0.70))
    max_block_area_ratio = float(override_config.get("max_block_area_ratio", 2.4))

    for block in text_blocks:
        bbox = block.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        clipped_bbox = [
            max(soft_bounds[0], int(bbox[0])),
            max(soft_bounds[1], int(bbox[1])),
            min(soft_bounds[2], int(bbox[2])),
            min(soft_bounds[3], int(bbox[3]))
        ]
        if clipped_bbox[0] >= clipped_bbox[2] or clipped_bbox[1] >= clipped_bbox[3]:
            continue
        if not _intersects_or_near(seed_box, clipped_bbox, overlap_margin):
            continue

        block_width = max(1, clipped_bbox[2] - clipped_bbox[0])
        block_height = max(1, clipped_bbox[3] - clipped_bbox[1])
        block_area = block_width * block_height
        if block_width > seed_width * 1.8:
            continue
        if block_height > seed_height * 1.8:
            continue
        if block_area > seed_area * max_block_area_ratio:
            continue

        overlap_x_ratio = _axis_overlap_ratio(seed_box[0], seed_box[2], clipped_bbox[0], clipped_bbox[2])
        overlap_y_ratio = _axis_overlap_ratio(seed_box[1], seed_box[3], clipped_bbox[1], clipped_bbox[3])

        if soft_bounds[0] < hard_bounds[0] and clipped_bbox[0] < expanded[0] and clipped_bbox[0] < hard_bounds[0]:
            if overlap_y_ratio >= min_overlap_ratio_y and (seed_box[0] - clipped_bbox[0]) <= int(seed_width * side_expand_ratio_x):
                expanded[0] = max(soft_bounds[0], min(expanded[0], clipped_bbox[0]))
        if soft_bounds[1] < hard_bounds[1] and clipped_bbox[1] < expanded[1] and clipped_bbox[1] < hard_bounds[1]:
            if overlap_x_ratio >= min_overlap_ratio_x and (seed_box[1] - clipped_bbox[1]) <= int(seed_height * side_expand_ratio_y):
                expanded[1] = max(soft_bounds[1], min(expanded[1], clipped_bbox[1]))
        if soft_bounds[2] > hard_bounds[2] and clipped_bbox[2] > expanded[2] and clipped_bbox[2] > hard_bounds[2]:
            if overlap_y_ratio >= min_overlap_ratio_y and (clipped_bbox[2] - seed_box[2]) <= int(seed_width * side_expand_ratio_x):
                expanded[2] = min(soft_bounds[2], max(expanded[2], clipped_bbox[2]))
        if soft_bounds[3] > hard_bounds[3] and clipped_bbox[3] > expanded[3] and clipped_bbox[3] > hard_bounds[3]:
            if overlap_x_ratio >= min_overlap_ratio_x and (clipped_bbox[3] - seed_box[3]) <= int(seed_height * side_expand_ratio_y):
                expanded[3] = min(soft_bounds[3], max(expanded[3], clipped_bbox[3]))

    return _clamp_box(expanded, soft_bounds)



def _apply_question_anchor_fix(

    box: List[int],
    anchors: List[Dict[str, Any]],
    question_number: Optional[str],
    config: Dict[str, Any],
    bounds: List[int]
) -> List[int]:

    normalized_number = _normalize_question_number(question_number)
    if not normalized_number:
        return box

    top_buffer_px = int(config.get("top_buffer_px", 10))
    search_above_px = int(config.get("search_above_px", 120))
    column_tolerance_ratio = float(config.get("column_tolerance_ratio", 0.35))

    x1, y1, x2, y2 = box
    width = max(1, x2 - x1)
    tolerance_px = int(width * column_tolerance_ratio)

    exact_candidates = []
    near_candidates = []
    for anchor in anchors:
        anchor_bbox = anchor.get("bbox")
        if not anchor_bbox or len(anchor_bbox) != 4:
            continue
        anchor_number = _normalize_question_number(anchor.get("number"))
        center_x = (anchor_bbox[0] + anchor_bbox[2]) / 2
        same_column = (x1 - tolerance_px) <= center_x <= (x2 + tolerance_px)
        vertically_relevant = anchor_bbox[1] <= y2 and anchor_bbox[3] >= (y1 - search_above_px)
        if not same_column or not vertically_relevant:
            continue
        candidate = (abs(anchor_bbox[1] - y1), anchor_bbox)
        if anchor_number == normalized_number:
            exact_candidates.append(candidate)
        else:
            near_candidates.append(candidate)

    selected = None
    if exact_candidates:
        selected = sorted(exact_candidates, key=lambda item: item[0])[0][1]
    elif near_candidates:
        selected = sorted(near_candidates, key=lambda item: item[0])[0][1]

    if not selected:
        return box

    fixed = [
        min(x1, selected[0] - 6),
        min(y1, selected[1] - top_buffer_px),
        x2,
        y2
    ]
    return _clamp_box(fixed, bounds)



def _auto_expand_until_safe(
    box: List[int],
    image: np.ndarray,
    config: Dict[str, Any],
    bounds: List[int]
) -> Tuple[List[int], List[str]]:

    margin_px = int(config.get("margin_px", 5))
    expand_step_px = int(config.get("expand_step_px", 12))
    max_iterations = int(config.get("max_iterations", 6))
    max_expand_ratio = float(config.get("max_expand_ratio", 0.35))
    max_expand_ratio_x = float(config.get("max_horizontal_expand_ratio", max_expand_ratio))
    max_expand_ratio_y = float(config.get("max_vertical_expand_ratio", max_expand_ratio))

    original_box = box[:]

    current_box = box[:]
    flags: List[str] = []

    original_width = max(1, original_box[2] - original_box[0])
    original_height = max(1, original_box[3] - original_box[1])

    for _ in range(max_iterations):
        crop = crop_image_by_box(image, current_box)
        risky_edges = _detect_edge_risk(crop, config, margin_px)
        if not risky_edges:
            break

        candidate = current_box[:]
        for edge in risky_edges:
            if edge == "top":
                if (original_box[1] - candidate[1]) < int(original_height * max_expand_ratio_y):
                    candidate[1] -= expand_step_px
            elif edge == "bottom":
                if (candidate[3] - original_box[3]) < int(original_height * max_expand_ratio_y):
                    candidate[3] += expand_step_px
            elif edge == "left":
                if (original_box[0] - candidate[0]) < int(original_width * max_expand_ratio_x):
                    candidate[0] -= expand_step_px
            elif edge == "right":
                if (candidate[2] - original_box[2]) < int(original_width * max_expand_ratio_x):
                    candidate[2] += expand_step_px


        candidate = _clamp_box(candidate, bounds)

        if candidate == current_box:
            break
        current_box = candidate
        flags.extend([f"edge_expand_{edge}" for edge in risky_edges])

    return current_box, sorted(set(flags))


def _detect_edge_risk(crop: np.ndarray, config: Dict[str, Any], margin_px: int) -> List[str]:
    if crop is None or crop.size == 0:
        return []

    h, w = crop.shape[:2]
    if h <= margin_px * 2 or w <= margin_px * 2:
        return []

    threshold = int(config.get("binary_threshold", 200))
    density_threshold = float(config.get("density_threshold", 0.15))
    ignore_corner_ratio = float(config.get("ignore_corner_ratio", 0.12))

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop.copy()
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)

    trim_x = min(w // 3, max(0, int(w * ignore_corner_ratio)))
    trim_y = min(h // 3, max(0, int(h * ignore_corner_ratio)))

    risky = []
    slices = {
        "top": binary[0:margin_px, trim_x:w - trim_x],
        "bottom": binary[h - margin_px:h, trim_x:w - trim_x],
        "left": binary[trim_y:h - trim_y, 0:margin_px],
        "right": binary[trim_y:h - trim_y, w - margin_px:w]
    }


    for edge, area in slices.items():
        density = float(cv2.countNonZero(area)) / float(area.size or 1)
        if density > density_threshold:
            risky.append(edge)

    return risky


def _trim_whitespace_box(
    box: List[int],
    image: np.ndarray,
    config: Dict[str, Any],
    crop_area: List[int]
) -> List[int]:
    crop = crop_image_by_box(image, box)
    if crop is None or crop.size == 0:
        return box

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop.copy()
    _, binary = cv2.threshold(gray, 245, 255, cv2.THRESH_BINARY_INV)
    coords = cv2.findNonZero(binary)
    if coords is None:
        return box

    x, y, w, h = cv2.boundingRect(coords)
    crop_h, crop_w = crop.shape[:2]
    if w <= 0 or h <= 0:
        return box

    area_ratio = float(w * h) / float(max(1, crop_w * crop_h))
    if area_ratio < 0.30:
        return box

    trim_padding = int(config.get("trim_padding", 6))
    max_inset_x = int(crop_w * 0.18)
    max_inset_y = int(crop_h * 0.18)

    inset_left = min(max(0, x - trim_padding), max_inset_x)
    inset_top = min(max(0, y - trim_padding), max_inset_y)
    inset_right = min(max(0, crop_w - (x + w) - trim_padding), max_inset_x)
    inset_bottom = min(max(0, crop_h - (y + h) - trim_padding), max_inset_y)

    trimmed = [
        box[0] + inset_left,
        box[1] + inset_top,
        box[2] - inset_right,
        box[3] - inset_bottom
    ]
    return _clamp_box(trimmed, crop_area)


def _normalize_crop_area(crop_area: Optional[List[int]], image_w: int, image_h: int) -> List[int]:
    if not crop_area or len(crop_area) != 4:
        return [0, 0, image_w, image_h]
    return [
        int(crop_area[0]),
        int(crop_area[1]),
        int(crop_area[2]),
        int(crop_area[3])
    ]


def _clamp_box(box: List[int], bounds: List[int]) -> List[int]:
    left, top, right, bottom = bounds
    x1 = max(left, min(int(round(box[0])), right - 1))
    y1 = max(top, min(int(round(box[1])), bottom - 1))
    x2 = max(x1 + 1, min(int(round(box[2])), right))
    y2 = max(y1 + 1, min(int(round(box[3])), bottom))
    return [x1, y1, x2, y2]


def _intersects_or_near(box_a: List[int], box_b: List[int], margin: int) -> bool:
    return not (
        box_b[2] < box_a[0] - margin or
        box_b[0] > box_a[2] + margin or
        box_b[3] < box_a[1] - margin or
        box_b[1] > box_a[3] + margin
    )



def _axis_overlap_ratio(start_a: int, end_a: int, start_b: int, end_b: int) -> float:
    overlap = max(0, min(end_a, end_b) - max(start_a, start_b))
    base = max(1, min(end_a - start_a, end_b - start_b))
    return float(overlap) / float(base)



def _to_normalized(pixel_value: int, dimension: int) -> int:

    return max(0, min(1000, int(round(pixel_value / float(max(1, dimension)) * 1000))))


def _normalize_question_number(question_number: Optional[str]) -> Optional[str]:
    if question_number is None:
        return None
    match = re.search(r"\d+", str(question_number))
    if not match:
        return None
    return str(int(match.group(0)))
