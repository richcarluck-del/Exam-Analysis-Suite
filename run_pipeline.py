import argparse
import os
import sys
import subprocess
from datetime import datetime

def run_pipeline():
    parser = argparse.ArgumentParser(description="End-to-end pipeline for Exam Analysis Suite.")
    parser.add_argument("--input-dir", required=True, help="Directory containing the original exam images.")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.abspath(__file__))
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace_dir = os.path.join(project_root, "temp_workspace", f"run_{timestamp}")
    os.makedirs(workspace_dir, exist_ok=True)

    print(f"--- Starting End-to-End Pipeline ---")
    print(f"Workspace for this run: {workspace_dir}")

    # --- Step 1: Run Preprocessor ---
    print("\n--- Running Preprocessor Module ---")
    preprocessor_script = os.path.join(project_root, "preprocessor", "main.py")
    preprocessor_output_dir = os.path.join(workspace_dir, "preprocessor_output")
    
    preprocessor_command = [
        sys.executable, # Use the same python interpreter that runs this script
        preprocessor_script,
        "--input-dir", args.input_dir,
        "--output-dir", preprocessor_output_dir
    ]

    try:
        subprocess.run(preprocessor_command, check=True, text=True, encoding='utf-8')
        print("--- Preprocessor Module Finished Successfully ---")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Preprocessor module failed with exit code {e.returncode}.")
        print(f"Stderr: {e.stderr}")
        return # Stop the pipeline if preprocessor fails

    # --- Step 2: Run Analyzer ---
    print("\n--- Running Analyzer Module ---")
    analyzer_script = os.path.join(project_root, "analyzer", "run.py")
    analyzer_output_dir = os.path.join(workspace_dir, "analyzer_output")

    analyzer_command = [
        sys.executable, # Use the same python interpreter
        analyzer_script,
        "--input-dir", preprocessor_output_dir, # Use preprocessor's output as input
        "--output-dir", analyzer_output_dir
    ]

    try:
        subprocess.run(analyzer_command, check=True, text=True, encoding='utf-8')
        print("--- Analyzer Module Finished Successfully ---")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Analyzer module failed with exit code {e.returncode}.")
        print(f"Stderr: {e.stderr}")
        return

    print("\n--- End-to-End Pipeline Finished Successfully ---")
    print(f"Final analysis report can be found in: {analyzer_output_dir}")

if __name__ == "__main__":
    run_pipeline()
