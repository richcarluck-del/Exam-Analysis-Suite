import os
from collections import defaultdict

def merge_same_number_questions(all_parts_results: list):
    """
    全局按题号分组，实现跨张关联
    
    返回结构：
    {
        "question_number": [
            {
                "number": "22",
                "sheet_id": "...",
                "sheet_type": "题目纸",
                "order": 1,
                "part_type": "left",
                "bbox": [...],
                "content": "...",
                ...
            }
        ]
    }
    """
    # 全局按题号分组
    results_by_question = defaultdict(list)
    
    for item in all_parts_results:
        vlm_output = item.get('vlm_output')
        if not vlm_output or 'questions' not in vlm_output:
            continue
        
        # 获取张的信息（用于跨张关联）
        sheet_id = item.get('sheet_id', 'unknown')
        sheet_type = item.get('sheet_type', 'unknown')
        order = item.get('order', 9999)
        
        # 判断是题目还是答案（支持中文和英文两种类型）
        # 英文类型：question_paper, answer_sheet, mixed
        # 中文类型：题目纸，答题纸，混合纸
        is_question_sheet = sheet_type in ['题目纸', '混合纸', 'question_paper', 'mixed']
        is_answer_sheet = sheet_type in ['答题纸', '混合纸', 'answer_sheet', 'mixed']
        
        # 处理每个题目
        for question_item in vlm_output['questions']:
            if not isinstance(question_item, dict):
                continue
            
            number = question_item.get('number', 'unknown')
            
            # 创建完整的题目碎片对象
            fragment = {
                **question_item,  # 包含 number, points, description 等
                # 张的信息
                "sheet_id": sheet_id,
                "sheet_type": sheet_type,
                "order": order,
                "is_question_sheet": is_question_sheet,
                "is_answer_sheet": is_answer_sheet,
                # 图片信息
                "source_original_image": item.get('source_image_path'),
                "source_corrected_image": item.get('source_corrected_image'),
                "source_part_image": item.get('part_image_path'),
                # 位置和裁剪信息
                "crop_area": item.get('crop_area'),
                "divider_x": item.get('divider_x'),
                "part_type": item.get('part_type', 'whole')
            }
            
            # 按题号分组（全局）
            results_by_question[number].append(fragment)
    
    # 返回按题号分组的结果
    return dict(results_by_question)
