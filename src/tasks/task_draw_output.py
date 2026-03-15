import json
import os
import sys
from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255), 
    (255, 0, 255), (192, 192, 192), (128, 0, 0), (128, 128, 0), (0, 128, 0)
]

def get_font(size):
    try:
        return ImageFont.truetype("simsun.ttc", size, encoding="utf-8")
    except IOError:
        return ImageFont.load_default()

def run_draw_output(merged_results_path: str, output_dir: str):
    with open(merged_results_path, 'r', encoding='utf-8') as f:
        fragments_by_image = json.load(f)

    os.makedirs(output_dir, exist_ok=True)
    print(f"  Starting to draw final output for images...")

    # The data is already grouped by the original image path. 
    # We need to find the corrected image path for each group to use as a canvas.
    print(f"  Found {len(fragments_by_image)} unique images to process.")

    for original_image_path, fragments in fragments_by_image.items():
        if not fragments:
            continue

        # Use the corrected path from the first fragment as the canvas
        corrected_image_path = fragments[0].get("source_corrected_image")
        if not corrected_image_path or not os.path.exists(corrected_image_path):
            print(f"    [Error] Corrected image not found for {original_image_path}. Skipping.")
            continue

        img = Image.open(corrected_image_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        font = get_font(60)

        # Group fragments on THIS image by their question number
        questions_on_this_image = defaultdict(list)
        for frag in fragments:
            q_num = frag.get("number", "N/A")
            questions_on_this_image[q_num].append(frag)

        # Sort question numbers for consistent coloring
        sorted_q_nums = sorted(questions_on_this_image.keys(), key=lambda q: int(q) if q.isdigit() else float('inf'))

        for i, q_num in enumerate(sorted_q_nums):
            question_fragments = questions_on_this_image[q_num]
            color = COLORS[i % len(COLORS)]
            fragment_centers = []

            for frag_idx, frag in enumerate(question_fragments):
                # --- 1. Coordinate Transformation ---
                crop_area = frag.get("crop_area")
                if not crop_area or len(crop_area) != 4:
                    continue
                offset_x, offset_y, part_x_end, part_y_end = crop_area
                part_w, part_h = part_x_end - offset_x, part_y_end - offset_y

                points_data = frag.get('points')
                if not points_data or not isinstance(points_data, dict):
                    continue
                
                box_points_normalized = [tuple(points_data[k]) for k in ['top_left', 'top_right', 'bottom_right', 'bottom_left']]

                absolute_points = [
                    (offset_x + (nx / 1000 * part_w), offset_y + (ny / 1000 * part_h))
                    for nx, ny in box_points_normalized if nx is not None and ny is not None
                ]
                if len(absolute_points) != 4:
                    continue

                # --- 2. Draw polygon for EACH fragment ---
                draw.polygon(absolute_points, outline=color, width=3)

                # --- 3. Calculate center and draw label ---
                min_x = min(p[0] for p in absolute_points)
                min_y = min(p[1] for p in absolute_points)
                max_x = max(p[0] for p in absolute_points)
                max_y = max(p[1] for p in absolute_points)
                
                center_x = (min_x + max_x) / 2
                center_y = (min_y + max_y) / 2
                fragment_centers.append((center_x, center_y))

                label = f"Q{q_num}"
                num_fragments = len(question_fragments)
                if num_fragments > 1:
                    label += f" [{frag_idx+1}/{num_fragments}]"

                text_bbox_size = draw.textbbox((0, 0), label, font=font)
                text_width = text_bbox_size[2] - text_bbox_size[0]
                text_pos = (max_x - text_width - 5, min_y + 5)

                text_bbox = draw.textbbox(text_pos, label, font=font)
                draw.rectangle(text_bbox, fill=color)
                draw.text(text_pos, label, fill="white", font=font)

            # --- 4. Draw connecting line ---
            if len(fragment_centers) > 1:
                draw.line(fragment_centers, fill=color, width=2, joint="curve")

        # --- 5. Save Image ---
        output_filename = os.path.basename(corrected_image_path).replace("_corrected.jpg", "_final_output.jpg")
        output_path_final = os.path.join(output_dir, output_filename)
        img.save(output_path_final)
        print(f"    Final output saved to: {output_path_final}")

    print(f"  All output images saved in: {output_dir}")
    return output_dir
