import os
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont


def save_box_debug_visualizations(
    image_path: str,
    crop_area: List[int],
    regions: List[Dict],
    output_dir: str,
    filename_prefix: Optional[str] = None
) -> List[str]:
    if not image_path or not os.path.exists(image_path) or not regions:
        return []

    os.makedirs(output_dir, exist_ok=True)
    base_name = filename_prefix or os.path.splitext(os.path.basename(image_path))[0]

    original_img = Image.open(image_path).convert("RGB")
    refined_img = original_img.copy()
    compare_img = original_img.copy()

    draw_original = ImageDraw.Draw(original_img)
    draw_refined = ImageDraw.Draw(refined_img)
    draw_compare = ImageDraw.Draw(compare_img)
    font = _get_font(24)

    for region in regions:
        number = str(region.get("number", "?"))
        original_points = region.get("original_points")
        refined_points = region.get("refined_points")

        if original_points:
            polygon = _points_to_absolute_polygon(original_points, crop_area)
            if polygon:
                _draw_region(draw_original, polygon, f"Q{number}", (255, 215, 0), font)
                _draw_region(draw_compare, polygon, f"O:{number}", (255, 215, 0), font)

        if refined_points:
            polygon = _points_to_absolute_polygon(refined_points, crop_area)
            if polygon:
                _draw_region(draw_refined, polygon, f"Q{number}", (255, 0, 0), font)
                _draw_region(draw_compare, polygon, f"R:{number}", (255, 0, 0), font)

    output_paths = []
    for suffix, image in [
        ("vlm_boxes", original_img),
        ("refined_boxes", refined_img),
        ("compare_boxes", compare_img)
    ]:
        output_path = os.path.join(output_dir, f"{base_name}_{suffix}.jpg")
        image.save(output_path)
        output_paths.append(output_path)

    return output_paths



def _points_to_absolute_polygon(points: Dict, crop_area: List[int]) -> List[tuple]:
    if not isinstance(points, dict) or not crop_area or len(crop_area) != 4:
        return []

    left, top, right, bottom = crop_area
    part_w = max(1, right - left)
    part_h = max(1, bottom - top)
    ordered_keys = ["top_left", "top_right", "bottom_right", "bottom_left"]

    polygon = []
    for key in ordered_keys:
        value = points.get(key)
        if not isinstance(value, list) or len(value) != 2:
            return []
        x = left + float(value[0]) / 1000.0 * part_w
        y = top + float(value[1]) / 1000.0 * part_h
        polygon.append((x, y))
    return polygon



def _draw_region(draw: ImageDraw.ImageDraw, polygon: List[tuple], label: str, color: tuple, font) -> None:
    draw.polygon(polygon, outline=color, width=3)

    min_x = min(point[0] for point in polygon)
    min_y = min(point[1] for point in polygon)
    max_x = max(point[0] for point in polygon)

    text_bbox = draw.textbbox((0, 0), label, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    text_x = max(min_x + 4, max_x - text_width - 6)
    text_y = max(0, min_y + 4)
    background_box = (text_x - 3, text_y - 2, text_x + text_width + 3, text_y + text_height + 2)
    draw.rectangle(background_box, fill=color)
    draw.text((text_x, text_y), label, fill=(255, 255, 255), font=font)



def _get_font(size: int):
    try:
        return ImageFont.truetype("simsun.ttc", size, encoding="utf-8")
    except OSError:
        return ImageFont.load_default()
