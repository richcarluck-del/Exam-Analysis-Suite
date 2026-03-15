#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目解答流程管道
整合切图、识别、解题的完整流程
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from .cropper import QuestionCropper
from .recognizer import QuestionRecognizer
from .solver import QuestionSolver

# 配置日志
logger = logging.getLogger(__name__)


class QuestionSolvingPipeline:
    """题目解答流程管道"""
    
    def __init__(self, 
                 cropper_padding: float = 0.05,
                 recognition_model: str = "Qwen/Qwen3-VL-32B-Instruct",
                 solving_model: str = "deepseek-chat",
                 output_dir: str = "question_solving_output"):
        """
        初始化管道
        
        Args:
            cropper_padding: 切图padding比例
            recognition_model: 识别模型名称
            solving_model: 解题模型名称
            output_dir: 输出目录
        """
        self.cropper = QuestionCropper(padding_ratio=cropper_padding)
        self.recognizer = QuestionRecognizer(model=recognition_model)
        self.solver = QuestionSolver(model=solving_model)
        self.output_dir = Path(output_dir)
        
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    def load_detection_result(self, detection_file: str) -> List[Dict[str, Any]]:
        """
        加载题目检测结果
        
        Args:
            detection_file: 检测结果文件路径
            
        Returns:
            题目列表
        """
        try:
            with open(detection_file, 'r', encoding='utf-8') as f:
                detection_data = json.load(f)
            
            # 支持多种检测结果格式
            if 'questions' in detection_data:
                questions = detection_data['questions']
            else:
                questions = detection_data
            
            # 确保每个题目都有question_number和bbox
            for i, question in enumerate(questions):
                if 'question_number' not in question:
                    question['question_number'] = f'q{i+1}'
                
                # 支持多种bbox格式
                if 'bbox' not in question:
                    # 尝试其他可能的字段
                    for bbox_key in ['coordinates', 'bounding_box', 'box']:
                        if bbox_key in question:
                            question['bbox'] = question[bbox_key]
                            break
            
            logger.info(f"成功加载检测结果: {len(questions)} 道题目")
            return questions
            
        except Exception as e:
            logger.error(f"加载检测结果失败 {detection_file}: {e}")
            raise
    
    def run_pipeline(self, image_path: str, detection_result: List[Dict[str, Any]], 
                    save_intermediate: bool = True) -> Dict[str, Any]:
        """
        运行完整的解答流程
        
        Args:
            image_path: 原始试卷图片路径
            detection_result: 题目检测结果
            save_intermediate: 是否保存中间结果
            
        Returns:
            完整的解答结果
        """
        # 生成时间戳用于文件命名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 阶段1: 题目切图
        logger.info("=== 阶段1: 题目切图 ===")
        cropped_questions = self.cropper.batch_crop_questions(
            image_path, detection_result, 
            output_dir=str(self.output_dir / "cropped_questions")
        )
        
        # 验证切图质量
        valid_cropped = self.cropper.validate_cropped_images(cropped_questions)
        
        if save_intermediate:
            self.save_intermediate_result(valid_cropped, f"cropped_questions_{timestamp}.json")
        
        # 阶段2: 题目识别
        logger.info("=== 阶段2: 题目识别 ===")
        recognized_questions = self.recognizer.batch_recognize_questions(valid_cropped)
        
        # 验证识别质量
        valid_recognized = self.recognizer.validate_recognition_quality(recognized_questions)
        
        if save_intermediate:
            self.save_intermediate_result(valid_recognized, f"recognized_questions_{timestamp}.json")
        
        # 阶段3: 题目解答
        logger.info("=== 阶段3: 题目解答 ===")
        solved_questions = self.solver.batch_solve_questions(valid_recognized)
        
        # 生成最终报告
        final_report = self.solver.generate_final_report(solved_questions)
        
        # 保存最终结果
        final_result = {
            "pipeline_info": {
                "timestamp": timestamp,
                "image_path": image_path,
                "total_questions": len(detection_result),
                "successful_solutions": len([q for q in solved_questions if q.get('status') == 'success'])
            },
            "cropped_questions": cropped_questions,
            "recognized_questions": recognized_questions,
            "solved_questions": solved_questions,
            "final_report": final_report
        }
        
        # 保存最终结果
        self.save_final_result(final_result, timestamp)
        
        logger.info("=== 解答流程完成 ===")
        logger.info(f"总题目数: {len(detection_result)}")
        logger.info(f"成功切图: {len(cropped_questions)}")
        logger.info(f"成功识别: {len(valid_recognized)}")
        logger.info(f"成功解答: {final_result['pipeline_info']['successful_solutions']}")
        
        return final_result
    
    def save_intermediate_result(self, data: List[Dict[str, Any]], filename: str):
        """保存中间结果"""
        file_path = self.output_dir / "intermediate" / filename
        file_path.parent.mkdir(exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"中间结果已保存: {file_path}")
    
    def save_final_result(self, final_result: Dict[str, Any], timestamp: str):
        """保存最终结果"""
        # 保存JSON格式
        json_path = self.output_dir / f"final_result_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        
        # 保存Markdown报告
        md_path = self.output_dir / f"report_{timestamp}.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(final_result['final_report'])
        
        logger.info(f"最终结果已保存:")
        logger.info(f"  - JSON格式: {json_path}")
        logger.info(f"  - Markdown报告: {md_path}")
    
    def run_from_detection_file(self, image_path: str, detection_file: str, 
                               save_intermediate: bool = True) -> Dict[str, Any]:
        """
        从检测结果文件运行完整流程
        
        Args:
            image_path: 原始试卷图片路径
            detection_file: 检测结果文件路径
            save_intermediate: 是否保存中间结果
            
        Returns:
            完整的解答结果
        """
        # 加载检测结果
        detection_result = self.load_detection_result(detection_file)
        
        # 运行流程
        return self.run_pipeline(image_path, detection_result, save_intermediate)


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='题目解答流程管道')
    parser.add_argument('image', help='试卷图片路径')
    parser.add_argument('detection_file', help='题目检测结果JSON文件路径')
    parser.add_argument('--output-dir', default='question_solving_output', 
                       help='输出目录')
    parser.add_argument('--no-intermediate', action='store_true',
                       help='不保存中间结果')
    
    args = parser.parse_args()
    
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # 创建管道
        pipeline = QuestionSolvingPipeline(output_dir=args.output_dir)
        
        # 运行流程
        result = pipeline.run_from_detection_file(
            args.image, 
            args.detection_file,
            save_intermediate=not args.no_intermediate
        )
        
        print(f"\n解答流程完成!")
        print(f"总题目数: {result['pipeline_info']['total_questions']}")
        print(f"成功解答: {result['pipeline_info']['successful_solutions']}")
        print(f"报告文件: {args.output_dir}/report_*.md")
        
    except Exception as e:
        logger.error(f"流程执行失败: {e}")
        raise


if __name__ == "__main__":
    main()