import argparse
import json
import os
import sys
import base64
from copy import deepcopy
import numpy as np
from PIL import Image


# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils import call_api, extract_json, crop_with_padding, save_crop_with_quality, analyze_page_ocr, refine_region_and_crop, save_box_debug_visualizations

from src.utils.config_loader import get_crop_refinement_config
from src.tasks.postprocess_answer_sheet import normalize_answer_sheet_output
from shared.prompt_step_config import get_seed_prompt_text



def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def run_content_extraction(
    layout_input_path: str, 
    output_path: str, 
    prompts_dict: dict, 
    workspace_dir: str, 
    a3_strategy: str = 'split',  # 新增参数
    api_key: str = None, 
    model_name: str = None, 
    api_url: str = None, 
    image_path_manager=None,
    logger=None,
    crop_refinement_config: dict = None
):
    """
    Extracts content from all page parts defined in the layout analysis output.

    Args:
        layout_input_path (str): Path to the JSON file from the layout analysis step.
        output_path (str): The path to save the output content JSON file.
        prompts_dict (dict): Dictionary of prompts for different page types from DB
                            {'exam_paper': str, 'answer_sheet': str, 'mixed': str}
        workspace_dir (str): The directory for the current run, to save the used prompts.
        a3_strategy (str): 'split' | 'whole'
            - split: 分割成左右两部分（方案 A）
            - whole: 整体识别，不分割（方案 B）
        api_key: API 密钥
        model_name: 模型名称
        api_url: API URL
        image_path_manager: ImagePathManager 实例，用于获取压缩后的图片路径
    """
    with open(layout_input_path, 'r', encoding='utf-8') as f:
        parts_to_process = json.load(f)

    print(f"  Starting content extraction for {len(parts_to_process)} parts...")
    all_extracted_content = []

    # prompts_dict 是从数据库获取的提示词字典
    prompt_set = prompts_dict if prompts_dict else None
    resolved_crop_refinement_config = get_crop_refinement_config({
        'crop_refinement': crop_refinement_config or {}
    })


    for part_info in parts_to_process:
        page_type = part_info['page_type']
        part_image_path = part_info['image_path']
        part_basename = os.path.basename(part_image_path)
        part_type = part_info.get('part_type', 'full')
        
        # 映射 page_type 到提示词字典的键
        # 支持中文和英文两种类型（分类步骤现在返回英文，但保留中文兼容性）
        prompt_key_map = {
            # 英文类型（分类步骤返回）
            'question_paper': 'exam_paper',
            'answer_sheet': 'answer_sheet',
            'mixed': 'mixed',
            # 中文类型（兼容性保留）
            '题目纸': 'exam_paper',
            '答题纸': 'answer_sheet',
            '题目和答题混合纸': 'mixed'
        }
        prompt_key = prompt_key_map.get(page_type, page_type)
        
        # 使用压缩后的图片进行内容提取
        if image_path_manager:
            actual_part_image_path = image_path_manager.get_image_path(part_image_path, use_original=False)
        else:
            actual_part_image_path = part_image_path
        
        print(f"    Processing part: {os.path.basename(actual_part_image_path)} (Type: {page_type}, Prompt Key: {prompt_key})")

        # 1. Select the appropriate prompt based on page type
        seed_prompt_key_map = {
            'exam_paper': 'preprocessor.extract_content.exam_paper',
            'answer_sheet': 'preprocessor.extract_content.answer_sheet',
            'mixed': 'preprocessor.extract_content.mixed',
        }
        if prompt_set:
            prompt = prompt_set.get(prompt_key)
            if not prompt:
                print(f"    [Warning] No prompt found for page_type '{page_type}', using mixed prompt")
                prompt = prompt_set.get('mixed')
        else:
            print(f"    [Warning] No prompt dict provided for content extraction, fallback to catalog seed prompt")
            prompt = None

        if not prompt:
            fallback_prompt_key = seed_prompt_key_map.get(prompt_key, 'preprocessor.extract_content.mixed')
            prompt = get_seed_prompt_text(fallback_prompt_key, variables={'side': part_type}) or ''

        
        # 2. 替换模板占位符
        if prompt and '{side}' in prompt:
            prompt = prompt.replace('{side}', part_type)
        if prompt and '[[side]]' in prompt:
            prompt = prompt.replace('[[side]]', part_type)


        # 3. Save the used prompt to the workspace for traceability
        prompt_save_path = os.path.join(workspace_dir, f"prompt_used_for_{part_basename}.txt")
        with open(prompt_save_path, 'w', encoding='utf-8') as f_prompt:
            f_prompt.write(prompt)
        print(f"      Saved prompt to: {prompt_save_path}")

        # 4. Call the VLM API and extract JSON
        # 重试逻辑
        max_retries = 3
        attempt = 0
        api_response = None
        extracted_data = None
        
        while attempt < max_retries:
            attempt += 1
            
            if attempt == 1:
                print(f"      [尝试] 第 1 次调用内容提取 {part_basename}（共{max_retries}次机会）")
            else:
                print(f"      [重试] 第 {attempt} 次重试内容提取 {part_basename}（共{max_retries}次机会）")
            
            try:
                api_response = call_api(
                    prompt=prompt, 
                    image_path=actual_part_image_path,
                    api_url=api_url,
                    api_key=api_key,
                    model_name=model_name,
                    logger=logger,
                    step_name=f"content_extraction_{page_type}",
                    min_content_length=20
                )
            except Exception as api_error:
                if attempt < max_retries:
                    print(f"      [警告] 第 {attempt} 次调用失败：{api_error}，准备重试...")
                    api_response = None
                    continue  # 继续重试
                else:
                    print(f"      [错误] 已达最大重试次数 ({max_retries})，内容提取失败：{api_error}")
                    extracted_data = {"questions": [], "error": str(api_error)}
                    break  # 所有重试都失败，退出循环
            
            # 处理 API 响应
            if not api_response or api_response.strip() == '':
                print(f"      [ERROR] API returned empty response for {part_basename}")
                if attempt < max_retries:
                    extracted_data = None
                    continue  # 继续重试
                else:
                    extracted_data = {"questions": [], "error": "API returned empty response"}
                    break  # 所有重试都失败，退出循环
            
            json_string = extract_json(api_response)
            
            # 检查提取的 JSON 是否为空
            if not json_string or json_string.strip() == '':
                print(f"      [ERROR] Failed to extract JSON from API response for {part_basename}")
                print(f"      [DEBUG] Raw API response (first 500 chars): {api_response[:500]}")
                if attempt < max_retries:
                    extracted_data = None
                    continue  # 继续重试
                else:
                    extracted_data = {"questions": [], "error": "Failed to extract JSON from response"}
                    break  # 所有重试都失败，退出循环
            
            try:
                extracted_data = json.loads(json_string)
            except json.JSONDecodeError as je:
                print(f"      [ERROR] Invalid JSON format for {part_basename}: {je}")
                print(f"      [DEBUG] JSON string: {json_string[:500]}")
                if attempt < max_retries:
                    extracted_data = None
                    continue  # 继续重试
                else:
                    extracted_data = {"questions": [], "error": f"Invalid JSON: {str(je)}"}
                    break  # 所有重试都失败，退出循环
            
            # 标准化大模型返回的格式
            if isinstance(extracted_data, list):
                standardized_questions = []
                for item in extracted_data:
                    if 'bbox_2d' in item:
                        x_min, y_min, x_max, y_max = item['bbox_2d']
                        standardized_item = {
                            "number": str(item.get('question_id', item.get('number', 'unknown'))),
                            "points": {
                                "top_left": [x_min, y_min],
                                "top_right": [x_max, y_min],
                                "bottom_right": [x_max, y_max],
                                "bottom_left": [x_min, y_max]
                            },
                            "description": item.get('question_text', item.get('description', ''))
                        }
                        standardized_questions.append(standardized_item)
                    else:
                        standardized_questions.append(item)
                extracted_data = {"questions": standardized_questions}
            elif isinstance(extracted_data, dict) and 'questions' not in extracted_data:
                extracted_data = {"questions": [extracted_data]}
            
            # 如果成功获取到有效数据，退出循环
            if extracted_data and 'questions' in extracted_data:
                print(f"      [成功] 内容提取成功，获取到 {len(extracted_data['questions'])} 个题目")
                break  # 成功，退出循环
            else:
                print(f"      [警告] 提取的数据格式不正确")
                if attempt < max_retries:
                    extracted_data = None
                    continue  # 继续重试
                else:
                    extracted_data = {"questions": [], "error": "Invalid data format"}
                    break  # 所有重试都失败，退出循环

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
            # 添加张的信息（用于跨张关联）
            "sheet_id": part_info.get('sheet_id', 'unknown'),
            "sheet_type": part_info.get('sheet_type', 'unknown'),
            "order": part_info.get('order', 9999),
            "vlm_output": extracted_data
        }
        
        # 6. 后处理：规范化答题纸输出
        sheet_type = part_info.get('sheet_type', 'unknown')
        if sheet_type in ['answer_sheet', '答题纸'] and extracted_data:
            extracted_data = normalize_answer_sheet_output(extracted_data, sheet_type)
            content_result["vlm_output"] = extracted_data  # 更新后处理后的数据
        
        # 7. 物理切片题目区域（带精修保护）- 只对题目纸和混合纸切片，不对答题纸切片
        page_type = part_info.get('page_type', '')
        if page_type in ['question_paper', 'mixed', '题目纸', '题目和答题混合纸'] and extracted_data.get('questions'):
            sheet_id = part_info.get('sheet_id', 'unknown')
            source_corrected_image = part_info.get('source_corrected_image')
            crop_area = part_info.get('crop_area')
            
            if source_corrected_image and os.path.exists(source_corrected_image):
                corrected_image = Image.open(source_corrected_image)
                corrected_image = np.array(corrected_image)

                page_ocr_result = None
                page_ocr_config = resolved_crop_refinement_config.get('page_ocr', {})
                if page_ocr_config.get('enabled', True):
                    page_ocr_result = analyze_page_ocr(
                        source_corrected_image,
                        workspace_dir=workspace_dir,
                        config=page_ocr_config,
                        logger=logger
                    )
                content_result['page_ocr_backend'] = page_ocr_result.get('backend', 'disabled') if page_ocr_result else 'disabled'
                
                question_slices_dir = os.path.join(workspace_dir, 'question_slices', sheet_id)
                os.makedirs(question_slices_dir, exist_ok=True)
                
                sliced_count = 0
                used_numbers = set()
                box_debug_items = []
                for question in extracted_data['questions']:

                    if question.get('number') == '涂卡区':
                        continue
                    
                    try:
                        points = question.get('points')
                        if not points:
                            continue

                        original_points = deepcopy(points)
                        try:
                            refine_result = refine_region_and_crop(
                                image=corrected_image,
                                points=points,
                                crop_area=crop_area,
                                question_number=question.get('number'),
                                mode='question',
                                page_ocr_result=page_ocr_result,
                                config=resolved_crop_refinement_config,
                                peer_points_list=[
                                    candidate.get('points')
                                    for candidate in extracted_data['questions']
                                    if candidate is not question and candidate.get('number') != '涂卡区' and candidate.get('points')
                                ]
                            )

                            crop = refine_result['crop']
                        except Exception as refine_error:
                            print(f"      [WARNING] Refine failed for question {question.get('number')}: {refine_error}")
                            crop = crop_with_padding(corrected_image, points)
                            refine_result = {
                                'points': original_points,
                                'refine_flags': ['fallback_crop_with_padding'],
                                'crop_debug': {
                                    'mode': 'question',
                                    'refined': False,
                                    'reason': str(refine_error),
                                    'crop_area': crop_area
                                }
                            }
                        
                        original_number = str(question.get('number', 'unknown'))
                        q_num = original_number
                        suffix = 1
                        while q_num in used_numbers:
                            if '续' in q_num:
                                q_num = f"{original_number}-{suffix}"
                            else:
                                q_num = f"{original_number}-{suffix}"
                            suffix += 1
                        used_numbers.add(q_num)
                        
                        q_num_formatted = q_num.zfill(3)
                        crop_output_path = os.path.join(question_slices_dir, f'Q{q_num_formatted}.jpg')
                        save_crop_with_quality(crop, crop_output_path)

                        if resolved_crop_refinement_config.get('preserve_original_points', True):
                            question['original_points'] = original_points
                        question['points'] = refine_result['points']
                        question['question_slice_path'] = crop_output_path
                        question['source_image_for_crop'] = source_corrected_image
                        if resolved_crop_refinement_config.get('record_debug', True):
                            question['crop_debug'] = refine_result.get('crop_debug', {})
                            question['refine_flags'] = refine_result.get('refine_flags', [])
                        if q_num != original_number:
                            question['original_number'] = original_number
                        box_debug_items.append({
                            'number': question.get('number'),
                            'original_points': original_points,
                            'refined_points': refine_result.get('points', original_points)
                        })
                        sliced_count += 1
                        
                    except Exception as e:
                        print(f"      [WARNING] Failed to crop question {question.get('number')}: {e}")
                
                box_debug_config = resolved_crop_refinement_config.get('box_debug_visualization', {})
                if box_debug_config.get('enabled', True) and box_debug_items:
                    save_box_debug_visualizations(
                        image_path=source_corrected_image,
                        crop_area=crop_area,
                        regions=box_debug_items,
                        output_dir=os.path.join(workspace_dir, 'box_debug', 'questions'),
                        filename_prefix=f"{sheet_id}_{os.path.splitext(os.path.basename(source_corrected_image))[0]}"
                    )
                print(f"      成功切片 {sliced_count} 个题目区域")

            else:
                print(f"      [WARNING] Source corrected image not found: {source_corrected_image}")

        
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
