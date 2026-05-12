# Exam-Analysis-Suite 系统架构图

> 生成时间：2026-04-28
> 基于工程源码扫描自动整理

---

## 1. 系统全景架构

```mermaid
graph TB
    subgraph 入口层["入口层"]
        CLI_PIPE["run_pipeline.py<br/>端到端Pipeline"]
    end

    subgraph Preprocessor["Preprocessor 预处理模块"]
        direction TB
        PMAIN["main.py<br/>预处理入口"]
        
        subgraph pipeline["预处理管道 Steps"]
            S0["Step 0<br/>图像预处理"]
            S1["Step 1<br/>透视校正"]
            S2["Step 2<br/>页面分类<br/>classify / long_image"]
            S3["Step 3<br/>布局分析"]
            S4["Step 4<br/>内容提取"]
            S45["Step 4.5<br/>答案提取"]
            S5["Step 5<br/>结果合并"]
            S6["Step 6<br/>答题卡识别<br/>answer_card_pipeline"]
            S7["Step 7<br/>生成完整单元"]
            S8["Step 8<br/>绘制输出"]
            S9["Step 9<br/>导出Bundle<br/>manifest.json + questions.json"]
        end

        subgraph answer_card["答题卡识别子模块"]
            OMR["OMR 扫描器"]
            OCR["OCR 检测器"]
            VLM["VLM 识别器"]
            HYBRID["混合识别器"]
        end

        subgraph src_core["核心能力 src/"]
            A3["a3_splitter<br/>A3分割"]
            AB["ab_comparison<br/>AB卷比对"]
            CLASSIFIER["classifier<br/>分类器"]
            MERGER["merger<br/>合并器"]
            PROMPTS["prompt_manager<br/>提示词管理"]
            LOGGER["enhanced_logger"]
        end

        PMAIN --> S0 --> S1 --> S2 --> S3 --> S4 --> S45 --> S5 --> S6 --> S7 --> S8 --> S9
        S6 --> answer_card
    end

    subgraph Analyzer["Analyzer 分析器模块"]
        direction TB
        
        subgraph offline["离线分析入口"]
            ARUN["run.py<br/>离线分析"]
        end

        subgraph online["在线服务"]
            FASTAPI["FastAPI<br/>analyzer/app/main.py"]
            CELERY["Celery<br/>异步任务"]
        end

        subgraph core["分析引擎"]
            RETRIEVER["retriever<br/>混合检索(hybrid_search)"]
            LLM["llm_client<br/>LLM / VLM 客户端"]
            KNOWLEDGE["knowledge_graph<br/>知识图谱"]
        end

        subgraph frontend["前端"]
            VITE["Vite 客户端<br/>client-app/"]
        end

        ARUN --> RETRIEVER
        ARUN --> LLM
        FASTAPI --> RETRIEVER
        FASTAPI --> LLM
        FASTAPI --> KNOWLEDGE
        FASTAPI --> CELERY
        VITE --> FASTAPI
    end

    subgraph Shared["Shared 共享层"]
        DB["database.py<br/>PostgreSQL 连接"]
        MODELS["models.py<br/>ORM 模型 (30+ 表)"]
        STEP_CFG["步骤配置<br/>llm_step_config / prompt_step_config"]
    end

    subgraph External["外部基础设施"]
        PG[("PostgreSQL<br/>关系数据库")]
        NEO4J[("Neo4j<br/>图数据库")]
        QDRANT[("Qdrant<br/>向量检索")]
        OPENSEARCH[("OpenSearch<br/>文本检索")]
        REDIS[("Redis<br/>消息队列/缓存")]
        EXT_LLM["外部 LLM / VLM API"]
    end

    subgraph Storage["存储挂载"]
        UPLOADS["uploads/<br/>上传文件"]
        NORMALIZED["normalized_documents/<br/>归一化文档"]
        KNOWLEDGE_BASE["knowledge_base/<br/>知识库"]
    end

    CLI_PIPE -->|"调起"| PMAIN
    CLI_PIPE -->|"读 bundle 调起"| ARUN
    
    PMAIN -->|"输出 bundle/"| ARUN
    
    DB --> PG
    RETRIEVER --> QDRANT
    RETRIEVER --> OPENSEARCH
    RETRIEVER --> NEO4J
    KNOWLEDGE --> NEO4J
    KNOWLEDGE --> PG
    CELERY --> REDIS
    LLM --> EXT_LLM
    
    FASTAPI --> DB
    ARUN --> DB
    PMAIN --> DB
    
    FASTAPI --> UPLOADS
    FASTAPI --> NORMALIZED
    FASTAPI --> KNOWLEDGE_BASE

    style 入口层 fill:#e1f5fe
    style Preprocessor fill:#fff3e0
    style Analyzer fill:#e8f5e9
    style Shared fill:#f3e5f5
    style External fill:#fce4ec
    style Storage fill:#e0f2f1
```

---

## 2. 离线处理链路 (端到端 Pipeline)

```mermaid
sequenceDiagram
    actor User as 用户
    participant Pipeline as run_pipeline.py
    participant Preprocessor as preprocessor/main.py
    participant Analyzer as analyzer/run.py
    participant DB as PostgreSQL
    participant LLM as LLM/VLM API

    User->>Pipeline: --input-dir (原始试卷图片)
    
    Pipeline->>Preprocessor: subprocess 调起
    activate Preprocessor
    
    Preprocessor->>Preprocessor: Step 0-2: 图像预处理+透视校正+分类
    Preprocessor->>Preprocessor: Step 3-4: 布局分析+内容提取
    Preprocessor->>Preprocessor: Step 4.5: 答案提取
    Preprocessor->>Preprocessor: Step 5-6: 合并+答题卡识别
    Preprocessor->>Preprocessor: Step 7-8: 生成完整单元+绘图
    Preprocessor->>Preprocessor: Step 9: 导出 Bundle
    
    deactivate Preprocessor
    
    Note over Preprocessor: 输出: manifest.json + questions.json
    
    Pipeline->>Analyzer: subprocess 调起 (传 bundle 目录)
    activate Analyzer
    
    Analyzer->>DB: resolve_prompt_template (获取提示词配置)
    DB-->>Analyzer: 提示词模板
    
    loop 逐题分析
        Analyzer->>Analyzer: build_retrieval_snapshot (混合检索)
        Analyzer->>LLM: call_vlm_on_image (题级VLM分析)
        LLM-->>Analyzer: VLM 观察结果
        
        Analyzer->>Analyzer: build_rule_based_final_conclusion
        Analyzer->>LLM: call_llm (LLM融合最终结论)
        LLM-->>Analyzer: 最终逐题结论
    end
    
    Analyzer->>Analyzer: build_analysis_report (汇总报告)
    deactivate Analyzer
    
    Note over Analyzer: 输出: analysis_report.json<br/>question_analyses.json
    
    Analyzer-->>Pipeline: 分析完成
    Pipeline-->>User: 端到端完成
```

---

## 3. 数据模型 ER 图

```mermaid
erDiagram
    Tenant ||--o{ ContentSource : "拥有"
    Tenant ||--o{ SourceDocument : "拥有"
    Tenant ||--o{ ExamSession : "拥有"
    
    ContentSource ||--o{ SourceDocument : "包含"
    
    SourceDocument ||--o{ DocumentParseJob : "解析任务"
    SourceDocument ||--o{ Paper : "试卷"
    SourceDocument ||--o{ ExamSession : "考试记录"
    SourceDocument ||--o{ KnowledgePackage : "知识专题包"
    
    Paper ||--o{ PaperSection : "章节"
    Paper ||--o{ PaperQuestion : "题目列表"
    
    QuestionItem ||--o{ PaperQuestion : "题目出现"
    QuestionItem ||--o{ QuestionBlock : "内容块"
    QuestionItem ||--o{ QuestionOption : "选项"
    QuestionItem }o--o| QuestionFamily : "题目家族"
    
    QuestionBlock ||--o| Formula : "公式"
    QuestionBlock ||--o| Asset : "资源"
    
    QuestionFamily ||--o| StrategyCard : "解题策略"
    
    KnowledgePackage ||--o{ KnowledgeBlock : "知识块"
    KnowledgePackage ||--o{ KnowledgePackagePoint : "包-知识点关联"
    KnowledgePackage ||--o{ KnowledgePackageQuestion : "包-题关联"
    
    KnowledgePoint ||--o{ KnowledgePackagePoint : "被关联"
    KnowledgePoint ||--o{ KnowledgePointProvenance : "来源溯源"
    KnowledgePoint ||--o{ KnowledgeAtom : "知识原子"
    KnowledgePoint ||--o{ KnowledgeDerivative : "知识衍生"
    KnowledgePoint ||--o{ KnowledgePointRelation : "知识点关系"
    
    KnowledgeBlock ||--o| KnowledgePoint : "关联知识点"
    KnowledgeBlock ||--o| Asset : "资源"
    
    TaxonomyNode ||--o| KnowledgePoint : "分类节点"
    
    ExamSession ||--o{ ExamSessionQuestion : "考试题目"
    ExamSession ||--o{ StudentAttempt : "学生作答"
    ExamSession ||--o{ DiagnosisSnapshot : "诊断快照"
    
    ExamSessionQuestion ||--o{ StudentAttempt : "作答记录"
    ExamSessionQuestion ||--o{ QuestionMatchResult : "题目匹配"
    
    User ||--o{ APIProvider : "管理"
    APIProvider ||--o{ LLMModel : "模型"
    
    LLMStepConfig }o--|| APIProvider : "使用"
    LLMStepConfig }o--|| LLMModel : "使用"
    
    Prompt ||--o{ PromptVersion : "版本"
    
    RetrievalDocument ||--o{ EmbeddingPoint : "向量"
    EntityGraphEdge }o--o| KnowledgePoint : "实体关系"

    KnowledgePackageQuestion }o--|| QuestionItem : "关联"
```

---

## 4. 在线服务架构

```mermaid
graph TB
    subgraph Client["客户端"]
        BROWSER["浏览器<br/>Vite SPA"]
    end

    subgraph Gateway["API 网关"]
        FASTAPI["FastAPI<br/>:8000"]
    end

    subgraph Workers["异步任务"]
        CELERY["Celery Worker"]
        BEAT["Celery Beat<br/>定时任务"]
    end

    subgraph Services["内部服务"]
        RETRIEVER_SVC["检索服务<br/>混合检索"]
        KNOWLEDGE_SVC["知识点服务<br/>图谱操作"]
        QUESTION_SVC["题库服务<br/>CRUD"]
        ANALYSIS_SVC["分析服务<br/>诊断/报告"]
        PROMPT_SVC["提示词管理"]
    end

    subgraph Data["数据层"]
        PG[("PostgreSQL<br/>关系数据")]
        QDRANT[("Qdrant<br/>向量")]
        OPENSEARCH[("OpenSearch<br/>文本")]
        NEO4J[("Neo4j<br/>图谱")]
        REDIS[("Redis<br/>消息队列")]
    end

    BROWSER -->|"HTTP :8000"| FASTAPI
    FASTAPI -->|"async task"| CELERY
    BEAT -->|"schedule"| CELERY
    
    FASTAPI --> RETRIEVER_SVC
    FASTAPI --> KNOWLEDGE_SVC
    FASTAPI --> QUESTION_SVC
    FASTAPI --> ANALYSIS_SVC
    FASTAPI --> PROMPT_SVC
    
    RETRIEVER_SVC --> QDRANT
    RETRIEVER_SVC --> OPENSEARCH
    KNOWLEDGE_SVC --> NEO4J
    KNOWLEDGE_SVC --> PG
    QUESTION_SVC --> PG
    ANALYSIS_SVC --> PG
    PROMPT_SVC --> PG
    
    CELERY --> PG
    CELERY --> REDIS
```

---

## 5. 部署拓扑 (Docker Compose)

```mermaid
graph TB
    subgraph Docker["Docker Compose 部署"]
        API["analyzer-api<br/>Dockerfile.analyzer-api<br/>FastAPI :8000"]
        WEB["analyzer-web<br/>Dockerfile.analyzer-web<br/>Nginx :80 → 宿主机 :8001"]
    end

    subgraph Host["宿主机服务"]
        PG[("PostgreSQL<br/>external")]
        QDRANT[("Qdrant<br/>:6333")]
        OPENSEARCH[("OpenSearch<br/>:9200")]
    end

    subgraph Volumes["挂载卷"]
        QB["question_bank/"]
        QBA["question_bank_assets/"]
        ND["normalized_documents/"]
    end

    WEB -->|"depends_on"| API
    API --> PG
    API --> QDRANT
    API --> OPENSEARCH
    API --> QB
    API --> QBA
    API --> ND
```

---

## 6. 预处理管道详细步骤

```mermaid
flowchart LR
    INPUT["输入<br/>原始试卷图片"] --> S0

    subgraph Pipeline["预处理管道"]
        S0["Step 0<br/>preprocess_images<br/>图像预处理/缩放"]
        S1["Step 1<br/>perspective_correction<br/>透视校正"]
        S2["Step 2<br/>classify<br/>页面分类<br/>(普通/长图)"]
        S3["Step 3<br/>analyze_layout<br/>布局分析"]
        S4["Step 4<br/>extract_content<br/>内容提取"]
        S4_5["Step 4.5<br/>extract_answers<br/>答案提取"]
        S5["Step 5<br/>merge_results<br/>结果合并"]
        S6["Step 6<br/>answer_card_pipeline<br/>答题卡识别"]
        S7["Step 7<br/>generate_complete_units<br/>完整单元生成"]
        S8["Step 8<br/>draw_output<br/>绘制标注输出"]
        S9["Step 9<br/>export_analysis_bundle<br/>导出Bundle"]
    end

    S0 --> S1 --> S2 --> S3 --> S4 --> S4_5 --> S5 --> S6 --> S7 --> S8 --> S9

    S9 --> OUTPUT["输出<br/>manifest.json<br/>questions.json"]

    style INPUT fill:#e1f5fe
    style OUTPUT fill:#e8f5e9
```

---

## 7. 包/模块依赖关系

```mermaid
graph TB
    subgraph Root["根目录"]
        RP["run_pipeline.py<br/>端到端编排"]
        DOCKER["docker-compose.analyzer.yml<br/>部署配置"]
        ALEMBIC["alembic/<br/>数据库迁移"]
    end

    shared["shared/<br/>共享层"]
    
    subgraph preprocessor["preprocessor/"]
        PM["main.py"]
        PS["src/<br/>核心处理"]
        PAC["answer_card/<br/>答题卡识别"]
        PT["tasks/<br/>任务管道"]
        PU["utils/<br/>工具函数"]
    end

    subgraph analyzer["analyzer/"]
        AR["run.py<br/>离线分析"]
        AA["app/<br/>在线服务"]
        AC["client-app/<br/>Vite前端"]
        AKB["knowledge_base/<br/>知识库"]
        AKP["knowledge_points/<br/>知识点"]
    end

    RP --> PM
    RP --> AR
    
    PM --> PS
    PS --> PT
    PS --> PU
    PT --> PAC
    
    AR --> shared
    AA --> shared
    PM --> shared
    
    RP --> shared
    
    AA --> AC
    AA --> AKB
    AA --> AKP
    
    DOCKER --> AA
    DOCKER --> AC
```

---

## 关键文件索引

| 层级 | 文件 | 说明 |
|------|------|------|
| **入口编排** | `run_pipeline.py` | 端到端 Pipeline（preprocessor → analyzer） |
| **预处理** | `preprocessor/main.py` | 预处理模块入口 |
| **预处理任务** | `preprocessor/src/tasks/` | 10 个预处理步骤任务 |
| **答题卡** | `preprocessor/src/answer_card/` | OM/OCR/VLM 混合答题卡识别 |
| **离线分析** | `analyzer/run.py` | 分析器离线入口 |
| **在线服务** | `analyzer/app/main.py` | FastAPI 应用入口 |
| **前端** | `analyzer/client-app/` | Vite SPA 前端 |
| **数据模型** | `shared/models.py` | 30+ 张 SQLAlchemy ORM 模型 |
| **数据库** | `shared/database.py` | PostgreSQL 连接管理 |
| **配置** | `shared/llm_step_config.py` | LLM 步骤配置 |
| **配置** | `shared/prompt_step_config.py` | 提示词步骤配置 |
| **迁移** | `alembic/` | 数据库迁移脚本 |
| **部署** | `docker-compose.analyzer.yml` | Docker 部署配置 |
| **文档** | `docs/ARCHITECTURE_SNAPSHOT.md` | 架构快照文档 |