import argparse
import json
import os
import sys
from PIL import Image

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.a3_splitter import A3Splitter, PagePart
from src.utils import call_api, extract_json
from src.prompts import PROMPT_EXAM_PAPER_JSON


def run_layout_analysis(classification_input_path: str, output_path: str, api_key: str = None, model_name: str = None, api_url: str = None):
    """
    Performs layout analysis on each page.
    If a page is classified as a question paper or mixed, it is first split into
    left and right halves before layout analysis is performed on each half.
    """
    with open(classification_input_path, 'r', encoding='utf-8') as f:
        pages_to_analyze = json.load(f)
    
    print(f"  Starting layout analysis for {len(pages_to_analyze)} pages...")
    all_layout_results = []
    splitter = A3Splitter()

    for page_info in pages_to_analyze:
        image_path = page_info['image_path']
        page_type = page_info['page_type']
        divider_x = 0 # Default to 0 if not split
        
        page_parts = []
        # If the page is a question paper or mixed, split it.
        # Only attempt to split images that are likely full A3 pages (i.e., their names don't contain _left or _right)
        # and are classified as types that might need splitting.
        filename = os.path.basename(image_path)
        if not ('_left' in filename or '_right' in filename):
            print(f"    -> A3 page detected ({filename}). Splitting for layout analysis.")
            # This might return None if splitting fails, so we handle that.
            split_parts = splitter.split_a3_page(image_path)
            if split_parts and len(split_parts) == 2:
                page_parts = split_parts
                # Calculate divider_x from the width of the left part
                with Image.open(page_parts[0].image_path) as left_img:
                    divider_x = left_img.width
                print(f"      Calculated divider_x: {divider_x}")
            else:
                # If splitting fails or returns unexpected parts, treat it as a single full page.
                if not split_parts:
                    print(f"      [Warning] Splitting failed for {filename}. Treating as a single page.")
                else:
                    print(f"      [Warning] Splitting returned {len(split_parts)} parts for {filename}. Treating as single pages.")
                # Use existing parts if available, otherwise create a new one
                if not split_parts:
                    with Image.open(image_path) as img:
                        width, height = img.size
                    page_parts.append(PagePart(image_path=image_path, part_type='full', crop_area=(0, 0, width, height)))
                else:
                    page_parts.extend(split_parts)
        else:
            # If it's an answer sheet, or already a part, treat it as a single part.
            part_type = 'full'
            if '_left' in filename:
                part_type = 'left'
            elif '_right' in filename:
                part_type = 'right'
            # For single pages/parts, the crop area is the full image dimension.
            with Image.open(image_path) as img:
                width, height = img.size
            crop_area = (0, 0, width, height)
            print(f"    -> Single page/part detected ({filename}). Processing as is.")
            page_parts.append(PagePart(image_path=image_path, part_type=part_type, crop_area=crop_area))

        # --- Perform layout analysis on each part (whether it's a split half or a full page) ---
        for part in page_parts:
            print(f"      Analyzing layout for: {os.path.basename(part.image_path)} ({part.part_type})")
            
            # This is where the actual VLM call for layout analysis happens.
            # We are creating a simplified representation for now, as was the case before.
            # The next step 'extract_content' will do the detailed VLM call.
            # This step's main job is to identify the parts and their paths correctly.
            with Image.open(part.image_path) as img:
                width, height = img.size

            layout_result = {
                "original_image_path": page_info.get('original_image_path', image_path), # Fallback for older formats
                "source_corrected_image": image_path, # CRITICAL: Pass the path to the corrected A3 image
                "page_type": page_type, # The type of the original whole page
                "page_index": page_info['page_index'],
                # IMPORTANT: The 'parts' key now contains the actual layout info for ONE part.
                # The structure is a bit confusing, but we are keeping it for consistency with the next step.
                "image_path": part.image_path, # Path to the part image
                "part_type": part.part_type, # 'left', 'right', or 'full'
                "crop_area": part.crop_area, # CRITICAL: Pass the crop_area for coordinate conversion
                "divider_x": divider_x, # Pass divider_x for coordinate conversion in drawing step
                "parts": [ # This list will be populated by the VLM call in the *next* step.
                           # For now, we just define the whole area.
                    {
                        "label": "full_page_area",
                        "box": [0, 0, width, height]
                    }
                ]
            }
            all_layout_results.append(layout_result)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_layout_results, f, indent=2, ensure_ascii=False)
        
    print(f"  Layout analysis results saved to: {output_path}")
    return output_path

def main():
    """
    Command-line entry point for standalone testing of the layout analysis task.
    """
    parser = argparse.ArgumentParser(description="Run layout analysis on a classification output file.")
    parser.add_argument("--input-path", required=True, help="Path to the classification output JSON file.")
    parser.add_argument("--output-path", required=True, help="Path to save the output layout JSON file.")
    args = parser.parse_args()

    if not os.path.exists(args.input_path):
        print(f"Error: Input file not found: {args.input_path}")
        sys.exit(1)

    try:
        run_layout_analysis(args.input_path, args.output_path)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
