import argparse
import json
import sys
import os
from collections import defaultdict

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.merger import merge_same_number_questions

def run_merge_results(content_extraction_path: str, output_path: str):
    """
    Reads content extraction results, groups them by original image,
    and uses the merger to create the final merged output.
    """
    with open(content_extraction_path, 'r', encoding='utf-8') as f:
        content_results = json.load(f)

    print(f"  Starting result merging for {len(content_results)} content parts...")

    # The new merger function takes the entire list of content parts and handles grouping internally.
    all_merged_questions = merge_same_number_questions(content_results)

    # Sort the final

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_merged_questions, f, indent=2, ensure_ascii=False)

    print(f"  Merged results saved to: {output_path}")
    return output_path

def main():
    """
    Command-line entry point for standalone testing of the merging task.
    """
    parser = argparse.ArgumentParser(description="Merge content extraction results.")
    parser.add_argument("--input-path", required=True, help="Path to the content extraction output JSON file.")
    parser.add_argument("--output-path", required=True, help="Path to save the merged output JSON file.")
    args = parser.parse_args()

    if not os.path.exists(args.input_path):
        print(f"Error: Input file not found: {args.input_path}")
        sys.exit(1)

    try:
        run_merge_results(args.input_path, args.output_path)
    except Exception as e:
        print(f"An error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
