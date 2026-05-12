# Topic Ingest Checkpoint (2026-05-09)

## Scope

This checkpoint records the current state before opening wider batch ingest for topic packages.

Current goal:

- make topic package ingest safe enough for larger-scale intake
- keep retrieval and graph layers aligned with real package data
- avoid silent success when retrieval or projection is incomplete

## What Was Fixed In This Round

### 1. Topic ingest quality gate is now executable

File:

- `D:\10739\Exam-Analysis-Suite\scripts\topic_ingest_quality_gate.py`

It now performs real package checks against the live database:

- `parse_status`
- point count
- question count
- question-link coverage
- retrieval doc count
- embedding coverage
- package point purity stability
- placeholder residue
- grounded LLM KP-KP relation count
- relation projection summary

### 2. Topic ingest main flow now syncs package retrieval

File:

- `D:\10739\Exam-Analysis-Suite\analyzer\app\knowledge_point_parser.py`

Change:

- after topic questions are persisted, if `KNOWLEDGE_RAG_ENABLED=true`, ingest now calls:
  - `sync_knowledge_package_retrieval(db, package.id)`
- retrieval sync result is returned in ingest output and stored in parse metrics

Reason:

- package `445` showed a real failure mode:
  - ingest data existed
  - package graph existed
  - but `retrieval_docs=0`, so package retrieval layer was missing

This is now a hard step in the main ingest path instead of a manual afterthought.

### 3. Pending LLM KP-KP auto-projection is now stricter

Files:

- `D:\10739\Exam-Analysis-Suite\analyzer\app\knowledge_graph_projection.py`
- `D:\10739\Exam-Analysis-Suite\scripts\kp_relations_package_audit.py`

For pending high-confidence LLM relations, auto-projection now requires:

- `evidence_block_id` exists
- evidence block belongs to the current package
- evidence preview mentions at least one endpoint name fragment
- `related` is rejected when it looks like a same-family variant pair

`approved` / `explicit` relations are not blocked by this stricter pending-LLM guard.

The audit script now uses the same projectable logic as the projection layer.

## Real Validation Run

### Gate run before retrieval repair

Command:

```powershell
.\.venv_commercial\Scripts\python.exe scripts\topic_ingest_quality_gate.py --package-id 428 --package-id 433 --package-id 438 --package-id 445
```

Observed hard fail:

- package `445`
  - `retrieval_docs=0`
  - `embedding_points=0`

### Real retrieval rebuild for package 445

Executed:

```python
sync_knowledge_package_retrieval(db, 445)
```

Observed result:

- `indexed_documents = 115`
- `vector_backend = qdrant`
- `text_backend = opensearch`
- `vector_dim = 1024`
- `embedding_model = BAAI/bge-large-zh-v1.5`
- elapsed about `84.45s`

### Gate run after retrieval repair

Observed result:

- `428 PASS`
- `433 PASS`
- `438 PASS`
- `445 PASS`

Output:

- `D:\10739\Exam-Analysis-Suite\scripts\_out\topic_ingest_quality_gate_20260509_160457.json`
- `D:\10739\Exam-Analysis-Suite\scripts\_out\topic_ingest_quality_gate_20260509_160718.json`

## Current KP-KP Projection State

After re-projecting packages `428 / 433 / 438 / 445` with the stricter pending-LLM guard:

- `428`: `projectable / projected = 4 / 5`
- `433`: `projectable / projected = 28 / 28`
- `438`: `projectable / projected = 2 / 2`
- `445`: `projectable / projected = 0 / 0`

Interpretation:

- the graph is now more conservative
- weakly evidenced pending LLM edges are less likely to pollute the formal KP-KP backbone
- package `445` still has grounded relations in storage, but its current evidence previews are not strong enough for formal auto-projection

## Current Status

### Batch-ingest hard gate

For the four validated sample packages, the current state is acceptable:

- no placeholder residue
- purity is stable
- retrieval exists
- embeddings exist
- question-link coverage is full

### Remaining graph-quality gap

The main remaining issue is no longer:

- missing retrieval docs
- placeholder leakage
- silent package success with incomplete indexing

It is now:

- finer-grained point grounding
- better evidence quality for KP-KP relations
- especially for packages whose relation evidence still lands on broad summary blocks

## Next Steps

1. Improve point grounding granularity
   - replace shared summary provenance with more precise block / atom / question evidence where possible
   - increase the share of relations whose evidence explicitly names the endpoints

2. Continue relation-type quality regression
   - focus on `related`
   - separate true stable semantic relations from step-like or variant-like package-local explainability links

3. Keep gate-first intake for new topic packages
   - ingest
   - run `topic_ingest_quality_gate.py`
   - run targeted relation audit if needed
   - only then treat the package as graph-ready

## Update: Grounding Refinement (2026-05-09 later)

Additional changes:

- improved Chinese point-name mention matching for KP-KP grounding / audit / projection
- added atom-level snippet support into relation grounding candidate selection
- reprojected packages `438` and `445` after the stricter grounding pass

Observed result after reproject:

- `438`: `projectable / projected = 3 / 3`
- `445`: `projectable / projected = 2 / 2`

This is a real improvement over the earlier state where:

- `445` was `0 / 0`
- `438` was `2 / 2`

Current remaining gap is narrower:

- some packages still keep a non-trivial `evidence_no_endpoint_mention` residue
- package `433` still has many broad `related` relations and many no-evidence rows

So the next optimization target is now more specific:

1. continue shrinking `evidence_no_endpoint_mention`
2. then tighten `related` relation quality, especially broad same-family or package-explainability links

## Update: Topic DOCX Ingest Repair (2026-05-09 evening)

Scope:

- repair real ingest quality for source document `192`
- prioritize question parsing and content-block integrity
- do not accept parser fallback that hides errors behind degraded output

Files changed:

- `D:\10739\Exam-Analysis-Suite\analyzer\app\knowledge_point_parser.py`

Real validation target:

- `D:\10739\Exam-Analysis-Suite\analyzer\knowledge_points\1 第一节　函数的概念及其表示.docx`

What was fixed in this round:

1. Question parsing regained the missing first multiple-choice question.
2. False synthetic question extraction from explanatory content was removed.
3. Grouped subquestions under drill / presentation sections remain detectable.
4. Content segments are now pruned against refined question spans before persistence.
5. Assessment headers and presentation-only wrappers are no longer persisted as knowledge blocks.
6. Question tables now stay inside question segments instead of being split into fake content blocks.

Latest real ingest result:

- package `450`
- content blocks `5`
- atoms `7`
- package points `15`
- topic questions `42`
- question bridge coverage `42/42`
- retrieval docs `224`
- embeddings `224`
- graph edges inserted `471`

Real audit result:

- `topic_ingest_health_audit.py --package-id 450`
  - question-link coverage `1.0`
  - no placeholder residue surfaced for this package
- `topic_ingest_quality_gate.py --source-document-id 192`
  - still `FAIL`
  - remaining fail reason: `grounded_llm_kp_relations = 0`

Interpretation:

- question-structure quality is materially better and no longer the main blocker for this topic package
- content backbone is no longer polluted by `[教材呈现]` wrappers or test-section metadata
- current main gap has shifted back to graph relation generation, not DOCX question splitting

Checkpoint intent:

- this state is suitable as the parser checkpoint before switching the main line back to `KP-KP grounding / relation generation`

## Update: KP-KP Mainline Restored (2026-05-09 night)

Root cause found:

- topic DOCX ingest main flow had `_extract_kp_relations_with_llm()` implemented
- but the main ingest path did not call it after block-point enrichment
- result: package data could look healthy while `grounded_llm_kp_relations` stayed at `0`

Fix applied:

- after block-point LLM enrichment and placeholder reconcile, refresh `package_point_links`
- call `_extract_kp_relations_with_llm()` inside the main topic ingest path
- keep rule-based validation active so low-evidence relations are still filtered
- additionally tightened `related` relation validation so partial-evidence links are rejected

Real verification:

1. Re-extract on existing package `450`
   - grounded relations rose from `0` to `6`
2. Full reingest for source document `192`
   - latest package: `451`
   - ingest log showed `KP-KP extraction: package=451 inserted=3 skipped=1 rule_rejected=2`
3. After one focused re-extract / reproject pass on `451`
   - grounded scoped LLM relations: `13`
   - projected / projectable: `8 / 8`

Latest quality gate result for `451`:

- `PASS`
- `points=17`
- `questions=42`
- `question_link_coverage=1.0`
- `retrieval_docs=224`
- `embeddings=224`
- `grounded_llm_kp_relations=13`

Current remaining gap:

- one residual audit anomaly remains: `evidence_no_endpoint_mention=1`
- it is currently a non-projected relation and no longer blocks the package quality gate
- next cleanup target should be improving endpoint mention grounding / normalization, not reopening question parsing

## Update: KP-KP Evidence Mention Tightening (2026-05-09 21:18)

Problem observed on real data:

- package `451` still allowed a false `related` edge:
  - `函数的表示法 -> related -> 求函数解析式的方法`
- root cause was not the LLM alone; the local evidence check treated generic suffix fragments like `方法` as a valid endpoint mention
- after tightening that one layer, a re-extract exposed a second issue:
  - `prerequisite` could still over-accept broad `概念 -> 方法` links when only shared package grounding existed

Fix applied:

- tightened `_kp_relation_name_fragments()` and the matching helpers used by:
  - `analyzer/app/knowledge_point_parser.py`
  - `analyzer/app/knowledge_graph_projection.py`
  - `scripts/kp_relations_package_audit.py`
- generic fragments such as `概念 / 定义 / 方法 / 解法 / 求法 / 步骤` no longer count as endpoint mentions by themselves
- tightened `prerequisite` validation:
  - reject when the source endpoint is not grounded in the evidence and there is no close lexical/focus overlap
  - reject `concept -> distant method` prerequisite links

Real verification on package `451`:

1. `reextract_package_kp_relations.py --package-id 451 --delete-existing-llm --reproject`
   - final extract summary:
     - `inserted=7`
     - `rule_rejected=3`
     - reject reasons:
       - `prerequisite_evidence_weak=1`
       - `prerequisite_concept_to_distant_method=2`
2. `kp_relations_package_audit.py --package-id 451`
   - `Relations in audit scope: 7`
   - `Projectable / projected: 7 / 7`
   - `Top anomaly flags: (none)`
3. `topic_ingest_quality_gate.py --package-id 451`
   - `PASS`
   - `grounded_llm_kp_relations=7`
   - `questions=42`
   - `question_link_coverage=1.0`
   - `retrieval_docs=224`
   - `embeddings=224`

Current accepted package-451 relations:

- `函数的概念 -> prerequisite -> 函数的定义域`
- `函数的概念 -> prerequisite -> 函数的值域`
- `函数的概念 -> prerequisite -> 函数的表示法`
- `函数的概念 -> prerequisite -> 分段函数`
- `分段函数 -> prerequisite -> 分段函数不等式的分类讨论`
- `函数的定义域 -> prerequisite -> 具体函数定义域的求法`
- `函数的定义域 -> prerequisite -> 抽象函数定义域的求法`

Interpretation:

- graph quality is now cleaner than the previous `7 relations with one weak related edge` state
- this round deliberately prioritized `false positive reduction` over relation-type richness
- the next graph-quality target should be `method hierarchy semantics`:
  - recover stable `specializes` edges only when hierarchy evidence is explicit enough

## Update: Method Hierarchy Probe Rolled Back (2026-05-09 21:39)

What was tried:

- attempted a narrow `specializes` recovery for method-family pairs
- goal was to lift clear hierarchy cases such as generic definition-domain methods vs abstract / composite variants

What happened on real re-extracts:

- the experiment itself was not stable enough
- one run dropped package `451` down to `4` grounded relations
- after rolling the probe back and re-running real extraction, package `451` recovered to a healthier state with `9` grounded relations and no audit anomalies

Current verified state for package `451`:

- `kp_relations_package_audit.py --package-id 451`
  - `Relations in audit scope: 9`
  - `Projectable / projected: 9 / 9`
  - `Top anomaly flags: (none)`
- `topic_ingest_quality_gate.py --package-id 451`
  - `PASS`
  - `grounded_llm_kp_relations=9`
  - `questions=42`
  - `question_link_coverage=1.0`
  - `retrieval_docs=224`
  - `embeddings=224`

Current accepted relations:

- `函数的概念 -> prerequisite -> 函数的定义域`
- `函数的概念 -> prerequisite -> 函数的值域`
- `函数的概念 -> prerequisite -> 函数的表示法`
- `函数的定义域 -> prerequisite -> 具体函数定义域的求法`
- `函数的定义域 -> prerequisite -> 抽象函数定义域的求法`
- `函数的值域 -> prerequisite -> 函数值域的求法`
- `分段函数 -> prerequisite -> 分段函数不等式的分类讨论`
- `分段函数 -> prerequisite -> 分段函数的定义域与值域`
- `函数的定义域 -> prerequisite -> 函数定义域的求法`

Conclusion:

- this package is currently in a better single-package state than the earlier `7 relation` checkpoint
- the next safe optimization target is no longer `specializes` typing itself
- the next safe target is `relation extraction stability`:
  - inspect prompt / payload variance
  - persist raw extracted candidate rows for audit
  - compare repeated re-extract runs on one package before changing semantic rules again

## Update: Two-Stage Probe Did Not Hold, Kept Low-Risk Precision Fixes (2026-05-09 22:41)

What was tried:

- a two-stage `KP-KP` extraction prototype:
  - stage 1 local candidate pair generation
  - stage 2 LLM pairwise judgment

Result:

- the prototype did not beat the current single-stage path on this package
- relation sets became too volatile during repeated real re-extracts
- so it was not kept as the mainline implementation

What was retained:

- stricter endpoint mention matching:
  - 2-char generic fragments no longer count as endpoint mentions unless no stronger fragment exists
- block evidence text no longer includes `section_path`
  - this removed package-title leakage into evidence preview
- `method` profile recognition now explicitly covers:
  - `方法 / 解法 / 求法 / 求解`
- tighter prerequisite rule:
  - if target is a method point, the evidence must explicitly mention the target

Current verified state for package `451` after cleanup:

- `kp_relations_package_audit.py --package-id 451`
  - `Relations in audit scope: 5`
  - `Projectable / projected: 4 / 4`
  - `Top anomaly flags: (none)`
- `topic_ingest_quality_gate.py --package-id 451`
  - `PASS`
  - `grounded_llm_kp_relations=5`
  - `questions=42`
  - `question_link_coverage=1.0`
  - `retrieval_docs=224`
  - `embeddings=224`

Current accepted relations:

- `函数定义域的求法 -> specializes -> 抽象函数定义域的求法`
- `函数的概念 -> prerequisite -> 函数的定义域`
- `函数的概念 -> prerequisite -> 函数的值域`
- `函数的概念 -> prerequisite -> 分段函数`
- `函数的概念 -> prerequisite -> 函数定义域的求法`

Interpretation:

- this state is cleaner than the anomalous intermediate states from the two-stage probe
- but it is also more conservative than the earlier `8/9 relation` states
- current mainline preference is now precision over coverage for single-package ingest

## Update: KP-KP Observability Added (2026-05-09 23:20)

Scope:

- do not change semantic rules again yet
- first make relation extraction drift observable on real package data
- persist enough raw artifacts so later regressions can be compared instead of guessed

Files changed:

- `D:\10739\Exam-Analysis-Suite\analyzer\app\knowledge_point_parser.py`
- `D:\10739\Exam-Analysis-Suite\scripts\reextract_package_kp_relations.py`
- `D:\10739\Exam-Analysis-Suite\scripts\kp_relation_repeat_compare.py`

What was added:

1. Raw KP-KP extraction artifact persistence
   - `_extract_kp_relations_with_llm()` now returns a `debug_payload`
   - payload includes:
     - package identity
     - candidate grounding payload
     - raw LLM response
     - parsed relations
     - per-row decision log
     - insert / reject / skip summary
   - verbose ingest runs also write package-scoped artifacts under the run `llm/` directory

2. Re-extract script debug output
   - `scripts/reextract_package_kp_relations.py` now writes:
     - `scripts/_out/reextract_package_kp_relations_debug_pkg{package_id}_{timestamp}.json`
   - this gives a direct snapshot for one repair / reproject run

3. Repeat-run drift comparison tool
   - new script:
     - `D:\10739\Exam-Analysis-Suite\scripts\kp_relation_repeat_compare.py`
   - it repeatedly re-extracts one package and reports:
     - per-run relation set
     - stable relations
     - volatile relations
     - pairwise Jaccard
     - per-run debug artifact path

Real run on package `451`:

Command:

```powershell
.\.venv_commercial\Scripts\python.exe scripts\kp_relation_repeat_compare.py --package-id 451 --runs 2
```

Artifacts:

- `D:\10739\Exam-Analysis-Suite\scripts\_out\kp_relation_repeat_compare_pkg451_20260509_232013.json`
- `D:\10739\Exam-Analysis-Suite\scripts\_out\kp_relation_repeat_compare_debug_pkg451_run1_20260509_231714.json`
- `D:\10739\Exam-Analysis-Suite\scripts\_out\kp_relation_repeat_compare_debug_pkg451_run2_20260509_232013.json`

Observed result:

- `relation_count_by_run = [7, 7]`
- `stable_relation_count = 5`
- `volatile_relation_count = 4`
- `pairwise_jaccard = 0.5556`

Interpretation:

- relation count alone is not a sufficient health signal
- package `451` already shows real extraction drift even when the count stays constant
- the next readiness judgment should use:
  - quality gate
  - package audit
  - repeat-run compare
- because of this, current readiness is:
  - acceptable for single-package formal ingest with review
  - not yet acceptable for unattended bulk ingest

Current safest next step:

1. keep the current single-stage mainline
2. use repeat-run compare on each newly ingested package before declaring it graph-stable
3. only then consider another semantic rule change
