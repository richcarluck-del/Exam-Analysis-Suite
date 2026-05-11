"""
答题纸内容提取后处理模块

功能：
1. 规范化大模型输出，修复常见错误
2. 标准化题号格式
3. 确保类型字段正确
4. 过滤非题目内容
5. 添加缺失的字段
"""

import re
import json
from typing import Dict, List, Any, Optional


PERSONAL_INFO_KEYWORDS = [
    '准考证', '准考号', '考号', '考生号', '证号', '学号', '座位号', '报名号',
    '姓名', '班级', '学校', '条形码', '二维码', '个人信息', '信息填写',
    'personal', 'info', 'information', 'student', 'admission', 'examid', 'exam id', 'barcode', 'id number'
]


def _contains_personal_info_keyword(*values: object) -> bool:
    combined_text = ' '.join(str(value or '').strip().lower() for value in values)
    return any(keyword in combined_text for keyword in PERSONAL_INFO_KEYWORDS)


def normalize_answer_sheet_output(extracted_data: Dict[str, Any], sheet_type: str) -> Dict[str, Any]:

    """
    规范化答题纸内容提取输出
    
    Args:
        extracted_data: 大模型提取的原始数据
        sheet_type: 纸张类型（answer_sheet/question_paper/mixed）
        
    Returns:
        规范化后的数据
    """
    if not extracted_data or 'questions' not in extracted_data:
        return extracted_data
    
    # 只对答题纸进行后处理
    if sheet_type not in ['answer_sheet', '答题纸']:
        return extracted_data
    
    questions = extracted_data['questions']
    if not questions:
        return extracted_data
    
    normalized_questions = []
    
    for question in questions:
        # 1. 规范化题号
        normalized_question = normalize_question_number(question)
        
        # 2. 规范化类型字段
        normalized_question = normalize_question_type(normalized_question)
        
        # 3. 过滤非题目内容
        if should_exclude_question(normalized_question):
            continue
        
        # 4. 规范化描述字段
        normalized_question = normalize_description(normalized_question)
        
        # 5. 添加缺失的字段
        normalized_question = add_missing_fields(normalized_question)
        
        normalized_questions.append(normalized_question)
    
    # 更新questions列表
    extracted_data['questions'] = normalized_questions
    
    return extracted_data


def normalize_question_number(question: Dict[str, Any]) -> Dict[str, Any]:
    """
    规范化题号
    
    规则：
    1. 涂卡区：范围格式 "1-21"、"22-40"
    2. 主观题：单个题号 "22"、"23"
    3. 修复常见错误
    """
    if 'number' not in question:
        question['number'] = 'unknown'
        return question
    
    number = str(question['number']).strip()
    
    # 常见错误修复
    number_fixes = {
        '涂卡区': '1-21',  # 默认涂卡区范围
        'I卷选择题': '1-21',
        '选择题': '1-21',
        '客观题': '1-21',
        '考号': None,
        '准考证号': None,
        '准考号': None,
        '考生号': None,
        'examid': None,
        'exam id': None,
        '姓名': None,
        '班级': None,
        'unknown': None,
        '': None,
    }

    
    # 应用修复
    if number in number_fixes:
        fixed_number = number_fixes[number]
        if fixed_number is None:
            question['number'] = 'excluded'
            return question
        number = fixed_number
    
    # 规范化范围格式
    if '-' in number:
        # 确保范围格式正确
        parts = number.split('-')
        if len(parts) == 2:
            try:
                start = int(parts[0])
                end = int(parts[1])
                # 确保顺序正确
                if start > end:
                    number = f"{end}-{start}"
                else:
                    number = f"{start}-{end}"
            except ValueError:
                # 如果不是数字，保持原样
                pass
    
    # 规范化单个题号
    else:
        # 提取数字
        match = re.search(r'(\d+)', number)
        if match:
            number = match.group(1)
        else:
            # 如果不是数字，尝试推断
            number = infer_question_number(number)
    
    question['number'] = number
    return question


def infer_question_number(text: str) -> str:
    """
    根据描述推断题号
    """
    # 常见模式匹配
    patterns = [
        (r'第\s*(\d+)\s*题', 1),  # 第22题
        (r'题\s*(\d+)', 1),      # 题22
        (r'(\d+)\s*题', 1),      # 22题
        (r'Q(\d+)', 1),          # Q22
        (r'question\s*(\d+)', 1), # question 22
    ]
    
    for pattern, group in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(group)
    
    return 'unknown'


def normalize_question_type(question: Dict[str, Any]) -> Dict[str, Any]:
    """
    规范化类型字段
    
    规则：
    1. 涂卡区：type = "objective_choice"
    2. 主观题：type = "answer_area"
    3. 根据描述推断类型
    """
    number = str(question.get('number', ''))
    description = str(question.get('description', '')).lower()

    if _contains_personal_info_keyword(number, description):
        question['type'] = 'personal_info'
        return question
    
    # 根据题号判断
    if '-' in number:
        # 范围格式 -> 涂卡区
        question['type'] = 'objective_choice'
    
    # 根据描述判断
    elif any(keyword in description for keyword in ['涂卡', '填涂', '选择题', '客观题', '选项']):
        question['type'] = 'objective_choice'
    
    elif any(keyword in description for keyword in ['主观题', '作答区', '书写区', '答题框', '解答']):
        question['type'] = 'answer_area'

    
    # 默认类型
    elif 'type' not in question:
        # 单个数字题号 -> 主观题
        if number.isdigit():
            question['type'] = 'answer_area'
        else:
            question['type'] = 'unknown'
    
    return question


def should_exclude_question(question: Dict[str, Any]) -> bool:
    """
    判断是否应该排除该问题（非题目内容）
    """
    number = str(question.get('number', '')).lower()
    description = str(question.get('description', '')).lower()

    # 排除的题号
    exclude_numbers = [
        '考号', '准考证号', '准考号', '考生号', 'examid', 'exam id',
        '姓名', '班级', '学校', 'excluded', 'unknown', ''
    ]
    if number in exclude_numbers:
        return True

    if _contains_personal_info_keyword(number, description):
        return True
    
    # 排除类型为 unknown / personal_info 的条目
    if question.get('type') in {'unknown', 'personal_info'}:
        return True

    
    return False


def normalize_description(question: Dict[str, Any]) -> Dict[str, Any]:
    """
    规范化描述字段
    """
    if 'description' not in question:
        number = question.get('number', 'unknown')
        q_type = question.get('type', 'unknown')
        
        if q_type == 'objective_choice':
            question['description'] = f"第{number}题选择题涂卡区"
        elif q_type == 'answer_area':
            question['description'] = f"第{number}题主观题作答区"
        else:
            question['description'] = f"第{number}题区域"
    
    return question


def add_missing_fields(question: Dict[str, Any]) -> Dict[str, Any]:
    """
    添加缺失的字段
    """
    # 确保有points字段
    if 'points' not in question:
        question['points'] = {
            'top_left': [0, 0],
            'top_right': [0, 0],
            'bottom_right': [0, 0],
            'bottom_left': [0, 0]
        }
    
    # 确保points格式正确
    points = question['points']
    required_keys = ['top_left', 'top_right', 'bottom_right', 'bottom_left']
    
    for key in required_keys:
        if key not in points:
            points[key] = [0, 0]
        elif not isinstance(points[key], list) or len(points[key]) != 2:
            points[key] = [0, 0]
    
    return question


def validate_normalized_output(extracted_data: Dict[str, Any]) -> List[str]:
    """
    验证规范化后的输出
    
    Returns:
        错误消息列表
    """
    errors = []
    
    if not extracted_data or 'questions' not in extracted_data:
        errors.append("输出数据格式错误：缺少questions字段")
        return errors
    
    questions = extracted_data['questions']
    
    for i, question in enumerate(questions):
        # 检查必填字段
        required_fields = ['number', 'type', 'points', 'description']
        for field in required_fields:
            if field not in question:
                errors.append(f"问题 {i+1}: 缺少必填字段 '{field}'")
        
        # 检查题号格式
        number = str(question.get('number', ''))
        q_type = question.get('type', '')
        
        if q_type == 'objective_choice':
            if '-' not in number:
                errors.append(f"问题 {i+1}: 涂卡区题号应为范围格式，但得到 '{number}'")
        elif q_type == 'answer_area':
            if not number.isdigit():
                errors.append(f"问题 {i+1}: 主观题题号应为数字，但得到 '{number}'")
        
        # 检查坐标
        points = question.get('points', {})
        for key in ['top_left', 'top_right', 'bottom_right', 'bottom_left']:
            if key not in points:
                errors.append(f"问题 {i+1}: 缺少坐标点 '{key}'")
            elif not isinstance(points[key], list) or len(points[key]) != 2:
                errors.append(f"问题 {i+1}: 坐标点 '{key}' 格式错误")
    
    return errors


# 测试函数
def test_postprocessing():
    """测试后处理功能"""
    test_cases = [
        {
            "input": {
                "questions": [
                    {
                        "number": "涂卡区",
                        "description": "I卷选择题作答区",
                        "points": {"top_left": [100, 200], "top_right": [900, 200], "bottom_right": [900, 350], "bottom_left": [100, 350]}
                    },
                    {
                        "number": "22",
                        "description": "第22题主观题",
                        "points": {"top_left": [95, 360], "top_right": [900, 360], "bottom_right": [900, 510], "bottom_left": [95, 510]}
                    },
                    {
                        "number": "考号",
                        "description": "考号填涂区",
                        "points": {"top_left": [50, 50], "top_right": [200, 50], "bottom_right": [200, 100], "bottom_left": [50, 100]}
                    }
                ]
            },
            "expected": {
                "questions": [
                    {
                        "number": "1-21",
                        "type": "objective_choice",
                        "description": "第1-21题选择题涂卡区",
                        "points": {"top_left": [100, 200], "top_right": [900, 200], "bottom_right": [900, 350], "bottom_left": [100, 350]}
                    },
                    {
                        "number": "22",
                        "type": "answer_area",
                        "description": "第22题主观题作答区",
                        "points": {"top_left": [95, 360], "top_right": [900, 360], "bottom_right": [900, 510], "bottom_left": [95, 510]}
                    }
                ]
            }
        }
    ]
    
    print("测试后处理功能...")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases):
        print(f"\n测试用例 {i+1}:")
        
        input_data = test_case["input"]
        expected = test_case["expected"]
        
        # 应用后处理
        result = normalize_answer_sheet_output(input_data, "answer_sheet")
        
        # 验证
        errors = validate_normalized_output(result)
        
        if errors:
            print(f"  ❌ 验证失败:")
            for error in errors:
                print(f"     - {error}")
        else:
            print(f"  ✅ 验证通过")
        
        # 显示结果
        print(f"  输入问题数: {len(input_data['questions'])}")
        print(f"  输出问题数: {len(result['questions'])}")
        print(f"  预期问题数: {len(expected['questions'])}")
        
        # 显示每个问题的详细信息
        for j, question in enumerate(result['questions']):
            print(f"\n  问题 {j+1}:")
            print(f"    number: {question.get('number')}")
            print(f"    type: {question.get('type')}")
            print(f"    description: {question.get('description')[:50]}...")
    
    print("\n" + "=" * 60)
    print("测试完成")


if __name__ == "__main__":
    test_postprocessing()