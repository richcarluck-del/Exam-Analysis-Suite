#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整页画框检测工具

功能：
1. 读取多张试卷图片
2. 透视矫正（可选）
3. 拼接成长图
4. 单次 VLM 识别所有题目和答案
5. 批量裁剪出题图
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import cv2
import numpy as np
from PIL import Image

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import call_api, extract_json
from src.tasks.task_perspective_correction import run_perspective_correction
from src.enhanced_logger import EnhancedLogger
from shared.database import SessionLocal
from shared.llm_step_config import resolve_step_llm_config
from shared.prompt_step_config import resolve_step_prompt, sync_prompt_step_configs


def parse_args():
    parser = argparse.ArgumentParser(description='整页画框检测工具')
    
    # 输入参数
    parser.add_argument('--input-dir', type=str, required=True,
                        help='输入图片目录')
    parser.add_argument('--images', type=str, nargs='+', default=None,
                        help='指定要处理的图片列表（可选）')
    
    # LLM 参数
    parser.add_argument('--provider', type=str,
                        help='全局模型供应商覆盖（未传时优先使用数据库步骤配置）')
    parser.add_argument('--api-key', type=str,
                        help='全局 API Key 覆盖（未传时从数据库解密读取）')
    parser.add_argument('--model', type=str,
                        help='全局模型覆盖（未传时优先使用数据库步骤配置）')
    parser.add_argument('--prompt-version', type=str,
                        help='可选：全局提示词版本覆盖（调试用）。未传时默认按步骤绑定版本或最高版本执行。')
    
    # 拼接参数
    parser.add_argument('--stitch-method', type=str, default='vstack',
                        choices=['vstack', 'hstack', 'smart'],
                        help='拼接方式：垂直/水平/智能')
    parser.add_argument('--overlap', type=int, default=0,
                        help='重叠像素数')
    
    # 识别参数
    parser.add_argument('--detect-questions', action='store_true', default=True,
                        help='是否识别题目区域')
    parser.add_argument('--detect-answers', action='store_true', default=True,
                        help='是否识别答案区域')
    parser.add_argument('--output-format', type=str, default='combined',
                        choices=['individual', 'combined'],
                        help='输出格式：单独/合并')
    
    # 输出参数
    parser.add_argument('--output-dir', type=str, default=None,
                        help='输出目录（可选，默认自动生成）')
    parser.add_argument('--record-case', type=str, default=None,
                        help='录制模式：指定案例名称')
    
    return parser.parse_args()


class WholePageDetection:
    """整页画框检测主类"""
    
    def __init__(self, args):
        self.args = args
        self.start_time = time.time()
        
        # 初始化日志
        self.logger = self._init_logger()
        self.perspective_llm_config, self.question_detection_llm_config = self._resolve_llm_configs()
        self.perspective_prompt_config, self.question_detection_prompt_config = self._resolve_prompt_configs()
        
        # 数据
        self.image_paths = []
        self.corrected_images = []
        self.stitched_image = None
        self.detection_result = None
        
    def _init_logger(self) -> EnhancedLogger:
        """初始化日志器"""
        if self.args.record_case:
            # 录制模式
            workspace_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),  # preprocessor 目录
                'tests', 'mock_data',
                f'whole_page_{self.args.record_case}'
            )
        else:
            # 实时模式
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            workspace_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),  # preprocessor 目录
                'temp',
                f'whole_page_run_{timestamp}'
            )
        
        os.makedirs(workspace_dir, exist_ok=True)
        
        logger = EnhancedLogger(workspace_dir)
        print(f"✅ 整页画框日志已初始化，工作目录：{workspace_dir}")
        
        return logger

    def _resolve_llm_configs(self):
        db = SessionLocal()
        try:
            global_provider_override = self.args.provider or 'dashscope'
            global_model_override = self.args.model or 'qwen3.5-plus'

            perspective_config = resolve_step_llm_config(
                db,
                'preprocessor.whole_page_perspective_correction',
                api_key_override=self.args.api_key,
                fallback_provider_name=global_provider_override,
                fallback_model_name=global_model_override,
            )
            question_detection_config = resolve_step_llm_config(
                db,
                'preprocessor.whole_page_detection',
                api_key_override=self.args.api_key,
                fallback_provider_name=global_provider_override,
                fallback_model_name=global_model_override,
            )
        finally:
            db.close()

        if not question_detection_config:
            raise ValueError('未找到整页画框识别步骤的模型配置。')
        if not perspective_config:
            perspective_config = question_detection_config

        print('✅ 整页画框步骤模型路由已解析：')
        print(
            f"  - 透视矫正：{perspective_config.get('provider_name')}/"
            f"{perspective_config.get('model_name')} ({perspective_config.get('config_source')})"
        )
        print(
            f"  - 整页识别：{question_detection_config.get('provider_name')}/"
            f"{question_detection_config.get('model_name')} ({question_detection_config.get('config_source')})"
        )
        return perspective_config, question_detection_config

    def _resolve_prompt_configs(self):
        db = SessionLocal()
        try:
            sync_prompt_step_configs(db)
            perspective_prompt_config = resolve_step_prompt(
                db,
                'preprocessor.whole_page_perspective_correction',
                version_override=self.args.prompt_version,
            )
            question_detection_prompt_config = resolve_step_prompt(
                db,
                'preprocessor.whole_page_detection',
                version_override=self.args.prompt_version,
            )
        finally:
            db.close()

        if not perspective_prompt_config:
            raise ValueError('未找到整页画框透视矫正提示词配置。')
        if not question_detection_prompt_config:
            raise ValueError('未找到整页画框题目识别提示词配置。')

        print('✅ 整页画框步骤提示词路由已解析：')
        print(
            f"  - 透视矫正：{perspective_prompt_config.get('prompt_key')} / "
            f"v{perspective_prompt_config.get('resolved_version')}"
        )
        print(
            f"  - 整页识别：{question_detection_prompt_config.get('prompt_key')} / "
            f"v{question_detection_prompt_config.get('resolved_version')}"
        )
        return perspective_prompt_config, question_detection_prompt_config
    
    def load_images(self):
        """加载输入图片"""
        print("\n[步骤 1] 读取图片...")
        
        if self.args.images:
            # 使用指定的图片列表
            self.image_paths = self.args.images
        else:
            # 从目录读取所有图片
            image_extensions = ['.jpg', '.jpeg', '.png', '.bmp']
            self.image_paths = []
            for f in os.listdir(self.args.input_dir):
                if any(f.lower().endswith(ext) for ext in image_extensions):
                    self.image_paths.append(os.path.join(self.args.input_dir, f))
        
        if not self.image_paths:
            raise ValueError(f"未找到任何图片：{self.args.input_dir}")
        
        # 排序（确保顺序一致）
        self.image_paths.sort()
        
        print(f"  ✓ 读取到 {len(self.image_paths)} 张图片")
        for i, path in enumerate(self.image_paths):
            print(f"    - 图片 {i+1}: {os.path.basename(path)}")
        
        # 保存到 compressed_images/（使用 ImageCompressor 压缩）
        compressed_dir = os.path.join(self.logger.workspace_dir, 'compressed_images')
        os.makedirs(compressed_dir, exist_ok=True)
        
        # 导入 ImageCompressor
        from image_compressor import ImageCompressor
        
        for path in self.image_paths:
            img_name = os.path.basename(path)
            output_path = os.path.join(compressed_dir, img_name)
            
            # 使用 ImageCompressor 压缩图片
            # 标准模式：2560x1440, quality=92
            compressed_path, info = ImageCompressor.compress_image(
                path,
                output_path=output_path,
                max_width=2560,
                max_height=1440,
                quality=92,
                return_info=True
            )
            
            size_reduction = (1 - info['compressed']['size'] / info['original']['size']) * 100
            print(f"  ✓ 压缩完成：{img_name} - 体积减少 {size_reduction:.1f}%")
        
    def correct_perspective(self):
        """透视矫正"""
        print("\n[步骤 2] 透视矫正...")
        
        corrected_dir = os.path.join(self.logger.workspace_dir, 'corrected_images')
        os.makedirs(corrected_dir, exist_ok=True)
        
        self.corrected_images = []
        
        # 使用压缩后的图片进行透视矫正
        compressed_dir = os.path.join(self.logger.workspace_dir, 'compressed_images')
        compressed_paths = []
        for f in sorted(os.listdir(compressed_dir)):
            if f.lower().endswith(('.jpg', '.jpeg', '.png')):
                compressed_paths.append(os.path.join(compressed_dir, f))
        
        for i, image_path in enumerate(compressed_paths):
            img_name = os.path.basename(image_path)
            print(f"  处理：{img_name}")
            
            try:
                perspective_prompt = self.perspective_prompt_config.get('prompt_text') if self.perspective_prompt_config else None
                if not perspective_prompt:
                    raise ValueError('未找到整页画框透视矫正提示词。')

                # 构建 JSON 文件的输出路径（在 corrected_dir 的父目录中创建临时 JSON 文件）
                json_output_path = os.path.join(self.logger.workspace_dir, f"{os.path.splitext(img_name)[0]}_correction.json")
                
                # 调用透视矫正
                json_path = run_perspective_correction(
                    [image_path],
                    json_output_path,  # 传递 JSON 文件的完整路径
                    prompt=perspective_prompt,  # 使用数据库 v3 版本的提示词
                    api_key=self.perspective_llm_config.get('api_key'),
                    model_name=self.perspective_llm_config.get('model_name'),
                    api_url=self.perspective_llm_config.get('api_url'),
                    logger=self.logger
                )
                
                # 从 JSON 文件中读取矫正后的图片路径
                if json_path and os.path.exists(json_path):
                    try:
                        with open(json_path, 'r', encoding='utf-8') as f:
                            correction_map = json.load(f)
                        
                        if correction_map and len(correction_map) > 0:
                            corrected_path = correction_map[0].get('corrected_image_path')
                            if corrected_path and os.path.exists(corrected_path):
                                self.corrected_images.append(corrected_path)
                                print(f"    ✓ 矫正完成")
                            else:
                                print(f"    ⚠ 矫正失败，使用压缩图")
                                self.corrected_images.append(image_path)
                        else:
                            print(f"    ⚠ JSON 为空，使用压缩图")
                            self.corrected_images.append(image_path)
                    except Exception as e:
                        print(f"    ✗ 读取 JSON 失败：{e}，使用压缩图")
                        self.corrected_images.append(image_path)
                else:
                    print(f"    ⚠ 矫正失败，使用压缩图")
                    self.corrected_images.append(image_path)
                    
            except Exception as e:
                print(f"    ✗ 错误：{e}")
                self.corrected_images.append(image_path)
        
        print(f"  ✓ 完成 {len(self.corrected_images)} 张图片的矫正")
        
        # 调试：打印矫正后的图片路径
        print(f"  矫正后的图片列表:")
        for i, path in enumerate(self.corrected_images):
            exists = "✓" if os.path.exists(path) else "✗"
            print(f"    [{i+1}] {exists} {path}")
    
    def stitch_images(self):
        """图片拼接"""
        print("\n[步骤 3] 图片拼接...")
        
        if not self.corrected_images:
            raise ValueError("没有矫正后的图片")
        
        # 读取所有图片
        images = []
        for path in self.corrected_images:
            img = cv2.imread(path)
            if img is not None:
                images.append(img)
        
        if not images:
            raise ValueError("无法读取任何图片")
        
        # 拼接
        if self.args.stitch_method == 'vstack':
            # 垂直拼接
            self.stitched_image = self._vstack_images(images)
        elif self.args.stitch_method == 'hstack':
            # 水平拼接
            self.stitched_image = self._hstack_images(images)
        else:
            # 智能拼接（默认垂直）
            self.stitched_image = self._vstack_images(images)
        
        # 保存拼接结果
        stitched_dir = os.path.join(self.logger.workspace_dir, '00_stitched_image')
        os.makedirs(stitched_dir, exist_ok=True)
        
        stitched_path = os.path.join(stitched_dir, 'stitched.jpg')
        cv2.imwrite(stitched_path, self.stitched_image)
        
        h, w = self.stitched_image.shape[:2]
        print(f"  ✓ 拼接完成，尺寸：{w}x{h}")
    
    def _vstack_images(self, images: List[np.ndarray]) -> np.ndarray:
        """垂直拼接"""
        # 获取最大宽度
        max_width = max(img.shape[1] for img in images)
        total_height = sum(img.shape[0] for img in images)
        
        # 创建空白画布
        result = np.zeros((total_height, max_width, 3), dtype=np.uint8)
        
        # 垂直拼接
        y_offset = 0
        for img in images:
            h, w = img.shape[:2]
            x_offset = (max_width - w) // 2  # 居中
            
            if self.args.overlap > 0 and y_offset > 0:
                # 重叠区域
                overlap_start = y_offset - self.args.overlap
                result[overlap_start:y_offset] = img[:self.args.overlap]
            
            result[y_offset:y_offset+h, x_offset:x_offset+w] = img
            y_offset += h
        
        return result
    
    def _hstack_images(self, images: List[np.ndarray]) -> np.ndarray:
        """水平拼接"""
        # 获取最大高度
        max_height = max(img.shape[0] for img in images)
        total_width = sum(img.shape[1] for img in images)
        
        # 创建空白画布
        result = np.zeros((max_height, total_width, 3), dtype=np.uint8)
        
        # 水平拼接
        x_offset = 0
        for img in images:
            h, w = img.shape[:2]
            y_offset = (max_height - h) // 2  # 居中
            
            result[y_offset:y_offset+h, x_offset:x_offset+w] = img
            x_offset += w
        
        return result
    
    def detect_questions(self):
        """题目识别（单次 VLM 调用）"""
        print("\n[步骤 4] 题目识别...")
        
        # 直接使用拼接后的图片
        stitched_path = os.path.join(self.logger.workspace_dir, '00_stitched_image', 'stitched.jpg')
        
        # 打印图片信息
        h, w = self.stitched_image.shape[:2]
        stitched_size = os.path.getsize(stitched_path)
        print(f"  拼接图片尺寸：{w}x{h}")
        print(f"  拼接文件大小：{stitched_size/1024:.2f} KB")
        
        prompt = self.question_detection_prompt_config.get('prompt_text') if self.question_detection_prompt_config else None
        if not prompt:
            raise ValueError('未找到整页画框题目识别提示词。')

        # 调用 VLM
        print("  调用 VLM 进行题目识别...")
        start_time = time.time()
        
        response = call_api(
            prompt=prompt,
            image_path=stitched_path,
            api_url=self.question_detection_llm_config.get('api_url'),
            api_key=self.question_detection_llm_config.get('api_key'),
            model_name=self.question_detection_llm_config.get('model_name'),
            logger=self.logger,
            step_name="question_detection"
        )
        
        duration = time.time() - start_time
        print(f"  VLM 响应时间：{duration:.2f}秒")
        
        # 解析 JSON
        try:
            json_str = extract_json(response)
            result = json.loads(json_str)
            self.detection_result = result
            
            if 'questions' in result:
                question_count = len(result['questions'])
                print(f"  ✓ 识别到 {question_count} 道题目")
                
                # 保存到文件
                detection_path = os.path.join(
                    self.logger.workspace_dir,
                    '01_detection_output.json'
                )
                with open(detection_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
                
                print(f"  ✓ 识别到 {question_count} 道题目")
            else:
                print(f"  ✗ 响应格式错误：缺少 questions 字段")
                self.detection_result = {'questions': [], 'error': 'Invalid format'}
                
        except json.JSONDecodeError as e:
            print(f"  ✗ JSON 解析失败：{e}")
            print(f"  原始响应：{response[:500]}")
            self.detection_result = {'questions': [], 'error': str(e)}
        except Exception as e:
            print(f"  ✗ 解析错误：{e}")
            self.detection_result = {'questions': [], 'error': str(e)}
        
        # 保存提示词
        self.logger.save_prompt('question_detection', prompt, stitched_path)
    
    def crop_questions(self):
        """批量裁剪题图"""
        print("\n[步骤 5] 批量裁剪...")
        
        if not self.detection_result or 'questions' not in self.detection_result:
            print("  ✗ 没有识别结果，跳过裁剪")
            return
        
        questions = self.detection_result['questions']
        
        # 创建输出目录
        output_dir = os.path.join(self.logger.workspace_dir, '02_question_crops')
        os.makedirs(output_dir, exist_ok=True)
        
        success_count = 0
        
        for i, q in enumerate(questions):
            number = q.get('number', str(i+1))
            question_bbox = q.get('question_bbox')
            answer_bbox = q.get('answer_bbox')
            
            if not question_bbox:
                print(f"  ⚠ 第{number}题：缺少题目坐标，跳过")
                continue
            
            try:
                if self.args.output_format == 'combined' and answer_bbox:
                    # 合并题目和答案区域
                    combined_bbox = self._merge_bboxes(question_bbox, answer_bbox)
                    crop = self._crop_image(self.stitched_image, combined_bbox)
                else:
                    # 只裁剪题目区域
                    crop = self._crop_image(self.stitched_image, question_bbox)
                
                if crop is not None:
                    # 保存题图
                    output_filename = f'question_{number.zfill(2)}.jpg'
                    output_path = os.path.join(output_dir, output_filename)
                    cv2.imwrite(output_path, crop)
                    success_count += 1
                    print(f"  ✓ 第{number}题 → {output_filename}")
                else:
                    print(f"  ✗ 第{number}题：裁剪失败")
                    
            except Exception as e:
                print(f"  ✗ 第{number}题：错误 {e}")
        
        print(f"\n  完成：成功裁剪 {success_count}/{len(questions)} 道题")
    
    def _merge_bboxes(self, bbox1: List[int], bbox2: List[int]) -> List[int]:
        """合并两个边界框"""
        x1 = min(bbox1[0], bbox2[0])
        y1 = min(bbox1[1], bbox2[1])
        x2 = max(bbox1[2], bbox2[2])
        y2 = max(bbox1[3], bbox2[3])
        return [x1, y1, x2, y2]
    
    def _crop_image(self, image: np.ndarray, bbox: List[int]) -> Optional[np.ndarray]:
        """裁剪图片"""
        try:
            x1, y1, x2, y2 = map(int, bbox)
            
            # 边界检查
            h, w = image.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            if x2 <= x1 or y2 <= y1:
                return None
            
            return image[y1:y2, x1:x2]
            
        except Exception as e:
            print(f"裁剪错误：{e}")
            return None
    
    def save_logs(self):
        """保存日志和摘要"""
        print("\n[步骤 6] 保存日志...")
        
        duration = time.time() - self.start_time
        
        # 生成摘要
        summary = {
            'run_id': os.path.basename(self.logger.workspace_dir),
            'status': 'success',
            'total_questions': len(self.detection_result.get('questions', [])) if self.detection_result else 0,
            'output_dir': '02_question_crops/',
            'stitched_image': '00_stitched_image/stitched.jpg',
            'duration_seconds': round(duration, 2),
            'config': {
                'input_dir': self.args.input_dir,
                'prompt_version': self.args.prompt_version,
                'stitching_method': self.args.stitch_method,
                'overlap_pixels': self.args.overlap,
                'output_format': self.args.output_format
            }
        }
        
        # 保存摘要
        summary_path = os.path.join(self.logger.workspace_dir, 'run_summary.json')
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        # 使用 EnhancedLogger 保存完整日志
        self.logger.save_all_logs()
        
        print(f"  ✓ 日志已保存：{self.logger.workspace_dir}")
    
    def run(self):
        """运行完整流程"""
        print("\n" + "="*80)
        print("整页画框检测工具")
        print("="*80)
        
        try:
            self.load_images()
            self.correct_perspective()
            self.stitch_images()
            self.detect_questions()
            self.crop_questions()
            self.save_logs()
            
            print("\n" + "="*80)
            print(f"✅ 完成！总耗时：{time.time() - self.start_time:.2f}秒")
            print(f"输出目录：{self.logger.workspace_dir}")
            print("="*80)
            
        except Exception as e:
            print(f"\n✗ 错误：{e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)


def main():
    args = parse_args()
    detector = WholePageDetection(args)
    detector.run()


if __name__ == '__main__':
    main()
