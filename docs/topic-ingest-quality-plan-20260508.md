# 专题摄入质量优化计划（2026-05-08）

## 背景

当前我们已经确认：专题摄入的“数量指标”不差，但 `package_id=443` 暴露出几个更关键的质量问题：

1. 题目结构化不稳定  
   - 复合题 / 子题 `(1)(2)` / 大题共用解答时，容易被切成坏题。
   - 部分题目把 `解：...` 吞进 `stem`，导致 `answer/solution` 为空。
   - 存在“标签题 / 空壳题”，例如只剩 `对点练3.`。

2. 图谱节点落地不够扎实  
   - 一部分知识点更像块级 LLM 概括点，而不是有 block/atom/question 充分支撑的 grounded point。
   - 存在 `未归类知识点` 这类兜底节点进入正式包覆盖。

3. KP-KP 关系已生成但未投影  
   - `knowledge_point_relations` 已有高置信关系，但因为 `approved_status="pending"` 未进入 `entity_graph_edges`。

## 本轮目标

本轮优先解决“题目结构化质量”，暂不优先处理图谱投影。

原因：

- 坏题会直接影响报告质量、题目检索质量、题-知识点桥接真实性。
- 图谱边是否投影，当前更多影响可视化与图遍历，不是最核心阻塞。

## 优化原则

1. 不做只对单个题目生效的特判。
2. 规则要适配同一本书后续专题文档的共性格式。
3. 优先修“分段/结构化”层，而不是靠后置补救掩盖上游错误。
4. 对明显坏题要报错或拦截，不要静默入库。

## 计划步骤

### 步骤 1：增强复合题解析

目标：让以下常见教材组织形式稳定解析：

- `11. ... (1) ... (2) ...`
- `13. ...`
  `（1）...`
  `（2）...`
  `解：...`
- `对点练1.解下列...`

具体方向：

- 合并“母题 + 连续子题”结构，避免把公共题干误落成独立题。
- 支持识别 `stem` 中嵌入的 `解：/解答：/证明：/解析：`，拆到 `solution/analysis`。
- 对共享答案/共享解答的子题群保持结构一致，不再出现前题无解、后题吞全部解答。

### 步骤 2：增加专题题质量闸门

对以下题段判为高风险或坏题：

- `stem` 只剩题号、`对点练N.`、`(1)`、`(2)` 等标签。
- 选择题没有选项。
- 主观题在结构化后 `answer/solution` 同时为空，且 `stem` 明显异常。
- 公共题干被拆成孤立题，后续子题再被单独入库。

处理原则：

- 严格模式下直接失败。
- 非严格模式下至少显式记录问题，不允许无提示通过。

### 步骤 3：回归 443 号专题包

重点看：

- `8275` 这类 stem 吞解答问题是否消失。
- `8290~8295` 这类大题/子题是否不再拆坏。
- `8278` 这类标签题是否被拦截或暴露为上游抽取问题。

### 步骤 4：下一轮再处理图谱优化

待题目结构化稳定后，再继续做：

- grounded_point / candidate_point 分层
- `未归类知识点` 清理
- `pending` KP-KP 关系的投影策略

## 当前判断

“当前检索优化”不等于“专题摄入优化完成”。

当前更准确的状态是：

- 检索链路：已有可用基线
- 专题题摄入：仍需继续优化
- 图谱关系：可以下一轮再回到深水区

## 2026-05-08 图谱质量进展（package 444，实库校验）

这一轮已经按真实 PostgreSQL 数据做了图谱侧修复，不是文档复述。

### 已完成

1. `未归类知识点` 清理  
   - 发现 `package_id=444` 残留的占位 block 实际是一个纯图片 banner，内容只有 `[图片]`，不承载可用知识语义。
   - 已增加通用清理规则：对“仅图片占位、无文本/公式/表格语义”的 placeholder block，不再继续挂到正式知识点上。
   - 清理后 `444` 的 placeholder package point 已从 `1` 降到 `0`。

2. grounding 口径修正  
   - 发现大量 package point 虽然没有落到 `knowledge_blocks.knowledge_point_id` 主外键上，但已经有
     `knowledge_point_provenance(source_kind=knowledge_block)` 作为块级证据。
   - 已把这类 provenance 正式纳入 grounding 判定，而不再只看 block/atom 单外键。
   - 修复后 `444` 从 `grounded=4 / candidate=12 / placeholder=1`
     变为 `grounded=16 / candidate=0 / placeholder=0`。

3. 图谱投影修正  
   - `knowledge_point -> knowledge_block` 不再只投影主外键 grounding；
     现在也投影基于 `knowledge_point_provenance` 的多知识点块级证据。
   - `444` 当前真实结果：
     - package points: `16`
     - grounded: `16`
     - placeholder: `0`
     - `knowledge_point -> knowledge_block` edges: `16`
     - 其中 `block_fk=4`，`knowledge_point_provenance=12`

### 当前仍值得继续优化的点

图谱“连通性”这一轮已经明显改善，但“专题纯度”还没完全收口。

实际数据里仍能看到一些点虽然有块级证据，却更像：

- 例题依赖知识
- 横向比较方法
- 邻接知识，而不是本专题主教学目标

例如 `集合的交并运算` 在 `444` 中有真实 provenance，
但它更接近真题讲解时引入的依赖知识，不一定应作为专题正式覆盖点长期保留。

## 下一步主线（更新）

题目结构化这一轮可以先收口；图谱质量这一轮的下一步，不再是补“是否连上”，而是做“连得准不准”：

1. 包内知识点 topic relevance / purity 过滤  
   - 区分“本专题主知识点”与“例题依赖点 / 邻接点 / 比较点”
   - 避免因为 LLM 在长 block 上过度概括，导致包覆盖点泛化过宽

2. candidate/grounded 证据分层细化  
   - 当前已把 provenance 计入 grounded
   - 下一步可补充 grounded_source（block_fk / provenance / atom / mixed）这类更细标签，方便后续审计和 UI 呈现

3. 继续观察高置信 KP-KP 投影质量  
   - 现在高置信 pending 关系已可投影
   - 下一步重点看关系是否“语义合理”，而不是只看数量是否增加

## 2026-05-08 图谱质量进展（第二轮：package point purity）

这一轮已经开始做“连得准不准”，不是继续堆连通性。

### 本轮实现

1. package point purity 分类  
   - 新增包内知识点 purity 重算：
     - `core`：专题主知识点
     - `adjacent`：专题邻接/延伸点，保留在正式 coverage
     - `dependency`：例题依赖点/跨专题借用点，不再计入正式 coverage
   - 分类使用：
     - package title
     - core points
     - evidence blocks
     - 与 core 的知识点关系
     - LLM 严格判别（失败显式报错，不静默降级）

2. package coverage 下游联动  
   - `dependency` 点已从以下口径中排除：
     - `knowledge_package -> covers_point` 图谱投影
     - 包级 RAG / retrieval 的 `knowledge_package_point`
     - package 过滤检索时允许命中的 package-point 集合
   - 这样 package 级检索与图谱 coverage 会更干净，不再把例题借用点和主知识点混在一起

### 实库验证（package 444）

真实跑库结果：

- purity 分类：
  - `core = 4`
  - `adjacent = 5`
  - `dependency = 7`
- 典型结果：
  - `三个二次关系（判别式、图象、根与解集）` -> `adjacent`
  - `一元二次不等式恒成立充要条件` -> `adjacent`
  - `分式不等式解法` -> `dependency`
  - `绝对值不等式解法` -> `dependency`
  - `集合的交并运算` -> `dependency`
- 联动结果：
  - `covers_point` edges: `16 -> 9`
  - package-level `knowledge_package_point` retrieval docs: `9`
  - 题桥接覆盖率仍保持 `24 / 24`
  - package 图谱总边数：`313 -> 297`

### 横向抽样回归

已对旧专题做回归抽样（未提交这些包的结果，只做验证）：

1. `428 第一节 集合`
   - 结果方向基本合理
   - `集合运算与不等式结合求解`、`集合运算中端点取舍与验证` 被识别为 `dependency`
   - `元素与集合的属于关系`、`集合的表示法`、`德摩根定律` 被保留为 `adjacent`

2. `438 第四节 基本不等式及其应用`
   - 结果方向基本合理
   - `分离参数法`、`换元法求最值`、`基本不等式与换元法结合` 被识别为 `dependency`
   - `基本不等式定义`、`算术平均数与几何平均数`、`利润最大化建模` 被保留为 `adjacent`

## 下一步主线（更新）

package point purity 这一轮已经能开始收噪，但还没到最终形态。下一步更值得做的是：

1. dependency 点的题桥接使用策略  
   - 现在 package coverage 已排除了 dependency
   - 但后续要进一步明确：dependency 点的题桥接是否只保留在 point 级，不再进入 package 级报告摘要

2. purity 审计可视化 / explainability  
   - 把每个点为什么被判为 `adjacent` / `dependency` 的证据暴露出来
   - 方便后续人工 spot check，而不是只看最终标签

3. 再回到 KP-KP 关系质量  
   - 现在 coverage 更干净后，再看 KP-KP 投影，误导性会比之前小很多

## 2026-05-08 图谱质量进展（第三轮：dependency 点题桥接使用策略）

这一轮的目标，是把 dependency 点的题桥接边界切清楚：

- point 级：保留  
  因为它们仍然是题目分析、知识追溯、方法依赖的重要证据
- package 级：收口  
  不再让 dependency 点进入专题正式桥接摘要 / package related questions / package fallback bridge 口径

### 本轮实现

1. package related questions 过滤  
   - `list_package_related_questions()` 现在只统计 package coverage 点（`core + adjacent`）
   - `dependency` 点不再进入专题相关题列表和桥接汇总

2. package detail 桥接统计联动  
   - `build_knowledge_package_detail()` 里的：
     - `bridged_question_count`
     - `orphan_in_material_count`
     - `related_questions`
   - 现在都基于“coverage bridge”而不是“所有 bridge”

3. package fallback bridge 过滤  
   - `backfill_package_question_bridge()` 现在只允许在 coverage 点集合里补桥接
   - 不会把 `dependency` 点当成包内代表知识点

### 实库验证（package 444）

真实数据结果：

- package related questions: `24`
- package bridged coverage: `24 / 24`
- orphan in material: `0`
- fallback backfill:
  - `new_links = 0`
  - `allowed_point_count = 9`
  - `representative_point_id = 2188`

这说明：

- package 视角下，`444` 的 coverage bridge 仍然完整
- dependency 点被排除后，没有把专题桥接打断

同时确认：

- dependency 点自己的 `KnowledgeQuestionLink` 仍然保留  
  例如：
  - `含参不等式的分类讨论（系数、判别式、根大小）` 仍有 `15` 条 question links
  - `集合的交并运算` 仍有 `5` 条 question links
  - `分式不等式解法` 仍有 `3` 条 question links

也就是说，这轮做到的是“package 不吃，point 还在”。

### package retrieval 再核验

已再次确认：

- `package_id=444` 的 package-level `knowledge_question_bridge` retrieval 文档中
  `dependency` 点数量为 `0`

因此目前 package 侧三条口径已经一致：

1. `covers_point`
2. `knowledge_package_point` retrieval
3. `knowledge_question_bridge` retrieval / package related questions

都只认 `core + adjacent`。

## 2026-05-08 KP-KP 关系质量回归（真实库审计）

本轮没有复述旧文档结论，而是直接基于 PostgreSQL 实库新增只读审计脚本：

- `scripts/kp_relations_package_audit.py`

审计口径：

1. 只看 package coverage points（`core + adjacent`）
2. 拉取两类 KP-KP 关系：
   - `evidence_block_id` 落在本包 block 内
   - `evidence_block_id is null` 且 source/target 至少一端触达本包 coverage points
3. 对每条关系显式输出：
   - 是否满足当前投影门槛
   - 是否已经落到 `entity_graph_edges`
   - evidence block 预览
   - 是否触达包外点
   - 保守的 review flags（不直接判死刑，只标“值得复核”）

### package 444：第五节 一元二次函数、方程和不等式

真实结果：

- coverage points：`9`
- 审计范围内 KP-KP 关系：`13`
- 满足投影门槛：`9`
- 已投影到 `entity_graph_edges`：`9`

结论：

1. `444` 的高置信 LLM 关系已经实际进图，不是“关系没生效”
2. 但 `13/13` 关系都没有 `evidence_block_id`
   - 说明当前 KP-KP 抽取仍然主要是“包级抽象判断”
   - 不是“由具体 block 证据支撑的 grounded relation”
3. 其中有一小批关系值得重点回归：
   - `含参数的一元二次不等式解法 -> 含参不等式的分类讨论（系数、判别式、根大小） [specializes]`
   - `含参不等式的分类讨论（系数、判别式、根大小） -> a=0时一元二次不等式求解注意事项 [specializes]`
   - `一元二次不等式的解法 -> 解一元二次不等式的四个步骤 [related]`
4. 这些问题不是“完全错误”，但暴露出当前 `specializes / related` 仍有链路偏松、跨层级跳连的问题

### package 438：第四节 基本不等式及其应用

真实结果：

- coverage points：`7`
- 审计范围内 KP-KP 关系：`10`
- 满足投影门槛：`6`
- 已投影到 `entity_graph_edges`：`0`

结论：

1. `438` 的问题比 `444` 更明确：关系表里已经有高置信 LLM 关系，但图层没有同步出来
2. 审计确认存在 `6` 条 `projectable_but_not_projected`
3. 这不是抽象判断，而是实库中可直接观测到：
   - `knowledge_point_relations` 里存在高置信 pending+llm 关系
   - `entity_graph_edges` 里当前没有对应 KP-KP 边
4. 高概率原因不是投影规则写错，而是历史 package 没有做过一次“按新规则重投影 / reconcile”

典型缺口：

- `利用基本不等式求最值 -> 配凑法求最值 [specializes]`
- `基本不等式定义 -> 基本不等式的证明 [prerequisite]`
- `不等式证明 -> 基本不等式的证明 [specializes]`
- `基本不等式定义 -> 基本不等式的实际应用 [prerequisite]`

### 这轮审计给出的主判断

当前 KP-KP 关系的主问题，不是“数量不够”，而是下面两件事：

1. `grounding` 不够
   - 当前 LLM 关系大量缺少 `evidence_block_id`
   - 这会让关系可解释性弱，也不利于后续自动审计和人工复核
2. 历史包投影不一致
   - 新规则已经允许高置信 `pending + llm` 关系进图
   - 但旧 package 没有统一重投影，导致 `438` 这类包出现“表里有关系，图里没有边”

### 下一步优先级（基于真实数据，不是文档推演）

1. 先补一个 package graph reconcile / reproject 工具
   - 面向历史 package 批量重建 `entity_graph_edges`
   - 先解决 `438` 这种“关系已存在但图未同步”的一致性问题
2. 再收紧 KP-KP 抽取的 grounding 约束
   - 要求 LLM 输出 relation 时尽量绑定 `evidence_block_id`
   - 没有明确证据块时，不要静默包装成“像是很扎实的图谱关系”
3. 最后做 relation-type 质量回归
   - 重点看 `specializes` 是否跨层级跳连
   - 区分“方法分型 / 例题步骤 / 应用场景 / 真正下位概念”

### 本轮已落地的修复动作

新增维护脚本：

- `scripts/reconcile_package_graph.py`

已对真实库执行：

- `package_id=438`

执行结果：

- reconcile 前：`kp-kp edges touching coverage = 0`
- reconcile 后：`kp-kp edges touching coverage = 6`
- reconcile 后再次审计：`projectable / projected = 6 / 6`

这说明：

1. `438` 的“图里没有 KP-KP 边”已经被真实修复
2. 当前剩下的主问题，已经收敛为“关系 grounding 不够”和“relation type 语义回归”

## 2026-05-08 KP-KP grounding 收紧（真实包回归）

这一轮不是停留在审计结论，而是把 KP-KP 抽取源头和历史维护链路一起收紧了。

### 已实现

1. KP-KP 抽取时序调整
   - `knowledge_point_parser.py`
   - 关系抽取从“grounding 后、purity 前”改为“package point purity 收口后再抽”
   - 这样进入关系抽取的点集，已经先排除了 `dependency`

2. KP-KP 抽取改为 evidence-block grounded
   - 不再只把一组知识点名称扔给 LLM
   - 现在会为每个候选知识点收集真实 package 内证据块：
     - `knowledge_blocks.knowledge_point_id`
     - `knowledge_point_provenance(source_kind=knowledge_block)`
   - LLM prompt 升级到 v2，要求每条关系必须返回 `evidence_block_id`
   - 后端只接受：
     - `source/target` 在候选点集中
     - `evidence_block_id` 来自 source/target 的允许证据块集合
   - 没有证据块的关系，不再落库

3. no-evidence 关系的包级边界收紧
   - `knowledge_graph_projection.py`
   - 对 `evidence_block_id is null` 的 KP-KP 关系，投影条件从“任一端点在包内”改为“两端都在包内 coverage”
   - 避免旧的包外关系因为“碰到一个包内点”被带进当前专题图谱

4. 历史包重抽维护脚本
   - 新增 `scripts/reextract_package_kp_relations.py`
   - 支持：
     - 删除包级旧 LLM KP-KP 关系
     - 按新 grounding 规则重抽
     - 抽取成功后立即重投影
   - 脚本带事务保护：如果重抽失败，会回滚，不会把包留在半空状态

5. 旧无证据关系清理范围收紧
   - 清理口径不再只看当前 `knowledge_package_points`
   - 还纳入 package 内：
     - blocks 挂载点
     - atoms 挂载点
     - provenance 挂载点
   - 用来删除历史上曾经属于该包、后来被 purity 收掉的旧 `evidence_block_id is null` LLM 关系

### 真实回归：package 444

先做环境核对：

- `analyzer.topic_docx_kp_relations` prompt 已解析到 `resolved_version = 2`
- `package 444` 当前可进入 KP-KP 抽取的 candidate points = `9`
- 这 `9` 个点全部都能拿到真实 evidence blocks

然后对真实库执行：

- `scripts/reextract_package_kp_relations.py --package-id 444 --delete-existing-llm --reproject`

结果：

- 第一次重抽：
  - 旧包级 LLM 关系：`12` 条（grounded `0`）
  - 删除后按新规则重抽：`4` 条（grounded `4`）
- 收紧 no-evidence 包边界并再次重抽后：
  - 包内 LLM 关系：`6` 条
  - grounded：`6`
  - 审计结果：`projectable / projected = 6 / 6`

当前 `444` 实际留下的 6 条关系，全部都有 `evidence_block_id`，不再存在“入图的是一串无证据抽象关系”的情况。

### 这轮之后的判断

KP-KP 这条线现在已经从“关系能不能进图”推进到“关系是否语义合理”阶段。

也就是说，grounding 问题这一轮基本已经打住，剩下最值得继续优化的是：

1. relation type 语义回归
   - 例如 `specializes` 和 `prerequisite` 是否存在层级方向偏差
   - 是否把“步骤/注意事项/题型角度”误当成稳定概念层级

2. evidence 选择质量
   - 当前虽然已经强制绑定 `evidence_block_id`
   - 但仍有一部分关系命中的 block 更像“题型讲解块”，不是最直接的概念关系证据块
   - 下一步可以继续优化“证据块排序与约束”，让 relation grounding 更贴近概念定义/方法总结块

## 2026-05-08 relation type 语义回归（真实包回归）

这一轮继续往前推的重点，不是再补更多边，而是把“边的类型和方向”收干净。

### 已实现

1. 候选点收口到 `core + adjacent`
   - `KnowledgePointRelation` 的 LLM 抽取候选点，现在只允许 package point `relation_type in {"core", "adjacent"}`
   - `dependency / supplement / placeholder / fallback` 都不再进入 KP-KP 抽取

2. 历史包重抽前先跑 purity 重分类
   - `scripts/reextract_package_kp_relations.py`
   - 先执行 `_reclassify_package_point_purity()`，再删旧关系、重抽、重投影
   - 这样旧包不会继续带着历史 `supplement` 口径抽关系

3. relation-type 保守验收规则
   - 在 `knowledge_point_parser.py` 增加了 LLM 关系后验验证
   - 重点拦截：
     - `specializes` 方向反了
     - `specializes` 焦点不一致（如“求参数范围”压到“求最值”）
     - `prerequisite` 从“步骤/注意事项”出发去指向主方法/主概念
     - `equivalent` 但语义族相差太远

4. 审计脚本同步升级
   - `scripts/kp_relations_package_audit.py`
   - 审计不再把“求最值”这种清晰的同任务分型一律报成弱关系

### 真实回归结果：package 438

第一次 grounding 收紧后，`438` 虽然已经摆脱了无证据关系，但还残留明显的历史包问题：

- package point 仍是：
  - `core = 7`
  - `supplement = 12`
- 重抽后虽然变成 grounded 关系，但仍偏宽：
  - `21` 条关系
  - 其中不少是旧 `supplement` 点带来的方法/应用混杂关系

继续收紧后，再次对真实库执行：

- `scripts/reextract_package_kp_relations.py --package-id 438 --delete-existing-llm --reproject`

最新结果：

- purity 重分类后：
  - `core = 7`
  - `adjacent = 8`
  - `dependency = 4`
- 删除旧 grounded 关系：`21`
- 新规则重抽后：`7`
- 全部 `7` 条都有 `evidence_block_id`
- 审计结果：`projectable / projected = 6 / 6`

当前 `438` 保留下来的主关系已经收口为：

- `基本不等式定义 -> 利用基本不等式求最值 [prerequisite]`
- `利用基本不等式求最值 -> 配凑法求最值 [specializes]`
- `利用基本不等式求最值 -> 常数代换法求最值 [specializes]`
- `利用基本不等式求最值 -> 换元法求最值 [specializes]`
- `利用基本不等式求最值 -> 消元法求最值 [specializes]`
- `基本不等式定义 -> 算术平均数与几何平均数 [related]`
- `一正二定三相等 -> 利用基本不等式求最值 [related]`

和前一轮相比，明显被去掉的就是那些：

- 方向反了的 `specializes`
- 不同任务焦点硬压在一起的 `specializes`
- 历史 `supplement` 点牵出来的泛化关系

### 真实回归结果：package 444

`444` 在这一轮没有再大幅动，但在当前规则下已经收口到：

- `5` 条 grounded KP-KP 关系
- `projectable / projected = 5 / 5`

当前主要剩下的是三条 `related`：

- `不含参数的一元二次不等式解法 -> 含参数的一元二次不等式解法`
- `不含参数的一元二次不等式解法 -> 解一元二次不等式的四个步骤`
- `含参数的一元二次不等式解法 -> 解一元二次不等式的四个步骤`

这说明：

- `444` 现在的主问题已经不是方向错边
- 而是 `related` 是否还要继续收紧，尤其是“步骤类点”是否应该只保留在包内 explainability，不进入正式 KP-KP 主干

### 当前判断

到这一步，KP-KP 主线已经从：

- “能不能进图”
- “有没有 evidence_block”

推进到了：

- “哪些关系值得成为正式图谱主干”

所以下一轮最值得做的，不再是泛泛地补边，而是：

1. `related` 关系收口
   - 尤其是步骤类 / 口诀类 / 注意事项类点
   - 判断它们是否应只保留在 package explainability，不进入稳定 KP-KP 主干

2. evidence block 排序继续优化
   - 当前大多数关系已经有 block 证据
   - 但 block 仍偏“题型讲解块”，不够像“概念定义块 / 方法总结块”
   - 可以继续提升 relation grounding 的可解释性
