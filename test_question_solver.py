#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目解答功能测试脚本
测试切图、识别、解题的完整流程
"""

import os
import json
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_question_cropper():
    """测试题目切图功能"""
    from question_solver.cropper import QuestionCropper
    
    print("=== 测试题目切图功能 ===")
    
    # 创建切图器
    cropper = QuestionCropper(padding_ratio=0.05)
    
    # 模拟检测结果
    test_questions = [
        {
            'question_number': '1',
            'bbox': [100, 100, 300, 400]  # [ymin, xmin, ymax, xmax]
        },
        {
            'question_number': '2', 
            'bbox': [100, 500, 300, 800]
        }
    ]
    
    # 测试图片路径（使用项目中的测试图片）
    test_image = "docs/ChemistryExamPaper.jpg"
    
    if not os.path.exists(test_image):
        print(f"测试图片不存在: {test_image}")
        return
    
    try:
        # 批量切图
        cropped_questions = cropper.batch_crop_questions(
            test_image, test_questions, 
            output_dir="test_output/cropped"
        )
        
        print(f"切图完成: {len(cropped_questions)} 道题目")
        
        # 验证切图质量
        valid_questions = cropper.validate_cropped_images(cropped_questions)
        print(f"有效图片: {len(valid_questions)} 张")
        
        return valid_questions
        
    except Exception as e:
        print(f"切图测试失败: {e}")
        return []


def test_question_recognizer(cropped_questions):
    """测试题目识别功能"""
    from question_solver.recognizer import QuestionRecognizer
    
    print("\n=== 测试题目识别功能 ===")
    
    if not cropped_questions:
        print("没有有效的切图题目，跳过识别测试")
        return []
    
    try:
        # 创建识别器
        recognizer = QuestionRecognizer()
        
        # 批量识别（只测试第一题）
        test_question = cropped_questions[0]
        
        print(f"识别题目: {test_question['question_number']}")
        
        # 单个题目识别
        recognition_result = recognizer.recognize_question_content(
            test_question['cropped_image_path']
        )
        
        print(f"识别完成，置信度: {recognition_result.get('recognition_confidence', 0):.2f}")
        
        if 'question_content' in recognition_result:
            content_preview = recognition_result['question_content'][:100] + "..."
            print(f"识别内容预览: {content_preview}")
        
        return [recognition_result]
        
    except Exception as e:
        print(f"识别测试失败: {e}")
        return []


def test_question_solver(recognized_questions):
    """测试题目解答功能"""
    from question_solver.solver import QuestionSolver
    
    print("\n=== 测试题目解答功能 ===")
    
    if not recognized_questions:
        print("没有有效的识别题目，跳过解答测试")
        return []
    
    try:
        # 创建解答器
        solver = QuestionSolver()
        
        # 单个题目解答
        test_question = recognized_questions[0]
        
        print(f"解答题目: {test_question.get('question_number', '未知')}")
        
        # 解答题目
        solution_result = solver.solve_chemistry_question(test_question)
        
        print(f"解答完成，状态: {solution_result.get('status', 'unknown')}")
        
        if solution_result.get('status') == 'success':
            solution = solution_result.get('solution_parsed', {})
            if '最终答案' in solution:
                print(f"最终答案: {solution['最终答案'][:100]}...")
        
        return [solution_result]
        
    except Exception as e:
        print(f"解答测试失败: {e}")
        return []


def test_full_pipeline():
    """测试完整流程"""
    from question_solver.pipeline import QuestionSolvingPipeline
    
    print("\n=== 测试完整解答流程 ===")
    
    # 创建模拟检测结果
    test_detection_result = [
        {
            'question_number': '1',
            'bbox': [100, 100, 300, 400]
        },
        {
            'question_number': '2',
            'bbox': [100, 500, 300, 800]
        }
    ]
    
    # 保存模拟检测结果
    detection_file = "test_detection_result.json"
    with open(detection_file, 'w', encoding='utf-8') as f:
        json.dump(test_detection_result, f, ensure_ascii=False, indent=2)
    
    test_image = "docs/ChemistryExamPaper.jpg"
    
    if not os.path.exists(test_image):
        print(f"测试图片不存在: {test_image}")
        return
    
    try:
        # 创建管道
        pipeline = QuestionSolvingPipeline(output_dir="test_pipeline_output")
        
        # 运行完整流程
        result = pipeline.run_from_detection_file(
            test_image, detection_file,
            save_intermediate=True
        )
        
        print(f"完整流程测试完成!")
        print(f"总题目数: {result['pipeline_info']['total_questions']}")
        print(f"成功解答: {result['pipeline_info']['successful_solutions']}")
        
        # 清理临时文件
        if os.path.exists(detection_file):
            os.remove(detection_file)
            
    except Exception as e:
        print(f"完整流程测试失败: {e}")
        
        # 清理临时文件
        if os.path.exists(detection_file):
            os.remove(detection_file)


def main():
    """主测试函数"""
    print("题目解答功能测试开始...\n")
    
    # 测试切图功能
    cropped_questions = test_question_cropper()
    
    # 测试识别功能
    recognized_questions = test_question_recognizer(cropped_questions)
    
    # 测试解答功能
    solved_questions = test_question_solver(recognized_questions)
    
    # 测试完整流程
    test_full_pipeline()
    
    print("\n=== 测试总结 ===")
    print("所有功能模块测试完成!")
    print("请检查输出目录中的结果文件验证功能。")


if __name__ == "__main__":
    main()