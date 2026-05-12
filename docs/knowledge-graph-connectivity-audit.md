# 知识图谱连通性审计报告

**日期**：2026-05-06
**审计范围**：PostgreSQL `entity_graph_edges` / `knowledge_points` / `knowledge_point_relations` / `knowledge_question_link` + Neo4j 图谱
**数据规模**：271 个知识点，2 个专题包，1651 条图谱边

---

## 1. 问题陈述

当前图谱实际上是一个「外部实体与关系的存储器」——所有边都从 KnowledgePackage 出发指向知识点和题目，形成以包为中心的星形图。知识点之间、题目与知识点之间没有边，图谱无法提供任何超出原始输入的推导能力。

用户期望的图谱应类似人脑记忆模式：以「知识点」为骨架节点，各种专题、试卷、讲解等所有内容通过知识点网络相互连接，产生丰富的联想和深入能力。

---

## 2. 核心发现

### 2.1 知识点之间零连接（致命）

```
KnowledgePointRelation 记录: 0 条
EntityGraphEdge kp→kp:    0 条
```

271 个知识点之间没有任何语义关系边。连「充分条件 → 充要条件」这种数学上明确的前置关系、「全称量词 → 全称命题」这种上下位关系都不存在。

`KnowledgePointRelation` 表结构已完整定义（`source_knowledge_point_id`, `target_knowledge_point_id`, `relation_type`, `strength_score`, `confidence`），但管道中没有任何步骤向该表写入数据。

### 2.2 题目↔知识点桥接数据存在但未入图

```
KnowledgeQuestionLink 记录:   285 条（61 道题 ↔ 50 个知识点）
EntityGraphEdge q→kp 边:       0 条
```

桥接数据 `KnowledgeQuestionLink` 已在 LLM 桥接步骤中正确生成（31/31 题的包 433 全部完成桥接），但 `sync_package_projection` 流程从未将这些桥接关系投影为 `EntityGraphEdge` 或写入 Neo4j。

当前图中存在的 `knowledge_point -[relates_strong]-> question_item`（887 条）方向是从 KP 指向题的反向边，与桥接数据方向不同，且来源不同（正则/规则抽取 vs LLM 桥接）。

### 2.3 同一概念的命名碎片化

以专题包 433「常用逻辑用语」为例，DeepSeek LLM 将同一个数学概念按「定义/判定/结构/等价表示」拆分为多个独立知识点：

| 核心概念 | 被拆分为 |
|---------|---------|
| 全称量词 | `全称量词`、`全称量词∀及其常见表述`、`全称量词（∀）及其常见表述`、`全称量词命题` |
| 全称命题 | `全称命题`、`全称命题真假的判定`、`全称命题真命题的判定（需普遍成立）`、`全称命题结构∀x∈M，p(x)` |
| 充要条件 | `充要条件`、`充要条件的定义`、`充要条件的等价表示p⇔q`、`充要条件的等价表示（p⇔q）`、`充要条件判断` |
| 充分条件 | `充分条件`、`充分条件的判定`、`充分条件与必要条件的定义（p⇒q）`、`充分条件判断` |

这些 LLM 生成的不同粒度变体**本该是一个概念节点的不同属性侧面**，却各自成为独立的图节点，彼此不相识。

### 2.4 跨包零共享

```
跨 package 共享的知识点:       0 个
孤立知识点（未关联任何包）:  209 个 (77%)
```

同一文档重摄入两次（包 432 → 包 433）产生的知识点 ID 完全不同——没有任何匹配/合并逻辑。孤立的 209 个知识点来自更早期的摄入，同样无法与任何包关联。

### 2.5 缺少学科标记

```
All KPs subject=None: 271 个
```

所有 271 个知识点的 `subject` 字段为空，连按数学/物理/化学的粗分类都无法进行。

### 2.6 当前图的边结构（全貌）

```
knowledge_point -[relates_strong]->   question_item:  887
knowledge_point -[relates_adjacent]-> question_item:  271
knowledge_package -[includes_question]-> question_item: 181
knowledge_package -[covers_point]->     knowledge_point: 119
knowledge_point -[contains_atom]->      knowledge_atom:  120
knowledge_point -[contains_block]->     knowledge_block:  69
knowledge_point -[relates_fallback]->   question_item:    4
```

**全部为星形结构**：以 KnowledgePackage 或 KnowledgePoint 为源的单跳边。缺失的关键边类型：

- `knowledge_point → knowledge_point`（前置/包含/相关）
- `question_item → knowledge_point`（题目考查知识点）

---

## 3. 根因分析

图谱无法形成网络的根因不在「知识点命名不统一」这一表面现象，而在**管道缺失了三个关键处理步骤**：

| 层 | 应该做的事 | 当前状态 |
|---|-----------|---------|
| **Dedup / Merge** | 新 KP 入库前与已有 KP 做语义匹配，决定新建还是归并 | 缺失 — 每次摄入均无条件新建 ID |
| **Relation Extraction** | 在同一包内/跨包提取 KP 之间的 prerequisite/hierarchy/related 关系 | 缺失 — `KnowledgePointRelation` 表完全为空 |
| **Bridge Projection** | 将 `KnowledgeQuestionLink` → `EntityGraphEdge` → Neo4j | 缺失 — 桥接数据算出来了但从未入图 |

---

## 4. 修复建议

### P0：Dedup / Merge（阻断级）

每次 LLM 提取出知识点名称后，在创建新 `KnowledgePoint` 记录之前，进行语义去重：

1. **候选召回**：用知识点名称做向量检索，在已有 KP 库中召回 top-N 候选
2. **LLM 判定**：让 LLM 判断「新名称」与「候选名称」是否为同一概念，输出 merge / new / refinement 判定
3. **执行**：
   - `merge`：复用已有 KP ID，追加别名（`aliases_json`）
   - `new`：创建新 KP
   - `refinement`：用新名称更新已有 KP 的描述粒度（在已有 KP 上追加 `canonical_summary` 等）

预期效果：同一概念不再产生多个 ID，跨包自动共享知识点。

### P1：Relation Extraction（阻断级）

在同一包的 LLM 提取步骤中，让 LLM 同时输出知识点之间的关系：

```
输入: 包内已提取的 38 个知识点名称列表
输出: [
  {source: "充分条件", target: "充要条件", relation: "prerequisite"},
  {source: "全称量词", target: "全称命题", relation: "contains"},
  {source: "含量词命题的否定", target: "全称命题", relation: "applies_to"},
  ...
]
```

写入 `KnowledgePointRelation` 表，然后由投影逻辑写入 `EntityGraphEdge` → Neo4j。

预期效果：知识点之间形成边，图从星形变为网状。

### P2：Bridge Projection（高优先级）

在 `sync_package_projection` 中增加一段：遍历包内所有 `KnowledgeQuestionLink`，为每条桥接记录创建 `question_item -[tests]-> knowledge_point` 的 `EntityGraphEdge`，然后同步到 Neo4j。

预期效果：Neo4j 中题目→知识点的路径打通，从错题可以遍历到知识点。

### P3：Subject 自动标注（中优先级）

在 LLM 提取知识点时，同时让 LLM 输出 `subject` 字段（从已有学科枚举中选择），或根据包/文档元数据自动继承。

---

## 5. 数据快照

| 指标 | 当前值 |
|-----|-------|
| 知识点总数 | 271 |
| 专题包数 | 2 |
| EntityGraphEdge 总数 | 1,651 |
| KnowledgePointRelation | 0 |
| KnowledgeQuestionLink | 285 |
| 已桥接题目数 | 61 |
| 跨包共享 KP | 0 |
| KP→KP 边 | 0 |
| 题→KP 图谱边 | 0 |
| LLM 生成 KP 占比 | 100% (271/271) |
| KP subject 为空 | 100% (271/271) |
