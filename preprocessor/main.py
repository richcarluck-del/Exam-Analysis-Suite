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
from shared.llm_step_config import resolve_step_llm_config
from shared.prompt_step_config import resolve_step_prompt, sync_prompt_step_configs

from src.enhanced_logger import EnhancedLogger


from src.tasks.task_preprocess_images import run_image_preprocessing
from src.tasks.task_classify_page import run_classification
from src.tasks.task_long_image_classification import run_long_image_classification
from src.tasks.task_perspective_correction import run_perspective_correction
from src.tasks.task_analyze_layout import run_layout_analysis
from src.tasks.task_extract_content import run_content_extraction
from src.tasks.task_extract_answers import run_answer_extraction
from src.tasks.task_merge_results import run_merge_results
from src.tasks.task_draw_output import run_draw_output
from src.tasks.task_answer_card_pipeline import run_answer_card_pipeline
from src.tasks.task_generate_complete_units import run_generate_complete_units
from src.tasks.task_export_analysis_bundle import run_export_analysis_bundle
from src.utils.config_loader import load_config, get_classification_method


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class ImagePathManager:
    """
    统一管理图片路径，确保所有步骤使用压缩后的图片
    """
    
    def __init__(self, compression_map: list = None):
        """
        初始化路径管理器
        
        Args:
            compression_map: 压缩映射列表，格式为：
                [{'original': 'path/to/original.jpg', 'compressed': 'path/to/compressed.jpg'}, ...]
        """
        self.compression_map = {}
        if compression_map:
            self.compression_map = {
                item['original']: item['compressed']
                for item in compression_map
            }
    
    def get_image_path(self, original_path: str, use_original: bool = False) -> str:
        """
        获取实际应该使用的图片路径
        
        Args:
            original_path: 原始图片路径
            use_original: 是否强制使用原始图片（用于最终输出等需要高清图片的场景）
            
        Returns:
            实际应该使用的图片路径
        """
        if use_original:
            return original_path
        
        # 查找压缩后的路径，如果没有找到则返回原始路径
        return self.compression_map.get(original_path, original_path)
    
    def get_all_compressed_paths(self) -> list:
        """
        获取所有压缩后的图片路径
        
        Returns:
            压缩后的图片路径列表
        """
        return list(self.compression_map.values())
    
    def load_compression_map(self, json_path: str):
        """
        从 JSON 文件加载压缩映射
        
        Args:
            json_path: 压缩映射 JSON 文件路径
        """
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            compression_map = data.get('compression_map', [])
            self.compression_map = {
                item['original']: item['compressed']
                for item in compression_map
            }
        print(f"  Loaded {len(self.compression_map)} image paths from compression map")


PIPELINE_STEPS = [
    {'step': 0, 'name': 'preprocess_images', 'func': run_image_preprocessing, 'output_file': '00_preprocess_output.json', 'needs_llm_config': False},
    {'step': 1, 'name': 'perspective_correction', 'func': run_perspective_correction, 'output_file': '01_correction_output.json', 'needs_llm_config': True},
    {'step': 2, 'name': 'classify', 'func': run_classification, 'output_file': '02_classify_output.json', 'needs_llm_config': True},
    {'step': 3, 'name': 'analyze_layout', 'func': run_layout_analysis, 'output_file': '03_layout_output.json', 'needs_llm_config': False},

    {'step': 4, 'name': 'extract_content', 'func': run_content_extraction, 'output_file': '04_content_output.json', 'needs_llm_config': True},
    {'step': 4.5, 'name': 'extract_answers', 'func': run_answer_extraction, 'output_file': '04_content_output.json', 'needs_llm_config': False},
    {'step': 5, 'name': 'merge_results', 'func': run_merge_results, 'output_file': '05_merged_output.json', 'needs_llm_config': False},
    {'step': 6, 'name': 'answer_card_recognition', 'func': run_answer_card_pipeline, 'output_file': 'complete_units.json', 'needs_answer_card_config': True},
    {'step': 7, 'name': 'generate_complete_units', 'func': run_generate_complete_units, 'output_file': '07_complete_units', 'needs_llm_config': False},
    {'step': 8, 'name': 'draw_output', 'func': run_draw_output, 'output_file': '08_annotated_images', 'needs_llm_config': False},
    {'step': 9, 'name': 'export_analysis_bundle', 'func': run_export_analysis_bundle, 'output_file': 'manifest.json', 'needs_llm_config': False}
]

STEP_ARTIFACT_DIRS = {
    0: ['compressed_images'],
    1: ['corrected_images'],
    2: ['stitched_images'],
    3: [],
    4: ['question_slices'],
    4.5: ['answer_slices'],
    5: [],
    6: ['answer_card_areas', 'complete_unit_images'],
    7: ['07_complete_units'],
    8: ['08_annotated_images'],
    9: []
}



def main():
    parser = argparse.ArgumentParser(description="Exam Analysis RAG Pipeline")
    
    # Mode selection
    parser.add_argument('--input-dir', type=str, help='Directory containing input images for a real run.')
    parser.add_argument('--test-case', type=str, help='Name of the test case to run (uses real images from tests/test_cases).')

    # Step control
    parser.add_argument('--start-step', type=int, default=0, help='The step number to start from (0-based, 0=image preprocessing).')
    parser.add_argument('--end-step', type=int, default=len(PIPELINE_STEPS), help='The step number to end at (inclusive).')

    # Recording
    parser.add_argument('--record-case', type=str, help='If specified, saves all intermediate results to a new mock case with this name.')

    # Mocking / Hybrid execution
    parser.add_argument('--mock-case', type=str, help='Name of the mock data case to use for a hybrid run.')
    parser.add_argument('--mock-source', type=str, help='Direct path to a directory containing mock data (e.g., from a previous temp run).')
    parser.add_argument('--real-steps', nargs='+', type=float, help='A list of step numbers to run with real API calls; others use mock data. Supports decimal steps like 4.5')
    parser.add_argument('--prompt-version', type=str, help='可选：全局提示词版本覆盖（调试用）。未传时默认按每个步骤绑定的最高版本执行。')


    parser.add_argument(
        '--a3-strategy',
        type=str,
        choices=['split', 'whole', 'both'],
        default='whole',
        help='A3 试卷处理策略：split=分割成 A4(方案 A), whole=整体识别 (方案 B), both=并行对比'
    )
    
    # 分类方式配置
    parser.add_argument(
        '--classification-method',
        type=str,
        choices=['single_page', 'long_image'],
        default='long_image',
        help='页面分类方式：single_page=单页分类, long_image=长图分类（默认）'
    )

    # LLM Configuration
    parser.add_argument('--provider', type=str, help='主流程模型供应商全局覆盖（未传时优先使用数据库步骤配置）。')
    parser.add_argument('--model', type=str, help='主流程模型全局覆盖（未传时优先使用数据库步骤配置）。')
    parser.add_argument('--api-key', type=str, help='可选的 API Key 覆盖；未传则从数据库解密读取。')
    
    # 涂卡识别专用模型配置
    parser.add_argument('--answer-card-provider', type=str, help='涂卡识别模型供应商覆盖（未传时优先使用数据库步骤配置）。')
    parser.add_argument('--answer-card-model', type=str, help='涂卡识别模型覆盖（未传时优先使用数据库步骤配置）。')


    # Manual workspace override
    parser.add_argument('--output-dir', type=str, help='Explicitly specify the output directory for all artifacts.')
    parser.add_argument('--workspace', type=str, help='DEPRECATED: Explicitly specify the workspace directory to use, overriding automatic creation.')

    # Business context for exported bundle
    parser.add_argument('--student-id', type=str, help='Optional student identifier for bundle export.')
    parser.add_argument('--exam-id', type=str, help='Optional exam identifier for bundle export.')
    parser.add_argument('--paper-id', type=str, help='Optional paper identifier for bundle export.')
    parser.add_argument('--subject', type=str, help='Optional subject for bundle export.')
    parser.add_argument('--grade', type=str, help='Optional grade for bundle export.')
    parser.add_argument('--class-id', type=str, help='Optional class identifier for bundle export.')
    parser.add_argument('--organization-id', type=str, help='Optional organization identifier for bundle export.')


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

    # 初始化工作目录
    os.makedirs(workspace_dir, exist_ok=True)
    # 新增：长图存储目录
    os.makedirs(os.path.join(workspace_dir, 'stitched_images'), exist_ok=True)
    
    # 初始化增强日志记录器
    logger = EnhancedLogger(workspace_dir)
    print(f"\n✅ 增强日志已初始化，工作目录：{workspace_dir}\n")

    if args.input_dir:
        input_dir = os.path.abspath(args.input_dir)
        print(f"\n--- Running in REAL mode on directory: {input_dir} ---")
    elif args.test_case:
        input_dir = os.path.join(BASE_DIR, 'tests', 'test_cases', args.test_case)
        print(f"\n--- Running in TEST mode on case: {args.test_case} ---")
    elif args.mock_case:
        input_dir = os.path.join(BASE_DIR, 'tests', 'mock_data', args.mock_case)
        print(f"\n--- Running in MOCK/HYBRID mode with case: {args.mock_case} ---")
    elif args.mock_source:
        input_dir = os.path.abspath(args.mock_source)
        print(f"\n--- Running in MOCK/HYBRID mode with source: {input_dir} ---")

    if not input_dir:
        parser.error("Could not determine input directory. Please specify --input-dir, --test-case, --mock-case, or --mock-source.")

    if not os.path.isdir(input_dir):
        parser.error(f"Input directory not found: {input_dir}")

    source_mode = 'real' if args.input_dir else 'test' if args.test_case else 'mock'
    exam_context = {
        'exam_id': args.exam_id,
        'paper_id': args.paper_id,
        'student_id': args.student_id,
        'subject': args.subject,
        'grade': args.grade,
        'class_id': args.class_id,
        'organization_id': args.organization_id,
        'source_mode': source_mode
    }

    print(f"Workspace for this run: {workspace_dir}\n")


    # --- Resolve step-level LLM routing and prompt routing ---
    llm_step_configs = {}
    answer_card_llm_config = {}
    prompt_step_configs = {}
    prompt_version_override = args.prompt_version
    db = SessionLocal()
    try:
        sync_prompt_step_configs(db)

        main_provider_override = args.provider or 'dashscope'
        main_model_override = args.model or 'qwen3.5-plus'
        answer_card_provider_override = args.answer_card_provider or 'volcengine'
        answer_card_model_override = args.answer_card_model or 'doubao-seed-2-0-pro-260215'

        llm_step_configs['perspective_correction'] = resolve_step_llm_config(
            db,
            'preprocessor.perspective_correction',
            api_key_override=args.api_key,
            fallback_provider_name=main_provider_override,
            fallback_model_name=main_model_override,
        )
        llm_step_configs['classify'] = resolve_step_llm_config(
            db,
            'preprocessor.classify',
            api_key_override=args.api_key,
            fallback_provider_name=main_provider_override,
            fallback_model_name=main_model_override,
        )
        llm_step_configs['extract_content'] = resolve_step_llm_config(
            db,
            'preprocessor.extract_content',
            api_key_override=args.api_key,
            fallback_provider_name=main_provider_override,
            fallback_model_name=main_model_override,
        )
        answer_card_llm_config = resolve_step_llm_config(
            db,
            'preprocessor.answer_card_recognition',
            fallback_provider_name=answer_card_provider_override,
            fallback_model_name=answer_card_model_override,
        )

        for step_name in ['perspective_correction', 'classify', 'extract_content']:
            if not llm_step_configs.get(step_name):
                raise ValueError(f"未找到步骤 `{step_name}` 的模型配置。")
        if not answer_card_llm_config:
            raise ValueError("未找到步骤 `answer_card_recognition` 的模型配置。")

        prompt_step_configs['perspective_correction'] = resolve_step_prompt(
            db,
            'preprocessor.perspective_correction',
            version_override=prompt_version_override,
        )
        prompt_step_configs['page_classification'] = resolve_step_prompt(
            db,
            'preprocessor.classify',
            version_override=prompt_version_override,
        )
        prompt_step_configs['long_image_classification'] = resolve_step_prompt(
            db,
            'preprocessor.long_image_classification',
            version_override=prompt_version_override,
        )
        prompt_step_configs['extract_content_exam_paper'] = resolve_step_prompt(
            db,
            'preprocessor.extract_content.exam_paper',
            version_override=prompt_version_override,
        )
        prompt_step_configs['extract_content_answer_sheet'] = resolve_step_prompt(
            db,
            'preprocessor.extract_content.answer_sheet',
            version_override=prompt_version_override,
        )
        prompt_step_configs['extract_content_mixed'] = resolve_step_prompt(
            db,
            'preprocessor.extract_content.mixed',
            version_override=prompt_version_override,
        )
        prompt_step_configs['answer_card_recognition'] = resolve_step_prompt(
            db,
            'preprocessor.answer_card_recognition',
            version_override=prompt_version_override,
        )

        missing_prompt_steps = [
            step_name
            for step_name in [
                'perspective_correction',
                'page_classification',
                'long_image_classification',
                'extract_content_exam_paper',
                'extract_content_answer_sheet',
                'extract_content_mixed',
                'answer_card_recognition',
            ]
            if not prompt_step_configs.get(step_name)
        ]
        if missing_prompt_steps:
            raise ValueError(f"未找到步骤提示词配置：{', '.join(missing_prompt_steps)}")

        prompts_dict = {
            'perspective_correction': prompt_step_configs['perspective_correction']['prompt_text'],
            'page_classification': prompt_step_configs['page_classification']['prompt_text'],
            'long_image_classification': prompt_step_configs['long_image_classification']['prompt_text'],
            'content_extraction': {
                'exam_paper': prompt_step_configs['extract_content_exam_paper']['prompt_text'],
                'answer_sheet': prompt_step_configs['extract_content_answer_sheet']['prompt_text'],
                'mixed': prompt_step_configs['extract_content_mixed']['prompt_text'],
            },
            'answer_card_recognition': prompt_step_configs['answer_card_recognition']['prompt_text'],
        }

        print("\n已解析步骤模型路由：")
        for step_name, step_label in [
            ('perspective_correction', '透视矫正'),
            ('classify', '页面分类'),
            ('extract_content', '内容提取'),
        ]:
            config = llm_step_configs[step_name]
            print(
                f"  -> {step_label}：{config.get('provider_name')}/{config.get('model_name')} "
                f"(来源: {config.get('config_source')})"
            )
        print(
            f"  -> 涂卡识别：{answer_card_llm_config.get('provider_name')}/"
            f"{answer_card_llm_config.get('model_name')} "
            f"(来源: {answer_card_llm_config.get('config_source')})"
        )

        print("\n已解析步骤提示词路由：")
        for prompt_key, step_label in [
            ('perspective_correction', '透视矫正'),
            ('page_classification', '页面分类（单页）'),
            ('long_image_classification', '页面分类（长图）'),
            ('extract_content_exam_paper', '内容提取（试卷）'),
            ('extract_content_answer_sheet', '内容提取（答题纸）'),
            ('extract_content_mixed', '内容提取（混合页）'),
            ('answer_card_recognition', '涂卡识别'),
        ]:
            config = prompt_step_configs[prompt_key]
            print(
                f"  -> {step_label}：{config.get('prompt_key')} / v{config.get('resolved_version')} "
                f"(来源: {config.get('version_source')})"
            )

        if args.api_key:
            print("  -> 主流程步骤使用命令行传入的 API Key 覆盖数据库密钥")
        if args.prompt_version:
            print(f"  -> 当前使用全局提示词版本覆盖：{args.prompt_version}")

    except Exception as e:
        print(f"[Error] Failed to configure step routing from database: {e}")
        sys.exit(1)
    finally:
        db.close()


    # --- 加载配置文件 ---
    config = load_config()
    
    # 命令行参数优先于配置文件
    if args.classification_method:
        classification_method = args.classification_method
    else:
        classification_method = get_classification_method(config)
    
    # 打印配置信息
    print(f"\n页面分类方式：{classification_method}")
    if classification_method == "long_image":
        print("  - 使用拼接长图 + 大模型识别")
        print("  - 优势：利用全局上下文，准确率高")
        print("  - 耗时：约 50-200 秒（1 次 API 调用）")
    else:
        print("  - 使用单页独立分类")
        print("  - 优势：实现简单，不依赖拼接")
    
    # 显示配置来源
    if args.classification_method:
        print("  - 配置来源：命令行参数")
    else:
        print("  - 配置来源：配置文件")
    
    # --- Execute pipeline steps ---
    current_input = None # This will hold the output path of the previous step
    image_path_manager = ImagePathManager()  # Initialize image path manager

    # Determine the source for mock data if needed
    mock_source_dir = None
    if args.test_case:
        # Full mock run based on a test case
        mock_source_dir = os.path.join('tests', 'mock_data', args.test_case)
    elif args.mock_case:
        # Hybrid run using a specified mock case
        mock_source_dir = os.path.join('tests', 'mock_data', args.mock_case)
    elif args.mock_source:
        # Direct path to mock data (e.g., from a previous temp run)
        mock_source_dir = args.mock_source
        print(f"Using mock data from: {mock_source_dir}")

    # 🔧 修复：在开始执行前，复制需要的所有前置数据（包括 JSON 和图片）
    if mock_source_dir and os.path.exists(mock_source_dir):
        print(f"\n准备从录制数据路径复制前置数据...")
        print(f"  录制数据路径：{mock_source_dir}")
        print(f"  开始步骤：{args.start_step}")
        
        import shutil
        
        # 复制开始步骤之前的所有输出文件和数据目录
        for step_info in PIPELINE_STEPS:
            step_number = step_info['step']
            step_output_file = step_info['output_file']
            
            # 只复制开始步骤之前的文件
            if step_number < args.start_step:
                mock_file_path = os.path.join(mock_source_dir, step_output_file)
                target_file_path = os.path.join(workspace_dir, step_output_file)
                
                if os.path.exists(mock_file_path):
                    # 确保目标目录存在
                    os.makedirs(os.path.dirname(target_file_path), exist_ok=True)
                    
                    # 复制文件或目录
                    if os.path.isdir(mock_file_path):
                        if os.path.exists(target_file_path):
                            shutil.rmtree(target_file_path)
                        shutil.copytree(mock_file_path, target_file_path)
                        print(f"  ✓ 已复制目录：{step_output_file}")
                    else:
                        shutil.copy2(mock_file_path, target_file_path)
                        print(f"  ✓ 已复制：{step_output_file}")
                else:
                    print(f"  ⚠ 未找到：{step_output_file}（录制数据中不存在）")
        
        # 🔧 修复：根据步骤定义，只复制 start_step 之前的产出物
        print(f"\n复制前置产出物...")
        
        # 定义步骤到目录的映射（根据步骤定义和产出物分析）
        step_to_dirs = {
            0: ['compressed_images'],
            1: ['corrected_images'],
            2: ['stitched_images'],
            3: [],
            4: ['question_slices'],
            4.5: ['answer_slices'],
            5: [],
            6: ['answer_card_areas', 'complete_unit_images'],
            7: ['07_complete_units'],
            8: ['08_annotated_images'],
            9: []
        }

        
        # 确定需要复制的目录（所有步骤 < start_step 的目录）
        dirs_to_copy = set()
        for step_num, dirs in step_to_dirs.items():
            if step_num < args.start_step:
                dirs_to_copy.update(dirs)
        
        # 添加额外必需的目录（基于JSON文件内容引用）
        # 这些目录在JSON文件中被引用，需要确保存在
        required_base_dirs = ['compressed_images', 'corrected_images', 'stitched_images']
        
        # 复制目录
        for image_dir in sorted(dirs_to_copy):
            mock_dir_path = os.path.join(mock_source_dir, image_dir)
            target_dir_path = os.path.join(workspace_dir, image_dir)
            
            if os.path.exists(mock_dir_path) and os.path.isdir(mock_dir_path):
                if os.path.exists(target_dir_path):
                    shutil.rmtree(target_dir_path)
                shutil.copytree(mock_dir_path, target_dir_path)
                print(f"  ✓ 已复制目录：{image_dir}/")
            else:
                # 如果目录不存在，创建一个空目录（保持结构完整）
                if image_dir in required_base_dirs:
                    os.makedirs(target_dir_path, exist_ok=True)
                    print(f"  ⚠ 目录不存在但已创建：{image_dir}/")
                else:
                    print(f"  ⚠ 未找到目录：{image_dir}/（录制数据中不存在）")
        
        print(f"\n✅ 前置数据准备完成！\n")

    for step_index, step_info in enumerate(PIPELINE_STEPS):
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
        # Special handling for Step 1: Always get image paths from image_path_manager
        if step_number == 1 and args.input_dir:
            # 步骤 1：透视矫正 - 总是从 image_path_manager 获取图片路径
            if image_path_manager and image_path_manager.compression_map:
                step_input = image_path_manager.get_all_compressed_paths()
                print(f"  Using {len(step_input)} compressed image paths for step 1")
            else:
                # 没有压缩映射，使用原始图片路径
                image_paths = sorted([os.path.join(args.input_dir, f) for f in os.listdir(args.input_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
                if not image_paths:
                    print(f"Error: No images found in {args.input_dir}")
                    break
                step_input = image_paths
        elif current_input is None:
            # This happens if it's the first step to be run (for steps other than step 1).
            if step_number == 0:
                # Step 0: Image preprocessing - input is the image directory
                if args.input_dir:
                    step_input = args.input_dir
                else:
                    step_input = None
            elif step_name == 'draw_output':
                step_input = os.path.join(workspace_dir, '05_merged_output.json')
                if not os.path.exists(step_input):
                    print(f"Error: Required merged results not found for step '{step_name}': {step_input}")
                    break
                print(f"  Loading draw input from merged results: {step_input}")
            elif step_name == 'export_analysis_bundle':
                step_input = workspace_dir
                print(f"  Loading bundle export input from workspace: {step_input}")
            else:
                # We are starting mid-pipeline, so we need to find the previous step's output file.
                prev_step_output_file = PIPELINE_STEPS[step_index - 1]['output_file'] if step_index > 0 else None
                if not prev_step_output_file:
                    print(f"Error: Could not determine prerequisite output for step '{step_name}'.")
                    break
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

            previous_step_number = PIPELINE_STEPS[step_index - 1]['step'] if step_index > 0 else None
            if use_mock and previous_step_number is not None:
                if args.real_steps and previous_step_number in args.real_steps:
                    print(
                        f"  ℹ️ 当前按用户配置执行：上一步（步骤 {previous_step_number}）是真实运行，"
                        f"但这一步（步骤 {step_number}）仍将复用 mock 结果。后续结果不会自动反映上一步的真实改动。"
                    )


        step_output_path = os.path.join(workspace_dir, step_output_file)

        if use_mock:

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

            for artifact_dir in STEP_ARTIFACT_DIRS.get(step_number, []):
                artifact_mock_path = os.path.join(mock_source_dir, artifact_dir)
                artifact_target_path = os.path.join(workspace_dir, artifact_dir)
                if not os.path.exists(artifact_mock_path) or artifact_dir == step_output_file:
                    continue
                if os.path.isdir(artifact_mock_path):
                    if os.path.exists(artifact_target_path):
                        shutil.rmtree(artifact_target_path)
                    shutil.copytree(artifact_mock_path, artifact_target_path)
                    print(f"  ✓ 已复制步骤附属目录：{artifact_dir}/")
                else:
                    os.makedirs(os.path.dirname(artifact_target_path), exist_ok=True)
                    shutil.copy2(artifact_mock_path, artifact_target_path)
                    print(f"  ✓ 已复制步骤附属文件：{artifact_dir}")
            
            current_input = step_output_path


        else: # Run for Real
            print(f"--- Running Step {step_number}: {step_name} ---")
            if step_input is None and step_number != 1:
                 print(f"  [Error] Cannot run step {step_number} for real without input from previous step.")
                 break
            
            step_llm_config_map = {
                'perspective_correction': llm_step_configs.get('perspective_correction'),
                'classify': llm_step_configs.get('classify'),
                'extract_content': llm_step_configs.get('extract_content'),
                'answer_card_recognition': answer_card_llm_config,
            }
            current_step_llm_config = step_llm_config_map.get(step_name)

            print(f"\n[DEBUG-TRACE] About to call step: '{step_name}'")
            print(f"[DEBUG-TRACE]   - step_input type: {type(step_input)}")
            print(
                f"[DEBUG-TRACE]   - step_llm_config keys: "
                f"{current_step_llm_config.keys() if current_step_llm_config else 'None'}"
            )
            
            # 记录步骤开始时间和使用的提示词
            step_start_time = datetime.now()

            
            step_prompt_preview_map = {
                'perspective_correction': prompts_dict.get('perspective_correction'),
                'classify': prompts_dict.get('page_classification') if classification_method != 'long_image' else prompts_dict.get('long_image_classification'),
                'extract_content': json.dumps(prompt_step_configs.get('extract_content_exam_paper', {}), ensure_ascii=False, indent=2),
                'answer_card_recognition': prompts_dict.get('answer_card_recognition'),
            }
            step_prompt_preview = step_prompt_preview_map.get(step_name)

            if step_prompt_preview:
                prompt_filename = f"prompt_used_for_step_{step_number}_{step_name}.txt"
                prompt_filepath = os.path.join(workspace_dir, prompt_filename)
                with open(prompt_filepath, 'w', encoding='utf-8') as f:
                    f.write(step_prompt_preview)
                print(f"  ✅ 步骤 {step_number} 提示词已保存：{prompt_filepath}")
                logger.save_prompt(f"step_{step_number}_{step_name}", step_prompt_preview, "N/A")


            if step_name == 'perspective_correction':
                # 步骤 1：透视矫正 - 传入压缩后的图片路径，但函数内部会使用原始图片
                current_input = step_func(
                    step_input,
                    step_output_path,
                    prompts_dict.get('perspective_correction'),
                    api_key=current_step_llm_config.get('api_key'),
                    model_name=current_step_llm_config.get('model_name'),
                    api_url=current_step_llm_config.get('api_url'),
                    image_path_manager=image_path_manager,
                    logger=logger
                )
            elif step_name == 'classify':
                # 步骤 2：页面分类 - 根据配置选择分类方式
                print(f"  [DEBUG] 步骤 2 调用分类器，logger={logger}")
                if classification_method == "long_image":
                    current_input = run_long_image_classification(
                        workspace_dir,
                        image_path_manager=image_path_manager,
                        prompt=prompts_dict.get('long_image_classification'),
                        api_key=current_step_llm_config.get('api_key'),
                        model_name=current_step_llm_config.get('model_name'),
                        api_url=current_step_llm_config.get('api_url'),
                        logger=logger
                    )

                else:
                    current_input = step_func(
                        step_input,
                        step_output_path,
                        prompts_dict.get('page_classification'),
                        api_key=current_step_llm_config.get('api_key'),
                        model_name=current_step_llm_config.get('model_name'),
                        api_url=current_step_llm_config.get('api_url'),
                        image_path_manager=image_path_manager,
                        logger=logger
                    )
            elif step_name == 'analyze_layout':
                current_input = step_func(
                    step_input,
                    step_output_path,
                    a3_strategy=args.a3_strategy,
                    api_key=current_step_llm_config.get('api_key') if current_step_llm_config else None,
                    model_name=current_step_llm_config.get('model_name') if current_step_llm_config else None,
                    api_url=current_step_llm_config.get('api_url') if current_step_llm_config else None,
                    image_path_manager=image_path_manager
                )
            elif step_name == 'extract_content':
                print(f"  [DEBUG] 步骤 4 调用 extract_content，logger={logger}")
                current_input = step_func(
                    step_input,
                    step_output_path,
                    prompts_dict.get('content_extraction'),
                    workspace_dir,
                    a3_strategy=args.a3_strategy,
                    api_key=current_step_llm_config.get('api_key'),
                    model_name=current_step_llm_config.get('model_name'),
                    api_url=current_step_llm_config.get('api_url'),
                    image_path_manager=image_path_manager,
                    logger=logger,
                    crop_refinement_config=config.get('crop_refinement')
                )

            elif step_name == 'extract_answers':
                print(f"  [DEBUG] 步骤 4.5 调用 extract_answers")
                current_input = step_func(
                    content_output_path=step_input,
                    output_path=step_output_path,
                    workspace_dir=workspace_dir,
                    crop_refinement_config=config.get('crop_refinement'),
                    logger=logger
                )
            elif step_name == 'answer_card_recognition':
                print(f"  [DEBUG] 步骤 {step_number} 调用涂卡识别，使用专用模型")
                step_func(
                    content_output_path=os.path.join(workspace_dir, '04_content_output.json'),
                    merged_results_path=os.path.join(workspace_dir, '05_merged_output.json'),
                    workspace_dir=workspace_dir,
                    llm_config=current_step_llm_config or answer_card_llm_config,
                    prompt_override=prompts_dict.get('answer_card_recognition')
                )


                current_input = step_output_path
            elif step_name == 'generate_complete_units':
                print(f"  [DEBUG] 步骤 {step_number} 生成完整单元图片")
                step_func(
                    complete_units_path=os.path.join(workspace_dir, 'complete_units.json'),
                    content_output_path=os.path.join(workspace_dir, '04_content_output.json'),
                    workspace_dir=workspace_dir,
                    image_path_manager=image_path_manager
                )
                current_input = step_output_path
            elif step_name == 'draw_output':
                print(f"  [DEBUG] 步骤 {step_number} 画框标注")
                step_func(
                    merged_results_path=os.path.join(workspace_dir, '05_merged_output.json'),
                    output_dir=step_output_path,
                    image_path_manager=image_path_manager
                )
                current_input = step_output_path
            elif step_name == 'export_analysis_bundle':
                print(f"  [DEBUG] 步骤 {step_number} 导出 analyzer bundle")
                step_func(
                    workspace_dir=workspace_dir,
                    output_path=step_output_path,
                    exam_context=exam_context,
                    producer={
                        'prompt_version_override': args.prompt_version,
                        'classification_method': classification_method,
                        'llm_provider': llm_step_configs['extract_content'].get('provider_name'),
                        'llm_model': llm_step_configs['extract_content'].get('model_name'),
                        'answer_card_provider': answer_card_llm_config.get('provider_name'),
                        'answer_card_model': answer_card_llm_config.get('model_name'),
                        'step_llm_configs': {
                            step_name: {
                                'provider': step_config.get('provider_name'),
                                'model': step_config.get('model_name'),
                                'source': step_config.get('config_source')
                            }
                            for step_name, step_config in {
                                'perspective_correction': llm_step_configs.get('perspective_correction'),
                                'classify': llm_step_configs.get('classify'),
                                'extract_content': llm_step_configs.get('extract_content'),
                                'answer_card_recognition': answer_card_llm_config,
                            }.items()
                            if step_config
                        },
                        'step_prompt_configs': {
                            step_name: {
                                'prompt_key': step_config.get('prompt_key'),
                                'version': step_config.get('resolved_version'),
                                'source': step_config.get('version_source')
                            }
                            for step_name, step_config in {
                                'perspective_correction': prompt_step_configs.get('perspective_correction'),
                                'page_classification': prompt_step_configs.get('page_classification'),
                                'long_image_classification': prompt_step_configs.get('long_image_classification'),
                                'extract_content_exam_paper': prompt_step_configs.get('extract_content_exam_paper'),
                                'extract_content_answer_sheet': prompt_step_configs.get('extract_content_answer_sheet'),
                                'extract_content_mixed': prompt_step_configs.get('extract_content_mixed'),
                                'answer_card_recognition': prompt_step_configs.get('answer_card_recognition'),
                            }.items()
                            if step_config
                        }
                    }


                )
                current_input = step_output_path
            else:
                current_input = step_func(step_input, step_output_path)

            
            # 记录步骤完成日志
            step_end_time = datetime.now()
            step_duration = (step_end_time - step_start_time).total_seconds()
            print(f"  ✅ 步骤 {step_number} 完成，耗时：{step_duration:.2f}秒")
            
            # 记录步骤使用的图片信息
            if step_number == 1:  # 透视矫正步骤
                # 记录压缩图片和矫正图片的信息
                if hasattr(image_path_manager, 'compression_map'):
                    for img_name, img_path in list(image_path_manager.compression_map.items())[:3]:  # 只记录前 3 个
                        if os.path.exists(img_path):
                            logger.log_image_info(img_path, {"type": "compressed", "image_name": img_name})
                            
                # 记录矫正后的图片
                corrected_dir = os.path.join(workspace_dir, 'corrected_images')
                if os.path.exists(corrected_dir):
                    for img_name in os.listdir(corrected_dir)[:3]:  # 只记录前 3 个
                        img_path = os.path.join(corrected_dir, img_name)
                        if os.path.exists(img_path):
                            logger.log_image_info(img_path, {"type": "corrected", "image_name": img_name})
            
            # After step 0 (preprocessing), load the compression map
            if step_number == 0 and os.path.exists(step_output_path):
                image_path_manager.load_compression_map(step_output_path)
                print(f"  Image compression completed. Using compressed images for subsequent steps.")

    # 保存所有日志
    logger.save_all_logs()
    print("\n✅ 所有日志已保存！\n")

    print("--- Pipeline finished. ---")

if __name__ == "__main__":
    main()
