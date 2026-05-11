# 试卷分析预处理器 (Preprocessor) v0.4.0

## 📋 目录

1. [系统概述](#系统概述)
2. [核心概念](#核心概念)
3. [处理流程](#处理流程)
4. [文件夹结构](#文件夹结构)
5. [文件用途说明](#文件用途说明)
6. [数据字段说明](#数据字段说明)
7. [安装与配置](#安装与配置)
8. [使用方法](#使用方法)
9. [Mock 测试](#mock-测试)
10. [开发指南](#开发指南)

---

## 系统概述

### 功能定位

Preprocessor 是试卷分析系统的前端处理模块，负责：
- 📸 **图片预处理**：透视矫正、图片压缩
- 🏷️ **页面分类**：识别题目纸、答题纸、混合纸
- 📐 **布局分析**：识别页面结构（左/右/整体）
- 📝 **内容提取**：使用 VLM 识别题目、答案区域、涂卡区
- ✂️ **物理切片**：切片题目和答案区域
- 🎯 **涂卡识别**：识别选择题填涂答案
- 🔗 **答案关联**：关联题目与答案
- 🖼️ **生成完整单元图片**：组合题目 + 作答切片（步骤 7）
- 📊 **画框输出**：在原图上标注识别结果（步骤 8）

### 技术栈

- **Python 3.10+**
- **VLM 模型**：通义千问 (qwen3.5-plus)、豆包 (doubao-seed-2.0-pro)
- **数据库**：PostgreSQL（与主项目共享）
- **图像处理**：Pillow, OpenCV

---

## 核心概念

### 1. 试卷类型

| 类型 | 英文 | 说明 | 示例 |
|------|------|------|------|
| **题目纸** | question_paper | 只包含题目，没有答题区域 | 试卷第 1 页 |
| **答题纸** | answer_sheet | 只包含答题区域和涂卡区 | 答题卡 |
| **混合纸** | mixed | 题目和答案在同一页 | 练习册 |

### 2. 页面分区

| 分区 | 说明 | 触发条件 |
|------|------|----------|
| **whole** | 整页 | 页面宽度 ≤ 2100px |
| **left** | 左半页 | 页面宽度 > 2100px，自动分割 |
| **right** | 右半页 | 页面宽度 > 2100px，自动分割 |

### 3. 区域类型

| 区域 | 说明 | 识别字段 |
|------|------|----------|
| **涂卡区** | 选择题填涂区域 | `number: "涂卡区"` 或 `"1-21"` |
| **题目区** | 客观题/主观题题目 | `type: "objective_choice"` 或 `"answer_area"` |
| **答案区** | 主观题书写区域 | `type: "answer_area"` |

### 4. 完整单元 (Complete Unit)

**定义**：一道题目的完整信息包，包含：
- 题目图片（question_slice）
- 答案图片（answer_slice）
- 完整单元组合图（question + answer 拼接）
- 涂卡答案（如果有）

**用途**：后续 RAG 分析的基础数据单元

---

## 处理流程

### 完整流程图

```
输入图片目录
    ↓
[步骤 0] 图片预处理
    - 压缩图片 (长边 ≤ 2000px)
    - 生成索引文件
    ↓
[步骤 1] 透视矫正
    - 检测纸张边缘
    - 矫正倾斜
    - 输出：corrected_images/
    ↓
[步骤 2] 页面分类
    - 识别页面类型 (题目纸/答题纸/混合纸)
    - 识别分区 (whole/left/right)
    - 输出：02_classify_output.json
    ↓
[步骤 3] 布局分析
    - 识别页面结构
    - 检测分割线位置
    - 输出：03_layout_output.json
    ↓
[步骤 4] 内容提取
    - VLM 识别所有区域
    - 生成边界框坐标
    - 物理切片题目区域
    - 输出：04_content_output.json + question_slices/
    ↓
[步骤 4.5] 答案切片
    - 物理切片答案区域
    - 输出：answer_slices/ (更新到 04_content_output.json)
    ↓
[步骤 5] 合并结果
    - 合并所有页面数据
    - 统一题号索引
    - 输出：05_merged_output.json
    ↓
[步骤 6] 涂卡识别
    - 切片涂卡区
    - 专用 VLM 识别填涂答案
    - 关联答案与题目
    - 输出：complete_units.json + answer_card_results.json
    ↓
[步骤 7] 生成完整单元图片
    - 提取题目切片和答题区切片
    - 组合生成完整单元图片
    - 输出：07_complete_units/
    ↓
[步骤 8] 画框输出
    - 在原图上绘制识别框
    - 输出：08_annotated_images/
```

### 各步骤详细说明

#### 步骤 0：图片预处理 (`run_image_preprocessing`)

**输入**：原始图片目录
**输出**：
- `00_preprocess_output.json` - 图片索引文件
- `compressed_images/` - 压缩后的图片

**逻辑**：
```python
for each image in input_dir:
    if image.width > 2000:
        compress(image, max_length=2000)
    generate_index(image_path, page_index)
```

#### 步骤 1：透视矫正 (`run_perspective_correction`)

**输入**：压缩后的图片
**输出**：
- `01_correction_output.json` - 矫正结果
- `corrected_images/` - 矫正后的图片

**逻辑**：
1. 调用 VLM 检测四角坐标
2. 使用 OpenCV 进行透视变换
3. 保存矫正图片

#### 步骤 2：页面分类 (`run_classification`)

**输入**：矫正后的图片
**输出**：`02_classify_output.json`

**识别内容**：
- `page_type`: question_paper / answer_sheet / mixed
- `part_type`: whole / left / right
- `sheet_id`: 试卷唯一标识
- `divider_x`: 左右分割线 x 坐标

#### 步骤 3：布局分析 (`run_layout_analysis`)

**输入**：`02_classify_output.json`
**输出**：`03_layout_output.json`

**功能**：细化页面结构，为内容提取做准备

#### 步骤 4：内容提取 (`run_content_extraction`)

**输入**：`03_layout_output.json`
**输出**：
- `04_content_output.json` - 内容识别结果
- `question_slices/` - 题目切片图片

**逻辑**：
```python
for each part in layout_output:
    prompt = select_prompt(part.page_type)
    vlm_response = call_vlm(part.image_path, prompt)
    
    # 物理切片题目区域
    for question in vlm_response.questions:
        crop = crop_with_padding(image, question.points)
        save_crop(crop, f"question_slices/{sheet_id}/Q{number}.jpg")
        question.question_slice_path = crop_path
```

**关键点**：
- 只对 **题目纸** 和 **混合纸** 切片题目
- **答题纸** 不切片题目（避免重复）
- 使用 `crop_with_padding` 带扩展容错切片

#### 步骤 4.5：答案切片 (`run_answer_extraction`)

**输入**：`04_content_output.json`
**输出**：
- 更新 `04_content_output.json`（添加 `answer_slice_path`）
- `answer_slices/` - 答案切片图片

**逻辑**：
```python
for each part in content_output:
    if part.page_type == 'answer_sheet':
        for answer_area in part.questions:
            crop = crop_with_padding(image, answer_area.points)
            save_crop(crop, f"answer_slices/{sheet_id}/A{number}.jpg")
            answer_area.answer_slice_path = crop_path
```

**重复题号处理**：
- 检测到重复题号时自动添加后缀：`22` → `22`, `22-1`
- 记录 `original_number` 字段用于关联

#### 步骤 5：合并结果 (`run_merge_results`)

**输入**：`04_content_output.json`
**输出**：`05_merged_output.json`

**功能**：
- 合并所有页面的识别结果
- 统一题号索引
- 添加 `sheet_type` 字段

#### 步骤 6：涂卡识别 (`run_answer_card_pipeline`)

**输入**：`05_merged_output.json`
**输出**：
- `complete_units.json` - 完整单元数据
- `answer_card_areas/` - 涂卡区切片
- `answer_card_results.json` - 涂卡识别结果

**子步骤**：

**6.1 提取涂卡区**
```python
for each fragment in merged_results:
    if is_answer_card_area(fragment):  # 严格判断
        crop = crop_answer_card_area(fragment)
        save_crop(crop, f"answer_card_areas/answer_card_{number}.jpg")
```

**6.2 VLM 识别涂卡答案**
```python
answer_dict = call_volcengine(crop_path, prompt="识别填涂答案")
# 返回：{"1": "B", "2": "B", "3": "A", ...}
```

**6.3 关联答案与题目**
```python
for question in all_questions:
    if question.number in answer_dict:
        question.answer = answer_dict[question.number]
        question.answer_source = "answer_card"
```

#### 步骤 7：生成完整单元图片 (`run_generate_complete_units`)

**目标**：为每个完整单元生成独立的组合图片，包含题目切片和作答切片

**输入**：
- `complete_units.json`（步骤 6 输出，完整单元数据）
- `04_content_output.json`（题目坐标信息）
- `corrected_images/`（矫正后的原图）

**输出**：
- `07_complete_units/SET_xxx_SHEET_xxx/CUxxx.jpg`（完整单元图片）
- `07_complete_units/complete_units_summary.json`（汇总信息）

**处理逻辑**：
```python
# 1. 构建坐标查找表（支持同一题号的多条记录）
lookup = build_coordinate_lookup(content_output)
# 题号 -> {question_slice_path, answer_areas: [多页答题区]}

# 2. 遍历完整单元，生成组合图片
for unit_id, unit in complete_units.items():
    if unit.is_mixed_mode:
        # 混合模式：直接使用题目切片
        use_question_slice_directly()
    elif unit.question_type == 'objective_choice':
        # 客观题：题目切片 + 答案标注
        combine_question_with_answer_label()
    elif unit.question_type == 'answer_area':
        # 主观题：题目切片 + 答题区切片（支持跨页多个切片）
        combine_question_with_answer_areas()
```

**三种完整单元类型**：
| 类型 | 说明 | 组合方式 | 示例 |
|------|------|----------|------|
| **客观题（涂卡答案）** | 有涂卡作答 | 题目切片 + 答案标注 | 1-15 题 |
| **主观题（答题区）** | 有手写答题区 | 题目切片 + 答题区切片（支持跨页） | 22-23 题 |
| **混合模式** | 题目和答案在同一页 | 直接使用题目切片 | 练习册题目 |

**主观题跨页处理**：
- 答题区可能分布在多页（如 22 题跨 2 页）
- `build_coordinate_lookup()` 会收集同一题号的所有答题区记录
- 生成完整单元时，将所有答题区切片按顺序拼接

**关键点**：
- 题目切片来自 `question_slices/`（步骤 4 生成）
- 答题区切片来自 `answer_slices/`（步骤 4.5 生成）
- 组合方式：上下拼接（题目在上，答案在下）
- 图片命名：`CU{题号}.jpg`（如 `CU022.jpg`）

#### 步骤 8：画框输出 (`run_draw_output`)

**目标**：在原图上画框标注识别结果，生成可视化输出

**输入**：
- `05_merged_output.json`（合并结果，包含所有区域坐标）
- `corrected_images/`（矫正后的原图）

**输出**：
- `08_annotated_images/`（画框标注图片）

**处理逻辑**：
```python
for each fragment in merged_results:
    image_path = fragment.source_corrected_image
    image = load_image(image_path)
    
    # 绘制边界框
    for question in fragment.vlm_output.questions:
        points = question.points
        draw_polygon(image, points, color=RED)
        draw_label(image, points.top_left, f"Q{question.number}")
    
    save_image(image, f"08_annotated_images/{filename}_annotated.jpg")
```

**标注内容**：
- 题目区域：红色框 + 题号标签
- 答案区域：绿色框 + "A" 标签
- 涂卡区：蓝色框 + "涂卡区" 标签

**用途**：
- 可视化验证识别结果
- 调试和错误分析
- 展示系统识别能力

---

## 文件夹结构

### 工作目录结构

```
workspace/
├── 00_preprocess_output.json          # 图片预处理结果
├── 01_correction_output.json          # 透视矫正结果
├── compressed_images/                 # 压缩后的图片
│   ├── 1.jpg
│   ├── 3.jpg
│   └── a.jpg
├── corrected_images/                  # 矫正后的图片
│   ├── 1_corrected.jpg
│   ├── 3_corrected.jpg
│   └── a_corrected.jpg
├── 02_classify_output.json            # 页面分类结果
├── 03_layout_output.json              # 布局分析结果
├── 04_content_output.json             # 内容提取结果
├── question_slices/                   # 题目切片
│   └── {sheet_id}/
│       ├── Q001.jpg
│       ├── Q002.jpg
│       └── ...
├── answer_slices/                     # 答案切片
│   └── {sheet_id}/
│       ├── A022.jpg
│       ├── A023.jpg
│       └── ...
├── 05_merged_output.json              # 合并结果
├── answer_card_areas/                 # 涂卡区切片
│   ├── answer_card_1-21.jpg
│   └── ...
├── answer_card_results.json           # 涂卡识别结果
├── complete_units.json                # 完整单元数据
├── 07_complete_units/                 # 完整单元图片
│   └── {sheet_id}/
│       ├── CU001.jpg
│       ├── CU022.jpg
│       └── ...
├── 08_annotated_images/               # 画框标注图片
│   ├── 1_annotated.jpg
│   ├── 3_annotated.jpg
│   └── a_annotated.jpg
├── complete_run_log.json              # 完整日志
├── run_summary.json                   # 简化摘要
└── run_log.txt                        # 文本日志
```

### Mock 数据目录结构

```
tests/mock_data/
└── {case_name}/
    ├── 00_preprocess_output.json
    ├── 01_correction_output.json
    ├── 02_classify_output.json
    ├── 03_layout_output.json
    ├── 04_content_output.json
    ├── 05_merged_output.json
    ├── complete_units.json
    ├── compressed_images/
    ├── corrected_images/
    ├── question_slices/
    ├── answer_slices/
    └── ...
```

---

## 文件用途说明

### JSON 文件

| 文件 | 用途 | 关键内容 |
|------|------|----------|
| `00_preprocess_output.json` | 图片索引 | 原始图片路径、压缩图片路径、页码 |
| `01_correction_output.json` | 矫正结果 | 矫正图片路径、四角坐标 |
| `02_classify_output.json` | 页面分类 | page_type, part_type, sheet_id, divider_x |
| `03_layout_output.json` | 布局分析 | 分区信息、裁剪区域 |
| `04_content_output.json` | 内容提取 | 题目/答案区域坐标、切片路径 |
| `05_merged_output.json` | 合并结果 | 所有页面的统一数据 |
| `complete_units.json` | 完整单元 | 题目 + 答案组合数据 |
| `answer_card_results.json` | 涂卡识别 | 题号 - 答案映射 |

### 图片目录

| 目录 | 用途 | 命名规则 |
|------|------|----------|
| `compressed_images/` | 压缩图片 | `{原文件名}.jpg` |
| `corrected_images/` | 矫正图片 | `{原文件名}_corrected.jpg` |
| `question_slices/` | 题目切片 | `Q{题号}.jpg` |
| `answer_slices/` | 答案切片 | `A{题号}.jpg` |
| `answer_card_areas/` | 涂卡区切片 | `answer_card_{题号}.jpg` |
| `07_complete_units/` | 完整单元组合图 | `CU{题号}.jpg` |
| `08_annotated_images/` | 画框标注输出 | `{原文件名}_annotated.jpg` |

### 日志文件

| 文件 | 用途 |
|------|------|
| `complete_run_log.json` | 完整的 JSON 格式日志（包含所有步骤的详细数据） |
| `run_summary.json` | 简化的运行摘要（只包含关键信息） |
| `run_log.txt` | 人类可读的文本日志 |

---

## 数据字段说明

### 02_classify_output.json 结构

```json
[
  {
    "original_image_path": "原始图片路径",
    "source_corrected_image": "矫正图片路径",
    "page_type": "question_paper|answer_sheet|mixed",
    "page_index": 1,
    "sheet_id": "SET_20260323_794E_SHEET_001",
    "sheet_type": "question_paper|answer_sheet|mixed",
    "order": 1,
    "image_path": "分区图片路径",
    "part_type": "whole|left|right",
    "crop_area": [x1, y1, x2, y2],
    "divider_x": 分割线 x 坐标
  }
]
```

### 04_content_output.json 结构

```json
[
  {
    "source_image_path": "原始图片路径",
    "source_corrected_image": "矫正图片路径",
    "part_image_path": "分区图片路径",
    "page_type": "question_paper|answer_sheet|mixed",
    "page_index": 0,
    "part_type": "left|right|whole",
    "sheet_id": "试卷 ID",
    "sheet_type": "试卷类型",
    "vlm_output": {
      "questions": [
        {
          "number": "题号 (如：1, 22, 涂卡区)",
          "type": "objective_choice|answer_area",
          "points": {
            "top_left": [x, y],
            "top_right": [x, y],
            "bottom_right": [x, y],
            "bottom_left": [x, y]
          },
          "description": "区域描述",
          "question_slice_path": "题目切片路径 (步骤 4 生成)",
          "answer_slice_path": "答案切片路径 (步骤 4.5 生成)",
          "source_image_for_crop": "切片来源图片"
        }
      ]
    }
  }
]
```

### 05_merged_output.json 结构

```json
[
  {
    "number": "题号",
    "type": "题目类型",
    "points": {...},
    "description": "描述",
    "question_slice_path": "题目切片路径",
    "answer_slice_path": "答案切片路径",
    "source_image_for_crop": "来源图片",
    "sheet_id": "试卷 ID",
    "sheet_type": "试卷类型",
    "page_index": 页码,
    "part_type": "分区类型",
    "answer": "答案 (涂卡识别后添加)",
    "answer_source": "answer_card|manual"
  }
]
```

### complete_units.json 结构

```json
{
  "Q001": {
    "question_number": "1",
    "question_type": "objective_choice",
    "question_slice_path": "题目切片路径",
    "answer_slice_path": "答案切片路径 (可选)",
    "complete_unit_image_path": "完整单元组合图路径",
    "is_mixed_mode": false,
    "sheet_id": "试卷 ID",
    "answer": "B",
    "answer_source": "answer_card"
  }
}
```

---

## 安装与配置

### 环境要求

- Python 3.10+
- 数据库：PostgreSQL
- 依赖包：见 `requirements.txt`

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository_url>
cd Exam-Analysis-Suite/preprocessor

# 2. 创建虚拟环境
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux/Mac

# 3. 安装依赖
pip install -r requirements.txt

# 4. 初始化数据库
python init_db.py
```

### 配置数据库

```bash
# 添加 API 提供商
python add_provider.py --name dashscope --url https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions

# 添加模型
python add_model.py --provider dashscope --model qwen3.5-plus

# 添加提示词
python add_prompt.py --step extract_content_exam_paper --version v3
```

---

## 使用方法

### 真实运行

> **注意**: 本项目推荐的测试图片输入目录为 `D:\10739\Exam-Analysis-Suite\preprocessor\my_test_images`。

```bash
# 从图片目录开始完整运行
python main.py --input-dir path/to/images --output-dir temp/run_$(date +%Y%m%d_%H%M%S)

# 从指定步骤开始运行
python main.py --input-dir path/to/images --start-step 4 --end-step 7 --output-dir temp/run

# 真实运行特定步骤（其他步骤用 mock）
python main.py --mock-case case_xxx --start-step 4 --end-step 7 --real-steps 4 4.5 6 7
```

### Mock 测试

```bash
# 使用录制的 mock 数据运行
python main.py --mock-case case_1774262585063 --output-dir temp/test_mock

# 从步骤 4 开始真实运行，前面步骤用 mock
python main.py --mock-case case_1774262585063 --start-step 4 --end-step 7 --real-steps 4 4.5 5 6 7

# 使用之前的运行结果作为 mock 源
python main.py --mock-source temp/run_20260323_194147 --start-step 4 --end-step 7 --real-steps 4 4.5 6 7
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `--input-dir` | str | 输入图片目录（真实运行） |
| `--test-case` | str | 测试用例名称 |
| `--mock-case` | str | Mock 数据用例名称 |
| `--mock-source` | str | Mock 数据源目录（可以是之前的 temp 运行目录） |
| `--start-step` | int | 开始步骤（0-7） |
| `--end-step` | int | 结束步骤（0-7） |
| `--real-steps` | float[] | 真实运行的步骤列表（支持小数如 4.5） |
| `--output-dir` | str | 输出目录 |
| `--record-case` | str | 录制为新 mock 用例的名称 |

### Mock 测试原理

**Mock 模式**：使用之前录制的中间结果（JSON + 图片），跳过某些步骤的 VLM 调用，直接加载录制的数据。

**工作流程**：
1. 指定 `--mock-case` 或 `--mock-source`
2. 指定 `--start-step`（从哪一步开始）
3. 程序自动创建新的 temp 输出目录
4. **自动复制前置数据**：
   - 复制 `--start-step` 之前的所有 JSON 文件
   - 复制所有图片目录（corrected_images, question_slices 等）
5. 从指定步骤开始执行

**示例**：
```bash
# 步骤 0-3 用 mock，步骤 4-7 真实运行
python main.py --mock-case case_xxx --start-step 4 --end-step 7 --real-steps 4 4.5 5 6 7
```

**复制的文件**：
- JSON: `00_preprocess_output.json`, `01_correction_output.json`, `02_classify_output.json`, `03_layout_output.json`
- 图片目录：`corrected_images/`, `question_slices/`, `answer_slices/`, 等

---

## 开发指南

### 添加新步骤

1. 在 `src/tasks/` 创建新任务文件
2. 实现任务函数，签名：
   ```python
   def run_new_step(input_path: str, output_path: str, workspace_dir: str, llm_config: dict, logger) -> str:
       # 实现逻辑
       return output_path
   ```
3. 在 `main.py` 的 `PIPELINE_STEPS` 中注册
4. 添加对应的 mock 逻辑（如果需要）

### 修改提示词

提示词存储在数据库中，表名 `llm_prompts`。

```sql
-- 查看提示词
SELECT * FROM llm_prompts WHERE step_name = 'extract_content' AND prompt_version = 'v3';

-- 更新提示词
UPDATE llm_prompts SET prompt_content = '新的提示词内容' WHERE id = xxx;
```

### 调试技巧

**查看日志**：
```bash
# 查看完整日志
cat temp/run_xxx/complete_run_log.json | jq

# 查看简化摘要
cat temp/run_xxx/run_summary.json | jq

# 查看文本日志
cat temp/run_xxx/run_log.txt
```

**Mock 调试**：
```bash
# 只运行步骤 4，使用 mock 数据
python main.py --mock-case case_xxx --start-step 4 --end-step 4 --real-steps 4

# 查看生成的文件
ls -la temp/run_xxx/
```

### 数据关联关系

```
00_preprocess_output.json (图片索引)
    ↓
01_correction_output.json (矫正图片)
    ↓
02_classify_output.json (页面分类)
    ↓
03_layout_output.json (布局分析)
    ↓
04_content_output.json (内容提取)
    ├── question_slices/ (题目切片)
    └── answer_slices/ (答案切片，步骤 4.5 添加)
    ↓
05_merged_output.json (合并所有页面)
    ↓
complete_units.json (完整单元数据，步骤 6)
    └── answer_card_results.json (涂卡答案)
    ↓
07_complete_units/ (完整单元组合图片，步骤 7)
    ↓
08_annotated_images/ (画框标注输出，步骤 8)
```

### 常见问题

**Q: 为什么步骤 4 报错 "TypeError: string indices must be integers"?**

A: 因为输入文件格式不对。步骤 4 期望 `03_layout_output.json` 是列表格式，但可能是字典格式。检查前一步的输出。

**Q: 为什么画框图缺少 a.jpg？**

A: 因为 `05_merged_output.json` 中没有 a.jpg 的数据。检查步骤 4 是否正确处理了答题纸。

**Q: Mock 测试时找不到前置文件？**

A: 确保 `--mock-case` 或 `--mock-source` 指定的目录包含所有需要的文件。程序会自动复制前置数据。

**Q: 如何添加新的页面类型？**

A: 
1. 修改 `task_classify.py` 的提示词
2. 更新 `task_extract_content.py` 的 `prompt_key_map`
3. 添加对应的提示词到数据库

---

## 版本历史

### v0.4.0 (当前版本)

**新功能**：
- ✅ 题目和答案区域物理切片（带扩展容错）
- ✅ 生成完整单元组合图片（步骤 7：题目切片 + 答题区切片）
- ✅ 画框标注输出（步骤 8：可视化识别结果）
- ✅ 更新 complete_units.json 数据结构

**Mock 测试修复**：
- ✅ 自动复制前置数据（JSON + 图片目录）
- ✅ 修复步骤输入路径错误
- ✅ 支持步骤 4.5 的小数编号

**Bug 修复**：
- ✅ 变量名覆盖问题
- ✅ 重复题号处理
- ✅ 涂卡区判断逻辑优化
- ✅ generate_complete_units 参数错误
- ✅ 画框图缺失问题
- ✅ 主观题跨页切片处理

### v0.3.0

- 基础流程打通
- 数据库配置支持

### v0.2

- 初始版本

---

## 贡献者

- 主要开发者列表

---

## 许可证

MIT License
