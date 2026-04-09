---
name: preprocessor-analyzer-契约与调度设计
overview: 围绕 `preprocessor -> analyzer` 的产品化衔接，形成可落地的中间数据契约与运行调度方案，并明确需要改造的入口、文件格式和兼容未来学生/考试维度字段。
todos:
  - id: draft-contract
    content: 使用 [subagent:code-explorer] 固化 bundle 契约与字段文档
    status: completed
  - id: export-bundle
    content: 实现 preprocessor 导出 manifest.json 与 questions.json
    status: completed
    dependencies:
      - draft-contract
  - id: wire-pipeline
    content: 改造 run_pipeline.py 传递 bundle 目录和业务标识
    status: completed
    dependencies:
      - export-bundle
  - id: analyzer-bundle
    content: 重构 analyzer/run.py 消费 bundle 并生成分析报告
    status: completed
    dependencies:
      - draft-contract
      - wire-pipeline
  - id: verify-regression
    content: 使用 [subagent:code-explorer] 补齐测试与兼容验证
    status: completed
    dependencies:
      - export-bundle
      - analyzer-bundle
---

## User Requirements

- 梳理并确认 `preprocessor` 与 `analyzer` 当前传递一套试卷信息的方式、整体触发运行方式，以及现有链路中的断点。
- 在现状未真正打通的前提下，设计一套可直接开发落地的交接方案，重点明确标准化 `manifest.json` 和 `questions.json` 的字段清单、约束和兼容规则。
- 给出 `run_pipeline.py` 与 `analyzer/run.py` 的具体改造方向，使整套试卷能从预处理结果进入逐题分析，再形成学生学情判断报告。
- 方案需兼顾当前可用产物与未来产品化扩展，预留 `student_id`、`exam_id`、`paper_id` 等业务标识，但不要求当前必须全部有值。
- 本轮重点是产出可指导后续开发的文档和实施方案，结果表现为清晰的目录结构、统一的结构化交接文件和标准分析报告输出，无新增界面改造要求。

## Product Overview

统一一套试卷从切题、取答案、汇总题目，到进入逐题分析和全卷学情输出的标准交接方式。系统对外呈现为一套稳定的运行入口、固定的输出目录和可复用的结构化文件，使后续开发、联调、回归验证都围绕同一份交接契约进行。

## Core Features

- 标准化试卷交接包，统一描述试卷、学生、题目、答案和资源路径
- 统一命令触发链路，支持从总入口串行执行预处理和分析
- 逐题输入契约，支撑后续 RAG 与知识图谱分析按题消费
- 全卷分析输出，区分逐题结果与汇总学情报告
- 兼容现有预处理产物，并为后续业务标识和版本升级预留扩展位

## Tech Stack Selection

- 编排方式：沿用现有 Python 命令行链路，核心入口为 `d:/10739/Exam-Analysis-Suite/run_pipeline.py`
- 预处理模块：沿用 `d:/10739/Exam-Analysis-Suite/preprocessor/main.py` 及现有步骤产物
- 分析模块：沿用 `d:/10739/Exam-Analysis-Suite/analyzer/run.py` 作为 CLI 入口，并复用 `analyzer/app` 中已有的检索与模型能力
- 配置与模型信息：沿用 `d:/10739/Exam-Analysis-Suite/shared/database.py` 和 `d:/10739/Exam-Analysis-Suite/shared/models.py` 中的 SQLite 配置库
- 检索底座：沿用 `d:/10739/Exam-Analysis-Suite/analyzer/app/graph_db.py` 和 `d:/10739/Exam-Analysis-Suite/analyzer/app/vector_db.py`
- 中间传递方式：采用“文件系统存放图片与大对象，JSON 存放结构化契约”，不把试卷图片或大结果塞入数据库

## Implementation Approach

方案核心是把当前 `preprocessor` 已经稳定产出的 `04_content_output.json`、`05_merged_output.json`、`complete_units.json` 重新组织成一份标准交接包，并让 `analyzer/run.py` 改为消费这份交接包，而不是继续依赖当前不存在的 `metadata.json`。这样可以最大化复用现有代码与产物，最小化改动面，同时为未来产品化字段和服务化扩展预留稳定接口。

关键决策如下：

- 以 `complete_units.json` 为题目级主事实来源，以 `05_merged_output.json` 和 `04_content_output.json` 作为补充溯源信息。
- 在 `preprocessor` 末端新增 bundle 导出步骤，生成标准 `manifest.json` 和 `questions.json`，但保留现有所有旧产物，避免破坏当前调试和回归方式。
- `run_pipeline.py` 继续采用子进程串行编排，不改为 HTTP 链路；只有标准交接目录变化，命令流保持直观稳定。
- `analyzer/run.py` 优先读取 bundle；首版可增加对旧目录结构的兼容提示或轻量适配，但不再以 `metadata.json` 作为正式契约。
- 将 bundle 读取、校验、路径解析、逐题分析聚合抽为独立模块，避免逻辑继续堆在 CLI 入口，方便未来被 `analyzer/app/main.py` 复用。

性能与可靠性考虑：

- bundle 生成仅做 JSON 整理与路径引用，时间复杂度为 O(n)，n 为题目数；避免重复复制题图和答案图，降低磁盘占用和 I/O。
- 分析阶段主耗时在逐题检索和模型调用，整体复杂度约为 O(n 乘以 单题检索与推理成本)；首版建议顺序执行保证稳定，后续再加可控并发。
- 对图片路径统一使用相对 bundle 根目录的引用，降低跨目录移动和归档成本。
- 单题失败不应中断整卷，报告层面应输出 `partial_success` 和失败清单，保证可追踪、可复跑。

### 标准交接契约

#### 交接包根目录

建议直接落在现有 `preprocessor` 输出目录根部，不额外创建第二层包装目录。目录中新增以下正式契约文件：

- `manifest.json`
- `questions.json`

同时继续保留并引用现有产物：

- `04_content_output.json`
- `05_merged_output.json`
- `complete_units.json`
- `question_slices/`
- `answer_slices/`
- `complete_unit_images/` 或 `07_complete_units/`

#### manifest.json 建议字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| schema_version | 是 | 交接协议版本，建议从 `1.0` 起步 |
| bundle_id | 是 | 单次试卷交接包唯一标识 |
| run_id | 是 | 本次运行标识，可复用 workspace 时间戳 |
| created_at | 是 | 生成时间，使用统一时间字符串 |
| producer | 是 | 生产者信息，至少包含模块名、输出目录、预处理版本 |
| exam_context | 是 | 试卷上下文对象，字段固定但允许空值 |
| files | 是 | 正式文件索引，记录 `questions.json`、`complete_units.json`、`05_merged_output.json`、`04_content_output.json` 相对路径 |
| assets | 否 | 资源目录索引，记录切图片目录和完整单元图目录 |
| stats | 是 | 题量、已作答数、未作答数、人工复核数等统计 |
| status | 是 | `success`、`partial_success`、`failed` |
| warnings | 否 | 全局警告列表 |


#### manifest.json 中 exam_context 建议字段

- `exam_id`
- `paper_id`
- `student_id`
- `subject`
- `grade`
- `class_id`
- `organization_id`
- `source_mode`，取值可对应 real、test、mock

说明：

- 这些字段当前可以为空，但字段位建议一开始就固定，避免后续破坏兼容。
- 与业务身份相关的字段优先放在 `manifest.json`，不要散落到每题记录中重复写入。

#### questions.json 建议结构

- 顶层为数组
- 按题号稳定排序
- 每条记录代表一题的标准分析输入，路径统一相对 bundle 根目录

#### questions.json 单题字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| question_no | 是 | 题号，保留原始题号文本 |
| question_id | 是 | 题目唯一标识，建议由 `bundle_id` 和题号稳定生成 |
| sheet_id | 否 | 来源试卷页标识 |
| question_type | 否 | 题型，来自已有提取结果 |
| question_text | 否 | 题干文本或描述 |
| student_answer | 否 | 学生答案，可能来自涂卡或答题区 |
| answer_source | 是 | `answer_card`、`answer_area`、`mixed`、`none` |
| answer_status | 是 | `answered`、`unanswered`、`uncertain` |
| question_image_path | 是 | 题目图路径 |
| answer_image_path | 否 | 答题区图路径 |
| complete_unit_image_path | 否 | 完整单元图路径 |
| source_complete_unit_key | 是 | 对应 `complete_units.json` 的来源键 |
| source_merged_number | 否 | 对应 `05_merged_output.json` 的题号键 |
| needs_manual_review | 是 | 是否需要人工复核 |
| confidence | 否 | 置信度对象，预留裁切、关联、识别等子字段 |
| tags | 否 | 预留业务标签和知识点提示位 |


字段约束建议：

- 所有图片路径均使用相对路径，不写绝对路径。
- `question_id` 必须稳定，可重复运行生成相同值，便于缓存和结果比对。
- `needs_manual_review` 的判定可以先基于缺图、题号异常、答案来源不确定等已有事实。
- `confidence` 和 `tags` 首版可为空对象或空数组，但键位应保留。

### 命令流落地

#### 顶层触发

沿用现有 `d:/10739/Exam-Analysis-Suite/run_pipeline.py`，但补充可选业务参数：

- `student_id`
- `exam_id`
- `paper_id`
- `subject`
- `grade`
- `class_id`

#### 预处理触发

`run_pipeline.py` 将这些参数透传给 `d:/10739/Exam-Analysis-Suite/preprocessor/main.py`。
`preprocessor/main.py` 在现有步骤基础上新增 bundle 导出动作，建议发生在 `complete_units.json` 和最终完整单元图片已经稳定之后。

#### 分析触发

`run_pipeline.py` 再调用 `d:/10739/Exam-Analysis-Suite/analyzer/run.py`，传入 bundle 根目录而不是泛化的旧输入目录。
为兼容旧调用方式，可让 `analyzer/run.py` 同时接受：

- `--bundle-dir`
- `--input-dir` 作为兼容别名

#### 分析输出

建议 `analyzer_output` 至少固定生成：

- `question_analyses.json`
- `analysis_report.json`

其中：

- `question_analyses.json` 保存逐题分析结果，便于排错和复核
- `analysis_report.json` 保存学生学情总报告，面向后续产品展示和下游消费

## Implementation Notes

- 复用现有 `preprocessor` 产物，不删改 `05_merged_output.json`、`complete_units.json`、切图片目录，新增 bundle 仅做标准化索引。
- bundle 导出建议新增独立任务文件，不把大段拼装逻辑塞进 `preprocessor/main.py`，降低主入口复杂度。
- `preprocessor/main.py` 现有第 6 步把 `complete_units.json` 作为旁路产物，bundle 导出应在读取最终 `complete_units.json` 后进行，避免拿到中间状态。
- `analyzer/run.py` 不应继续把解析、校验、逐题分析、聚合报告全部写在一个文件里，应下沉为可复用模块。
- 日志中严禁输出解密后的 API Key；错误日志只记录题号、文件名、状态和可执行修复建议。
- 对 bundle 做启动前校验：缺失必需 JSON、路径失效、题图不存在、题号重复时尽早失败；单题分析过程中的失败转为局部错误并写入结果。
- 首版保持顺序执行，控制变更风险；若后续加并发，需限制并发度并保持输出顺序稳定。
- 保持向后兼容：旧调试文件和旧目录结构继续保留，新 analyzer 入口优先读 bundle，必要时给出清晰的兼容提示而不是沉默失败。

## Architecture Design

### 当前可复用结构

- `preprocessor/main.py` 已有稳定的步骤型流水线和工作目录概念
- `task_merge_results.py` 与 `task_answer_card_pipeline.py` 已能提供题目级和答案级事实
- `run_pipeline.py` 已有顶层串行命令编排
- `analyzer/app/main.py`、`tasks.py`、`graph_db.py`、`vector_db.py` 已提供模型配置、知识图谱和向量检索能力

### 目标结构

- `preprocessor` 负责生产标准 bundle，不负责学情判断
- `run_pipeline.py` 负责总编排和参数透传
- `analyzer/run.py` 负责消费 bundle 并驱动逐题分析
- `analyzer/app` 中新增可复用的 bundle 解析和分析聚合模块，供 CLI 和未来接口共用
- `shared` 继续负责模型、提示词、供应商配置，不承接图片和大结果传输

### 推荐数据流

1. 原始试卷图片进入 `preprocessor`
2. `preprocessor` 生成既有中间产物和最终 `complete_units.json`
3. bundle 导出任务生成 `manifest.json` 和 `questions.json`
4. `run_pipeline.py` 将 bundle 根目录传给 `analyzer/run.py`
5. `analyzer/run.py` 校验 bundle，逐题调用检索与推理能力
6. `analyzer` 输出逐题结果和全卷报告

## Directory Structure

### Directory Structure Summary

本次开发以“补齐正式交接契约并打通 CLI 分析链路”为主，优先复用现有工作目录和已有 JSON 产物；新增文件聚焦在 bundle 导出、bundle 读取和分析执行抽象，不引入新的大规模架构层。

```text
d:/10739/Exam-Analysis-Suite/
├── docs/
│   └── preprocessor-analyzer-handoff.md
│       # [NEW] 交接契约与命令流文档。固化 manifest.json、questions.json 字段、兼容策略、运行方式和错误处理约定，作为开发与联调依据。
├── run_pipeline.py
│   # [MODIFY] 顶层编排入口。补充业务标识参数透传，改为显式传递 bundle 目录给 analyzer，并输出更清晰的阶段状态与失败信息。
├── preprocessor/
│   ├── main.py
│   │   # [MODIFY] 在现有步骤链上接入 bundle 导出动作，并接收 student_id、exam_id、paper_id 等可选上下文字段，保持旧产物不变。
│   └── src/
│       └── tasks/
│           └── task_export_analysis_bundle.py
│               # [NEW] 标准交接包导出任务。读取 04_content_output.json、05_merged_output.json、complete_units.json，生成 manifest.json 和 questions.json，并统一相对路径与统计信息。
├── analyzer/
│   ├── run.py
│   │   # [MODIFY] 去除 metadata.json 依赖，改为读取 bundle，执行校验、逐题分析和报告输出；兼容 input-dir 别名。
│   └── app/
│       ├── exam_bundle.py
│       │   # [NEW] bundle 解析与校验模块。负责 manifest 和 questions 读取、路径解析、字段校验、兼容适配和错误归类。
│       └── exam_analysis.py
│           # [NEW] 逐题分析与总报告聚合模块。复用现有图谱、向量检索和模型配置能力，输出 question_analyses.json 与 analysis_report.json。
├── test_preprocessor_bundle_export.py
│   # [NEW] bundle 导出测试。覆盖字段完整性、路径相对化、题号排序、空字段兼容和旧产物引用正确性。
└── test_analyzer_bundle_run.py
    # [NEW] analyzer bundle 运行测试。覆盖缺文件校验、最小 bundle 成功路径、局部失败降级和报告结构稳定性。
```

## Agent Extensions

### SubAgent

- **code-explorer**
- Purpose: 复核 bundle 契约涉及的调用链、输出文件、依赖边界和测试样例来源
- Expected outcome: 形成准确的修改清单、低风险改造范围和可执行回归验证依据