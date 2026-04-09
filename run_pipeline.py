import argparse
import os
import subprocess
import sys
from datetime import datetime


def append_optional_arg(command, flag, value):
    if value not in (None, ""):
        command.extend([flag, str(value)])



def run_pipeline():
    parser = argparse.ArgumentParser(description="End-to-end pipeline for Exam Analysis Suite.")
    parser.add_argument("--input-dir", required=True, help="Directory containing the original exam images.")
    parser.add_argument("--workspace-dir", help="Optional root workspace directory for this run.")

    parser.add_argument("--student-id", help="Optional student identifier.")
    parser.add_argument("--exam-id", help="Optional exam identifier.")
    parser.add_argument("--paper-id", help="Optional paper identifier.")
    parser.add_argument("--subject", help="Optional subject.")
    parser.add_argument("--grade", help="Optional grade.")
    parser.add_argument("--class-id", help="Optional class identifier.")
    parser.add_argument("--organization-id", help="Optional organization identifier.")

    parser.add_argument("--provider", help="Optional preprocessor LLM provider.")
    parser.add_argument("--model", help="Optional preprocessor LLM model.")
    parser.add_argument("--api-key", help="Optional preprocessor API key.")
    parser.add_argument("--prompt-version", help="Optional prompt version.")
    parser.add_argument("--classification-method", choices=["single_page", "long_image"], help="Optional classification method.")
    parser.add_argument("--a3-strategy", choices=["split", "whole", "both"], help="Optional A3 processing strategy.")
    parser.add_argument("--answer-card-provider", help="Optional answer card provider.")
    parser.add_argument("--answer-card-model", help="Optional answer card model.")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    if args.workspace_dir:
        workspace_dir = os.path.abspath(args.workspace_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace_dir = os.path.join(project_root, "temp_workspace", f"run_{timestamp}")
    os.makedirs(workspace_dir, exist_ok=True)

    print("--- Starting End-to-End Pipeline ---")
    print(f"Workspace for this run: {workspace_dir}")

    print("\n--- Running Preprocessor Module ---")
    preprocessor_script = os.path.join(project_root, "preprocessor", "main.py")
    preprocessor_output_dir = os.path.join(workspace_dir, "preprocessor_output")

    preprocessor_command = [
        sys.executable,
        preprocessor_script,
        "--input-dir", os.path.abspath(args.input_dir),
        "--output-dir", preprocessor_output_dir
    ]

    for flag, value in [
        ("--student-id", args.student_id),
        ("--exam-id", args.exam_id),
        ("--paper-id", args.paper_id),
        ("--subject", args.subject),
        ("--grade", args.grade),
        ("--class-id", args.class_id),
        ("--organization-id", args.organization_id),
        ("--provider", args.provider),
        ("--model", args.model),
        ("--api-key", args.api_key),
        ("--prompt-version", args.prompt_version),
        ("--classification-method", args.classification_method),
        ("--a3-strategy", args.a3_strategy),
        ("--answer-card-provider", args.answer_card_provider),
        ("--answer-card-model", args.answer_card_model)
    ]:
        append_optional_arg(preprocessor_command, flag, value)

    try:
        subprocess.run(preprocessor_command, check=True, text=True, encoding="utf-8")
        print("--- Preprocessor Module Finished Successfully ---")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Preprocessor module failed with exit code {e.returncode}.")
        raise SystemExit(e.returncode) from e

    print("\n--- Running Analyzer Module ---")
    analyzer_script = os.path.join(project_root, "analyzer", "run.py")
    analyzer_output_dir = os.path.join(workspace_dir, "analyzer_output")

    analyzer_command = [
        sys.executable,
        analyzer_script,
        "--bundle-dir", preprocessor_output_dir,
        "--output-dir", analyzer_output_dir
    ]

    try:
        subprocess.run(analyzer_command, check=True, text=True, encoding="utf-8")
        print("--- Analyzer Module Finished Successfully ---")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Analyzer module failed with exit code {e.returncode}.")
        raise SystemExit(e.returncode) from e

    print("\n--- End-to-End Pipeline Finished Successfully ---")
    print(f"Preprocessor bundle directory: {preprocessor_output_dir}")
    print(f"Final analysis report directory: {analyzer_output_dir}")


if __name__ == "__main__":
    run_pipeline()

