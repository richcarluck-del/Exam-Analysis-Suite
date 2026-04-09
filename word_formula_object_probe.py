from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Optional
import xml.etree.ElementTree as ET

try:
    from PIL import Image
except Exception:
    Image = None

try:
    from analyzer.app.question_bank_rich_content import DocxRichContentExtractor
except Exception as exc:
    DocxRichContentExtractor = None
    _EXTRACTOR_IMPORT_ERROR = exc
else:
    _EXTRACTOR_IMPORT_ERROR = None



DOCX_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
}

MODE_CURRENT_MEDIA = "current"
MODE_FILTERED_RAW = "filtered_html_raw"
MODE_FILTERED_CLEAN = "filtered_html_clean"
MODE_WORD_PICTURE = "word_picture"
MODE_HYBRID = "hybrid"
ALL_MODES = [MODE_CURRENT_MEDIA, MODE_FILTERED_RAW, MODE_FILTERED_CLEAN, MODE_WORD_PICTURE, MODE_HYBRID]


class WordFormulaObjectProbe:
    def __init__(self, docx_path: Path, output_dir: Path) -> None:
        self.docx_path = docx_path.resolve()
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        modes: list[str],
        max_media: int,
        max_items: int,
        tiny_px: int,
        low_bytes: int,
        near_white_threshold: int,
    ) -> dict[str, Any]:
        package_summary = self._inspect_docx_package()
        expected_count = int(package_summary.get("w_object_count") or 0)

        mode_summaries: dict[str, Any] = {}
        filtered_raw_entries: list[dict[str, Any]] = []
        filtered_clean_entries: list[dict[str, Any]] = []
        word_picture_entries: list[dict[str, Any]] = []

        if MODE_CURRENT_MEDIA in modes:
            started = time.perf_counter()
            current_media = self._export_current_pipeline_media(max_media=max_media)
            current_media["elapsed_seconds"] = round(time.perf_counter() - started, 2)
            mode_summaries[MODE_CURRENT_MEDIA] = current_media

        if MODE_FILTERED_RAW in modes or MODE_FILTERED_CLEAN in modes or MODE_HYBRID in modes:
            started = time.perf_counter()
            filtered_raw_entries = self._export_via_extractor(mode=MODE_FILTERED_RAW, max_items=max_items, source="filtered_html")
            mode_summaries[MODE_FILTERED_RAW] = self._build_mode_summary(
                mode=MODE_FILTERED_RAW,
                entries=filtered_raw_entries,
                expected_count=expected_count,
                elapsed_seconds=time.perf_counter() - started,
            )

        if MODE_FILTERED_CLEAN in modes or MODE_HYBRID in modes:
            started = time.perf_counter()
            filtered_clean_entries, clean_stats = self._clean_entries(
                entries=filtered_raw_entries,
                output_dir=self.output_dir / MODE_FILTERED_CLEAN,
                tiny_px=tiny_px,
                low_bytes=low_bytes,
                near_white_threshold=near_white_threshold,
                max_items=max_items,
            )
            mode_summary = self._build_mode_summary(
                mode=MODE_FILTERED_CLEAN,
                entries=filtered_clean_entries,
                expected_count=expected_count,
                elapsed_seconds=time.perf_counter() - started,
            )
            mode_summary["cleaning"] = clean_stats
            mode_summaries[MODE_FILTERED_CLEAN] = mode_summary

        if MODE_WORD_PICTURE in modes or MODE_HYBRID in modes:
            started = time.perf_counter()
            word_picture_entries = self._export_via_extractor(mode=MODE_WORD_PICTURE, max_items=max_items, source="word_picture")
            mode_summaries[MODE_WORD_PICTURE] = self._build_mode_summary(
                mode=MODE_WORD_PICTURE,
                entries=word_picture_entries,
                expected_count=expected_count,
                elapsed_seconds=time.perf_counter() - started,
            )

        if MODE_HYBRID in modes:
            started = time.perf_counter()
            if not filtered_clean_entries:
                filtered_clean_entries, _ = self._clean_entries(
                    entries=filtered_raw_entries,
                    output_dir=self.output_dir / MODE_FILTERED_CLEAN,
                    tiny_px=tiny_px,
                    low_bytes=low_bytes,
                    near_white_threshold=near_white_threshold,
                    max_items=max_items,
                )
            hybrid_entries, hybrid_stats = self._build_hybrid_entries(
                word_entries=word_picture_entries,
                fallback_entries=filtered_clean_entries,
                output_dir=self.output_dir / MODE_HYBRID,
                expected_count=expected_count,
                max_items=max_items,
            )
            hybrid_summary = self._build_mode_summary(
                mode=MODE_HYBRID,
                entries=hybrid_entries,
                expected_count=expected_count,
                elapsed_seconds=time.perf_counter() - started,
            )
            hybrid_summary["hybrid"] = hybrid_stats
            mode_summaries[MODE_HYBRID] = hybrid_summary

        summary = {
            "docx_path": str(self.docx_path),
            "output_dir": str(self.output_dir),
            "package_summary": package_summary,
            "modes": mode_summaries,
            "params": {
                "max_media": max_media,
                "max_items": max_items,
                "tiny_px": tiny_px,
                "low_bytes": low_bytes,
                "near_white_threshold": near_white_threshold,
            },
        }

        summary_path = self.output_dir / "summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"summary saved to: {summary_path}")
        return summary

    def _export_via_extractor(self, mode: str, max_items: int, source: str) -> list[dict[str, Any]]:
        mode_dir = self.output_dir / mode
        if mode_dir.exists():
            shutil.rmtree(mode_dir, ignore_errors=True)
        mode_dir.mkdir(parents=True, exist_ok=True)

        extractor = self._build_extractor(mode_dir)
        if source == "filtered_html":
            images = extractor._export_legacy_object_images_via_word_filtered_html(self.docx_path)
        else:
            images = extractor._export_legacy_object_images_via_word_picture(self.docx_path)

        entries: list[dict[str, Any]] = []
        for item in images:
            if item is None:
                continue
            if len(entries) >= max_items:
                break
            path = Path(item.asset.storage_url)
            file_size = path.stat().st_size if path.exists() else 0
            width, height = self._read_image_size(path)
            file_hash = item.asset.file_hash or self._sha256(path)
            entries.append(
                {
                    "index": len(entries) + 1,
                    "path": str(path),
                    "file_name": path.name,
                    "width": item.width or width,
                    "height": item.height or height,
                    "raw_width": width,
                    "raw_height": height,
                    "bytes": file_size,
                    "hash": file_hash,
                }
            )
        return entries


    def _build_mode_summary(self, mode: str, entries: list[dict[str, Any]], expected_count: int, elapsed_seconds: float) -> dict[str, Any]:
        metrics = self._calc_metrics(entries)
        coverage_ratio = round(len(entries) / expected_count, 4) if expected_count > 0 else None
        return {
            "mode": mode,
            "count": len(entries),
            "expected_object_count": expected_count,
            "coverage_ratio": coverage_ratio,
            "elapsed_seconds": round(elapsed_seconds, 2),
            "metrics": metrics,
            "items": entries,
        }

    def _build_hybrid_entries(
        self,
        word_entries: list[dict[str, Any]],
        fallback_entries: list[dict[str, Any]],
        output_dir: Path,
        expected_count: int,
        max_items: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        target_count = expected_count if expected_count > 0 else max_items
        selected: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()

        def pick(entries: list[dict[str, Any]], source: str) -> int:
            picked = 0
            for item in entries:
                if target_count > 0 and len(selected) >= target_count:
                    break
                if len(selected) >= max_items:
                    break
                item_hash = str(item.get("hash") or "")
                if item_hash and item_hash in seen_hashes:
                    continue
                src_path = Path(str(item.get("path") or ""))
                if not src_path.exists() or not src_path.is_file():
                    continue
                dst_name = f"hybrid_{len(selected) + 1:04d}_{src_path.name}"
                dst_path = output_dir / dst_name
                shutil.copy2(src_path, dst_path)
                copied = dict(item)
                copied["source"] = source
                copied["path"] = str(dst_path)
                copied["file_name"] = dst_path.name
                selected.append(copied)
                if item_hash:
                    seen_hashes.add(item_hash)
                picked += 1
            return picked

        picked_word = pick(word_entries, MODE_WORD_PICTURE)
        picked_filtered = pick(fallback_entries, MODE_FILTERED_CLEAN)

        for idx, item in enumerate(selected, start=1):
            item["index"] = idx

        stats = {
            "picked_from_word_picture": picked_word,
            "picked_from_filtered_html_clean": picked_filtered,
            "target_count": target_count,
            "max_items": max_items,
        }
        return selected, stats

    def _clean_entries(
        self,
        entries: list[dict[str, Any]],
        output_dir: Path,
        tiny_px: int,
        low_bytes: int,
        near_white_threshold: int,
        max_items: int,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        cleaned: list[dict[str, Any]] = []
        seen_hashes: set[str] = set()
        dropped = Counter()

        for item in entries:
            if len(cleaned) >= max_items:
                break
            src_path = Path(str(item.get("path") or ""))
            if not src_path.exists() or not src_path.is_file():
                dropped["missing"] += 1
                continue

            width = int(item.get("raw_width") or item.get("width") or 0)
            height = int(item.get("raw_height") or item.get("height") or 0)
            file_size = int(item.get("bytes") or 0)
            file_hash = str(item.get("hash") or "")

            if width > 0 and height > 0 and (width <= tiny_px or height <= tiny_px):
                dropped["tiny"] += 1
                continue
            if file_size > 0 and file_size <= low_bytes:
                dropped["low_bytes"] += 1
                continue
            if self._is_near_white(src_path, threshold=near_white_threshold):
                dropped["near_white"] += 1
                continue
            if file_hash and file_hash in seen_hashes:
                dropped["duplicate_hash"] += 1
                continue

            dst_name = f"clean_{len(cleaned) + 1:04d}_{src_path.name}"
            dst_path = output_dir / dst_name
            shutil.copy2(src_path, dst_path)
            copied = dict(item)
            copied["index"] = len(cleaned) + 1
            copied["path"] = str(dst_path)
            copied["file_name"] = dst_path.name
            cleaned.append(copied)
            if file_hash:
                seen_hashes.add(file_hash)

        stats = {
            "input_count": len(entries),
            "output_count": len(cleaned),
            "dropped": dict(dropped),
            "tiny_px": tiny_px,
            "low_bytes": low_bytes,
            "near_white_threshold": near_white_threshold,
        }
        return cleaned, stats

    def _calc_metrics(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        hash_counter = Counter(str(item.get("hash") or "") for item in entries if item.get("hash"))
        tiny_count = 0
        near_white_count = 0
        for item in entries:
            width = int(item.get("raw_width") or item.get("width") or 0)
            height = int(item.get("raw_height") or item.get("height") or 0)
            if width > 0 and height > 0 and (width <= 12 or height <= 12):
                tiny_count += 1
            path = Path(str(item.get("path") or ""))
            if path.exists() and self._is_near_white(path, threshold=250):
                near_white_count += 1
        return {
            "duplicate_hash_count": sum(1 for _, count in hash_counter.items() if count > 1),
            "tiny_image_count": tiny_count,
            "near_white_count": near_white_count,
        }

    def _is_near_white(self, image_path: Path, threshold: int) -> bool:
        if Image is None:
            return False
        try:
            with Image.open(image_path) as image:
                gray = image.convert("L")
                extrema = gray.getextrema()
            if not extrema:
                return False
            min_val, max_val = extrema
            return max_val >= threshold and min_val >= max(0, threshold - 10)
        except Exception:
            return False

    def _read_image_size(self, path: Path) -> tuple[Optional[int], Optional[int]]:
        if Image is None:
            return None, None
        try:
            with Image.open(path) as image:
                return image.width, image.height
        except Exception:
            return None, None

    def _sha256(self, path: Path) -> Optional[str]:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            return None

    def _build_extractor(self, output_dir: Path):
        if DocxRichContentExtractor is None:
            detail = f" ({_EXTRACTOR_IMPORT_ERROR})" if _EXTRACTOR_IMPORT_ERROR else ""
            raise RuntimeError(f"缺少依赖，无法导入 DocxRichContentExtractor{detail}")
        return DocxRichContentExtractor(output_dir)

    def _inspect_docx_package(self) -> dict[str, Any]:
        with zipfile.ZipFile(self.docx_path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
            media_entries = [name for name in archive.namelist() if name.startswith("word/media/")]
            ole_entries = [name for name in archive.namelist() if name.startswith("word/embeddings/")]
            object_samples = []
            for index, obj in enumerate(root.findall(".//w:object", DOCX_NS), start=1):
                ole = obj.find(".//o:OLEObject", DOCX_NS)
                imagedata = obj.find(".//v:imagedata", DOCX_NS)
                object_samples.append(
                    {
                        "index": index,
                        "prog_id": (ole.get(f"{{{DOCX_NS['o']}}}ProgID") if ole is not None else None),
                        "shape_id": (ole.get(f"{{{DOCX_NS['o']}}}ShapeID") if ole is not None else None),
                        "image_rel_id": (imagedata.get(f"{{{DOCX_NS['r']}}}id") if imagedata is not None else None),
                    }
                )
                if len(object_samples) >= 12:
                    break
            return {
                "w_object_count": len(root.findall(".//w:object", DOCX_NS)),
                "w_pict_count": len(root.findall(".//w:pict", DOCX_NS)),
                "v_shape_count": len(root.findall(".//v:shape", DOCX_NS)),
                "v_imagedata_count": len(root.findall(".//v:imagedata", DOCX_NS)),
                "ole_object_count": len(root.findall(".//o:OLEObject", DOCX_NS)),
                "omath_count": len(root.findall(".//m:oMath", DOCX_NS)),
                "omath_para_count": len(root.findall(".//m:oMathPara", DOCX_NS)),
                "docx_media_count": len(media_entries),
                "docx_media_suffix_counts": dict(Counter(Path(name).suffix.lower() or "<no_suffix>" for name in media_entries)),
                "docx_ole_embedding_count": len(ole_entries),
                "object_samples": object_samples,
            }

    def _export_current_pipeline_media(self, max_media: int) -> dict[str, Any]:
        output_dir = self.output_dir / MODE_CURRENT_MEDIA
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        extractor = self._build_extractor(output_dir)
        exported = []
        with zipfile.ZipFile(self.docx_path) as archive:
            media_entries = [
                name
                for name in sorted(archive.namelist())
                if name.startswith("word/media/") and Path(name).suffix.lower() in {".wmf", ".emf", ".png", ".jpg", ".jpeg", ".gif", ".bmp"}
            ]
            for index, name in enumerate(media_entries[:max_media], start=1):
                blob = archive.read(name)
                source_suffix = Path(name).suffix or ".bin"
                normalized_blob, normalized_suffix = extractor._normalize_image_blob(blob, source_suffix)
                output_name = f"current_{index:04d}{normalized_suffix}"
                output_path = output_dir / output_name
                output_path.write_bytes(normalized_blob)
                exported.append(
                    {
                        "index": index,
                        "source_name": name,
                        "source_suffix": source_suffix,
                        "normalized_suffix": normalized_suffix,
                        "output_path": str(output_path),
                    }
                )
        return {"count": len(exported), "items": exported}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="测试旧式 Word 公式对象的转图策略，并输出多策略对比")
    parser.add_argument("docx_path", type=Path, help="待测试的 Word 文档")
    parser.add_argument("--output-dir", type=Path, default=Path("word_formula_object_probe_output"), help="输出目录")
    parser.add_argument("--modes", type=str, default=",".join(ALL_MODES), help=f"逗号分隔: {','.join(ALL_MODES)}")
    parser.add_argument("--max-media", type=int, default=80, help="current 模式最多导出多少张 media")
    parser.add_argument("--max-items", type=int, default=2000, help="每个策略最多保留多少张")
    parser.add_argument("--tiny-px", type=int, default=10, help="过滤阈值: 宽或高<=该值视为 tiny")
    parser.add_argument("--low-bytes", type=int, default=120, help="过滤阈值: 文件字节<=该值视为 low_bytes")
    parser.add_argument("--near-white-threshold", type=int, default=250, help="过滤阈值: 接近纯白判定阈值")
    return parser.parse_args()


def parse_modes(raw: str) -> list[str]:
    requested = [item.strip() for item in raw.split(",") if item.strip()]
    invalid = [item for item in requested if item not in ALL_MODES]
    if invalid:
        raise ValueError(f"未知模式: {invalid}，可选模式: {ALL_MODES}")
    return requested or ALL_MODES


def main() -> None:
    args = parse_args()
    modes = parse_modes(args.modes)
    probe = WordFormulaObjectProbe(args.docx_path, args.output_dir)
    probe.run(
        modes=modes,
        max_media=args.max_media,
        max_items=args.max_items,
        tiny_px=args.tiny_px,
        low_bytes=args.low_bytes,
        near_white_threshold=args.near_white_threshold,
    )


if __name__ == "__main__":
    main()
