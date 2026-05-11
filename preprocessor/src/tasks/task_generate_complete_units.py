"""
步骤7：生成完整单元图片

功能：
1. 从 complete_units.json 读取完整单元数据
2. 从 04_content_output.json 读取题目坐标信息
3. 提取题目切片
4. 提取答题区切片
5. 组合成完整单元图片

输出：
- 07_complete_units/SET_xxx_SHEET_xxx/CUxxx.jpg
- 07_complete_units/complete_units_summary.json
"""

import json
import os
import cv2
import numpy as np
from typing import Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont


def run_generate_complete_units(
    complete_units_path: str,
    content_output_path: str,
    workspace_dir: str,
    image_path_manager=None
) -> Dict:
    """
    生成完整单元图片
    
    Args:
        complete_units_path: complete_units.json 路径
        content_output_path: 04_content_output.json 路径
        workspace_dir: 工作目录
        image_path_manager: 图片路径管理器
        
    Returns:
        生成结果统计
    """
    print("=" * 60)
    print("步骤7：生成完整单元图片")
    print("=" * 60)
    
    # 读取完整单元数据
    with open(complete_units_path, 'r', encoding='utf-8') as f:
        complete_units = json.load(f)
    
    # 读取内容提取结果（获取坐标信息）
    with open(content_output_path, 'r', encoding='utf-8') as f:
        content_output = json.load(f)
    
    # 构建坐标查找表：题号 -> 坐标信息
    coord_lookup = build_coordinate_lookup(content_output)
    
    # 创建输出目录
    output_dir = os.path.join(workspace_dir, '07_complete_units')
    os.makedirs(output_dir, exist_ok=True)
    
    # 统计
    stats = {
        'total': len(complete_units),
        'generated': 0,
        'failed': 0,
        'by_type': {
            'objective': 0,
            'subjective': 0,
            'mixed': 0,
            'no_answer': 0
        }
    }
    
    # 处理每个完整单元
    for question_number, unit_data in complete_units.items():
        try:
            result = generate_single_complete_unit(
                question_number=question_number,
                unit_data=unit_data,
                coord_lookup=coord_lookup,
                output_dir=output_dir,
                workspace_dir=workspace_dir,
                image_path_manager=image_path_manager
            )
            
            if result:
                stats['generated'] += 1
                stats['by_type'][result['type']] += 1
                
                # 更新完整单元数据
                unit_data['complete_unit_image_path'] = result['path']
                unit_data['question_slice_path'] = result.get('question_slice_path')
                unit_data['answer_slice_paths'] = result.get('answer_slice_paths')
            else:
                stats['failed'] += 1
                
        except Exception as e:
            print(f"  [错误] 题{question_number}生成失败: {e}")
            stats['failed'] += 1
    
    # 保存更新后的完整单元数据
    with open(complete_units_path, 'w', encoding='utf-8') as f:
        json.dump(complete_units, f, indent=2, ensure_ascii=False)
    
    # 保存汇总信息
    summary = {
        'total': stats['total'],
        'generated': stats['generated'],
        'failed': stats['failed'],
        'by_type': stats['by_type'],
        'output_dir': output_dir
    }
    
    summary_path = os.path.join(output_dir, 'complete_units_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    # 打印统计
    print(f"\n生成完成：")
    print(f"  - 总数: {stats['total']}")
    print(f"  - 成功: {stats['generated']}")
    print(f"  - 失败: {stats['failed']}")
    print(f"  - 客观题: {stats['by_type']['objective']}")
    print(f"  - 主观题: {stats['by_type']['subjective']}")
    print(f"  - 混合模式: {stats['by_type']['mixed']}")
    print(f"  - 无答案: {stats['by_type']['no_answer']}")
    print(f"\n输出目录: {output_dir}")
    
    return summary


def build_coordinate_lookup(content_output: List) -> Dict:
    """
    构建坐标查找表
    
    Args:
        content_output: 内容提取结果
        
    Returns:
        {题号: {题目信息, 答题区信息列表}}
    """
    lookup = {}
    
    for item in content_output:
        vlm_output = item.get('vlm_output', {})
        questions = vlm_output.get('questions', [])
        
        for q in questions:
            number = str(q.get('number', ''))
            if not number:
                continue
            
            q_type = q.get('type', '')
            is_answer_area = q_type == 'answer_area'
            
            if number not in lookup:
                lookup[number] = {
                    'question_slice_path': None,
                    'answer_areas': []
                }
            
            # 如果是答题区，添加到 answer_areas 列表
            if is_answer_area:
                lookup[number]['answer_areas'].append({
                    'points': q.get('points', {}),
                    'source_image': q.get('source_image_for_crop', ''),
                    'answer_slice_path': q.get('answer_slice_path'),
                    'description': q.get('text', q.get('description', ''))
                })
            else:
                # 如果是题目，保存题目切片路径（不覆盖已有的信息）
                if q.get('question_slice_path'):
                    lookup[number]['question_slice_path'] = q.get('question_slice_path')
                    lookup[number]['points'] = q.get('points', {})
                    lookup[number]['source_image'] = q.get('source_image_for_crop', '')
                    lookup[number]['description'] = q.get('text', q.get('description', ''))
    
    return lookup


def resolve_workspace_path(path: Optional[str], workspace_dir: str) -> Optional[str]:
    """将记录在 JSON 中的路径优先解析到当前 workspace。"""
    if not path:
        return None

    normalized_path = os.path.normpath(path)
    path_parts = normalized_path.split(os.sep)
    anchors = [
        'question_slices',
        'answer_slices',
        'corrected_images',
        'compressed_images',
        'stitched_images',
        'answer_card_areas',
        '06_final_output',
        '07_complete_units',
        '08_annotated_images'
    ]
    lower_parts = [part.lower() for part in path_parts]

    for anchor in anchors:
        if anchor in lower_parts:
            anchor_index = lower_parts.index(anchor)
            candidate = os.path.join(workspace_dir, *path_parts[anchor_index:])
            candidate = os.path.normpath(candidate)
            if os.path.exists(candidate):
                return candidate

    if os.path.exists(normalized_path):
        return normalized_path

    return None


def generate_single_complete_unit(
    question_number: str,
    unit_data: Dict,
    coord_lookup: Dict,
    output_dir: str,
    workspace_dir: str,
    image_path_manager=None
) -> Optional[Dict]:
    """
    生成单个完整单元图片
    
    Args:
        question_number: 题号
        unit_data: 完整单元数据
        coord_lookup: 坐标查找表
        output_dir: 输出目录
        image_path_manager: 图片路径管理器
        
    Returns:
        生成结果 {path, type, question_slice_path, answer_slice_paths}
    """
    answer_source = unit_data.get('answer_source', '')
    is_mixed_mode = unit_data.get('is_mixed_mode', False)
    sheet_id = unit_data.get('sheet_id', 'unknown')
    answer = unit_data.get('answer')
    
    # 创建按 sheet_id 分组的输出目录
    sheet_output_dir = os.path.join(output_dir, sheet_id)
    os.makedirs(sheet_output_dir, exist_ok=True)
    
    # 获取坐标信息
    coord_info = coord_lookup.get(question_number, {})
    
    result = {
        'type': 'no_answer',
        'question_slice_path': None,
        'answer_slice_paths': []
    }
    
    # 1. 获取题目切片，优先使用当前 workspace 中的切片
    question_slice_path = resolve_workspace_path(
        coord_info.get('question_slice_path') or unit_data.get('question_slice_path'),
        workspace_dir
    )
    result['question_slice_path'] = question_slice_path
    
    # 2. 获取答题区信息（优先使用步骤 4.5 已生成的答题区切片）
    answer_areas = coord_info.get('answer_areas', [])
    
    # 3. 根据类型生成完整单元
    if is_mixed_mode:
        # 类型C：混合模式，直接使用题目切片
        result['type'] = 'mixed'
        result['path'] = question_slice_path
        print(f"  题{question_number}: 混合模式")
        
    elif answer_source == 'answer_card' and answer:
        # 类型A：客观题，题目切片 + 答案标注
        result['type'] = 'objective'
        combined_path = combine_question_with_answer_label(
            question_slice_path=question_slice_path,
            answer=answer,
            question_number=question_number,
            output_dir=sheet_output_dir
        )
        result['path'] = combined_path
        print(f"  题{question_number}: 客观题，答案={answer}")
        
    elif answer_source == 'answer_area':
        # 类型B：主观题，题目切片 + 答题区切片
        result['type'] = 'subjective'
        
        answer_slice_paths = []
        for i, area_info in enumerate(answer_areas, 1):
            answer_slice_path = resolve_workspace_path(area_info.get('answer_slice_path'), workspace_dir)
            if answer_slice_path:
                answer_slice_paths.append(answer_slice_path)
                continue
            
            area_path = extract_answer_area_slice(
                area_info=area_info,
                question_number=question_number,
                area_index=i,
                output_dir=sheet_output_dir
            )
            if area_path:
                answer_slice_paths.append(area_path)
        
        result['answer_slice_paths'] = answer_slice_paths
        
        # 组合题目和答题区
        combined_path = combine_question_with_answer_areas(
            question_slice_path=question_slice_path,
            answer_slice_paths=answer_slice_paths,
            question_number=question_number,
            output_dir=sheet_output_dir
        )
        result['path'] = combined_path
        print(f"  题{question_number}: 主观题，答题区{len(answer_slice_paths)}个")
        
    else:
        # 无答案，只使用题目切片
        result['type'] = 'no_answer'
        result['path'] = question_slice_path
        print(f"  题{question_number}: 无答案")
    
    return result


def extract_question_slice(
    question_number: str,
    coord_info: Dict,
    output_dir: str,
    image_path_manager=None
) -> Optional[str]:
    """
    提取题目切片
    
    Args:
        question_number: 题号
        coord_info: 坐标信息
        output_dir: 输出目录
        image_path_manager: 图片路径管理器
        
    Returns:
        切片图片路径
    """
    # 如果已经有切片路径，直接返回
    question_slice_path = coord_info.get('question_slice_path')
    if question_slice_path and os.path.exists(question_slice_path):
        return question_slice_path
    
    # 否则返回 None（需要后续实现从原图裁剪的逻辑）
    return None


def extract_answer_slices(
    question_number: str,
    answer_area_images: List[str],
    output_dir: str
) -> List[str]:
    """
    提取答题区切片
    
    Args:
        question_number: 题号
        answer_area_images: 答题区图片路径列表
        output_dir: 输出目录
        
    Returns:
        切片图片路径列表
    """
    slice_paths = []
    
    for i, image_path in enumerate(answer_area_images, 1):
        if not os.path.exists(image_path):
            continue
        
        # 读取图片
        img = cv2.imread(image_path)
        if img is None:
            continue
        
        # 保存切片
        output_path = os.path.join(output_dir, f'Q{question_number.zfill(3)}_answer_{i}.jpg')
        cv2.imwrite(output_path, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        slice_paths.append(output_path)
    
    return slice_paths


def extract_answer_area_slice(
    area_info: Dict,
    question_number: str,
    area_index: int,
    output_dir: str
) -> Optional[str]:
    """
    从答题区图片中裁剪出答题区切片
    
    Args:
        area_info: 答题区信息（包含坐标和图片路径）
        question_number: 题号
        area_index: 区域索引
        output_dir: 输出目录
        
    Returns:
        切片图片路径
    """
    source_image = area_info.get('source_image', '')
    points = area_info.get('points', {})
    
    if not source_image or not os.path.exists(source_image):
        return None
    
    if not points:
        return None
    
    # 读取原图
    img = cv2.imread(source_image)
    if img is None:
        return None
    
    # 获取坐标
    top_left = points.get('top_left', [0, 0])
    bottom_right = points.get('bottom_right', [0, 0])
    
    x1, y1 = top_left[0], top_left[1]
    x2, y2 = bottom_right[0], bottom_right[1]
    
    # 添加 padding
    padding = 5
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(img.shape[1], x2 + padding)
    y2 = min(img.shape[0], y2 + padding)
    
    # 裁剪
    if x2 <= x1 or y2 <= y1:
        return None
    
    slice_img = img[y1:y2, x1:x2]
    
    # 保存
    output_path = os.path.join(output_dir, f'Q{question_number.zfill(3)}_answer_{area_index}.jpg')
    cv2.imwrite(output_path, slice_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    return output_path


def combine_question_with_answer_label(
    question_slice_path: str,
    answer: str,
    question_number: str,
    output_dir: str
) -> str:
    """
    组合题目切片和答案标注（客观题）
    
    Args:
        question_slice_path: 题目切片路径
        answer: 答案（A/B/C/D）
        question_number: 题号
        output_dir: 输出目录
        
    Returns:
        组合图片路径
    """
    if not question_slice_path or not os.path.exists(question_slice_path):
        return question_slice_path
    
    # 读取题目切片
    question_img = cv2.imread(question_slice_path)
    if question_img is None:
        return question_slice_path
    
    # 创建答案标注区域
    h, w = question_img.shape[:2]
    label_height = 60
    label_img = np.ones((label_height, w, 3), dtype=np.uint8) * 255  # 白色背景
    
    # 添加文字
    font = cv2.FONT_HERSHEY_SIMPLEX
    text = f"Answer: {answer}"
    font_scale = 1.5
    thickness = 2
    
    # 计算文字位置（居中）
    (text_w, text_h), baseline = cv2.getTextSize(text, font, font_scale, thickness)
    text_x = (w - text_w) // 2
    text_y = (label_height + text_h) // 2
    
    # 绘制文字
    cv2.putText(label_img, text, (text_x, text_y), font, font_scale, (0, 0, 0), thickness)
    
    # 上下拼接
    combined = cv2.vconcat([question_img, label_img])
    
    # 保存
    output_path = os.path.join(output_dir, f'CU{question_number.zfill(3)}.jpg')
    cv2.imwrite(output_path, combined, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    return output_path


def combine_question_with_answer_areas(
    question_slice_path: str,
    answer_slice_paths: List[str],
    question_number: str,
    output_dir: str
) -> str:
    """
    组合题目切片和答题区切片（主观题）
    
    Args:
        question_slice_path: 题目切片路径
        answer_slice_paths: 答题区切片路径列表
        question_number: 题号
        output_dir: 输出目录
        
    Returns:
        组合图片路径
    """
    images = []
    
    # 读取题目切片
    if question_slice_path and os.path.exists(question_slice_path):
        question_img = cv2.imread(question_slice_path)
        if question_img is not None:
            images.append(question_img)
    
    # 读取答题区切片
    for answer_path in answer_slice_paths:
        if os.path.exists(answer_path):
            answer_img = cv2.imread(answer_path)
            if answer_img is not None:
                images.append(answer_img)
    
    if not images:
        return None
    
    # 统一宽度
    target_width = max(img.shape[1] for img in images)
    resized_images = []
    
    for img in images:
        if img.shape[1] != target_width:
            scale = target_width / img.shape[1]
            new_height = int(img.shape[0] * scale)
            img = cv2.resize(img, (target_width, new_height))
        resized_images.append(img)
    
    # 上下拼接
    combined = cv2.vconcat(resized_images)
    
    # 保存
    output_path = os.path.join(output_dir, f'CU{question_number.zfill(3)}.jpg')
    cv2.imwrite(output_path, combined, [cv2.IMWRITE_JPEG_QUALITY, 95])
    
    return output_path
