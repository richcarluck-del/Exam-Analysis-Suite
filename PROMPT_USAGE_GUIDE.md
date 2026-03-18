# 提示词使用规则详解

本文档详细说明 Exam-Analysis-Suite 测试工具中提示词（Prompt）的使用规则、版本管理逻辑和降级策略。

---

## 📋 目录

- [核心概念](#核心概念)
- [提示词加载流程](#提示词加载流程)
- [版本管理规则](#版本管理规则)
- [跨版本降级策略](#跨版本降级策略)
- [实际使用示例](#实际使用示例)
- [常见问题](#常见问题)

---

## 🎯 核心概念

### 1. 提示词是什么？

提示词（Prompt）是发送给大模型（LLM）的指令文本，用于指导模型完成特定任务。例如：

```
你是一个专业的文档图像矫正助手。请识别这张图片中【试卷】的四个顶点...
```

### 2. 提示词的属性

每个提示词在数据库中有以下关键属性：

| 属性 | 说明 | 示例 |
|------|------|------|
| `name` | 提示词名称 | `perspective_correction_all_types_v1` |
| `pipeline_step` | 流水线步骤 | `1` (透视矫正) |
| `category` | 类别 | `perspective_correction` |
| `target_type` | 目标类型 | `all_types`, `exam_paper`, `answer_sheet` |
| `version` | 版本号 | `2` |
| `prompt_text` | 提示词内容 | 完整的指令文本 |
| `is_active` | 是否激活 | `true` |

### 3. 六个处理步骤

系统有 6 个处理步骤，每个步骤都需要提示词：

| 步骤 | 名称 | 作用 | 默认 target_type |
|------|------|------|-----------------|
| **Step 1** | 透视矫正 | 识别试卷四角并矫正 | `all_types` |
| **Step 2** | 页面分类 | 判断是试卷还是答题纸 | `full_page` |
| **Step 3** | 版面分析 | 分析页面布局 | - |
| **Step 4** | 内容提取 | 提取题目内容和坐标 | `exam_paper`/`answer_sheet`/`mixed` |
| **Step 5** | 结果合并 | 合并所有结果 | - |
| **Step 6** | 绘制输出 | 在图片上绘制边界框 | - |

---

## 🔄 提示词加载流程

### 完整加载逻辑

```
用户选择版本 (如 v8)
    ↓
从数据库加载指定版本的提示词
    ↓
如果指定版本不存在
    ↓
降级到最新版本 (v7 → v6 → v5 → ...)
    ↓
如果所有版本都不存在
    ↓
使用代码中的默认提示词
```

### 代码实现位置

**主程序**: `preprocessor/main.py` (第 230-260 行)

```python
# 示例：加载步骤 1 的提示词
perspective_prompt = prompt_manager.get_prompt(
    step=1, 
    target_type="all_types", 
    version=8  # 用户选择的版本
)

if perspective_prompt:
    # ✅ 数据库中有 v8，使用 v8
    prompts_dict['perspective_correction'] = perspective_prompt
    print(f"✓ 步骤 1：已加载提示词，长度 {len(perspective_prompt)}")
else:
    # ❌ 数据库中没有 v8，尝试最新版本
    perspective_prompt_latest = prompt_manager.get_prompt(
        step=1, 
        target_type="all_types", 
        version="latest"
    )
    if perspective_prompt_latest:
        # ✅ 使用最新版本（如 v2）
        prompts_dict['perspective_correction'] = perspective_prompt_latest
        print(f"⚠ 步骤 1：v8 不存在，使用最新版本 (v2)")
    else:
        # ❌ 数据库中完全没有，使用代码默认值
        print(f"⚠ 步骤 1：未找到提示词，将使用默认值")
        prompts_dict['perspective_correction'] = None
```

---

## 📊 版本管理规则

### 1. 版本号规则

- 版本号是**整数**，从 1 开始递增
- 版本号**越大越新**（v8 比 v7 新）
- 每个步骤可以**独立版本**（步骤 1 可以是 v2，步骤 4 可以是 v8）

### 2. 版本与步骤的关系

**重要**：不同步骤的提示词版本**可以不同**！

| 场景 | 步骤 1 版本 | 步骤 2 版本 | 步骤 4 版本 | 说明 |
|------|-----------|-----------|-----------|------|
| 场景 1 | v2 | v1 | v8 | 步骤 4 最新，步骤 1-2 较旧 |
| 场景 2 | v5 | v5 | v5 | 所有步骤都是 v5 |
| 场景 3 | v3 | v2 | v4 | 各步骤版本不同 |

### 3. 数据库表结构

```sql
CREATE TABLE prompts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,           -- 如：perspective_correction_all_types_v1
    pipeline_step INTEGER,         -- 1-6
    category TEXT,                 -- 如：perspective_correction
    target_type TEXT,              -- 如：all_types, exam_paper
    version INTEGER,               -- 版本号：1, 2, 3...
    prompt_text TEXT,              -- 提示词内容
    is_active BOOLEAN,             -- 是否激活
    updated_at TIMESTAMP
);
```

---

## 📉 跨版本降级策略

### 为什么需要降级？

**问题**：用户选择了 v8，但数据库中：
- 步骤 1 只有 v2
- 步骤 2 只有 v1
- 步骤 4 有 v8

**解决**：自动降级到最新版本，而不是报错或失败。

### 降级逻辑详解

#### 步骤 1-2：直接降级到最新

```python
# 步骤 1：透视矫正
perspective_prompt = get_prompt(step=1, target_type="all_types", version=8)
if not perspective_prompt:
    # v8 不存在，使用最新（v2）
    perspective_prompt = get_prompt(step=1, target_type="all_types", version="latest")
```

#### 步骤 4：按类型分别降级

步骤 4 有 3 种类型，**每种类型独立降级**：

```python
# 用户选择 v10，但 v10 只有 exam_paper 有内容
exam_paper_prompt = get_prompt(step=4, target_type="exam_paper", version=10)
answer_sheet_prompt = get_prompt(step=4, target_type="answer_sheet", version=10)
mixed_prompt = get_prompt(step=4, target_type="mixed", version=10)

# exam_paper: v10 ✓
# answer_sheet: v10 ✗ → 降级到 v9 ✗ → 降级到 v8 ✓
# mixed: v10 ✗ → 降级到 v9 ✗ → 降级到 v8 ✓

if prompt_version_num and prompt_version_num != "latest":
    current_version = int(prompt_version_num)
    
    # 为每个类型尝试从低版本获取（最多尝试 5 个版本）
    for fallback_version in range(current_version - 1, max(0, current_version - 6), -1):
        fallback_version_str = str(fallback_version)
        
        # 为 answer_sheet 查找降级版本
        if answer_sheet_prompt is None:
            answer_sheet_prompt = get_prompt(step=4, target_type="answer_sheet", version=fallback_version_str)
            if answer_sheet_prompt:
                print(f"✓ 步骤 4（内容提取 - 答题纸）：使用 v{fallback_version} 降级版本")
        
        # 为 mixed 查找降级版本
        if mixed_prompt is None:
            mixed_prompt = get_prompt(step=4, target_type="mixed", version=fallback_version_str)
            if mixed_prompt:
                print(f"✓ 步骤 4（内容提取 - 混合）：使用 v{fallback_version} 降级版本")
        
        # 如果所有类型都找到了，提前退出
        if exam_paper_prompt and answer_sheet_prompt and mixed_prompt:
            break
```

### 降级范围

- **最大降级跨度**：5 个版本
- **示例**：v10 → v9 → v8 → v7 → v6 → v5（最多到 v5）
- **终止条件**：找到可用提示词 或 达到降级下限

---

## 📚 实际使用示例

### 示例 1：标准场景（所有步骤都有 v8）

**数据库状态**：
```
步骤 1：perspective_correction_all_types (v8) ✓
步骤 2：page_classification_full_page (v8) ✓
步骤 4：content_extraction_exam_paper (v8) ✓
        content_extraction_answer_sheet (v8) ✓
        content_extraction_mixed (v8) ✓
```

**用户操作**：
- 选择提示词版本：`v8`

**加载结果**：
```
✓ 步骤 1（透视矫正）：已加载提示词，长度 1234
✓ 步骤 2（页面分类）：已加载提示词，长度 567
✓ 步骤 4（内容提取 - 试卷）：已加载提示词，长度 2220
✓ 步骤 4（内容提取 - 答题纸）：已加载提示词，长度 2220
✓ 步骤 4（内容提取 - 混合）：已加载提示词，长度 983
```

**实际使用**：所有步骤都使用 v8 提示词 ✅

---

### 示例 2：降级场景（只有步骤 4 有 v8）

**数据库状态**：
```
步骤 1：perspective_correction_all_types (v2) ✓  (最新 v2)
步骤 2：page_classification_full_page (v1) ✓    (最新 v1)
步骤 4：content_extraction_exam_paper (v8) ✓
        content_extraction_answer_sheet (v8) ✓
        content_extraction_mixed (v8) ✓
```

**用户操作**：
- 选择提示词版本：`v8`

**加载结果**：
```
⚠ 步骤 1（透视矫正）：v8 不存在，使用最新版本 (v2)，长度 765
⚠ 步骤 2（页面分类）：v8 不存在，使用最新版本 (v1)，长度 347
✓ 步骤 4（内容提取 - 试卷）：已加载提示词，长度 2220
✓ 步骤 4（内容提取 - 答题纸）：已加载提示词，长度 2220
✓ 步骤 4（内容提取 - 混合）：已加载提示词，长度 983
```

**实际使用**：
- 步骤 1：使用 **v2** 提示词（降级）
- 步骤 2：使用 **v1** 提示词（降级）
- 步骤 4：使用 **v8** 提示词（指定版本）

---

### 示例 3：部分降级场景（步骤 4 的 v10 只有部分类型）

**数据库状态**：
```
步骤 4：content_extraction_exam_paper (v10) ✓
        content_extraction_answer_sheet (v8) ✓  (最新 v8)
        content_extraction_mixed (v8) ✓         (最新 v8)
```

**用户操作**：
- 选择提示词版本：`v10`

**加载过程**：
```
1. 尝试加载 v10:
   - exam_paper: ✓ 找到
   - answer_sheet: ✗ 不存在
   - mixed: ✗ 不存在

2. 降级到 v9:
   - answer_sheet: ✗ 不存在
   - mixed: ✗ 不存在

3. 降级到 v8:
   - answer_sheet: ✓ 找到！
   - mixed: ✓ 找到！
```

**加载结果**：
```
✓ 步骤 4（内容提取 - 试卷）：已加载提示词，长度 2500
✓ 步骤 4（内容提取 - 答题纸）：使用 v8 降级版本
✓ 步骤 4（内容提取 - 混合）：使用 v8 降级版本
```

**实际使用**：
- `exam_paper`: **v10**（原始版本）
- `answer_sheet`: **v8**（降级 2 个版本）
- `mixed`: **v8**（降级 2 个版本）

---

### 示例 4：完全没有数据库提示词（使用代码默认值）

**数据库状态**：
```
（空数据库，或所有提示词 is_active=false）
```

**用户操作**：
- 选择提示词版本：`v8`

**加载结果**：
```
⚠ 步骤 1（透视矫正）：未找到提示词，将使用默认值
⚠ 步骤 2（页面分类）：未找到提示词，将使用默认值
⚠ 步骤 4（内容提取 - 试卷）：未找到提示词，将使用默认值
```

**实际使用**：使用代码中硬编码的默认提示词

**代码位置**：
- 步骤 1：`preprocessor/src/tasks/task_perspective_correction.py` (第 23-64 行)
- 步骤 2：`preprocessor/src/tasks/task_classify_page.py`
- 步骤 4：`preprocessor/src/tasks/task_extract_content.py`

---

## 🔧 修改提示词的影响

### 场景 1：修改数据库中的提示词

**操作**：在提示词管理页面编辑并保存

**影响**：
1. ✅ **立即生效**：下次运行时会使用新提示词
2. ✅ **影响所有版本**：如果修改的是 v8，所有选择 v8 的测试都会用到
3. ⚠️ **不影响正在运行的测试**：已开始的测试使用加载时的提示词

**示例**：
```
10:00 - 修改步骤 1 的 v2 提示词，优化角点定位描述
10:05 - 用户 A 运行测试（选择 v8）
        → 步骤 1 降级到 v2，使用新提示词 ✅
10:10 - 用户 B 运行测试（选择 v2）
        → 步骤 1 使用 v2，使用新提示词 ✅
```

---

### 场景 2：添加新版本的提示词

**操作**：在提示词管理页面创建新版本（如 v9）

**影响**：
1. ✅ **新版本可用**：用户可以选择 v9
2. ✅ **不影响旧版本**：选择 v8 的用户仍然使用 v8
3. ✅ **自动降级更新**：如果用户选择 v10，会降级到 v9（而不是 v8）

**示例**：
```
当前数据库：
- 步骤 1: v2 (最新)
- 步骤 4: v8 (最新)

10:00 - 添加步骤 4 的 v9 提示词
10:05 - 用户选择 v10
        → 步骤 4 降级逻辑：v10 ✗ → v9 ✓
        → 使用 v9（而不是之前的 v8）✅
```

---

### 场景 3：删除提示词版本

**操作**：在提示词管理页面删除某个版本

**影响**：
1. ⚠️ **选择该版本会降级**：用户选择被删除的版本会自动降级
2. ✅ **不影响其他版本**：其他版本正常使用

**示例**：
```
当前数据库：
- 步骤 4: v6, v7, v8, v9, v10

10:00 - 删除 v8 提示词
10:05 - 用户选择 v8
        → v8 ✗ (已删除)
        → 降级到 v7 ✓
        → 使用 v7
```

---

### 场景 4：修改代码中的默认提示词

**操作**：修改 `task_perspective_correction.py` 中的默认提示词

**影响**：
1. ⚠️ **仅影响无数据库提示词的情况**：只有当数据库中没有对应提示词时才会用到
2. ✅ **立即生效**：代码修改后下次运行即生效
3. ⚠️ **需要重新部署**：代码修改需要重新拉取或部署

**示例**：
```
10:00 - 修改 task_perspective_correction.py 的默认提示词
        优化透视矫正的角点定位描述

10:05 - 用户运行测试（数据库为空）
        → 使用代码默认提示词 ✅
        → 透视矫正效果提升

10:10 - 用户运行测试（数据库有 v2）
        → 使用数据库 v2 提示词
        → 不受代码修改影响 ❌
```

---

## ❓ 常见问题

### Q1: 为什么我选择了 v8，但日志显示使用的是 v2？

**A**: 因为数据库中步骤 1 只有 v2 版本，没有 v8。系统自动降级到最新版本（v2）。

**解决方案**：
- 在提示词管理页面为步骤 1 创建 v8 版本
- 或者接受降级（v2 也能正常工作）

---

### Q2: 修改提示词后需要重启服务吗？

**A**: 
- **数据库修改**：不需要重启，立即生效 ✅
- **代码修改**：需要重启服务 ⚠️

---

### Q3: 如何确认当前使用的是哪个版本的提示词？

**A**: 查看运行日志：

```
✓ 步骤 1（透视矫正）：已加载提示词，长度 1234
⚠ 步骤 1（透视矫正）：v8 不存在，使用最新版本 (v2)，长度 765
```

- 第一行：使用指定版本（v8）
- 第二行：使用降级版本（v2）

或者查看生成的提示词文件：
```
temp/run_xxxxx/prompt_used_for_step_1_perspective_correction.txt
```

---

### Q4: 降级会影响效果吗？

**A**: 
- **小幅度降级**（1-2 个版本）：通常影响不大
- **大幅度降级**（5+ 个版本）：可能影响效果

**建议**：
- 定期更新提示词到最新版本
- 测试不同版本的效果差异
- 使用录制模式对比不同版本的结果

---

### Q5: 如何为不同页面类型（试卷/答题纸）设置不同的提示词？

**A**: 在创建提示词时设置不同的 `target_type`：

```
步骤 4 提示词 1:
- name: content_extraction_exam_paper_v8
- target_type: exam_paper
- prompt_text: 你是试卷内容提取助手...

步骤 4 提示词 2:
- name: content_extraction_answer_sheet_v8
- target_type: answer_sheet
- prompt_text: 你是答题纸内容提取助手...
```

系统会根据页面分类结果**自动选择**对应的提示词。

---

### Q6: 提示词文件保存在哪里？

**A**: 每次测试会在输出目录生成提示词文件：

```
temp/run_20260318_101723/
├── prompt_used_for_step_1_perspective_correction.txt
├── prompt_used_for_step_2_classify.txt
├── prompt_used_for_step_4_extract_content_exam_paper.txt
├── prompt_used_for_step_4_extract_content_answer_sheet.txt
└── prompt_used_for_step_4_extract_content_mixed.txt
```

这些文件记录了**实际使用的提示词**（包括降级后的版本）。

---

## 📖 相关文档

- [Mock 测试使用指南](./preprocessor_test_ui/MOCK_TEST_GUIDE.md)
- [提示词管理页面使用](#)
- [透视矫正原理](#)

---

## 🎯 最佳实践

1. **定期更新提示词**：保持所有步骤的提示词版本一致
2. **使用录制模式**：对比不同提示词版本的效果
3. **查看详细日志**：确认实际使用的提示词版本
4. **备份重要版本**：不要随意删除旧版本提示词
5. **测试后再上线**：新提示词先在测试环境验证

---

**最后更新**: 2026-03-18  
**维护者**: Exam-Analysis-Suite Team
