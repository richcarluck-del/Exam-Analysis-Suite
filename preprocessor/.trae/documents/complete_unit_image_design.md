# 完整单元图片生成产品设计

## 一、背景与目标

### 当前问题
- 步骤6生成的 `complete_units.json` 中，`question_slice_path` 和 `answer_slice_path` 都是 `null`
- 步骤7只是在原图上画框标注，没有生成独立的完整单元图片
- 后续agent需要独立的完整单元图片来分析学生作答

### 目标
增强步骤7，为每个完整单元生成独立的组合图片，包含：
- 题目切片（题目内容区域）
- 作答切片（学生作答区域）
- 或客观题答案选项（选择题）

---

## 二、完整单元类型分析

根据当前数据，完整单元分为以下类型：

### 类型A：客观题（选择题）- 涂卡答案
```
┌─────────────────┐
│   题目切片      │
│  (题目内容)     │
├─────────────────┤
│   答案标注      │
│   答案: B       │
└─────────────────┘
```
- **数据来源**：`answer_source = "answer_card"`
- **答案形式**：A/B/C/D 字母
- **组合方式**：题目切片 + 答案文字标注

### 类型B：主观题 - 答题区
```
┌─────────────────┐
│   题目切片      │
│  (题目内容)     │
├─────────────────┤
│   答题区切片1   │
│  (学生手写)     │
├─────────────────┤
│   答题区切片2   │
│  (学生手写)     │
└─────────────────┘
```
- **数据来源**：`answer_source = "answer_area"`
- **答案形式**：学生手写内容（可能跨页）
- **组合方式**：题目切片 + 答题区切片（上下拼接）

### 类型C：混合模式
```
┌─────────────────┐
│   题目切片      │
│  (含答案区域)   │
└─────────────────┘
```
- **数据来源**：`is_mixed_mode = true`
- **答案形式**：答案已在题目切片旁边
- **组合方式**：直接使用题目切片

---

## 三、数据流设计

### 输入数据
```
complete_units.json (步骤6输出)
├── question_number: 题号
├── question_text: 题目文本
├── question_image: 题目所在原图路径
├── answer: 答案（A/B/C/D 或 null）
├── answer_source: 答案来源（answer_card/answer_area）
├── answer_card_bbox: 涂卡区坐标（客观题）
├── answer_area_images: 答题区图片路径列表（主观题）
├── answer_area_count: 答题区碎片数量
└── sheet_id: 试卷ID
```

### 输出数据
```
07_complete_units/              # 新增：完整单元图片目录
├── SET_xxx_SHEET_001/
│   ├── CU001.jpg  # 题1完整单元
│   ├── CU002.jpg  # 题2完整单元
│   └── ...
├── SET_xxx_SHEET_002/
│   └── ...
└── complete_units_summary.json  # 完整单元汇总

06_final_output/               # 保留：画框标注图片（现有功能）
├── 1_final_output.jpg
├── 3_final_output.jpg
└── a_final_output.jpg
```

---

## 四、步骤规划

### 步骤分配

| 步骤 | 名称 | 功能 | 输出 |
|------|------|------|------|
| 步骤6 | answer_card_recognition | 涂卡识别 + 关联 + 生成完整单元数据 | complete_units.json |
| **步骤7** | **generate_complete_units** | **生成完整单元图片** | **07_complete_units/** |
| 步骤8 | draw_output | 画框标注（保留现有功能） | 08_annotated_images/ |

**说明**：
- 步骤6已经生成了完整单元的**数据**（complete_units.json）
- **步骤7**负责生成完整单元的**图片**（组合切片）
- 步骤8是现有的画框功能，保留不变

### 步骤7输入输出

**输入**：
- `complete_units.json`（步骤6输出）
- `04_content_output.json`（题目坐标信息）
- `corrected_images/`（矫正后的原图）

**输出**：
- `07_complete_units/SET_xxx_SHEET_xxx/CUxxx.jpg`（完整单元图片）
- `07_complete_units/complete_units_summary.json`（汇总信息）

---

## 四、核心算法设计

### 4.1 题目切片提取

**输入**：
- `question_image`: 题目所在原图
- `question_text`: 题目文本（用于定位）
- 步骤4的内容提取结果（包含题目坐标）

**算法**：
1. 从 `04_content_output.json` 中查找该题目的坐标信息
2. 根据坐标从原图中裁剪出题目区域
3. 添加适当padding，确保题目完整

**输出**：题目切片图片

### 4.2 答题区切片提取

**输入**：
- `answer_area_images`: 答题区所在原图路径列表
- `answer_fragments`: 答题区碎片信息（包含坐标）

**算法**：
1. 遍历每个答题区碎片
2. 根据坐标从原图中裁剪出答题区
3. 按题号顺序排列（处理跨页情况）

**输出**：答题区切片图片列表

### 4.3 完整单元图片组合

**算法**：
```python
def generate_complete_unit_image(unit_data):
    if unit_data['is_mixed_mode']:
        # 类型C：直接使用题目切片
        return get_question_slice(unit_data)
    
    elif unit_data['answer_source'] == 'answer_card':
        # 类型A：题目切片 + 答案标注
        question_slice = get_question_slice(unit_data)
        answer = unit_data['answer']
        return combine_question_with_answer_label(question_slice, answer)
    
    elif unit_data['answer_source'] == 'answer_area':
        # 类型B：题目切片 + 答题区切片
        question_slice = get_question_slice(unit_data)
        answer_slices = get_answer_slices(unit_data)
        return combine_question_with_answer_areas(question_slice, answer_slices)
    
    else:
        # 无答案：只返回题目切片
        return get_question_slice(unit_data)
```

---

## 五、实现步骤

### 步骤1：增强数据结构
修改步骤6的输出，增加以下字段：
- `question_bbox`: 题目区域坐标
- `question_slice_path`: 题目切片保存路径
- `answer_slice_paths`: 答题区切片路径列表
- `complete_unit_image_path`: 完整单元图片路径

### 步骤2：实现切片提取
新增函数：
- `extract_question_slice()`: 提取题目切片
- `extract_answer_slices()`: 提取答题区切片

### 步骤3：实现图片组合
新增函数：
- `combine_question_with_answer_label()`: 题目+答案标注
- `combine_question_with_answer_areas()`: 题目+答题区拼接

### 步骤4：修改步骤7
将步骤7从"绘制标注"改为"生成完整单元图片"：
- 保留原图标注功能（可选）
- 新增完整单元图片生成功能

---

## 六、文件结构

```
preprocessor/
├── src/
│   └── tasks/
│       ├── task_answer_card_pipeline.py  # 修改：增加切片路径
│       ├── task_slice_generator.py       # 新增：切片生成模块
│       └── task_draw_output.py           # 修改：增加完整单元生成
└── main.py                               # 修改：调整步骤7逻辑
```

---

## 七、API设计

### 输入接口
```python
def run_generate_complete_units(
    complete_units_path: str,      # complete_units.json 路径
    content_output_path: str,      # 04_content_output.json 路径
    workspace_dir: str,            # 工作目录
    image_path_manager             # 图片路径管理器
) -> Dict:
    """
    生成完整单元图片
    
    Returns:
        {
            "total_units": 17,
            "generated_images": 17,
            "output_dir": "06_final_output/complete_units/",
            "units": {
                "1": {"path": "...", "type": "objective"},
                "22": {"path": "...", "type": "subjective"},
                ...
            }
        }
    """
```

### 输出格式
```json
{
  "total_units": 17,
  "generated_images": 17,
  "output_dir": "06_final_output/complete_units/",
  "units": {
    "1": {
      "path": "06_final_output/complete_units/SET_xxx_SHEET_001/CU001.jpg",
      "type": "objective",
      "has_answer": true,
      "answer": "B"
    },
    "22": {
      "path": "06_final_output/complete_units/SET_xxx_SHEET_002/CU022.jpg",
      "type": "subjective",
      "has_answer": true,
      "answer_area_count": 2
    }
  }
}
```

---

## 八、后续Agent接口

完整单元图片生成后，供后续agent使用：

```python
# 后续agent调用示例
def analyze_student_answer(complete_unit_image_path: str) -> dict:
    """
    分析学生作答
    
    Args:
        complete_unit_image_path: 完整单元图片路径
        
    Returns:
        {
            "question_number": "22",
            "question_type": "subjective",
            "student_answer": "学生手写内容OCR结果",
            "analysis": "作答分析...",
            "score": 8
        }
    """
```

---

## 九、验收标准

1. **功能验收**
   - [ ] 能正确提取题目切片
   - [ ] 能正确提取答题区切片
   - [ ] 能正确组合客观题完整单元
   - [ ] 能正确组合主观题完整单元（含跨页）
   - [ ] 能正确处理混合模式

2. **质量验收**
   - [ ] 切片边界清晰，无截断
   - [ ] 图片质量足够高（供后续OCR使用）
   - [ ] 文件命名规范，易于索引

3. **性能验收**
   - [ ] 单张图片处理时间 < 1秒
   - [ ] 内存占用合理

---

## 十、风险与应对

| 风险 | 影响 | 应对措施 |
|------|------|---------|
| 题目坐标不准确 | 切片不完整 | 增加padding，边界检测 |
| 跨页题目拼接 | 对齐问题 | 统一宽度，智能对齐 |
| 答题区识别遗漏 | 缺少答案 | 标记缺失，人工补充 |
| 图片质量下降 | OCR失败 | 保持原始分辨率 |

---

## 十一、实施计划

| 阶段 | 任务 | 预计时间 |
|------|------|---------|
| 阶段1 | 数据结构增强 | 0.5天 |
| 阶段2 | 切片提取实现 | 1天 |
| 阶段3 | 图片组合实现 | 1天 |
| 阶段4 | 步骤7改造 | 0.5天 |
| 阶段5 | 测试验证 | 0.5天 |
| **总计** | | **3.5天** |
