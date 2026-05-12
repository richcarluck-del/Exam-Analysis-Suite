# Exam-Analysis-Suite 工程全面解读

> 本文用自然语言逐层拆解整个工程的架构、模块职责和数据流转。

---

## 一、这个工程是做什么的？

**Exam-Analysis-Suite** 是一套**试卷智能批改与分析系统**。一句话概括：你把学生的试卷扫描进来，它自动识别每一道题、识别学生的答案、调用 AI 判断对错、关联知识点、给出学习建议，最终输出一份完整的分析报告。

系统分为两个大阶段：

1. **预处理阶段（Preprocessor）**：把原始试卷图片变成结构化的"题目包"
2. **分析阶段（Analyzer）**：用 AI 对每道题做深度分析，输出分析报告

此外还有一个**在线服务面**：提供 Web 前端 + RESTful API，让用户可以上传试卷、管理题库、检索知识点。

---

## 二、顶层入口：`run_pipeline.py`

这是整个系统的"总开关"。它是一个 Python 脚本，按顺序调用两个子系统：

```
用户 → run_pipeline.py → preprocessor/main.py → 输出 bundle/ → analyzer/run.py → 输出分析报告
```

- 用户在命令行传入 `--input-dir`（原始试卷图片目录）
- Pipeline 先调起 `preprocessor/main.py` 做预处理
- 预处理完成后，再调起 `analyzer/run.py` 做分析
- 最终输出 `analysis_report.json`（汇总报告）和 `question_analyses.json`（逐题详情）

---

## 三、Preprocessor 预处理模块（详细拆解）

**入口**：`preprocessor/main.py`
**核心位置**：`preprocessor/src/`

### 3.1 总体思路

预处理模块像一个**工厂流水线**，总共 10 个步骤（Step 0～9）。每一步都是一个独立的 Python 任务函数，位于 `preprocessor/src/tasks/` 目录下。

```
原始试卷图片 → [Step 0-9 流水线] → manifest.json + questions.json（Bundle）
```

### 3.2 每个 Step 做什么？

#### Step 0 — 图像预处理（`task_preprocess_images`）
- 读取用户提供的原始图片
- 进行**压缩**（减小后续 API 调用成本）
- 生成一个 `compression_map`（原始图 → 压缩图的映射关系），后续所有步骤默认使用压缩后的图片

#### Step 1 — 透视校正（`task_perspective_correction`）
- 很多试卷是翻拍或扫描的，可能歪斜
- 这一步调用 **LLM / VLM** 做**透视校正**，把歪斜的图片"摆正"
- 输出校正后的图片

#### Step 2 — 页面分类（`task_classify_page` / `task_long_image_classification`）
- 判断每一页是什么类型：
  - **试卷页**（含题目和题干）
  - **答题卡页**（学生填写答案的区域）
- 支持两种分类模式（通过 `--classification-method` 选择）：
  - `single_page`：传统的单页逐页分类
  - `long_image`：把多页拼接成一个长图后交给大模型一次性识别（利用全局上下文，准确率更高）
- 如果是 A3 大小的试卷，还支持 `--a3-strategy` 来控制是拆分还是整体处理

#### Step 3 — 布局分析（`task_analyze_layout`）
- 对每个页面做**版面分析**
- 识别页面上的**文本区域、图片区域、题目分界线**
- 输出每个区域的坐标（bounding box）

#### Step 4 — 内容提取（`task_extract_content`）
- 根据布局分析的结果，把每道题的区域裁剪出来
- 调用 LLM/VLM **识别每道题的题号和题干文字**
- 输出每道题的元数据：题号、题干文本、题目类型、所属页面等

#### Step 4.5 — 答案提取（`task_extract_answers`）
- 与 Step 4 配套
- 从答题区裁剪学生手写的答案
- 输出学生答案区域

#### Step 5 — 结果合并（`task_merge_results`）
- 将题号和题目内容、答案区域**配对合并**
- 处理跨页题目、多页题目的拼接
- 输出一个统一的中间 JSON：`05_merged_output.json`

#### Step 6 — 答题卡识别（`task_answer_card_pipeline`）
- 这是整个预处理流程中**最复杂的步骤**
- 位于 `preprocessor/src/answer_card/` 之下，是一个**多策略组合**的答题卡识别引擎
- 包含四个策略：
  1. **OMR 扫描器**：光电标记识别（传统的涂卡识别）
  2. **OCR 检测器**：手写答案的字符识别
  3. **VLM 识别器**：用多模态大模型直接"看"答题卡并识别答案
  4. **混合识别器**：综合以上三种策略的结果，给出最终答案
- 处理各种复杂情况：涂擦痕迹、模糊字迹、选择/填空混合

#### Step 7 — 生成完整单元（`task_generate_complete_units`）
- 把每道题的 **题干图片 + 学生答案图片** 合成一张"完整单元图"
- 这张图后续会被 analyzer 的 VLM 分析使用（一次看完整题目，理解更准）

#### Step 8 — 绘制标注输出（`task_draw_output`）
- 把识别结果**画回到原图上**：画框、标题号、标答案
- 输出 `08_annotated_images/` 目录，供人工检查质量

#### Step 9 — 导出 Bundle（`task_export_analysis_bundle`）
- 把所有预处理结果打包成两个标准文件：
  - `manifest.json`：身份证信息（考试ID、科目、年级、学生ID、统计信息等）
  - `questions.json`：所有题目的结构化数据（题号、题干、答案、图片路径、置信度等）
- 这就是 **Bundle 契约**，是 preprocessor 和 analyzer 之间的"合同"

### 3.3 核心辅助模块

| 模块 | 位置 | 作用 |
|------|------|------|
| **EnhancedLogger** | `src/enhanced_logger.py` | 记录每一步的输入输出、耗时、LLM 调用的 prompt 和 response |
| **ImagePathManager** | 内嵌于 `main.py` | 统一管理压缩图和原始图的路径映射 |
| **ConfigLoader** | `src/utils/config_loader.py` | 从 YAML 加载配置（分类方式等） |
| **PromptManager** | `src/prompt_manager.py` | 管理各个步骤的 LLM 提示词模板 |

### 3.4 运行模式

Preprocessor 支持多种运行模式：

| 模式 | 触发方式 | 说明 |
|------|----------|------|
| **真实模式** | `--input-dir` | 全流程真实运行，调用 LLM API |
| **测试模式** | `--test-case` | 用测试数据集运行 |
| **混合模式** | `--mock-case` + `--real-steps` | 部分步骤用 mock 数据，部分用真实 API（调试神器） |
| **录制模式** | `--record-case` | 保存所有中间结果到 mock 数据目录 |

---

## 四、Analyzer 分析器模块（详细拆解）

### 4.1 双重职责

Analyzer 承担两套职责：

| 职责 | 入口 | 说明 |
|------|------|------|
| **离线分析** | `analyzer/run.py` | 批量读取 Bundle，逐题用 AI 分析，输出报告 |
| **在线服务** | `analyzer/app/main.py` | FastAPI Web 服务，提供 RESTful API 和前端界面 |

### 4.2 离线分析链路（`analyzer/run.py`）

#### 输入
- Preprocessor 产出的 Bundle 目录（含 `manifest.json` + `questions.json`）

#### 流程
每道题的分析分三个阶段：

1. **混合检索（Retrieval）** — `build_retrieval_snapshot()`
   - 把题干文字作为查询词，做**向量检索 + 图检索**（Qdrant + Neo4j）
   - 召回知识库中的相关知识点、典型解法、类似题目
   - 输出：检索到的知识片段（citation + snippet）

2. **VLM 题级分析** — `build_vlm_snapshot()`
   - 把第 7 步生成的"完整单元图片"发给**多模态大模型**（VLM）
   - 让 VLM"看题"并回答：
     - 题干总结
     - 学生答案观察
     - 对错判断（correct / incorrect / uncertain）
     - 涉及的知识点
     - 可能的错误原因
     - 下一步动作建议

3. **最终结论融合** — `build_final_conclusion()`
   - **规则融合（Rule-based）**：根据已有数据（检索结果 + VLM 观察）用规则引擎生成初步结论
   - **LLM 融合**：用文本 LLM 把检索结果和 VLM 观察"揉在一起"，生成更准确的结论
   - 结合两者的结果，输出最终分析：对错、掌握度、错因分析、学习建议

#### 每个分析的结果结构
```json
{
  "question_no": "1",
  "answer_status": "answered",
  "correctness": "incorrect",
  "mastery_level": "weak",
  "knowledge_points": ["勾股定理", "直角三角形"],
  "error_causes": ["对勾股定理的逆定理理解有偏差"],
  "explanation": "...",
  "study_advice": ["回顾勾股定理的公式，重做同类题"],
  "supporting_evidence": ["... 引用知识库片段"],
  "recommended_next_action": "回看知识点后重做"
}
```

#### 输出
- `question_analyses.json`：每道题的详细分析
- `analysis_report.json`：汇总报告（总分、正确率、薄弱知识点 Top N 等）

### 4.3 在线服务架构（`analyzer/app/`）

这是一套完整的 **Web 应用**，技术栈为：

| 层 | 技术 |
|----|------|
| **后端框架** | FastAPI (Python) |
| **异步任务** | Celery + Redis |
| **前端** | Vite + React/Vue（`client-app/`） |
| **认证** | JWT Token |
| **部署** | Docker Compose（API + Web 两个容器） |

#### 核心 API 模块（位于 `analyzer/app/`）

| 路由/服务 | 功能 |
|-----------|------|
| **题库管理** | 上传试卷、创建题库、管理题目 |
| **知识点管理** | 知识点 CRUD、知识图谱导航、知识点分类树 |
| **检索服务** | 向量检索、图检索、混合检索（Hybrid Search） |
| **分析/诊断** | 触发试卷分析、查看分析报告、生成学习诊断 |
| **提示词管理** | 管理所有 LLM 步骤的提示词模板和版本 |
| **配置管理** | LLM 提供商、模型、API Key 的加密存储 |

#### 数据存储

```
PostgreSQL ─── 所有结构化数据（题库、题目、知识点、分析报告、配置...）
Neo4j      ─── 知识图谱（知识点间的关联、题目与知识点的关联）
Qdrant     ─── 向量检索（语义相似题搜索）
OpenSearch ─── 文本全文检索（关键词搜索）
Redis      ─── Celery 消息队列 + 结果缓存
```

### 4.4 前端（`analyzer/client-app/`）

- 使用 **Vite** 构建（现代前端构建工具）
- 提供可视化的操作界面：上传试卷、查看分析结果、浏览知识点图谱
- 通过 HTTP 与 FastAPI 后端通信（端口 8000）

---

## 五、Shared 共享层（`shared/`）

这是 preprocessor 和 analyzer **共同依赖**的底层代码，避免重复。

### 5.1 `database.py` — 数据库连接
- 强制使用 **PostgreSQL**（禁止 SQLite）
- 通过环境变量 `DATABASE_URL` 配置
- 管理连接池（默认 10 个连接，最多溢出 20 个）
- 提供 `get_db()` 生成器供 FastAPI 依赖注入

### 5.2 `models.py` — ORM 数据模型
这是整个系统**最核心的数据定义**，30 多张 SQLAlchemy 表，分为几个域：

| 域 | 核心表 | 作用 |
|----|--------|------|
| **题库域** | `QuestionItem`, `Paper`, `PaperQuestion`, `QuestionBlock` | 题目的结构化存储 |
| **知识点域** | `KnowledgePoint`, `KnowledgeAtom`, `KnowledgeDerivative`, `KnowledgePointRelation` | 知识点的多维度建模 |
| **考试域** | `ExamSession`, `StudentAttempt`, `ExamSessionQuestion` | 考试记录和作答历史 |
| **诊断域** | `DiagnosisSnapshot` | 学情分析快照 |
| **配置域** | `LLMStepConfig`, `Prompt`, `PromptVersion`, `APIProvider`, `LLMModel` | LLM 步骤配置和提示词版本管理 |
| **检索域** | `RetrievalDocument`, `EmbeddingPoint` | 向量检索的文档和嵌入 |
| **图谱域** | `EntityGraphEdge`, `KnowledgePackage`, `KnowledgeBlock` | 知识图谱的数据模型 |
| **组织域** | `Tenant`, `User`, `ContentSource`, `SourceDocument` | 多租户、用户、内容来源管理 |

### 5.3 `llm_step_config.py` / `prompt_step_config.py` — 步骤配置

- **`llm_step_config.py`**：管理每个步骤调用哪个 LLM（提供商、模型名、API Key）
  - 支持从数据库读取或从环境变量 fallback
  - 每个步骤可以有独立的 LLM 配置
  - 例如：透视校正用 `dashscope/qwen3.5-plus`，涂卡识别用 `volcengine/doubao-seed-2-0-pro`

- **`prompt_step_config.py`**：管理每个步骤用的提示词模板
  - 支持**版本管理**（提示词可以有 v1、v2、v3...）
  - 按步骤 key 解析并返回最高版本或指定版本
  - 支提示词变量替换（如 `{question_text}`, `{student_answer}`）

---

## 六、数据流转全景

```
┌──────────────┐
│  原始试卷图片  │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────┐
│          Preprocessor（预处理管道）            │
│                                              │
│  Step 0: 压缩图片                             │
│  Step 1: 透视校正 ──→ LLM                    │
│  Step 2: 页面分类 ──→ LLM                    │
│  Step 3: 布局分析                             │
│  Step 4: 内容提取 ──→ LLM                    │
│  Step 4.5: 答案提取                           │
│  Step 5: 合并配对                             │
│  Step 6: 答题卡识别 ──→ VLM (专用模型)       │
│  Step 7: 生成完整单元图                        │
│  Step 8: 画框标注                             │
│  Step 9: 导出 Bundle                         │
│                                              │
│  输出: manifest.json + questions.json          │
└──────────────────┬───────────────────────────┘
                   │
                   ▼
┌──────────────────────────────────────────────┐
│           Analyzer（分析阶段）                  │
│                                              │
│  逐题分析循环:                                 │
│    ① 混合检索 ──→ Qdrant + Neo4j + OpenSearch│
│    ② VLM 观察 ──→ 多模态 LLM                  │
│    ③ 规则融合                                 │
│    ④ LLM 最终结论 ──→ 文本 LLM               │
│                                              │
│  输出: analysis_report.json                    │
│        question_analyses.json                  │
└──────────────────────────────────────────────┘
```

---

## 七、部署方式

### 7.1 Docker Compose 部署

```
docker-compose.analyzer.yml
  ├── analyzer-api    :8000 (FastAPI 后端)
  └── analyzer-web    :80 → 宿主机 :8001 (Nginx + 前端静态文件)
```

外部依赖需要自行部署：
- PostgreSQL（关系数据库）
- Neo4j（图数据库）
- Qdrant / OpenSearch（向量检索 / 全文检索）
- Redis（消息队列）

### 7.2 离线运行（不依赖 Docker）

```
# 1. 预处理
python preprocessor/main.py --input-dir ./exam_images --output-dir ./output

# 2. 分析
python analyzer/run.py --bundle-dir ./output --output-dir ./analysis_result
```

### 7.3 一键运行

```
# 直接运行 start_analyzer_all.bat（Windows）
# 或 docker compose up（Docker）
```

---

## 八、数据库迁移（Alembic）

```
alembic/
  ├── env.py            # 迁移环境（强制 PostgreSQL）
  ├── script.py.mako    # 迁移脚本模板
  └── versions/         # 历史迁移版本
```

所有数据库 schema 变更通过 Alembic 管理，确保版本可控。

---

## 九、关键设计决策

### 9.1 "Bundle 契约"
Preprocessor 和 Analyzer 之间通过 `manifest.json` + `questions.json` 通信，这就是 **Bundle 契约**。改动这个契约要格外小心，会影响两个模块的兼容性。

### 9.2 多 LLM 模型混合使用
系统不是用一个模型包打天下，而是**不同步骤用不同的模型**：
- 透视校正：`dashscope/qwen3.5-plus`
- 页面分类：`dashscope/qwen3.5-plus`
- 内容提取：`dashscope/qwen3.5-plus`
- 涂卡识别：`volcengine/doubao-seed-2-0-pro`（专用视觉模型）
- VLM 分析：支持视觉的多模态模型
- 最终结论：文本 LLM

### 9.3 多策略答题卡识别
答题卡识别使用 **OMR + OCR + VLM 混合策略**，不是单一技术，而是用多种方式交叉验证，提高准确率。

### 9.4 知识点与题目硬隔离
知识点模型（`KnowledgePoint` 等）和题目模型（`QuestionItem` 等）是独立域，通过桥接表关联，不互相侵入。这符合"高内聚、低耦合"原则。

### 9.5 模块分层
```
根目录（编排）
 ├── preprocessor/（独立子项目）
 ├── analyzer/（独立子项目）
 └── shared/（底层公共库）
```

- Preprocessor 和 Analyzer 互相不直接依赖
- 二者只依赖 `shared/` 中的公共代码
- 可独立开发、测试、部署

---

## 十、快速查阅索引

| 想了解... | 看这个文件 |
|-----------|-----------|
| 项目总览 | `README.md` |
| 架构图 | `ARCHITECTURE_DIAGRAM.md` |
| 架构快照 | `docs/ARCHITECTURE_SNAPSHOT.md` |
| 预处理模块 | `preprocessor/README.md` + `preprocessor/main.py` |
| 分析器模块 | `analyzer/run.py` + `analyzer/TECH_ARCHITECTURE.md` |
| 数据模型 | `shared/models.py` |
| 数据库配置 | `shared/database.py` |
| LLM 配置 | `shared/llm_step_config.py` |
| 提示词配置 | `shared/prompt_step_config.py` |
| 部署配置 | `docker-compose.analyzer.yml` |
| 环境变量 | `.env` + `docs/ENV_RUNBOOK.md` |
| 知识点系统设计 | `analyzer/docs/knowledge-point-system-technical-design.md` |