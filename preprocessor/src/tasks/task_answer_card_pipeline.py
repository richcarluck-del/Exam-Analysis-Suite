"""
答题卡识别完整流程

功能：
1. 提取涂卡区并切片
2. 使用 VLM 识别答案
3. 关联答案与题目
4. 生成完整单元

形成【完整单元】：题目 + 学生答案
"""

import json
import os
import cv2
import numpy as np
from typing import Dict, List, Optional
from PIL import Image, ImageDraw, ImageFont


def run_answer_card_pipeline(
    content_output_path: str,
    merged_results_path: str,
    workspace_dir: str,
    vlm_api_url: Optional[str] = None,
    vlm_api_key: Optional[str] = None,
    vlm_model_name: Optional[str] = None,
    llm_config: Optional[dict] = None,  # 专用涂卡识别模型配置
    prompt_override: Optional[str] = None,
) -> Dict:
    """
    运行答题卡识别完整流程
    
    Args:
        content_output_path: 内容提取结果 JSON 路径 (04_content_output.json)
        merged_results_path: 合并结果 JSON 路径 (05_merged_output.json)
        workspace_dir: 工作目录
        vlm_api_url: VLM API URL（可选，默认从数据库读取或使用 llm_config）
        vlm_api_key: VLM API Key（可选，默认从数据库读取或使用 llm_config）
        vlm_model_name: VLM 模型名称（可选，默认从数据库读取或使用 llm_config）
        llm_config: 专用涂卡识别模型配置（可选，优先级最高）
        
    Returns:
        完整单元字典：{题号：完整单元信息}
    """
    print("=" * 60)
    print("答题卡识别完整流程")
    print("=" * 60)
    
    # 使用专用的涂卡识别模型配置（如果有）
    if llm_config:
        print(f"\n使用专用涂卡识别模型配置:")
        print(f"  供应商：volcengine")
        print(f"  模型：{llm_config.get('model_name')}")
        print(f"  API URL: {llm_config.get('api_url')}")
        vlm_api_url = llm_config.get('api_url')
        vlm_api_key = llm_config.get('api_key')
        vlm_model_name = llm_config.get('model_name')
        
        # 如果 API Key 已解密，直接使用
        if llm_config.get('api_key_decrypted'):
            print(f"  API Key: 已解密（明文）")
    
    # ========== 步骤 1: 提取涂卡区并识别答案 ==========
    print("\n[步骤 1] 提取涂卡区并识别答案...")
    from src.tasks.task_extract_answer_card import extract_answer_cards
    
    answer_card_results = extract_answer_cards(
        content_output_path=content_output_path,
        workspace_dir=workspace_dir,
        use_vlm=True,
        vlm_api_url=vlm_api_url,
        vlm_api_key=vlm_api_key,
        vlm_model_name=vlm_model_name,
        prompt_override=prompt_override,
    )
    
    # ========== 步骤 2: 关联答案与题目 ==========
    print("\n[步骤 2] 关联答案与题目...")
    from src.tasks.task_link_answers import link_answers_to_questions
    
    # 读取合并结果
    with open(merged_results_path, 'r', encoding='utf-8') as f:
        merged_results = json.load(f)
    
    linked_results = link_answers_to_questions(
        answer_card_results=answer_card_results,
        merged_results=merged_results
    )
    
    # ========== 步骤 3: 生成完整单元 ==========
    print("\n[步骤 3] 生成完整单元...")
    complete_units = generate_complete_units(linked_results)
    
    # ========== 步骤 4: 生成完整单元组合图片 ==========
    print("\n[步骤 4] 生成完整单元组合图片...")
    generate_complete_unit_images(linked_results, workspace_dir)
    
    # 重新生成 complete_units（包含完整单元图片路径）
    # 注意：linked_results 现在已经包含了 complete_unit_image_path
    complete_units = generate_complete_units(linked_results)
    
    # 保存完整单元
    output_path = os.path.join(workspace_dir, 'complete_units.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(complete_units, f, indent=2, ensure_ascii=False)
    
    print(f"\n完整单元已保存至：{output_path}")
    
    # 统计
    total_questions = len(complete_units)
    answered_questions = sum(1 for u in complete_units.values() if u.get('answer') not in [None, 'EMPTY'])
    
    print(f"\n统计：")
    print(f"  - 总题目数：{total_questions}")
    print(f"  - 已作答：{answered_questions}")
    print(f"  - 未作答：{total_questions - answered_questions}")
    
    return complete_units


def generate_complete_unit_images(linked_results: Dict, workspace_dir: str):
    """
    生成完整单元组合图片
    
    根据题目类型和答案来源，生成不同的组合图片：
    1. 选择题（涂卡）：题目图片 + 答案文字标注
    2. 主观题（答题区）：题目图片 + 答题区图片（上下拼接）
    3. 混合模式：直接使用题目切片（答案已在旁边）
    
    Args:
        linked_results: 关联结果
        workspace_dir: 工作目录
    """
    print("\n" + "=" * 60)
    print("生成完整单元组合图片")
    print("=" * 60)
    
    total_generated = 0
    
    for question_number, data in linked_results.items():
        question = data.get('question', {})
        answer = data.get('answer')
        answer_source = data.get('answer_source')
        answer_fragments = data.get('answer_fragments', [])
        
        question_slice_path = question.get('question_slice_path')
        answer_slice_path = data.get('answer_slice_path')
        is_mixed_mode = question.get('is_mixed_sheet', False)
        sheet_id = question.get('sheet_id', 'unknown')
        
        # 判断模式并生成对应的完整单元图片
        if is_mixed_mode:
            # 混合模式：直接使用题目切片作为完整单元图片
            unit_image_path = question_slice_path
            print(f"  题目 {question_number}: 混合模式 -> {unit_image_path}")
        elif answer_source == 'answer_card':
            # 选择题（涂卡）：题目 + 答案标注
            unit_image_path = combine_question_and_answer_card(
                question_slice_path,
                answer,
                workspace_dir,
                question_number,
                sheet_id
            )
            print(f"  题目 {question_number}: 选择题（涂卡）-> {unit_image_path}")
        elif answer_source == 'answer_area' and answer_fragments:
            # 主观题（答题区）：题目 + 答题区图片拼接
            unit_image_path = combine_question_and_answer_areas(
                question_slice_path,
                answer_fragments,
                workspace_dir,
                question_number,
                sheet_id
            )
            print(f"  题目 {question_number}: 主观题（答题区 {len(answer_fragments)} 个碎片）-> {unit_image_path}")
        else:
            # 其他情况：使用题目切片
            unit_image_path = question_slice_path
            print(f"  题目 {question_number}: 无答案 -> {unit_image_path}")
        
        # 记录完整单元图片路径
        data['complete_unit_image_path'] = unit_image_path
        question['complete_unit_image_path'] = unit_image_path
        total_generated += 1
    
    print(f"\n完整单元图片生成完成：共生成 {total_generated} 张图片")
    print("=" * 60)


def combine_question_and_answer_card(
    question_image_path: str,
    answer: str,
    workspace_dir: str,
    question_number: str,
    sheet_id: str
) -> str:
    """
    组合题目图片和答案标注（选择题）
    
    Args:
        question_image_path: 题目切片路径
        answer: 答案（如 'A', 'B', 'C', 'D'）
        workspace_dir: 工作目录
        question_number: 题号
        sheet_id: 试卷 ID
        
    Returns:
        组合后的图片路径
    """
    if not question_image_path or not os.path.exists(question_image_path):
        return question_image_path
    
    # 创建输出目录
    output_dir = os.path.join(workspace_dir, 'complete_unit_images', sheet_id)
    os.makedirs(output_dir, exist_ok=True)
    
    # 读取题目图片
    question_img = Image.open(question_image_path)
    
    # 在题目图片上添加答案标注（右上角）
    draw = ImageDraw.Draw(question_img)
    
    # 尝试加载字体（使用系统字体）
    font_size = max(20, min(question_img.width, question_img.height) // 30)
    try:
        # 尝试加载中文字体
        font = ImageFont.truetype("simhei.ttf", font_size)  # 黑体
    except:
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            font = ImageFont.load_default()
    
    # 答案标注文本
    answer_text = f"答案：{answer}" if answer else "答案：未作答"
    
    # 计算文本位置（右上角）
    bbox = draw.textbbox((0, 0), answer_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    padding = 10
    x = question_img.width - text_width - padding
    y = padding
    
    # 绘制半透明背景
    overlay = Image.new('RGBA', question_img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle(
        [x - 5, y - 5, x + text_width + 5, y + text_height + 5],
        fill=(255, 255, 255, 200)  # 白色半透明背景
    )
    question_img = Image.alpha_composite(question_img.convert('RGBA'), overlay)
    
    # 绘制答案文本
    draw = ImageDraw.Draw(question_img)
    draw.text((x, y), answer_text, fill='black', font=font)
    
    # 保存组合图片
    q_num = question_number.zfill(3)
    output_path = os.path.join(output_dir, f'CU{q_num}.jpg')
    question_img.convert('RGB').save(output_path, quality=95)
    
    return output_path


def combine_question_and_answer_areas(
    question_image_path: str,
    answer_fragments: List[Dict],
    workspace_dir: str,
    question_number: str,
    sheet_id: str
) -> str:
    """
    组合题目图片和多个答题区碎片（主观题，上下拼接）
    
    Args:
        question_image_path: 题目切片路径
        answer_fragments: 答题区碎片列表
        workspace_dir: 工作目录
        question_number: 题号
        sheet_id: 试卷 ID
        
    Returns:
        组合后的图片路径
    """
    if not question_image_path or not os.path.exists(question_image_path):
        return question_image_path
    
    if not answer_fragments:
        return question_image_path
    
    # 创建输出目录
    output_dir = os.path.join(workspace_dir, 'complete_unit_images', sheet_id)
    os.makedirs(output_dir, exist_ok=True)
    
    # 读取题目图片
    question_img = cv2.imread(question_image_path)
    if question_img is None:
        return question_image_path
    
    images_to_combine = [question_img]
    question_width = question_img.shape[1]
    
    # 读取所有答题区碎片
    for fragment in answer_fragments:
        fragment_path = fragment.get('crop_path', fragment.get('source_corrected_image', ''))
        if fragment_path and os.path.exists(fragment_path):
            answer_img = cv2.imread(fragment_path)
            if answer_img is not None:
                # 调整宽度
                answer_width = answer_img.shape[1]
                if answer_width != question_width:
                    scale = question_width / answer_width
                    new_height = int(answer_img.shape[0] * scale)
                    answer_img = cv2.resize(answer_img, (question_width, new_height))
                images_to_combine.append(answer_img)
    
    if len(images_to_combine) == 1:
        return question_image_path
    
    # 上下拼接
    combined_img = cv2.vconcat(images_to_combine)
    
    # 保存组合图片
    q_num = question_number.zfill(3)
    output_path = os.path.join(output_dir, f'CU{q_num}.jpg')
    cv2.imwrite(output_path, combined_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    return output_path


def combine_question_and_answer(
    question_image_path: str,
    answer_image_path: str,
    workspace_dir: str,
    question_number: str,
    sheet_id: str
) -> str:
    """
    组合题目图片和答案图片（非选择题，上下拼接）
    
    Args:
        question_image_path: 题目切片路径
        answer_image_path: 答案切片路径
        workspace_dir: 工作目录
        question_number: 题号
        sheet_id: 试卷 ID
        
    Returns:
        组合后的图片路径
    """
    if not question_image_path or not os.path.exists(question_image_path):
        return question_image_path
    
    if not answer_image_path or not os.path.exists(answer_image_path):
        return question_image_path
    
    # 创建输出目录
    output_dir = os.path.join(workspace_dir, 'complete_unit_images', sheet_id)
    os.makedirs(output_dir, exist_ok=True)
    
    # 读取题目和答案图片
    question_img = cv2.imread(question_image_path)
    answer_img = cv2.imread(answer_image_path)
    
    if question_img is None or answer_img is None:
        return question_image_path
    
    # 确保宽度一致（以题目图片宽度为准）
    question_width = question_img.shape[1]
    answer_width = answer_img.shape[1]
    
    if answer_width != question_width:
        # 调整答案图片宽度
        scale = question_width / answer_width
        new_height = int(answer_img.shape[0] * scale)
        answer_img = cv2.resize(answer_img, (question_width, new_height))
    
    # 上下拼接（题目在上，答案在下）
    combined_img = cv2.vconcat([question_img, answer_img])
    
    # 保存组合图片
    q_num = question_number.zfill(3)
    output_path = os.path.join(output_dir, f'CU{q_num}.jpg')
    cv2.imwrite(output_path, combined_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    return output_path


def generate_complete_units(linked_results: Dict) -> Dict:
    """
    生成完整单元
    
    完整单元结构：
    {
        'question_id': 'SET_xxx_Q001',
        'question_number': '1',
        'question_text': '题目内容...',
        'question_image': 'path/to/question.jpg',
        'answer': 'A',
        'answer_source': 'answer_card',
        'answer_card_image': 'path/to/answer_card.jpg',
        'answer_card_bbox': 'path/to/complete_unit.jpg'  # 题目 + 答案合成图
    }
    
    Args:
        linked_results: 关联结果
        
    Returns:
        完整单元字典
    """
    complete_units = {}
    
    for question_number, data in linked_results.items():
        question = data.get('question', {})
        answer = data.get('answer')
        answer_source = data.get('answer_source')
        answer_card_info = data.get('answer_card_info') or {}  # 确保不是 None
        answer_fragments = data.get('answer_fragments', [])  # 答题区碎片
        
        # 构建完整单元 - 确保题目信息完整
        unit = {
            'question_number': question_number,
            'question_text': question.get('question_text', question.get('description', '')),
            'question_image': question.get('question_image', question.get('crop_path', '')),
            'answer': answer,
            'answer_source': answer_source,
        }
        
        # 只有当 answer_card_info 存在时才添加涂卡区信息
        if answer_card_info:
            unit['answer_card_image'] = answer_card_info.get('crop_path', answer_card_info.get('card_number', ''))
            unit['answer_card_bbox'] = answer_card_info.get('bbox', {})
        
        # 添加切片路径（新增）
        unit['question_slice_path'] = question.get('question_slice_path')
        unit['answer_slice_path'] = data.get('answer_slice_path')
        unit['complete_unit_image_path'] = data.get('complete_unit_image_path')
        unit['is_mixed_mode'] = question.get('is_mixed_sheet', False)
        
        # 添加答题区碎片信息（主观题）
        if answer_fragments:
            unit['answer_area_images'] = [f.get('crop_path', f.get('source_corrected_image', '')) for f in answer_fragments]
            unit['answer_area_count'] = len(answer_fragments)
        
        # 生成唯一 ID
        sheet_id = question.get('sheet_id', 'unknown')
        unit['question_id'] = f"{sheet_id}_Q{question_number.zfill(3)}"
        unit['sheet_id'] = sheet_id
        
        complete_units[question_number] = unit
    
    print(f"  生成 {len(complete_units)} 个完整单元")
    
    return complete_units


def print_complete_units_summary(complete_units: Dict):
    """
    打印完整单元摘要
    
    Args:
        complete_units: 完整单元字典
    """
    print("\n" + "=" * 60)
    print("完整单元摘要")
    print("=" * 60)
    
    for q_num in sorted(complete_units.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        unit = complete_units[q_num]
        answer = unit.get('answer', 'N/A')
        question_text = unit.get('question_text', '')[:30]  # 截取前 30 字
        
        print(f"  第{q_num:2s}题: {answer:6s} | {question_text}...")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='答题卡识别完整流程')
    parser.add_argument('--content-output', required=True, help='内容提取结果 JSON 路径')
    parser.add_argument('--merged-results', required=True, help='合并结果 JSON 路径')
    parser.add_argument('--workspace-dir', required=True, help='工作目录')
    args = parser.parse_args()
    
    # 运行完整流程
    complete_units = run_answer_card_pipeline(
        content_output_path=args.content_output,
        merged_results_path=args.merged_results,
        workspace_dir=args.workspace_dir
    )
    
    # 打印摘要
    print_complete_units_summary(complete_units)
