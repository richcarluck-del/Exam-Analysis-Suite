"""
答题纸内容提取验证模块

功能：
1. 验证输出格式是否符合规范
2. 检查必填字段是否完整
3. 验证题号格式是否正确
4. 检查类型字段是否合理
5. 生成详细的验证报告
"""

import json
import re
from typing import Dict, List, Any, Tuple
from enum import Enum


class ValidationLevel(Enum):
    """验证级别"""
    ERROR = "error"      # 错误：必须修复
    WARNING = "warning"  # 警告：建议修复
    INFO = "info"       # 信息：仅供参考


class ValidationResult:
    """验证结果"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.infos = []
        self.is_valid = True
    
    def add(self, level: ValidationLevel, message: str, question_index: int = None):
        """添加验证结果"""
        formatted_message = message
        if question_index is not None:
            formatted_message = f"问题 {question_index+1}: {message}"
        
        if level == ValidationLevel.ERROR:
            self.errors.append(formatted_message)
            self.is_valid = False
        elif level == ValidationLevel.WARNING:
            self.warnings.append(formatted_message)
        elif level == ValidationLevel.INFO:
            self.infos.append(formatted_message)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len(self.infos),
            "errors": self.errors,
            "warnings": self.warnings,
            "infos": self.infos
        }
    
    def __str__(self) -> str:
        """字符串表示"""
        result = []
        
        if self.errors:
            result.append("❌ 错误:")
            for error in self.errors:
                result.append(f"  - {error}")
        
        if self.warnings:
            result.append("⚠️ 警告:")
            for warning in self.warnings:
                result.append(f"  - {warning}")
        
        if self.infos:
            result.append("ℹ️ 信息:")
            for info in self.infos:
                result.append(f"  - {info}")
        
        result.append(f"\n总计: {len(self.errors)} 个错误, {len(self.warnings)} 个警告, {len(self.infos)} 个信息")
        result.append(f"验证结果: {'✅ 通过' if self.is_valid else '❌ 失败'}")
        
        return "\n".join(result)


def validate_answer_sheet_output(extracted_data: Dict[str, Any], sheet_type: str) -> ValidationResult:
    """
    验证答题纸内容提取输出
    
    Args:
        extracted_data: 提取的数据
        sheet_type: 纸张类型
        
    Returns:
        验证结果
    """
    result = ValidationResult()
    
    # 只验证答题纸
    if sheet_type not in ['answer_sheet', '答题纸']:
        result.add(ValidationLevel.INFO, f"非答题纸类型: {sheet_type}，跳过验证")
        return result
    
    # 1. 验证数据结构
    validate_structure(extracted_data, result)
    
    if not extracted_data or 'questions' not in extracted_data:
        return result
    
    questions = extracted_data['questions']
    
    # 2. 验证每个问题
    for i, question in enumerate(questions):
        validate_question(question, i, result)
    
    # 3. 验证整体一致性
    validate_consistency(questions, result)
    
    return result


def validate_structure(data: Dict[str, Any], result: ValidationResult):
    """验证数据结构"""
    if not data:
        result.add(ValidationLevel.ERROR, "数据为空")
        return
    
    if 'questions' not in data:
        result.add(ValidationLevel.ERROR, "缺少questions字段")
        return
    
    questions = data.get('questions', [])
    
    if not isinstance(questions, list):
        result.add(ValidationLevel.ERROR, "questions字段不是列表")
        return
    
    if len(questions) == 0:
        result.add(ValidationLevel.WARNING, "questions列表为空")


def validate_question(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证单个问题"""
    # 1. 验证必填字段
    validate_required_fields(question, index, result)
    
    # 2. 验证题号格式
    validate_number_format(question, index, result)
    
    # 3. 验证类型字段
    validate_type_field(question, index, result)
    
    # 4. 验证坐标
    validate_points(question, index, result)
    
    # 5. 验证描述
    validate_description(question, index, result)
    
    # 6. 验证逻辑一致性
    validate_logic_consistency(question, index, result)


def validate_required_fields(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证必填字段"""
    required_fields = ['number', 'type', 'points', 'description']
    
    for field in required_fields:
        if field not in question:
            result.add(ValidationLevel.ERROR, f"缺少必填字段 '{field}'", index)
        elif not question[field]:
            result.add(ValidationLevel.WARNING, f"字段 '{field}' 为空", index)


def validate_number_format(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证题号格式"""
    number = str(question.get('number', ''))
    q_type = question.get('type', '')
    
    if not number:
        result.add(ValidationLevel.ERROR, "题号为空", index)
        return
    
    # 检查排除的题号
    excluded_numbers = ['考号', '姓名', '班级', '学校', 'unknown', 'excluded']
    if number in excluded_numbers:
        result.add(ValidationLevel.ERROR, f"题号 '{number}' 应该被排除", index)
        return
    
    # 根据类型验证格式
    if q_type == 'objective_choice':
        # 涂卡区应该是范围格式
        if '-' not in number:
            result.add(ValidationLevel.ERROR, f"涂卡区题号应为范围格式，但得到 '{number}'", index)
        else:
            # 验证范围格式
            parts = number.split('-')
            if len(parts) != 2:
                result.add(ValidationLevel.ERROR, f"范围格式错误: '{number}'", index)
            else:
                try:
                    start = int(parts[0])
                    end = int(parts[1])
                    if start <= 0 or end <= 0:
                        result.add(ValidationLevel.WARNING, f"范围包含非正数: '{number}'", index)
                    if start > end:
                        result.add(ValidationLevel.WARNING, f"范围顺序错误: '{number}'", index)
                    if end - start > 50:  # 假设最多50题
                        result.add(ValidationLevel.WARNING, f"范围过大: '{number}'", index)
                except ValueError:
                    result.add(ValidationLevel.ERROR, f"范围包含非数字: '{number}'", index)
    
    elif q_type == 'answer_area':
        # 主观题应该是单个数字
        if not number.isdigit():
            result.add(ValidationLevel.ERROR, f"主观题题号应为数字，但得到 '{number}'", index)
        else:
            try:
                num = int(number)
                if num <= 0:
                    result.add(ValidationLevel.WARNING, f"题号非正数: '{number}'", index)
                if num > 100:  # 假设最多100题
                    result.add(ValidationLevel.WARNING, f"题号过大: '{number}'", index)
            except ValueError:
                pass  # 已经在上面检查过了


def validate_type_field(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证类型字段"""
    q_type = question.get('type', '')
    valid_types = ['objective_choice', 'answer_area']
    
    if not q_type:
        result.add(ValidationLevel.ERROR, "类型字段为空", index)
        return
    
    if q_type not in valid_types:
        result.add(ValidationLevel.ERROR, f"无效的类型: '{q_type}'，有效类型: {valid_types}", index)
    
    # 检查类型与描述的匹配
    description = str(question.get('description', '')).lower()
    
    if q_type == 'objective_choice':
        objective_keywords = ['涂卡', '填涂', '选择题', '客观题', '选项']
        if not any(keyword in description for keyword in objective_keywords):
            result.add(ValidationLevel.WARNING, f"类型为涂卡区但描述不包含相关关键词", index)
    
    elif q_type == 'answer_area':
        answer_keywords = ['主观题', '作答区', '书写区', '答题框', '解答']
        if not any(keyword in description for keyword in answer_keywords):
            result.add(ValidationLevel.WARNING, f"类型为主观题但描述不包含相关关键词", index)


def validate_points(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证坐标"""
    points = question.get('points', {})
    
    if not points:
        result.add(ValidationLevel.ERROR, "坐标字段为空", index)
        return
    
    required_points = ['top_left', 'top_right', 'bottom_right', 'bottom_left']
    
    for point_name in required_points:
        if point_name not in points:
            result.add(ValidationLevel.ERROR, f"缺少坐标点 '{point_name}'", index)
            continue
        
        point = points[point_name]
        
        if not isinstance(point, list):
            result.add(ValidationLevel.ERROR, f"坐标点 '{point_name}' 不是列表", index)
            continue
        
        if len(point) != 2:
            result.add(ValidationLevel.ERROR, f"坐标点 '{point_name}' 长度不为2", index)
            continue
        
        x, y = point
        
        # 验证坐标范围 (0-1000)
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            result.add(ValidationLevel.ERROR, f"坐标点 '{point_name}' 包含非数字值", index)
            continue
        
        if x < 0 or x > 1000:
            result.add(ValidationLevel.WARNING, f"坐标点 '{point_name}' 的x坐标超出范围: {x}", index)
        
        if y < 0 or y > 1000:
            result.add(ValidationLevel.WARNING, f"坐标点 '{point_name}' 的y坐标超出范围: {y}", index)
    
    # 验证矩形逻辑
    if all(p in points for p in required_points):
        try:
            tl = points['top_left']
            tr = points['top_right']
            br = points['bottom_right']
            bl = points['bottom_left']
            
            # 检查矩形是否有效
            if tl[0] > tr[0]:
                result.add(ValidationLevel.WARNING, "左上角的x坐标大于右上角", index)
            
            if tr[1] > br[1]:
                result.add(ValidationLevel.WARNING, "右上角的y坐标大于右下角", index)
            
            if bl[0] > br[0]:
                result.add(ValidationLevel.WARNING, "左下角的x坐标大于右下角", index)
            
            if tl[1] > bl[1]:
                result.add(ValidationLevel.WARNING, "左上角的y坐标大于左下角", index)
            
            # 检查矩形面积
            width = abs(tr[0] - tl[0])
            height = abs(bl[1] - tl[1])
            
            if width < 10 or height < 10:
                result.add(ValidationLevel.WARNING, f"矩形过小: {width}x{height}", index)
            
            if width > 900 or height > 900:
                result.add(ValidationLevel.WARNING, f"矩形过大: {width}x{height}", index)
                
        except (TypeError, IndexError):
            pass  # 已经在上面检查过了


def validate_description(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证描述字段"""
    description = question.get('description', '')
    
    if not description:
        result.add(ValidationLevel.WARNING, "描述字段为空", index)
        return
    
    if len(description) < 5:
        result.add(ValidationLevel.WARNING, "描述过短", index)
    
    if len(description) > 200:
        result.add(ValidationLevel.WARNING, "描述过长", index)
    
    # 检查描述是否包含题号
    number = str(question.get('number', ''))
    if number and number not in description:
        result.add(ValidationLevel.INFO, f"描述中未包含题号 '{number}'", index)


def validate_logic_consistency(question: Dict[str, Any], index: int, result: ValidationResult):
    """验证逻辑一致性"""
    number = str(question.get('number', ''))
    q_type = question.get('type', '')
    description = str(question.get('description', '')).lower()
    
    # 检查题号与类型的一致性
    if q_type == 'objective_choice' and '-' not in number:
        result.add(ValidationLevel.WARNING, "涂卡区但题号不是范围格式", index)
    
    if q_type == 'answer_area' and '-' in number:
        result.add(ValidationLevel.WARNING, "主观题但题号是范围格式", index)
    
    # 检查描述与类型的一致性
    if q_type == 'objective_choice':
        excluded_keywords = ['主观题', '作答区', '书写区', '答题框']
        if any(keyword in description for keyword in excluded_keywords):
            result.add(ValidationLevel.WARNING, "涂卡区但描述包含主观题关键词", index)
    
    if q_type == 'answer_area':
        excluded_keywords = ['涂卡', '填涂', '选择题', '客观题']
        if any(keyword in description for keyword in excluded_keywords):
            result.add(ValidationLevel.WARNING, "主观题但描述包含涂卡区关键词", index)


def validate_consistency(questions: List[Dict[str, Any]], result: ValidationResult):
    """验证整体一致性"""
    if len(questions) <= 1:
        return
    
    # 检查题号重复
    numbers = []
    for i, question in enumerate(questions):
        number = str(question.get('number', ''))
        if number:
            numbers.append((number, i))
    
    number_counts = {}
    for number, index in numbers:
        if number in number_counts:
            number_counts[number].append(index)
        else:
            number_counts[number] = [index]
    
    for number, indices in number_counts.items():
        if len(indices) > 1:
            indices_str = ', '.join(str(i+1) for i in indices)
            result.add(ValidationLevel.WARNING, f"题号 '{number}' 重复出现在问题 {indices_str}")
    
    # 检查题号顺序
    objective_questions = []
    answer_questions = []
    
    for i, question in enumerate(questions):
        q_type = question.get('type', '')
        number = str(question.get('number', ''))
        
        if q_type == 'objective_choice':
            objective_questions.append((number, i))
        elif q_type == 'answer_area':
            answer_questions.append((number, i))
    
    # 检查涂卡区题号范围
    if objective_questions:
        ranges = []
        for number, index in objective_questions:
            if '-' in number:
                parts = number.split('-')
                if len(parts) == 2:
                    try:
                        start = int(parts[0])
                        end = int(parts[1])
                        ranges.append((start, end, index))
                    except ValueError:
                        pass
        
        # 检查范围重叠
        for i in range(len(ranges)):
            for j in range(i+1, len(ranges)):
                start1, end1, idx1 = ranges[i]
                start2, end2, idx2 = ranges[j]
                
                if max(start1, start2) <= min(end1, end2):
                    result.add(ValidationLevel.WARNING, 
                              f"涂卡区范围重叠: '{start1}-{end1}' (问题{idx1+1}) 和 '{start2}-{end2}' (问题{idx2+1})")
    
    # 检查主观题题号连续性
    if answer_questions:
        numbers = []
        for number, index in answer_questions:
            if number.isdigit():
                numbers.append((int(number), index))
        
        if numbers:
            numbers.sort(key=lambda x: x[0])
            
            # 检查是否有缺失的题号
            expected = numbers[0][0]
            for num, index in numbers:
                if num != expected:
                    result.add(ValidationLevel.INFO, 
                              f"主观题题号不连续: 期望 {expected}，得到 {num} (问题{index+1})")
                expected = num + 1


def generate_validation_report(validation_result: ValidationResult, output_path: str = None) -> str:
    """
    生成验证报告
    
    Args:
        validation_result: 验证结果
        output_path: 输出文件路径（可选）
        
    Returns:
        报告文本
    """
    report = []
    
    # 标题
    report.append("=" * 80)
    report.append("答题纸内容提取验证报告")
    report.append("=" * 80)
    
    # 摘要
    report.append(f"\n📊 验证摘要:")
    report.append(f"  - 验证结果: {'✅ 通过' if validation_result.is_valid else '❌ 失败'}")
    report.append(f"  - 错误数量: {len(validation_result.errors)}")
    report.append(f"  - 警告数量: {len(validation_result.warnings)}")
    report.append(f"  - 信息数量: {len(validation_result.infos)}")
    
    # 详细结果
    if validation_result.errors:
        report.append(f"\n❌ 错误 ({len(validation_result.errors)} 个):")
        for i, error in enumerate(validation_result.errors, 1):
            report.append(f"  {i}. {error}")
    
    if validation_result.warnings:
        report.append(f"\n⚠️ 警告 ({len(validation_result.warnings)} 个):")
        for i, warning in enumerate(validation_result.warnings, 1):
            report.append(f"  {i}. {warning}")
    
    if validation_result.infos:
        report.append(f"\nℹ️ 信息 ({len(validation_result.infos)} 个):")
        for i, info in enumerate(validation_result.infos, 1):
            report.append(f"  {i}. {info}")
    
    # 建议
    report.append(f"\n💡 建议:")
    if validation_result.errors:
        report.append("  1. 优先修复所有错误")
    if validation_result.warnings:
        report.append("  2. 考虑修复警告问题")
    if not validation_result.errors and not validation_result.warnings:
        report.append("  所有验证通过，输出格式良好！")
    
    report.append("=" * 80)
    
    report_text = "\n".join(report)
    
    # 保存到文件
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"✅ 验证报告已保存到: {output_path}")
    
    return report_text


# 测试函数
def test_validation():
    """测试验证功能"""
    test_cases = [
        {
            "name": "有效数据",
            "data": {
                "questions": [
                    {
                        "number": "1-21",
                        "type": "objective_choice",
                        "points": {
                            "top_left": [100, 200],
                            "top_right": [900, 200],
                            "bottom_right": [900, 350],
                            "bottom_left": [100, 350]
                        },
                        "description": "第1-21题选择题涂卡区"
                    },
                    {
                        "number": "22",
                        "type": "answer_area",
                        "points": {
                            "top_left": [95, 360],
                            "top_right": [900, 360],
                            "bottom_right": [900, 510],
                            "bottom_left": [95, 510]
                        },
                        "description": "第22题主观题作答区"
                    }
                ]
            },
            "expected_valid": True
        },
        {
            "name": "包含错误的数据",
            "data": {
                "questions": [
                    {
                        "number": "涂卡区",
                        "type": "unknown",
                        "points": {},
                        "description": ""
                    },
                    {
                        "number": "考号",
                        "type": "objective_choice",
                        "points": {"top_left": [50, 50]},
                        "description": "考号填涂区"
                    }
                ]
            },
            "expected_valid": False
        }
    ]
    
    print("测试验证功能...")
    print("=" * 80)
    
    for test_case in test_cases:
        print(f"\n测试用例: {test_case['name']}")
        
        result = validate_answer_sheet_output(test_case['data'], "answer_sheet")
        report = generate_validation_report(result)
        
        print(f"预期有效: {test_case['expected_valid']}")
        print(f"实际有效: {result.is_valid}")
        print(f"状态: {'✅ 通过' if result.is_valid == test_case['expected_valid'] else '❌ 失败'}")
        
        # 显示摘要
        print(f"\n验证摘要:")
        print(f"  错误: {len(result.errors)} 个")
        print(f"  警告: {len(result.warnings)} 个")
        print(f"  信息: {len(result.infos)} 个")
    
    print("\n" + "=" * 80)
    print("测试完成")


if __name__ == "__main__":
    test_validation()