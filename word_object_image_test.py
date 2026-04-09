from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Optional


try:
    import pythoncom
except Exception:
    pythoncom = None

try:
    from PIL import Image, ImageGrab
except Exception:
    Image = None
    ImageGrab = None

try:
    from win32com.client import gencache
except Exception:
    gencache = None


@dataclass
class ExportResult:
    label: str
    source_kind: str
    ordinal: int
    text_preview: str
    emf_path: Optional[str]
    png_path: Optional[str]
    width: Optional[int]
    height: Optional[int]
    method: str
    elapsed_seconds: float
    meta: dict[str, Any]
    error: Optional[str] = None


class WordObjectImageExporter:
    def __init__(self, docx_path: Path, output_dir: Path, dpi: int = 600) -> None:
        self.docx_path = docx_path
        self.output_dir = output_dir
        self.dpi = dpi
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run(self, max_omaths: int, max_inline_ole: int, include_floating_shapes: bool, max_metafiles: int) -> dict[str, Any]:
        if pythoncom is None or gencache is None:
            raise RuntimeError("缺少 pywin32（pythoncom/win32com），无法调用 Word COM")
        if Image is None or ImageGrab is None:
            raise RuntimeError("缺少 Pillow，无法处理剪贴板图片")

        started_at = time.perf_counter()
        pythoncom.CoInitialize()
        app = None
        document = None
        results: list[ExportResult] = []
        try:
            app = gencache.EnsureDispatch("Word.Application")
            app.Visible = False
            app.DisplayAlerts = 0
            app.ScreenUpdating = False
            document = app.Documents.Open(str(self.docx_path), ReadOnly=True, AddToRecentFiles=False)
            time.sleep(1.5)

            omath_count = int(self._word_call(lambda: document.OMaths.Count, default=0))
            inline_shape_count = int(self._word_call(lambda: document.InlineShapes.Count, default=0))
            shape_count = int(self._word_call(lambda: document.Shapes.Count, default=0))


            for index in range(1, min(omath_count, max_omaths) + 1):
                omath = document.OMaths(index)
                results.append(
                    self._export_range(
                        range_obj=omath.Range,
                        label=f"omath_{index:04d}",
                        source_kind="omath",
                        ordinal=index,
                        meta={"omath_index": index},
                    )
                )

            exported_inline_ole = 0
            for index in range(1, inline_shape_count + 1):
                inline_shape = document.InlineShapes(index)
                ole_info = self._extract_ole_info(inline_shape)
                if not ole_info["is_ole"]:
                    continue
                exported_inline_ole += 1
                results.append(
                    self._export_range(
                        range_obj=inline_shape.Range,
                        label=f"inline_ole_{exported_inline_ole:04d}",
                        source_kind="inline_ole",
                        ordinal=index,
                        meta={
                            "inline_shape_index": index,
                            "inline_shape_type": self._safe_value(lambda: int(inline_shape.Type)),
                            **ole_info,
                        },
                    )
                )
                if exported_inline_ole >= max_inline_ole:
                    break

            exported_shapes = 0
            if include_floating_shapes:
                for index in range(1, shape_count + 1):
                    shape = document.Shapes(index)
                    ole_info = self._extract_ole_info(shape)
                    if not ole_info["is_ole"]:
                        continue
                    anchor = self._safe_value(lambda: shape.Anchor)
                    if anchor is None:
                        continue
                    exported_shapes += 1
                    results.append(
                        self._export_range(
                            range_obj=anchor,
                            label=f"floating_ole_{exported_shapes:04d}",
                            source_kind="floating_ole",
                            ordinal=index,
                            meta={
                                "shape_index": index,
                                "shape_type": self._safe_value(lambda: int(shape.Type)),
                                **ole_info,
                            },
                        )
                    )

            metafile_results = self._export_docx_metafiles_via_word(max_metafiles=max_metafiles)
            results.extend(metafile_results)


            summary = {

                "docx_path": str(self.docx_path),
                "output_dir": str(self.output_dir),
                "dpi": self.dpi,
                "elapsed_seconds": round(time.perf_counter() - started_at, 2),
                "document_stats": {
                    "omath_count": omath_count,
                    "inline_shape_count": inline_shape_count,
                    "shape_count": shape_count,
                    **self._inspect_docx_package(self.docx_path),
                },
                "exported_counts": {
                    "omath": sum(1 for item in results if item.source_kind == "omath"),
                    "inline_ole": sum(1 for item in results if item.source_kind == "inline_ole"),
                    "floating_ole": sum(1 for item in results if item.source_kind == "floating_ole"),
                    "docx_media_metafile": sum(1 for item in results if item.source_kind == "docx_media_metafile"),

                    "success_png": sum(1 for item in results if item.png_path),
                    "success_emf": sum(1 for item in results if item.emf_path),
                    "failed": sum(1 for item in results if item.error),
                },

                "results": [asdict(item) for item in results],
            }
            summary_path = self.output_dir / "summary.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k, v in summary.items() if k != "results"}, ensure_ascii=False, indent=2))
            print(f"summary saved to: {summary_path}")
            return summary
        finally:
            if document is not None:
                try:
                    document.Close(False)
                except Exception:
                    pass
            if app is not None:
                try:
                    app.Quit()
                except Exception:
                    pass
            if pythoncom is not None:
                pythoncom.CoUninitialize()

    def _export_range(self, range_obj, label: str, source_kind: str, ordinal: int, meta: dict[str, Any]) -> ExportResult:
        started_at = time.perf_counter()
        text_preview = self._normalize_preview_text(self._safe_value(lambda: str(range_obj.Text), ""))
        emf_path = self.output_dir / f"{label}.emf"
        png_path = self.output_dir / f"{label}.png"

        try:
            # 1. 尝试通过 EnhMetaFileBits (EMF) 导出，这种方式通常最清晰，因为它保留了矢量信息
            emf_bytes = self._variant_to_bytes(self._safe_value(lambda: range_obj.EnhMetaFileBits))
            if emf_bytes:
                emf_path.write_bytes(emf_bytes)
                # 使用更高 DPI 栅格化
                raster = self._rasterize_emf(emf_bytes)
                if raster is not None:
                    width, height = raster.size
                    # 针对小图进行放大，确保清晰度
                    target_scale = 3.0
                    if width < 300 or height < 100:
                        new_size = (int(width * target_scale), int(height * target_scale))
                        raster = raster.resize(new_size, Image.Resampling.LANCZOS)
                        width, height = raster.size
                    
                    raster.save(png_path, format="PNG")
                    return ExportResult(
                        label=label,
                        source_kind=source_kind,
                        ordinal=ordinal,
                        text_preview=text_preview,
                        emf_path=str(emf_path),
                        png_path=str(png_path),
                        width=width,
                        height=height,
                        method="range_enhmetafilebits",
                        elapsed_seconds=round(time.perf_counter() - started_at, 2),
                        meta=meta,
                    )

            # 2. 尝试通过 CopyAsPicture (剪贴板) 导出，增加缩放逻辑
            # 设置窗口缩放以获取更高清晰度的位图
            app = self._safe_value(lambda: range_obj.Application)
            original_zoom = 100
            window = None
            if app:
                window = self._safe_value(lambda: app.ActiveWindow)
                if window:
                    original_zoom = self._safe_word_value(lambda: int(window.View.Zoom.Percentage), 100)
                    self._safe_word_value(lambda: setattr(window.View.Zoom, "Percentage", 500) or True)
                    time.sleep(0.3)
                    self._safe_word_value(lambda: range_obj.Select())
                    time.sleep(0.2)

            try:
                self._safe_value(lambda: range_obj.CopyAsPicture())
                time.sleep(0.5)
                clipboard_image = ImageGrab.grabclipboard()
                if isinstance(clipboard_image, Image.Image):
                    trimmed = self._trim_raster_image(clipboard_image.convert("RGBA"))
                    width, height = trimmed.size
                    
                    # 针对截图也进行一次清晰度补偿（如果是小截图）
                    if width < 300 or height < 100:
                        target_scale = 2.0 # 剪贴板截图已经有500%缩放了，这里补一点就行
                        new_size = (int(width * target_scale), int(height * target_scale))
                        trimmed = trimmed.resize(new_size, Image.Resampling.LANCZOS)
                        width, height = trimmed.size

                    trimmed.save(png_path, format="PNG")
                    return ExportResult(
                        label=label,
                        source_kind=source_kind,
                        ordinal=ordinal,
                        text_preview=text_preview,
                        emf_path=None,
                        png_path=str(png_path),
                        width=width,
                        height=height,
                        method="copy_as_picture_clipboard_zoom500",
                        elapsed_seconds=round(time.perf_counter() - started_at, 2),
                        meta=meta,
                    )
            finally:
                # 还原缩放
                if window:
                    self._safe_word_value(lambda: setattr(window.View.Zoom, "Percentage", original_zoom) or True)

            return ExportResult(
                label=label,
                source_kind=source_kind,
                ordinal=ordinal,
                text_preview=text_preview,
                emf_path=None,
                png_path=None,
                width=None,
                height=None,
                method="none",
                elapsed_seconds=round(time.perf_counter() - started_at, 2),
                meta=meta,
                error="既无法通过 EnhMetaFileBits 导出，也无法从剪贴板取到图片",
            )
        except Exception as exc:
            return ExportResult(
                label=label,
                source_kind=source_kind,
                ordinal=ordinal,
                text_preview=text_preview,
                emf_path=str(emf_path) if emf_path.exists() else None,
                png_path=str(png_path) if png_path.exists() else None,
                width=None,
                height=None,
                method="error",
                elapsed_seconds=round(time.perf_counter() - started_at, 2),
                meta=meta,
                error=f"{exc.__class__.__name__}: {exc}",
            )

    def _safe_word_value(self, func, default=None):
        try:
            return func()
        except Exception:
            return default

    def _rasterize_emf(self, emf_bytes: bytes) -> Optional[Image.Image]:
        try:
            with Image.open(BytesIO(emf_bytes)) as image:
                image.load(dpi=self.dpi)
                return self._trim_raster_image(image.convert("RGBA"))
        except Exception:
            return None

    def _trim_raster_image(self, image: Image.Image) -> Image.Image:
        if image.width == 0 or image.height == 0:
            return image
        alpha_bbox = image.getchannel("A").getbbox()
        if alpha_bbox and alpha_bbox != (0, 0, image.width, image.height):
            image = image.crop(alpha_bbox)
        grayscale = image.convert("L")
        mask = grayscale.point(lambda value: 0 if value > 245 else 255)
        bbox = mask.getbbox()
        if not bbox:
            return image
        left = max(bbox[0] - 2, 0)
        top = max(bbox[1] - 2, 0)
        right = min(bbox[2] + 2, image.width)
        bottom = min(bbox[3] + 2, image.height)
        return image.crop((left, top, right, bottom))

    def _export_docx_metafiles_via_word(self, max_metafiles: int) -> list[ExportResult]:
        return self._export_via_filtered_html(max_html_images=max_metafiles)

    def _export_via_filtered_html(self, max_html_images: int) -> list[ExportResult]:
        started_at = time.perf_counter()
        results: list[ExportResult] = []
        with tempfile.TemporaryDirectory(prefix="word_html_export_") as temp_dir:
            temp_path = Path(temp_dir)
            html_path = temp_path / f"{self.docx_path.stem}.html"
            html_app = None
            export_document = None
            try:
                html_app = gencache.EnsureDispatch("Word.Application")
                html_app.Visible = False
                html_app.DisplayAlerts = 0
                html_app.ScreenUpdating = False
                export_document = html_app.Documents.Open(str(self.docx_path), ReadOnly=True, AddToRecentFiles=False)
                time.sleep(2.0)
                self._word_call(lambda: export_document.SaveAs2(str(html_path), FileFormat=10))
                time.sleep(1.0)
            finally:
                if export_document is not None:
                    try:
                        export_document.Close(False)
                    except Exception:
                        pass
                if html_app is not None:
                    try:
                        html_app.Quit()
                    except Exception:
                        pass


            html_files_dir = temp_path / f"{self.docx_path.stem}.files"
            if not html_files_dir.exists():
                html_files_dir = temp_path / f"{self.docx_path.stem}_files"
            if not html_files_dir.exists():
                return [
                    ExportResult(
                        label="filtered_html_export",
                        source_kind="filtered_html_image",
                        ordinal=0,
                        text_preview="",
                        emf_path=None,
                        png_path=None,
                        width=None,
                        height=None,
                        method="filtered_html_export",
                        elapsed_seconds=round(time.perf_counter() - started_at, 2),
                        meta={},
                        error="Word 过滤 HTML 导出未生成资源目录",
                    )
                ]

            image_files = [
                path for path in sorted(html_files_dir.iterdir())
                if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".wmf", ".emf"}
            ]
            for index, source_path in enumerate(image_files[:max_html_images], start=1):
                target_path = self.output_dir / f"filtered_html_{index:04d}{source_path.suffix.lower()}"
                shutil.copy2(source_path, target_path)
                width, height = self._read_image_size_if_possible(target_path)
                results.append(
                    ExportResult(
                        label=f"filtered_html_{index:04d}",
                        source_kind="filtered_html_image",
                        ordinal=index,
                        text_preview="",
                        emf_path=str(target_path) if target_path.suffix.lower() in {".emf", ".wmf"} else None,
                        png_path=str(target_path) if target_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".bmp"} else None,
                        width=width,
                        height=height,
                        method="filtered_html_export",
                        elapsed_seconds=round(time.perf_counter() - started_at, 2),
                        meta={"source_file": str(source_path.name)},
                    )
                )
        return results

    def _extract_ole_info(self, shape_obj) -> dict[str, Any]:
        prog_id = self._safe_value(lambda: str(shape_obj.OLEFormat.ProgID))
        class_type = self._safe_value(lambda: str(shape_obj.OLEFormat.ClassType))
        return {
            "is_ole": bool(prog_id or class_type),
            "prog_id": prog_id,
            "class_type": class_type,
        }

    def _read_image_size_if_possible(self, path: Path) -> tuple[Optional[int], Optional[int]]:
        try:
            with Image.open(path) as image:
                return image.width, image.height
        except Exception:
            return None, None

    def _variant_to_bytes(self, value: Any) -> Optional[bytes]:

        if value in (None, ""):
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, memoryview):
            return value.tobytes()
        try:
            return bytes(value)
        except Exception:
            try:
                return bytes(int(item) & 0xFF for item in value)
            except Exception:
                return None

    def _normalize_preview_text(self, text: str, limit: int = 80) -> str:
        normalized = " ".join((text or "").split())
        return normalized[:limit]

    def _inspect_docx_package(self, docx_path: Path) -> dict[str, Any]:
        media_entries: list[str] = []
        ole_entries: list[str] = []
        with zipfile.ZipFile(docx_path) as archive:
            for name in archive.namelist():
                if name.startswith("word/media/"):
                    media_entries.append(name)
                elif name.startswith("word/embeddings/"):
                    ole_entries.append(name)
        media_suffix_counts = Counter(Path(name).suffix.lower() for name in media_entries)
        return {
            "docx_media_count": len(media_entries),
            "docx_media_suffix_counts": dict(media_suffix_counts),
            "docx_ole_embedding_count": len(ole_entries),
        }

    def _word_call(self, func, default=None, retries: int = 8, delay: float = 0.35):
        last_error = None
        for _ in range(retries):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                try:
                    pythoncom.PumpWaitingMessages()
                except Exception:
                    pass
                time.sleep(delay)

        if default is not None:
            return default
        raise last_error

    def _safe_value(self, func, default=None):
        try:
            return self._word_call(func, default=default)
        except Exception:
            return default



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="单独测试 Word 特殊对象/公式导出为清晰图片")
    parser.add_argument("docx_path", type=Path, help="待测试的 .docx 文件")
    parser.add_argument("--output-dir", type=Path, default=Path("word_object_image_test_output"), help="输出目录")
    parser.add_argument("--dpi", type=int, default=1200, help="EMF 栅格化 DPI")
    parser.add_argument("--max-omaths", type=int, default=12, help="最多导出多少个 OMath")
    parser.add_argument("--max-inline-ole", type=int, default=12, help="最多导出多少个内联 OLE 对象")
    parser.add_argument("--include-floating-shapes", action="store_true", help="是否尝试导出浮动 Shape OLE 对象")
    parser.add_argument("--max-metafiles", type=int, default=20, help="Word 过滤 HTML 导出后最多保留多少张图片")
    parser.add_argument("--max-html-images", type=int, default=None, help="兼容旧参数名（等价于 --max-metafiles）")
    return parser.parse_args()



def main() -> None:
    args = parse_args()
    exporter = WordObjectImageExporter(docx_path=args.docx_path.resolve(), output_dir=args.output_dir.resolve(), dpi=args.dpi)
    max_metafiles = args.max_html_images if args.max_html_images is not None else args.max_metafiles
    exporter.run(
        max_omaths=args.max_omaths,
        max_inline_ole=args.max_inline_ole,
        include_floating_shapes=args.include_floating_shapes,
        max_metafiles=max_metafiles,
    )



if __name__ == "__main__":
    main()
