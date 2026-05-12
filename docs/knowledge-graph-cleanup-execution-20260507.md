# 知识图谱清洗执行档案 · 2026-05-07

**执行人**：Cursor Agent (Claude Opus 4.7) + 项目 Owner
**执行日期**：2026-05-07
**前置文档**：[`docs/knowledge-graph-connectivity-audit.md`](./knowledge-graph-connectivity-audit.md)（2026-05-06 的连通性审计，本次执行的依据）
**对应 chat**：[KP 清理与图谱重建](1e846a48-c766-458e-8c87-f6b2a9ba664e)
**最新状态**：2026-05-07 12:46 已追加 Phase 2 第一项优化：`KnowledgeQuestionLink` 常态投影为 `question_item -[tests]-> knowledge_point`。2026-05-07 13:20 已开发 P0 摄入侧 KP 去重闸门。2026-05-07 13:51 已完成 P1 KP-KP 关系冷启动。

---

## 0. 文档目的

把「**完整的四层修复计划**」与「**本轮实际执行的范围 / 产物 / 指标 / 残留**」固化成一份可追溯的档案，便于：

1. 后续接手者一眼看清「已做什么、剩什么」；
2. 在出现问题时按文末的回滚预案准确还原；
3. 作为下一轮（Phase 2+）的起点。

---

## 1. 完整修复计划（四层）

来自 2026-05-06 审计与后续讨论的**四层修复方案**。本次只完成**第 0 层**与**部分第 3 层（投影对齐）**；第 1、2 层留给后续阶段。

### Layer 0 — Cleanup（数据治理层）— **本轮已完成**

历史数据已经混乱到无法用增量方式补救，必须先一次性把库洗干净，给后续算法一个干净的起点。具体动作：

| 类别 | 动作 | 触发条件 |
|---|---|---|
| `KEEP` | 保留 KP | 真正的概念，名字符合"概念名词"或"公式定理"等可保留粒度 |
| `KEEP_AS_CANONICAL` | 保留为同核心词簇代表 | 簇内多条 KP，挑承载最丰富、命名最规范的一条 |
| `MERGE_INTO_CANONICAL` | 合并入簇代表 | 同一概念碎片化（如"充分条件的判定"→"充分条件"）|
| `DEMOTE_TO_ATOM` | 降级为 `knowledge_atom` | 粒度过细、是"判断/求解/分析方法"，挂到上位 KP 下 |
| `DELETE_EMPTY_IN_PKG` | 删除 | 在 active package 中但 0 KQL/0 atom/0 block 承载 |
| `DELETE_ORPHAN` | 删除 | 不在任何 active package 且 0 承载 |

副作用同步：

- `retrieval_documents` + `embedding_points`（PG）
- Qdrant / Chroma 向量集合
- `entity_graph_edges`（投影边）
- `knowledge_point_relations`（KP-KP 关系）
- Neo4j 节点与关系
- 历史悬空 EGE 边（source/target 已无底层实体的 dangling 边）

### Layer 1 — Dedup / Merge（摄入层去重）— **未做**

**目标**：每次 LLM 提取出 KP 名称后，**入库前**做语义匹配，决定 `merge` / `new` / `refinement`。
**输入**：新 KP 名 + 已有 KP 池（向量召回 top-N + 名称 trigram 匹配）。
**输出**：复用旧 ID（追加 `aliases_json`）／新建 ID／在旧 KP 上扩展 `canonical_summary`。

不做的话，下一次摄入会立刻把刚清洗干净的库重新污染回去。这是**当前管道最致命的缺口**。

**2026-05-07 13:20 更新**：已完成应用层第一版 P0 闸门：

- 新增 `analyzer/app/knowledge_point_dedup.py`。
- `KnowledgePointIngestionService._get_or_create_knowledge_point()` 已改为去重优先。
- 管理 API 的 `create_knowledge_point()` 也复用同一去重逻辑。
- 复用旧 KP 时会把新名称追加到 `aliases_json`，并补齐旧 KP 缺失的 `subject` / `grade_scope`。
- 默认开启，可用 `KNOWLEDGE_POINT_DEDUP_ENABLED=false` 关闭。
- `pg_trgm` 可用时会启用高阈值相似匹配，阈值可用 `KNOWLEDGE_POINT_DEDUP_TRGM_THRESHOLD` 调整，默认 `0.92`。

### Layer 2 — Relation Extraction（KP-KP 关系层）— **未做**

**目标**：让 LLM 在抽取 KP 时同步输出 `prerequisite / contains / specializes / related / equivalent` 关系。
**写入**：`knowledge_point_relations` 表 → `entity_graph_edges` → Neo4j。
**预期效果**：把图从「以包/KP 为根的星形」变为「KP-KP 网状」。

清洗后的 40 个 KP 仍然有清晰的可建关系机会（如 `充分条件 ⊂ 充分不必要条件`、`全称量词 → 全称命题`、`元素 → 集合`），audit 自动检出 7 对子串包含对，可作为冷启动种子。

**2026-05-07 13:51 更新**：已完成冷启动第一版：

- 新增 `scripts/kp_relation_cold_start.py`。
- 写入 `knowledge_point_relations` 44 条。
- 类型分布：`prerequisite=29`、`specializes=6`、`equivalent=2`、`related=7`。
- 已同步到 `entity_graph_edges` 与 Neo4j；Neo4j 中新增 `PREREQUISITE / SPECIALIZES / EQUIVALENT / RELATED` 四类 KP-KP 边。
- 关系来源统一为 `source_origin='cold_start'`（KPR）/ `business_projection`（EGE/Neo4j 投影）。

### Layer 3 — Bridge & Sync（桥接投影层）— **本轮做了对齐部分**

**目标**：让 `KnowledgeQuestionLink` 自动投影为 `EntityGraphEdge` 中的 `question_item -[tests]-> knowledge_point` 边，并把 PG ↔ Neo4j 状态保持一致。

**本轮做的**：
- 把 PG 中已删 KP 的 EGE / 投影边 / Neo4j 节点都同步删掉（治理层副作用）。
- 写了一段 Neo4j 重投影脚本（先 DETACH DELETE 孤节点，再清掉骨干关系，再 `sync_all_knowledge_projection` MERGE 重建）。
- 追加 `KnowledgeQuestionLink` → `EntityGraphEdge[question_item→knowledge_point, relation_type=tests]` 常态投影；保留原 `knowledge_point→question_item` 方向以兼容旧查询。

**没做的**（属于真正的 Layer 3 业务功能）：
- `entity_graph_edges` 写入时的"两端都必须存在"的约束（数据库层）或 trigger（兜底）。

---

## 2. 本轮执行范围（"Phase 1：彻底清洗 + 三库对齐"）

只做 **Layer 0 + Layer 3 的对齐部分**。明确不做 Layer 1 / 2。

执行原则：

1. **不可逆操作前必须有 PG 备份与 rollback JSONL**。
2. PG 写库**全程单事务**；任何子步出错则整体回滚，不留半态。
3. 向量库 / Neo4j 等**事务外副作用**在 PG `COMMIT` 之后才执行。
4. **dry-run 默认**；改为 `--apply` 才真写。

---

## 3. 实际执行步骤与产物

### Step 1：PG 全量备份

```powershell
docker exec exam-pg pg_dump -U postgres -d exam_analysis -Fc -f /tmp/backup_pre_kp_cleanup.dump
docker cp exam-pg:/tmp/backup_pre_kp_cleanup.dump scripts\_out\backup_pre_kp_cleanup_20260507.dump
```

**产物**：`scripts/_out/backup_pre_kp_cleanup_20260507.dump`（12.6 MB，custom format）。

### Step 2：清洗前指标快照

```powershell
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_compare.py snapshot --tag before
```

**产物**：`scripts/_out/kp_cleanup_metrics_before.json`。

### Step 3：清洗决策评估（dry-run）

```powershell
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_proposal.py
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_migration.py
```

**决策分布**（共 271 KP）：

| 动作 | 条数 | 说明 |
|---|---:|---|
| `DELETE_ORPHAN` | 209 | 孤立 KP，0 承载，不在任何包 |
| `KEEP` | 35 | 保留为概念 |
| `DEMOTE_TO_ATOM` | 17 | 降级为 `knowledge_atom` |
| `KEEP_AS_CANONICAL` | 5 | 簇内代表，保留 |
| `DELETE_EMPTY_IN_PKG` | 3 | 包内空壳 KP |
| `MERGE_INTO_CANONICAL` | 2 | 合并到簇代表 |

**产物**：`scripts/_out/kp_cleanup_proposal_*.csv` / `*.md`。

### Step 4：执行迁移（PG 单事务）+ 向量库清理

```powershell
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_migration.py --apply --purge-vectors-after-commit
```

执行结果：

- PG 单事务一次提交 231 次写操作。
- 17 条 `knowledge_atom` 新建，承接被 demote 的 KP。
- 1 条 `retrieval_document` + 对应 embedding 实删（KP #2061）。
- 18 条 `aliases_json` 追加（被合并/降级的 KP 名记入幸存父）。

**产物**：`scripts/_out/kp_cleanup_rollback_20260507_115734.jsonl`。

### Step 5：清理悬空 EGE 边

```powershell
.venv_commercial\Scripts\python.exe scripts\ege_dangling_cleanup.py --apply
```

通过 `LEFT JOIN` 检查 `entity_graph_edges` 的 `source` / `target` 是否还指向真实的底层实体（KP / KB / KA / Q / Pkg / KD），把 545 条历史悬空边一次删掉。

**产物**：`scripts/_out/ege_dangling_rollback_20260507_120015.jsonl`。

### Step 6：Neo4j 重投影

```powershell
.venv_commercial\Scripts\python.exe scripts\neo4j_resync_after_cleanup.py
```

三步：

1. **DETACH DELETE 孤节点**：Neo4j 中 `KnowledgePoint` / `Question` 的 `entity_id` 已不在 PG 的，全部删（98 KP + 183+77 Q）。
2. **清掉知识图骨干关系**：`RELATES_STRONG` / `RELATES_ADJACENT` / `INCLUDES_QUESTION` / `COVERS_POINT` / `CONTAINS_BLOCK` / `CONTAINS_ATOM` / `HAS_DERIVATIVE` / `RELATES_FALLBACK`，避免 `MERGE` 后老边残留。
3. **`sync_all_knowledge_projection`**：调 `analyzer.app.academic_graph_service.AcademicGraphService.sync_all_knowledge_projection(db)` 全量重投影。

### Step 7：清洗后快照 + 对比

```powershell
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_compare.py snapshot --tag after
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_compare.py diff
```

### Step 8：复测

```powershell
.venv_commercial\Scripts\python.exe scripts\kp_skeleton_audit.py
.venv_commercial\Scripts\python.exe scripts\graph_audit_real.py
```

---

## 4. 关键指标对比

### PostgreSQL

| 指标 | before | after | Δ |
|---|---:|---:|---:|
| `knowledge_points` | **271** | **40** | -231 |
| `knowledge_points_in_active_pkg` | 62 | 40 | -22 |
| `knowledge_points_orphan` | 209 | **0** | -209 |
| `knowledge_blocks` | 14 | 14 | 0 |
| `knowledge_atoms` | 15 | **32** | +17 |
| `knowledge_question_links` | 285 | 243 | -42 |
| `knowledge_package_points` | 62 | 40 | -22 |
| `entity_graph_edges` | 1,651 | 667 | -984 |
| `ege_relates_strong` | 887 | 172 | -715 |
| `ege_dangling_kp_source` | 172 | **0** | -172 |
| `ege_dangling_kp_target` | 8 | **0** | -8 |
| `ege_dangling_question_target` | 997 | **0** | -997 |
| `retrieval_documents_kp_related` | 49 | 42 | -7 |
| `embedding_points` | 10,895 | 10,888 | -7 |
| `distinct_kp_referenced_by_kql` | 50 | 33 | -17 |

### Neo4j

| 指标 | before | after |
|---|---:|---:|
| `KnowledgePoint` 节点数 | 138 | **40** |
| `Question` 节点数 | 245 | 62 |
| 关系总数 | 1,419 | 680 |

| 关系类型 | before | after |
|---|---:|---:|
| `RELATES_STRONG` | 702 | 172 |
| `TESTS` | 4 | 235 |
| `RELATES_ADJACENT` | 218 | 67 |
| `INCLUDES_QUESTION` | 185 | 61 |
| `COVERS_POINT` | 157 | 40 |
| `CONTAINS_ATOM` | 75 | 32 |
| `PREREQUISITE` | 0 | 29 |
| `CONTAINS_BLOCK` | 56 | 13 |
| `HAS_DERIVATIVE` | 9 | 9 |
| `RELATED` | 0 | 7 |
| `SPECIALIZES` | 0 | 6 |
| `RELATES_FALLBACK` | 4 | 4 |
| `EQUIVALENT` | 0 | 2 |

> 验证：清洗后 PG `entity_graph_edges` = 667，其中业务投影 `question_item -[tests]-> knowledge_point` 为 234 条，KP-KP 业务投影为 44 条。Neo4j `TESTS=235`，其中 234 条来自业务投影，另 1 条是既有考试会话状态边；Neo4j KP-KP 边 44 条；`KnowledgePoint` 节点数 PG 与 Neo4j 都是 40。

---

## 5. 操作的 231 条 KP 详细动作

### MERGE_INTO_CANONICAL — 2 条

| 源 KP | → | 目标（canonical） |
|---|---|---|
| #2075 充分条件的判定 | → | #2061 充分条件 |
| #2076 必要条件的判定 | → | #2062 必要条件 |

`#2075/#2076` 的名称作为 alias 追加进 `#2061/#2062.aliases_json`，KQL/atom/block/derivative 全部 retarget 到 canonical。

### DEMOTE_TO_ATOM — 17 条

形如 `KP "X 判断" → 上位 KP "X" 下挂一个 atom_type='method' 的 atom`，原 KP 行删除。完整列表见 `scripts/_out/kp_cleanup_proposal_*.md` 的对应小节。代表性条目：

| 源 KP | → | 父 KP |
|---|---|---|
| #1931 集合的交集、并集、补集运算 | → | #1927 集合的含义与元素属性 |
| #1932 Venn图表示集合关系与运算 | → | #1982 利用Venn图与补集分析阴影区域 |
| #2080 全称命题真假判断 | → | #2068 全称命题 |
| #2081 特称命题真假判断 | → | #2069 特称命题 |
| #2090 充分条件判断 | → | #2061 充分条件 |
| #2091 必要条件判断 | → | #2062 必要条件 |
| #2092 充要条件判断 | → | #1990 充要条件 |
| ...（共 17 条）|

### DELETE_EMPTY_IN_PKG — 3 条

`#1985 / #1986 / #1987`，在包内但完全没有承载（KQL=0、atom=0、block=0、provenance=0）。

### DELETE_ORPHAN — 209 条

ID 范围主要落在 `[1825..1924]`、`[1941..1981]`、`[1989..2060]`，均为不在任何 active package 且 0 承载的历史孤儿。

---

## 6. 决策算法的关键修正（执行过程中迭代）

### 修正 1：`fix_demote_parents` 必须排除已被删除的父

最初算法挑出"建议父 KP"时不区分该父是否在本次清洗中也被删除，导致 DEMOTE 后落到一个**即将不存在的父**上。

修复：先算出 `survivor_kp_ids`（KEEP / KEEP_AS_CANONICAL / MERGE 目标），再从中找父；找不到则按下一条规则兜底。

### 修正 2：DEMOTE 找不到父时的兜底

最初的兜底是"无父就降级为 DELETE_EMPTY_IN_PKG / DELETE_ORPHAN"，但这会把还有 KQL 承载的 KP（如 #1934 集合运算的等价转化关系，KQL=7）直接删掉，**会触发外键违例并断证据链**。

修复（`scripts/kp_cleanup_common.py` `build_kp_cleanup_decisions` 末段）：

```python
if 找不到合适幸存者父:
    if KP 还有 KQL/atom/block 承载:
        proposed_action = "KEEP"  # 留给人工指派父概念
    else:
        proposed_action = "DELETE_EMPTY_IN_PKG" or "DELETE_ORPHAN"
```

修正后分布：DEMOTE 17（不变）、KEEP 35（+5）、DELETE_EMPTY_IN_PKG 3（-5）。

### 修正 3：`purge_retrieval_docs_pg` 不能 `SELECT DISTINCT rd.*`

`retrieval_documents.metadata_json` 是 `json` 列，PG 没有 `json` 等值算子，`DISTINCT *` 会报 `UndefinedFunction`。

修复：改为先取 id 列表，再分两步读快照（`SELECT rd.id` + `SELECT id, ..., metadata_json::text`）。

### 修正 4：`knowledge_atoms.atom_type` 是 `String(32)`

最初写的是 `'derived_from_demoted_knowledge_point'`（39 字符），插入时 `StringDataRightTruncation`。

修复：改为现存唯一取值 `'method'`，并在 `normalized_json` 写入 `{"origin":"demoted_kp"}` 标记来源。

---

## 7. 产物清单

### 脚本（仓库内）

| 路径 | 用途 |
|---|---|
| `scripts/kp_cleanup_common.py` | 共享决策逻辑（建簇 / 选 canonical / 算 DEMOTE 父 / 兜底） |
| `scripts/kp_cleanup_proposal.py` | dry-run 报告（CSV + Markdown） |
| `scripts/kp_cleanup_migration.py` | 真正的 PG 迁移 + 可选向量库 purge |
| `scripts/ege_dangling_cleanup.py` | 历史悬空 EGE 边清理 |
| `scripts/neo4j_resync_after_cleanup.py` | Neo4j 孤节点剪枝 + 骨干边 / `TESTS(business)` 重投影 |
| `scripts/kp_cleanup_compare.py` | 清洗前后指标快照与 diff |
| `scripts/kp_dedup_smoke.py` | P0 去重规则 smoke 测试 |
| `scripts/kp_relation_cold_start.py` | P1 KP-KP 关系冷启动 dry-run / apply 脚本 |

### 数据（`scripts/_out/`，构建产物，不入版本库）

| 文件 | 内容 |
|---|---|
| `backup_pre_kp_cleanup_20260507.dump` | PG 全量 custom-format 备份（12.6 MB） |
| `kp_cleanup_metrics_before.json` / `_after.json` | 指标快照 |
| `kp_cleanup_proposal_20260507_*.csv` / `.md` | dry-run 决策报告 |
| `kp_cleanup_rollback_20260507_115734.jsonl` | 主迁移 rollback 日志（含每条 forward + undo_hint + 行级快照） |
| `ege_dangling_rollback_20260507_120015.jsonl` | EGE 边清理 rollback 日志 |
| `backup_pre_bridge_projection_20260507.dump` | Phase 2 桥接投影优化前 PG 备份 |
| `backup_pre_kp_relation_cold_start_20260507.dump` | P1 KP-KP 冷启动写库前 PG 备份 |
| `kp_relation_cold_start_*.csv` | P1 冷启动候选关系清单 |
| `kp_relation_cold_start_rollback_*.jsonl` | P1 冷启动关系 rollback 日志 |

---

## 8. 复测结果

### `kp_skeleton_audit.py`

```
KP 总数                                                  40
knowledge_type 分布                                      {'concept': 40}
同核心词簇数                                                0
被卷入碎片化的 KP 总数                                       0
跨包概念交集                                                0
aliases_json 非空的 KP 数                                  11
provenance 行数 / 有 provenance 的 KP 数                    53 / 40
```

清洗前：8 簇、26 个 KP 卷入碎片化；清洗后：0 / 0 ✓

### `graph_audit_real.py`

```
ege_dangling_kp_source / target / question_target          0 / 0 / 0
KnowledgeQuestionLink 总数                                 243
关联 KP 数 / 题数                                          33 / 61
EntityGraphEdge: question_item -> knowledge_point tests     234
Neo4j TESTS                                                 235（234 业务投影 + 1 考试会话）
knowledge_point_relations                                  44
Neo4j KP-KP 边                                              44
桥接覆盖率（包内）                                          100%
桥接覆盖率（全库）                                          2.8%（61 / 2153）
```

PG ↔ Neo4j 一致性：节点数、关系数、关系类型分布全部对齐。

---

## 9. 已知遗留 / Phase 2 起点

清洗只解决了"碎片化与脏数据"，下面这些**不是本轮目标**，需要后续阶段处理。

| 项 | 现状 | 优先级 | 处置建议 |
|---|---|---|---|
| KP-KP 冷启动与自动化抽取已完成 | 44 条冷启动关系已回填为 `approved`；新包入库时自动 LLM 抽取关系并以 `pending` 写入 | ✅ P1 完成 | 已新增 smoke 脚本、审核 CLI，并将 KP-KP 图谱投影收紧为只投影 `approved` / `explicit` 状态 |
| 5 条低相似度 DEMOTE 建议 | 因为合适的上位 KP 在本轮被一并清空 | P2 | 先补 3-5 个骨架 KP（"集合运算"、"集合关系"等），再跑一轮 DEMOTE |
| `subject` / `grade_scope` / `canonical_summary` 100% 空 | LLM 抽取阶段未填这些字段 | P2 | 数据补齐脚本：基于包元数据继承 subject/grade，基于 provenance block 提炼 canonical_summary |
| `name_substring_pairs = 7` | "全称量词 ⊂ 全称量词命题"等真实包含关系 | P1 | 不应合并，应建 `specializes` / `prerequisite` 边 |
| 摄入侧 dedup 第一版已完成 | 已覆盖同名、alias、常见 LLM 后缀变体、高阈值 trigram；暂未做 LLM 判定 | P1 | 后续可加 LLM 判定层，处理低相似但语义等价的复杂别名 |
| Qdrant 客户端版本警告 | client 1.13.2 vs server 1.17.1 | P3 | 升级 Python `qdrant-client` 到 1.16+ 或显式 `check_version=False` |

---

## 10. 回滚预案

### 完整回滚（首选，最安全）

```powershell
docker cp scripts\_out\backup_pre_kp_cleanup_20260507.dump exam-pg:/tmp/restore.dump
docker exec exam-pg pg_restore -U postgres -d exam_analysis --clean --if-exists /tmp/restore.dump
.venv_commercial\Scripts\python.exe scripts\neo4j_resync_after_cleanup.py
```

`pg_restore --clean` 会把当前 schema 全部清掉再 import，相当于把 PG 完整还原到 2026-05-07 11:54 时点。Neo4j 重投影脚本基于回滚后 PG 重建即可恢复一致状态。

### 细粒度逆操作（仅当主备份不可用时）

按 `scripts/_out/kp_cleanup_rollback_*.jsonl` 与 `ege_dangling_rollback_*.jsonl` 中每行的 `undo_hint` **逆序** INSERT。每行 JSONL 格式：

```json
{
  "ts": "...",
  "forward_op": "...",
  "undo_hint": "...",
  "kp_id": 1934,
  "rows": [...原行快照...]
}
```

涉及表：`knowledge_points` / `knowledge_atoms` / `knowledge_question_links` / `knowledge_package_points` / `entity_graph_edges` / `knowledge_point_relations` / `retrieval_documents` / `embedding_points` / `knowledge_blocks` / `knowledge_derivatives`。

> 主备份永远是首选；细粒度逆操作易出错。

---

## 11. Phase 2 建议路径

按"用最小成本止血 → 逐步建网"的顺序：

1. **已完成 — P0 / Layer 1 上游 dedup 第一版**：在 `analyzer/app/knowledge_point_dedup.py` 实现名称规范化、alias 匹配、概念 key、pg_trgm 高阈值匹配，并接入摄入与 API 创建入口。
2. **已完成 — P1 KP-KP 关系冷启动**：`scripts/kp_relation_cold_start.py` 已写入 44 条冷启动关系，并同步到 EGE / Neo4j。
3. **已完成 — P1 自动化延伸（LLM 摄入时自动抽取 KP-KP 关系）**：
   - 新增 LLM 步骤 `analyzer.topic_docx_kp_relations`（在 `shared/llm_step_config.py` 和 `shared/prompt_step_config.py` 注册，含种子提示词）。
   - 在 `analyzer/app/config.py` 新增开关 `KNOWLEDGE_POINT_RELATIONS_LLM_ENABLED`（默认 `true`）。
   - 在 `analyzer/app/knowledge_point_parser.py` 新增方法 `_extract_kp_relations_with_llm`，并在 `_ingest_topic_docx` 图谱投影前自动调用。
   - 行为：每次专题入库，LLM 对本包所有 KP 输出 prerequisite / specializes / equivalent / related 关系，confidence ≥ 0.70 的新关系写入 `knowledge_point_relations`（`source_origin='llm'`，`approved_status='pending'`），重复关系自动跳过；结果记录在 `metrics_json.kp_relations` 中。
   - 优雅降级：LLM 配置缺失 / 包内 KP < 2 / LLM 调用异常均只记录日志，不中断摄入流程。
4. **已完成 — P0/P1 闭环验证与审核闸**：
   - 新增 `scripts/kp_relations_llm_smoke.py`：可对指定/最近专题包调用 `_extract_kp_relations_with_llm`，默认 dry-run 回滚；本次验证 package_id=433、12 个 KP，LLM 产出 8 条新关系、跳过 6 条，最终回滚。
   - 新增 `scripts/kp_relations_review_cli.py`：支持交互式审核 `pending` 关系，也支持批量回填可信来源；本次已将 44 条 `source_origin='cold_start'` 关系从 `pending` 回填为 `approved`，rollback 日志为 `scripts/_out/kp_relations_review_rollback_20260507_141158.jsonl`。
   - `analyzer/app/knowledge_graph_projection.py` 已收紧 KP-KP 投影门槛：仅 `approved_status in ('approved', 'explicit')` 的 `knowledge_point_relations` 会进入 `entity_graph_edges` / Neo4j；新增 LLM `pending` 关系不会污染图谱。
   - 已运行 `scripts/neo4j_resync_after_cleanup.py` 和 `scripts/graph_audit_real.py`；当前 `knowledge_point_relations=44`，审核状态全部为 `approved`，Neo4j KP→KP 边仍为 44。
5. **已完成 — P2 检索量化基线第一版**：
   - 新增 `scripts/retrieval_benchmark.py`：从 `KnowledgeQuestionLink` 构造 ground truth，以真实题面为 query，评估 recall / graph / fusion 三条路线的 `hit@1`、`hit@5`、`hit@10`、`MRR`。
   - 脚本支持 `--recall-backend pg_text|hybrid`。其中 `pg_text` 是基于 `retrieval_documents` 的快速文本基线；`hybrid` 会调用现有向量+文本索引。
   - 已给 KP-KP 关系抽取和 smoke 增加占位 KP 过滤：`未归类知识点`、`llm_pending`、`fallback`、`placeholder` 不再进入 LLM 关系抽取。
   - 当前 `hybrid` 路径在首条 query 上长时间阻塞，初步判断是实时 embedding / Qdrant 调用链路问题；因此本次先落 `pg_text` 基线。
   - 全局 30 条基线暴露出索引覆盖问题：`package_id=428` 没有 active 知识库检索文档，导致召回为空。
   - 针对 `package_id=433` 的 30 条基线输出：`scripts/_out/retrieval_benchmark_20260507_144945.json` / `.md`。结果为 recall `hit@10=0.0333`、graph `hit@1=0.0333`、fusion `hit@5=0.0333`，说明当前文本召回与图谱扩展都还很弱，下一步应优先修复向量检索链路与知识库索引覆盖。
6. **已完成 — Bridge Projection**：`kg_projection.project_package` 已把 `KnowledgeQuestionLink` 投影成 `question_item → knowledge_point` 的 `tests` EGE 边。
7. **P2 后续 — 向量链路修复 / 元数据补齐**：先排查 `hybrid` 首条 query 阻塞和 `package_id=428` 检索文档缺失；随后做 subject/grade/canonical_summary 一次性脚本回填。
8. **P3 — 兜底约束**：在 `entity_graph_edges` 加 trigger，强制 `(source_entity_type, source_entity_id)` 与 `(target_entity_type, target_entity_id)` 必须存在；杜绝悬空边再次产生。

---

## 12. 速查指令卡

```powershell
# 当前状态
.venv_commercial\Scripts\python.exe scripts\kp_skeleton_audit.py
.venv_commercial\Scripts\python.exe scripts\graph_audit_real.py
.venv_commercial\Scripts\python.exe scripts\kp_dedup_smoke.py
.venv_commercial\Scripts\python.exe scripts\kp_relation_cold_start.py
.venv_commercial\Scripts\python.exe scripts\kp_relations_llm_smoke.py --limit 12
.venv_commercial\Scripts\python.exe scripts\kp_relations_review_cli.py --limit 20
.venv_commercial\Scripts\python.exe scripts\retrieval_benchmark.py --package-id 433 --max-cases 30 --recall-backend pg_text

# 重新评估清洗（dry-run）
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_proposal.py
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_migration.py

# 真做（务必先备份）
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_migration.py --apply --purge-vectors-after-commit
.venv_commercial\Scripts\python.exe scripts\ege_dangling_cleanup.py --apply
.venv_commercial\Scripts\python.exe scripts\neo4j_resync_after_cleanup.py

# 前后对比
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_compare.py snapshot --tag before
# 执行清洗 ...
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_compare.py snapshot --tag after
.venv_commercial\Scripts\python.exe scripts\kp_cleanup_compare.py diff
```
