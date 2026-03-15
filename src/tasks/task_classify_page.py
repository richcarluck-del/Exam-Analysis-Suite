import argparse
import json
import os
import sys

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.classifier import PageClassifier


def run_classification(correction_map_path: str, output_path: str, api_key: str, model_name: str, api_url: str):
    print(f"[DEBUG-TRACE] Entered 'run_classification' with:")
    print(f"[DEBUG-TRACE]   - correction_map_path: {correction_map_path}")
    print(f"[DEBUG-TRACE]   - api_key is None: {api_key is None}")
    print(f"[DEBUG-TRACE]   - model_name: {model_name}")
    print(f"[DEBUG-TRACE]   - api_url: {api_url}")
    """
    Reads a map of original-to-corrected images, classifies each corrected image,
    and saves the aggregated result. A3 splitting is deferred to the layout analysis step.
    """
    with open(correction_map_path, 'r', encoding='utf-8') as f:
        correction_map = json.load(f)

    print(f"  Starting classification for {len(correction_map)} corrected images...")
    classifier = PageClassifier()

    output_data = []
    page_counter = 0

    for item in correction_map:
        original_image = item['original_image_path']
        corrected_image = item['corrected_image_path']

        # Classify the single, whole, corrected image.
        print(f"    Classifying {os.path.basename(corrected_image)}...")
        page_result = classifier.classify(corrected_image, api_key=api_key, model_name=model_name, api_url=api_url)

        output_data.append({
            "image_path": corrected_image,  # Path to the corrected (but not split) image
            "page_type": page_result.page_type,
            "page_index": page_counter,
            "original_image_path": original_image,  # CRITICAL: Pass through the VERY original path
            "part_type": "full"  # Mark as full page, splitting will happen later
        })
        page_counter += 1

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"  Classification results saved to: {output_path}")
    return output_path

def main():
    """
    Command-line entry point for standalone testing of the classification task.
    """
    parser = argparse.ArgumentParser(description="Run classification on a correction map JSON.")
    parser.add_argument("--input-path", required=True, help="Path to the JSON file from the perspective correction step.")
    parser.add_argument("--output-path", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--config-path", required=True, help="Path to the configuration JSON file.")
    args = parser.parse_args()

    if not os.path.isfile(args.input_path):
        print(f"Error: Input file not found: {args.input_path}")
        sys.exit(1)

    if not os.path.isfile(args.config_path):
        print(f"Error: Config file not found: {args.config_path}")
        sys.exit(1)

    with open(args.config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    llm_config = config.get("page_classifier", {})

    try:
        run_classification(args.input_path, args.output_path, llm_config)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
