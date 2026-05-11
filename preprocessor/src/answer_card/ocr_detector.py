"""
答题卡 OCR 识别模块

功能：
1. 定位每个选项框的位置
2. 识别每个选项是否被填涂
3. 返回填涂结果
"""

import cv2
import numpy as np
import os
import json
from typing import List, Dict, Tuple


def detect_option_boxes(crop_image: np.ndarray) -> List[Dict]:
    """
    检测每个选项框的位置（优化版）
    
    使用 OMRChecker 的算法原理：
    1. 灰度化 + 自适应阈值二值化
    2. 查找轮廓，定位选项框
    3. 按位置排序，分配题号和选项
    
    Args:
        crop_image: 涂卡区切片图片
        
    Returns:
        选项框列表：
        [
            {'question_num': '1', 'option': 'A', 'bbox': [x, y, w, h], 'contour': cnt},
            ...
        ]
    """
    # 1. 灰度化
    if len(crop_image.shape) == 3:
        gray = cv2.cvtColor(crop_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = crop_image.copy()
    
    # 2. 自适应阈值二值化（比固定阈值更好）
    # 使用高斯自适应阈值，更好地处理光照不均
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV, 11, 2
    )
    
    # 3. 形态学操作（去除噪点，连接断裂的区域）
    kernel = np.ones((3, 3), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
    
    # 4. 查找轮廓
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # 5. 筛选选项框轮廓
    option_boxes = []
    img_h, img_w = gray.shape
    min_area = (img_w * img_h) / 10000  # 最小面积为图片的 1/10000
    max_area = (img_w * img_h) / 100    # 最大面积为图片的 1/100
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        
        # 根据面积筛选
        if min_area < area < max_area:
            x, y, w, h = cv2.boundingRect(cnt)
            aspect_ratio = w / float(h)
            
            # 选项框通常接近圆形或方形
            if 0.5 < aspect_ratio < 2.0:
                option_boxes.append({
                    'bbox': [x, y, w, h],
                    'contour': cnt,
                    'center': (x + w // 2, y + h // 2),
                    'area': area
                })
    
    # 6. 按位置排序，分配题号和选项
    option_boxes = sort_and_assign_questions(option_boxes, img_w, img_h)
    
    return option_boxes


def sort_and_assign_questions(
    option_boxes: List[Dict], 
    img_w: int, 
    img_h: int
) -> List[Dict]:
    """
    按位置排序选项框，并分配题号和选项（优化版）
    
    假设布局：
    - 横向排列：1A 1B 1C 1D 2A 2B 2C 2D ...
    - 或纵向排列：1A 2A 3A ... 1B 2B 3B ...
    
    Args:
        option_boxes: 检测到的选项框
        img_w: 图片宽度
        img_h: 图片高度
        
    Returns:
        分配好题号和选项的列表
    """
    if not option_boxes:
        return []
    
    print(f"    图片尺寸：{img_w}x{img_h}, 检测到 {len(option_boxes)} 个选项框")
    
    # 1. 按 y 坐标排序（从上到下）
    option_boxes_sorted_y = sorted(option_boxes, key=lambda k: k['center'][1])
    
    # 2. 按 x 坐标排序（从左到右）
    option_boxes_sorted_x = sorted(option_boxes, key=lambda k: k['center'][0])
    
    # 3. 判断布局方向
    # 计算 y 坐标的变化
    y_coords = [box['center'][1] for box in option_boxes_sorted_x]
    y_variance = np.var(y_coords)
    
    # 如果图片很扁长（宽>高*3），很可能是横向排列
    is_wide_image = img_w > img_h * 3
    
    # 如果 y 坐标变化小，说明是横向排列
    # 如果 y 坐标变化大，说明是纵向排列
    is_horizontal = y_variance < (img_h * 0.2) ** 2 or is_wide_image
    
    print(f"    布局方向：{'横向' if is_horizontal else '纵向'} (y_variance={y_variance:.2f}, threshold={(img_h * 0.2) ** 2:.2f}, is_wide={is_wide_image})")
    
    # 4. 分组（按行或按列）
    if is_horizontal:
        # 横向排列：按 x 坐标分组（每 4 个或 5 个为一组）
        # 使用更智能的分组：根据 x 坐标的跳跃
        groups = group_by_position_smart(option_boxes_sorted_x, axis='x', min_gap_ratio=0.5)
    else:
        # 纵向排列：按 y 坐标分组
        groups = group_by_position_smart(option_boxes_sorted_y, axis='y', min_gap_ratio=0.5)
    
    print(f"    分组数：{len(groups)} 组")
    
    # 5. 分配题号和选项
    result = []
    options = ['A', 'B', 'C', 'D', 'E', 'F']  # 支持更多选项
    
    for group_idx, group in enumerate(groups):
        # 按位置排序组内选项
        if is_horizontal:
            group_sorted = sorted(group, key=lambda k: k['center'][0])
        else:
            group_sorted = sorted(group, key=lambda k: k['center'][1])
        
        # 分配选项字母
        for opt_idx, box in enumerate(group_sorted):
            if opt_idx < len(options):
                box['question_num'] = str(group_idx + 1)
                box['option'] = options[opt_idx]
                result.append(box)
    
    return result


def group_by_position_smart(
    boxes: List[Dict], 
    axis: str = 'x',
    min_gap_ratio: float = 0.3
) -> List[List[Dict]]:
    """
    智能分组：根据坐标的跳跃来分组
    
    Args:
        boxes: 选项框列表
        axis: 分组轴 ('x' 或 'y')
        min_gap_ratio: 最小间隔比例（相对于框的平均大小）
        
    Returns:
        分组后的列表
    """
    if not boxes:
        return []
    
    # 计算平均框大小
    if axis == 'x':
        avg_size = np.mean([box['bbox'][2] for box in boxes])  # 平均宽度
    else:
        avg_size = np.mean([box['bbox'][3] for box in boxes])  # 平均高度
    
    # 计算最小间隔
    min_gap = avg_size * min_gap_ratio
    
    groups = []
    current_group = [boxes[0]]
    
    for i in range(1, len(boxes)):
        prev_box = current_group[-1]
        curr_box = boxes[i]
        
        # 计算位置差异
        if axis == 'x':
            diff = curr_box['center'][0] - prev_box['center'][0]
        else:
            diff = curr_box['center'][1] - prev_box['center'][1]
        
        # 如果间隔超过阈值，开始新组
        if diff > min_gap:
            groups.append(current_group)
            current_group = []
        
        current_group.append(curr_box)
    
    # 添加最后一组
    if current_group:
        groups.append(current_group)
    
    return groups


def group_by_position(
    boxes: List[Dict], 
    axis: str = 'x',
    threshold: int = 20
) -> List[List[Dict]]:
    """
    按位置分组（同一行的选项分为一组）
    
    Args:
        boxes: 选项框列表
        axis: 分组轴 ('x' 或 'y')
        threshold: 分组阈值（像素）
        
    Returns:
        分组后的列表
    """
    if not boxes:
        return []
    
    groups = []
    current_group = [boxes[0]]
    
    for i in range(1, len(boxes)):
        prev_box = current_group[-1]
        curr_box = boxes[i]
        
        # 计算位置差异
        if axis == 'x':
            diff = abs(curr_box['center'][0] - prev_box['center'][0])
        else:
            diff = abs(curr_box['center'][1] - prev_box['center'][1])
        
        # 如果差异超过阈值，开始新组
        if diff > threshold:
            groups.append(current_group)
            current_group = []
        
        current_group.append(curr_box)
    
    # 添加最后一组
    if current_group:
        groups.append(current_group)
    
    return groups


def detect_filled_option(
    crop_image: np.ndarray, 
    option_box: Dict,
    threshold: float = 0.4
) -> bool:
    """
    判断选项是否被填涂（优化版）
    
    方法：
    1. 分析框内像素密度
    2. 填涂的区域通常颜色更深、密度更高
    3. 使用中心区域分析，避免边框干扰
    
    Args:
        crop_image: 涂卡区切片图片
        option_box: 选项框信息
        threshold: 填涂判断阈值（0-1）
        
    Returns:
        是否被填涂
    """
    x, y, w, h = option_box['bbox']
    
    # 1. 提取 ROI（Region of Interest）
    roi = crop_image[y:y+h, x:x+w]
    
    if roi.size == 0:
        return False
    
    # 2. 灰度化
    if len(roi.shape) == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi.copy()
    
    # 3. 缩小分析区域到中心 70%（避免边框干扰）
    margin_x = int(w * 0.15)
    margin_y = int(h * 0.15)
    center_roi = gray[margin_y:h-margin_y, margin_x:w-margin_x]
    
    if center_roi.size == 0:
        return False
    
    # 4. 使用 Otsu 自动阈值分割
    _, thresh = cv2.threshold(center_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # 5. 计算填涂比例
    filled_ratio = cv2.countNonZero(thresh) / center_roi.size
    
    # 6. 判断
    return filled_ratio > threshold


def recognize_answer_card(crop_image_path: str) -> Dict[str, str]:
    """
    识别涂卡区的所有答案
    
    Args:
        crop_image_path: 涂卡区切片图片路径
        
    Returns:
        答案字典：
        {
            '1': 'A',  # 第 1 题选 A
            '2': 'C',  # 第 2 题选 C
            '3': 'B',
            ...
        }
    """
    # 1. 加载图片
    image = cv2.imread(crop_image_path)
    
    if image is None:
        raise ValueError(f"无法加载图片：{crop_image_path}")
    
    # 2. 检测所有选项框
    option_boxes = detect_option_boxes(image)
    
    print(f"    检测到 {len(option_boxes)} 个选项框")
    
    # 3. 识别每个选项是否填涂
    answers = {}
    filled_count = 0
    
    for box in option_boxes:
        question_num = box['question_num']
        option = box['option']
        
        is_filled = detect_filled_option(image, box)
        
        if is_filled:
            filled_count += 1
            
            # 如果该题已经有答案，可能是多选或误识别
            if question_num in answers:
                # 记录警告（实际应用中可能需要特殊处理）
                print(f"    [WARNING] 第{question_num}题检测到多个答案：{answers[question_num]} 和 {option}")
            else:
                answers[question_num] = option
    
    print(f"    识别到 {filled_count} 个填涂答案")
    
    return answers


def process_answer_card_areas(
    answer_card_results: Dict,
    workspace_dir: str
) -> Dict:
    """
    批量处理所有涂卡区，识别填涂答案
    
    Args:
        answer_card_results: 涂卡区识别结果（包含 crop_path）
        workspace_dir: 工作目录
        
    Returns:
        包含答案的涂卡区结果
    """
    print("  开始识别涂卡区答案...")
    
    enhanced_results = {}
    
    for number, result in answer_card_results.items():
        crop_path = result.get('crop_path')
        
        if not crop_path or not os.path.exists(crop_path):
            print(f"  [WARNING] 涂卡区 {number} 的图片不存在：{crop_path}")
            continue
        
        try:
            # 识别答案
            answers = recognize_answer_card(crop_path)
            
            # 保存结果
            enhanced_results[number] = {
                **result,
                'answers': answers  # 新增答案字段
            }
            
            print(f"  涂卡区 {number}: 识别到 {len(answers)} 个答案")
            
        except Exception as e:
            print(f"  [ERROR] 识别涂卡区 {number} 失败：{e}")
            enhanced_results[number] = {
                **result,
                'answers': {},
                'error': str(e)
            }
    
    # 保存增强后的结果
    output_path = os.path.join(workspace_dir, 'answer_card_results.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        import json
        json.dump(enhanced_results, f, indent=2, ensure_ascii=False)
    
    print(f"  涂卡区识别结果已保存至：{output_path}")
    
    return enhanced_results


if __name__ == '__main__':
    import argparse
    import json
    
    parser = argparse.ArgumentParser(description='识别涂卡区答案')
    parser.add_argument('--input-json', required=True, help='涂卡区识别结果 JSON 路径')
    parser.add_argument('--workspace-dir', required=True, help='工作目录')
    args = parser.parse_args()
    
    # 读取结果
    with open(args.input_json, 'r', encoding='utf-8') as f:
        answer_card_results = json.load(f)
    
    # 识别答案
    enhanced_results = process_answer_card_areas(
        answer_card_results=answer_card_results,
        workspace_dir=args.workspace_dir
    )
    
    # 输出示例
    print("\n识别结果示例:")
    for number, result in list(enhanced_results.items())[:2]:
        print(f"  {number}: {result.get('answers', {})}")
