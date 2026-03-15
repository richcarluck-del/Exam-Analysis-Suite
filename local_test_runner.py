import sys
import os
import subprocess

# --- Add project root to sys.path ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)
# -------------------------------------

from shared.database import SessionLocal
from shared import models
from analyzer.app.security import decrypt_api_key

def run_local_test():
    """Simulates the test run process locally without the UI."""
    print("--- [Local Test Runner] Starting --- ")
    
    # 1. --- Get Config from DB ---
    db = SessionLocal()
    try:
        print("Connecting to DB to fetch configs...")
        provider_obj = db.query(models.APIProvider).filter(models.APIProvider.name == 'dashscope').first()
        # Try qwen-vl-max first (vision model), then fallback to qwen3-max, then qwen-plus
        model_obj = db.query(models.LLMModel).filter(
            models.LLMModel.name == 'qwen-vl-max', 
            models.LLMModel.provider_id == provider_obj.id
        ).first()
        
        if not model_obj:
            model_obj = db.query(models.LLMModel).filter(
                models.LLMModel.name == 'qwen3-max',
                models.LLMModel.provider_id == provider_obj.id
            ).first()
        
        if not model_obj:
            model_obj = db.query(models.LLMModel).filter(
                models.LLMModel.name == 'qwen-plus',
                models.LLMModel.provider_id == provider_obj.id
            ).first()

        if not provider_obj or not model_obj:
            print("Error: Could not find provider 'dashscope' or any vision model in the database.")
            return

        print(f"Found Provider: {provider_obj.name}")
        print(f"Found Model: {model_obj.name}")

        # 2. --- Decrypt API Key ---
        encrypted_key = provider_obj.encrypted_api_key
        decrypted_key = decrypt_api_key(encrypted_key)
        print(f"API Key decrypted successfully.")

    finally:
        db.close()

    # 3. --- Construct Command ---
    preprocessor_script = os.path.join(project_root, "preprocessor", "main.py")
    input_dir = os.path.join(project_root, "preprocessor", "my_test_images")

    command = [
        sys.executable, 
        preprocessor_script,
        '--input-dir', input_dir,
        '--provider', provider_obj.name,
        '--api-key', decrypted_key,
        '--model', model_obj.name,
        '--prompt-version', 'v4' # Hardcoding for test
    ]

    print(f"\nExecuting command:\n{' '.join(command)}\n")

    # 4. --- Run and Stream Output ---
    sub_env = os.environ.copy()
    sub_env["PYTHONIOENCODING"] = "utf-8"
    
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        env=sub_env,
        cwd=os.path.dirname(__file__)
    )

    error_found = False
    while True:
        output = process.stdout.readline()
        if output == '' and process.poll() is not None:
            break
        if output:
            print(f"[STDOUT] {output.strip()}")
            if '未提供任何图片' in output:
                error_found = True

    stderr = process.communicate()[1]
    if stderr:
        print("[STDERR] --------------")
        print(stderr)

    stderr = process.communicate()[1]
    if stderr:
        print("[STDERR] --------------")
        print(stderr)

    print("--- [Local Test Runner] Finished --- ")
    if error_found:
        print("\n[RESULT] >>> FAILURE: '未提供任何图片' error was found in the output.")
        sys.exit(1) # Exit with a failure code

    if process.returncode != 0:
        print(f"\n[RESULT] >>> FAILURE: Process exited with non-zero code {process.returncode}.")
        sys.exit(1)

    print("\n[RESULT] >>> SUCCESS: The test ran without the specific '未提供任何图片' error and exited cleanly.")

if __name__ == "__main__":
    run_local_test()
