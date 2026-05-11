#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""优化四角定位提示词并更新数据库"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 优化后的透视矫正提示词
    optimized_prompt = """你是一个专业的图像处理助手，专门检测试卷或答题卡的四个顶点。

### 核心任务
识别图片中试卷/答题卡的四个角点，并输出**归一化坐标**（0-1000 范围）。

### 重要概念：什么是归一化坐标？
归一化坐标是将图片的宽高都映射到 0-1000 的坐标系中：
- **x 坐标**：表示从左到右的相对位置（0=最左边，1000=最右边）
- **y 坐标**：表示从上到下的相对位置（0=最顶部，1000=最底部）

**举例说明**：
- 如果图片宽度是 2000 像素，那么 x=500 表示在 1/4 位置（500/1000 = 25%）
- 如果图片高度是 1500 像素，那么 y=750 表示在中间位置（750/1000 = 50%）
- 右上角的归一化坐标应该是 [1000, 0] 左右
- 左下角的归一化坐标应该是 [0, 1000] 左右

### 任务步骤
1. **找到试卷边缘**：识别试卷/答题卡的最外围边界
2. **确定四个角点**：
   - 左上角 (top_left)
   - 右上角 (top_right)
   - 右下角 (bottom_right)
   - 左下角 (bottom_left)
3. **输出归一化坐标**：每个点都是 [x, y] 格式，值范围 0-1000

### 几何约束（必须严格遵守）
你的输出必须满足以下几何关系：
- **左右关系**：top_left.x < top_right.x 且 bottom_left.x < bottom_right.x
- **上下关系**：top_left.y < bottom_left.y 且 top_right.y < bottom_right.y
- **顶部水平**：top_left.y 和 top_right.y 应该非常接近（差值 ≤ 15）
- **底部水平**：bottom_left.y 和 bottom_right.y 应该非常接近（差值 ≤ 15）
- **左侧垂直**：top_left.x 和 bottom_left.x 应该比较接近（差值 ≤ 15）
- **右侧垂直**：top_right.x 和 bottom_right.x 应该比较接近（差值 ≤ 15）

### 常见错误示例（请避免）
❌ **错误 1**：使用像素坐标而非归一化坐标
   - 错误：top_right: [1280, 45]（1280 超出了 0-1000 范围）
   - 正确：top_right: [950, 50]（在 0-1000 范围内）

❌ **错误 2**：坐标值超出范围
   - 错误：bottom_right: [1360, 795]（1360 > 1000）
   - 正确：bottom_right: [980, 800]（所有值都在 0-1000 内）

❌ **错误 3**：几何关系错误
   - 错误：top_left.x > top_right.x（左右颠倒）
   - 正确：top_left.x < top_right.x

### 输出格式
请**仅**返回以下 JSON 格式，不要添加任何额外说明：

```json
{
  "corners": {
    "top_left": [x1, y1],
    "top_right": [x2, y2],
    "bottom_right": [x3, y3],
    "bottom_left": [x4, y4]
  },
  "has_perspective_distortion": true/false
}
```

### 输出要求
1. **坐标范围**：所有 x 和 y 值必须在 0-1000 之间
2. **坐标格式**：必须是 [x, y] 格式的整数数组
3. **角点顺序**：必须按照 top_left → top_right → bottom_right → bottom_left 的顺序
4. **透视判断**：如果试卷有明显倾斜，`has_perspective_distortion` 设为 true

### 参考示例
假设试卷在图片中的位置：
- 左上角在图片的 10% 宽度、5% 高度位置
- 右上角在图片的 95% 宽度、8% 高度位置
- 右下角在图片的 98% 宽度、85% 高度位置
- 左下角在图片的 12% 宽度、82% 高度位置

正确的输出应该是：
```json
{
  "corners": {
    "top_left": [100, 50],
    "top_right": [950, 80],
    "bottom_right": [980, 850],
    "bottom_left": [120, 820]
  },
  "has_perspective_distortion": true
}
```"""

    # 检查是否已存在
    existing = db.query(models.Prompt).filter(
        models.Prompt.name == "perspective_correction",
        models.Prompt.version == "v1"
    ).first()
    
    if existing:
        # 更新现有提示词
        existing.content = optimized_prompt
        existing.description = "透视矫正 v2 - 优化版：检测试卷四个角点（归一化坐标 0-1000）"
        existing.system_prompt = "你是一个专业的图像处理助手，专门检测试卷或答题卡的四个顶点，输出归一化坐标（0-1000 范围）。"
        print("✅ 已更新透视矫正提示词（优化版）")
    else:
        # 创建新提示词
        prompt = schemas.PromptCreate(
            name="perspective_correction",
            version="v2",
            system_prompt="你是一个专业的图像处理助手，专门检测试卷或答题卡的四个顶点，输出归一化坐标（0-1000 范围）。",
            user_prompt_template="请识别这张图片中试卷的四个顶点，输出归一化坐标（0-1000 范围）。",
            content=optimized_prompt
        )
        crud.create_prompt(db, prompt)
        print("✅ 已创建透视矫正提示词（优化版 v2）")
    
    db.commit()
    print("\n✅ 提示词优化完成！")
    
    # 显示优化后的提示词摘要
    print("\n" + "="*80)
    print("优化后的提示词特点：")
    print("="*80)
    print("1. ✅ 清晰解释什么是归一化坐标（0-1000 范围）")
    print("2. ✅ 提供具体的坐标转换示例")
    print("3. ✅ 明确说明常见错误及如何避免")
    print("4. ✅ 强调几何约束条件")
    print("5. ✅ 提供正确的参考示例")
    print("6. ✅ 使用对比（错误 vs 正确）加深理解")
    print("="*80)
    
finally:
    db.close()
