#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新绘制边界框，将归一化坐标转换为像素坐标"""

import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 读取检测结果
result_path = Path(__file__).parent.parent / "output" / "detection_v2_result.json"
with open(result_path, "r", encoding="utf-8") as f:
    result = json.load(f)

questions = result["questions"]
image_path = Path(__file__).parent.parent / "docs" / "ChemistryExamPaper.jpg"
output_path = Path(__file__).parent.parent / "output" / "detection_v2_result.png"

# 打开图片
image = Image.open(image_path)
width, height = image.size
draw = ImageDraw.Draw(image)

# 字体
try:
    font = ImageFont.truetype("msyh.ttc", 28)
except:
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font = ImageFont.load_default()

# 颜色
colors = [(255,0,0), (0,255,0), (0,0,255), (255,165,0), (128,0,128), (0,128,128)]

print(f"图片尺寸: {width} x {height}")
print(f"归一化坐标 (0-1000) 转换为像素坐标:")

for i, q in enumerate(questions):
    color = colors[i % len(colors)]
    
    # 归一化坐标 (0-1000) 转换为像素坐标
    x1 = int(q["x_min"] * width / 1000)
    y1 = int(q["y_min"] * height / 1000)
    x2 = int(q["x_max"] * width / 1000)
    y2 = int(q["y_max"] * height / 1000)
    
    orig = f"({q['x_min']},{q['y_min']},{q['x_max']},{q['y_max']})"
    pixel = f"({x1},{y1})-({x2},{y2})"
    print(f"  Q{q['number']}: {orig} -> {pixel}")
    
    # 绘制矩形
    draw.rectangle([(x1, y1), (x2, y2)], outline=color, width=3)
    
    # 绘制标签
    label = f"Q{q['number']}"
    label_bbox = draw.textbbox((x1, y1 - 33), label, font=font)
    draw.rectangle(label_bbox, fill=color)
    draw.text((x1, y1 - 33), label, fill=(255,255,255), font=font)

image.save(output_path)
print(f"\n已保存: {output_path}")
