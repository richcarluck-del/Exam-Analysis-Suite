"""
答案关联任务

功能：
1. 读取涂卡区识别结果
2. 读取题目切片数据
3. 按题号关联填涂答案与题目
"""

import json
import os
from typing import Dict


def link_answers_to_questions(
    answer_card_results: Dict,
    merged_results: Dict
) -> Dict:
    """
    将填涂答案与题目关联
    
    Args:
        answer_card_results: 涂卡区识别结果
            {
                "1-21": {
                    "answers": {"1": "A", "2": "C", ...},
                    ...
                }
            }
        merged_results: 合并后的题目数据
            {
                "1": [question_fragment1, question_fragment2, ...],
                "2": [...],
                ...
            }
            
    Returns:
        关联结果：
        {
            '1': {
                'question': {...},      # 题目切片信息
                'answer': 'A',          # 学生填涂的答案
                'answer_source': 'answer_card',
                'answer_card_bbox': [...]  # 涂卡区坐标
            },
            '2': {
                'question': {...},
                'answer': 'C',
                'answer_source': 'answer_card',
                ...
            },
            ...
        }
    """
    print("  开始关联题目与答案...")
    
    linked_results = {}
    linked_count = 0
    
    # 构建答案查找表：题号 -> (答案, 涂卡区信息)
    answer_lookup = {}
    for card_number, card_result in answer_card_results.items():
        answers = card_result.get('answers', {})
        for question_number, answer in answers.items():
            answer_lookup[question_number] = {
                'answer': answer,
                'card_number': card_number,
                'card_info': card_result
            }
    
    print(f"  涂卡答案表：共 {len(answer_lookup)} 个答案")
    
    # 遍历所有题目（从 merged_results）
    for question_number, question_fragments in merged_results.items():
        # 跳过非题号的条目（如 "1-21" 是涂卡区标识）
        if '-' in str(question_number):
            continue
        
        # 找到题目纸上的题目碎片
        question_fragment = None
        answer_fragments = []  # 收集所有答题区碎片
        
        for fragment in question_fragments:
            is_question_sheet = fragment.get('is_question_sheet', False)
            is_answer_sheet = fragment.get('is_answer_sheet', False)
            sheet_type = fragment.get('sheet_type', '')
            
            if is_question_sheet or sheet_type in ['question_paper', '题目纸', 'mixed', '混合纸']:
                question_fragment = fragment
            elif is_answer_sheet or sheet_type in ['answer_sheet', '答题纸']:
                answer_fragments.append(fragment)
        
        # 如果没有找到题目碎片，使用第一个碎片
        if not question_fragment and question_fragments:
            question_fragment = question_fragments[0]
        
        if not question_fragment:
            print(f"  [WARNING] 题目 {question_number} 没有找到任何碎片")
            continue
        
        # 构建题目信息
        question_info = {
            'number': question_fragment.get('number', question_number),
            'question_text': question_fragment.get('description', ''),
            'question_image': question_fragment.get('source_corrected_image', ''),
            'crop_path': question_fragment.get('crop_path', ''),
            'sheet_id': question_fragment.get('sheet_id'),
            'sheet_type': question_fragment.get('sheet_type'),
            'is_question_sheet': question_fragment.get('is_question_sheet', False),
            'is_answer_sheet': question_fragment.get('is_answer_sheet', False),
            'points': question_fragment.get('points', {}),
        }
        
        # 查找答案
        answer_data = answer_lookup.get(question_number)
        
        if answer_data:
            # 有涂卡答案
            linked_results[question_number] = {
                'question': question_info,
                'answer': answer_data['answer'],
                'answer_source': 'answer_card',
                'answer_card_info': {
                    'card_number': answer_data['card_number'],
                    'bbox': answer_data['card_info'].get('bbox'),
                    'crop_path': answer_data['card_info'].get('crop_path'),
                    'sheet_id': answer_data['card_info'].get('sheet_id'),
                },
                'answer_fragments': answer_fragments,  # 保存答题区碎片
            }
            linked_count += 1
        else:
            # 没有涂卡答案，但仍然关联（主观题）
            linked_results[question_number] = {
                'question': question_info,
                'answer': None,
                'answer_source': 'answer_area',  # 标记为答题区
                'answer_card_info': None,
                'answer_fragments': answer_fragments,  # 保存答题区碎片
            }
            linked_count += 1
            print(f"  [INFO] 题目 {question_number} 无涂卡答案，关联答题区碎片 {len(answer_fragments)} 个")
    
    print(f"  成功关联 {linked_count} 个题目")
    
    return linked_results


def save_linked_results(
    linked_results: Dict,
    workspace_dir: str,
    filename: str = 'linked_results.json'
) -> str:
    """
    保存关联结果
    
    Args:
        linked_results: 关联结果字典
        workspace_dir: 工作目录
        filename: 输出文件名
        
    Returns:
        输出文件路径
    """
    output_path = os.path.join(workspace_dir, filename)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(linked_results, f, indent=2, ensure_ascii=False)
    
    print(f"  关联结果已保存至：{output_path}")
    
    return output_path


def link_answers(
    answer_card_results_path: str,
    merged_results_path: str,
    workspace_dir: str
) -> Dict:
    """
    主函数：读取文件并关联答案
    
    Args:
        answer_card_results_path: 涂卡区识别结果 JSON 路径
        merged_results_path: 合并结果 JSON 路径
        workspace_dir: 工作目录
        
    Returns:
        关联结果字典
    """
    print("开始关联填涂答案与题目...")
    
    # 1. 读取涂卡区识别结果
    with open(answer_card_results_path, 'r', encoding='utf-8') as f:
        answer_card_results = json.load(f)
    
    # 2. 读取合并结果
    with open(merged_results_path, 'r', encoding='utf-8') as f:
        merged_results = json.load(f)
    
    # 3. 关联
    linked_results = link_answers_to_questions(
        answer_card_results=answer_card_results,
        merged_results=merged_results
    )
    
    # 4. 保存
    save_linked_results(linked_results, workspace_dir)
    
    print("答案关联完成")
    
    return linked_results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='关联填涂答案与题目')
    parser.add_argument('--answer-card-results', required=True, help='涂卡区识别结果 JSON 路径')
    parser.add_argument('--merged-results', required=True, help='合并结果 JSON 路径')
    parser.add_argument('--workspace-dir', required=True, help='工作目录')
    args = parser.parse_args()
    
    link_answers(
        answer_card_results_path=args.answer_card_results,
        merged_results_path=args.merged_results,
        workspace_dir=args.workspace_dir
    )
