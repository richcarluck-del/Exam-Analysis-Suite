# Mock 测试使用指南

## 三种测试模式

系统现在支持三种测试模式，每种模式有不同的用途：

### 1. 真实测试
- **用途**：使用真实 API 完整运行所有步骤
- **数据流向**：输入图片 → 真实 API → `temp/run_时间戳/`
- **场景**：首次测试、完整流程验证

### 2. 录制测试 ⭐ 新增
- **用途**：使用真实 API 运行，但将结果保存为 Mock Case
- **数据流向**：输入图片 → 真实 API → `tests/mock_data/case_name/`
- **场景**：创建新的 Mock 数据快照，用于后续模拟测试

### 3. 模拟测试
- **用途**：使用已有的 Mock Case 数据，部分步骤用 mock，部分步骤调用真实 API
- **数据流向**：`tests/mock_data/case_name/` → 部分 mock + 部分真实 API → `temp/run_时间戳/`
- **场景**：测试不同 prompt 效果、调试特定步骤、节省 API 调用

## 使用流程

### 第一步：录制 Mock 数据（必须先执行）

1. 选择 **录制测试** 模式
2. 输入 Case 名称（留空则自动生成，如 `case_1773585542`）
3. 点击 **开始测试**
4. 程序会使用真实 API 运行所有 6 个步骤
5. 完成后，数据保存到 `tests/mock_data/<case_name>/` 目录

生成的 Mock Case 包含：
- `01_correction_output.json` - 视角矫正结果
- `02_classify_output.json` - 页面分类结果
- `03_layout_output.json` - 布局分析结果
- `04_content_output.json` - 内容提取结果
- `05_merged_output.json` - 合并结果
- `corrected_images/` - 矫正后的图片
- `06_final_output/` - 最终输出图片

### 第二步：使用 Mock 数据测试

录制完成后，可以使用模拟测试来复用这些数据：

1. 选择 **模拟测试** 模式
2. 选择要使用的 **Mock Case**（默认选择最新的）
3. 勾选需要 **真实执行** 的步骤（例如只勾选步骤 4 测试新 prompt）
4. 点击 **开始测试**

结果：
- **未勾选**的步骤：使用 Mock Case 中的数据（不调用 API）
- **勾选**的步骤：调用真实 API 执行
- 输出保存到：`temp/run_时间戳/`

## 示例场景

### 场景 1：测试不同 prompt 的效果

1. **录制数据**：
   - 选择"录制测试"模式
   - 输入 case 名称：`baseline_test`
   - 运行测试（使用默认 prompt v4）

2. **修改 prompt**：
   - 在数据库中修改 extract_content_v4 的内容

3. **对比测试**：
   - 选择"模拟测试"模式
   - 选择 Mock Case：`baseline_test`
   - **只勾选步骤 4**（extract_content）
   - 运行测试
   - 比较输出结果与 `tests/mock_data/baseline_test/04_content_output.json`

### 场景 2：调试布局分析步骤

1. 先录制完整数据
2. 选择"模拟测试"模式
3. 选择对应的 Mock Case
4. **只勾选步骤 3**（analyze_layout）
5. 修改布局分析的 prompt 或代码
6. 运行测试，查看效果

### 场景 3：完全模拟测试（不花 API 调用）

1. 选择"模拟测试"模式
2. 选择 Mock Case
3. **不勾选任何步骤**
4. 运行测试
5. 所有步骤都使用 Mock 数据，快速查看结果

## 目录结构说明

```
preprocessor/
├── temp/                           # 临时测试输出
│   └── run_时间戳/                 # 真实测试和模拟测试的输出
├── tests/
│   ├── mock_data/                  # Mock 数据仓库（录制测试的输出）
│   │   ├── case_1/
│   │   ├── case_2/
│   │   └── baseline_test/
│   └── test_cases/                 # 正式测试用例（预留）
```

### 目录用途对比

| 目录 | 用途 | 何时创建 | 何时删除 |
|------|------|----------|----------|
| `temp/run_时间戳/` | 临时测试输出 | 每次真实测试或模拟测试 | 可随时删除 |
| `tests/mock_data/case_name/` | Mock 数据快照 | 录制测试时创建 | 手动删除（需要保留） |

## 常见问题

### Q: 为什么需要三种模式？
A: 
- **真实测试**：用于首次测试或完整验证
- **录制测试**：创建可复用的 Mock 数据快照
- **模拟测试**：基于已有快照快速测试，节省时间和 API 调用

### Q: 录制测试和真实测试有什么区别？
A: 
- **输出目录不同**：
  - 真实测试 → `temp/`
  - 录制测试 → `tests/mock_data/`
- **目的不同**：
  - 真实测试：临时验证
  - 录制测试：创建可复用的 Mock Case

### Q: 模拟测试的数据从哪里来？
A: 从 `tests/mock_data/` 目录加载，可以选择任意已录制的 Mock Case。

### Q: 如何查看有哪些 Mock Cases？
A: 
1. 在前端选择"模拟测试"模式后，下拉框会显示所有可用的 Mock Cases
2. 或直接查看 `tests/mock_data/` 目录

### Q: Mock Case 可以删除吗？
A: 可以，直接删除 `tests/mock_data/<case_name>/` 目录即可。但删除后，依赖该 Case 的模拟测试将无法使用。

### Q: 如何更新 Mock Case？
A: 重新运行录制测试，使用相同的 Case 名称，会覆盖原有数据。

### Q: 连续多次模拟测试会导致数据不完整吗？
A: **不会！** 这是新设计的关键优势：
- 每次模拟测试都从 `tests/mock_data/` 加载原始快照
- 输出到 `temp/` 目录，不会污染 Mock 数据源
- 可以无限次进行模拟测试，数据始终保持完整

## 注意事项

1. **必须先录制数据**，才能使用模拟测试
2. Mock 数据依赖于输入图片，如果更换图片需要重新录制
3. 混合测试时，确保前面的步骤有 Mock 数据，否则后续步骤无法执行
4. 建议为不同的测试场景录制多个 Mock Cases（如不同类型的试卷）

## 最佳实践

1. **首次使用**：先录制一个完整的 baseline case
2. **日常测试**：使用模拟测试 + 部分步骤真实执行
3. **Prompt 迭代**：每次修改 prompt 后，录制新的 case 保存结果
4. **团队协作**：将重要的 Mock Cases 提交到 Git，共享测试数据

## 命令参考

### 命令行录制
```bash
cd D:\10739\Exam-Analysis-Suite\preprocessor
python main.py --input-dir my_test_images --provider dashscope --model qwen-vl-max --record-case baseline_test
```

### 命令行模拟测试
```bash
cd D:\10739\Exam-Analysis-Suite\preprocessor
python main.py --mock-case baseline_test --real-steps 4
```

这将使用 `baseline_test` Mock Case，只有步骤 4 调用真实 API。
