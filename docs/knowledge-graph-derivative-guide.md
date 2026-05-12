# 知识图谱层 & 衍生层 运行手册

本指南说明：**如何打开图谱层与衍生层 / 打开后系统到底做什么 / 服务的业务场景**。配套代码位于：

- 后端：`analyzer/app/knowledge_graph_projection.py`、`analyzer/app/knowledge_derivative.py`
- API：`preprocessor/preprocessor_test_ui/knowledge_point_admin_api.py`
- 前端：`preprocessor/preprocessor_test_ui/frontend/src/KnowledgeGraphDerivativePanel.jsx`，并挂载到「知识点管理」页的 **图谱 / 衍生层** 两个 tab

两层都**默认关闭**，不打开不影响原有摄入与 RAG 流程；开启后是**增量叠加**，可以任意时间回滚。

---

## 1. 先打开开关（`.env`）

```env
# 图谱层：摄入 DOCX 后自动把业务关系投影到 entity_graph_edges
KNOWLEDGE_GRAPH_ENABLED=true

# 衍生层：允许调用 LLM 生成衍生内容
KNOWLEDGE_DERIVATIVE_ENABLED=true

# 衍生内容只有在审核通过（approved）且 RAG 开启时才进入检索
KNOWLEDGE_RAG_ENABLED=true
```

改完后**重启** `preprocessor_test_ui`（管理后台进程）。

> LLM / 提示词都走数据库驱动：`analyzer.knowledge_derivative_generation` 步骤和 `analyzer.knowledge_derivative.default` 提示词在首次调用时会自动落库种子（或由 `sync_llm_step_configs / sync_prompt_step_configs` 预先同步）。如需替换模型或 Prompt，直接在「LLM 配置 / 提示词管理」里改，不用动代码。

---

## 2. 图谱层：打开后系统做什么

### 2.1 触发方式

- **自动**：每次 DOCX 摄入成功后（`_ingest_docx_topic` 结尾），若 `KNOWLEDGE_GRAPH_ENABLED=true`，会调用 `knowledge_graph_projection.project_package(db, package_id)`，把本次摄入相关的边幂等地写入 / 覆盖到 `entity_graph_edges`。
- **手动**：管理后台「图谱」tab：
  - *全量投影*：遍历所有 `KnowledgePackage`，一次性把存量业务关系投影进图表（首次启用推荐做一次）。
  - *按作用域*：按 `KnowledgePackage.id` 或 `KnowledgePoint.id` 局部重投影。
- **API**：
  - `POST /api/knowledge-admin/graph/projection/all`
  - `POST /api/knowledge-admin/graph/projection/package/{package_id}`
  - `POST /api/knowledge-admin/graph/projection/knowledge-point/{knowledge_point_id}`
  - `GET  /api/knowledge-admin/graph/summary`
  - `GET  /api/knowledge-admin/graph/edges?package_id=...&knowledge_point_id=...`

### 2.2 它到底写了什么

`entity_graph_edges` 的一行代表一条有向关系，**不替换业务表**，只把分散在 6 张业务表中的关联抽出来统一编号。`source_origin` 固定为 `business_projection`，便于未来与 LLM 抽边的结果（`source_origin=llm_extraction`）共存。

| 源表 | 投影出的边 | 典型用途 |
|---|---|---|
| `KnowledgeBlock` | `knowledge_point` **contains_block** `knowledge_block` | 列出某知识点下所有说明块 |
| `KnowledgeAtom` | `knowledge_block` **contains_atom** `knowledge_atom` | 定义/性质/公式粒度检索 |
| `KnowledgePackagePoint` | `knowledge_package` **covers_point** `knowledge_point` | 专题包覆盖面统计 |
| `KnowledgePackageQuestion` | `knowledge_package` **includes_question** `question` | 按包取题 |
| `KnowledgeQuestionLink`（relevance≥强阈） | `question` **assesses_point_strong** `knowledge_point` | 错题 → 主考点反查 |
| `KnowledgeQuestionLink`（相关但未到强） | `question` **assesses_point_related** `knowledge_point` | 相关考点 / 扩展推荐 |
| `KnowledgePointRelation` | `knowledge_point` **relates_strong / relates_weak** `knowledge_point` | 前置图 / 易混图 |

写入用 `(source_id, target_id, relation_type, source_origin)` 作唯一键，先 `DELETE` 对应作用域，再 `INSERT`，**幂等**。

### 2.3 服务的业务场景

| 场景 | 怎么用图谱层 |
|---|---|
| 家长 / 学生画像 | 学生错 Q → `assesses_point_strong` → 得到薄弱点 → `relates_weak` 向上取前置点 → 针对性推荐 |
| 命题 / 教师 | 一组知识点 → `covers_point` 反查包含它们的所有专题包与题目，评估覆盖度 |
| 商业题库的打标质检 | 比较 `business_projection` 与 `llm_extraction` 的边集合，找"模型认为有关联但业务未登记"或"业务登记但模型不认可"的差异 |
| GraphRAG | 将该表作为图检索子图的输入（边的 `weight_score / confidence` 已归一） |
| 分析报告 | "错这道题的人，70% 同时错下面两个知识点" —— 通过图上二跳查询得出 |

### 2.4 验证

1. `.env` 打开 `KNOWLEDGE_GRAPH_ENABLED=true` 并重启；
2. 后台 *图谱* tab → *全量投影*；
3. 摘要卡片应显示 `总数 > 0`，分布表包含 `contains_block / covers_point / assesses_point_strong` 等；
4. 输入某个 `KnowledgePackage.id` → *加载边列表*，应看到该包相关的 5～数百条边；
5. 再摄入一份新的 DOCX，观察进度日志里出现 `知识图谱投影：... inserted=X deleted=Y`。

---

## 3. 衍生层：打开后系统做什么

### 3.1 触发方式

衍生层**不会自动跑**（生成成本高，需要人工审核）。只能手动触发：

- **前端**：*衍生层* tab → 选"作用域 / 类型 / 受众" → *生成*。
- **API**：
  - `POST /api/knowledge-admin/derivatives/generate`
    body: `{ "knowledge_point_id": 123, "derivative_types": [...], "target_audiences": [...] }`
    或 `{ "package_id": 45, ... }`
  - `GET  /api/knowledge-admin/derivatives?review_status=draft&...`
  - `POST /api/knowledge-admin/derivatives/{id}/review` body `{"review_status":"approved"}`
  - `POST /api/knowledge-admin/derivatives/{id}/retry`
  - `DELETE /api/knowledge-admin/derivatives/{id}`

### 3.2 它到底做什么

一次生成的完整链路：

1. `build_source_snapshot(db, point_id)` 收集该知识点的 **精炼原文快照**：
   - `knowledge_points.content` 的核心字段（定义、公式、考点）
   - 最多 N 个高优先级 `KnowledgeBlock` 的 `text_content`（含表、图 alt）
   - 关键 `KnowledgeAtom`（definition / formula / property / example）
2. 按 `derivative_types × target_audiences` 笛卡尔积调用 `analyzer.knowledge_derivative_generation`：
   - Prompt 通过 `shared/prompt_step_config.py` 的 `analyzer.knowledge_derivative.default` 注入，要求模型返回严格 JSON：
     ```json
     {"title":"...","summary":"...","bullets":["..."],"body":"...","notes":"...",
      "quality":{"groundedness":0.x,"coverage":0.x}}
     ```
3. 解析 → `_upsert_derivative` 写入/更新 `knowledge_derivatives`：
   - `review_status=draft`（初次生成 / retry）
   - 存 `source_snapshot_hash`，便于后续变更检测
4. `set_review_status(id, "approved")` 时：
   - 若 `KNOWLEDGE_RAG_ENABLED=true`：`_sync_derivative_retrieval` 会把 `title+summary+bullets+body` 组装成 `RetrievalDocument`（`source_type='derivative'`），由现有 embedder 补向量，自动纳入 RAG 语料；
   - `rejected` / `delete` 时同步从 `RetrievalDocument` 移除。

### 3.3 衍生类型与受众

| type | 典型产物 | 面向 |
|---|---|---|
| `concept_explainer` | 通俗化讲解（打比方、类比） | 学生、家长 |
| `exam_cheatsheet` | 考点速记卡（公式 / 易漏条件） | 学生、教师 |
| `common_pitfalls` | 易错点 / 常见陷阱 | 学生 |
| `comparison` | 易混知识点对比表 | 学生、教师 |
| `memory_tip` | 记忆口诀 / 口令 | 学生、家长 |

每条记录都绑定 `(knowledge_point_id, derivative_type, target_audience)` 唯一键；同一组合再次"生成"等价于 `retry`（覆盖 + 回到 draft）。

### 3.4 服务的业务场景

| 场景 | 怎么用衍生层 |
|---|---|
| 家长报告 | 把 `concept_explainer + parent` 的条目直接贴到报告里，模型讲给家长听 |
| 自主复习 | `exam_cheatsheet + student` → APP 的"考前速记卡"列表 |
| 题型教学 | `common_pitfalls + student` + 错题 → "这道题的典型错误" 个性化提示 |
| 教师备课 | `comparison / cheatsheet + teacher` 作为讲义草稿 |
| 高质量 RAG | 原文块通常晦涩；衍生层 approved 后进入 RAG 后，问答更贴近受众语言，groundedness 与 coverage 指标也写在记录里用于挑选 |

### 3.5 为什么要"审核后才进 RAG"

模型生成有幻觉风险，直接进检索语料会污染答题。因此：

- 生成 → `draft`（只在管理台可见）
- 人工/未来的自动校验 → `approved` / `rejected`
- 只有 `approved` 才调 `RetrievalDocument`；被 `rejected` 或 `delete` 时**立即**从 RAG 撤回。

### 3.6 验证

1. `.env` 打开 `KNOWLEDGE_DERIVATIVE_ENABLED=true`（推荐同时 `KNOWLEDGE_RAG_ENABLED=true`）并重启；
2. *衍生层* tab → 作用域"知识点" + 某个 `KnowledgePoint.id` → 选 `concept_explainer`、`exam_cheatsheet`，受众 `student` → *生成*；
3. 列表应出现新增记录，`review_status=draft`，能展开看 `title / bullets / body`；
4. 点 *approve* → 消息里出现 `检索：indexed`（表示已进 RAG）；`RetrievalDocument` 表会多出一行 `source_type='derivative'`；
5. 点 *reject* 或 *del* → `检索：removed`。

---

## 4. 组合用：图谱 × 衍生 × RAG

一次完整的"从 DOCX 到家长报告"路径：

1. 摄入 DOCX → 生成 `knowledge_points / blocks / atoms / question_links`；
2. `KNOWLEDGE_GRAPH_ENABLED=true` 自动投影 → `entity_graph_edges` 打通"题-点-包"六向关系；
3. 在"知识点" tab 或批脚本里触发衍生 → 生成 `concept_explainer(parent)`、`exam_cheatsheet(student)` 等；
4. 人工 / 规则校验 approved → 写入 `RetrievalDocument`；
5. 家长端提问："孩子这次错的这道题在考什么？"
   - 图谱给出：该 Q → `assesses_point_strong` → 点 P → `relates_weak` → 前置点 P'
   - RAG 命中：P 的 `concept_explainer(parent)` 衍生条目
   - LLM 拼装出易读的家长版解答。

---

## 5. 回滚

- 关掉 `KNOWLEDGE_GRAPH_ENABLED` → 后续摄入不再投影；已有边不动，也可在 DB 手工 `DELETE FROM entity_graph_edges WHERE source_origin='business_projection';` 清掉。
- 关掉 `KNOWLEDGE_DERIVATIVE_ENABLED` → 前端无法触发生成；`KnowledgeDerivative` 表保留，审核/浏览仍可用。
- 关掉 `KNOWLEDGE_RAG_ENABLED` → 衍生内容 approved 也不会进 RAG；已进 RAG 的不会自动撤回（避免误伤），需要时在后台 `reject` 或 `delete` 对应条目。
