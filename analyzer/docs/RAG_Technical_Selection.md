# RAG 系统技术选型与实现路径

## 一、项目背景分析

**当前系统架构**：
- 后端：Python Flask
- 数据库：PostgreSQL
- 大模型：通义千问（Qwen）、OpenAI 等
- 前端：React + Vite
- 已有功能：考试分析、图片识别、提示词实验区

**RAG 应用场景**：
1. 考试知识点检索
2. 历史试题库检索
3. 教学资料检索
4. 错题本智能检索
5. 知识图谱构建

---

## 二、技术选型

### 1. RAG 框架选择

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **LangChain** | 生态完善、文档丰富、社区活跃 | 抽象层较多、学习曲线陡 | ⭐⭐⭐⭐⭐ |
| **LlamaIndex** | 专注数据索引、易上手 | 功能相对单一 | ⭐⭐⭐⭐ |
| **自研实现** | 完全可控、轻量 | 开发成本高、功能有限 | ⭐⭐⭐ |

**推荐方案**：**LangChain** 
- 理由：成熟稳定、与现有架构兼容、支持多种向量数据库和嵌入模型

### 2. 向量数据库选择

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **ChromaDB** | 轻量、本地、易用、开源 | 大规模性能一般 | ⭐⭐⭐⭐⭐ |
| **FAISS** | 高性能、Facebook 出品 | 需要手动管理索引 | ⭐⭐⭐⭐ |
| **Milvus** | 企业级、高性能 | 部署复杂、资源占用大 | ⭐⭐⭐ |
| **Pinecone** | 云服务、免维护 | 收费、数据安全 | ⭐⭐ |

**推荐方案**：**ChromaDB**
- 理由：轻量级、本地部署、与 LangChain 集成良好、适合中小规模数据

### 3. 嵌入模型选择

| 方案 | 优点 | 缺点 | 推荐度 |
|------|------|------|--------|
| **DashScope Embeddings** | 与现有 Qwen 配合好、中文优化 | 需要 API 调用 | ⭐⭐⭐⭐⭐ |
| **OpenAI Embeddings** | 质量高、多语言 | 收费、需要翻墙 | ⭐⭐⭐⭐ |
| **BGE (本地)** | 免费、中文优化、开源 | 需要本地资源 | ⭐⭐⭐⭐ |
| **M3E (本地)** | 轻量、中文优化 | 性能略低 | ⭐⭐⭐ |

**推荐方案**：**DashScope Embeddings + BGE 本地备选**
- 理由：与现有通义千问配合好、支持中文、有本地备选方案

### 4. 文档处理方案

| 文档类型 | 处理工具 | 说明 |
|---------|---------|------|
| PDF | PyPDF2 / pdfplumber | 提取文本和表格 |
| Word | python-docx | 提取文本和表格 |
| 图片 | OCR (PaddleOCR) | 已集成 |
| Excel | openpyxl / pandas | 提取结构化数据 |
| Markdown | 直接读取 | 无需转换 |

### 5. 文本分割策略

| 策略 | 适用场景 | 推荐参数 |
|------|---------|---------|
| **RecursiveCharacterTextSplitter** | 通用文本 | chunk_size=500, overlap=50 |
| **MarkdownTextSplitter** | Markdown 文档 | 按标题分割 |
| **SemanticChunker** | 语义分割 | 基于句子相似度 |

---

## 三、系统架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                        前端界面                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 文档上传  │  │ 知识检索  │  │ 智能问答  │  │ 知识管理  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      后端 API 层                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Flask REST API                                       │  │
│  │  - /api/rag/upload      文档上传                      │  │
│  │  - /api/rag/search      知识检索                      │  │
│  │  - /api/rag/chat        智能问答                      │  │
│  │  - /api/rag/documents   文档管理                      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      RAG 核心层                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ 文档处理器  │  │ 向量存储    │  │ 检索器      │          │
│  │ - 加载器    │  │ - ChromaDB │  │ - 相似度    │          │
│  │ - 分割器    │  │ - 索引管理  │  │ - 重排序    │          │
│  │ - 清洗器    │  │ - 持久化    │  │ - 过滤器    │          │
│  └────────────┘  └────────────┘  └────────────┘          │
│                                                              │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ 嵌入模型    │  │ 大模型      │  │ 提示工程    │          │
│  │ - DashScope│  │ - Qwen     │  │ - Template │          │
│  │ - BGE      │  │ - GPT      │  │ - Context  │          │
│  └────────────┘  └────────────┘  └────────────┘          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      数据存储层                             │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ PostgreSQL │  │ ChromaDB   │  │ 文件系统    │          │
│  │ - 业务数据  │  │ - 向量索引  │  │ - 原始文档  │          │
│  │ - 元数据    │  │ - 嵌入向量  │  │ - 缓存      │          │
│  └────────────┘  └────────────┘  └────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、实现路径（分阶段）

### 阶段一：基础 RAG 功能（1-2 周）

**目标**：实现基本的文档上传、向量化和检索功能

**任务清单**：
1. ✅ 安装依赖包
   ```bash
   pip install langchain langchain-community chromadb
   pip install langchain-openai langchain-dashscope
   pip install pypdf python-docx pandas
   ```

2. ✅ 创建向量数据库模块
   - 初始化 ChromaDB
   - 配置嵌入模型
   - 实现文档向量化

3. ✅ 实现文档处理
   - PDF 文档加载器
   - 文本分割器
   - 元数据提取

4. ✅ 实现检索功能
   - 相似度检索
   - 混合检索（关键词 + 向量）
   - 检索结果排序

5. ✅ 创建 API 接口
   - 文档上传接口
   - 知识检索接口
   - 文档管理接口

**交付物**：
- 基础 RAG 服务
- API 接口文档
- 测试用例

---

### 阶段二：智能问答功能（1-2 周）

**目标**：实现基于 RAG 的智能问答

**任务清单**：
1. ✅ 实现问答链
   - 提示词模板设计
   - 上下文构建
   - 答案生成

2. ✅ 优化检索策略
   - 多路召回
   - 重排序
   - 去重

3. ✅ 添加引用来源
   - 标注答案来源
   - 显示相关文档片段
   - 置信度评分

4. ✅ 前端界面
   - 问答界面
   - 来源展示
   - 历史记录

**交付物**：
- 智能问答系统
- 前端界面
- 使用文档

---

### 阶段三：高级功能（2-3 周）

**目标**：增强 RAG 系统的能力

**任务清单**：
1. ✅ 多模态支持
   - 图片 OCR + RAG
   - 表格理解
   - 图文混合检索

2. ✅ 知识图谱
   - 实体抽取
   - 关系抽取
   - 图谱可视化

3. ✅ 个性化检索
   - 用户画像
   - 检索历史
   - 推荐算法

4. ✅ 性能优化
   - 缓存机制
   - 异步处理
   - 批量索引

**交付物**：
- 高级 RAG 功能
- 性能报告
- 用户手册

---

### 阶段四：应用集成（1 周）

**目标**：将 RAG 集成到现有考试分析系统

**任务清单**：
1. ✅ 考试知识点检索
   - 知识点库建设
   - 关联试题
   - 学习路径

2. ✅ 错题本智能分析
   - 错题归因
   - 知识点定位
   - 推荐练习

3. ✅ 试题生成
   - 基于知识点生成试题
   - 难度控制
   - 多样性保证

**交付物**：
- 集成系统
- 测试报告
- 部署文档

---

## 五、技术细节

### 1. 目录结构

```
Exam-Analysis-RAG/
├── src/
│   ├── rag/                    # RAG 模块
│   │   ├── __init__.py
│   │   ├── document_loader.py  # 文档加载器
│   │   ├── text_splitter.py    # 文本分割器
│   │   ├── embeddings.py       # 嵌入模型
│   │   ├── vector_store.py     # 向量存储
│   │   ├── retriever.py        # 检索器
│   │   ├── qa_chain.py         # 问答链
│   │   └── utils.py            # 工具函数
│   ├── models/                 # 数据模型
│   │   ├── rag_document.py     # RAG 文档模型
│   │   └── rag_config.py       # RAG 配置模型
│   └── api/                    # API 路由
│       └── rag_routes.py       # RAG API 路由
├── data/
│   ├── rag/                    # RAG 数据目录
│   │   ├── documents/          # 原始文档
│   │   ├── chroma_db/          # 向量数据库
│   │   └── cache/              # 缓存
│   └── knowledge_base/         # 知识库
├── tests/
│   └── test_rag.py             # RAG 测试
└── docs/
    └── rag_usage.md            # 使用文档
```

### 2. 核心代码示例

**向量存储初始化**：
```python
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

# 初始化嵌入模型
embeddings = OpenAIEmbeddings(
    model="text-embedding-ada-002"
)

# 初始化向量存储
vectorstore = Chroma(
    persist_directory="./data/rag/chroma_db",
    embedding_function=embeddings
)

# 文本分割器
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50
)
```

**文档索引**：
```python
from langchain_community.document_loaders import PyPDFLoader

# 加载 PDF
loader = PyPDFLoader("example.pdf")
documents = loader.load()

# 分割文本
texts = text_splitter.split_documents(documents)

# 添加到向量存储
vectorstore.add_documents(texts)
```

**检索和问答**：
```python
from langchain.chains import RetrievalQA
from langchain_openai import ChatOpenAI

# 初始化大模型
llm = ChatOpenAI(model="gpt-3.5-turbo")

# 创建检索器
retriever = vectorstore.as_retriever(
    search_type="similarity",
    search_kwargs={"k": 3}
)

# 创建问答链
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever=retriever,
    return_source_documents=True
)

# 提问
result = qa_chain({"query": "什么是机器学习？"})
print(result['result'])
print(result['source_documents'])
```

---

## 六、成本估算

### 1. 开发成本

| 阶段 | 工作量 | 人力成本 |
|------|--------|---------|
| 阶段一 | 1-2 周 | 1 人 |
| 阶段二 | 1-2 周 | 1 人 |
| 阶段三 | 2-3 周 | 1 人 |
| 阶段四 | 1 周 | 1 人 |
| **总计** | **5-8 周** | **1 人** |

### 2. 运行成本

| 项目 | 费用 | 说明 |
|------|------|------|
| 嵌入模型 API | ¥0.0007/千 token | DashScope |
| 大模型 API | ¥0.004/千 token | Qwen-Turbo |
| 向量存储 | 免费 | 本地 ChromaDB |
| 服务器 | 现有服务器 | 无额外成本 |

**预估月成本**：¥100-500（取决于使用量）

---

## 七、风险评估

| 风险 | 影响 | 概率 | 应对措施 |
|------|------|------|---------|
| 检索质量不高 | 高 | 中 | 优化分割策略、多路召回 |
| API 成本过高 | 中 | 低 | 使用本地模型、缓存优化 |
| 性能瓶颈 | 中 | 中 | 异步处理、索引优化 |
| 数据安全 | 高 | 低 | 本地部署、数据加密 |

---

## 八、下一步行动

**立即开始**：
1. ✅ 安装依赖包
2. ✅ 创建 RAG 模块目录结构
3. ✅ 实现基础向量存储功能
4. ✅ 测试文档索引和检索

**本周目标**：
- 完成阶段一的基础功能
- 实现文档上传和检索 API
- 前端基础界面

**下周目标**：
- 完成智能问答功能
- 优化检索质量
- 集成到现有系统

---

## 九、参考资源

1. **LangChain 文档**：https://python.langchain.com/docs/
2. **ChromaDB 文档**：https://docs.trychroma.com/
3. **DashScope API**：https://help.aliyun.com/zh/dashscope/
4. **RAG 最佳实践**：https://blog.langchain.dev/deconstructing-rag/

---

**准备好开始实施了吗？我可以帮您逐步实现每个阶段的功能！** 🚀
