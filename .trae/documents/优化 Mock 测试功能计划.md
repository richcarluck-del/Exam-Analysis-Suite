# 优化 Mock 测试功能计划

## 目标
实现三种测试模式的清晰分离：
1. **真实测试** - 使用真实 API，数据存放到 `temp/` 目录
2. **录制测试** - 使用真实 API，数据存放到 `tests/mock_data/` 目录（创建新的 mock case）
3. **模拟测试** - 使用最新的 mock case 数据，部分步骤用 mock，部分步骤调用真实 API

## 目录结构设计
```
preprocessor/
├── temp/                           # 临时测试输出（真实测试和 mock 测试都输出到这里）
│   └── run_时间戳/
├── tests/
│   ├── test_cases/                 # 正式的测试用例
│   └── mock_data/                  # Mock 数据仓库（录制测试的输出）
│       ├── case_1/
│       ├── case_2/
│       └── ...
```

## 实现步骤

### 1. 前端 UI 修改
**文件**: `preprocessor_test_ui/frontend/src/App.jsx`

#### 1.1 添加录制测试单选按钮
- 在"测试模式"区域添加第三个选项："录制测试"
- 三个选项互斥：真实测试 | 模拟测试 | 录制测试

#### 1.2 添加录制名称输入框
- 当选择"录制测试"时，显示输入框让用户输入 case 名称
- 默认值：`case_时间戳`

#### 1.3 调整模拟测试的 UI 逻辑
- 当选择"模拟测试"时，自动选择最新的 mock case
- 显示当前使用的 mock case 名称

### 2. 后端 API 修改
**文件**: `preprocessor_test_ui/main.py`

#### 2.1 修改 WebSocket 处理逻辑
添加对 `test_mode === 'record'` 的处理：
```python
if config.get('test_mode') == 'record':
    case_name = config.get('case_name', f'case_{timestamp}')
    command.extend(["--record-case", case_name])
```

#### 2.2 修改模拟测试逻辑
- 从 `tests/mock_data/` 目录查找最新的 case
- 使用 `--mock-case` 参数指定使用哪个 mock case

### 3. Main.py 参数支持
**文件**: `preprocessor/main.py`

#### 3.1 确认 `--record-case` 参数已存在
检查现有代码，确认该参数已经支持将数据保存到 `tests/mock_data/` 目录

#### 3.2 确认 `--mock-case` 参数逻辑
确保 mock 测试从 `tests/mock_data/<case_name>/` 加载数据

### 4. 辅助功能
**文件**: `preprocessor_test_ui/frontend/src/App.jsx`

#### 4.1 添加 Mock Case 列表显示
- 显示所有可用的 mock cases
- 显示每个 case 的创建时间和包含的步骤
- 允许用户手动选择使用哪个 mock case（可选）

#### 4.2 添加 API 端点获取 mock cases 列表
**文件**: `preprocessor_test_ui/main.py`
```python
@app.get("/api/mock-cases")
def get_mock_cases():
    # 返回 tests/mock_data/ 目录下的所有 case
```

### 5. 测试验证

#### 5.1 测试录制测试
- 选择"录制测试"模式
- 输入 case 名称
- 运行测试，验证数据保存到 `tests/mock_data/<case_name>/`

#### 5.2 测试模拟测试
- 选择"模拟测试"模式
- 选择部分步骤使用 mock
- 验证从最新的 mock case 加载数据
- 验证输出仍然保存到 `temp/` 目录

#### 5.3 测试真实测试
- 确保真实测试功能不受影响
- 验证数据仍然保存到 `temp/` 目录

### 6. 文档更新
**文件**: `preprocessor_test_ui/MOCK_TEST_GUIDE.md`

更新使用指南，说明三种模式的区别和使用场景。

## 技术细节

### 前端状态管理
需要添加的状态：
- `testMode`: 'real' | 'mock' | 'record'
- `caseName`: string (录制测试时使用)
- `mockCases`: array (可用的 mock cases 列表)
- `selectedMockCase`: string (选择的 mock case)

### 后端逻辑
- 录制测试：完全走真实测试流程，只是输出目录不同
- 模拟测试：从 `tests/mock_data/` 加载，输出到 `temp/`
- 真实测试：保持不变

### 数据流
```
录制测试：
  输入图片 → 真实 API → tests/mock_data/<case_name>/

模拟测试：
  tests/mock_data/<latest_case>/ → 部分 mock + 部分真实 API → temp/

真实测试：
  输入图片 → 真实 API → temp/
```

## 验收标准
- ✅ 三种测试模式可以正常切换
- ✅ 录制测试数据正确保存到 `tests/mock_data/`
- ✅ 模拟测试正确从最新 mock case 加载数据
- ✅ 模拟测试输出到 `temp/` 目录
- ✅ 真实测试功能不受影响
- ✅ UI 清晰显示当前模式和使用的数据源
