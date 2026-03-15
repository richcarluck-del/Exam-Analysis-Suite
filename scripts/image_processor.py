#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像处理模块 - 基于坐标切图
支持归一化坐标 [ymin, xmin, ymax, xmax] 格式，自动添加 1% padding
"""

import os
import logging
from pathlib import Path
from typing import Tuple, List, Optional
from PIL import Image

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 归一化坐标范围
NORMALIZED_MAX = 1000
# Padding 比例
PADDING_RATIO = 0.01


def normalize_to_pixel(
    coord: float,
    image_dimension: int,
    normalized_max: float = NORMALIZED_MAX
) -> int:
    """
    将归一化坐标转换为像素坐标
    
    Args:
        coord: 归一化坐标 [0, 1000]
        image_dimension: 图片对应维度的像素大小
        normalized_max: 归一化坐标的最大值，默认 1000
    
    Returns:
        像素坐标
    """
    return int(coord * image_dimension / normalized_max)


def apply_padding_left_top(value: int, dimension: int, padding_ratio: float = PADDING_RATIO) -> int:
    """
    对左边界或上边界应用 padding，向外扩展（减小坐标值）
    
    Args:
        value: 原始坐标值（左边界 x 或上边界 y）
        dimension: 图片对应维度的总大小
        padding_ratio: padding 比例，默认 1%
    
    Returns:
        调整后的坐标值（向外扩展）
    """
    padding = max(1, int(dimension * padding_ratio))  # 至少1像素
    return max(0, value - padding)  # 向左或向上扩展，确保不小于 0


def apply_padding_right_bottom(value: int, dimension: int, padding_ratio: float = PADDING_RATIO) -> int:
    """
    对右边界或下边界应用 padding，向外扩展（增大坐标值）
    
    Args:
        value: 原始坐标值（右边界 x 或下边界 y）
        dimension: 图片对应维度的总大小
        padding_ratio: padding 比例，默认 1%
    
    Returns:
        调整后的坐标值（向外扩展）
    """
    padding = max(1, int(dimension * padding_ratio))  # 至少1像素
    return min(dimension, value + padding)  # 向右或向下扩展，确保不超过图片大小


def crop_image_by_coords(
    image_path: str,
    coords: List[float],
    output_path: Optional[str] = None,
    add_padding: bool = True
) -> str:
    """
    根据归一化坐标切图
    
    Args:
        image_path: 原始图片路径
        coords: 归一化坐标 [ymin, xmin, ymax, xmax]
        output_path: 输出路径，如果不指定则自动生成
        add_padding: 是否添加 1% padding，默认 True
    
    Returns:
        输出图片路径
    
    Raises:
        ValueError: 坐标格式错误
        FileNotFoundError: 图片文件不存在
    """
    if len(coords) != 4:
        raise ValueError(f"坐标格式错误，需要 4 个值 [ymin, xmin, ymax, xmax]，实际得到 {len(coords)} 个")
    
    ymin, xmin, ymax, xmax = coords
    
    # 验证坐标有效性
    if not (0 <= ymin < ymax <= NORMALIZED_MAX and 0 <= xmin < xmax <= NORMALIZED_MAX):
        raise ValueError(f"坐标值超出有效范围 [0, {NORMALIZED_MAX}]")
    
    # 加载图片
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"图片文件不存在: {image_path}")
    
    image = Image.open(image_path)
    width, height = image.size
    
    logger.info(f"原始图片尺寸: {width}x{height}")
    logger.info(f"归一化坐标: ymin={ymin}, xmin={xmin}, ymax={ymax}, xmax={xmax}")
    
    # 转换为像素坐标
    x1 = normalize_to_pixel(xmin, width)
    y1 = normalize_to_pixel(ymin, height)
    x2 = normalize_to_pixel(xmax, width)
    y2 = normalize_to_pixel(ymax, height)
    
    logger.info(f"像素坐标（未加 padding）: x1={x1}, y1={y1}, x2={x2}, y2={y2}")
    
    # 应用 padding
    if add_padding:
        x1 = apply_padding_left_top(x1, width)
        y1 = apply_padding_left_top(y1, height)
        x2 = apply_padding_right_bottom(x2, width)
        y2 = apply_padding_right_bottom(y2, height)
        logger.info(f"像素坐标（已加 padding）: x1={x1}, y1={y1}, x2={x2}, y2={y2}")
    
    # 确保坐标顺序正确
    left = min(x1, x2)
    top = min(y1, y2)
    right = max(x1, x2)
    bottom = max(y1, y2)
    
    # 切图
    cropped = image.crop((left, top, right, bottom))
    
    # 生成输出路径
    if output_path is None:
        base_dir = Path(__file__).parent.parent / "output"
        base_dir.mkdir(exist_ok=True)
        
        input_name = Path(image_path).stem
        output_path = str(base_dir / f"{input_name}_crop_{int(ymin)}_{int(xmin)}.png")
    
    # 确保输出目录存在
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存图片
    cropped.save(output_path)
    logger.info(f"切图保存至: {output_path}, 尺寸: {cropped.size}")
    
    return output_path


def batch_crop_images(
    image_path: str,
    coords_list: List[List[float]],
    output_dir: Optional[str] = None
) -> List[str]:
    """
    批量切图
    
    Args:
        image_path: 原始图片路径
        coords_list: 多个坐标列表 [[ymin, xmin, ymax, xmax], ...]
        output_dir: 输出目录，如果不指定则使用默认 output 目录
    
    Returns:
        输出图片路径列表
    """
    results = []
    
    if output_dir is None:
        output_dir = str(Path(__file__).parent.parent / "output")
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    for idx, coords in enumerate(coords_list):
        try:
            output_path = os.path.join(output_dir, f"crop_{idx:03d}.png")
            result = crop_image_by_coords(image_path, coords, output_path)
            results.append(result)
        except Exception as e:
            logger.error(f"切图失败 (坐标 {coords}): {e}")
            raise
    
    logger.info(f"批量切图完成，共 {len(results)} 张")
    return results


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) < 3:
        print("用法: python image_processor.py <图片路径> <ymin> <xmin> <ymax> <xmax>")
        sys.exit(1)
    
    image_path = sys.argv[1]
    coords = [float(sys.argv[i]) for i in range(2, 6)]
    
    try:
        output_path = crop_image_by_coords(image_path, coords)
        print(f"切图成功: {output_path}")
    except Exception as e:
        logger.error(f"切图失败: {e}")
        sys.exit(1)
