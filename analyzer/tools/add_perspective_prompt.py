#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""添加透视矫正提示词到数据库"""

from src.database import SessionLocal
from src import crud, schemas, models

db = SessionLocal()
try:
    # 透视矫正提示词
    perspective_correction_prompt = """你是一个图像处理助手。请识别这张图片中【试卷】或【答题卡】的四个顶点。

### 任务要求：
1. 找到试卷的最外围边缘的四个角。
2. 按照以下顺序输出归一化坐标 [x, y] (范围 0-1000)：
   - 左上角 (top_left)
   - 右上角 (top_right)
   - 右下角 (bottom_right)
   - 左下角 (bottom_left)
3. 确保坐标的几何正确性：
   - top_left.x < top_right.x
   - bottom_left.x < bottom_right.x
   - top_left.y < bottom_left.y
   - top_right.y < bottom_right.y
   - abs(top_left.y - top_right.y) <= 15  // 顶部边缘应大致水平
   - abs(bottom_left.y - bottom_right.y) <= 15 // 底部边缘应大致水平
   - abs(top_left.x - bottom_left.x) <= 15  // 左侧边缘应大致垂直
   - abs(top_right.x - bottom_right.x) <= 15 // 右侧边缘应大致垂直

### 输出格式：
请仅返回 JSON：
```json
{
  "corners": {
    "top_left": [x, y],
    "top_right": [x, y],
    "bottom_right": [x, y],
    "bottom_left": [x, y]
  },
  "has_perspective_distortion": true/false
}
```

### 重要说明：
- 坐标范围必须是 0-1000，表示归一化坐标
- 例如：如果图片宽度是 1000 像素，那么 x=500 表示在中间位置
- 如果图片宽度是 2000 像素，那么 x=500 表示在 1/4 位置（因为 500/1000 = 0.5 = 50%）"""

    # 检查是否已存在
    existing = db.query(models.Prompt).filter(
        models.Prompt.name == "perspective_correction",
        models.Prompt.version == "v1"
    ).first()
    
    if existing:
        # 更新现有提示词
        existing.content = perspective_correction_prompt
        existing.description = "透视矫正 - 检测试卷四个角点"
        print("✅ 已更新透视矫正提示词")
    else:
        # 创建新提示词
        prompt = schemas.PromptCreate(
            name="perspective_correction",
            version="v1",
            system_prompt="你是一个图像处理助手，专门检测试卷或答题卡的四个顶点。",
            user_prompt_template="请识别这张图片中试卷的四个顶点。",
            content=perspective_correction_prompt
        )
        crud.create_prompt(db, prompt)
        print("✅ 已创建透视矫正提示词")
    
    db.commit()
    print("\n✅ 提示词更新完成！")
    
finally:
    db.close()
