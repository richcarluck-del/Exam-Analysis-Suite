# 计划：将 Preprocessor 的大模型配置迁移到数据库

## 目标

修改 `preprocessor` 模块，使其不再依赖环境变量来获取大模型（LLM）的配置信息，而是通过新的命令行参数，从共享的 `exam_analysis.db` 数据库中动态查询和获取。这可以统一项目的配置管理，并为未来的 UI 控制提供灵活性。

## 核心原则

**重用，而非重造**。本次修改将严格遵循“调用而非实现”的原则，充分利用 `preprocessor/main.py` 现有的、强大的命令行执行框架。我们只修改其获取配置的方式，不改变其核心处理流程。

## 详细步骤

### 第一阶段：修改 `preprocessor/main.py` 以支持新参数

1.  **增加新的命令行参数**：
    *   在 `preprocessor/main.py` 的 `main` 函数中，添加两个新的、互斥的命令行参数：
        *   `--provider <供应商名称>`: 用于指定使用哪个 API 供应商 (例如, `Dashscope`)。
        *   `--model <模型名称>`: 用于指定使用哪个具体的 LLM 模型 (例如, `qwen-vl-max`)。
    *   这两个参数将成为 `preprocessor` 选择大模型的主要依据。

2.  **调整 `main.py` 的主逻辑**：
    *   在 `main` 函数的开始部分，增加一段新的逻辑：
        *   如果用户提供了 `--provider` 或 `--model` 参数，程序将连接到 `exam_analysis.db` 数据库。
        *   根据用户输入的名称，查询 `APIProvider` 和 `LLMModel` 表，获取对应的 API URL, 解密后的 API Key, 和最终的模型名称。
        *   将这些获取到的配置信息（URL, Key, Model Name）存储在变量中，准备传递给后续的 `call_api` 函数。
        *   如果数据库查询失败，或用户没有提供这些参数，程序应能优雅地回退到某种默认行为或报错，确保不会因为配置问题而崩溃。

### 第二阶段：重构 `preprocessor/src/utils.py` 中的 `call_api` 函数

1.  **移除旧的、硬编码的逻辑**：
    *   删除 `preprocessor/src/utils.py` 文件中所有与加载环境变量 (`load_dotenv`, `os.environ.get`) 和硬编码供应商优先级 (`if/elif DASHSCOPE_API_KEY...`) 相关的代码块。这些全局变量（`API_KEY`, `API_URL`, `DEFAULT_MODEL`）将不再被需要。

2.  **改造 `call_api` 函数签名**：
    *   修改 `call_api` 函数的定义，使其不再依赖任何全局变量，而是通过函数参数来接收所有必要的配置信息。新的函数签名应该类似于：
        ```python
        def call_api(prompt: str, api_url: str, api_key: str, model_name: str, image_path: str = None, ...):
        ```

3.  **更新 `call_api` 函数的内部实现**：
    *   调整函数内部的 `requests.post` 调用，使其使用从函数参数中传入的 `api_url`, `api_key`, 和 `model_name`，而不是旧的全局变量。

### 第三阶段：连接 `main.py` 和 `utils.py`

1.  **更新 `main.py` 中对 `call_api` 的调用**：
    *   找到 `main.py` 中（或其调用的子模块中）所有调用 `call_api` 的地方。
    *   将第一阶段获取到的、存储在变量中的数据库配置信息（URL, Key, Model Name），通过新的参数传递给 `call_api` 函数。

## 预期成果

*   `preprocessor` 模块将彻底摆脱对 `.env` 文件和环境变量的硬编码依赖。
*   我们可以通过 `--provider` 和 `--model` 命令行参数，在运行时灵活地、动态地指定 `preprocessor` 使用任何已在数据库中注册的大模型。
*   为我们的 `preprocessor_test_ui` 项目的后端服务实现，提供了清晰、直接的调用路径：后端服务只需将前端传来的模型选择，转换成这两个新的命令行参数即可。

### 第四阶段：适配 `preprocessor_test_ui` 以利用新机制

为了确保我们的测试工具能够利用这次重构带来的好处，我们需要执行以下适配工作：

1.  **确认数据获取链路**：
    *   **后端**：确保 `preprocessor_test_ui/main.py` 中的 `/api/providers` 和 `/api/models` 接口，能够正确地从 `exam_analysis.db` 数据库中查询出所有的供应商和模型列表。
    *   **前端**：确保 `preprocessor_test_ui/frontend/src/App.jsx` 在页面加载时，调用上述两个接口，并将返回的数据填充到对应的下拉菜单中。这一步确保了 UI 的选项与数据库中的数据是实时同步的。

2.  **改造测试执行逻辑**：
    *   **后端**：修改 `preprocessor_test_ui/main.py` 中的 `websocket_run_test` 函数。
    *   当收到前端发送的、包含 `provider_name` 和 `model_name` 的测试配置时，后端服务**必须**将这些名称直接转换成 `--provider <provider_name>` 和 `--model <model_name>` 这两个新的命令行参数。
    *   后端服务将使用这些新的参数去执行 `preprocessor/main.py` 子进程，从而将前端用户的动态选择，无缝地传递给 `preprocessor` 的执行环境。
