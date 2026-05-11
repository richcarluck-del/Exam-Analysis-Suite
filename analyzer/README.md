# Exam Analysis RAG - 智能试卷分析系统

## 项目概述

本项目是一个基于 **混合式检索增强生成 (Hybrid Retrieval-Augmented Generation)** 的智能问答系统，专为教育场景设计。它深度融合了 **知识图谱 (Knowledge Graph)** 和 **向量数据库 (Vector Database)**，旨在提供比传统 RAG 更精准、更具逻辑性的答案。

- **核心能力**: 理解并回答基于提供的知识库（如教材、讲义的PDF）的复杂问题。
- **关键特色**: 采用图谱与向量结合的双路检索策略，既能理解实体间的逻辑关系，又能捕捉长文本的语义相似性。

---

## 技术栈 (Tech Stack)

| 分类         | 技术/库                                       | 作用与说明                                                                 |
|--------------|-----------------------------------------------|----------------------------------------------------------------------------|
| **后端框架**   | FastAPI                                       | 高性能的异步Web框架，用于提供API接口。                                         |
| **前端框架**   | React (Vite)                                  | 用于构建用户交互界面。                                                     |
| **异步任务**   | Celery & Redis                                | 处理耗时的数据摄入任务 (如PDF解析、LLM调用、数据库写入)。                  |
| **图数据库**   | Neo4j                                         | 存储知识图谱中的实体和关系，负责**结构化知识**的检索。                     |
| **向量数据库** | ChromaDB (嵌入式)                             | 存储文本块的向量，负责**非结构化内容**的语义相似度搜索。                   |
| **应用数据库** | PostgreSQL                                    | 存储应用自身的数据，如用户信息、Provider 配置与题库业务数据。               |
| **ORM**        | SQLAlchemy                                    | 通过 `shared/database.py` 统一连接 PostgreSQL。                                           |
| **LLM 调用**   | httpx                                         | 用于向符合OpenAI规范的大模型API发送请求。                                    |
| **向量生成**   | sentence-transformers                         | 将文本块转换为高质量的语义向量。                                           |

---

## 架构与数据流

### 1. 数据摄入 (Ingestion)

当用户在管理后台点击“Start Ingestion”时，会触发一个 Celery 异步任务：

1.  **解析文档**: 系统读取 `knowledge_base` 目录下的 PDF 或 TXT 文件。
2.  **双路处理**: 对每个文档的内容进行并行的两种处理：
    *   **图谱路径**: 调用大模型 (LLM) 提取文中的**实体**和**关系**，然后存入 **Neo4j** 数据库。
    *   **向量路径**: 将长文本**切块 (Chunking)**，然后使用 `sentence-transformers` 模型将每个文本块**向量化**，最终存入 **ChromaDB** 数据库。

### 2. 问答 (Question Answering)

当用户在聊天页面提问时：

1.  **关键词提取**: 调用一次 LLM，从用户问题中提取核心**关键词**。
2.  **混合检索 (Hybrid Search)**: 系统**同时**执行两种搜索：
    *   **图谱搜索**: 使用关键词在 **Neo4j** 中查找相关的实体及其邻居节点。
    *   **向量搜索**: 使用完整的用户问题，在 **ChromaDB** 中查找语义最相似的文本块。
3.  **上下文融合**: 将图谱搜索的“结构化知识”和向量搜索的“原文片段”融合成一个强大的“超级上下文”。
4.  **生成答案**: 将融合后的上下文和原始问题一起发送给 LLM，要求它基于此上下文来生成最终答案。

---

## 如何运行项目

### 1. 环境设置

**警告：本项目严格依赖 Python 3.10 版本。**

在设置本地开发环境时，**必须**使用 **Python 3.10** 来创建虚拟环境。使用任何其他较新或较旧的 Python 版本都将导致 `requirements.txt` 中的部分依赖（如 `neo4j` 和 `PyMuPDF`）因缺少预编译包而安装失败。

为避免浪费大量时间，请严格遵循以下步骤：

1.  **确认 Python 3.10 已安装**：确保您的系统中已安装 Python 3.10。
2.  **使用 Python 3.10 创建虚拟环境**：
    ```powershell
    # 假定 `py -3.10` 可以调用到您的 Python 3.10 解释器
    py -3.10 -m venv .venv
    ```
3.  **激活虚拟环境**：
    ```powershell
    .\.venv\Scripts\Activate.ps1
    ```
4.  **安装依赖**：
    ```powershell
    pip install -r requirements.txt
    ```
5.  **前端依赖**：
    进入 `client-app` 目录，运行 `npm install`。

**请务必遵守此约定，这是保证项目顺利运行的关键前提。**

### 2. 关键配置文件

- **应用数据库**: 本项目的关系型数据库统一通过项目根 `DATABASE_URL` 指向 **PostgreSQL**，数据库入口位于 `shared/database.py`。
- **Neo4j 配置**: Neo4j 的连接信息同样在 `app/config.py` 中。

### 3. 启动服务

您需要**依次启动 5 个独立的服务**。请为每个服务打开一个独立的终端窗口。

1.  **Neo4j 数据库**: 通过 Neo4j Desktop 或其他方式启动您本地的 Neo4j 服务。

2.  **Redis**: (假设您已通过其他方式安装并启动了 Redis Server)

3.  **启动 Celery Worker** (负责后台任务):
    ```powershell
    # 激活虚拟环境
    .\.venv\Scripts\Activate.ps1
    # 启动 Celery
    .\start_celery.ps1
    ```

4.  **启动 FastAPI 后端** (提供 API):
    ```powershell
    # 激活虚拟环境
    .\.venv\Scripts\Activate.ps1
    # 启动 FastAPI
    .\start_fastapi.ps1
    ```

5.  **启动 Vite 前端** (提供UI):
    ```powershell
    # 进入 client-app 目录
    cd client-app
    # 启动 Vite
    npm run dev 
    # (或者使用根目录的脚本 .\start_vite.ps1)
    ```

### 4. 特别注意

- **关于 Neo4j 的“假死”问题**: 根据排错经验，即使 Neo4j Desktop 界面显示服务为 `RUNNING` 状态，它也可能处于一种无法正确响应连接请求的“假死”状态。如果您在启动 Celery 后遇到关于 `Unable to retrieve routing information` 的错误，最有效的解决方案是：**在 Neo4j Desktop 中手动停止 (Stop) 该数据库实例，然后再重新启动 (Start) 它**。一次干净的重启通常能解决此问题。

### 5. 开发工具脚本

项目根目录下提供了一些便捷的 `.ps1` (PowerShell) 脚本：

- `start_*.ps1`: 用于启动各项服务。
- `stop_*.ps1`: 用于停止各项服务。
- `clear_dbs.py`: **一个非常重要的工具脚本**，用于清空 Neo4j 和 ChromaDB 中的所有数据。在重新进行数据摄入前，强烈建议运行此脚本 (`python clear_dbs.py`) 以保证数据干净。

---

## 目录结构

```
.
├── app/                # 后端 FastAPI 应用的核心代码
│   ├── __init__.py
│   ├── config.py       # **关键：数据库和应用配置**
│   ├── crud.py         # 数据库增删改查操作
│   ├── database.py     # SQLAlchemy 数据库引擎设置
│   ├── graph_db.py     # Neo4j 图数据库交互模块
│   ├── main.py         # FastAPI 应用主文件，定义所有API端点
│   ├── models.py       # SQLAlchemy 数据模型
│   ├── schemas.py      # Pydantic 数据校验模型
│   ├── security.py     # 密码和Token安全相关
│   ├── tasks.py        # Celery 异步任务定义 (核心的数据摄入逻辑)
│   ├── vector_db.py    # ChromaDB 向量数据库交互模块
│   └── worker.py       # Celery Worker 配置
├── client-app/         # 前端 React 应用代码
├── knowledge_base/     # 存放用于学习的源文件 (PDF, TXT等)
├── chroma_db/          # **ChromaDB 向量数据库的本地存储目录**
├── requirements.txt    # 后端 Python 依赖
└── README.md           # 本文件
```
