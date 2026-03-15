import argparse
import os
import sys
import json
import glob
from datetime import datetime

# --- Add project root to sys.path ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
# -------------------------------------

from shared.database import SessionLocal, get_db
from shared import models
from shared.models import Prompt, PromptVersion

from src.tasks.task_classify_page import run_classification
from src.tasks.task_perspective_correction import run_perspective_correction
from src.tasks.task_analyze_layout import run_layout_analysis
from src.tasks.task_extract_content import run_content_extraction
from src.tasks.task_merge_results import run_merge_results
from src.tasks.task_draw_output import run_draw_output

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PIPELINE_STEPS = [
    {'step': 1, 'name': 'perspective_correction', 'func': run_perspective_correction, 'output_file': '01_correction_output.json'},
    {'step': 2, 'name': 'classify', 'func': run_classification, 'output_file': '02_classify_output.json'},
    {'step': 3, 'name': 'analyze_layout', 'func': run_layout_analysis, 'output_file': '03_layout_output.json'},
    {'step': 4, 'name': 'extract_content', 'func': run_content_extraction, 'output_file': '04_content_output.json'},
    {'step': 5, 'name': 'merge_results', 'func': run_merge_results, 'output_file': '05_merged_output.json'},
    {'step': 6, 'name': 'draw_output', 'func': run_draw_output, 'output_file': '06_final_output'} # This last one is a directory
]

def main():
    parser = argparse.ArgumentParser(description="Exam Analysis RAG Pipeline")
    
    # Mode selection
    parser.add_argument('--input-dir', type=str, help='Directory containing input images for a real run.')
    parser.add_argument('--test-case', type=str, help='Name of the test case to run (uses real images from tests/test_cases).')

    # Step control
    parser.add_argument('--start-step', type=int, default=1, help='The step number to start from (1-based).')
    parser.add_argument('--end-step', type=int, default=len(PIPELINE_STEPS), help='The step number to end at (inclusive).')

    # Recording
    parser.add_argument('--record-case', type=str, help='If specified, saves all intermediate results to a new mock case with this name.')

    # Mocking / Hybrid execution
    parser.add_argument('--mock-case', type=str, help='Name of the mock data case to use for a hybrid run.')
    parser.add_argument('--real-steps', nargs='+', type=int, help='A list of step numbers to run with real API calls; others use mock data.')
    parser.add_argument('--prompt-version', type=str, default='v3', help='Fallback prompt version to use if DB is unavailable (e.g., v1, v2, v3).')

    # LLM Configuration
    parser.add_argument('--provider', type=str, help='Name of the API provider to use (e.g., Dashscope). Overrides environment variables.')
    parser.add_argument('--model', type=str, help='Name of the LLM model to use. If specified, provider must also be specified or will be inferred.')
    parser.add_argument('--api-key', type=str, help='Directly provide the API key, bypassing database lookup for the key.')

    # Manual workspace override
    parser.add_argument('--output-dir', type=str, help='Explicitly specify the output directory for all artifacts.')
    parser.add_argument('--workspace', type=str, help='DEPRECATED: Explicitly specify the workspace directory to use, overriding automatic creation.')

    args = parser.parse_args()

    # --- Argument validation ---
    # ... (rest of the validation logic remains the same)

    # --- Determine run mode, workspace, and input directory ---
    workspace_dir = None
    input_dir = None

    if args.output_dir:
        workspace_dir = os.path.abspath(args.output_dir)
    elif args.workspace:
        print("Warning: --workspace is deprecated. Please use --output-dir instead.")
        workspace_dir = os.path.abspath(args.workspace)
    
    if args.record_case:
        workspace_dir = os.path.join(BASE_DIR, 'tests', 'mock_data', args.record_case)
    
    if not workspace_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace_dir = os.path.join(BASE_DIR, 'temp', f'run_{timestamp}')

    os.makedirs(workspace_dir, exist_ok=True)

    if args.input_dir:
        input_dir = os.path.abspath(args.input_dir)
        print(f"\n--- Running in REAL mode on directory: {input_dir} ---")
    elif args.test_case:
        input_dir = os.path.join(BASE_DIR, 'tests', 'test_cases', args.test_case)
        print(f"\n--- Running in TEST mode on case: {args.test_case} ---")
    elif args.mock_case:
        input_dir = os.path.join(BASE_DIR, 'tests', 'mock_data', args.mock_case)
        print(f"\n--- Running in MOCK/HYBRID mode with case: {args.mock_case} ---")

    if not input_dir:
        parser.error("Could not determine input directory. Please specify --input-dir, --test-case, or --mock-case.")

    if not os.path.isdir(input_dir):
        parser.error(f"Input directory not found: {input_dir}")

    print(f"Workspace for this run: {workspace_dir}\n")

    # --- Get LLM Config from DB (based on new args) or fallback ---
    llm_config = {}
    db = SessionLocal()
    try:
        if args.provider:
            print(f"Fetching LLM config from DB for provider: {args.provider}")
            provider_obj = db.query(models.APIProvider).filter(models.APIProvider.name == args.provider).first()
            if not provider_obj:
                raise ValueError(f"Provider '{args.provider}' not found in the database.")
            
            model_obj = None
            if args.model:
                model_obj = db.query(models.LLMModel).filter(models.LLMModel.name == args.model, models.LLMModel.provider_id == provider_obj.id).first()
                if not model_obj:
                    raise ValueError(f"Model '{args.model}' not found for provider '{args.provider}' in the database.")
            else:
                model_obj = provider_obj.models[0] if provider_obj.models else None
                if not model_obj:
                    raise ValueError(f"No models found for provider '{args.provider}' in the database.")

            llm_config["api_url"] = provider_obj.api_url
            llm_config["api_key"] = args.api_key if args.api_key else provider_obj.encrypted_api_key
            llm_config["model_name"] = model_obj.name
            print(f"  -> Successfully configured to use Model '{llm_config['model_name']}' from '{provider_obj.name}'.")

    except Exception as e:
        print(f"[Error] Failed to configure LLM from database: {e}")
        sys.exit(1)
    finally:
        db.close()


    # --- Get latest prompts from DB (with fallback) ---
    db = SessionLocal()
    content_extraction_prompt = None
    try:
        # Fetching the latest version of the content extraction prompt by finding the max version number
        all_extraction_prompts = db.query(Prompt).filter(Prompt.name.like("extract_content_v%")).all()
        if all_extraction_prompts:
            latest_prompt_obj = max(all_extraction_prompts, key=lambda p: int(p.name.split('_v')[-1]))
            if latest_prompt_obj.versions:
                content_extraction_prompt = latest_prompt_obj.versions[0].prompt_text
                print(f"Successfully fetched prompt '{latest_prompt_obj.name}' from the database.")
            else:
                print(f"[Warning] Prompt '{latest_prompt_obj.name}' found, but it has no versions.")
        else:
            print("[Warning] Could not find any 'extract_content_v*' prompts in DB.")
    except Exception as e:
        print(f"[Warning] Database connection failed: {e}")
    finally:
        db.close()

    if not content_extraction_prompt:
        print(f"  -> Falling back to using local prompt version: {args.prompt_version}")
        # If DB fetch fails, we pass the version string to the task, 
        # which will then handle loading from the local file system.
        content_extraction_prompt = args.prompt_version

    # --- Execute pipeline steps ---
    current_input = None # This will hold the output path of the previous step

    # Determine the source for mock data if needed
    mock_source_dir = None
    if args.test_case:
        # Full mock run based on a test case
        mock_source_dir = os.path.join('tests', 'mock_data', args.test_case)
    elif args.mock_case:
        # Hybrid run using a specified mock case
        mock_source_dir = os.path.join('tests', 'mock_data', args.mock_case)

    for step_info in PIPELINE_STEPS:
        step_number = step_info['step']
        step_name = step_info['name']
        step_func = step_info['func']
        step_output_file = step_info['output_file']

        if step_number < args.start_step:
            print(f"Skipping Step {step_number}: {step_name}")
            continue
        
        if step_number > args.end_step:
            print(f"Stopping before Step {step_number}: {step_name}")
            break

        # --- Determine Step Input ---
        if current_input is None:
            # This happens if it's the first step to be run.
            if step_number == 1:
                # The very first step's input is the image directory for a real/hybrid run
                if args.input_dir:
                    image_paths = sorted([os.path.join(args.input_dir, f) for f in os.listdir(args.input_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                    if not image_paths:
                        print(f"Error: No images found in {args.input_dir}")
                        break
                    step_input = image_paths
                else: # Should be a test_case run
                    step_input = None # In a full mock run, the first step is also mocked.
            else:
                # We are starting mid-pipeline, so we need to find the previous step's output file.
                prev_step_output_file = PIPELINE_STEPS[step_number - 2]['output_file']
                step_input = os.path.join(workspace_dir, prev_step_output_file)
                if not os.path.exists(step_input):
                    print(f"Error: Prerequisite input file not found for step '{step_name}': {step_input}")
                    break
                print(f"  Loading input from previous step's file: {step_input}")
        else:
            step_input = current_input
            print(f"  Using input from previous step's output in memory.")

        # --- Decide whether to Mock or Run for Real ---
        use_mock = False
        if mock_source_dir:
            use_mock = True # Default to mock if a mock source is set
            if args.real_steps and step_number in args.real_steps:
                use_mock = False # Override if this step is flagged as real

        step_output_path = os.path.join(workspace_dir, step_output_file)

        if use_mock and step_name != 'draw_output':
            print(f"--- Mocking Step {step_number}: {step_name} ---")
            mock_file_path = os.path.join(mock_source_dir, step_output_file)
            
            if not os.path.exists(mock_file_path):
                print(f"  [Error] Mock file not found: {mock_file_path}")
                print(f"  Cannot proceed. Please provide the mock file or mark this step as real.")
                break

            print(f"  Loading mock output from: {mock_file_path}")

            # In a mock run, we copy the mock data to the current workspace to simulate a real run's file structure.
            import shutil
            if os.path.isdir(mock_file_path):
                if os.path.exists(step_output_path):
                    shutil.rmtree(step_output_path)
                shutil.copytree(mock_file_path, step_output_path)
            else:
                os.makedirs(os.path.dirname(step_output_path), exist_ok=True)
                shutil.copy(mock_file_path, step_output_path)
            
            current_input = step_output_path

        else: # Run for Real
            print(f"--- Running Step {step_number}: {step_name} ---")
            if step_input is None and step_number != 1:
                 print(f"  [Error] Cannot run step {step_number} for real without input from previous step.")
                 break
            
            # Re-architected call logic: Pass explicit, individual parameters instead of the llm_config dict.
            print(f"\n[DEBUG-TRACE] About to call step: '{step_name}'")
            print(f"[DEBUG-TRACE]   - step_input type: {type(step_input)}")
            print(f"[DEBUG-TRACE]   - llm_config keys: {llm_config.keys() if llm_config else 'None'}")

            if step_name in ['perspective_correction', 'classify']:
                current_input = step_func(
                    step_input,
                    step_output_path,
                    api_key=llm_config.get('api_key'),
                    model_name=llm_config.get('model_name'),
                    api_url=llm_config.get('api_url')
                )
            elif step_name == 'extract_content':
                current_input = step_func(
                    step_input,
                    step_output_path,
                    content_extraction_prompt,
                    workspace_dir,
                    api_key=llm_config.get('api_key'),
                    model_name=llm_config.get('model_name'),
                    api_url=llm_config.get('api_url')
                )
            else:
                current_input = step_func(step_input, step_output_path)

    print("--- Pipeline finished. ---")

if __name__ == "__main__":
    main()
