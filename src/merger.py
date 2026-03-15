import os
from collections import defaultdict

def merge_same_number_questions(all_parts_results: list):
    """Groups all question fragments by their original source image."""
    results_by_image = defaultdict(list)

    for item in all_parts_results:
        vlm_output = item.get('vlm_output')
        if not vlm_output or 'questions' not in vlm_output:
            continue

        source_image = item.get('source_image_path')
        if not source_image:
            continue

        # Just pass all fragments from the VLM output, along with their context
        for question_item in vlm_output['questions']:
            if not isinstance(question_item, dict):
                continue
            
            # Create a comprehensive fragment object
            fragment = {
                **question_item,  # This includes 'number', 'points', 'description', etc.
                "source_original_image": item.get('source_image_path'),
                "source_corrected_image": item.get('source_corrected_image'),
                "source_part_image": item.get('part_image_path'),
                "crop_area": item.get('crop_area'),
                "divider_x": item.get('divider_x')
            }
            results_by_image[source_image].append(fragment)

    # The output is now a dictionary, keyed by the original image path
    return results_by_image
