#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目切图模块
基于Pillow实现题目批量切图功能
"""

import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from PIL import Image

# 配置日志
logger = logging.getLogger(__name__)


class QuestionCropper:
    """题目切图器"""
    
    def __init__(self, padding_ratio: float = 0.05):
        """
        初始化切图器
        
        Args:
            padding_ratio: 切图时添加的padding比例，默认5%
        """
        self.padding_ratio = padding_ratio
        
    def normalize_to_pixel(self, coord: float, image_dimension: int, normalized_max: float = 1000) -> int:
        """将归一化坐标转换为像素坐标"""
        return int(coord * image_dimension / normalized_max)
    
    def apply_padding(self, value: int, dimension: int, is_left_top: bool) -> int:
        """应用padding"""
        padding = max(1, int(dimension * self.padding_ratio))
        if is_left_top:
            return max(0, value - padding)  # 向左或向上扩展
        else:
            return min(dimension, value + padding)  # 向右或向下扩展
    
    def crop_single_question(self, image_path: str, coords: List[float], output_path: Optional[str] = None) -> str:
        """
        切分单个题目
        
        Args:
            image_path: 原始图片路径
            coords: 归一化坐标 [ymin, xmin, ymax, xmax]
            output_path: 输出路径，如不指定则自动生成
            
        Returns:
            切分后的图片路径
        """
        if len(coords) != 4:
            raise ValueError("坐标格式错误，应为 [ymin, xmin, ymax, xmax]")
        
        # 打开图片
        image = Image.open(image_path)
        width, height = image.size
        
        # 转换坐标
        ymin, xmin, ymax, xmax = coords
        y1 = self.normalize_to_pixel(ymin, height)
        x1 = self.normalize_to_pixel(xmin, width)
        y2 = self.normalize_to_pixel(ymax, height)
        x2 = self.normalize_to_pixel(xmax, width)
        
        # 应用padding
        x1 = self.apply_padding(x1, width, is_left_top=True)
        y1 = self.apply_padding(y1, height, is_left_top=True)
        x2 = self.apply_padding(x2, width, is_left_top=False)
        y2 = self.apply_padding(y2, height, is_left_top=False)
        
        # 确保坐标有效
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width, x2), min(height, y2)
        
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"无效的坐标范围: ({x1}, {y1}) - ({x2}, {y2})")
        
        # 切图
        cropped = image.crop((x1, y1, x2, y2))
        
        # 生成输出路径
        if output_path is None:
            original_path = Path(image_path)
            output_dir = original_path.parent / "cropped_questions"
            output_dir.mkdir(exist_ok=True)
            output_path = str(output_dir / f"q_{int(ymin)}_{int(xmin)}.jpg")
        
        # 保存图片
        cropped.save(output_path, quality=95)
        logger.info(f"题目切图完成: {output_path} ({cropped.size[0]}x{cropped.size[1]})")
        
        return output_path
    
    def batch_crop_questions(self, image_path: str, questions: List[Dict[str, Any]], 
                           output_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        批量切分题目
        
        Args:
            image_path: 原始图片路径
            questions: 题目列表，每个题目包含bbox和question_number
            output_dir: 输出目录，如不指定则自动生成
            
        Returns:
            包含切图信息的题目列表
        """
        if output_dir is None:
            original_path = Path(image_path)
            output_dir = str(original_path.parent / "cropped_questions")
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        cropped_questions = []
        
        for i, question in enumerate(questions):
            try:
                question_number = question.get('question_number', f'q{i+1}')
                bbox = question.get('bbox')
                
                if not bbox or len(bbox) != 4:
                    logger.warning(f"题目 {question_number} 坐标格式错误，跳过")
                    continue
                
                # 生成输出路径
                output_path = str(Path(output_dir) / f"{question_number}.jpg")
                
                # 切图
                cropped_path = self.crop_single_question(image_path, bbox, output_path)
                
                cropped_questions.append({
                    'question_number': question_number,
                    'original_bbox': bbox,
                    'cropped_image_path': cropped_path,
                    'image_size': Image.open(cropped_path).size
                })
                
            except Exception as e:
                logger.error(f"切分题目 {question_number} 失败: {e}")
                continue
        
        logger.info(f"批量切图完成: 成功 {len(cropped_questions)}/{len(questions)} 道题目")
        return cropped_questions
    
    def validate_cropped_images(self, cropped_questions: List[Dict[str, Any]], 
                              min_size: int = 50) -> List[Dict[str, Any]]:
        """
        验证切图质量
        
        Args:
            cropped_questions: 切图后的题目列表
            min_size: 最小图片尺寸（像素）
            
        Returns:
            验证通过的题目列表
        """
        valid_questions = []
        
        for question in cropped_questions:
            try:
                image_path = question['cropped_image_path']
                width, height = question['image_size']
                
                # 检查文件存在
                if not os.path.exists(image_path):
                    logger.warning(f"图片文件不存在: {image_path}")
                    continue
                
                # 检查图片尺寸
                if width < min_size or height < min_size:
                    logger.warning(f"图片尺寸过小: {image_path} ({width}x{height})")
                    continue
                
                # 检查图片完整性
                with Image.open(image_path) as img:
                    img.verify()  # 验证图片完整性
                
                valid_questions.append(question)
                
            except Exception as e:
                logger.error(f"验证题目图片失败 {question.get('question_number')}: {e}")
                continue
        
        logger.info(f"图片验证完成: 有效 {len(valid_questions)}/{len(cropped_questions)} 张图片")
        return valid_questions