# 环境与运行手册（Windows / PowerShell）

> 适用目录：`d:/10739/Exam-Analysis-Suite`
> 目标：让新 agent 在不切换工程目录的前提下，快速完成本地可运行验证。

## 1. 先决条件

- Python：**3.10**（建议固定）
- Node.js：用于 `analyzer/client-app`
- PostgreSQL：必须可连接
- Redis：用于 Celery
- Neo4j：用于图检索链路（如相关功能启用）

---

## 2. Python 环境

在仓库根目录执行：

```powershell
cd d:/10739/Exam-Analysis-Suite
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 3. 环境变量（最小可用）

根目录 `.env` 关键项：

```env
APP_ENV=development
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/exam_analysis

VECTOR_SEARCH_BACKEND=qdrant
TEXT_SEARCH_BACKEND=opensearch
QDRANT_URL=http://127.0.0.1:6333
OPENSEARCH_URL=http://127.0.0.1:9200
```

说明：
- `DATABASE_URL` 必须是 PostgreSQL；SQLite 已不支持。
- 检索后端以当前环境变量为准。

---

## 4. 数据库迁移

```powershell
cd d:/10739/Exam-Analysis-Suite
.\.venv\Scripts\Activate.ps1
alembic upgrade head
```

如失败，先确认：
- `.env` 已加载且 `DATABASE_URL` 正确
- PostgreSQL 可连接

---

## 5. 推荐运行方式

## 5.1 端到端（最少误操作）

```powershell
cd d:/10739/Exam-Analysis-Suite
.\.venv\Scripts\Activate.ps1
python run_pipeline.py --input-dir "preprocessor/my_test_images"
```

## 5.2 单独运行 preprocessor

```powershell
cd d:/10739/Exam-Analysis-Suite/preprocessor
..\.venv\Scripts\Activate.ps1
python main.py --input-dir "my_test_images" --output-dir "temp/run_manual"
```

## 5.3 单独运行 analyzer（离线 bundle 模式）

```powershell
cd d:/10739/Exam-Analysis-Suite
.\.venv\Scripts\Activate.ps1
python analyzer/run.py --bundle-dir "<preprocessor输出目录>" --output-dir "temp/analyzer_output"
```

---

## 6. 在线服务模式（FastAPI + Celery + 前端）

在不同 PowerShell 窗口分别启动：

- Redis：`d:/10739/Exam-Analysis-Suite/analyzer/start_redis.ps1`
- Celery：`d:/10739/Exam-Analysis-Suite/analyzer/start_celery.ps1`
- FastAPI：`d:/10739/Exam-Analysis-Suite/analyzer/start_fastapi.ps1`
- 前端：`d:/10739/Exam-Analysis-Suite/analyzer/start_vite.ps1`

也可在根目录使用：
- `start_analyzer_backend.bat`
- `start_analyzer_frontend.bat`
- `start_analyzer_all.bat`

---

## 7. 快速健康检查

- DB：执行 `alembic current` 能返回当前 revision
- API：浏览器打开 `http://localhost:8000/docs`
- 前端：浏览器打开 `http://localhost:5173/paper-preview`
- 端到端：`run_pipeline.py` 产出 `analysis_report.json`

---

## 8. 常见问题与处理

- **报 PostgreSQL 连接错误**：检查 `.env` 的 `DATABASE_URL`，以及数据库服务是否可达。
- **Celery 启动失败**：先确认 Redis 已启动，再检查 Python 环境与依赖。
- **Neo4j 连接异常**：重启 Neo4j 服务后重试。
- **文档与代码不一致**：以 `shared/database.py`、`alembic/env.py`、入口脚本为准。
