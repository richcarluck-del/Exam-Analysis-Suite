# 专题 Word 文档摄入 —— 设计文档

> 日期：2026-04-13
> 状态：设计评审

---

## 一、文档分析：`1 第一节　集合.docx` 结构

### 1.1 整体结构概览


| 元素类型                | 数量  | 说明                     |
| ------------------- | --- | ---------------------- |
| 段落 (p)              | 254 | 全部样式为 `Normal`，无分级标题样式 |
| 表格 (tbl)            | 10  | 含知识总结表、考点标题表、分页标记表     |
| 内嵌图片 (drawing)      | 33  | Venn 图、数轴示意图等          |
| Office Math (oMath) | 104 | 分式、根号、集合运算等公式          |


### 1.2 内容组织结构（按阅读顺序）

整份文档呈现 **线性交替** 的结构，可划分为如下层次：

```
┌─ 标题行："第一节　集合"
├─ 【课程标准】    ←─ 专题内容（知识框架）
├─ 知识梳理
│   ├─ 1.集合与元素          ←─ 专题内容（带表格、公式）
│   │   └─ TABLE: 常用数集
│   ├─ 2.集合间的基本关系    ←─ 专题内容（带表格）
│   │   └─ TABLE: 关系对照表
│   ├─ 3.集合的基本运算      ←─ 专题内容（带表格）
│   │   └─ TABLE: 运算对照表
│   └─ 【常用结论】          ←─ 专题内容
├─ 【自主检测】
│   ├─ 1. ... 答案：ABC      ←─ 题目（含答案）
│   ├─ 2. ... 答案：AD       ←─ 题目
│   ├─ 3. ... 答案＋解析     ←─ 题目
│   ├─ 4. ... 答案＋解析     ←─ 题目
│   └─ 5. ... 答案           ←─ 题目（填空）
├─ TABLE "考点一　集合的基本概念·自主练透"  ←─ 分隔标记
│   ├─ 1. ... 答案＋解析     ←─ 题目
│   ├─ 2. ... 答案＋解析     ←─ 题目
│   └─ ...
├─ 方法总结（非题目段落）    ←─ 专题内容
├─ TABLE "考点二　集合间的基本关系·师生共研"
│   ├─ 例题 (1)(2) + 答案解析  ←─ 题目
│   ├─ [变式探究]              ←─ 题目（变式）
│   └─ 方法总结 + 对点练      ←─ 专题内容 + 题目
├─ TABLE "考点四　集合的新定义问题·师生共研"
│   └─ ...
├─ [真题再现]                  ←─ 题目
├─ [教材呈现]                  ←─ 题目
├─ TABLE "课时测评1　集合"     ←─ 分隔标记
│   ├─ 选择题 1-12             ←─ 题目
│   ├─ 解答题 13-16            ←─ 题目
│   └─ 每题含答案+解析
└─ END
```

### 1.3 关键发现

1. **题目与专题内容高度交织**：不像普通试卷从头到尾都是题目；这里"知识讲解→例题→方法总结→练习"反复出现。
2. **分区标记用表格而非标题样式**：`考点一`、`考点二`、`课时测评` 等章节标题嵌在 **1×1 单格表格** 里。
3. **题目识别信号**：
  - 以 `数字.` 或 `数字．` 开头的段落
  - 紧跟 `A．...  B．...` 选项行
  - 紧跟 `答案：` / `解析：` 段落
4. **专题内容识别信号**：
  - `【课程标准】`、`【常用结论】` 等中括号标记
  - 知识总结表格（2×6、4×4 等结构化表）
  - 不以题号开头、不含选项的段落（方法描述、规律总结）
5. **oMath 分布广泛**（104 处）：公式既出现在知识讲解里，也出现在题目里。

---

## 二、【题目】与【专题内容】的边界判定

### 2.1 边界的核心难点


| 挑战          | 描述                                   |
| ----------- | ------------------------------------ |
| 交叉嵌套        | 一个"考点"区域内先有讲解，中间插例题，后有方法总结，再接对点练     |
| 题目答案连续性     | 题目文本 → 选项 → `答案：` → `解析：` 构成不可分割的题目段 |
| 方法总结前后无显式标记 | 有些方法总结段直接跟在题目解析后面，没有标题行              |


### 2.2 判定规则设计

采用 **有限状态机 + 段落分类器** 方案：

```
状态：CONTENT（专题内容）| QUESTION（题目段）| ANSWER_ZONE（答案/解析区域）

段落事件分类：
  E_QUESTION_HEAD   → 匹配 QUESTION_HEADER_PATTERN（"数字." 开头）
  E_OPTION          → 匹配 "A．" / "B．" 等选项行
  E_ANSWER_LABEL    → 匹配 "答案：" / "解析：" / "详解：" 等
  E_SECTION_TABLE   → 1×1 表格且含 "考点"/"课时测评"/"自主检测" 等关键词
  E_KNOWLEDGE_TAG   → "【课程标准】"/"【常用结论】"/"[微提醒]" 等方括号标签
  E_METHOD_SUMMARY  → 非题号开头、长段、含 "方法"/"注意"/"关键" 等总结性关键词
  E_KNOWLEDGE_TABLE → 多行多列的知识总结表格（非 1×1 标题表）
  E_PLAIN           → 不匹配以上任何规则
```

**状态转移规则：**

```
CONTENT:
  + E_QUESTION_HEAD     → 切换到 QUESTION，新建 QuestionItem
  + E_SECTION_TABLE     → 刷出当前 content block，记录新区域标题
  + E_KNOWLEDGE_TAG     → 留在 CONTENT，开始新 content block
  + E_KNOWLEDGE_TABLE   → 留在 CONTENT，内容追加（保留表格 render）
  + E_PLAIN             → 留在 CONTENT，内容追加
  + E_METHOD_SUMMARY    → 留在 CONTENT

QUESTION:
  + E_OPTION            → 留在 QUESTION（追加选项）
  + E_ANSWER_LABEL      → 切换到 ANSWER_ZONE（仍属当前题目）
  + E_QUESTION_HEAD     → 完结当前题目 → 开始新题目
  + E_KNOWLEDGE_TAG     → 完结当前题目 → 切换到 CONTENT
  + E_METHOD_SUMMARY    → 完结当前题目 → 切换到 CONTENT
  + E_SECTION_TABLE     → 完结当前题目 → 切换到 CONTENT
  + E_KNOWLEDGE_TABLE   → 完结当前题目 → 切换到 CONTENT
  + E_PLAIN             → 留在 QUESTION（追加到 stem 或当前 section）

ANSWER_ZONE:
  + E_ANSWER_LABEL      → 留在 ANSWER_ZONE（可能从"答案"切到"解析"）
  + E_QUESTION_HEAD     → 完结当前题目 → 开始新题目
  + E_KNOWLEDGE_TAG     → 完结当前题目 → 切换到 CONTENT
  + E_METHOD_SUMMARY    → 完结当前题目 → 切换到 CONTENT
  + E_SECTION_TABLE     → 完结当前题目 → 切换到 CONTENT
  + E_PLAIN             →
      若紧跟答案/解析 → 留在 ANSWER_ZONE（解析续行）
      若出现 2+ 段无题号无选项无答案标记 → 切换到 CONTENT（方法总结开始）
```

### 2.3 区域归属

划分出的每个段落最终归属到两类之一：

- **QuestionSegment**：题号 + stem + options + answer + analysis + solution + comment
- **ContentSegment**：知识讲解 / 方法总结 / 表格 / 知识框架

每个 ContentSegment 会标注它在文档中的位置以及 **前后相邻的题目编号**，用于后续的关联。

---

## 三、数据模型映射

### 3.1 现有模型 —— 完全够用，无需新增表


| 存储目标          | 模型                                   | 关键字段用法                                                                                         |
| ------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------- |
| 文档元数据         | **SourceDocument**                   | `storage_url`, `file_ext=".docx"`, `parse_profile="knowledge_point"`                           |
| 专题包           | **KnowledgePackage**                 | `source_document_id`, `package_type="topic"`, `outline_json`（含区域清单）                            |
| 专题知识块（讲解、方法等） | **KnowledgeBlock**                   | `package_id`, `content_format="rich_docx"`, `**rich_content_json`**（完整 render 树）, `block_role` |
| 专题题目          | **QuestionItem** + **QuestionBlock** | 与现有试卷题目完全一致                                                                                    |
| 题目所在材料卷       | **Paper**                            | `knowledge_package_id=pkg.id`, `source_type="topic_material"`                                  |
| 题目→专题包        | **KnowledgePackageQuestion**         | `source_block_id` 指向该题所在上下文的 KnowledgeBlock                                                    |
| 内嵌图片          | **Asset**                            | `owner_type="knowledge_block"` 或 `"question_item"`                                             |


### 3.2 KnowledgeBlock.rich_content_json 的格式

**当前问题**：DOCX 专题摄入时 `rich_content_json` 仅存 `{"heading": "..."}`，无法展示。

**改进后**：存储与 `QuestionBlock.rich_content_json` 相同格式的完整 render 树：

```json
{
  "type": "block_group",
  "role": "topic_content",
  "section_title": "集合与元素",
  "plain_text": "...",
  "blocks": [
    {
      "type": "paragraph",
      "style": { "text_align": "left" },
      "children": [
        { "type": "text", "text": "(1)集合元素的基本属性：", "marks": { "bold": true } }
      ]
    },
    {
      "type": "table",
      "rows": [
        {
          "cells": [
            {
              "blocks": [
                {
                  "type": "paragraph",
                  "children": [{ "type": "text", "text": "集合" }]
                }
              ]
            }
          ]
        }
      ]
    },
    {
      "type": "paragraph",
      "children": [
        { "type": "text", "text": "∁" },
        { "type": "image", "storage_url": "...", "width": 120, "height": 40, "alt_text": "公式" }
      ]
    }
  ]
}
```

这与 `QuestionRichRenderer.jsx` 已支持的 `block_group` / `paragraph` / `table` / `image` 节点完全兼容。

---

## 四、完整摄入管线设计

### 4.1 流程图

```
                       ┌───────────────────┐
                       │  .docx 文件输入    │
                       └─────────┬─────────┘
                                 │
                    ┌────────────▼────────────┐
                    │ Step 1: DOCX 富文本提取  │
                    │ extract_docx_blocks()   │
                    │ → blocks[{text, render}]│
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │ Step 2: 段落分类         │
                    │ 状态机遍历 blocks        │
                    │ → ContentSegment[]      │
                    │ → QuestionSegment[]     │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                                      │
   ┌──────────▼──────────┐              ┌───────────▼───────────┐
   │ Step 3A: 知识块入库  │              │ Step 3B: 题目入库     │
   │ → KnowledgeBlock    │              │ → Paper               │
   │   (rich_content_json│              │ → QuestionItem        │
   │    完整 render 树)  │              │ → QuestionBlock       │
   │ → KnowledgeAtom     │              │   (rich_content_json) │
   └──────────┬──────────┘              │ → QuestionOption      │
              │                          │ → KnowledgePackage-   │
              │                          │   Question (关联)     │
              │                          └───────────┬───────────┘
              │                                      │
              └──────────────────┬───────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │ Step 4: 向量索引         │
                    │ index_document_questions │
                    └─────────────────────────┘
```

### 4.2 各步骤详细说明

#### Step 1：DOCX 富文本提取

复用现有 `question_bank_rich_content.extract_docx_blocks()`。该函数已完整处理：

- 段落：文本 + 粗体/斜体/上下标/字号 marks
- 表格：嵌套行列 + 单元格内段落
- 图片：drawing/pict → 导出 PNG → `storage_url` + `file_hash`
- Office Math (oMath)：→ `formula` 节点
- Legacy OLE 对象：→ Word COM / filtered HTML 回退

输出：`List[{"text": str, "render": dict}]`，每个 block 对应 DOCX body 中的一个段落或表格。

#### Step 2：段落分类（核心新增逻辑）

新增函数 `classify_topic_docx_blocks(blocks) → (content_segments, question_segments)`。

每个 block 依次通过分类器打上标签（见第二节规则），然后合并相邻同类 block 为 segment：

```python
@dataclass
class TopicContentSegment:
    section_title: str           # 所属区域标题（如 "考点一"）
    blocks: List[Dict]           # 完整的 render blocks
    plain_text: str              # 纯文本摘要
    block_order_range: Tuple[int, int]  # 在原文中的位置
    adjacent_question_nos: List[str]    # 前后相邻题号

@dataclass
class TopicQuestionSegment:
    question_no: str
    section_title: str           # 所属考点区域
    blocks: List[Dict]           # 完整的 render blocks（stem+options+answer+解析）
    block_order_range: Tuple[int, int]
```

#### Step 3A：知识块入库

对每个 `TopicContentSegment`：

```python
block = KnowledgeBlock(
    package_id=package.id,
    block_order=order,
    section_path=f"{package_title}/{section_title}",
    block_role=infer_block_role(section_title, plain_text),  # "knowledge_framework" / "method_summary" / "tips" 等
    content_format="rich_docx",
    raw_text=plain_text,
    normalized_text=normalize(plain_text),
    rich_content_json={
        "type": "block_group",
        "role": "topic_content",
        "section_title": section_title,
        "plain_text": plain_text,
        "blocks": [b["render"] for b in segment.blocks],
    },
    source_origin="structured_extraction",
    confidence=0.9,
)
```

#### Step 3B：题目入库

对每个 `TopicQuestionSegment`，复用现有 `_parse_structured_question_segment()` 和 `persist_questions()`：

1. 将题目 blocks 传入 `_parse_structured_question_segment` → `ExtractedQuestion`
2. 创建 `Paper`（`source_type="topic_material"`, `knowledge_package_id=pkg.id`）
3. `persist_questions()` → `QuestionItem` + `QuestionBlock` + `QuestionOption`
4. 写入 `KnowledgePackageQuestion`（`source_block_id` 指向最近的相关 `KnowledgeBlock`）

### 4.3 对现有代码的改动范围


| 文件                              | 改动                                                  | 说明                                                                                  |
| ------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `knowledge_point_parser.py`     | **修改** `_extract_pages`                             | DOCX 路径改为调用 `extract_docx_blocks` 返回 rich blocks                                    |
| `knowledge_point_parser.py`     | **修改** `ingest_source_document`                     | `.docx` 同样走专题题目入库路径（当前仅 PDF）                                                        |
| `knowledge_point_parser.py`     | **新增** `_classify_topic_docx_blocks()`              | 段落分类状态机                                                                             |
| `knowledge_point_parser.py`     | **新增** `_ingest_docx_topic_content_and_questions()` | 统一编排知识块+题目入库                                                                        |
| `question_bank_parser.py`       | **新增** `ingest_topic_docx_questions()`              | DOCX 专题题目入库（类似 `ingest_topic_packages_questions` 但基于 blocks 而非 page text）           |
| `question_bank_rich_content.py` | **不改**                                              | 已完备，直接复用                                                                            |
| `question_bank_views.py`        | **小改**                                              | `_decorate_render_payload` 可能需对 `knowledge_block` 的 `storage_url` 做 `to_public_url` |
| `shared/models.py`              | **不改**                                              | 现有模型已满足                                                                             |
| `QuestionRichRenderer.jsx`      | **不改**                                              | 已支持 `block_group`/`paragraph`/`table`/`image`                                       |


---

## 五、【专题内容】精准展示方案

### 5.1 存储层

`KnowledgeBlock.rich_content_json` 存完整的 `block_group` render 树。包括：

- **段落**：带 marks（粗体、斜体、上下标、字号）
- **表格**：嵌套 rows → cells → blocks
- **公式**：oMath → formula 节点（保留原始文本表示）
- **图片**：导出为 PNG → Asset 表 → `storage_url` → `public_url`

### 5.2 API 层

新增或复用 API 端点：

```
GET /api/knowledge-packages/{package_id}/blocks
→ 返回该专题下所有 KnowledgeBlock，rich_content_json 经 _decorate_render_payload 处理
  （storage_url → public_url, image 节点补 src）
```

### 5.3 展示层

前端复用 `QuestionRichRenderer`（已有完整的段落/表格/图片/公式渲染能力）：

```jsx
{blocks.map(block => (
  <QuestionRichRenderer
    key={block.id}
    payload={block.rich_content_json}
    fallbackText={block.raw_text}
  />
))}
```

### 5.4 手机端兼容

- 图片：`max-width: min(100%, 92vw)` + `object-contain` → 自动缩放
- 表格：已有 `overflow-x-auto` → 横向滚动
- 公式小图（若开启 `QUESTION_BANK_PDF_MATH_CLIP_IMAGES`）：普通 `<img>`，不依赖字体

---

## 六、与现有系统的关系

### 6.1 与 PDF 专题摄入并行

```
SourceDocument.file_ext == ".pdf"
  → 现有 PDF 管线（extract_page_structured + segment_questions + page rich attach）
  → 不变

SourceDocument.file_ext == ".docx"
  → 新增 DOCX 管线（extract_docx_blocks + classify + structured question segment）
  → 与 PDF 管线并行，最终写入相同的表结构
```

### 6.2 与题库主流程的关系

题库主流程（`QuestionBankIngestionService.ingest_source_document`）处理的是**试卷类文档**——从头到尾基本都是题目。

专题流程（`KnowledgePointIngestionService.ingest_source_document`）处理的是**教辅类文档**——知识讲解与题目交替。

两者共享：

- `extract_docx_blocks`（DOCX 富文本提取）
- `_segment_structured_questions` / `_parse_structured_question_segment`（题目切分）
- `persist_questions`（题目持久化）
- `QuestionRichRenderer`（前端渲染）

差异在于：专题流程多一个**段落分类**步骤，产出 **KnowledgeBlock**。

### 6.3 最终目标链路

```
学生家长上传试卷图片
  → OCR / 结构化识别 → 纯文本
  → 向量检索 QuestionItem（题库基座）
  → 命中的 QuestionItem 通过 KnowledgePackageQuestion 关联到 KnowledgePackage
  → 加载 KnowledgeBlock（专题内容）
  → 展示：题目分析 + 相关专题知识点（精准还原格式）
```

---

## 七、开发任务拆解

### Phase 1：DOCX 富文本提取接入（~0.5 天）

- `knowledge_point_parser._extract_pages_docx_rich()` 调用 `extract_docx_blocks`
- 返回 `List[Dict[str, Any]]`（text + render）

### Phase 2：段落分类器（~1.5 天）

- 实现 `_classify_topic_docx_blocks(blocks)` 状态机
- 分类器单元测试（用实际文档验证边界判定）
- 输出 `TopicContentSegment[]` + `TopicQuestionSegment[]`

### Phase 3：知识块入库（~0.5 天）

- `KnowledgeBlock` 写入 `rich_content_json`（完整 render 树）
- `KnowledgeAtom` 生成（从 plain_text 切句）
- `content_format` 改为 `"rich_docx"`

### Phase 4：题目入库（~1 天）

- 新增 `ingest_topic_docx_questions()`，基于 blocks 的结构化切题
- 复用 `_parse_structured_question_segment` + `persist_questions`
- 写入 `KnowledgePackageQuestion`（`source_block_id` 关联上下文知识块）
- `.docx` 入口去掉 `if suffix == ".pdf"` 限制

### Phase 5：展示接口（~0.5 天）

- API：`GET /api/knowledge-packages/{id}/blocks` 返回 rich blocks
- `_decorate_render_payload` 处理 knowledge_block 的图片 URL
- 前端复用 `QuestionRichRenderer` 展示

### Phase 6：测试与调优（~1 天）

- 用 `1 第一节　集合.docx` 端到端测试
- 验证题目与专题内容的正确切分
- 验证富文本展示（表格、公式、图片）
- 手机端测试

**预计总工期：~5 天**

---

## 八、风险与注意事项


| 风险            | 应对                                                                           |
| ------------- | ---------------------------------------------------------------------------- |
| 段落分类器误判边界     | 先用当前文档调试完善规则，设置 review_status="draft" 支持人工审核                                 |
| oMath 公式丢失    | `extract_docx_blocks` 已处理 oMath → formula 节点，但需验证 104 处公式都被正确提取              |
| 图片 33 张需导出为文件 | `DocxRichContentExtractor` 已有图片导出逻辑，需确认 output_dir 写入 `question_bank_assets` |
| 大文档性能         | 254 段落 + 10 表格规模不大；但若后续有更大的文档需评估                                             |
| 不同专题文档格式差异    | 当前只有一份文档，规则可能需要随更多文档迭代                                                       |


