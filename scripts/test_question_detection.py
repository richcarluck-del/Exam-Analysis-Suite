#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目边界检测测试程序
输入：试卷图片
输出：用红框标出每道题边界的图片
"""

import os
import sys
import json
import re
import requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import base64

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vlm_e2e.config import default_config

# ============================================================
# 配置
# ============================================================
NORMALIZED_MAX = 1000  # 归一化坐标最大值
BOX_COLOR = (255, 0, 0)  # 红色
BOX_WIDTH = 3  # 线宽
FONT_SIZE = 24  # 题号字体大小
PADDING_PERCENT = 2  # 边界框向外扩展的百分比（补偿定位误差）


# ============================================================
# 题目检测 Prompt
# ============================================================
DETECTION_PROMPT = """请检测这张试卷图片中每道题目的位置。

这是一张两页并排的试卷照片：
- 左边是第3页，包含选择题16-20
- 右边是第4页，包含第21题

请为每道题目输出一个边界框，使用格式 <box>y1 x1 y2 x2</box>，其中坐标范围是 0-999。

每道题的边界框应该完整包含：题号、题目内容、所有选项或填空。

请按以下格式输出：

第16题的位置是<box>...</box>，这是一道关于...的选择题
第17题的位置是<box>...</box>，这是一道关于...的选择题
第18题的位置是<box>...</box>，这是一道...
第19题的位置是<box>...</box>，这是一道...
第20题的位置是<box>...</box>，这是一道...
第21题的位置是<box>...</box>，这是一道...
"""


def encode_image_to_base64(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_image_mime_type(image_path: str) -> str:
    """获取图片 MIME 类型"""
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp"
    }
    return mime_map.get(ext, "image/jpeg")


def detect_questions(image_path: str) -> dict:
    """
    调用 VLM 检测题目边界
    
    Args:
        image_path: 试卷图片路径
        
    Returns:
        检测结果字典
    """
    print(f"正在检测题目边界: {image_path}")
    
    # 获取配置
    config = default_config
    provider = config.get_provider("dashscope")
    api_key = config.get_api_key("dashscope")
    
    # 编码图片
    base64_image = encode_image_to_base64(image_path)
    mime_type = get_image_mime_type(image_path)
    
    # 构建请求
    payload = {
        "model": provider.default_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": DETECTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4000
    }
    
    # 发送请求
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    print("正在调用 VLM API...")
    response = requests.post(
        provider.base_url,
        headers=headers,
        json=payload,
        timeout=provider.timeout
    )
    response.raise_for_status()
    
    result = response.json()
    content = result["choices"][0]["message"]["content"]
    
    print("API 返回成功，正在解析结果...")
    # 保存原始返回内容到文件（避免 Windows 控制台编码问题）
    raw_output_path = str(Path(__file__).parent.parent / "output" / "api_raw_response.txt")
    Path(raw_output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(raw_output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"原始返回内容已保存到: {raw_output_path}")
    
    # 尝试解析 <box> 格式（Qwen-VL grounding 格式）
    # 注意：Qwen-VL 的 box 格式是 <box>x1 y1 x2 y2</box>
    box_pattern = r'第(\d+)题的位置是<box>(\d+)\s+(\d+)\s+(\d+)\s+(\d+)</box>'
    box_matches = re.findall(box_pattern, content)
    
    if box_matches:
        print(f"检测到 {len(box_matches)} 个 <box> 格式的边界框")
        questions = []
        for match in box_matches:
            q_num, x1, y1, x2, y2 = match  # Qwen-VL 格式是 x1 y1 x2 y2
            questions.append({
                "question_number": q_num,
                "bbox_xyxy": [int(x1), int(y1), int(x2), int(y2)],  # [x1, y1, x2, y2] 格式
                "description": f"第{q_num}题"
            })
        return {
            "questions": questions,
            "page_info": {
                "total_questions": len(questions),
                "layout": "从box格式解析",
                "notes": ""
            }
        }
    
    # 如果没有 box 格式，尝试解析 JSON
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_str = content
    
    try:
        detection_result = json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"JSON 解析失败: {e}")
        print("尝试修复 JSON...")
        start = json_str.find('{')
        end = json_str.rfind('}')
        if start != -1 and end != -1:
            json_str = json_str[start:end+1]
            detection_result = json.loads(json_str)
        else:
            raise
    
    return detection_result


def normalize_to_pixel(coord: float, dimension: int, normalized_max: float = NORMALIZED_MAX) -> int:
    """将归一化坐标转换为像素坐标"""
    return int(coord * dimension / normalized_max)


def apply_padding(x1, y1, x2, y2, width, height, padding_percent=PADDING_PERCENT):
    """
    对边界框应用 padding，向外扩展
    
    Args:
        x1, y1, x2, y2: 原始边界框像素坐标
        width, height: 图片尺寸
        padding_percent: 扩展百分比
    
    Returns:
        扩展后的坐标 (x1, y1, x2, y2)
    """
    pad_x = int(width * padding_percent / 100)
    pad_y = int(height * padding_percent / 100)
    
    x1 = max(0, x1 - pad_x)
    y1 = max(0, y1 - pad_y)
    x2 = min(width, x2 + pad_x)
    y2 = min(height, y2 + pad_y)
    
    return x1, y1, x2, y2


def draw_boxes_on_image(image_path: str, detection_result: dict, output_path: str, add_padding: bool = True) -> str:
    """
    在图片上绘制检测到的题目边界框
    
    Args:
        image_path: 原始图片路径
        detection_result: 检测结果
        output_path: 输出图片路径
        add_padding: 是否添加 padding
        
    Returns:
        输出图片路径
    """
    # 打开图片
    image = Image.open(image_path)
    width, height = image.size
    print(f"图片尺寸: {width} x {height}")
    if add_padding:
        print(f"Padding: {PADDING_PERCENT}%")
    
    # 创建绘图对象
    draw = ImageDraw.Draw(image)
    
    # 尝试加载字体
    try:
        # Windows 字体
        font = ImageFont.truetype("msyh.ttc", FONT_SIZE)
    except:
        try:
            # 通用字体
            font = ImageFont.truetype("arial.ttf", FONT_SIZE)
        except:
            font = ImageFont.load_default()
    
    # 绘制每道题的边界框
    questions = detection_result.get("questions", [])
    print(f"检测到 {len(questions)} 道题目")
    
    for q in questions:
        question_number = q.get("question_number", "?")
        
        # 支持多种格式
        if "bbox_xyxy" in q:
            # Qwen-VL box 格式: [x1, y1, x2, y2]
            x1_norm, y1_norm, x2_norm, y2_norm = q["bbox_xyxy"]
            x1 = normalize_to_pixel(x1_norm, width)
            y1 = normalize_to_pixel(y1_norm, height)
            x2 = normalize_to_pixel(x2_norm, width)
            y2 = normalize_to_pixel(y2_norm, height)
            if add_padding:
                x1, y1, x2, y2 = apply_padding(x1, y1, x2, y2, width, height)
            print(f"  题目 {question_number}: 归一化坐标 (x1={x1_norm}, y1={y1_norm}, x2={x2_norm}, y2={y2_norm}) -> 像素 ({x1}, {y1}) - ({x2}, {y2})")
        elif "bbox" in q:
            bbox = q["bbox"]
            if isinstance(bbox, dict):
                # 对象格式: {"left": x1, "top": y1, "right": x2, "bottom": y2}
                left = bbox.get("left", 0)
                top = bbox.get("top", 0)
                right = bbox.get("right", 0)
                bottom = bbox.get("bottom", 0)
                x1 = normalize_to_pixel(left, width)
                y1 = normalize_to_pixel(top, height)
                x2 = normalize_to_pixel(right, width)
                y2 = normalize_to_pixel(bottom, height)
                if add_padding:
                    x1, y1, x2, y2 = apply_padding(x1, y1, x2, y2, width, height)
                print(f"  题目 {question_number}: 归一化坐标 (left={left}, top={top}, right={right}, bottom={bottom}) -> 像素 ({x1}, {y1}) - ({x2}, {y2})")
            elif isinstance(bbox, list) and len(bbox) == 4:
                # 数组格式: [ymin, xmin, ymax, xmax]
                ymin, xmin, ymax, xmax = bbox
                x1 = normalize_to_pixel(xmin, width)
                y1 = normalize_to_pixel(ymin, height)
                x2 = normalize_to_pixel(xmax, width)
                y2 = normalize_to_pixel(ymax, height)
                if add_padding:
                    x1, y1, x2, y2 = apply_padding(x1, y1, x2, y2, width, height)
                print(f"  题目 {question_number}: 归一化坐标 [{ymin}, {xmin}, {ymax}, {xmax}] -> 像素 ({x1}, {y1}) - ({x2}, {y2})")
            else:
                print(f"  题目 {question_number}: 坐标格式错误 {bbox}")
                continue
        else:
            print(f"  题目 {question_number}: 缺少坐标信息")
            continue
        
        # 绘制矩形框
        draw.rectangle(
            [(x1, y1), (x2, y2)],
            outline=BOX_COLOR,
            width=BOX_WIDTH
        )
        
        # 绘制题号标签（在框的左上角）
        label = f"Q{question_number}"
        # 绘制标签背景
        label_bbox = draw.textbbox((x1, y1 - FONT_SIZE - 5), label, font=font)
        draw.rectangle(label_bbox, fill=BOX_COLOR)
        # 绘制标签文字
        draw.text((x1, y1 - FONT_SIZE - 5), label, fill=(255, 255, 255), font=font)
    
    # 保存图片
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    image.save(output_path)
    print(f"\n标注结果已保存到: {output_path}")
    
    return output_path


def main():
    """主函数"""
    # 默认图片路径
    default_image = str(Path(__file__).parent.parent / "docs" / "ChemistryExamPaper.jpg")
    
    # 从命令行参数获取图片路径
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
    else:
        image_path = default_image
    
    # 检查图片是否存在
    if not os.path.exists(image_path):
        print(f"错误: 图片文件不存在: {image_path}")
        sys.exit(1)
    
    # 设置输出路径
    output_dir = Path(__file__).parent.parent / "output"
    output_path = str(output_dir / "detection_result.png")
    
    # 检测结果保存路径
    json_output_path = str(output_dir / "detection_result.json")
    
    try:
        # 1. 检测题目边界
        detection_result = detect_questions(image_path)
        
        # 保存检测结果
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(detection_result, f, ensure_ascii=False, indent=2)
        print(f"检测结果 JSON 已保存到: {json_output_path}")
        
        # 2. 在图片上绘制边界框
        draw_boxes_on_image(image_path, detection_result, output_path)
        
        # 3. 打印摘要
        print("\n" + "=" * 50)
        print("检测摘要")
        print("=" * 50)
        page_info = detection_result.get("page_info", {})
        print(f"总题目数: {page_info.get('total_questions', len(detection_result.get('questions', [])))}")
        print(f"页面布局: {page_info.get('layout', '未知')}")
        if page_info.get('notes'):
            print(f"备注: {page_info.get('notes')}")
        
        print("\n题目列表:")
        for q in detection_result.get("questions", []):
            # 处理可能的编码问题
            desc = q.get('description', '').encode('gbk', errors='replace').decode('gbk')
            print(f"  - 第{q.get('question_number', '?')}题: {desc}")
        
        print(f"\n请查看输出图片: {output_path}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
