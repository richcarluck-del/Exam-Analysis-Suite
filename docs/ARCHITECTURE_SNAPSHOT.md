# 架构快照（Exam-Analysis-Suite）

> 更新时间：2026-04-09
> 用途：给接手 agent 快速建立模块边界、数据流和开发落点。

## 1. 模块边界

- `preprocessor/`
  - 职责：试卷图像预处理、分类、布局、内容/答案切片、合并、涂卡识别、完整单元生成、分析 bundle 导出。
  - 入口：`preprocessor/main.py`
- `analyzer/`
  - 职责 A（离线）：读取 preprocessor 导出的 bundle 并生成分析结果。
    - 入口：`analyzer/run.py`
  - 职责 B（在线）：FastAPI + Celery 的题库/检索/知识点服务。
    - 入口：`analyzer/app/main.py`
- `shared/`
  - 职责：共享数据库连接、ORM 模型、步骤配置。
  - 关键：`shared/database.py`、`shared/models.py`
- 根目录编排
  - `run_pipeline.py`：端到端串联 preprocessor → analyzer

---

## 2. 关键数据流

## 2.1 端到端离线链路

1. `run_pipeline.py` 调起 `preprocessor/main.py`
2. preprocessor 输出 `preprocessor_output/`（包含 `manifest.json`、`questions.json`）
3. `run_pipeline.py` 再调起 `analyzer/run.py`
4. analyzer 输出 `analysis_report.json`、`question_analyses.json`

## 2.2 preprocessor 步骤链（主干）

- Step 0: `preprocess_images`
- Step 1: `perspective_correction`
- Step 2: `classify` / `long_image_classification`
- Step 3: `analyze_layout`
- Step 4: `extract_content`
- Step 4.5: `extract_answers`
- Step 5: `merge_results`
- Step 6: `answer_card_recognition`
- Step 7: `generate_complete_units`
- Step 8: `draw_output`
- Step 9: `export_analysis_bundle`

---

## 3. 存储与检索拓扑

- **关系库**：PostgreSQL（强制）
  - 入口：`shared/database.py`
  - 迁移：`alembic/env.py`（仅允许 PostgreSQL）
- **图数据库**：Neo4j（图关系）
- **向量/文本检索**：当前配置可见 Qdrant / OpenSearch（由环境变量控制）
- **本地向量库能力**：模块中仍有 Chroma 相关能力与历史内容

> 开发判断原则：是否启用以运行配置为准，不以历史文档为准。

---

## 4. 知识点维度当前开发焦点

当前任务规范在：`analyzer/docs/knowledge-point-system-technical-design.md`

焦点包括：
- 知识点独立领域模型（与题目维度硬隔离）
- 多阶段解析链路（归一化、块切分、抽取、桥接、检索投影、图谱投影）
- 多视图检索（`RetrievalDocument` 多 `view_type`）

建议执行策略：
- 新增能力默认开关关闭
- 表/服务/API/任务编排独立
- 与现有题目链路做“连接”，不做“反向绑死”

---

## 5. 高风险误区（接手必读）

- 用旧脚本或历史文档替代当前主链路判断。
- 在未确认契约前改动 `bundle` 结构（`manifest.json` / `questions.json`）。
- 将知识点能力直接侵入题目主链，导致回归风险。
- 引入 SQLite 兼容逻辑（违反当前工程约束）。
