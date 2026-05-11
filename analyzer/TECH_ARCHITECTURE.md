# 技术架构文档: 学情分析与智能辅导系统

## 1. 系统架构总览

本系统采用**前后端分离的微服务架构**，确保各模块的独立性、可扩展性和可维护性。核心处理流程通过消息队列进行异步解耦，提升系统的响应速度和鲁棒性。

**架构图 (逻辑)**:
```mermaid
graph TD
    A[用户客户端 - Web/App] -->|HTTPS RESTful API| B(Nginx 网关)
    B --> C{后端API服务 (FastAPI)}
    C -->|任务入队| D[消息队列 (Celery + Redis)]
    C -->|读写业务数据| E[业务数据库 (PostgreSQL)]
    C -->|查询图谱数据| F[图数据库 (Neo4j)]
    
    G[AI Worker] -->|从队列获取任务| D
    G -->|OCR识别| H[OCR服务]
    G -->|LLM分析/GraphRAG| I[大语言模型服务]
    G -->|更新图谱| F
    G -->|写回分析结果| E
```

## 2. 技术栈 (Technology Stack)

| 领域 | 技术选型 | 备注 |
|---|---|---|
| **前端** | React (Vite), Tailwind CSS, Recharts | 现代、高效的Web开发框架，Recharts用于数据可视化。 |
| **后端** | Python (FastAPI), SQLAlchemy | FastAPI提供高性能API，SQLAlchemy作为ORM与数据库交互。 |
| **业务数据库** | PostgreSQL | 成熟、稳定、功能强大的关系型数据库，用于存储用户信息、试卷、题目等结构化数据。 |
| **图数据库** | Neo4j | 领先的图数据库，用于存储和查询学生知识图谱，是实现GraphRAG的核心。 |
| **消息队列** | Celery + Redis | 实现OCR、AI分析等耗时任务的异步处理。 |
| **AI & ML** | PaddleOCR, LangChain, OpenAI/Gemini | PaddleOCR用于试卷识别，LangChain作为框架与LLM交互。 |
| **部署** | Docker, Docker Compose, Nginx | 容器化部署，简化环境管理和扩展。Nginx作为反向代理和负载均衡。 |

## 3. 核心实现方案

### 3.1. GraphRAG 实现方案

GraphRAG (Graph-based Retrieval-Augmented Generation) 是本系统的技术核心，旨在为LLM提供更精确、更具上下文的知识，以克服传统RAG仅依赖文本向量检索的局限性。

**流程**:
1.  **知识图谱构建**: 每次试卷分析完成后，将题目考察的知识点（如：“一元二次方程求根公式”）作为节点（`KnowledgePoint`）存入Neo4j。如果节点已存在，则更新其`mastery_level`（掌握度）等属性。同时，根据预设的教材知识体系，创建知识点之间的关联关系（`prerequisite_for`, `related_to`）。

2.  **检索 (Retrieval)**: 当需要为学生A的薄弱知识点“二次函数图像”生成学习建议时，不仅仅是查询这个节点本身。系统会执行一个图查询（Cypher Query），检索与“二次函数图像”相关的整个**子图**。这个子图可能包括：
    - 它的前置知识点（如：“一元二次方程”）。
    - 它的后续知识点（如：“二次函数与不等式”）。
    - 与它相关的常见错误类型。

3.  **增强 (Augmentation)**: 将检索到的子图信息（节点、关系、属性）序列化为文本或结构化数据。这份数据比简单的文本片段包含了更丰富的逻辑关系和上下文。

4.  **生成 (Generation)**: 将增强后的上下文信息，连同原始请求（“为我生成二次函数图像的学习建议”），一起发送给LLM。由于LLM获得了关于该知识点全方位的、结构化的背景知识，它能够生成远比通用模型更具针对性和深度的回答。

### 3.2. 数据模型 (Data Models)

**PostgreSQL - 主要表**: 
- `users`: (id, username, role, ...)
- `exams`: (id, user_id, subject, exam_date, ...)
- `questions`: (id, exam_id, question_text, ocr_result, correct_answer, student_answer, is_correct, ...)
- `question_analysis`: (id, question_id, difficulty, llm_analysis_text, ...)
- `knowledge_links`: (question_id, knowledge_point_id)

**Neo4j - 图模型**:
- **节点 (Nodes)**:
    - `(:Student {id, name})`
    - `(:KnowledgePoint {id, name, subject, chapter})`
- **关系 (Relationships)**:
    - `(s:Student)-[:MASTERS {level: 'A', history: [...]}]->(k:KnowledgePoint)`: 表示学生对某个知识点的掌握情况。
    - `(k1:KnowledgePoint)-[:PREREQUISITE_FOR]->(k2:KnowledgePoint)`: 表示知识点之间的前置依赖关系。

## 4. API 设计 (Endpoints)

- `POST /api/v1/exams/upload`: 上传试卷图片，启动异步分析流程。
    - **返回**: `{"task_id": "..."}`
- `GET /api/v1/tasks/{task_id}/status`: 查询异步任务的状态。
- `GET /api/v1/students/{student_id}/exams/{exam_id}`: 获取单次考试的详细分析结果。
- `GET /api/v1/students/{student_id}/knowledge_graph`: 获取学生的个人知识图谱数据（用于前端可视化）。
- `POST /api/v1/students/{student_id}/recommendations`: 为学生请求个性化的学习建议和练习题。

## 5. 部署与运维

- 所有服务（FastAPI, Neo4j, PostgreSQL, etc.）都将打包成独立的Docker镜像。
- 使用 `docker-compose.yml` 在开发和生产环境中编排和管理所有容器。
- 设立独立的AI Worker服务，并可以根据负载进行水平扩展，以处理高并发的分析任务。
