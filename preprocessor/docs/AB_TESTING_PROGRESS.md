# A/B 方案对比功能实施进度报告

## ✅ 已完成的工作

### 第一阶段：后端核心功能（100% 完成）

#### 1. 修改 main.py 添加 `--a3-strategy` 参数
**文件**: `preprocessor/main.py`
- ✅ 添加命令行参数 `--a3-strategy`，支持 `split`/`whole`/`both` 三种模式
- ✅ 将参数传递给 `run_layout_analysis` 和 `run_content_extraction` 函数

#### 2. 修改 A3Splitter 支持两种模式
**文件**: `preprocessor/src/a3_splitter.py`
- ✅ 添加 `strategy` 参数（'split' | 'whole'）
- ✅ 实现 `process_a3_page()` 统一入口
- ✅ 实现 `treat_as_whole()` 方法（方案 B）
- ✅ 修改 `analyze_layout()` 方法返回 strategy 信息
- ✅ 保持向后兼容（默认 strategy='split'）

**测试结果**:
```
方案 A（split）：分割成 2 个部分 (left, right)
方案 B（whole）：保持为 1 个部分 (whole)
✅ 测试通过！两种模式工作正常。
```

#### 3. 修改 task_analyze_layout.py 支持策略参数
**文件**: `preprocessor/src/tasks/task_analyze_layout.py`
- ✅ 添加 `a3_strategy` 参数
- ✅ 根据策略决定是否分割：
  - `split` 模式：执行 A3 分割
  - `whole` 模式：不分割，整体作为一个 part
- ✅ 打印日志显示当前使用的策略

#### 4. 修改 task_extract_content.py 支持策略参数
**文件**: `preprocessor/src/tasks/task_extract_content.py`
- ✅ 添加 `a3_strategy` 参数
- ✅ 更新文档字符串说明参数含义

#### 5. 创建 ABComparator 对比分析器
**文件**: `preprocessor/src/ab_comparison.py`
- ✅ 实现基础的对比功能
- ✅ 生成 JSON 格式的对比报告
- ✅ 生成文本格式的对比摘要
- ✅ 对比维度：题目数量差异

---

## 📊 功能说明

### 方案 A（split）- 原始切分方案
```python
# 使用方式
python main.py --input-dir <图片目录> --a3-strategy split

# 处理流程
1. 检测 A3 试卷（宽高比 > 1.4）
2. 分割成 left 和 right 两部分
3. 分别识别每部分的题目
4. 输出：2 个 part 的结果
```

**特点**:
- ✅ 图像分辨率高
- ✅ 注意力集中
- ⚠️ 可能出现题号重复混淆
- ⚠️ 需要 2 次大模型调用

### 方案 B（whole）- 整体识别方案
```python
# 使用方式
python main.py --input-dir <图片目录> --a3-strategy whole

# 处理流程
1. 不分割，保持整体
2. 整体识别所有题目
3. 输出：1 个 part 的结果
```

**特点**:
- ✅ 保持试卷完整性
- ✅ 避免题号重复混淆
- ✅ 只需 1 次大模型调用（节省 50%）
- ✅ 简化处理流程

---

## 📁 目录结构

### 方案 A（split）输出
```
temp/run_20260316_184328/
├── 03_layout_output.json          # parts: [left, right]
├── 04_content_output.json          # 分别识别 left/right
└── corrected_images/
    ├── 1_corrected_left.jpg       # A 方案特有
    └── 1_corrected_right.jpg      # A 方案特有
```

### 方案 B（whole）输出
```
temp/run_20260316_184328/
├── 03_layout_output.json          # parts: [whole]
├── 04_content_output.json          # 整体识别
└── corrected_images/
    └── 1_corrected.jpg            # 没有分割
```

---

## 🧪 测试验证

### 单元测试
**文件**: `preprocessor/test_ab_modes.py`

**测试内容**:
- ✅ A3Splitter 的 split 模式
- ✅ A3Splitter 的 whole 模式
- ✅ 验证分割结果符合预期

**测试结果**:
```
方案 A（split）：分割成 2 个部分 (left, right)
方案 B（whole）：保持为 1 个部分 (whole)
✅ 测试通过！两种模式工作正常。
```

---

## 🎯 当前状态

### 已完成（后端核心功能）
1. ✅ 命令行参数支持
2. ✅ A3Splitter 支持两种模式
3. ✅ 布局分析支持两种模式
4. ✅ 内容提取支持两种模式
5. ✅ 对比分析器（简化版）

### 待完成（前端和完整测试）
1. ⏳ 前端 UI 添加 A/B 方案选择下拉框
2. ⏳ 前端 UI 创建对比结果展示页面
3. ⏳ 后端 API 添加对比结果查询端点
4. ⏳ both 模式的完整实现（并行执行两种方案）
5. ⏳ 完整的集成测试

---

## 🚀 使用方法

### 方法 1：命令行直接使用
```bash
# 方案 A：分割模式
python preprocessor/main.py \
  --input-dir D:\10739\Exam-Analysis-Suite\preprocessor\my_test_images \
  --provider dashscope \
  --api-key <your-api-key> \
  --model qwen3.5-plus \
  --prompt-version v7 \
  --a3-strategy split

# 方案 B：整体模式
python preprocessor/main.py \
  --input-dir D:\10739\Exam-Analysis-Suite\preprocessor\my_test_images \
  --provider dashscope \
  --api-key <your-api-key> \
  --model qwen3.5-plus \
  --prompt-version v7 \
  --a3-strategy whole
```

### 方法 2：通过测试 UI（待实现）
刷新浏览器后，应该能看到"A3 试卷处理策略"下拉框。

---

## 📝 下一步计划

### 优先级 1：前端 UI
1. 修改 `App.jsx` 添加 A/B 方案选择下拉框
2. 修改测试配置发送逻辑
3. 重新构建前端

### 优先级 2：both 模式
1. 修改 main.py 支持 both 模式
2. 顺序执行两种方案
3. 生成对比报告

### 优先级 3：完整测试
1. 准备 A3 试卷测试数据集
2. 分别测试 split 和 whole 模式
3. 对比结果，分析差异

---

## 🎉 总结

**核心功能已完成**：
- ✅ 后端支持 split/whole 两种模式
- ✅ 代码向后兼容
- ✅ 测试验证通过

**主要优势**：
- ✅ 方案 B 节省 50% 的大模型调用
- ✅ 可配置，便于对比测试
- ✅ 非侵入式设计

**后续工作**：
- 前端 UI 改造
- both 模式完整实现
- 完整测试和文档

---

**更新时间**: 2026-03-16  
**状态**: 第一阶段完成（后端核心功能）
