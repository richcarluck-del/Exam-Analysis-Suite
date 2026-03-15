# 试卷分析 RAG 系统

基于 AI 的高中试卷分析系统，通过多模态大模型（Gemini）实现试卷的智能分析、布局识别、内容提取和结果可视化。

## 项目结构

```
Exam-Analysis-RAG/
├── src/                     # 核心源代码
│   ├── tasks/               # 管道任务模块
│   │   ├── task_classify_page.py
│   │   ├── task_perspective_correction.py
│   │   ├── task_analyze_layout.py
│   │   ├── task_extract_content.py
│   │   ├── task_merge_results.py
│   │   └── task_draw_output.py
│   ├── a3_splitter.py       # A3 试卷分割逻辑
│   ├── classifier.py        # 页面分类器
│   ├── merger.py            # 结果合并器
│   ├── models.py            # 数据模型 (Question)
│   ├── prompts.py           # 大模型提示词管理
│   └── utils.py             # 通用工具函数 (API 调用, JSON 提取等)
├── main.py                  # 项目主入口程序 (管道编排)
├── scripts/                 # 辅助脚本 (目前为空或仅包含非核心功能)
├── temp/                    # 临时工作目录，用于存储每次运行的中间结果和输出
├── test_images/             # (DEPRECATED) 旧的测试图片目录, 请使用 my_test_images
├── .env.example             # 环境变量示例文件
├── README.md                # 项目说明文档
└── requirements.txt         # Python 依赖
```

## 快速开始

### 1. 环境准备

确保您已安装 Python 3.8+。

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API 密钥

复制 `.env.example` 为 `.env`，并填入您的 OhMyGPT API 密钥。

```ini
# .env
OHMYGPT_API_KEY="sk-YOUR_OHMYGPT_API_KEY"
```

### 4. 运行分析管道

使用 `main.py` 作为入口程序，运行完整的试卷分析管道。

```bash
python main.py --input-dir ./my_test_images --workspace ./temp/my_run --prompt-version v4
```

**常用参数说明:**
*   `--input-dir`: 包含待分析图片的目录。
*   `--workspace`: 指定本次运行的工作目录，所有中间结果和最终输出将保存在此。如果未指定，将自动生成一个时间戳目录。
*   `--prompt-version`: 指定使用的提示词版本（例如 `v4`）。
*   `--start-step`: 从指定步骤开始运行管道（例如 `--start-step 3`）。
*   `--end-step`: 在指定步骤结束管道运行（例如 `--end-step 4`）。
*   `--mock-case`: 使用模拟数据运行指定步骤，不进行实际 API 调用。
*   `--real-steps`: 强制指定步骤使用真实 API 调用，即使在 `--mock-case` 模式下。

## 技术架构

### 核心模型：Google Gemini (通过 OhMyGPT)

*   **多模态理解**: 强大的图像和文本理解能力，用于页面分类、布局分析、内容提取和视角矫正。
*   **提示工程**: 通过精心设计的提示词，引导模型输出结构化、准确的结果，并解决特定几何问题。

### 管道流程

项目采用模块化、可配置的管道设计，主要步骤包括：

1.  **页面分类 (Classification)**: 判断图片是试卷、答题纸还是其他类型。
2.  **视角矫正 (Perspective Correction)**: 利用 VLM 检测试卷四角，并进行透视变换，确保图像方正。
3.  **布局分析 (Layout Analysis)**: 识别试卷的整体布局，如分栏、题目区域等。
4.  **内容提取 (Content Extraction)**: 从识别出的题目区域中提取文本内容和结构。
5.  **结果合并 (Merge Results)**: 合并不同步骤的分析结果，形成统一的结构化数据。
6.  **输出可视化 (Draw Output)**: 在原始图片上绘制识别出的边界框和标签，方便人工校验。

### 工具与库

*   **Python**: 主要开发语言。
*   **Pillow**: 图像处理库，用于图像的旋转、裁剪和绘制。
*   **requests**: HTTP 客户端，用于与大模型 API 交互。
*   **dataclasses**: Python 内置模块，用于创建简洁的数据类。

## 开发规范

*   **模块化设计**: 每个管道步骤都封装在独立的 `src/tasks` 模块中。
*   **API 抽象**: `src/utils.py` 封装了通用的 API 调用逻辑和 JSON 提取。
*   **测试原则**: 尽可能使用 `--mock-case` 参数进行测试，以节省模型调用费用。通过 `--start-step` 和 `--workspace` 参数可以复用已完成的流水线步骤，专注于调试特定环节。
*   **坐标处理**: 遵循归一化 `[0, 1000]` 格式。
*   **日志记录**: 详细的日志输出，便于问题排查。

## 核心目录详解与数据流

为了更好地理解项目的工作方式，必须厘清 `src/`, `tests/` 和 `temp/` 这三个核心目录的职责与它们之间的数据流。

### 目录职责

*   **`src/` - 项目大脑 (The Brain)**
    *   包含所有核心的业务逻辑、算法和处理流水线。项目的绝大部分功能都在这里实现。

*   **`tests/mock_data/` - 测试案例库 (Test Case Library)**
    *   这是一个**只读的资产目录**，作为**模拟运行的输入源**。
    *   它里面包含了许多以 `case_` 或 `final_` 命名的子目录，每一个都代表一个完整的、已知的测试案例。
    *   这些案例是过去通过“录制模式”真实运行后保存下来的“标准答案”，包含了流水线每一步的输出JSON。
    *   **核心用途**:
        1.  **离线开发**: 无需API密钥或网络即可运行和调试程序。
        2.  **节省成本**: 避免在开发和测试中反复调用付费API。
        3.  **结果一致性**: 确保测试的输入是固定的，便于自动化回归测试。

*   **`temp/` - 临时工作台 (Temporary Workbench)**
    *   这是一个**临时的、用于输出的工作目录**。
    *   **所有模式（真实、模拟、混合）的运行结果**都会被输出到这里。程序会在此目录下创建一个带时间戳的子目录（例如 `run_20260312_213200`），用于存放当次运行的所有中间文件和最终产物。
    *   这个目录是**易失的 (Volatile)**，可以随时安全地删除，不会影响项目的核心功能或测试案例库。

### 运行模式与数据流

`main.py` 支持三种主要运行模式，它们决定了数据如何在上述目录间流动。

#### 1. 真实运行 (Real Mode)

*   **目的**: 对新的、真实的图片进行完整的在线分析。
*   **命令**: `python main.py --input-dir <你的图片目录>`
*   **数据流**:
    *   **输入**: `<你的图片目录>` (例如: `my_test_images/`)
    *   **处理**: 调用真实的API (例如: DashScope)
    *   **输出**: `temp/<run_timestamp>/`

#### 2. 模拟运行 (Mock Mode)

*   **目的**: 使用“测试案例库”中的数据进行快速的、离线的程序逻辑验证。
*   **命令**: `python main.py --mock-case <案例名称>` (例如: `final_test`)
*   **数据流**:
    *   **输入**: `tests/mock_data/<案例名称>/`
    *   **处理**: **跳过所有API调用**，直接读取案例库中的JSON文件作为每一步的输入。
    *   **输出**: `temp/<run_timestamp>/` (程序会把从案例库复制来的文件放在这里，以模拟真实运行的结构)

#### 3. 录制模式 (Recording Mode)

*   **目的**: 运行一次真实的分析，并将其结果保存为一个**新的、可复用的测试案例**。
*   **命令**: `python main.py --input-dir <你的图片目录> --record-case <新案例名称>`
*   **数据流**:
    *   **输入**: `<你的图片目录>`
    *   **处理**: 调用真实的API
    *   **输出**: `tests/mock_data/<新案例名称>/` (直接写入“测试案例库”，而不是 `temp/` 目录)

## 许可证

个人项目，仅供学习使用。
