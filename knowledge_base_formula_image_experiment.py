from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

rich_content_logger = logging.getLogger("analyzer.app.question_bank_rich_content")



PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = PROJECT_ROOT / "analyzer" / "knowledge_base"
DEFAULT_OUTPUT_BASE_DIR = PROJECT_ROOT / "analyzer" / "uploads" / "question_bank_formula_object_experiments"
SUPPORTED_INPUT_EXTENSIONS = {".doc", ".docx", ".pdf", ".txt"}
DOCX_PROCESSABLE_EXTENSIONS = {".doc", ".docx"}
SOFFICE_CANDIDATES = [
    "soffice",
    "soffice.exe",
    "soffice.com",
    r"D:\Program Files\LibreOffice\program\soffice.exe",
    r"D:\Program Files\LibreOffice\program\soffice.com",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files\LibreOffice\program\soffice.com",
]

script_logger = logging.getLogger("knowledge_base_formula_image_experiment")


@dataclass
class ExportedObjectImage:
    object_index: int
    source_asset_path: str
    exported_copy_path: str
    width: Optional[int]
    height: Optional[int]
    file_name: str


@dataclass
class DocumentExperimentSummary:
    document_index: int
    source_path: str
    source_extension: str
    status: str
    reason: Optional[str] = None
    normalized_docx_path: Optional[str] = None
    document_output_dir: Optional[str] = None
    asset_output_dir: Optional[str] = None
    log_path: Optional[str] = None
    block_count: int = 0
    omml_formula_count: int = 0
    legacy_object_encountered_count: int = 0
    exported_formula_object_image_count: int = 0
    exported_formula_object_images: list[dict[str, Any]] | None = None


def build_extractor(output_dir: Path):
    try:
        from analyzer.app.question_bank_rich_content import DocxRichContentExtractor
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少运行依赖，请先安装 analyzer/requirements.txt 中的依赖，例如 python-docx、Pillow、pywin32。"
        ) from exc

    class ExperimentDocxExtractor(DocxRichContentExtractor):
        def __init__(self, target_output_dir: Path):
            super().__init__(target_output_dir)
            self.legacy_object_nodes: list[dict[str, Any]] = []
            self.legacy_object_encountered_count = 0

        def _extract_legacy_object_nodes(self, part, element) -> list[dict[str, Any]]:
            self.legacy_object_encountered_count += 1
            nodes = super()._extract_legacy_object_nodes(part, element)
            for node in nodes:
                if node.get("type") == "image":
                    self.legacy_object_nodes.append(
                        {
                            "storage_url": str(node.get("storage_url") or ""),
                            "file_hash": node.get("file_hash"),
                            "width": node.get("width"),
                            "height": node.get("height"),
                        }
                    )
            return nodes

    return ExperimentDocxExtractor(output_dir)





def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量导出 knowledge_base 文档中 Word 公式/对象图片，便于肉眼对比效果")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR, help="输入文档目录，默认 analyzer/knowledge_base")
    parser.add_argument("--output-root", type=Path, default=None, help="输出根目录，默认自动创建到 analyzer/uploads/question_bank_formula_object_experiments/<时间戳>")
    parser.add_argument("--limit", type=int, default=0, help="最多处理多少个文档，0 表示不限制")
    parser.add_argument("--pattern", type=str, default="*", help="按文件名过滤，例如 *.docx")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir = args.input_dir.resolve()
    output_root = (args.output_root or build_default_output_root()).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    configure_console_logging()
    run_log_path = output_root / "run.log"
    run_file_handler = build_file_handler(run_log_path)
    script_logger.addHandler(run_file_handler)
    rich_content_logger.addHandler(run_file_handler)
    rich_content_logger.setLevel(logging.INFO)

    try:
        script_logger.info("Experiment run start: input_dir=%s output_root=%s pattern=%s limit=%s", input_dir, output_root, args.pattern, args.limit)
        documents = collect_documents(input_dir=input_dir, pattern=args.pattern, limit=args.limit)
        if not documents:
            raise FileNotFoundError(f"未在目录中找到可处理文档: {input_dir}")

        summaries: list[DocumentExperimentSummary] = []
        for index, source_path in enumerate(documents, start=1):
            summaries.append(process_document(index=index, source_path=source_path, output_root=output_root))

        run_summary = {
            "input_dir": str(input_dir),
            "output_root": str(output_root),
            "document_count": len(summaries),
            "processed_success_count": sum(1 for item in summaries if item.status == "success"),
            "processed_skipped_count": sum(1 for item in summaries if item.status == "skipped"),
            "processed_failed_count": sum(1 for item in summaries if item.status == "failed"),
            "legacy_object_total": sum(item.legacy_object_encountered_count for item in summaries),
            "exported_formula_object_image_total": sum(item.exported_formula_object_image_count for item in summaries),
            "documents": [asdict(item) for item in summaries],
        }
        summary_path = output_root / "run_summary.json"
        summary_path.write_text(json.dumps(run_summary, ensure_ascii=False, indent=2), encoding="utf-8")

        print(json.dumps({k: v for k, v in run_summary.items() if k != "documents"}, ensure_ascii=False, indent=2))
        print(f"run_summary: {summary_path}")
        print(f"run_log: {run_log_path}")
        print(f"output_root: {output_root}")
    finally:
        script_logger.removeHandler(run_file_handler)
        rich_content_logger.removeHandler(run_file_handler)
        run_file_handler.close()


def build_default_output_root() -> Path:
    return DEFAULT_OUTPUT_BASE_DIR / datetime.now().strftime("run_%Y%m%d_%H%M%S")


def configure_console_logging() -> None:
    if script_logger.handlers:
        return
    script_logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"))
    script_logger.addHandler(console_handler)


def build_file_handler(log_path: Path) -> logging.FileHandler:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(name)s - %(message)s"))
    return file_handler


def collect_documents(input_dir: Path, pattern: str, limit: int) -> list[Path]:
    if not input_dir.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"输入路径不是目录: {input_dir}")

    files = [
        path for path in sorted(input_dir.iterdir())
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS and path.match(pattern)
    ]
    if limit > 0:
        files = files[:limit]
    return files


def process_document(index: int, source_path: Path, output_root: Path) -> DocumentExperimentSummary:
    document_dir = output_root / f"document_{index:03d}_{safe_stem(source_path.stem)}"
    document_dir.mkdir(parents=True, exist_ok=True)
    asset_dir = document_dir / "assets"
    asset_dir.mkdir(parents=True, exist_ok=True)
    log_path = document_dir / "extract.log"

    summary = DocumentExperimentSummary(
        document_index=index,
        source_path=str(source_path),
        source_extension=source_path.suffix.lower(),
        status="failed",
        document_output_dir=str(document_dir),
        asset_output_dir=str(asset_dir),
        log_path=str(log_path),
        exported_formula_object_images=[],
    )

    doc_file_handler = build_file_handler(log_path)
    script_logger.addHandler(doc_file_handler)
    rich_content_logger.addHandler(doc_file_handler)
    try:
        script_logger.info("Document experiment start: index=%s source_path=%s", index, source_path)
        if source_path.suffix.lower() not in DOCX_PROCESSABLE_EXTENSIONS:
            summary.status = "skipped"
            summary.reason = f"该实验只处理 .doc/.docx；当前文件类型为 {source_path.suffix.lower()}"
            script_logger.info("Document skipped: index=%s source_path=%s reason=%s", index, source_path, summary.reason)
            write_document_summary(document_dir, summary)
            return summary

        normalized_docx_path = normalize_to_docx_if_needed(source_path=source_path, document_dir=document_dir)
        summary.normalized_docx_path = str(normalized_docx_path)

        extractor = build_extractor(asset_dir)

        blocks = extractor.extract(normalized_docx_path)
        summary.block_count = len(blocks)
        summary.omml_formula_count = count_formula_nodes(blocks)
        summary.legacy_object_encountered_count = extractor.legacy_object_encountered_count

        exported_images = copy_formula_object_images(
            legacy_object_nodes=extractor.legacy_object_nodes,
            target_dir=document_dir / "formula_object_images",
        )
        summary.exported_formula_object_images = [asdict(item) for item in exported_images]
        summary.exported_formula_object_image_count = len(exported_images)
        summary.status = "success"
        summary.reason = None

        script_logger.info(
            "Document experiment done: index=%s source_path=%s blocks=%s omml_formula_count=%s legacy_object_count=%s exported_images=%s",
            index,
            source_path,
            summary.block_count,
            summary.omml_formula_count,
            summary.legacy_object_encountered_count,
            summary.exported_formula_object_image_count,
        )
        write_document_summary(document_dir, summary)
        return summary
    except Exception as exc:
        summary.status = "failed"
        summary.reason = f"{exc.__class__.__name__}: {exc}"
        script_logger.exception("Document experiment failed: index=%s source_path=%s", index, source_path)
        write_document_summary(document_dir, summary)
        return summary
    finally:
        script_logger.removeHandler(doc_file_handler)
        rich_content_logger.removeHandler(doc_file_handler)
        doc_file_handler.close()


def normalize_to_docx_if_needed(source_path: Path, document_dir: Path) -> Path:
    suffix = source_path.suffix.lower()
    if suffix == ".docx":
        return source_path
    if suffix != ".doc":
        raise ValueError(f"暂不支持的归一化输入类型: {suffix}")

    normalized_dir = document_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    soffice_binary = resolve_soffice_binary()
    if not soffice_binary:
        raise RuntimeError("未找到 LibreOffice 可执行文件 soffice，无法将 .doc 转成 .docx")

    command = [
        soffice_binary,
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(normalized_dir),
        str(source_path),
    ]
    script_logger.info("LibreOffice normalize start: source_path=%s output_dir=%s command=%s", source_path, normalized_dir, command)
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    script_logger.info(
        "LibreOffice normalize finished: source_path=%s returncode=%s stdout_tail=%s stderr_tail=%s",
        source_path,
        completed.returncode,
        (completed.stdout or "")[-500:],
        (completed.stderr or "")[-500:],
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout or "LibreOffice 转换失败")

    converted_path = normalized_dir / f"{source_path.stem}.docx"
    if not converted_path.exists():
        raise FileNotFoundError(f"LibreOffice 转换结果不存在: {converted_path}")
    return converted_path


def resolve_soffice_binary() -> Optional[str]:
    for candidate in SOFFICE_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        candidate_path = Path(candidate)
        if candidate_path.exists():
            return str(candidate_path)
    return None


def copy_formula_object_images(legacy_object_nodes: list[dict[str, Any]], target_dir: Path) -> list[ExportedObjectImage]:
    target_dir.mkdir(parents=True, exist_ok=True)
    exported: list[ExportedObjectImage] = []
    for index, node in enumerate(legacy_object_nodes, start=1):
        source_asset_path = Path(str(node.get("storage_url") or "")).resolve()
        if not source_asset_path.exists() or not source_asset_path.is_file():
            script_logger.warning("Formula object image missing: object_index=%s source_asset_path=%s", index, source_asset_path)
            continue
        target_path = target_dir / f"object_{index:04d}__{source_asset_path.name}"
        shutil.copy2(source_asset_path, target_path)
        exported.append(
            ExportedObjectImage(
                object_index=index,
                source_asset_path=str(source_asset_path),
                exported_copy_path=str(target_path),
                width=safe_int(node.get("width")),
                height=safe_int(node.get("height")),
                file_name=target_path.name,
            )
        )
    return exported


def count_formula_nodes(blocks: list[Any]) -> int:
    count = 0

    def walk(value: Any) -> None:
        nonlocal count
        if isinstance(value, dict):
            if value.get("type") == "formula":
                count += 1
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif hasattr(value, "render"):
            walk(getattr(value, "render"))

    walk(blocks)
    return count


def write_document_summary(document_dir: Path, summary: DocumentExperimentSummary) -> None:
    summary_path = document_dir / "document_summary.json"
    summary_path.write_text(json.dumps(asdict(summary), ensure_ascii=False, indent=2), encoding="utf-8")


def safe_stem(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff._-]+", "_", value).strip("._-")
    return normalized[:80] or "document"


def safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
