import argparse
import json
import os
import sys
import base64
from PIL import Image

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils import call_api, extract_json
from src.prompts import PROMPTS

def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def run_content_extraction(layout_input_path: str, output_path: str, prompt_or_version: str, workspace_dir: str, api_key: str, model_name: str, api_url: str):
    """
    Extracts content from all page parts defined in the layout analysis output.

    Args:
        layout_input_path (str): Path to the JSON file from the layout analysis step.
        output_path (str): The path to save the output content JSON file.
        prompt_or_version (str): Can be either the full prompt text (if fetched from DB)
                                 or a version string (e.g., 'v3') to load from local prompts.
        workspace_dir (str): The directory for the current run, to save the used prompts.
    """
    with open(layout_input_path, 'r', encoding='utf-8') as f:
        parts_to_process = json.load(f)

    print(f"  Starting content extraction for {len(parts_to_process)} parts...")
    all_extracted_content = []

    # Determine if we have the full prompt text or just a version key
    base_prompt_text = None
    if '{' in prompt_or_version and '}' in prompt_or_version:
        print("    Using full prompt text passed directly.")
        base_prompt_text = prompt_or_version
    else:
        print(f"    Loading prompt from local store using version key: {prompt_or_version}")
        if prompt_or_version not in PROMPTS:
            raise ValueError(f"Prompt version '{prompt_or_version}' is not valid. Available versions: {list(PROMPTS.keys())}")
        # In this case, we have a dictionary of prompts for different page types
        prompt_set = PROMPTS[prompt_or_version]

    for part_info in parts_to_process:
        page_type = part_info['page_type']
        part_image_path = part_info['image_path']
        part_basename = os.path.basename(part_image_path)
        part_type = part_info.get('part_type', 'full')
        print(f"    Processing part: {part_basename} (Type: {page_type})")

        # 1. Select the appropriate prompt
        if base_prompt_text:
            prompt = base_prompt_text # Use the direct text for all parts
        else:
            # Fallback to using the version set and page type
            prompt = prompt_set.get(page_type, prompt_set['mixed'])
        
        # 2. Replace {side} placeholder with actual part type
        prompt = prompt.replace('{side}', part_type)

        # 3. Save the used prompt to the workspace for traceability
        prompt_save_path = os.path.join(workspace_dir, f"prompt_used_for_{part_basename}.txt")
        with open(prompt_save_path, 'w', encoding='utf-8') as f_prompt:
            f_prompt.write(prompt)
        print(f"      Saved prompt to: {prompt_save_path}")

        # 4. Call the VLM API and extract JSON
        try:
            api_response = call_api(
                prompt=prompt, 
                image_path=part_image_path,
                api_url=api_url,
                api_key=api_key,
                model_name=model_name
            )
            json_string = extract_json(api_response)
            extracted_data = json.loads(json_string)
        except Exception as e:
            print(f"      ERROR calling API or extracting JSON for {part_basename}: {e}")
            extracted_data = {"error": str(e)}

        # 5. Add context and append to results
        content_result = {
            "source_image_path": part_info['original_image_path'],
            "source_corrected_image": part_info.get('source_corrected_image'), # Pass corrected A3 image path along
            "part_image_path": part_image_path,
            "page_type": page_type,
            "page_index": part_info['page_index'],
            "part_type": part_info.get('part_type', 'full'),
            "crop_area": part_info.get('crop_area'), # Pass crop_area along
            "divider_x": part_info.get('divider_x', 0), # Pass divider_x along
            "vlm_output": extracted_data
        }
        all_extracted_content.append(content_result)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_extracted_content, f, indent=2, ensure_ascii=False)

    print(f"  Content extraction results saved to: {output_path}")
    return output_path

def main():
    """
    Command-line entry point for standalone testing of the content extraction task.
    """
    parser = argparse.ArgumentParser(description="Run content extraction on a layout analysis output file.")
    parser.add_argument("--input-path", required=True, help="Path to the layout analysis output JSON file.")
    parser.add_argument("--output-path", required=True, help="Path to save the output content JSON file.")
    args = parser.parse_args()

    if not os.path.exists(args.input_path):
        print(f"Error: Input file not found: {args.input_path}")
        sys.exit(1)

    try:
        run_content_extraction(args.input_path, args.output_path)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
