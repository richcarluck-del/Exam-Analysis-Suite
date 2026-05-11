#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算四边形面积占比"""

import cv2
import numpy as np

# 图片尺寸
width = 4096
height = 2304
img_area = width * height

# qwen-vl-plus 返回的像素坐标
corners = np.array([
    [182, 36],      # top_left
    [1294, 36],     # top_right
    [1370, 825],    # bottom_right
    [208, 825]      # bottom_left
], dtype="float32")

print("="*80)
print("计算四边形面积占比")
print("="*80)

print(f"\n图片尺寸：{width} x {height}")
print(f"图片总面积：{img_area:,} 像素")

print(f"\n四个角点（像素坐标）：")
corner_names = ["top_left", "top_right", "bottom_right", "bottom_left"]
for i, (name, point) in enumerate(zip(corner_names, corners)):
    print(f"  {i}. {name}: [{int(point[0])}, {int(point[1])}]")

# 方法 1：使用鞋带公式计算四边形面积
def polygon_area(points):
    """使用鞋带公式计算多边形面积"""
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0

quad_area = polygon_area(corners)

print(f"\n四边形面积：{quad_area:,.0f} 像素")
print(f"面积占比：{quad_area / img_area * 100:.2f}%")

# 方法 2：使用 OpenCV 的 contourArea 验证
contour_area = cv2.contourArea(corners)
print(f"\nOpenCV contourArea 验证：{contour_area:,.0f} 像素")
print(f"面积占比：{contour_area / img_area * 100:.2f}%")

# 转换为归一化坐标（0-1000）
print(f"\n归一化坐标（0-1000）：")
for i, (name, point) in enumerate(zip(corner_names, corners)):
    x_norm = int(point[0] / width * 1000)
    y_norm = int(point[1] / height * 1000)
    print(f"  {i}. {name}: [{x_norm}, {y_norm}]")

# 计算宽高
top_width = np.sqrt((corners[1][0] - corners[0][0])**2 + (corners[1][1] - corners[0][1])**2)
bottom_width = np.sqrt((corners[3][0] - corners[2][0])**2 + (corners[3][1] - corners[2][1])**2)
left_height = np.sqrt((corners[3][0] - corners[0][0])**2 + (corners[3][1] - corners[0][1])**2)
right_height = np.sqrt((corners[2][0] - corners[1][0])**2 + (corners[2][1] - corners[1][1])**2)

print(f"\n四边形尺寸：")
print(f"  上边宽度：{top_width:.0f} 像素 ({top_width/width*100:.1f}%)")
print(f"  下边宽度：{bottom_width:.0f} 像素 ({bottom_width/width*100:.1f}%)")
print(f"  左边高度：{left_height:.0f} 像素 ({left_height/height*100:.1f}%)")
print(f"  右边高度：{right_height:.0f} 像素 ({right_height/height*100:.1f}%)")

# 计算宽高比
avg_width = (top_width + bottom_width) / 2
avg_height = (left_height + right_height) / 2
print(f"\n平均宽高比：{avg_width/avg_height:.2f} ({avg_width:.0f} x {avg_height:.0f})")

print("\n" + "="*80)
