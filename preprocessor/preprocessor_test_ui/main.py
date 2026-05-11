import sys
import os
import json
import asyncio
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, WebSocket
from fastapi.routing import APIRouter as FastAPIRouter
from sqlalchemy.orm import Session, joinedload
from fastapi.staticfiles import StaticFiles
from starlette.routing import Router as StarletteRouter

# --- Add project root to sys.path ---
current_dir = os.path.abspath(os.path.dirname(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
sys.path.insert(0, current_dir)
sys.path.insert(0, project_root)
# -------------------------------------

if not getattr(StarletteRouter.__init__, "_codebuddy_compat", False):
    _original_starlette_router_init = StarletteRouter.__init__

    def _starlette_router_init_compat(self, *args, **kwargs):
        kwargs.pop("on_startup", None)
        kwargs.pop("on_shutdown", None)
        kwargs.pop("lifespan", None)
        kwargs.pop("middleware", None)
        return _original_starlette_router_init(self, *args, **kwargs)

    _starlette_router_init_compat._codebuddy_compat = True
    StarletteRouter.__init__ = _starlette_router_init_compat

if not hasattr(FastAPIRouter, "add_event_handler"):
    def _router_add_event_handler(self, event_type, func):
        if event_type == "startup":
            if not hasattr(self, "on_startup"):
                self.on_startup = []
            self.on_startup.append(func)
        elif event_type == "shutdown":
            if not hasattr(self, "on_shutdown"):
                self.on_shutdown = []
            self.on_shutdown.append(func)

    FastAPIRouter.add_event_handler = _router_add_event_handler

from shared import models
from shared.database import SessionLocal as MainSessionLocal
from analyzer.app.security import decrypt_api_key
from analyzer.app.config import (
    NORMALIZED_DOCUMENTS_DIR,
    QUESTION_BANK_ASSET_DIR,
    QUESTION_BANK_UPLOAD_DIR,
)
from db_runtime import (
    SessionLocal,
    engine,
    get_database_mode_label,
    get_database_runtime_state,
)
from shared.llm_step_config import list_llm_step_configs, sync_llm_step_configs, update_llm_step_config
from shared.prompt_step_config import list_registered_prompts, sync_prompt_step_configs
from analyzer.app.knowledge_point_api import register_knowledge_point_routes

# 导入提示词管理 API
from prompt_editor_api import router as prompts_router
from model_management_api import router as model_management_router
from content_ingestion_admin_api import router as content_ingestion_router
from knowledge_point_admin_api import router as knowledge_point_admin_router
from case_run_inspect_api import router as case_run_inspect_router

for _router in (prompts_router, model_management_router, content_ingestion_router, knowledge_point_admin_router):
    if not hasattr(_router, "on_startup"):
        _router.on_startup = []
    if not hasattr(_router, "on_shutdown"):
        _router.on_shutdown = []
    if not hasattr(_router, "lifespan_context"):
        _router.lifespan_context = None

app = FastAPI()
if not hasattr(app.router, "on_startup"):
    app.router.on_startup = []
if not hasattr(app.router, "on_shutdown"):
    app.router.on_shutdown = []
if not hasattr(app.router, "lifespan_context"):
    app.router.lifespan_context = None

db_runtime_state = get_database_runtime_state()

for directory in [QUESTION_BANK_UPLOAD_DIR, QUESTION_BANK_ASSET_DIR, NORMALIZED_DOCUMENTS_DIR]:
    Path(directory).mkdir(parents=True, exist_ok=True)

app.mount("/static/question-bank/uploads", StaticFiles(directory=QUESTION_BANK_UPLOAD_DIR), name="question-bank-uploads")
app.mount("/static/question-bank/assets", StaticFiles(directory=QUESTION_BANK_ASSET_DIR), name="question-bank-assets")
app.mount("/static/question-bank/normalized", StaticFiles(directory=NORMALIZED_DOCUMENTS_DIR), name="question-bank-normalized")

TEST_UI_PIPELINE_STEPS = [
    {"id": 0, "key": "0", "name": "preprocess_images", "label": "预处理", "description": "压缩并规范化输入图片", "output_file": "00_preprocess_output.json"},
    {"id": 1, "key": "1", "name": "perspective_correction", "label": "透视矫正", "description": "透视纠正并输出矫正图", "output_file": "01_correction_output.json"},
    {"id": 2, "key": "2", "name": "classify", "label": "分类", "description": "页面类型分类", "output_file": "02_classify_output.json"},
    {"id": 3, "key": "3", "name": "analyze_layout", "label": "版面分析", "description": "分析题目区与答题区布局", "output_file": "03_layout_output.json"},
    {"id": 4, "key": "4", "name": "extract_content", "label": "内容提取", "description": "提取题目内容与结构化结果", "output_file": "04_content_output.json"},
    {"id": 4.5, "key": "4.5", "name": "extract_answers", "label": "答案提取", "description": "补充答案切片与答案信息", "output_file": "04_content_output.json"},
    {"id": 5, "key": "5", "name": "merge_results", "label": "结果合并", "description": "合并题目、答案与版面结果", "output_file": "05_merged_output.json"},
    {"id": 6, "key": "6", "name": "answer_card_recognition", "label": "涂卡识别", "description": "识别选择题涂卡区并生成完整单元", "output_file": "complete_units.json"},
    {"id": 7, "key": "7", "name": "generate_complete_units", "label": "生成完整单元", "description": "生成完整单元图片输出", "output_file": "07_complete_units"},
    {"id": 8, "key": "8", "name": "draw_output", "label": "输出画框", "description": "生成最终标注图片", "output_file": "08_annotated_images"},
    {"id": 9, "key": "9", "name": "export_analysis_bundle", "label": "导出分析包", "description": "导出 analyzer bundle", "output_file": "manifest.json"},
]


def _get_available_step_keys(case_path: str) -> list[str]:
    available = []
    for step in TEST_UI_PIPELINE_STEPS:
        output_path = os.path.join(case_path, step["output_file"])
        if os.path.exists(output_path):
            available.append(step["key"])
    return available


# 注册提示词管理 API 路由
app.include_router(prompts_router)
app.include_router(model_management_router)
app.include_router(content_ingestion_router)
app.include_router(knowledge_point_admin_router)
app.include_router(case_run_inspect_router)
register_knowledge_point_routes(app)


@app.on_event("startup")
def log_database_runtime_mode():
    print(f"[DB] 当前测试 UI 使用：{get_database_mode_label()} -> {db_runtime_state.active_url}")

    db = SessionLocal()
    try:
        try:
            sync_llm_step_configs(db)
            print("[LLM] 步骤模型路由已同步到数据库。")
        except Exception as exc:
            db.rollback()
            print(f"[WARN] 跳过 LLM 步骤模型路由同步：{exc}")

        try:
            sync_prompt_step_configs(db)
            print("[Prompt] 步骤提示词路由已同步到数据库。")
        except Exception as exc:
            db.rollback()
            print(f"[WARN] 跳过 Prompt 步骤提示词路由同步：{exc}")
    finally:
        db.close()

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


@app.get("/api/llm-step-configs")
def get_llm_step_configs(db: Session = Depends(get_db)):
    return list_llm_step_configs(db)


@app.put("/api/llm-step-configs/{step_key}")
def put_llm_step_config(step_key: str, payload: dict, db: Session = Depends(get_db)):
    provider_id = payload.get('provider_id')
    model_id = payload.get('model_id')
    is_active = payload.get('is_active', True)

    if provider_id is None or model_id is None:
        raise HTTPException(status_code=400, detail='provider_id 和 model_id 不能为空')

    try:
        return update_llm_step_config(
            db,
            step_key,
            provider_id=int(provider_id),
            model_id=int(model_id),
            is_active=bool(is_active),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@app.get("/api/prompts")
def get_prompts(db: Session = Depends(get_db)):
    return list_registered_prompts(db)

@app.get("/api/pipeline-steps")
def get_pipeline_steps():
    return TEST_UI_PIPELINE_STEPS


@app.get("/api/mock-cases")
def get_mock_cases():
    """Get list of available mock cases from tests/mock_data/ directory"""
    mock_data_dir = os.path.join(project_root, "preprocessor", "tests", "mock_data")
    if not os.path.exists(mock_data_dir):
        return []

    from datetime import datetime

    cases = []
    for case_name in os.listdir(mock_data_dir):
        case_path = os.path.join(mock_data_dir, case_name)
        if os.path.isdir(case_path):
            created_at = os.path.getctime(case_path)
            available_step_keys = _get_available_step_keys(case_path)
            step_files = [f for f in os.listdir(case_path) if f.endswith('.json')]

            cases.append({
                'name': case_name,
                'created_at': datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M:%S'),
                'created_at_ts': created_at,
                'steps': len(step_files),
                'available_step_keys': available_step_keys,
                'available_step_count': len(available_step_keys)
            })

    cases.sort(key=lambda x: x['created_at_ts'], reverse=True)
    for case in cases:
        case.pop('created_at_ts', None)
    return cases


# --- WebSocket for running tests ---
@app.websocket("/ws/run-test")
async def websocket_run_test(websocket: WebSocket):
    await websocket.accept()
    
    # 收集所有日志
    all_logs = []
    
    try:
        await websocket.send_text("[SYSTEM] WebSocket connection established. Ready to run test.")
        
        config_str = await websocket.receive_text()
        config = json.loads(config_str)
        config_log = f"[SYSTEM] Received test configuration: {config}"
        await websocket.send_text(config_log)
        all_logs.append(config_log)

        preprocessor_script = os.path.join(project_root, "preprocessor", "main.py")
        command = [sys.executable, preprocessor_script]

        if config.get('input_dir'):
            command.extend(["--input-dir", config['input_dir']])
        
        db = MainSessionLocal()
        try:
            if config.get('use_model_override'):
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

            # 现在 config.prompt_id 是版本号（如 "v7"），而不是具体的 prompt ID
            # 直接使用版本号，main.py 会根据页面类型自动选择合适的提示词
            if config.get('prompt_version'):
                # 确保版本号是字符串格式
                version = config['prompt_version']
                if isinstance(version, int):
                    version = str(version)
                elif isinstance(version, str) and not version.startswith('v'):
                    # 如果是 "8" 格式，保持不变（main.py 会处理）
                    pass
                command.extend(["--prompt-version", version])
            
            # 添加 A3 处理策略参数
            if config.get('a3_strategy'):
                command.extend(["--a3-strategy", config['a3_strategy']])

            # 添加分类方法参数
            if config.get('classification_method'):
                command.extend(["--classification-method", config['classification_method']])
        finally:
            db.close()

        # 确定日志保存的 case 名称
        log_case_name = "unknown"
        
        if config.get('test_mode') == 'record':
            # Record mode: run all steps with real API, save to tests/mock_data/
            case_name = config.get('case_name', f'case_{int(asyncio.get_event_loop().time())}')
            command.extend(["--record-case", case_name])
            log_case_name = case_name
            
        elif config.get('test_mode') == 'mock':
            # Mock mode: load from tests/mock_data/, output to temp/
            mock_case = config.get('mock_case')
            if mock_case:
                command.extend(["--mock-case", mock_case])
                log_case_name = mock_case
            else:
                # Fallback to latest case if not specified
                mock_data_dir = os.path.join(project_root, "preprocessor", "tests", "mock_data")
                if os.path.exists(mock_data_dir):
                    case_dirs = [d for d in os.listdir(mock_data_dir) if os.path.isdir(os.path.join(mock_data_dir, d))]
                    if case_dirs:
                        case_dirs.sort(reverse=True)
                        command.extend(["--mock-case", case_dirs[0]])
                        log_case_name = case_dirs[0]
            
            requested_real_steps = config.get('real_steps')
            if requested_real_steps is None:
                llm_steps = {1, 2, 4}
                mocked_steps = set(config.get('mock_steps', []))
                requested_real_steps = sorted(llm_steps - mocked_steps)

            if requested_real_steps:
                command.append("--real-steps")
                command.extend([str(step) for step in requested_real_steps])
                mode_log = f"[SYSTEM] Mock 模式下真实执行步骤: {requested_real_steps}"
                await websocket.send_text(mode_log)
                all_logs.append(mode_log)
        else:
            log_case_name = f"run_{int(asyncio.get_event_loop().time())}"

        exec_log = f"[SYSTEM] Executing command: {' '.join(command)}"
        await websocket.send_text(exec_log)
        all_logs.append(exec_log)

        sub_env = os.environ.copy()
        sub_env["PYTHONIOENCODING"] = "utf-8"
        sub_env["PYTHONUNBUFFERED"] = "1"  # 禁用输出缓冲，确保实时日志输出
        sub_env["DATABASE_URL"] = db_runtime_state.active_url
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
                decoded_line = line.decode('utf-8').strip()
                log_line = f"[{prefix}] {decoded_line}"
                await websocket.send_text(log_line)
                all_logs.append(log_line)
        
        await asyncio.gather(
            stream_output(process.stdout, "STDOUT"),
            stream_output(process.stderr, "STDERR")
        )
        
        await process.wait()
        final_log = f"[SYSTEM] Process finished with exit code {process.returncode}"
        await websocket.send_text(final_log)
        all_logs.append(final_log)
        
        # 保存日志到文件（仅 record 模式）
        if config.get('test_mode') == 'record':
            log_dir = os.path.join(project_root, "preprocessor", "tests", "mock_data", log_case_name)
            os.makedirs(log_dir, exist_ok=True)
            log_file_path = os.path.join(log_dir, "test_run_log.txt")
            
            with open(log_file_path, 'w', encoding='utf-8') as f:
                f.write("="*80 + "\n")
                f.write("测试运行日志\n")
                f.write("="*80 + "\n\n")
                for log_line in all_logs:
                    f.write(log_line + "\n")
            
            save_log = f"[SYSTEM] 日志已保存到：{log_file_path}"
            await websocket.send_text(save_log)

    except Exception as e:
        error_log = f"[SYSTEM-ERROR] An error occurred: {e}"
        await websocket.send_text(error_log)
        all_logs.append(error_log)
    finally:
        await websocket.close()


# 整页画框测试 WebSocket 端点
@app.websocket("/ws/run-whole-page")
async def run_whole_page_test(websocket: WebSocket):
    """整页画框测试：多张图片拼接 → 识别 → 裁剪"""
    await websocket.accept()
    
    all_logs = []
    
    try:
        await websocket.send_text("[SYSTEM] 整页画框测试初始化...")
        
        config = await websocket.receive_json()
        await websocket.send_text(f"[SYSTEM] 收到测试配置：{config}")
        all_logs.append(f"[SYSTEM] 收到测试配置：{config}")
        
        # 构建命令
        project_root = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        python_exe = sys.executable
        main_script = os.path.join(project_root, "preprocessor", "whole_page_detection.py")
        
        command = [
            python_exe,
            main_script,
            "--input-dir", config.get('input_dir'),
        ]

        if config.get('prompt_version'):
            command.extend(["--prompt-version", str(config['prompt_version'])])
        
        # 添加图片拼接参数
        if config.get('stitching_method'):
            command.extend(["--stitch-method", config['stitching_method']])
        if config.get('overlap_pixels', 0) > 0:
            command.extend(["--overlap", str(config['overlap_pixels'])])
        
        # 添加识别参数
        if config.get('detect_questions'):
            command.append("--detect-questions")
        if config.get('detect_answers'):
            command.append("--detect-answers")
        if config.get('output_format'):
            command.extend(["--output-format", config['output_format']])
        
        # 添加图片列表
        if config.get('image_files'):
            command.extend(["--images"] + config['image_files'])

        if config.get('use_model_override'):
            db = MainSessionLocal()
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
            finally:
                db.close()
        
        # 测试模式
        if config.get('test_mode') == 'record':
            case_name = config.get('case_name', f'whole_page_{int(asyncio.get_event_loop().time())}')
            command.extend(["--record-case", case_name])
            log_case_name = case_name
        else:
            log_case_name = f"whole_page_{int(asyncio.get_event_loop().time())}"
        
        exec_log = f"[SYSTEM] 执行命令：{' '.join(command)}"
        await websocket.send_text(exec_log)
        all_logs.append(exec_log)
        
        # 启动子进程
        sub_env = os.environ.copy()
        sub_env["PYTHONIOENCODING"] = "utf-8"
        sub_env["PYTHONUNBUFFERED"] = "1"
        sub_env["DATABASE_URL"] = db_runtime_state.active_url
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
                decoded_line = line.decode('utf-8').strip()
                log_line = f"[{prefix}] {decoded_line}"
                await websocket.send_text(log_line)
                all_logs.append(log_line)
        
        await asyncio.gather(
            stream_output(process.stdout, "STDOUT"),
            stream_output(process.stderr, "STDERR")
        )
        
        await process.wait()
        final_log = f"[SYSTEM] 进程结束，退出码：{process.returncode}"
        await websocket.send_text(final_log)
        all_logs.append(final_log)
        
        # 保存日志
        if config.get('test_mode') == 'record':
            log_dir = os.path.join(project_root, "preprocessor", "tests", "mock_data", log_case_name)
            os.makedirs(log_dir, exist_ok=True)
            log_file_path = os.path.join(log_dir, "whole_page_test_log.txt")
            
            with open(log_file_path, 'w', encoding='utf-8') as f:
                f.write("="*80 + "\n")
                f.write("整页画框测试日志\n")
                f.write("="*80 + "\n\n")
                for log_line in all_logs:
                    f.write(log_line + "\n")
            
            save_log = f"[SYSTEM] 日志已保存到：{log_file_path}"
            await websocket.send_text(save_log)
    
    except Exception as e:
        error_log = f"[SYSTEM-ERROR] 发生错误：{e}"
        await websocket.send_text(error_log)
        all_logs.append(error_log)
    finally:
        await websocket.close()

# --- Mount Static files (the frontend) as the LAST step ---
# 尝试挂载前端静态文件，如果不存在则跳过（开发模式）
import os
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

# 添加禁用缓存的中间件
@app.middleware("http")
async def disable_cache(request, call_next):
    response = await call_next(request)
    path = request.url.path

    # 前端静态资源与 HTML 统一禁用缓存，避免发布后仍引用旧 hash 资源导致白屏
    if request.method == "GET" and (path.startswith("/assets/") or path == "/" or path.endswith(".html")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

frontend_dist_path = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if os.path.exists(frontend_dist_path):
    # 添加 SPA 路由支持 - 处理 /prompt-editor、/whole-page、/model-routing 等前端路由
    @app.get("/prompt-editor")
    async def serve_spa():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))
    
    @app.get("/whole-page")
    async def serve_whole_page():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/content-sources")
    async def serve_content_sources():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/content-ingestion")
    async def serve_content_ingestion():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/content-management")
    async def serve_content_management():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/knowledge-points")
    async def serve_knowledge_points():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/knowledge-retrieval")
    async def serve_knowledge_retrieval():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/question-bank-management")
    async def serve_question_bank_management():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/model-routing")
    async def serve_model_routing():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/model-management")
    async def serve_model_management():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/prompt-routing")
    async def serve_prompt_routing():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/paper-preview")
    async def serve_paper_preview():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))

    @app.get("/case-run-inspect")
    async def serve_case_run_inspect():
        return FileResponse(os.path.join(frontend_dist_path, "index.html"))
    
    app.mount("/", StaticFiles(directory=frontend_dist_path, html=True), name="static")
    print(f"[OK] Mounted static files from {frontend_dist_path}")
else:
    print(f"[WARN] Static files not found at {frontend_dist_path}")
    print(f"  Running in API-only mode. Use frontend dev server for UI.")
    print("[DEBUG] Frontend dist not found, skipping static file mounting.")

# --- Start the server ---
if __name__ == "__main__":
    import uvicorn
    print("\n" + "="*80)
    print("提示词管理工具 - 已集成到测试页面！")
    print("="*80)
    print("\n访问地址：http://localhost:8001")
    print("点击顶部工具栏的'提示词管理'按钮即可使用")
    print("\n按 Ctrl+C 停止服务\n")
    uvicorn.run(app, host="0.0.0.0", port=8001)
