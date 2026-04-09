---
name: preprocessor-切图精度优化方案
overview: 基于当前 `preprocessor` 流水线，为题目切图增加“VLM框 + OCR补偿 + 题号锚点 + 边界安全检测”的多层保护后处理，优先保证不漏内容，并尽量保持现有 JSON 结构与下游步骤兼容。
todos:
  - id: verify-impact
    content: 使用 [subagent:code-explorer] 复核坐标消费链与回归样例
    status: completed
  - id: build-page-ocr
    content: 实现页级 OCR 缓存与题号锚点识别模块
    status: completed
    dependencies:
      - verify-impact
  - id: build-crop-refiner
    content: 实现题目框和作答框精修裁剪模块
    status: completed
    dependencies:
      - build-page-ocr
  - id: integrate-pipeline
    content: 改造内容提取与答案切片接入精修流程
    status: completed
    dependencies:
      - build-crop-refiner
  - id: config-and-regression
    content: 补充配置依赖评估脚本并完成 mock 回归验证
    status: completed
    dependencies:
      - integrate-pipeline
---

## 用户需求

### Product Overview

在现有试卷预处理流程中，继续提升题目框和作答框的切图精度。目标以内容完整优先，重点减少题干、题号、半行文字、公式下标、图表边缘、表格线条被裁掉的情况，同时保持现有输出结果和后续处理链可继续使用。

### Core Features

- 对识别出的题目框和作答框进行动态安全外扩，优先保证不漏内容
- 基于整页文本块信息对框进行补偿扩展，尽量把被截断的文字补回来
- 基于题号位置对题目起始边界做结构化修正，避免题号丢失或题干起始被切掉
- 对裁剪边缘做截断风险检测，并在安全范围内自动二次扩边
- 在最终保存前做保守去白边，让切图更完整且观感更稳定

### User Requirements

- 方案应结合当前 preprocessor 工程落地，而不是新增一套脱离现有流程的独立系统
- 优先级明确为：内容完整高于美观，美观高于速度
- 不应破坏现有题目结果、切片路径和后续合并、绘制、完整单元生成等使用方式

## Tech Stack Selection

- 现有工程基础：Python 主流程，OpenCV、NumPy、Pillow 做图像处理，现有 VLM API 负责透视矫正与题目框识别
- 新增能力：页级 OCR 适配层，用于整页文本块和题号锚点检测
- 配置与日志：继续复用 `preprocessor/config/config.json`、`preprocessor/src/utils/config_loader.py`、`EnhancedLogger` 和步骤输出 JSON

## Implementation Approach

用户给出的思路总体合理，且非常贴合当前工程的痛点：现在的核心问题就是 `VLM 题目框 + 固定 padding + 直接裁剪` 过于粗糙。更合适的落地方式不是把它拆成新的十个顶层步骤，而是在现有 `run_content_extraction` 和 `run_answer_extraction` 内部增加“切图精修层”。

高层策略是：先把当前 VLM 返回的 `points` 转成整页矫正图坐标，再在整页坐标系上完成动态外扩、OCR 文本补偿、题号锚点修正、边缘截断检测和保守去白边，最后把结果回写成现有的 `points` 结构并保存切片。这样既能提升精度，也能保持下游兼容。

关键技术决策：

1. 不直接改通用 `crop_with_padding` 默认行为，而是新增独立精修模块。原因是该函数已同时被题目切片和答案切片使用，直接改默认值会扩大影响面。
2. OCR 只做“补偿和锚点”，不直接替代 VLM 框。原因是 OCR 擅长文字边界，VLM 更适合题目整体结构和图表范围，两者互补比“谁大用谁”更稳。
3. 题号锚点优先做“题号匹配修正”，不是简单找最近文字块。优先匹配当前题号文本，再做同列近邻兜底，可降低串题风险。
4. 自动扩边必须设置上限，包括最大迭代次数、最大扩展比例、页边界和相邻题目约束，避免无限扩张或吞并相邻题目。
5. 去白边默认保守且可关闭，只在最终裁剪稳定后执行，避免误伤浅色图表、细线和下标。

性能与可靠性：

- 页级 OCR 按 `source_corrected_image` 一次执行并缓存，避免按题重复 OCR；主要瓶颈在 OCR，本方案通过“整页一次、题目复用”控制开销
- 单页复杂度大致为：OCR 一次，加上题目级 `O(题目数 × 文本块数)` 的补偿判断，以及有限次边缘检测迭代；在题量和文本块规模可控的试卷场景中可接受
- OCR 不可用或失败时，自动降级为“动态外扩 + 边缘截断保护”，保证流水线不中断

## Implementation Notes

- 当前步骤接入点应放在 `preprocessor/src/tasks/task_extract_content.py` 和 `preprocessor/src/tasks/task_extract_answers.py` 内部，保留 `main.py` 现有步骤编号与主流程顺序
- 现有任务通过 `from src.utils import ...` 和 `from ..utils import ...` 走的是 `preprocessor/src/utils/__init__.py` 导出链，新增能力应接入 `preprocessor/src/utils/` 包，不要只改同名的 `preprocessor/src/utils.py`
- 精修逻辑内部必须使用 `crop_area` 完成“part 内归一化坐标”和“整页矫正图像素坐标”之间的双向转换；否则 split 模式下的裁剪精度无法保证
- 兼容性优先：建议覆盖 `points` 为精修后的结果，同时保留 `original_points`、`crop_debug`、`refine_flags` 等调试字段，避免下游消费协议断裂
- 默认不要输出大体量 OCR 原始结果和大量调试图；调试落盘应受配置开关控制，防止 I/O 放大

## Architecture Design

- `main.py` 继续负责配置装载和步骤调用
- `task_extract_content.py` 负责题目纸、混合纸的题目框精修与切片
- `task_extract_answers.py` 复用同一精修框架处理作答框切片，但关闭题号锚点等题目专属逻辑
- `page_ocr` 模块负责整页 OCR、文本块抽取、题号锚点识别和按页缓存
- `crop_refiner` 模块负责坐标换算、动态外扩、文本补偿、锚点修正、边缘风险检测、保守精裁
- `task_draw_output.py`、`task_generate_complete_units.py` 继续消费现有 `points`、`question_slice_path`、`answer_slice_path` 字段，原则上不改协议

## Directory Structure Summary

本次改造以最小主流程改动实现切图精修，核心是新增页级 OCR 与框精修模块，并在内容提取和答案切片步骤中接入，同时保持下游输出兼容。

```text
preprocessor/
├── main.py  # [MODIFY] 继续在主流程中加载配置，并将切图精修相关配置传入步骤 4 和 4.5；不改变现有步骤顺序与产物命名。
├── requirements.txt  # [MODIFY] 增加 OCR 相关依赖或适配层依赖，保留现有图像处理依赖版本约束，避免影响原流水线运行。
├── config/
│   └── config.json  # [MODIFY] 增加切图精修开关、动态外扩比例、OCR 启用项、题号匹配规则、边缘检测阈值、调试输出开关等安全默认值。
├── src/
│   ├── tasks/
│   │   ├── task_extract_content.py  # [MODIFY] 将题目框从“固定 padding 裁剪”升级为“坐标换算 + 精修 + 安全裁剪”；回写 points、original_points、question_slice_path 与调试信息。
│   │   ├── task_extract_answers.py  # [MODIFY] 对作答框复用精修裁剪能力；以内容完整为先，但关闭题号锚点等题目专属规则。
│   │   ├── task_draw_output.py  # [AFFECTED] 验证精修后的 points 仍可按 crop_area 正确绘制；仅在兼容性不足时补最小修复。
│   │   └── task_generate_complete_units.py  # [AFFECTED] 验证精修后的 question_slice_path 和 answer_slice_path 继续可被完整单元生成逻辑直接使用。
│   └── utils/
│       ├── __init__.py  # [MODIFY] 按当前导出方式暴露新 OCR 与精修工具，保持现有 import 风格不变。
│       ├── config_loader.py  # [MODIFY] 新增切图精修配置读取方法和默认值兜底。
│       ├── page_ocr.py  # [NEW] 页级 OCR 适配层。负责整页文本块提取、题号候选识别、按图片缓存分析结果，并向精修模块提供统一数据结构。
│       └── crop_refiner.py  # [NEW] 题目框与作答框精修核心。实现坐标转换、动态外扩、文本块补偿、题号锚点修正、边缘风险扩展、保守去白边和调试元数据生成。
└── scripts/
    └── evaluate_crop_refinement.py  # [NEW] 基于现有 mock_data 跑前后对比，输出切片统计、风险标记和示例图片，便于回归验证。
```

## Agent Extensions

### SubAgent

- **code-explorer**
- Purpose: 在实施前后复核 `task_extract_content.py`、`task_extract_answers.py` 及下游 `points` 消费链，确认所有兼容影响面与 mock case 覆盖范围
- Expected outcome: 得到精确的修改边界、验证清单和回归样例列表，避免遗漏下游兼容问题