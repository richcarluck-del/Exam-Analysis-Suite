# 项目整合计划：构建统一的试卷分析套件

## 1. 目标与理念

将 `Exam-Analysis-RAG0227` (预处理器) 和 `Exam-Analysis-RAG-Clean` (分析器) 两个独立的项目，整合到一个名为 `Exam-Analysis-Suite` 的单一代码库 (Monorepo) 中。遵循“统一工作区，独立模块化”的设计理念，实现以下目标：

- **低耦合**: 两个核心模块（`preprocessor`, `analyzer`）在功能上完全解耦，通过定义好的文件目录作为“数据契约”进行通信。
- **易于管理**: 所有代码在同一个 Git 仓库中进行版本控制，便于原子性提交和统一依赖管理。
- **职责清晰**: 每个模块和目录的职责都一目了然，便于独立开发、测试和维护。

---

## 2. 独立测试能力保障

此整合方案将严格保障并增强每个模块独立开发与测试的能力，确保不强依赖于顶层协调器。

-   **模块级独立运行**:
    -   改造后的 `preprocessor/main.py` 和 `analyzer/main.py` 不仅是流程中的一环，其本身就是**功能完整的可执行脚本**。
    -   开发者可以随时进入 `preprocessor/` 目录，通过 `python main.py --input-image <...> --output-dir <...>` 命令，只针对预处理模块进行开发、调试和测试。
    -   同理，只要准备好符合“数据契约”的输入文件夹，就可以独立运行 `analyzer` 模块。

-   **保留单元测试**:
    -   `preprocessor/` 和 `analyzer/` 将各自保留其 `tests/` 目录（例如 `preprocessor/tests/`）。
    -   这允许开发者在各自的模块内编写和运行单元测试 (Unit Tests) 和集成测试 (Integration Tests)，而无需启动完整的端到端流程。
    -   测试框架（如 `pytest`）可以被配置为在模块级别独立运行。

-   **清晰的开发边界**:
    -   开发人员在修改 `preprocessor` 的功能时，其工作范围被严格限制在 `preprocessor/` 和 `shared/` 目录内，完全不必担心会意外影响到 `analyzer` 模块，反之亦然。

---

## 3. 计划实施步骤

### **Phase 1: 代码维度的重组 (Code Scaffolding & Migration)**

此阶段的目标是建立新的项目骨架，并将现有代码迁移进来。

- [ ] **创建项目根目录**: 在当前工作区的同级目录下，创建一个名为 `Exam-Analysis-Suite` 的新文件夹。
- [ ] **创建模块子目录**: 在 `Exam-Analysis-Suite` 内部，创建以下核心目录：
    - `preprocessor/` (用于存放预处理器项目)
    - `analyzer/` (用于存放分析器项目)
    - `shared/` (用于存放共享的数据模型和数据库访问逻辑)
    - `workspace/` (用于存放所有运行的临时产物，替代旧的 `temp/` 目录)
    - `exam_images/` (用于存放待处理的原始试卷图片)
- [ ] **复制预处理器 (`Exam-Analysis-RAG0227`)**: 将当前 `Exam-Analysis-RAG0227` 目录下的所有相关文件和文件夹 (`src/`, `main.py`, `requirements.txt`, `tests/` 等) **复制**到新的 `preprocessor/` 目录中。
- [ ] **复制分析器 (`Exam-Analysis-RAG-Clean`)**: 将 `Exam-Analysis-RAG-Clean` 项目的所有文件**复制**到新的 `analyzer/` 目录中。 (此步骤假设 `Exam-Analysis-RAG-Clean` 具有类似的项目结构)。

### **Phase 2: 功能维度的解耦 (Defining the Contract)**

此阶段的目标是改造两个模块的入口，使其成为可被外部调用的、遵守“数据契约”的独立工具。

- [ ] **改造 `preprocessor/main.py`**: 
    - 修改其 `main` 函数，使其不再写死输入输出路径。
    - 使用 `argparse` 库，为脚本添加入口参数：`--input-image` (接收单张原始试卷图片路径) 和 `--output-dir` (指定本次处理的输出目录)。
- [ ] **改造 `analyzer/main.py`**:
    - 同样使用 `argparse` 库，为脚本添加入口参数：`--input-dir` (接收预处理器产出的目录路径) 和 `--output-dir` (指定存放最终分析报告的目录)。
- [ ] **定义数据契约**: 明确 `preprocessor` 的输出格式。例如，约定它在 `--output-dir` 中必须生成：
    - `images/` 子目录，存放所有切好的题目图片 (e.g., `question_1.png`)。
    - `metadata.json` 文件，包含所有题目的元信息 (e.g., 题号、在原图中的坐标等)。

### **Phase 3: 数据维度的共享 (Shared Data Layer)**

此阶段的目标是建立一个共享的数据访问层，以优雅地处理共用的数据库。

- [ ] **实现共享数据库模型**: 在 `shared/models.py` 中，使用 SQLAlchemy 或类似的 ORM 框架定义所有需要跨模块共享的数据表模型（例如 `KnowledgePoint`, `Subject` 等）。
- [ ] **实现共享数据访问逻辑**: 在 `shared/database.py` 中，编写用于连接数据库的引擎、创建会话的逻辑，以及所有对共享表的增删改查函数 (例如 `get_knowledge_point_by_name()`)。
- [ ] **重构模块以使用共享层**: 
    - 审查 `preprocessor` 和 `analyzer` 的代码。
    - 移除它们各自内部的任何数据库连接或模型定义代码。
    - 修改代码，使其通过 `from shared.database import ...` 的方式来调用共享数据访问层的函数。

### **Phase 4: 顶层协调与文档完善 (Orchestration & Documentation)**

此阶段的目标是创建一个统一的入口来运行完整流程，并完善项目文档。

- [ ] **创建顶层协调器 (`run_pipeline.py`)**: 在 `Exam-Analysis-Suite` 根目录下创建此文件。它将：
    - 接收一个原始试卷图片作为输入。
    - 使用 `subprocess.run()` 按顺序调用 `preprocessor/main.py` 和 `analyzer/main.py`，并正确地传递输入输出路径。
    - 提供端到端流程的统一入口。
- [ ] **合并依赖**: 整合 `preprocessor/requirements.txt` 和 `analyzer/requirements.txt` 的内容，在项目根目录下创建一个统一的 `requirements.txt` 文件。
- [ ] **撰写顶层 `README.md`**: 在根目录下创建新的 `README.md`，详细说明：
    - 项目的新架构和理念。
    - 每个模块 (`preprocessor`, `analyzer`, `shared`) 的职责。
    - 如何独立运行每个模块。
    - 如何使用 `run_pipeline.py` 运行端到端流程。

### **Phase 5: 最终化与验证 (Finalization & Verification)**

- [ ] **初始化 Git 仓库**: 在 `Exam-Analysis-Suite` 根目录下运行 `git init`，并完成项目的首次提交。
- [ ] **端到端测试**: 运行 `run_pipeline.py`，传入一张测试图片，验证从预处理到分析的整个流程是否能顺利跑通。
