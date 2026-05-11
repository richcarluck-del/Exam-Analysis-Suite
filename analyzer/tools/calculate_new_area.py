#!/usr/bin/env python3
import numpy as np

# 图片尺寸
width = 4096
height = 2304

# 归一化坐标
corners_norm = np.array([
    [180, 60],      # top_left
    [920, 70],      # top_right
    [950, 830],     # bottom_right
    [200, 840]      # bottom_left
], dtype="float32")

# 转换为像素坐标
corners_pixel = np.array([
    [int(corners_norm[i][0] / 1000.0 * width), 
     int(corners_norm[i][1] / 1000.0 * height)]
    for i in range(4)
], dtype="float32")

print("="*80)
print("计算面积占比（使用数据库提示词）")
print("="*80)

print(f"\n图片尺寸：{width} x {height}")
print(f"图片总面积：{width * height:,} 像素")

print(f"\n归一化坐标（0-1000）：")
for i, point in enumerate(corners_norm):
    print(f"  {i}. [{int(point[0])}, {int(point[1])}]")

print(f"\n像素坐标：")
for i, point in enumerate(corners_pixel):
    print(f"  {i}. [{int(point[0])}, {int(point[1])}]")

# 计算面积
def polygon_area(points):
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0

# 归一化坐标的面积占比
area_norm = polygon_area(corners_norm) / (1000 * 1000) * 100
print(f"\n归一化坐标系中的面积占比：{area_norm:.2f}%")

# 像素坐标的面积
quad_area = polygon_area(corners_pixel)
img_area = width * height
area_percent = quad_area / img_area * 100

print(f"\n像素坐标系中的面积：")
print(f"  四边形面积：{quad_area:,.0f} 像素")
print(f"  面积占比：{area_percent:.2f}%")

# 计算中心点
center_x = int(np.mean(corners_pixel[:, 0]))
center_y = int(np.mean(corners_pixel[:, 1]))
print(f"\n中心点：")
print(f"  四边形中心：[{center_x}, {center_y}]")
print(f"  图片中心：[{width//2}, {height//2}]")
print(f"  偏移：[{abs(center_x - width//2)}, {abs(center_y - height//2)}]")

print("\n" + "="*80)
