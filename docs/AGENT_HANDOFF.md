# Agent 交接总览（Exam-Analysis-Suite）

> 目的：让新 agent 在**同一工程目录**内快速建立正确上下文，避免被历史文件/旧脚本误导。

## 1. 事实优先级（必须遵守）

当文档与代码不一致时，按以下优先级判断“真相源”：

1. **运行时代码与配置**（最高优先）
   - `shared/database.py`
   - `alembic/env.py`
   - `run_pipeline.py`
   - `preprocessor/main.py`
   - `analyzer/run.py`
2. **当前开发规格文档**
   - `analyzer/docs/knowledge-point-system-technical-design.md`
3. **模块 README / 其他历史文档**（仅辅助）

---

## 2. 强约束（避免误开发）

- 数据库是 **PostgreSQL-only**，禁止引入 SQLite 回退。
- Schema 变更走 Alembic 增量迁移；禁止以“临时脚本 + 手工改表”代替迁移。
- 不做无关大重构（目录搬迁、批量重命名、全局格式化）。
- 不清理历史文件、产物目录与 `.codebuddy/`，除非任务明确要求。
- `analyzer/tools/` 下存在历史/实验脚本；默认不作为主链路依据。

---

## 3. 新 agent 首轮阅读清单（30 分钟）

### 第 1 轮：建立全局（10 分钟）
- `README.md`
- `analyzer/README.md`
- `preprocessor/README.md`

### 第 2 轮：建立执行主链（10 分钟）
- `run_pipeline.py`
- `shared/database.py`
- `alembic/env.py`

### 第 3 轮：建立当前任务语义（10 分钟）
- `analyzer/docs/knowledge-point-system-technical-design.md`
- 当前任务相关文件（例如：`analyzer/app/question_bank_parser.py`、`preprocessor/src/tasks/task_long_image_classification.py`）

---

## 4. 对外输出协议（每次改动前必须先给）

新 agent 在开始改代码前，先输出以下 5 点：

1. 目标理解（≤ 3 句）
2. 计划改动文件清单
3. 明确不改动范围
4. 验收标准（运行/接口/数据）
5. 风险点与回滚点

---

## 5. 当前主链路摘要

- 预处理入口：`preprocessor/main.py`（步骤 0~9，包含 `export_analysis_bundle`）
- 分析入口：`analyzer/run.py`（读取 bundle：`manifest.json` + `questions.json`）
- 端到端入口：`run_pipeline.py`（先 preprocessor 再 analyzer）
- Web 服务入口：`analyzer/app/main.py`（FastAPI + Celery）
- 共享层：`shared/`（模型、数据库、步骤配置）

---

## 6. 给新 agent 的启动提示词（v2）

```text
你在 d:/10739/Exam-Analysis-Suite 工作，不切换目录。
先按“代码与配置 > 当前技术设计文档 > 其他 README”的优先级理解项目。
必须先读：README.md、analyzer/README.md、preprocessor/README.md、run_pipeline.py、shared/database.py、alembic/env.py、analyzer/docs/knowledge-point-system-technical-design.md。
硬约束：PostgreSQL-only，禁止引入 SQLite 回退；数据库结构变更必须走 Alembic 增量迁移。
开始实现前，先输出：目标理解（3句内）、改动文件清单、不改范围、验收标准、风险与回滚点。
实现时遵循“最小改动 + 可验证 + 不动无关模块”。
```
