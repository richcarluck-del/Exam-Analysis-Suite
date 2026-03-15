import sys
import os
import json
import asyncio
from fastapi import FastAPI, Depends, WebSocket
from sqlalchemy.orm import Session
from fastapi.staticfiles import StaticFiles

# --- Add project root to sys.path ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)
# -------------------------------------

from shared.database import SessionLocal, Base, engine
from shared import models
from analyzer.app.security import decrypt_api_key

# --- Create DB tables on startup ---
models.Base.metadata.create_all(bind=engine)
# ----------------------------------

app = FastAPI()

# --- Dependency to get DB session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- API Endpoints for fetching data ---
@app.get("/api/providers")
def get_providers(db: Session = Depends(get_db)):
    return db.query(models.APIProvider).all()

@app.get("/api/models")
def get_models(db: Session = Depends(get_db)):
    return db.query(models.LLMModel).all()

@app.get("/api/prompts")
def get_prompts(db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    return db.query(models.Prompt).options(joinedload(models.Prompt.versions)).filter(models.Prompt.name.like("extract_content_v%")).all()


# --- WebSocket for running tests ---
@app.websocket("/ws/run-test")
async def websocket_run_test(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("[SYSTEM] WebSocket connection established. Ready to run test.")
    
    try:
        config_str = await websocket.receive_text()
        config = json.loads(config_str)
        await websocket.send_text(f"[SYSTEM] Received test configuration: {config}")

        preprocessor_script = os.path.join(project_root, "preprocessor", "main.py")
        command = [sys.executable, preprocessor_script]

        if config.get('input_dir'):
            command.extend(["--input-dir", config['input_dir']])
        
        db = SessionLocal()
        try:
            if config.get('provider_id'):
                provider_obj = db.query(models.APIProvider).filter(models.APIProvider.id == config['provider_id']).first()
                if provider_obj:
                    command.extend(["--provider", provider_obj.name])
                    decrypted_key = decrypt_api_key(provider_obj.encrypted_api_key)
                    command.extend(["--api-key", decrypted_key])
            if config.get('model_id'):
                model_obj = db.query(models.LLMModel).filter(models.LLMModel.id == config['model_id']).first()
                if model_obj:
                    command.extend(["--model", model_obj.name])

            prompt = db.query(models.Prompt).filter(models.Prompt.id == config.get('prompt_id')).first()
            if prompt:
                prompt_version = prompt.name.split('_')[-1]
                command.extend(["--prompt-version", prompt_version])
        finally:
            db.close()

        if config.get('test_mode') == 'mock':
            command.extend(["--mock-case", "default_case"])
            llm_steps = {1, 2, 4}
            mocked_steps = set(config.get('mock_steps', []))
            real_steps = llm_steps - mocked_steps
            if real_steps:
                command.append("--real-steps")
                command.extend([str(step) for step in sorted(list(real_steps))])

        await websocket.send_text(f"[SYSTEM] Executing command: {' '.join(command)}")

        sub_env = os.environ.copy()
        sub_env["PYTHONIOENCODING"] = "utf-8"
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.path.join(project_root, "preprocessor"),
            env=sub_env
        )

        async def stream_output(stream, prefix):
            while True:
                line = await stream.readline()
                if not line:
                    break
                await websocket.send_text(f"[{prefix}] {line.decode('utf-8').strip()}")
        
        await asyncio.gather(
            stream_output(process.stdout, "STDOUT"),
            stream_output(process.stderr, "STDERR")
        )
        
        await process.wait()
        await websocket.send_text(f"[SYSTEM] Process finished with exit code {process.returncode}")

    except Exception as e:
        await websocket.send_text(f"[SYSTEM-ERROR] An error occurred: {e}")
    finally:
        await websocket.close()

# --- Mount Static files (the frontend) as the LAST step ---
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
