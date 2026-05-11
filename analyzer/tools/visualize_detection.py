#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在原始图片上画出大模型检测的四个角点"""

import cv2
import numpy as np

# 读取原始图片
image_path = "D:\\10739\\Exam-Analysis-RAG\\data\\input\\a.jpg"
img = cv2.imread(image_path)
height, width = img.shape[:2]

print(f"图片尺寸：{width} x {height}")

# qwen-vl-plus 返回的像素坐标
corners = np.array([
    [182, 36],      # top_left
    [1294, 36],     # top_right
    [1370, 825],    # bottom_right
    [208, 825]      # bottom_left
], dtype="float32")

print(f"\n四个角点（像素坐标）：")
print(f"  左上：{corners[0]}")
print(f"  右上：{corners[1]}")
print(f"  右下：{corners[2]}")
print(f"  左下：{corners[3]}")

# 创建一个副本用于绘制
result = img.copy()

# 1. 画四边形的边（绿色粗线）
cv2.line(result, (int(corners[0][0]), int(corners[0][1])), 
         (int(corners[1][0]), int(corners[1][1])), (0, 255, 0), 5)
cv2.line(result, (int(corners[1][0]), int(corners[1][1])), 
         (int(corners[2][0]), int(corners[2][1])), (0, 255, 0), 5)
cv2.line(result, (int(corners[2][0]), int(corners[2][1])), 
         (int(corners[3][0]), int(corners[3][1])), (0, 255, 0), 5)
cv2.line(result, (int(corners[3][0]), int(corners[3][1])), 
         (int(corners[0][0]), int(corners[0][1])), (0, 255, 0), 5)

# 2. 画四个角点（红色圆点）
for i, point in enumerate(corners):
    cv2.circle(result, (int(point[0]), int(point[1])), 15, (0, 0, 255), -1)
    
    # 添加标签
    label = f"{i}: {int(point[0])},{int(point[1])}"
    cv2.putText(result, label, (int(point[0]) + 20, int(point[1]) + 20),
               cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

# 3. 填充四边形区域（半透明蓝色）
overlay = result.copy()
contour = corners.reshape((-1, 1, 2)).astype(np.int32)
cv2.fillPoly(overlay, [contour], (255, 0, 0))
alpha = 0.3
cv2.addWeighted(overlay, alpha, result, 1 - alpha, 0, result)

# 4. 计算并显示面积占比
def polygon_area(points):
    n = len(points)
    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    return abs(area) / 2.0

quad_area = polygon_area(corners)
img_area = width * height
area_percent = quad_area / img_area * 100

# 在图片上显示面积信息
info_text = f"Area: {quad_area:,.0f} px ({area_percent:.2f}%)"
cv2.putText(result, info_text, (50, 50),
           cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)

# 保存结果
temp_dir = os.path.join(os.path.dirname(image_path), '..', '..', 'temp', 'detection_results')
os.makedirs(temp_dir, exist_ok=True)
output_path = os.path.join(temp_dir, f'{os.path.basename(image_path)}.qwen_detection.jpg')
cv2.imwrite(output_path, result)
print(f"\n✅ 结果已保存：{output_path}")

# 同时保存一个不带文字的版本用于对比
clean_result = img.copy()
cv2.line(clean_result, (int(corners[0][0]), int(corners[0][1])), 
         (int(corners[1][0]), int(corners[1][1])), (0, 255, 0), 5)
cv2.line(clean_result, (int(corners[1][0]), int(corners[1][1])), 
         (int(corners[2][0]), int(corners[2][1])), (0, 255, 0), 5)
cv2.line(clean_result, (int(corners[2][0]), int(corners[2][1])), 
         (int(corners[3][0]), int(corners[3][1])), (0, 255, 0), 5)
cv2.line(clean_result, (int(corners[3][0]), int(corners[3][1])), 
         (int(corners[0][0]), int(corners[0][1])), (0, 255, 0), 5)

for i, point in enumerate(corners):
    cv2.circle(clean_result, (int(point[0]), int(point[1])), 15, (0, 0, 255), -1)

clean_output_path = os.path.join(temp_dir, f'{os.path.basename(image_path)}.qwen_detection_clean.jpg')
cv2.imwrite(clean_output_path, clean_result)
print(f"✅ 清洁版已保存：{clean_output_path}")

print(f"\n分析：")
print(f"  图片总面积：{img_area:,} 像素")
print(f"  检测的四边形面积：{quad_area:,.0f} 像素")
print(f"  面积占比：{area_percent:.2f}%")

# 计算中心点
center_x = int(np.mean(corners[:, 0]))
center_y = int(np.mean(corners[:, 1]))
print(f"\n  四边形中心点：[{center_x}, {center_y}]")
print(f"  图片中心点：[{width//2}, {height//2}]")
print(f"  中心偏移：[{abs(center_x - width//2)}, {abs(center_y - height//2)}]")
