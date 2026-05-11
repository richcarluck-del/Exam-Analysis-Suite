import os
from pathlib import Path

from dotenv import load_dotenv

# 先于 shared.database 加载，且必须用仓库根路径（见 shared/database.py 说明）；避免 CWD 在子目录时漏读 .env。
_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env")

from shared.database import DATABASE_URL, PROJECT_ROOT

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "20e911774b17a56433236cc34fbae0e4ba3f37017546ccbf03ea38b47047e557",
)
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

FERNET_KEY = os.getenv(
    "FERNET_KEY",
    "pyqZhb-1rraJIC1oIjGpOb3_NltU7fDt_HOzbTN_o4Y=",
).encode("utf-8")

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")

NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "exam123456")
NEO4J_DB = os.getenv("NEO4J_DB", "neo4j")

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6380/0")
KNOWLEDGE_BASE_DIR = os.getenv(
    "KNOWLEDGE_BASE_DIR",
    str(PROJECT_ROOT / "analyzer" / "knowledge_base"),
)
KNOWLEDGE_POINTS_DIR = os.getenv(
    "KNOWLEDGE_POINTS_DIR",
    str(PROJECT_ROOT / "analyzer" / "knowledge_points"),
)
# Runtime process artifacts (_derivative_runs, _ingest_runs) — separate from the
# knowledge_points resource directory which is for staged-to-ingest document files.
KNOWLEDGE_RUNS_DIR = os.getenv(
    "KNOWLEDGE_RUNS_DIR",
    str(PROJECT_ROOT / "analyzer" / "_runs"),
)
NORMALIZED_DOCUMENTS_DIR = os.getenv(
    "NORMALIZED_DOCUMENTS_DIR",
    str(PROJECT_ROOT / "analyzer" / "normalized_documents"),
)
QUESTION_BANK_UPLOAD_DIR = os.getenv(
    "QUESTION_BANK_UPLOAD_DIR",
    str(PROJECT_ROOT / "analyzer" / "uploads" / "question_bank"),
)
QUESTION_BANK_ASSET_DIR = os.getenv(
    "QUESTION_BANK_ASSET_DIR",
    str(PROJECT_ROOT / "analyzer" / "uploads" / "question_bank_assets"),
)
QUESTION_BANK_DOCX_SANITIZE_ENABLED = os.getenv(
    "QUESTION_BANK_DOCX_SANITIZE_ENABLED",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}

QUESTION_BANK_DOCX_SANITIZE_MODE = os.getenv(
    "QUESTION_BANK_DOCX_SANITIZE_MODE",
    "conservative",
).strip().lower()
QUESTION_BANK_DOCX_SANITIZE_BACKEND = os.getenv(
    "QUESTION_BANK_DOCX_SANITIZE_BACKEND",
    "auto",
).strip().lower()

# 为 True 时：DOCX 内 Word 原生公式（OMML）通过本机 Word COM 栅格为 PNG，render 树用 image 节点展示，不把公式当 Unicode 文本抽取（需安装 Word，Windows 常见）
QUESTION_BANK_DOCX_OMML_AS_IMAGES = os.getenv(
    "QUESTION_BANK_DOCX_OMML_AS_IMAGES",
    "true",
).strip().lower() in {"1", "true", "yes", "on"}

# PDF 文本层乱码时可选 Pix2Text 整页 OCR：off | auto | force（需 pip install -r analyzer/requirements-ocr.txt）
QUESTION_BANK_PDF_OCR_MODE = os.getenv("QUESTION_BANK_PDF_OCR_MODE", "auto").strip().lower()
QUESTION_BANK_PDF_OCR_THRESHOLD = float(os.getenv("QUESTION_BANK_PDF_OCR_THRESHOLD", "0.18"))
QUESTION_BANK_PDF_OCR_RENDER_SCALE = float(os.getenv("QUESTION_BANK_PDF_OCR_RENDER_SCALE", "2.0"))
# 为 True 时 Pix2Text 尝试开启公式识别（输出 $...$ / LaTeX），失败则自动回退为纯文本 OCR（.venv_ocr 内需模型齐全）
QUESTION_BANK_PDF_OCR_ENABLE_FORMULA = os.getenv("QUESTION_BANK_PDF_OCR_ENABLE_FORMULA", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# 为 True 时在 OCR 文本末尾附加「整页渲染 PNG」的 Markdown 图链（静态挂载见 preprocessor main.py /static/question-bank/assets）
QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER = os.getenv("QUESTION_BANK_PDF_OCR_APPEND_PAGE_RASTER", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# 为 True 时：结构化 PDF 提取阶段对含关键数学符号的 span 按 bbox 裁切为 PNG，写入题库资产目录并以 image 节点展示（不依赖端上数学字体）
QUESTION_BANK_PDF_MATH_CLIP_IMAGES = os.getenv("QUESTION_BANK_PDF_MATH_CLIP_IMAGES", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
QUESTION_BANK_PDF_MATH_CLIP_DPI = int(os.getenv("QUESTION_BANK_PDF_MATH_CLIP_DPI", "144"))

KNOWLEDGE_POINT_ENABLED = os.getenv("KNOWLEDGE_POINT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
KNOWLEDGE_POINT_DEV_UI_ENABLED = os.getenv("KNOWLEDGE_POINT_DEV_UI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
KNOWLEDGE_RAG_ENABLED = os.getenv("KNOWLEDGE_RAG_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
KNOWLEDGE_TOPIC_INLINE_RETRIEVAL_SYNC = os.getenv(
    "KNOWLEDGE_TOPIC_INLINE_RETRIEVAL_SYNC",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}

# 题↔知识点桥接索引策略：
#   strong_medium（默认）：仅把 topic_strong/topic_adjacent 或 approved 的链接写入检索索引；
#   approved_only：仅 approved_status=="approved" 的链接写入；
#   all：全部写入（含 topic_fallback，等同旧行为）。
KNOWLEDGE_POINT_BRIDGE_INDEX_MODE = os.getenv(
    "KNOWLEDGE_POINT_BRIDGE_INDEX_MODE",
    "strong_medium",
).strip().lower() or "strong_medium"

# 专题题↔知识点桥接排序（摄入时读环境变量，见 knowledge_point_parser._sync_docx_topic_question_knowledge_links）：
#   overlap（默认）：题干 vs 知识点名字符覆盖 + Top-K；
#   vector：本包 hybrid 检索打分，空则回退 overlap；
#   vector_then_overlap：先 vector，无结果再 overlap；
#   llm：按题 LLM 从候选 ID 中选，失败/无题干则 overlap；
#   llm_then_overlap：先 LLM，无结果再 overlap；
#   hybrid：overlap 与 vector 分数各 50% 融合，空则 overlap。
# 另：KNOWLEDGE_POINT_BRIDGE_TOPK、KNOWLEDGE_POINT_BRIDGE_MIN_SCORE。
# 按题 LLM 桥接（llm / llm_then_overlap）：模型可返回 0～N 条并自带关联度（见 KNOWLEDGE_POINT_BRIDGE_LLM_*）。
# KNOWLEDGE_POINT_BRIDGE_LLM_MAX_LINKS=5
# KNOWLEDGE_POINT_BRIDGE_LLM_MIN_RELEVANCE=0.38（低于此分的条目不入库）
# KNOWLEDGE_POINT_BRIDGE_LLM_STRONG_RELEVANCE=0.78（≥ 此 relevance 落 topic_strong，否则 topic_adjacent）
# 知识点 WebSocket/脚本摄入写入 _ingest_runs/<run_id>/ 下单个详细文件（如 llm/*.txt）的最大字节数，默认 3MB。
# KNOWLEDGE_INGEST_VERBOSE_MAX_FILE_BYTES=3145728
#
# 专题「块级知识点」LLM（analyzer.topic_docx_block_points）：为 true 且当前步骤模型为视觉模型时，
# 在 OpenAI 兼容请求中于提示词后附加本批各块的表格/段落阅读顺序 + 内嵌图（data URL），便于云百炼等多模态接口。
KNOWLEDGE_TOPIC_BLOCK_POINTS_MULTIMODAL = os.getenv(
    "KNOWLEDGE_TOPIC_BLOCK_POINTS_MULTIMODAL",
    "false",
).strip().lower() in {"1", "true", "yes", "on"}
KNOWLEDGE_BLOCK_LLM_MAX_IMAGES_PER_CALL = int(os.getenv("KNOWLEDGE_BLOCK_LLM_MAX_IMAGES_PER_CALL", "24"))
KNOWLEDGE_BLOCK_LLM_MAX_IMAGE_BYTES = int(os.getenv("KNOWLEDGE_BLOCK_LLM_MAX_IMAGE_BYTES", str(4 * 1024 * 1024)))

KNOWLEDGE_GRAPH_ENABLED = os.getenv("KNOWLEDGE_GRAPH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
KNOWLEDGE_DERIVATIVE_ENABLED = os.getenv("KNOWLEDGE_DERIVATIVE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
# 摄入时自动调用 LLM 抽取 KP-KP 语义关系并写入 knowledge_point_relations
KNOWLEDGE_POINT_RELATIONS_LLM_ENABLED = os.getenv("KNOWLEDGE_POINT_RELATIONS_LLM_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

KNOWLEDGE_PACKAGE_KEYWORDS = tuple(
    token.strip()
    for token in os.getenv("KNOWLEDGE_PACKAGE_KEYWORDS", "专题,单元,模块").split(",")
    if token and token.strip()
)


_embedding_model = os.getenv("EMBEDDING_MODEL_NAME") or os.getenv("CHROMA_EMBEDDING_MODEL")
if not _embedding_model:
    raise RuntimeError("EMBEDDING_MODEL_NAME 未设置，请在 .env 中配置（例如 EMBEDDING_MODEL_NAME=BAAI/bge-large-zh-v1.5）")
EMBEDDING_MODEL_NAME: str = _embedding_model


VECTOR_SEARCH_BACKEND = os.getenv("VECTOR_SEARCH_BACKEND", "qdrant").strip().lower()
TEXT_SEARCH_BACKEND = os.getenv("TEXT_SEARCH_BACKEND", "opensearch").strip().lower()

CHROMA_DB_PATH = os.getenv(
    "CHROMA_DB_PATH",
    str((Path(__file__).resolve().parent.parent / "chroma_db").resolve()),
)
CHROMA_COLLECTION_NAME = os.getenv("CHROMA_COLLECTION_NAME", "knowledge_base")

QDRANT_URL = os.getenv("QDRANT_URL", "http://127.0.0.1:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "question_bank")
QDRANT_PREFER_GRPC = os.getenv("QDRANT_PREFER_GRPC", "false").strip().lower() in {"1", "true", "yes", "on"}

OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://127.0.0.1:9200")
OPENSEARCH_USERNAME = os.getenv("OPENSEARCH_USERNAME")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD")
OPENSEARCH_INDEX_NAME = os.getenv("OPENSEARCH_INDEX_NAME", "question_bank")
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").strip().lower() in {"1", "true", "yes", "on"}
