"""
图片预处理任务
功能：
1. 检测图片是否包含细小文字
2. 智能压缩图片
3. 返回压缩后的图片路径映射
"""
import os
import json
from pathlib import Path
from PIL import Image
import cv2
import numpy as np
from typing import List, Dict, Optional

# 导入压缩工具
from image_compressor import ImageCompressor


def detect_small_text(image_path: str) -> bool:
    """
    检测图片是否包含细小文字
    
    判断逻辑：
    1. 如果图片分辨率 > 2560×1440，可能包含细小文字
    2. 如果图片 DPI > 300，可能包含细小文字
    3. 如果图片宽度/高度 > 3000，可能包含细小文字
    4. 使用 OpenCV 分析文字区域面积
    """
    # 步骤 1: 快速检查分辨率
    with Image.open(image_path) as img:
        width, height = img.size
        
        # 如果分辨率很低，直接返回 False
        if width < 1920 and height < 1080:
            return False
        
        # 如果分辨率超高，直接返回 True
        if width > 3000 or height > 2000:
            return True
    
    # 步骤 2: 检查 DPI
    try:
        with Image.open(image_path) as img:
            dpi = img.info.get('dpi', (0, 0))
            if isinstance(dpi, tuple) and len(dpi) > 0:
                if dpi[0] > 300 or dpi[1] > 300:
                    return True
    except:
        pass
    
    # 步骤 3: OpenCV 详细分析
    return detect_small_text_by_cv(image_path)


def detect_small_text_by_cv(image_path: str) -> bool:
    """
    使用 OpenCV 检测细小文字
    通过分析文字区域的面积和形状
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return False
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # 二值化
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # 形态学操作，提取文字区域
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        dilated = cv2.dilate(binary, kernel, iterations=2)
        eroded = cv2.erode(dilated, kernel, iterations=1)
        
        # 查找轮廓
        contours, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # 分析轮廓面积
        small_text_count = 0
        total_count = len(contours)
        
        if total_count == 0:
            return False
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 100:  # 面积小于 100 像素，可能是细小文字
                small_text_count += 1
        
        # 如果超过 30% 的文字区域很小，认为是细小文字
        return small_text_count / total_count > 0.3
    except Exception as e:
        print(f"      [Warning] OpenCV 文字检测失败：{e}")
        return False


def should_use_high_resolution(image_path: str) -> bool:
    """
    综合判断是否需要高分辨率模式
    """
    return detect_small_text(image_path)


def compress_single_image(
    image_path: str,
    output_dir: str,
    use_high_res: bool = False,
    quality: int = 90
) -> Dict:
    """
    压缩单张图片 - 优化版本，在保证清晰度的前提下压缩
    
    Args:
        image_path: 原始图片路径
        output_dir: 输出目录
        use_high_res: 是否使用高分辨率模式
        quality: JPEG 质量（默认 90，平衡清晰度和体积）
        
    Returns:
        压缩信息字典
    """
    # 优化配置参数 - 提高分辨率和质量，减少模糊感
    if use_high_res:
        # 高分辨率模式：包含细小文字的图片
        max_width = 3200  # 从 2560 提升到 3200
        max_height = 1800  # 从 1440 提升到 1800
        quality = 98  # 从 95 提升到 98，接近无损
    else:
        # 标准模式：普通图片
        max_width = 2560  # 从 1920 提升到 2560
        max_height = 1440  # 从 1080 提升到 1440
        quality = 92  # 从 85 提升到 92，显著提升质量
    
    # 生成输出路径
    filename = Path(image_path).name
    output_path = os.path.join(output_dir, filename)
    
    # 压缩图片
    compressed_path, info = ImageCompressor.compress_image(
        image_path,
        output_path=output_path,
        max_width=max_width,
        max_height=max_height,
        quality=quality,
        return_info=True
    )
    
    return {
        'original': image_path,
        'compressed': compressed_path,
        'high_res': use_high_res,
        'info': info
    }


def run_image_preprocessing(
    input_dir: str,
    output_path: str,
    api_key: str = None,
    model_name: str = None,
    api_url: str = None
):
    """
    图片预处理主函数
    
    Args:
        input_dir: 输入图片目录
        output_path: 输出 JSON 映射文件路径
        api_key, model_name, api_url: 保留参数（本步骤不需要）
    """
    print(f"  Starting image preprocessing for directory: {input_dir}")
    
    # 创建输出目录
    compressed_dir = os.path.join(os.path.dirname(output_path), 'compressed_images')
    os.makedirs(compressed_dir, exist_ok=True)
    
    # 获取所有图片
    image_files = []
    for f in sorted(os.listdir(input_dir)):
        if f.lower().endswith(('.png', '.jpg', '.jpeg')):
            image_files.append(os.path.join(input_dir, f))
    
    if not image_files:
        print(f"  [Warning] No images found in {input_dir}")
        return output_path
    
    print(f"  Found {len(image_files)} images to preprocess")
    
    # 压缩所有图片
    compression_map = []
    total_original_size = 0
    total_compressed_size = 0
    
    for image_path in image_files:
        filename = os.path.basename(image_path)
        print(f"    Processing: {filename}")
        
        # 检测是否需要高分辨率
        use_high_res = should_use_high_resolution(image_path)
        
        # 压缩图片
        result = compress_single_image(
            image_path,
            compressed_dir,
            use_high_res=use_high_res,
            quality=85 if not use_high_res else 95
        )
        
        compression_map.append(result)
        
        # 统计大小
        total_original_size += result['info']['original']['size']
        total_compressed_size += result['info']['compressed']['size']
        
        # 打印压缩效果
        size_reduction = (1 - result['info']['compressed']['size'] / result['info']['original']['size']) * 100
        print(f"      Original: {result['info']['original']['size'] / 1024:.2f} KB")
        print(f"      Compressed: {result['info']['compressed']['size'] / 1024:.2f} KB")
        print(f"      Reduction: {size_reduction:.1f}%")
        print(f"      High Resolution Mode: {'Yes' if use_high_res else 'No'}")
    
    # 计算总体压缩率
    overall_reduction = (1 - total_compressed_size / total_original_size) * 100 if total_original_size > 0 else 0
    
    print(f"\n  Overall Statistics:")
    print(f"    Total Original Size: {total_original_size / 1024:.2f} KB")
    print(f"    Total Compressed Size: {total_compressed_size / 1024:.2f} KB")
    print(f"    Overall Reduction: {overall_reduction:.1f}%")
    
    # 保存映射关系
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    output_data = {
        'compression_map': [
            {
                'original': item['original'],
                'compressed': item['compressed'],
                'high_res': item['high_res']
            }
            for item in compression_map
        ],
        'statistics': {
            'total_images': len(compression_map),
            'total_original_size': total_original_size,
            'total_compressed_size': total_compressed_size,
            'overall_reduction': overall_reduction
        }
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"  Preprocessing results saved to: {output_path}")
    return output_path


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Run image preprocessing.')
    parser.add_argument('--input-dir', required=True, help='Directory containing the raw images.')
    parser.add_argument('--output', required=True, help='Path to save the output JSON map file.')
    
    args = parser.parse_args()
    
    run_image_preprocessing(
        input_dir=args.input_dir,
        output_path=args.output
    )
