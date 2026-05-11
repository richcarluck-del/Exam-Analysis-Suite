"""
涂卡区识别与切片任务

功能：
1. 从内容提取结果中识别涂卡区切片
2. 物理切片涂卡区并保存到单独目录
3. 生成涂卡区识别结果 JSON
4. 支持从数据库读取 VLM 配置
"""

import json
import os
import cv2
import re
from typing import List, Dict, Optional


PERSONAL_INFO_KEYWORDS = [
    '准考证', '准考号', '考号', '考生号', '证号', '学号', '座位号', '报名号',
    '姓名', '班级', '学校', '条形码', '二维码', '个人信息', '信息填写',
    'admission', 'examid', 'exam id', 'student id', 'barcode', 'id number'
]

CHOICE_AREA_KEYWORDS = [
    '选择题', '客观题', '选项', '填涂卡', '答题卡', 'i卷', '第i卷',
    'objective', 'choice', 'multiple choice', 'single choice'
]


def _normalize_text(value: object) -> str:
    return str(value or '').strip().lower()


def _contains_personal_info_keyword(*values: object) -> bool:
    combined_text = ' '.join(_normalize_text(value) for value in values)
    return any(keyword in combined_text for keyword in PERSONAL_INFO_KEYWORDS)


def _parse_question_range(value: object) -> Optional[tuple[int, int]]:
    match = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', str(value or ''))
    if not match:
        return None

    start = int(match.group(1))
    end = int(match.group(2))
    if start > end:
        start, end = end, start
    return start, end


def _is_objective_range(value: object) -> bool:
    question_range = _parse_question_range(value)
    if not question_range:
        return False

    start, end = question_range
    return start <= 5 and end > 5 and (end - start) >= 4


def _has_range_in_description(description: object) -> bool:
    return bool(re.search(r'第?\s*\d+\s*-\s*\d+\s*题', str(description or ''), re.IGNORECASE))



def _has_choice_area_keyword(description: object) -> bool:
    description_text = str(description or '')
    return any(keyword in description_text.lower() for keyword in CHOICE_AREA_KEYWORDS)



def _calculate_fragment_area(fragment: dict) -> int:
    points = fragment.get('points') or {}
    try:
        xs = [points[key][0] for key in ['top_left', 'top_right', 'bottom_right', 'bottom_left']]
        ys = [points[key][1] for key in ['top_left', 'top_right', 'bottom_right', 'bottom_left']]
    except (KeyError, TypeError, IndexError):
        return 0

    return max(0, max(xs) - min(xs)) * max(0, max(ys) - min(ys))



def _score_answer_card_fragment(fragment: dict) -> int:
    number = fragment.get('number', '')
    description = fragment.get('description', '')
    question_type = _normalize_text(fragment.get('type', ''))

    if _contains_personal_info_keyword(number, description):
        return -100

    score = 0
    if question_type == 'objective_choice':
        score += 4
    if _is_objective_range(number):
        score += 4
    if _has_range_in_description(description):
        score += 3
    if _has_choice_area_keyword(description):
        score += 3

    return score



def _normalize_card_number(number: object) -> str:
    number_str = str(number or 'unknown').strip().replace('/', '_')
    if number_str == '涂卡区':
        return 'answer_card_area'

    question_range = _parse_question_range(number_str)
    if question_range:
        start, end = question_range
        return f'{start}-{end}'

    return number_str



def is_answer_card_area(fragment: dict) -> bool:
    """
    判断是否是选择题涂卡区。

    关键原则：
    - 必须位于答题纸上
    - 必须是“选择题/客观题”相关区域
    - 必须排除准考证号、考号等个人信息填涂区
    """
    number = fragment.get('number', '')
    description = fragment.get('description', '')
    question_type = _normalize_text(fragment.get('type', ''))

    sheet_type = fragment.get('sheet_type', '')
    is_answer_sheet = sheet_type in ['answer_sheet', '答题纸']
    if not is_answer_sheet:
        return False

    if _contains_personal_info_keyword(number, description):
        return False

    has_objective_range = _is_objective_range(number)
    has_range_in_description = _has_range_in_description(description)
    has_choice_keyword = _has_choice_area_keyword(description)
    is_objective_choice = question_type == 'objective_choice'
    is_named_answer_card = _normalize_text(number) in ['涂卡区', 'answer_card_area']

    return (
        (has_objective_range or has_range_in_description or is_named_answer_card)
        and (has_choice_keyword or is_objective_choice)
    )


def crop_answer_card_area(fragment: dict, workspace_dir: str) -> str:
    """
    切片涂卡区并保存
    
    Args:
        fragment: 切片数据
        workspace_dir: 工作目录
        
    Returns:
        切片图片路径
    """
    # 1. 获取原图路径和坐标
    image_path = fragment['source_corrected_image']
    points = fragment['points']
    
    # 2. 加载图片
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"无法加载图片：{image_path}")
    
    h, w = image.shape[:2]
    
    # 3. 将归一化坐标转换为像素坐标
    x_min = int(min(points['top_left'][0], points['bottom_left'][0]) / 1000 * w)
    y_min = int(min(points['top_left'][1], points['top_right'][1]) / 1000 * h)
    x_max = int(max(points['top_right'][0], points['bottom_right'][0]) / 1000 * w)
    y_max = int(max(points['bottom_left'][1], points['bottom_right'][1]) / 1000 * h)
    
    # 4. 切片
    crop_image = image[y_min:y_max, x_min:x_max]
    
    # 5. 保存 - 使用稳定的标准化文件名，避免中文编码和重复范围格式问题
    number = _normalize_card_number(fragment.get('number', 'unknown'))

    output_dir = os.path.join(workspace_dir, 'answer_card_areas')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'answer_card_{number}.jpg')
    cv2.imwrite(output_path, crop_image)
    
    print(f"  涂卡区切片已保存：{output_path}")
    
    return output_path


def extract_answer_cards(
    content_output_path: str,
    workspace_dir: str,
    use_vlm: bool = True,
    vlm_api_url: Optional[str] = None,
    vlm_api_key: Optional[str] = None,
    vlm_model_name: Optional[str] = None,
    llm_config: Optional[dict] = None,  # 专用涂卡识别模型配置
    prompt_override: Optional[str] = None,
) -> Dict:
    """
    提取所有涂卡区并切片，使用 VLM 识别答案
    
    配置优先级：
    1. llm_config 参数（最高优先级）
    2. 传入的 vlm_* 参数
    3. 从数据库读取的配置
    
    Args:
        content_output_path: 内容提取结果 JSON 路径
        workspace_dir: 工作目录
        use_vlm: 是否使用 VLM 识别答案
        vlm_api_url: VLM API URL（可选，默认从数据库读取）
        vlm_api_key: VLM API Key（可选，默认从数据库读取）
        vlm_model_name: VLM 模型名称（可选，默认从数据库读取）
        llm_config: 专用涂卡识别模型配置（可选）
        
    Returns:
        涂卡区识别结果字典（包含答案）
    """
    print("  开始提取涂卡区...")
    
    # 使用专用的涂卡识别模型配置（如果有）
    if llm_config:
        print(f"  使用专用涂卡识别模型配置：{llm_config.get('model_name')}")
        vlm_api_url = llm_config.get('api_url')
        vlm_api_key = llm_config.get('api_key')
        vlm_model_name = llm_config.get('model_name')
    
    # 1. 读取内容提取结果
    with open(content_output_path, 'r', encoding='utf-8') as f:
        content_results = json.load(f)
    
    # 2. 遍历所有切片，识别涂卡区
    answer_card_fragments = []
    
    for part_result in content_results:
        # 获取 part 级别的 sheet_type
        part_sheet_type = part_result.get('sheet_type', '')
        part_sheet_id = part_result.get('sheet_id', '')
        
        vlm_output = part_result.get('vlm_output', {})
        questions = vlm_output.get('questions', [])
        
        for question in questions:
            # 临时添加 sheet_type 用于判断
            question_with_type = {**question}
            question_with_type['sheet_type'] = part_sheet_type
            question_with_type['sheet_id'] = part_sheet_id
            
            if is_answer_card_area(question_with_type):
                # 复制并添加额外信息
                fragment = {**question}
                fragment.update({
                    'source_corrected_image': part_result.get('source_corrected_image'),
                    'sheet_id': part_sheet_id,
                    'sheet_type': part_sheet_type,
                    'order': part_result.get('order'),
                })
                answer_card_fragments.append(fragment)
    
    deduplicated_fragments = {}
    for fragment in answer_card_fragments:
        number = _normalize_card_number(fragment.get('number', 'unknown'))
        candidate_score = _score_answer_card_fragment(fragment)
        candidate_area = _calculate_fragment_area(fragment)
        existing_fragment = deduplicated_fragments.get(number)

        if existing_fragment is None:
            deduplicated_fragments[number] = fragment
            continue

        existing_score = _score_answer_card_fragment(existing_fragment)
        existing_area = _calculate_fragment_area(existing_fragment)
        should_replace = (candidate_score, candidate_area) > (existing_score, existing_area)

        if should_replace:
            print(
                f"  [去重] 涂卡区 {number} 检测到重复候选，"
                f"保留分数更高/面积更大的区域：{fragment.get('description', '')}"
            )
            deduplicated_fragments[number] = fragment
        else:
            print(
                f"  [去重] 涂卡区 {number} 跳过较弱候选：{fragment.get('description', '')}"
            )

    answer_card_fragments = list(deduplicated_fragments.values())
    print(f"  识别到 {len(answer_card_fragments)} 个有效涂卡区")

    # 3. 物理切片并识别答案
    answer_card_results = {}

    for fragment in answer_card_fragments:
        number = _normalize_card_number(fragment.get('number', 'unknown'))

        try:
            # 切片
            crop_path = crop_answer_card_area(fragment, workspace_dir)

            # 使用 VLM 识别答案
            answers = {}
            if use_vlm:
                print(f"  使用 VLM 识别涂卡区 {number}...")
                from src.answer_card.vlm_recognizer import recognize_answer_card_with_vlm
                answers = recognize_answer_card_with_vlm(
                    crop_image_path=crop_path,
                    api_url=vlm_api_url,
                    api_key=vlm_api_key,
                    model_name=vlm_model_name,
                    prompt_override=prompt_override,
                )
                print(f"  涂卡区 {number}: 识别到 {len(answers)} 个答案")

            # 保存结果
            answer_card_results[number] = {
                'crop_path': crop_path,
                'bbox': fragment.get('points'),
                'description': fragment.get('description'),
                'sheet_id': fragment.get('sheet_id'),
                'sheet_type': fragment.get('sheet_type'),
                'answers': answers,
            }

        except Exception as e:
            print(f"  [ERROR] 处理涂卡区 {number} 失败：{e}")
    
    # 4. 保存涂卡区识别结果
    output_path = os.path.join(workspace_dir, 'answer_card_results.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(answer_card_results, f, indent=2, ensure_ascii=False)
    
    print(f"  涂卡区识别结果已保存至：{output_path}")
    
    return answer_card_results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='提取涂卡区并切片')
    parser.add_argument('--content-output-path', required=True, help='内容提取结果 JSON 路径')
    parser.add_argument('--workspace-dir', required=True, help='工作目录')
    parser.add_argument('--no-vlm', action='store_true', help='不使用 VLM 识别')
    parser.add_argument('--vlm-api-url', help='VLM API URL（可选，默认从数据库读取）')
    parser.add_argument('--vlm-api-key', help='VLM API Key（可选，默认从数据库读取）')
    parser.add_argument('--vlm-model-name', help='VLM 模型名称（可选，默认从数据库读取）')
    args = parser.parse_args()
    
    extract_answer_cards(
        content_output_path=args.content_output_path,
        workspace_dir=args.workspace_dir,
        use_vlm=not args.no_vlm,
        vlm_api_url=args.vlm_api_url,
        vlm_api_key=args.vlm_api_key,
        vlm_model_name=args.vlm_model_name
    )
