"""
混合识别方案：OpenCV + 大模型 + 规则校验

功能：
1. OpenCV 初筛：快速检测填涂区域
2. 大模型确认：对不确定的选项进行二次识别
3. 规则校验：检查答案合理性
"""

import cv2
import numpy as np
from typing import Dict, List, Tuple


def hybrid_recognize_answer_card(
    crop_image_path: str,
    vlm_api_config: dict = None
) -> Dict[str, str]:
    """
    混合识别：OpenCV + 大模型
    
    Args:
        crop_image_path: 涂卡区切片图片路径
        vlm_api_config: 大模型 API 配置（可选）
        
    Returns:
        答案字典：{'1': 'A', '2': 'C', ...}
    """
    from src.answer_card.ocr_detector import recognize_answer_card, detect_option_boxes, detect_filled_option
    
    # ========== 步骤 1: OpenCV 识别 ==========
    print("  [步骤 1] OpenCV 初筛...")
    opencv_answers = recognize_answer_card(crop_image_path)
    print(f"    OpenCV 识别到 {len(opencv_answers)} 个答案")
    
    # ========== 步骤 2: 检测不确定性 ==========
    # 识别不确定的题目（OpenCV 未识别到或多选）
    uncertain_questions = []
    
    image = cv2.imread(crop_image_path)
    option_boxes = detect_option_boxes(image)
    
    # 按题号分组
    questions_dict = {}
    for box in option_boxes:
        q_num = box['question_num']
        if q_num not in questions_dict:
            questions_dict[q_num] = []
        questions_dict[q_num].append(box)
    
    # 找出不确定的题目
    for q_num, boxes in questions_dict.items():
        # 情况 1：OpenCV 未识别到
        if q_num not in opencv_answers:
            uncertain_questions.append(q_num)
            continue
        
        # 情况 2：检测到的填涂框数量异常（>1 或=0）
        filled_boxes = [b for b in boxes if detect_filled_option(image, b)]
        if len(filled_boxes) != 1:
            uncertain_questions.append(q_num)
    
    print(f"    发现 {len(uncertain_questions)} 个不确定的题目：{uncertain_questions[:10]}...")
    
    # ========== 步骤 3: 大模型确认（可选） ==========
    if vlm_api_config and uncertain_questions:
        print("  [步骤 3] 大模型确认不确定题目...")
        # TODO: 调用大模型 API 确认不确定题目
        # 这需要裁剪出每个不确定题目的区域，然后调用大模型
        pass
    
    # ========== 步骤 4: 规则校验 ==========
    print("  [步骤 4] 规则校验...")
    validated_answers = validate_answers(opencv_answers)
    
    return validated_answers


def validate_answers(answers: Dict[str, str]) -> Dict[str, str]:
    """
    规则校验答案
    
    规则：
    1. 题号连续性检查
    2. 选项有效性检查（A/B/C/D）
    3. 异常检测（如连续相同答案过多）
    
    Args:
        answers: 原始答案
        
    Returns:
        校验后的答案
    """
    validated = {}
    valid_options = ['A', 'B', 'C', 'D', 'E', 'F']
    
    for q_num, answer in answers.items():
        # 规则 1：选项必须有效
        if answer not in valid_options:
            print(f"    [WARNING] 题目{q_num} 选项{answer} 无效，已跳过")
            continue
        
        # 规则 2：题号必须是数字
        try:
            int(q_num)
            validated[q_num] = answer
        except ValueError:
            print(f"    [WARNING] 题号{q_num} 不是数字，已跳过")
    
    # 规则 3：检测连续相同答案（可选）
    # 如果连续 5 题答案相同，可能是识别错误
    sorted_q_nums = sorted(validated.keys(), key=lambda x: int(x))
    consecutive_same = 1
    max_consecutive = 5
    
    for i in range(1, len(sorted_q_nums)):
        prev_q = sorted_q_nums[i-1]
        curr_q = sorted_q_nums[i]
        
        # 检查题号是否连续
        try:
            if int(curr_q) == int(prev_q) + 1:
                if validated[curr_q] == validated[prev_q]:
                    consecutive_same += 1
                    if consecutive_same >= max_consecutive:
                        print(f"    [WARNING] 检测到连续{consecutive_same}题答案相同，可能需要人工检查")
                else:
                    consecutive_same = 1
        except ValueError:
            continue
    
    print(f"    校验后保留 {len(validated)} 个答案")
    
    return validated


def recognize_with_confidence(
    crop_image_path: str
) -> Dict[str, Tuple[str, float]]:
    """
    识别答案并返回置信度
    
    Args:
        crop_image_path: 涂卡区切片图片路径
        
    Returns:
        答案字典：{'1': ('A', 0.95), '2': ('C', 0.60), ...}
        元组第二个元素是置信度（0-1）
    """
    from src.answer_card.ocr_detector import detect_option_boxes, detect_filled_option
    
    image = cv2.imread(crop_image_path)
    option_boxes = detect_option_boxes(image)
    
    # 按题号分组
    questions_dict = {}
    for box in option_boxes:
        q_num = box['question_num']
        if q_num not in questions_dict:
            questions_dict[q_num] = []
        questions_dict[q_num].append(box)
    
    # 识别每个题的答案和置信度
    answers_with_confidence = {}
    
    for q_num, boxes in questions_dict.items():
        filled_options = []
        
        for box in boxes:
            is_filled = detect_filled_option(image, box)
            option = box['option']
            
            if is_filled:
                # 计算置信度（基于填涂比例）
                confidence = calculate_fill_confidence(image, box)
                filled_options.append((option, confidence))
        
        if filled_options:
            # 选择置信度最高的选项
            best_option = max(filled_options, key=lambda x: x[1])
            answers_with_confidence[q_num] = best_option
        else:
            # 未检测到填涂
            answers_with_confidence[q_num] = (None, 0.0)
    
    return answers_with_confidence


def calculate_fill_confidence(
    crop_image: np.ndarray, 
    option_box: Dict
) -> float:
    """
    计算填涂置信度
    
    Args:
        crop_image: 涂卡区切片
        option_box: 选项框信息
        
    Returns:
        置信度（0-1）
    """
    x, y, w, h = option_box['bbox']
    roi = crop_image[y:y+h, x:x+w]
    
    if roi.size == 0:
        return 0.0
    
    # 灰度化
    if len(roi.shape) == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi.copy()
    
    # 缩小分析区域到中心 70%
    margin_x = int(w * 0.15)
    margin_y = int(h * 0.15)
    center_roi = gray[margin_y:h-margin_y, margin_x:w-margin_x]
    
    if center_roi.size == 0:
        return 0.0
    
    # Otsu 阈值分割
    _, thresh = cv2.threshold(center_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    filled_ratio = cv2.countNonZero(thresh) / center_roi.size
    
    # 将填涂比例转换为置信度
    # 填涂比例在 0.3-0.8 之间置信度最高
    if filled_ratio < 0.2:
        confidence = filled_ratio / 0.2 * 0.5  # 0-0.5
    elif filled_ratio < 0.9:
        confidence = 0.5 + (filled_ratio - 0.2) / 0.7 * 0.5  # 0.5-1.0
    else:
        confidence = 1.0 - (filled_ratio - 0.9) * 2  # 过度填涂降低置信度
    
    return min(max(confidence, 0.0), 1.0)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='混合识别涂卡区答案')
    parser.add_argument('--crop-image', required=True, help='涂卡区切片图片路径')
    args = parser.parse_args()
    
    answers = hybrid_recognize_answer_card(args.crop_image)
    print(f"\n最终识别结果：{answers}")
