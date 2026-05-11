import copy
import hashlib
import logging
import math
import re
import xml.etree.ElementTree as ET
import zipfile

import shutil

import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional



from docx import Document as load_docx_document

from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from PIL import Image, ImageFilter, ImageStat

from analyzer.app.config import QUESTION_BANK_DOCX_OMML_AS_IMAGES

try:
    from PIL import ImageGrab

except Exception:
    ImageGrab = None

try:
    import pythoncom
    from win32com.client import DispatchEx, gencache
except Exception:
    pythoncom = None
    DispatchEx = None
    gencache = None

try:
    import win32clipboard
except Exception:
    win32clipboard = None




logger = logging.getLogger(__name__)


DOCX_NS = {

    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}



ALIGNMENT_MAP = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
    WD_ALIGN_PARAGRAPH.DISTRIBUTE: "distribute",
}

IMAGE_PLACEHOLDER_TEXT = "[图片]"
METAFILE_RENDER_DPI = 1200
METAFILE_RENDER_TARGET_SCALE = 5.0
METAFILE_RENDER_SUPERSAMPLE = 2.0
METAFILE_RENDER_MAX_PIXELS = 8_000_000
METAFILE_SLOW_LOG_SECONDS = 3.0
WORD_COPY_AS_PICTURE_ZOOM_PERCENTAGES = (500, 100)
WORD_COPY_AS_PICTURE_CAPTURE_ATTEMPTS = 4
WORD_PRINT_VIEW = 3
WORD_OLE_TARGET_ENUM_RETRIES = 3
WORD_OLE_TARGET_ENUM_DELAY_SECONDS = 0.15
WORD_OLE_TARGET_COLLECT_TIMEOUT_SECONDS = 0.0
LEGACY_OBJECT_SOURCE_WORD_PICTURE = "word_picture"
LEGACY_OBJECT_SOURCE_FILTERED_HTML = "filtered_html"
LEGACY_OBJECT_SOURCE_EMBEDDED = "embedded"
LEGACY_OBJECT_WORD_EXPORT_EARLY_STOP_MIN_SLOTS = 48
LEGACY_OBJECT_WORD_EXPORT_SHAPE_ACCESS_ERROR_STREAK = 24
LEGACY_OBJECT_WORD_EXPORT_EMPTY_PROBE_TARGETS = 16











@dataclass
class StructuredDocxBlock:

    text: str
    render: Dict[str, Any]


@dataclass
class _RichImageAsset:
    storage_url: str
    file_hash: str
    width: Optional[int]
    height: Optional[int]


@dataclass
class _LegacyObjectImage:
    asset: _RichImageAsset
    width: Optional[int]
    height: Optional[int]
    source: str
    ordinal: int
    layout_width_px: Optional[int] = None
    layout_height_px: Optional[int] = None


@dataclass
class _LegacyObjectCandidate:
    source: str
    storage_url: str
    file_hash: str
    width: Optional[int]
    height: Optional[int]
    ordinal: Optional[int] = None


@dataclass
class _LegacyObjectSlot:
    ordinal: int
    preferred_width: Optional[int]
    preferred_height: Optional[int]
    embedded_candidates: List[_LegacyObjectCandidate] = field(default_factory=list)
    best_embedded_candidate: Optional[_LegacyObjectCandidate] = None
    word_picture_candidate: Optional[_LegacyObjectCandidate] = None
    filtered_html_candidate: Optional[_LegacyObjectCandidate] = None
    filtered_html_alignment_score: Optional[float] = None
    local_reliability: float = 0.0
    selected_candidate: Optional[_LegacyObjectCandidate] = None
    selected_score: Optional[float] = None
    selected_node: Optional[Dict[str, Any]] = None
    selection_debug: Dict[str, Any] = field(default_factory=dict)


class _FilteredHtmlImageParser(HTMLParser):

    def __init__(self) -> None:
        super().__init__()
        self.images: List[Dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "img":
            return
        attr_map = {key.lower(): value for key, value in attrs if key}
        self.images.append(
            {
                "src": attr_map.get("src"),
                "width": self._safe_int(attr_map.get("width")),
                "height": self._safe_int(attr_map.get("height")),
            }
        )

    @staticmethod
    def _safe_int(value: Optional[str]) -> Optional[int]:
        try:
            return int(str(value)) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None


class DocxRichContentExtractor:

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._image_cache: Dict[str, _RichImageAsset] = {}
        self._blank_image_cache: Dict[str, bool] = {}
        self._image_analysis_cache: Dict[str, Dict[str, Any]] = {}
        self._source_docx_path: Optional[Path] = None
        self._word_export_docx_path: Optional[Path] = None
        self._legacy_object_images: List[Optional[_LegacyObjectImage]] = []

        self._legacy_object_slots: List[_LegacyObjectSlot] = []

        self._legacy_object_fallback_images: List[_LegacyObjectImage] = []
        self._legacy_object_slot_cursor = 0
        self._legacy_object_export_attempted = False
        self._legacy_object_expected_count: Optional[int] = None
        self._legacy_object_embedded_covered_slots = 0
        self._legacy_object_embedded_full_coverage = False
        self._legacy_word_export_early_stopped = False

        self._metafile_total = 0

        self._metafile_pillow_success = 0
        self._metafile_libreoffice_success = 0
        self._metafile_fail = 0
        self._metafile_slow = 0
        self._omath_word_images: List[Optional[_LegacyObjectImage]] = []
        self._omath_word_cursor = int(0)
        self._omath_placeholder_render: Optional[Dict[str, Any]] = None
        self._omath_layout_hints: List[tuple[Optional[int], Optional[int]]] = []


    def extract(self, path: Path, word_export_path: Optional[Path] = None) -> List[StructuredDocxBlock]:
        started_at = time.perf_counter()
        self._source_docx_path = Path(path)
        candidate_word_export_path = Path(word_export_path) if word_export_path else self._source_docx_path
        self._word_export_docx_path = candidate_word_export_path if candidate_word_export_path.exists() else self._source_docx_path
        self._blank_image_cache = {}
        self._image_analysis_cache = {}
        self._legacy_object_images = []
        self._legacy_object_slots = []

        self._legacy_object_fallback_images = []
        self._legacy_object_slot_cursor = 0
        self._legacy_object_export_attempted = False
        self._legacy_object_expected_count = None
        self._legacy_object_embedded_covered_slots = 0
        self._legacy_object_embedded_full_coverage = False
        self._legacy_word_export_early_stopped = False

        self._metafile_total = 0


        self._metafile_pillow_success = 0
        self._metafile_libreoffice_success = 0
        self._metafile_fail = 0
        self._metafile_slow = 0
        self._omath_word_images = []
        self._omath_word_cursor = 0
        self._omath_placeholder_render = None
        self._omath_layout_hints = []
        logger.info(
            "Docx rich content extract start: path=%s word_export_path=%s output_dir=%s",
            self._source_docx_path,
            self._word_export_docx_path,
            self.output_dir,
        )
        document = load_docx_document(path)
        if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
            self._omath_layout_hints = self._collect_omath_layout_hints_from_loaded_document(document)
        if (
            QUESTION_BANK_DOCX_OMML_AS_IMAGES
            and pythoncom is not None
            and (DispatchEx is not None or gencache is not None)
        ):
            try:
                self._omath_word_images = self._export_omath_images_via_word(self._word_export_docx_path)
                logger.info(
                    "DOCX OMath raster: file=%s images=%s usable=%s layout_hints_body=%s",
                    self._word_export_docx_path.name,
                    len(self._omath_word_images),
                    sum(1 for x in self._omath_word_images if x and self._is_usable_legacy_object_image(x)),
                    len(self._omath_layout_hints),
                )
            except Exception as exc:
                logger.warning("DOCX OMath raster via Word failed (fallback=placeholder): %s", exc)
                self._omath_word_images = []

        self._prepare_legacy_object_slots(document)

        blocks: List[StructuredDocxBlock] = []

        for item in self._iter_block_items(document):

            if isinstance(item, Paragraph):
                blocks.extend(self._build_paragraph_blocks(item))
                continue
            if isinstance(item, Table):
                table_render = self._build_table_render(item)
                table_text = self._render_to_text(table_render)
                if table_text or table_render.get("rows"):
                    blocks.append(StructuredDocxBlock(text=table_text, render=table_render))
        logger.info(
            "Docx rich content extract done: path=%s blocks=%s legacy_object_images=%s legacy_object_slots=%s metafile_total=%s pillow_success=%s libreoffice_success=%s failed=%s slow=%s elapsed=%s",
            self._source_docx_path,
            len(blocks),
            self._count_ready_legacy_object_images(self._legacy_object_images),
            len(self._legacy_object_images),
            self._metafile_total,
            self._metafile_pillow_success,
            self._metafile_libreoffice_success,
            self._metafile_fail,
            self._metafile_slow,
            f"{time.perf_counter() - started_at:.2f}s",
        )

        return blocks


    def _iter_block_items(self, parent: DocxDocument | _Cell) -> Iterable[Paragraph | Table]:
        if isinstance(parent, DocxDocument):
            parent_elm = parent.element.body
        elif isinstance(parent, _Cell):
            parent_elm = parent._tc
        else:
            raise TypeError(f"Unsupported parent type: {type(parent)!r}")

        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    def _build_paragraph_blocks(self, paragraph: Paragraph) -> List[StructuredDocxBlock]:
        paragraph_render = {
            "type": "paragraph",
            "style": self._build_paragraph_style(paragraph),
            "children": self._extract_paragraph_children(paragraph),
        }
        blocks: List[StructuredDocxBlock] = []
        for logical_paragraph in self._split_paragraph_render(paragraph_render):
            logical_text = self._render_to_text(logical_paragraph)
            if logical_text or logical_paragraph.get("children"):
                blocks.append(StructuredDocxBlock(text=logical_text, render=logical_paragraph))
        return blocks

    def _build_table_render(self, table: Table) -> Dict[str, Any]:
        rows: List[Dict[str, Any]] = []
        for row in table.rows:
            row_cells: List[Dict[str, Any]] = []
            for cell in row.cells:
                cell_blocks: List[Dict[str, Any]] = []
                for cell_item in self._iter_block_items(cell):
                    if isinstance(cell_item, Paragraph):
                        cell_blocks.extend(block.render for block in self._build_paragraph_blocks(cell_item))
                    elif isinstance(cell_item, Table):
                        cell_blocks.append(self._build_table_render(cell_item))
                row_cells.append({"type": "table_cell", "blocks": cell_blocks})
            rows.append({"type": "table_row", "cells": row_cells})
        return {"type": "table", "rows": rows}

    def _extract_paragraph_children(self, paragraph: Paragraph) -> List[Dict[str, Any]]:
        """按 w:p 子节点顺序提取，包含段落级 Office Math（python-docx 的 runs 会漏掉 m:oMathPara）。"""
        from docx.text.run import Run

        children: List[Dict[str, Any]] = []
        p_elm = paragraph._element
        for child in p_elm.iterchildren():
            ln = self._local_name(child.tag)
            if ln == "r":
                children.extend(self._extract_run_children(Run(child, paragraph)))
            elif ln == "hyperlink":
                for sub in child.iterchildren():
                    if self._local_name(sub.tag) == "r":
                        children.extend(self._extract_run_children(Run(sub, paragraph)))
            elif ln in {"oMath", "oMathPara"}:
                if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
                    children.append(self._consume_omath_render_dict())
                else:
                    formula_text = self._extract_formula_text(child)
                    children.append(
                        {
                            "type": "formula",
                            "text": formula_text or "[公式]",
                            "display": ln == "oMathPara",
                            "marks": {},
                        }
                    )
            elif ln == "AlternateContent":
                children.extend(self._extract_alternate_content_math(paragraph, child))
        return self._merge_adjacent_text_nodes(children)

    def _extract_alternate_content_math(self, paragraph: Paragraph, ac_el) -> List[Dict[str, Any]]:
        """mc:AlternateContent：优先取 Choice 内 OMML，否则尝试 Fallback 中的绘图/图片。"""
        out: List[Dict[str, Any]] = []
        first_omath: Any = None
        first_omath_ln = ""
        for el in ac_el.iter():
            ln = self._local_name(el.tag)
            if ln in {"oMath", "oMathPara"}:
                first_omath = el
                first_omath_ln = ln
                break
        if first_omath is not None:
            if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
                return [self._consume_omath_render_dict()]
            formula_text = self._extract_formula_text(first_omath)
            return [
                {
                    "type": "formula",
                    "text": formula_text or "[公式]",
                    "display": first_omath_ln == "oMathPara",
                    "marks": {},
                }
            ]
        for fb in ac_el.findall(f".//{{{DOCX_NS['mc']}}}Fallback"):
            for dr in fb.findall(f".//{{{DOCX_NS['w']}}}drawing"):
                out.extend(self._extract_image_nodes(paragraph.part, dr))
            for pic in fb.findall(f".//{{{DOCX_NS['w']}}}pict"):
                out.extend(self._extract_image_nodes(paragraph.part, pic))
        return out

    def _extract_run_children(self, run) -> List[Dict[str, Any]]:
        marks = self._build_run_marks(run)
        children: List[Dict[str, Any]] = []
        for child in run._r.iterchildren():
            local_name = self._local_name(child.tag)
            if local_name == "t":
                text = child.text or ""
                if text:
                    children.append({"type": "text", "text": text, "marks": marks})
                continue
            if local_name == "tab":
                children.append({"type": "text", "text": "    ", "marks": marks})
                continue
            if local_name in {"br", "cr"}:
                children.append({"type": "line_break"})
                continue
            if local_name == "object":
                children.extend(self._extract_legacy_object_nodes(run.part, child))
                continue
            if local_name in {"drawing", "pict"}:
                children.extend(self._extract_image_nodes(run.part, child))
                continue


            if local_name in {"oMath", "oMathPara"}:
                if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
                    children.append(self._consume_omath_render_dict())
                else:
                    formula_text = self._extract_formula_text(child)
                    children.append(
                        {
                            "type": "formula",
                            "text": formula_text or "[公式]",
                            "display": local_name == "oMathPara",
                            "marks": marks,
                        }
                    )
                continue
            if local_name == "AlternateContent":
                parent = getattr(run, "_parent", None)
                if isinstance(parent, Paragraph):
                    children.extend(self._extract_alternate_content_math(parent, child))
        return children

    def _extract_image_nodes(self, part, element, skip_blank: bool = False) -> List[Dict[str, Any]]:
        nodes: List[Dict[str, Any]] = []
        for rel_id in self._extract_image_rel_ids(element):
            image_part = part.related_parts.get(rel_id)
            if image_part is None:
                continue
            preferred_width, preferred_height = self._extract_image_size(element, None, None)
            asset = self._export_image_part(image_part, preferred_size=(preferred_width, preferred_height))
            width, height = self._extract_image_size(element, asset.width, asset.height)
            if skip_blank and self._is_blank_image_asset(asset):
                logger.info(
                    "Skip blank embedded image: storage_url=%s size=%sx%s",
                    asset.storage_url,
                    width or asset.width or 0,
                    height or asset.height or 0,
                )
                continue

            nodes.append(
                {
                    "type": "image",
                    "storage_url": asset.storage_url,
                    "file_hash": asset.file_hash,
                    "width": width or asset.width,
                    "height": height or asset.height,
                    "layout_width_px": preferred_width,
                    "layout_height_px": preferred_height,
                    "raster_width": asset.width,
                    "raster_height": asset.height,
                    "alt_text": IMAGE_PLACEHOLDER_TEXT,
                }
            )
        return nodes


    def _extract_legacy_object_nodes(self, part, element) -> List[Dict[str, Any]]:
        slot = self._next_legacy_object_slot()
        if slot is None:
            logger.warning("Legacy object slot missing during extraction: fallback=embedded_only")
            return self._extract_image_nodes(part, element, skip_blank=True)
        if slot.selected_node is None:
            logger.info("Legacy object slot unresolved: slot=%s returning_empty", slot.ordinal)
            return []
        return [copy.deepcopy(slot.selected_node)]

    def _count_ready_legacy_object_images(self, images: List[Optional[_LegacyObjectImage]]) -> int:
        return sum(1 for item in images if item is not None)

    def _count_legacy_object_slots_with_embedded_candidates(
        self,
        slots: Optional[List[_LegacyObjectSlot]] = None,
    ) -> int:
        target_slots = self._legacy_object_slots if slots is None else slots
        return sum(1 for slot in target_slots if slot.embedded_candidates)

    def _should_enable_legacy_word_export_early_stop(self, expected_count: int) -> bool:
        return bool(
            self._legacy_object_embedded_full_coverage
            and expected_count >= LEGACY_OBJECT_WORD_EXPORT_EARLY_STOP_MIN_SLOTS
        )

    def _count_docx_legacy_object_slots(self, source_path: Path) -> int:

        try:
            with zipfile.ZipFile(source_path) as archive:
                document_xml = archive.read("word/document.xml")
            root = ET.fromstring(document_xml)
        except Exception:
            logger.exception("Failed to inspect DOCX legacy object count: path=%s", source_path)
            return 0
        return len(root.findall(".//w:object", DOCX_NS))

    def _is_usable_legacy_object_image(self, image: Optional[_LegacyObjectImage]) -> bool:
        if image is None:
            return False
        path = Path(image.asset.storage_url)
        if not path.exists() or not path.is_file():
            return False
        width = int(image.width or image.asset.width or 0)
        height = int(image.height or image.asset.height or 0)
        if width <= 0 or height <= 0:
            return False
        try:
            return path.stat().st_size > 0
        except OSError:
            return False

    def _clean_filtered_legacy_object_images(self, images: List[_LegacyObjectImage]) -> List[_LegacyObjectImage]:
        cleaned: List[_LegacyObjectImage] = []
        for item in images:
            if not self._is_usable_legacy_object_image(item):
                continue
            cleaned.append(item)
        return cleaned

    def _is_blank_image_asset(self, asset: _RichImageAsset) -> bool:
        cache_key = asset.file_hash or asset.storage_url
        cached = self._blank_image_cache.get(cache_key)
        if cached is not None:
            return cached
        is_blank = bool(self._analyze_image_path(Path(asset.storage_url)).get("blank"))
        self._blank_image_cache[cache_key] = is_blank
        return is_blank

    def _is_effectively_blank_legacy_object_image(self, image: Optional[_LegacyObjectImage]) -> bool:
        return bool(image is not None and self._is_blank_image_asset(image.asset))

    def _prepare_legacy_object_slots(self, document: DocxDocument) -> None:
        if self._legacy_object_slots:
            return

        slots: List[_LegacyObjectSlot] = []
        for ordinal, (part, element) in enumerate(self._iter_legacy_object_elements(document), start=1):
            preferred_width, preferred_height = self._extract_image_size(element, None, None)
            embedded_candidates = [
                candidate
                for node in self._extract_image_nodes(part, element, skip_blank=True)
                if (candidate := self._candidate_from_image_node(node, source=LEGACY_OBJECT_SOURCE_EMBEDDED, ordinal=ordinal)) is not None
            ]
            slots.append(
                _LegacyObjectSlot(
                    ordinal=ordinal,
                    preferred_width=preferred_width,
                    preferred_height=preferred_height,
                    embedded_candidates=embedded_candidates,
                )
            )

        self._legacy_object_slots = slots
        self._legacy_object_slot_cursor = 0
        self._legacy_object_expected_count = len(slots)
        self._legacy_object_embedded_covered_slots = self._count_legacy_object_slots_with_embedded_candidates(slots)
        self._legacy_object_embedded_full_coverage = bool(slots) and self._legacy_object_embedded_covered_slots == len(slots)
        self._legacy_word_export_early_stopped = False
        if not slots:
            self._legacy_object_export_attempted = True
            return

        logger.info(
            "Legacy object slot scan ready: slots=%s embedded_covered_slots=%s embedded_full_coverage=%s",
            len(slots),
            self._legacy_object_embedded_covered_slots,
            self._legacy_object_embedded_full_coverage,
        )

        if not self._legacy_object_export_attempted:
            self._prepare_legacy_object_images()


        for slot in self._legacy_object_slots:
            if slot.ordinal - 1 < len(self._legacy_object_images):
                slot.word_picture_candidate = self._candidate_from_legacy_image(self._legacy_object_images[slot.ordinal - 1])
            slot.best_embedded_candidate = self._pick_best_embedded_candidate(slot)
            slot.local_reliability = self._estimate_legacy_object_local_reliability(slot)

        self._align_filtered_html_candidates(self._legacy_object_slots, self._legacy_object_fallback_images)

        source_counts: Dict[str, int] = {}
        for slot in self._legacy_object_slots:
            self._resolve_legacy_object_slot_candidates(slot)
            chosen_source = slot.selected_candidate.source if slot.selected_candidate is not None else "missing"
            source_counts[chosen_source] = source_counts.get(chosen_source, 0) + 1

        logger.info(
            "Legacy object slot selection ready: slots=%s selected_word_picture=%s selected_embedded=%s selected_filtered_html=%s missing=%s",
            len(self._legacy_object_slots),
            source_counts.get(LEGACY_OBJECT_SOURCE_WORD_PICTURE, 0),
            source_counts.get(LEGACY_OBJECT_SOURCE_EMBEDDED, 0),
            source_counts.get(LEGACY_OBJECT_SOURCE_FILTERED_HTML, 0),
            source_counts.get("missing", 0),
        )

    def _iter_legacy_object_elements(self, parent: DocxDocument | _Cell) -> Iterable[tuple[Any, Any]]:
        for item in self._iter_block_items(parent):
            if isinstance(item, Paragraph):
                for run in item.runs:
                    for child in run._r.iterchildren():
                        if self._local_name(child.tag) == "object":
                            yield run.part, child
                continue
            if isinstance(item, Table):
                for row in item.rows:
                    for cell in row.cells:
                        yield from self._iter_legacy_object_elements(cell)

    def _candidate_from_image_node(
        self,
        node: Optional[Dict[str, Any]],
        source: str,
        ordinal: Optional[int] = None,
    ) -> Optional[_LegacyObjectCandidate]:
        if not node:
            return None
        storage_url = str(node.get("storage_url") or "").strip()
        file_hash = str(node.get("file_hash") or "").strip()
        if not storage_url:
            return None
        return _LegacyObjectCandidate(
            source=source,
            storage_url=storage_url,
            file_hash=file_hash,
            width=self._safe_int(node.get("width")),
            height=self._safe_int(node.get("height")),
            ordinal=ordinal,
        )

    def _candidate_from_legacy_image(self, image: Optional[_LegacyObjectImage]) -> Optional[_LegacyObjectCandidate]:
        if image is None or not self._is_usable_legacy_object_image(image) or self._is_effectively_blank_legacy_object_image(image):
            return None
        return _LegacyObjectCandidate(
            source=image.source,
            storage_url=image.asset.storage_url,
            file_hash=image.asset.file_hash,
            width=image.width or image.asset.width,
            height=image.height or image.asset.height,
            ordinal=image.ordinal,
        )

    def _next_legacy_object_slot(self) -> Optional[_LegacyObjectSlot]:
        if self._legacy_object_slot_cursor >= len(self._legacy_object_slots):
            return None
        slot = self._legacy_object_slots[self._legacy_object_slot_cursor]
        self._legacy_object_slot_cursor += 1
        return slot

    def _pick_best_embedded_candidate(self, slot: _LegacyObjectSlot) -> Optional[_LegacyObjectCandidate]:
        if not slot.embedded_candidates:
            return None
        return min(slot.embedded_candidates, key=lambda candidate: self._score_embedded_candidate_for_slot(slot, candidate))

    def _score_embedded_candidate_for_slot(self, slot: _LegacyObjectSlot, candidate: _LegacyObjectCandidate) -> float:
        target_width, target_height = self._resolve_legacy_object_slot_target_size(slot, fallback_candidate=candidate)
        return self._size_mismatch_score(candidate.width, candidate.height, target_width, target_height) + self._legacy_object_quality_penalty(candidate)

    def _estimate_legacy_object_local_reliability(self, slot: _LegacyObjectSlot) -> float:
        if slot.word_picture_candidate is not None:
            return 1.0
        candidate = slot.best_embedded_candidate
        if candidate is None:
            return 0.0
        analysis = self._analyze_image_candidate(candidate)
        reliability = 0.28
        if not analysis.get("blank"):
            reliability += 0.18
        if float(analysis.get("ink_pixel_ratio") or 0.0) >= 0.01:
            reliability += 0.14
        sharpness = float(analysis.get("sharpness") or 0.0)
        if sharpness >= 12:
            reliability += 0.16
        if sharpness >= 40:
            reliability += 0.14
        size_score = self._size_mismatch_score(candidate.width, candidate.height, slot.preferred_width, slot.preferred_height)
        if size_score <= 0.35:
            reliability += 0.1
        return min(reliability, 0.9)

    def _align_filtered_html_candidates(
        self,
        slots: List[_LegacyObjectSlot],
        filtered_images: List[_LegacyObjectImage],
    ) -> None:
        for slot in slots:
            slot.filtered_html_candidate = None
            slot.filtered_html_alignment_score = None

        filtered_candidates = [
            candidate
            for image in filtered_images
            if (candidate := self._candidate_from_legacy_image(image)) is not None
        ]
        if not slots or not filtered_candidates:
            return

        slot_count = len(slots)
        candidate_count = len(filtered_candidates)
        dp: List[List[float]] = [[float("inf")] * (candidate_count + 1) for _ in range(slot_count + 1)]
        move: List[List[int]] = [[0] * (candidate_count + 1) for _ in range(slot_count + 1)]
        dp[0][0] = 0.0

        for slot_index in range(1, slot_count + 1):
            dp[slot_index][0] = dp[slot_index - 1][0] + self._legacy_object_slot_skip_cost(slots[slot_index - 1])
            move[slot_index][0] = 1
        for candidate_index in range(1, candidate_count + 1):
            dp[0][candidate_index] = dp[0][candidate_index - 1] + self._legacy_object_candidate_skip_cost(filtered_candidates[candidate_index - 1])
            move[0][candidate_index] = 2

        for slot_index in range(1, slot_count + 1):
            slot = slots[slot_index - 1]
            slot_skip_cost = self._legacy_object_slot_skip_cost(slot)
            for candidate_index in range(1, candidate_count + 1):
                candidate = filtered_candidates[candidate_index - 1]
                best_cost = dp[slot_index - 1][candidate_index] + slot_skip_cost
                best_move = 1

                candidate_skip_cost = dp[slot_index][candidate_index - 1] + self._legacy_object_candidate_skip_cost(candidate)
                if candidate_skip_cost < best_cost:
                    best_cost = candidate_skip_cost
                    best_move = 2

                match_cost = dp[slot_index - 1][candidate_index - 1] + self._score_filtered_html_alignment(slot, candidate)
                if match_cost < best_cost:
                    best_cost = match_cost
                    best_move = 3

                dp[slot_index][candidate_index] = best_cost
                move[slot_index][candidate_index] = best_move

        slot_index = slot_count
        candidate_index = candidate_count
        while slot_index > 0 or candidate_index > 0:
            current_move = move[slot_index][candidate_index]
            if current_move == 3:
                slot = slots[slot_index - 1]
                candidate = filtered_candidates[candidate_index - 1]
                alignment_score = self._score_filtered_html_alignment(slot, candidate)
                slot.filtered_html_candidate = candidate
                slot.filtered_html_alignment_score = alignment_score
                logger.info(
                    "Legacy object fallback aligned: slot=%s candidate_ordinal=%s alignment_score=%s storage_url=%s",
                    slot.ordinal,
                    candidate.ordinal or 0,
                    f"{alignment_score:.4f}",
                    candidate.storage_url,
                )
                slot_index -= 1
                candidate_index -= 1
                continue
            if current_move == 2:
                candidate_index -= 1
                continue
            if current_move == 1:
                slot_index -= 1
                continue
            break

    def _legacy_object_slot_skip_cost(self, slot: _LegacyObjectSlot) -> float:
        if slot.word_picture_candidate is not None:
            return 0.02
        if slot.best_embedded_candidate is None:
            return 1.35
        return max(0.08, 1.35 - min(slot.local_reliability, 1.0) * 1.45)

    def _legacy_object_candidate_skip_cost(self, candidate: _LegacyObjectCandidate) -> float:
        quality_penalty = self._legacy_object_quality_penalty(candidate)
        return max(0.03, 0.08 - min(quality_penalty, 1.0) * 0.02)

    def _score_filtered_html_alignment(self, slot: _LegacyObjectSlot, candidate: _LegacyObjectCandidate) -> float:
        target_width, target_height = self._resolve_legacy_object_slot_target_size(slot, fallback_candidate=candidate)
        ordinal_gap = abs((candidate.ordinal or slot.ordinal) - slot.ordinal)
        score = 0.35
        score += self._size_mismatch_score(candidate.width, candidate.height, target_width, target_height)
        score += self._legacy_object_quality_penalty(candidate) * 0.55
        score += min(ordinal_gap * 0.015, 0.6)

        reference = slot.word_picture_candidate or slot.best_embedded_candidate
        if reference is not None:
            score += self._candidate_similarity_distance(candidate, reference) * 1.9
            score += slot.local_reliability * 0.35
        return score

    def _resolve_legacy_object_slot_candidates(self, slot: _LegacyObjectSlot) -> None:
        candidate_scores: List[tuple[float, _LegacyObjectCandidate, Dict[str, Any]]] = []
        seen_keys: set[str] = set()
        for candidate in (slot.word_picture_candidate, slot.best_embedded_candidate, slot.filtered_html_candidate):
            if candidate is None:
                continue
            lookup_key = self._candidate_lookup_key(candidate)
            if lookup_key and lookup_key in seen_keys:
                continue
            if lookup_key:
                seen_keys.add(lookup_key)
            score, components = self._score_legacy_object_slot_candidate(slot, candidate)
            candidate_scores.append((score, candidate, components))

        if not candidate_scores:
            slot.selected_candidate = None
            slot.selected_score = None
            slot.selected_node = None
            slot.selection_debug = {
                "slot_ordinal": slot.ordinal,
                "chosen_source": None,
                "chosen_score": None,
                "preferred_width": slot.preferred_width,
                "preferred_height": slot.preferred_height,
            }
            return

        candidate_scores.sort(key=lambda item: item[0])
        best_score, best_candidate, _ = candidate_scores[0]
        slot.selected_candidate = best_candidate
        slot.selected_score = best_score
        slot.selection_debug = {
            "slot_ordinal": slot.ordinal,
            "preferred_width": slot.preferred_width,
            "preferred_height": slot.preferred_height,
            "chosen_source": best_candidate.source,
            "chosen_score": round(best_score, 4),
            "word_picture_storage_url": slot.word_picture_candidate.storage_url if slot.word_picture_candidate else None,
            "embedded_storage_url": slot.best_embedded_candidate.storage_url if slot.best_embedded_candidate else None,
            "filtered_html_storage_url": slot.filtered_html_candidate.storage_url if slot.filtered_html_candidate else None,
            "filtered_html_alignment_score": round(slot.filtered_html_alignment_score, 4) if slot.filtered_html_alignment_score is not None else None,
            "candidates": [
                {
                    **components,
                    "source": candidate.source,
                    "storage_url": candidate.storage_url,
                    "file_hash": candidate.file_hash,
                    "score": round(score, 4),
                }
                for score, candidate, components in candidate_scores
            ],
        }
        slot.selected_node = self._build_legacy_object_output_node(slot, best_candidate)
        logger.info(
            "Legacy object slot resolved: slot=%s chosen_source=%s chosen_score=%s chosen_storage_url=%s word_picture=%s embedded=%s filtered_html=%s",
            slot.ordinal,
            best_candidate.source,
            f"{best_score:.4f}",
            best_candidate.storage_url,
            slot.word_picture_candidate.storage_url if slot.word_picture_candidate else "",
            slot.best_embedded_candidate.storage_url if slot.best_embedded_candidate else "",
            slot.filtered_html_candidate.storage_url if slot.filtered_html_candidate else "",
        )

    def _score_legacy_object_slot_candidate(
        self,
        slot: _LegacyObjectSlot,
        candidate: _LegacyObjectCandidate,
    ) -> tuple[float, Dict[str, Any]]:
        target_width, target_height = self._resolve_legacy_object_slot_target_size(slot, fallback_candidate=candidate)
        size_penalty = self._size_mismatch_score(candidate.width, candidate.height, target_width, target_height)
        quality_penalty = self._legacy_object_quality_penalty(candidate)
        source_penalty = self._legacy_object_candidate_source_penalty(slot, candidate)
        similarity_penalty = 0.0
        ordinal_penalty = 0.0

        if candidate.source == LEGACY_OBJECT_SOURCE_FILTERED_HTML:
            ordinal_penalty = min(abs((candidate.ordinal or slot.ordinal) - slot.ordinal) * 0.02, 0.8)
            reference = slot.word_picture_candidate or slot.best_embedded_candidate
            if reference is not None:
                similarity_penalty = self._candidate_similarity_distance(candidate, reference) * 2.25
        elif candidate.source == LEGACY_OBJECT_SOURCE_EMBEDDED and slot.word_picture_candidate is not None:
            similarity_penalty = self._candidate_similarity_distance(candidate, slot.word_picture_candidate) * 0.35

        score = size_penalty + quality_penalty + source_penalty + similarity_penalty + ordinal_penalty
        analysis = self._analyze_image_candidate(candidate)
        return score, {
            "width": candidate.width,
            "height": candidate.height,
            "target_width": target_width,
            "target_height": target_height,
            "size_penalty": round(size_penalty, 4),
            "quality_penalty": round(quality_penalty, 4),
            "source_penalty": round(source_penalty, 4),
            "similarity_penalty": round(similarity_penalty, 4),
            "ordinal_penalty": round(ordinal_penalty, 4),
            "sharpness": round(float(analysis.get("sharpness") or 0.0), 4),
            "ink_pixel_ratio": round(float(analysis.get("ink_pixel_ratio") or 0.0), 4),
            "ink_bbox_ratio": round(float(analysis.get("ink_bbox_ratio") or 0.0), 4),
        }

    def _legacy_object_candidate_source_penalty(
        self,
        slot: _LegacyObjectSlot,
        candidate: _LegacyObjectCandidate,
    ) -> float:
        if candidate.source == LEGACY_OBJECT_SOURCE_WORD_PICTURE:
            return 0.0
        if candidate.source == LEGACY_OBJECT_SOURCE_EMBEDDED:
            return 0.12
        if candidate.source == LEGACY_OBJECT_SOURCE_FILTERED_HTML:
            if slot.word_picture_candidate is None and slot.best_embedded_candidate is None:
                return 0.22
            return 0.95
        return 0.4

    def _legacy_object_quality_penalty(self, candidate: _LegacyObjectCandidate) -> float:
        analysis = self._analyze_image_candidate(candidate)
        if analysis.get("blank"):
            return 10.0
        ink_pixel_ratio = float(analysis.get("ink_pixel_ratio") or 0.0)
        ink_bbox_ratio = float(analysis.get("ink_bbox_ratio") or 0.0)
        sharpness = float(analysis.get("sharpness") or 0.0)
        penalty = 0.0
        if ink_pixel_ratio < 0.002:
            penalty += 1.8
        elif ink_pixel_ratio < 0.01:
            penalty += 0.6
        if ink_bbox_ratio < 0.05:
            penalty += 0.4
        sharpness_score = min(math.log1p(max(sharpness, 0.0)) / 6.0, 0.85)
        penalty += max(0.0, 0.85 - sharpness_score)
        return penalty

    def _resolve_legacy_object_slot_target_size(
        self,
        slot: _LegacyObjectSlot,
        fallback_candidate: Optional[_LegacyObjectCandidate] = None,
    ) -> tuple[int, int]:
        for width, height in (
            (slot.preferred_width, slot.preferred_height),
            ((slot.word_picture_candidate.width if slot.word_picture_candidate else None), (slot.word_picture_candidate.height if slot.word_picture_candidate else None)),
            ((slot.best_embedded_candidate.width if slot.best_embedded_candidate else None), (slot.best_embedded_candidate.height if slot.best_embedded_candidate else None)),
            ((fallback_candidate.width if fallback_candidate else None), (fallback_candidate.height if fallback_candidate else None)),
        ):
            normalized_width = int(width or 0)
            normalized_height = int(height or 0)
            if normalized_width > 0 and normalized_height > 0:
                return normalized_width, normalized_height
        return 0, 0

    def _size_mismatch_score(
        self,
        candidate_width: Optional[int],
        candidate_height: Optional[int],
        target_width: Optional[int],
        target_height: Optional[int],
    ) -> float:
        width = int(candidate_width or 0)
        height = int(candidate_height or 0)
        target_w = int(target_width or 0)
        target_h = int(target_height or 0)
        if width <= 0 or height <= 0 or target_w <= 0 or target_h <= 0:
            return 0.0
        candidate_area = max(width * height, 1)
        target_area = max(target_w * target_h, 1)
        return (
            abs(width - target_w) / max(target_w, 1)
            + abs(height - target_h) / max(target_h, 1)
            + abs(candidate_area - target_area) / target_area
        )

    def _candidate_similarity_distance(
        self,
        first: Optional[_LegacyObjectCandidate],
        second: Optional[_LegacyObjectCandidate],
    ) -> float:
        if first is None or second is None:
            return 0.5
        first_hash = self._analyze_image_candidate(first).get("hash")
        second_hash = self._analyze_image_candidate(second).get("hash")
        if first_hash is None or second_hash is None:
            return 0.5
        return float((int(first_hash) ^ int(second_hash)).bit_count()) / 64.0

    def _analyze_image_candidate(self, candidate: _LegacyObjectCandidate) -> Dict[str, Any]:
        return self._analyze_image_path(Path(candidate.storage_url))

    def _analyze_image_path(self, image_path: Path) -> Dict[str, Any]:
        cache_key = str(image_path)
        cached = self._image_analysis_cache.get(cache_key)
        if cached is not None:
            return cached

        analysis: Dict[str, Any] = {
            "blank": False,
            "sharpness": 0.0,
            "ink_pixel_ratio": 0.0,
            "ink_bbox_ratio": 0.0,
            "hash": None,
        }
        try:
            with Image.open(image_path) as image:
                rgba = image.convert("RGBA")
                alpha = rgba.getchannel("A")
                alpha_bbox = alpha.getbbox()
                if not alpha_bbox:
                    analysis["blank"] = True
                    self._image_analysis_cache[cache_key] = analysis
                    return analysis
                if alpha_bbox != (0, 0, rgba.width, rgba.height):
                    rgba = rgba.crop(alpha_bbox)
                gray = rgba.convert("L")
                dark_mask = gray.point(lambda value: 255 if value <= 250 else 0)
                dark_bbox = dark_mask.getbbox()
                analysis["blank"] = dark_bbox is None
                if dark_bbox is not None:
                    total_area = max(gray.width * gray.height, 1)
                    bbox_area = max((dark_bbox[2] - dark_bbox[0]) * (dark_bbox[3] - dark_bbox[1]), 0)
                    analysis["ink_bbox_ratio"] = bbox_area / total_area
                    analysis["ink_pixel_ratio"] = (ImageStat.Stat(dark_mask).mean[0] or 0.0) / 255.0
                laplacian = gray.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
                analysis["sharpness"] = float(ImageStat.Stat(laplacian).var[0] or 0.0)
                analysis["hash"] = self._compute_average_hash(gray)
        except Exception:
            logger.exception("Analyze image candidate failed: path=%s", image_path)

        self._image_analysis_cache[cache_key] = analysis
        return analysis

    def _compute_average_hash(self, image: Image.Image, hash_size: int = 8) -> Optional[int]:
        try:
            resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
            thumbnail = image.resize((hash_size, hash_size), resample)
            pixels = [int(pixel) for pixel in thumbnail.getdata()]
            if not pixels:
                return None
            mean_value = sum(pixels) / len(pixels)
            bits = 0
            for pixel in pixels:
                bits = (bits << 1) | (1 if pixel >= mean_value else 0)
            return bits
        except Exception:
            return None

    def _build_legacy_object_output_node(
        self,
        slot: _LegacyObjectSlot,
        candidate: _LegacyObjectCandidate,
    ) -> Dict[str, Any]:
        return {
            "type": "image",
            "storage_url": candidate.storage_url,
            "file_hash": candidate.file_hash,
            "width": slot.preferred_width or candidate.width,
            "height": slot.preferred_height or candidate.height,
            "layout_width_px": slot.preferred_width,
            "layout_height_px": slot.preferred_height,
            "raster_width": candidate.width,
            "raster_height": candidate.height,
            "alt_text": IMAGE_PLACEHOLDER_TEXT,
            "legacy_object": copy.deepcopy(slot.selection_debug),
        }

    def _candidate_lookup_key(self, candidate: _LegacyObjectCandidate) -> str:
        return candidate.file_hash or candidate.storage_url

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        try:
            return int(str(value)) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _prepare_legacy_object_images(self) -> None:


        self._legacy_object_export_attempted = True
        export_docx_path = self._word_export_docx_path or self._source_docx_path
        if self._source_docx_path is None or export_docx_path is None:
            return
        if pythoncom is None or (DispatchEx is None and gencache is None):
            logger.warning(
                "Legacy Word object export skipped: source_path=%s export_path=%s reason=pythoncom_unavailable",
                self._source_docx_path,
                export_docx_path,
            )
            return

        if self._legacy_object_expected_count is None:
            self._legacy_object_expected_count = self._count_docx_legacy_object_slots(self._source_docx_path)

        expected_count = int(self._legacy_object_expected_count or 0)
        early_stop_enabled = self._should_enable_legacy_word_export_early_stop(expected_count)
        started_at = time.perf_counter()
        logger.info(
            "Legacy Word object export start: source_path=%s export_path=%s expected=%s embedded_covered_slots=%s embedded_full_coverage=%s early_stop_enabled=%s",
            self._source_docx_path,
            export_docx_path,
            expected_count,
            self._legacy_object_embedded_covered_slots,
            self._legacy_object_embedded_full_coverage,
            early_stop_enabled,
        )


        word_picture_images: List[Optional[_LegacyObjectImage]] = []
        try:
            word_picture_images = self._export_legacy_object_images_via_word_picture(export_docx_path)
        except Exception:
            logger.exception(
                "Failed to export legacy Word objects via word picture: source_path=%s export_path=%s",
                self._source_docx_path,
                export_docx_path,
            )

        raw_word_picture_signal_count = sum(1 for item in word_picture_images if item is not None)
        if expected_count > len(word_picture_images):
            word_picture_images.extend([None] * (expected_count - len(word_picture_images)))

        self._legacy_object_images = [
            item if self._is_usable_legacy_object_image(item) and not self._is_effectively_blank_legacy_object_image(item) else None
            for item in word_picture_images
        ]

        ready_word_picture_count = self._count_ready_legacy_object_images(self._legacy_object_images)
        missing_word_picture_count = len(self._legacy_object_images) - ready_word_picture_count

        needs_filtered_html = missing_word_picture_count > 0 or not word_picture_images
        if (
            needs_filtered_html
            and self._legacy_object_embedded_full_coverage
            and ready_word_picture_count == 0
            and raw_word_picture_signal_count == 0
        ):
            needs_filtered_html = False
            logger.info(
                "Filtered HTML export bypassed: reason=embedded_full_coverage_word_picture_empty expected=%s embedded_covered_slots=%s early_stopped=%s",
                expected_count,
                self._legacy_object_embedded_covered_slots,
                self._legacy_word_export_early_stopped,
            )

        if needs_filtered_html:
            filtered_html_images: List[_LegacyObjectImage] = []
            try:
                filtered_html_images = self._export_legacy_object_images_via_word_filtered_html(export_docx_path)
            except Exception:
                logger.exception(
                    "Failed to export legacy Word objects via filtered HTML: source_path=%s export_path=%s",
                    self._source_docx_path,
                    export_docx_path,
                )
            self._legacy_object_fallback_images = self._clean_filtered_legacy_object_images(filtered_html_images)


        logger.info(
            "Legacy Word object export done: source_path=%s export_path=%s method=per_object_fallback expected=%s word_picture_slots=%s word_picture_ready=%s word_picture_missing=%s filtered_html_candidates=%s embedded_covered_slots=%s embedded_full_coverage=%s early_stopped=%s elapsed=%s",
            self._source_docx_path,
            export_docx_path,
            expected_count,
            len(self._legacy_object_images),
            ready_word_picture_count,
            missing_word_picture_count,
            len(self._legacy_object_fallback_images),
            self._legacy_object_embedded_covered_slots,
            self._legacy_object_embedded_full_coverage,
            self._legacy_word_export_early_stopped,
            f"{time.perf_counter() - started_at:.2f}s",
        )



    def _export_legacy_object_images_via_word_picture(self, source_path: Path) -> List[Optional[_LegacyObjectImage]]:


        app = None
        document = None
        try:
            pythoncom.CoInitialize()
            app = self._create_word_application()
            time.sleep(1.5)
            app.Visible = False
            app.DisplayAlerts = 0
            app.ScreenUpdating = False
            document = self._word_call(lambda: app.Documents.Open(str(source_path), ReadOnly=True, AddToRecentFiles=False))
            time.sleep(1.5)
            word_window = self._resolve_word_window(document, app)
            self._safe_word_value(lambda: setattr(app, "ScreenUpdating", True) or True, True)

            results: List[Optional[_LegacyObjectImage]] = []
            expected_count = int(self._legacy_object_expected_count or 0)
            early_stop_enabled = self._should_enable_legacy_word_export_early_stop(expected_count)
            collect_deadline = None
            if WORD_OLE_TARGET_COLLECT_TIMEOUT_SECONDS and WORD_OLE_TARGET_COLLECT_TIMEOUT_SECONDS > 0:
                collect_deadline = time.perf_counter() + WORD_OLE_TARGET_COLLECT_TIMEOUT_SECONDS
            targets = self._collect_word_ole_export_targets(document, collect_deadline=collect_deadline)
            if expected_count > 0 and len(targets) < expected_count and collect_deadline is not None:
                logger.warning(
                    "Legacy Word object target collection incomplete: expected=%s collected=%s timeout_seconds=%s retry=no_deadline",
                    expected_count,
                    len(targets),
                    WORD_OLE_TARGET_COLLECT_TIMEOUT_SECONDS,
                )
                targets = self._collect_word_ole_export_targets(document, collect_deadline=None)
            ready_result_count = 0
            empty_probe_limit = min(len(targets), LEGACY_OBJECT_WORD_EXPORT_EMPTY_PROBE_TARGETS) if early_stop_enabled else 0
            for ordinal, target in enumerate(targets, start=1):
                exported: Optional[_LegacyObjectImage] = None
                range_obj = self._resolve_word_ole_target_range(document, target)
                if range_obj is None:
                    logger.warning(
                        "Legacy Word object picture export skipped: slot=%s kind=%s index=%s reason=missing_range_on_export",
                        ordinal,
                        target["kind"],
                        target["index"],
                    )
                    results.append(None)
                else:
                    try:
                        exported = self._export_word_range_to_legacy_object_image(
                            range_obj=range_obj,
                            ordinal=ordinal,
                            preferred_width=target["preferred_width"],
                            preferred_height=target["preferred_height"],
                            prog_id=target.get("prog_id"),
                            word_window=word_window,
                        )
                    except Exception:
                        logger.exception(
                            "Legacy Word object picture export target error: slot=%s kind=%s index=%s prog_id=%s",
                            ordinal,
                            target["kind"],
                            target["index"],
                            target.get("prog_id") or "",
                        )
                    if exported is None:
                        logger.warning(
                            "Legacy Word object picture export failed: slot=%s kind=%s index=%s prog_id=%s",
                            ordinal,
                            target["kind"],
                            target["index"],
                            target.get("prog_id") or "",
                        )
                        results.append(None)
                    else:
                        results.append(exported)
                        if self._is_usable_legacy_object_image(exported) and not self._is_effectively_blank_legacy_object_image(exported):
                            ready_result_count += 1
                if empty_probe_limit and ordinal >= empty_probe_limit and ready_result_count == 0 and ordinal < len(targets):
                    self._legacy_word_export_early_stopped = True
                    logger.warning(
                        "Legacy Word object picture export early stop: reason=empty_probe processed=%s total_targets=%s probe_limit=%s embedded_full_coverage=%s",
                        ordinal,
                        len(targets),
                        empty_probe_limit,
                        self._legacy_object_embedded_full_coverage,
                    )
                    break
            return results



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
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


    def _collect_word_ole_export_targets(self, document, collect_deadline: Optional[float] = None) -> List[Dict[str, Any]]:
        targets: List[Dict[str, Any]] = []
        expected_count = int(self._legacy_object_expected_count or 0)
        early_stop_enabled = self._should_enable_legacy_word_export_early_stop(expected_count)

        inline_shape_count = int(self._safe_word_value(lambda: document.InlineShapes.Count, 0) or 0)
        for index in range(1, inline_shape_count + 1):
            if collect_deadline is not None and time.perf_counter() >= collect_deadline:
                logger.warning("Legacy Word object target collection timeout: kind=inline scanned=%s total=%s", index - 1, inline_shape_count)
                break
            try:
                inline_shape = self._word_call(
                    lambda idx=index: document.InlineShapes(idx),
                    retries=WORD_OLE_TARGET_ENUM_RETRIES,
                    delay_seconds=WORD_OLE_TARGET_ENUM_DELAY_SECONDS,
                )
            except Exception:
                logger.warning("Legacy Word object picture export skipped: kind=inline index=%s reason=shape_access_error", index)
                continue
            ole_info = self._extract_word_ole_info(inline_shape)
            if not ole_info["is_ole"]:
                continue
            range_obj = self._safe_word_value(lambda shape=inline_shape: shape.Range)
            if range_obj is None:
                logger.warning("Legacy Word object picture export skipped: kind=inline index=%s reason=missing_range", index)
                continue
            range_start = self._safe_word_value(lambda obj=range_obj: int(obj.Start))
            targets.append(
                {
                    "kind": "inline",
                    "kind_rank": 0,
                    "index": index,
                    "range_start": int(range_start) if range_start is not None else 10**9 + len(targets),
                    "preferred_width": self._points_to_px(self._safe_word_value(lambda shape=inline_shape: shape.Width)),
                    "preferred_height": self._points_to_px(self._safe_word_value(lambda shape=inline_shape: shape.Height)),
                    "prog_id": ole_info.get("prog_id"),
                }
            )

        shape_count = int(self._safe_word_value(lambda: document.Shapes.Count, 0) or 0)
        floating_shape_access_error_streak = 0
        for index in range(1, shape_count + 1):
            if collect_deadline is not None and time.perf_counter() >= collect_deadline:
                logger.warning("Legacy Word object target collection timeout: kind=floating scanned=%s total=%s", index - 1, shape_count)
                break
            try:
                shape = self._word_call(
                    lambda idx=index: document.Shapes(idx),
                    retries=WORD_OLE_TARGET_ENUM_RETRIES,
                    delay_seconds=WORD_OLE_TARGET_ENUM_DELAY_SECONDS,
                )
            except Exception:
                floating_shape_access_error_streak += 1
                logger.warning("Legacy Word object picture export skipped: kind=floating index=%s reason=shape_access_error", index)
                if early_stop_enabled and not targets and floating_shape_access_error_streak >= LEGACY_OBJECT_WORD_EXPORT_SHAPE_ACCESS_ERROR_STREAK:
                    self._legacy_word_export_early_stopped = True
                    logger.warning(
                        "Legacy Word object target collection early stop: kind=floating scanned=%s total=%s collected=%s error_streak=%s embedded_full_coverage=%s",
                        index,
                        shape_count,
                        len(targets),
                        floating_shape_access_error_streak,
                        self._legacy_object_embedded_full_coverage,
                    )
                    break
                continue
            floating_shape_access_error_streak = 0
            ole_info = self._extract_word_ole_info(shape)
            if not ole_info["is_ole"]:
                continue
            range_obj = self._safe_word_value(lambda current_shape=shape: current_shape.Anchor)
            if range_obj is None:
                logger.warning("Legacy Word object picture export skipped: kind=floating index=%s reason=missing_anchor", index)
                continue
            range_start = self._safe_word_value(lambda obj=range_obj: int(obj.Start))
            targets.append(
                {
                    "kind": "floating",
                    "kind_rank": 1,
                    "index": index,
                    "range_start": int(range_start) if range_start is not None else 10**9 + len(targets),
                    "preferred_width": self._points_to_px(self._safe_word_value(lambda current_shape=shape: current_shape.Width)),
                    "preferred_height": self._points_to_px(self._safe_word_value(lambda current_shape=shape: current_shape.Height)),
                    "prog_id": ole_info.get("prog_id"),
                }
            )

        targets.sort(key=lambda item: (item["range_start"], item["kind_rank"], item["index"]))
        return targets


    def _resolve_word_ole_target_range(self, document, target: Dict[str, Any]):
        kind = target.get("kind")
        index = int(target.get("index") or 0)
        if index <= 0:
            return None
        if kind == "inline":
            inline_shape = self._safe_word_value(
                lambda idx=index: document.InlineShapes(idx)
            )
            if inline_shape is None:
                return None
            return self._safe_word_value(lambda shape=inline_shape: shape.Range)
        if kind == "floating":
            shape = self._safe_word_value(
                lambda idx=index: document.Shapes(idx)
            )
            if shape is None:
                return None
            return self._safe_word_value(lambda current_shape=shape: current_shape.Anchor)
        return None


    def _export_word_range_to_legacy_object_image(
        self,
        range_obj,
        ordinal: int,
        preferred_width: Optional[int],
        preferred_height: Optional[int],
        prog_id: Optional[str],
        word_window=None,
    ) -> Optional[_LegacyObjectImage]:
        emf_blob = self._variant_to_bytes(self._safe_word_value(lambda: range_obj.EnhMetaFileBits))
        if emf_blob:
            pillow_blob = self._render_legacy_emf_with_pillow(emf_blob)
            if pillow_blob:
                return self._store_legacy_object_image_blob(
                    blob=pillow_blob,
                    suffix=".png",
                    ordinal=ordinal,
                    preferred_width=preferred_width,
                    preferred_height=preferred_height,
                    method="word_enhmetafile_pillow",
                    prog_id=prog_id,
                )

        clipboard_blob, render_zoom_percentage = self._capture_word_range_png_from_clipboard(
            range_obj,
            word_window=word_window,
        )
        if clipboard_blob:
            return self._store_legacy_object_image_blob(
                blob=clipboard_blob,
                suffix=".png",
                ordinal=ordinal,
                preferred_width=preferred_width,
                preferred_height=preferred_height,
                method="word_copy_as_picture",
                prog_id=prog_id,
                render_zoom_percentage=render_zoom_percentage,
            )

        return None

    def _render_legacy_emf_with_pillow(self, emf_blob: bytes) -> Optional[bytes]:
        try:
            with Image.open(BytesIO(emf_blob)) as image:
                image.load(dpi=METAFILE_RENDER_DPI)
                raster = self._trim_raster_image(image.convert("RGBA"))
                width, height = raster.size
                if width < 300 or height < 100:
                    new_size = (int(width * 3.0), int(height * 3.0))
                    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                    raster = raster.resize(new_size, resample)
                output = BytesIO()
                raster.save(output, format="PNG")
                return output.getvalue()
        except Exception:
            return None

    def _capture_word_range_png_from_clipboard(self, range_obj, word_window=None) -> tuple[Optional[bytes], Optional[int]]:
        if ImageGrab is None:
            logger.warning("Legacy Word object clipboard export skipped: reason=imagegrab_unavailable")
            return None, None

        app = self._safe_word_value(lambda: range_obj.Application)
        if word_window is None and app is not None:
            word_window = self._safe_word_value(lambda: app.ActiveWindow)

        original_zoom = self._safe_word_value(lambda: int(word_window.View.Zoom.Percentage), 100) if word_window else 100
        try:
            if word_window is not None:
                self._safe_word_value(lambda: setattr(word_window.View.Zoom, "Percentage", 500) or True, True)
                time.sleep(0.3)
                self._safe_word_value(lambda: range_obj.Select(), True)
                time.sleep(0.2)

            self._clear_windows_clipboard()
            self._word_call(lambda: range_obj.CopyAsPicture())
            time.sleep(0.5)
            clipboard_image = ImageGrab.grabclipboard()
            if not isinstance(clipboard_image, Image.Image):
                return None, None

            trimmed = self._trim_raster_image(clipboard_image.convert("RGBA"))
            width, height = trimmed.size
            if width < 300 or height < 100:
                new_size = (int(width * 2.0), int(height * 2.0))
                resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                trimmed = trimmed.resize(new_size, resample)

            output = BytesIO()
            trimmed.save(output, format="PNG")
            return output.getvalue(), 500 if word_window is not None else None
        finally:
            if word_window is not None:
                self._safe_word_value(lambda: setattr(word_window.View.Zoom, "Percentage", original_zoom) or True, True)

    def _resolve_word_window(self, document, app):
        for candidate in (
            lambda: document.ActiveWindow,
            lambda: app.ActiveWindow,
            lambda: document.Windows(1),
        ):
            window = self._safe_word_value(candidate)
            if window is not None:
                return window
        logger.warning("Legacy Word picture export window unavailable: fallback=current_view")
        return None

    def _omath_layout_px_from_range(self, range_obj) -> tuple[Optional[int], Optional[int]]:
        """Word 中公式占位尺寸（点）→ 布局像素，用于与栅格 PNG 解耦。"""
        count = int(self._safe_word_value(lambda r=range_obj: r.InlineShapes.Count, 0) or 0)
        if count < 1:
            return None, None
        w_px = self._points_to_px(self._safe_word_value(lambda r=range_obj: r.InlineShapes(1).Width))
        h_px = self._points_to_px(self._safe_word_value(lambda r=range_obj: r.InlineShapes(1).Height))
        if w_px and h_px and w_px > 0 and h_px > 0:
            return w_px, h_px
        return None, None

    def _collect_omath_layout_hints_from_loaded_document(self, document: DocxDocument) -> List[tuple[Optional[int], Optional[int]]]:
        """与正文遍历顺序一致，从 OOXML 子树提取每个 oMath 的占位尺寸（若有 drawing 的 ext）。"""
        hints: List[tuple[Optional[int], Optional[int]]] = []
        for item in self._iter_block_items(document):
            if isinstance(item, Paragraph):
                hints.extend(self._omath_layout_hints_for_paragraph(item))
            elif isinstance(item, Table):
                hints.extend(self._omath_layout_hints_for_table(item))
        return hints

    def _omath_layout_hints_for_table(self, table: Table) -> List[tuple[Optional[int], Optional[int]]]:
        hints: List[tuple[Optional[int], Optional[int]]] = []
        for row in table.rows:
            for cell in row.cells:
                for cell_item in self._iter_block_items(cell):
                    if isinstance(cell_item, Paragraph):
                        hints.extend(self._omath_layout_hints_for_paragraph(cell_item))
                    elif isinstance(cell_item, Table):
                        hints.extend(self._omath_layout_hints_for_table(cell_item))
        return hints

    def _omath_layout_hints_for_paragraph(self, paragraph: Paragraph) -> List[tuple[Optional[int], Optional[int]]]:
        from docx.text.run import Run

        hints: List[tuple[Optional[int], Optional[int]]] = []
        p_elm = paragraph._element
        for child in p_elm.iterchildren():
            ln = self._local_name(child.tag)
            if ln == "r":
                hints.extend(self._omath_layout_hints_for_run(Run(child, paragraph), paragraph))
            elif ln == "hyperlink":
                for sub in child.iterchildren():
                    if self._local_name(sub.tag) == "r":
                        hints.extend(self._omath_layout_hints_for_run(Run(sub, paragraph), paragraph))
            elif ln in {"oMath", "oMathPara"}:
                if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
                    hints.append(self._extract_image_size(child, None, None))
            elif ln == "AlternateContent":
                hints.extend(self._omath_layout_hints_for_alternate_content(paragraph, child))
        return hints

    def _omath_layout_hints_for_run(self, run, paragraph: Paragraph) -> List[tuple[Optional[int], Optional[int]]]:
        hints: List[tuple[Optional[int], Optional[int]]] = []
        for child in run._r.iterchildren():
            local_name = self._local_name(child.tag)
            if local_name in {"oMath", "oMathPara"}:
                if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
                    hints.append(self._extract_image_size(child, None, None))
            elif local_name == "AlternateContent":
                hints.extend(self._omath_layout_hints_for_alternate_content(paragraph, child))
        return hints

    def _omath_layout_hints_for_alternate_content(self, paragraph: Paragraph, ac_el) -> List[tuple[Optional[int], Optional[int]]]:
        first_omath = None
        for el in ac_el.iter():
            ln = self._local_name(el.tag)
            if ln in {"oMath", "oMathPara"}:
                first_omath = el
                break
        if first_omath is not None:
            if QUESTION_BANK_DOCX_OMML_AS_IMAGES:
                return [self._extract_image_size(first_omath, None, None)]
            return []
        return []

    def _export_omath_images_via_word(self, source_path: Path) -> List[Optional[_LegacyObjectImage]]:
        """用 Word COM 将正文中的每个 OMath 栅格为 PNG（与 XML 遍历顺序一致，不抽取 OMML 文本）。"""
        if not source_path.exists():
            return []
        if pythoncom is None:
            logger.info("OMath Word export skipped: pythoncom unavailable")
            return []
        app = None
        document = None
        results: List[Optional[_LegacyObjectImage]] = []
        try:
            pythoncom.CoInitialize()
            app = self._create_word_application()
            time.sleep(1.0)
            app.Visible = False
            app.DisplayAlerts = 0
            app.ScreenUpdating = False
            document = self._word_call(
                lambda: app.Documents.Open(str(source_path.resolve()), ReadOnly=True, AddToRecentFiles=False)
            )
            time.sleep(1.2)
            word_window = self._resolve_word_window(document, app)
            self._safe_word_value(lambda: setattr(app, "ScreenUpdating", True) or True, True)

            main_story = self._safe_word_value(lambda: document.Content, None)
            omath_count = int(self._safe_word_value(lambda: document.OMaths.Count, 0) or 0)
            hints = getattr(self, "_omath_layout_hints", None) or []
            hint_idx = 0
            logger.info(
                "OMath Word export start: path=%s omath_count=%s body_layout_hints=%s",
                source_path.name,
                omath_count,
                len(hints),
            )
            for i in range(1, omath_count + 1):
                exported: Optional[_LegacyObjectImage] = None
                try:
                    rng_om = self._word_call(lambda idx=i: document.OMaths(idx))
                    rng = self._safe_word_value(lambda o=rng_om: o.Range, None)
                    if rng is None or main_story is None:
                        results.append(None)
                        continue
                    in_main = self._safe_word_value(lambda r=rng, m=main_story: r.InStory(m), True)
                    if not in_main:
                        results.append(None)
                        continue
                    com_lw, com_lh = self._omath_layout_px_from_range(rng)
                    xml_lw, xml_lh = (None, None)
                    if hint_idx < len(hints):
                        xml_lw, xml_lh = hints[hint_idx]
                        hint_idx += 1
                    if com_lw and com_lh and com_lw > 0 and com_lh > 0:
                        layout_w, layout_h = com_lw, com_lh
                    else:
                        layout_w, layout_h = xml_lw, xml_lh
                    exported = self._export_word_range_to_legacy_object_image(
                        range_obj=rng,
                        ordinal=40000 + i,
                        preferred_width=None,
                        preferred_height=None,
                        prog_id="OMML",
                        word_window=word_window,
                    )
                    if exported is not None and layout_w and layout_h and layout_w > 0 and layout_h > 0:
                        exported.layout_width_px = int(layout_w)
                        exported.layout_height_px = int(layout_h)
                except Exception:
                    logger.warning("OMath Word export item failed: index=%s", i, exc_info=True)
                    exported = None
                results.append(exported)
            with_layout = sum(
                1
                for x in results
                if x is not None and getattr(x, "layout_width_px", None) and getattr(x, "layout_height_px", None)
            )
            logger.info(
                "OMath Word export done: path=%s slots=%s body_hints_consumed=%s exported_with_layout_px=%s",
                source_path.name,
                len(results),
                hint_idx,
                with_layout,
            )
            if hint_idx != len(hints):
                logger.warning(
                    "OMath layout hint count mismatch: body_hints_consumed=%s body_hints_total=%s (Word 正文公式数与 OOXML 遍历数不一致时请核对文档)",
                    hint_idx,
                    len(hints),
                )
            return results
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
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def _consume_omath_render_dict(self) -> Dict[str, Any]:
        if self._omath_word_cursor >= len(self._omath_word_images):
            return self._placeholder_omath_image_dict()
        legacy = self._omath_word_images[self._omath_word_cursor]
        self._omath_word_cursor += 1
        if (
            legacy is None
            or not self._is_usable_legacy_object_image(legacy)
            or self._is_effectively_blank_legacy_object_image(legacy)
        ):
            return self._placeholder_omath_image_dict()
        a = legacy.asset
        lw = getattr(legacy, "layout_width_px", None)
        lh = getattr(legacy, "layout_height_px", None)
        rw = int(a.width or 0)
        rh = int(a.height or 0)
        norm_w, norm_h = self._normalize_formula_display_size(rw, rh)
        if lw and lh and lw > 0 and lh > 0:
            box_w, box_h = lw, lh
        else:
            box_w, box_h = norm_w, norm_h
        return {
            "type": "image",
            "storage_url": a.storage_url,
            "file_hash": a.file_hash,
            "width": box_w,
            "height": box_h,
            "layout_width_px": lw if lw and lh and lw > 0 and lh > 0 else None,
            "layout_height_px": lh if lw and lh and lw > 0 and lh > 0 else None,
            "raster_width": rw or None,
            "raster_height": rh or None,
            "alt_text": "公式图片",
            "omml_raster": True,
        }

    _OMATH_RENDER_SCALE = 6

    def _normalize_formula_display_size(self, width: Optional[int], height: Optional[int]) -> tuple[int, int]:
        w = int(width or 0)
        h = int(height or 0)
        if w <= 0 or h <= 0:
            return (72, 28)
        w = max(8, int(round(w / self._OMATH_RENDER_SCALE)))
        h = max(8, int(round(h / self._OMATH_RENDER_SCALE)))
        max_w, max_h, min_h = 420, 300, 14
        if w > max_w:
            ratio = max_w / w
            w = max_w
            h = max(min_h, int(round(h * ratio)))
        if h > max_h:
            ratio = max_h / h
            h = max_h
            w = max(min_h, int(round(w * ratio)))
        if h < min_h:
            ratio = min_h / max(h, 1)
            h = min_h
            w = int(round(w * ratio))
        return (max(8, w), max(8, h))

    def _is_bad_omath_image(self, image: _LegacyObjectImage) -> bool:
        analysis = self._analyze_image_path(Path(image.asset.storage_url))
        w = int(image.asset.width or image.width or 0)
        h = int(image.asset.height or image.height or 0)
        if w <= 0 or h <= 0:
            return True
        # Reject likely clipboard garbage strips / giant black bars.
        if w > 2000 or h > 600:
            return True
        if w / max(h, 1) > 12:
            return True
        ink_ratio = float(analysis.get("ink_pixel_ratio") or 0.0)
        if ink_ratio > 0.9:
            return True
        return False

    def _placeholder_omath_image_dict(self) -> Dict[str, Any]:
        if self._omath_placeholder_render is not None:
            return self._omath_placeholder_render
        path = (self.output_dir / "docx_omath_placeholder.png").resolve()
        if not path.exists():
            im = Image.new("RGBA", (96, 36), (248, 248, 252, 255))
            bio = BytesIO()
            im.save(bio, format="PNG")
            path.write_bytes(bio.getvalue())
        blob = path.read_bytes()
        w, h = self._get_image_dimensions(blob)
        fh = hashlib.sha256(blob).hexdigest()
        self._omath_placeholder_render = {
            "type": "image",
            "storage_url": str(path),
            "file_hash": fh,
            "width": w or 96,
            "height": h or 36,
            "layout_width_px": None,
            "layout_height_px": None,
            "raster_width": w or 96,
            "raster_height": h or 36,
            "alt_text": "公式图片",
            "omml_raster": True,
        }
        return self._omath_placeholder_render


    def _store_legacy_object_image_blob(

        self,
        blob: bytes,
        suffix: str,
        ordinal: int,
        preferred_width: Optional[int],
        preferred_height: Optional[int],
        method: str,
        prog_id: Optional[str],
        render_zoom_percentage: Optional[int] = None,
    ) -> _LegacyObjectImage:
        file_hash = hashlib.sha256(blob).hexdigest()
        target_path = self.output_dir / f"word_object_{ordinal:04d}_{file_hash[:12]}{suffix}"
        if not target_path.exists():
            target_path.write_bytes(blob)
        width, height = self._get_image_dimensions(blob)
        asset = _RichImageAsset(
            storage_url=str(target_path),
            file_hash=file_hash,
            width=width,
            height=height,
        )
        output_width = preferred_width or width
        output_height = preferred_height or height
        logger.info(
            "Legacy object image exported: index=%s method=%s prog_id=%s preferred_size=%sx%s output_size=%sx%s raster_size=%sx%s copy_zoom=%s bytes=%s",
            ordinal,
            method,
            prog_id or "",
            preferred_width or 0,
            preferred_height or 0,
            output_width or 0,
            output_height or 0,
            width or 0,
            height or 0,
            render_zoom_percentage or 0,
            len(blob),
        )
        return _LegacyObjectImage(
            asset=asset,
            width=output_width,
            height=output_height,
            source=LEGACY_OBJECT_SOURCE_WORD_PICTURE,
            ordinal=ordinal,
            layout_width_px=None,
            layout_height_px=None,
        )



    def _extract_word_ole_info(self, shape_obj) -> Dict[str, Any]:
        prog_id = self._safe_word_value(lambda: shape_obj.OLEFormat.ProgID)
        class_type = self._safe_word_value(lambda: shape_obj.OLEFormat.ClassType)
        normalized_prog_id = str(prog_id).strip() if prog_id not in (None, "") else None
        normalized_class_type = str(class_type).strip() if class_type not in (None, "") else None
        return {
            "is_ole": bool(normalized_prog_id or normalized_class_type),
            "prog_id": normalized_prog_id,
            "class_type": normalized_class_type,
        }

    def _safe_word_value(self, func, default=None):
        try:
            return self._word_call(func, retries=6, delay_seconds=0.3)
        except Exception:
            return default

    def _is_near_white(self, image_path: Path, threshold: int) -> bool:
        try:
            with Image.open(image_path) as image:
                rgba = image.convert("RGBA")
                alpha = rgba.getchannel("A")
                alpha_bbox = alpha.getbbox()
                if not alpha_bbox:
                    return True
                if alpha_bbox != (0, 0, rgba.width, rgba.height):
                    rgba = rgba.crop(alpha_bbox)
                gray = rgba.convert("L")
                mask = gray.point(lambda value: 255 if value <= threshold else 0)
                return mask.getbbox() is None
        except Exception:
            return False


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

    def _clear_windows_clipboard(self) -> None:
        if win32clipboard is None:
            return
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
        except Exception:
            return
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    def _points_to_px(self, value: Any) -> Optional[int]:
        try:
            return int(round(float(value) * 96 / 72))
        except (TypeError, ValueError):
            return None

    def _normalize_legacy_object_blob(

        self,
        blob: bytes,
        suffix: str,
        target_width: Optional[int],
        target_height: Optional[int],
    ) -> tuple[bytes, str, Optional[tuple[int, int]]]:
        normalized_suffix = (suffix or "").lower()
        if normalized_suffix != ".gif":
            return blob, suffix or ".png", None

        try:
            with Image.open(BytesIO(blob)) as image:
                image = image.convert("RGBA")
                output_size: Optional[tuple[int, int]] = None
                desired_width = target_width or 0
                desired_height = target_height or 0
                if desired_width > 0 and desired_height > 0 and METAFILE_RENDER_TARGET_SCALE > 1:
                    desired_width = int(round(desired_width * METAFILE_RENDER_TARGET_SCALE))
                    desired_height = int(round(desired_height * METAFILE_RENDER_TARGET_SCALE))
                if desired_width > 0 and desired_height > 0:
                    if METAFILE_RENDER_MAX_PIXELS and desired_width * desired_height > METAFILE_RENDER_MAX_PIXELS:
                        scale = math.sqrt(METAFILE_RENDER_MAX_PIXELS / float(desired_width * desired_height))
                        desired_width = max(1, int(round(desired_width * scale)))
                        desired_height = max(1, int(round(desired_height * scale)))
                    if desired_width > image.width or desired_height > image.height:
                        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                        image = image.resize((desired_width, desired_height), resample)
                    output_size = (desired_width, desired_height)
                output = BytesIO()
                image.save(output, format="PNG")
            return output.getvalue(), ".png", output_size
        except Exception:
            return blob, suffix or ".png", None


    def _export_legacy_object_images_via_word_filtered_html(self, source_path: Path) -> List[_LegacyObjectImage]:

        temp_dir = Path(tempfile.mkdtemp(prefix="qb_word_html_"))
        html_path = temp_dir / f"{source_path.stem}.html"
        html_files_dir = temp_dir / f"{source_path.stem}.files"
        app = None
        document = None
        try:
            pythoncom.CoInitialize()
            app = self._create_word_application()
            time.sleep(2.0)
            app.Visible = False
            app.DisplayAlerts = 0
            app.ScreenUpdating = False
            document = self._word_call(lambda: app.Documents.Open(str(source_path), ReadOnly=True, AddToRecentFiles=False))
            time.sleep(2.5)
            self._word_call(lambda: document.SaveAs2(str(html_path), FileFormat=10))

            if not html_files_dir.exists():
                html_files_dir = temp_dir / f"{source_path.stem}_files"
            if not html_path.exists() or not html_files_dir.exists():
                return []

            parser = _FilteredHtmlImageParser()
            parser.feed(html_path.read_text(encoding="gb2312", errors="ignore"))
            results: List[_LegacyObjectImage] = []
            for index, image_info in enumerate(parser.images, start=1):
                src = str(image_info.get("src") or "")
                if Path(src).suffix.lower() != ".gif":
                    continue
                exported_path = html_files_dir / Path(src).name
                if not exported_path.exists():
                    continue
                blob = exported_path.read_bytes()
                preferred_width = image_info.get("width")
                preferred_height = image_info.get("height")
                normalized_blob, normalized_suffix, normalized_size = self._normalize_legacy_object_blob(
                    blob,
                    exported_path.suffix.lower(),
                    preferred_width,
                    preferred_height,
                )
                file_hash = hashlib.sha256(normalized_blob).hexdigest()
                target_path = self.output_dir / f"word_object_{index:04d}_{file_hash[:12]}{normalized_suffix}"
                if not target_path.exists():
                    target_path.write_bytes(normalized_blob)
                width, height = self._get_image_dimensions(normalized_blob)
                asset = _RichImageAsset(
                    storage_url=str(target_path),
                    file_hash=file_hash,
                    width=width,
                    height=height,
                )
                output_width = preferred_width or (normalized_size[0] if normalized_size else width)
                output_height = preferred_height or (normalized_size[1] if normalized_size else height)
                logger.info(
                    "Legacy object image exported: index=%s src=%s normalized_suffix=%s preferred_size=%sx%s output_size=%sx%s bytes=%s",
                    index,
                    src,
                    normalized_suffix,
                    preferred_width or 0,
                    preferred_height or 0,
                    output_width or 0,
                    output_height or 0,
                    len(normalized_blob),
                )
                results.append(
                    _LegacyObjectImage(
                        asset=asset,
                        width=output_width,
                        height=output_height,
                        source=LEGACY_OBJECT_SOURCE_FILTERED_HTML,
                        ordinal=index,
                        layout_width_px=preferred_width,
                        layout_height_px=preferred_height,
                    )
                )



            return results
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
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _create_word_application(self):
        last_error = None
        factories = []
        if gencache is not None:
            factories.append(lambda: gencache.EnsureDispatch("Word.Application"))
        if DispatchEx is not None:
            factories.append(lambda: DispatchEx("Word.Application"))
        for factory in factories:
            try:
                return factory()
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError("Word COM is unavailable")

    def _word_call(self, func, retries: int = 30, delay_seconds: float = 1.0):

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
                time.sleep(delay_seconds)
        raise last_error

    def _extract_image_rel_ids(self, element) -> List[str]:


        rel_ids: List[str] = []
        for blip in element.findall(".//a:blip", DOCX_NS):
            rel_id = blip.get(qn("r:embed")) or blip.get(f"{{{DOCX_NS['r']}}}embed")
            if rel_id:
                rel_ids.append(rel_id)
        for image_data in element.findall(".//v:imagedata", DOCX_NS):
            rel_id = image_data.get(qn("r:id")) or image_data.get(f"{{{DOCX_NS['r']}}}id")
            if rel_id:
                rel_ids.append(rel_id)
        return list(dict.fromkeys(rel_ids))


    def _export_image_part(self, image_part, preferred_size: Optional[tuple[Optional[int], Optional[int]]] = None) -> _RichImageAsset:
        original_blob = image_part.blob
        original_suffix = Path(image_part.partname).suffix or ".png"
        blob, suffix = self._normalize_image_blob(original_blob, original_suffix, preferred_size)

        file_hash = hashlib.sha256(blob).hexdigest()
        cached = self._image_cache.get(file_hash)
        if cached:
            return cached

        storage_path = self.output_dir / f"docx_inline_{file_hash[:12]}{suffix}"
        if not storage_path.exists():
            storage_path.write_bytes(blob)
        width, height = self._get_image_dimensions(blob)
        asset = _RichImageAsset(
            storage_url=str(storage_path),
            file_hash=file_hash,
            width=width,
            height=height,
        )
        self._image_cache[file_hash] = asset
        return asset

    def _normalize_image_blob(
        self,
        blob: bytes,
        suffix: str,
        preferred_size: Optional[tuple[Optional[int], Optional[int]]] = None,
    ) -> tuple[bytes, str]:
        normalized_suffix = (suffix or "").lower()
        if normalized_suffix not in {".wmf", ".emf"}:
            return blob, suffix or ".png"

        self._metafile_total += 1
        metafile_index = self._metafile_total
        started_at = time.perf_counter()
        preferred_width = (preferred_size or (None, None))[0]
        preferred_height = (preferred_size or (None, None))[1]
        logger.info(
            "Metafile convert request: index=%s suffix=%s size_bytes=%s preferred_size=%sx%s",
            metafile_index,
            normalized_suffix,
            len(blob),
            preferred_width or 0,
            preferred_height or 0,
        )

        pillow_blob = self._convert_metafile_with_pillow(blob, preferred_size)

        if pillow_blob:
            elapsed = time.perf_counter() - started_at
            self._metafile_pillow_success += 1
            if elapsed >= METAFILE_SLOW_LOG_SECONDS:
                self._metafile_slow += 1
                logger.warning(
                    "Metafile convert slow: index=%s method=pillow elapsed=%s",
                    metafile_index,
                    f"{elapsed:.2f}s",
                )
            logger.info(
                "Metafile convert done: index=%s method=pillow elapsed=%s output_bytes=%s",
                metafile_index,
                f"{elapsed:.2f}s",
                len(pillow_blob),
            )
            return pillow_blob, ".png"

        libreoffice_blob = self._convert_metafile_with_libreoffice(blob, normalized_suffix)
        if libreoffice_blob:
            elapsed = time.perf_counter() - started_at
            self._metafile_libreoffice_success += 1
            if elapsed >= METAFILE_SLOW_LOG_SECONDS:
                self._metafile_slow += 1
                logger.warning(
                    "Metafile convert slow: index=%s method=libreoffice elapsed=%s",
                    metafile_index,
                    f"{elapsed:.2f}s",
                )
            logger.info(
                "Metafile convert done: index=%s method=libreoffice elapsed=%s output_bytes=%s",
                metafile_index,
                f"{elapsed:.2f}s",
                len(libreoffice_blob),
            )
            return libreoffice_blob, ".png"

        elapsed = time.perf_counter() - started_at
        self._metafile_fail += 1
        logger.warning(
            "Metafile convert failed: index=%s suffix=%s elapsed=%s",
            metafile_index,
            normalized_suffix,
            f"{elapsed:.2f}s",
        )
        return blob, suffix or ".png"


    def _convert_metafile_with_libreoffice(self, blob: bytes, suffix: str) -> Optional[bytes]:
        soffice_path = self._resolve_soffice_path()
        if not soffice_path:
            logger.warning("Metafile libreoffice convert skipped: reason=soffice_not_found")
            return None
        started_at = time.perf_counter()
        logger.info(
            "Metafile libreoffice convert start: suffix=%s size_bytes=%s soffice=%s",
            suffix,
            len(blob),
            soffice_path,
        )
        try:
            with tempfile.TemporaryDirectory(prefix="qb_metafile_") as temp_dir:
                temp_path = Path(temp_dir)
                source_path = temp_path / f"source{suffix}"
                output_path = temp_path / "source.png"
                source_path.write_bytes(blob)
                completed = subprocess.run(
                    [
                        soffice_path,
                        "--headless",
                        "--convert-to",
                        "png",
                        "--outdir",
                        str(temp_path),
                        str(source_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if completed.returncode != 0 and not output_path.exists():
                    logger.warning(
                        "Metafile libreoffice convert failed: returncode=%s elapsed=%s stdout_tail=%s stderr_tail=%s",
                        completed.returncode,
                        f"{time.perf_counter() - started_at:.2f}s",
                        (completed.stdout or "")[-300:],
                        (completed.stderr or "")[-300:],
                    )
                    return None
                if not output_path.exists():
                    matches = list(temp_path.glob("*.png"))
                    if not matches:
                        logger.warning(
                            "Metafile libreoffice convert failed: output_missing elapsed=%s",
                            f"{time.perf_counter() - started_at:.2f}s",
                        )
                        return None
                    output_path = matches[0]
                converted_blob = self._trim_png_blob(output_path.read_bytes())
                width, height = self._get_image_dimensions(converted_blob)
                logger.info(
                    "Metafile libreoffice convert done: elapsed=%s output_bytes=%s size=%sx%s",
                    f"{time.perf_counter() - started_at:.2f}s",
                    len(converted_blob),
                    width or 0,
                    height or 0,
                )
                return converted_blob
        except Exception:
            logger.exception("Metafile libreoffice convert error: suffix=%s", suffix)
            return None


    def _resolve_soffice_path(self) -> Optional[str]:
        return shutil.which("soffice.com") or shutil.which("soffice")

    def _convert_metafile_with_pillow(
        self,
        blob: bytes,
        preferred_size: Optional[tuple[Optional[int], Optional[int]]] = None,
    ) -> Optional[bytes]:
        started_at = time.perf_counter()
        try:
            render_dpi = METAFILE_RENDER_DPI
            if METAFILE_RENDER_SUPERSAMPLE and METAFILE_RENDER_SUPERSAMPLE > 1:
                render_dpi = int(round(METAFILE_RENDER_DPI * METAFILE_RENDER_SUPERSAMPLE))

            with Image.open(BytesIO(blob)) as image:
                image.load(dpi=render_dpi)
                image = image.convert("RGBA")
                image = self._trim_raster_image(image)
                base_width, base_height = image.width, image.height
                preferred_width = (preferred_size or (None, None))[0] or 0
                preferred_height = (preferred_size or (None, None))[1] or 0
                target_width, target_height = base_width, base_height

                if preferred_width > 0 and preferred_height > 0 and METAFILE_RENDER_TARGET_SCALE > 1:
                    scaled_width = int(round(preferred_width * METAFILE_RENDER_TARGET_SCALE))
                    scaled_height = int(round(preferred_height * METAFILE_RENDER_TARGET_SCALE))
                    if scaled_width > target_width or scaled_height > target_height:
                        target_width = max(target_width, scaled_width)
                        target_height = max(target_height, scaled_height)
                        logger.info(
                            "Metafile pillow upscale: from=%sx%s to=%sx%s preferred=%sx%s scale=%s",
                            base_width,
                            base_height,
                            target_width,
                            target_height,
                            preferred_width,
                            preferred_height,
                            METAFILE_RENDER_TARGET_SCALE,
                        )

                if METAFILE_RENDER_MAX_PIXELS and target_width * target_height > METAFILE_RENDER_MAX_PIXELS:
                    scale = math.sqrt(METAFILE_RENDER_MAX_PIXELS / float(target_width * target_height))
                    target_width = max(1, int(round(target_width * scale)))
                    target_height = max(1, int(round(target_height * scale)))
                    logger.info(
                        "Metafile pillow downscale: from=%sx%s to=%sx%s limit_pixels=%s",
                        base_width,
                        base_height,
                        target_width,
                        target_height,
                        METAFILE_RENDER_MAX_PIXELS,
                    )

                if target_width != base_width or target_height != base_height:
                    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
                    if target_width < base_width or target_height < base_height:
                        logger.info(
                            "Metafile pillow supersample downscale: from=%sx%s to=%sx%s render_dpi=%s",
                            base_width,
                            base_height,
                            target_width,
                            target_height,
                            render_dpi,
                        )
                    image = image.resize((target_width, target_height), resample)

                output = BytesIO()
                image.save(output, format="PNG")
            converted_blob = output.getvalue()
            logger.info(
                "Metafile pillow convert done: dpi=%s size=%sx%s output_bytes=%s elapsed=%s",
                render_dpi,
                image.width,
                image.height,
                len(converted_blob),
                f"{time.perf_counter() - started_at:.2f}s",
            )
            return converted_blob
        except Exception:
            logger.exception("Metafile pillow convert error")
            return None





    def _trim_png_blob(self, blob: bytes) -> bytes:
        try:
            with Image.open(BytesIO(blob)) as image:
                trimmed = self._trim_raster_image(image.convert("RGBA"))
                output = BytesIO()
                trimmed.save(output, format="PNG")
            return output.getvalue()
        except Exception:
            return blob

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


    def _build_paragraph_style(self, paragraph: Paragraph) -> Dict[str, Any]:

        style: Dict[str, Any] = {}
        try:
            paragraph_alignment = paragraph.alignment
        except Exception:
            paragraph_alignment = None
        alignment = ALIGNMENT_MAP.get(paragraph_alignment)
        if alignment:
            style["text_align"] = alignment
        paragraph_format = paragraph.paragraph_format

        if paragraph_format.first_line_indent is not None:
            style["first_line_indent_pt"] = round(paragraph_format.first_line_indent.pt, 2)
        if paragraph_format.left_indent is not None:
            style["left_indent_pt"] = round(paragraph_format.left_indent.pt, 2)
        if paragraph_format.right_indent is not None:
            style["right_indent_pt"] = round(paragraph_format.right_indent.pt, 2)
        if paragraph_format.space_before is not None:
            style["space_before_pt"] = round(paragraph_format.space_before.pt, 2)
        if paragraph_format.space_after is not None:
            style["space_after_pt"] = round(paragraph_format.space_after.pt, 2)
        if paragraph_format.line_spacing is not None and isinstance(paragraph_format.line_spacing, (int, float)):
            style["line_spacing"] = paragraph_format.line_spacing
        return style

    def _build_run_marks(self, run) -> Dict[str, Any]:
        marks: Dict[str, Any] = {}
        if run.bold:
            marks["bold"] = True
        if run.italic:
            marks["italic"] = True
        if run.underline:
            marks["underline"] = True
        if getattr(run.font, "subscript", False):
            marks["subscript"] = True
        if getattr(run.font, "superscript", False):
            marks["superscript"] = True
        if run.font.size is not None:
            marks["font_size_pt"] = round(run.font.size.pt, 2)
        return marks

    def _split_paragraph_render(self, paragraph_render: Dict[str, Any]) -> List[Dict[str, Any]]:
        base_style = paragraph_render.get("style") or {}
        groups: List[List[Dict[str, Any]]] = [[]]
        for child in paragraph_render.get("children") or []:
            if child.get("type") == "line_break":
                if groups[-1]:
                    groups.append([])
                continue
            groups[-1].append(child)

        blocks: List[Dict[str, Any]] = []
        for group in groups:
            if not group:
                continue
            blocks.append({"type": "paragraph", "style": dict(base_style), "children": group})
        if not blocks:
            return [{"type": "paragraph", "style": dict(base_style), "children": []}]
        return blocks

    def _merge_adjacent_text_nodes(self, children: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        for child in children:
            if child.get("type") != "text":
                merged.append(child)
                continue
            if merged and merged[-1].get("type") == "text" and merged[-1].get("marks") == child.get("marks"):
                merged[-1]["text"] = f"{merged[-1].get('text', '')}{child.get('text', '')}"
            else:
                merged.append(child)
        return merged

    def _render_to_text(self, render: Dict[str, Any]) -> str:
        node_type = render.get("type")
        if node_type == "paragraph":
            return "".join(self._inline_node_to_text(child) for child in render.get("children") or []).strip()
        if node_type == "table":
            row_texts: List[str] = []
            for row in render.get("rows") or []:
                cell_texts: List[str] = []
                for cell in row.get("cells") or []:
                    cell_blocks = cell.get("blocks") or []
                    cell_text = "\n".join(filter(None, (self._render_to_text(block) for block in cell_blocks))).strip()
                    if cell_text:
                        cell_texts.append(cell_text)
                if cell_texts:
                    row_texts.append(" | ".join(cell_texts))
            return "\n".join(row_texts).strip()
        return ""

    _FORMULA_ALT_TEXTS = frozenset({"公式", "公式图片", "[公式]", "formula"})

    def _inline_node_to_text(self, node: Dict[str, Any]) -> str:
        node_type = node.get("type")
        if node_type == "text":
            return str(node.get("text") or "")
        if node_type == "formula":
            return str(node.get("text") or "")
        if node_type == "image":
            if node.get("omml_raster"):
                return ""
            alt = str(node.get("alt_text") or "")
            if alt in self._FORMULA_ALT_TEXTS:
                return ""
            return alt or IMAGE_PLACEHOLDER_TEXT
        if node_type == "line_break":
            return "\n"
        return ""

    def _extract_formula_text(self, element) -> str:
        parts: List[str] = []
        for descendant in element.iter():
            ln = self._local_name(descendant.tag)
            if ln == "t":
                if descendant.text:
                    parts.append(descendant.text)
                if getattr(descendant, "tail", None):
                    parts.append(descendant.tail or "")
            elif ln == "chr":
                val = descendant.get("val")
                if val:
                    parts.append(str(val))
                else:
                    for _k, v in (descendant.attrib or {}).items():
                        if str(_k).endswith("}val") or _k == "val":
                            parts.append(str(v))
                            break
        joined = "".join(parts).strip()
        if joined:
            return joined
        try:
            return "".join(t for t in element.itertext() if t).strip()
        except Exception:
            return ""

    def _extract_image_size(self, element, fallback_width: Optional[int], fallback_height: Optional[int]) -> tuple[Optional[int], Optional[int]]:
        for ext in element.findall(".//a:ext", DOCX_NS):
            cx = ext.get("cx")
            cy = ext.get("cy")
            if cx and cy:
                return self._emu_to_px(cx), self._emu_to_px(cy)
        for extent in element.findall(".//wp:extent", DOCX_NS):
            cx = extent.get("cx")
            cy = extent.get("cy")
            if cx and cy:
                return self._emu_to_px(cx), self._emu_to_px(cy)
        for shape in element.findall(".//v:shape", DOCX_NS):
            width, height = self._extract_vml_shape_size(shape.get("style") or "")
            if width or height:
                return width or fallback_width, height or fallback_height
        return fallback_width, fallback_height

    def _extract_vml_shape_size(self, style: str) -> tuple[Optional[int], Optional[int]]:
        return self._css_length_to_px(style, "width"), self._css_length_to_px(style, "height")

    def _css_length_to_px(self, style: str, key: str) -> Optional[int]:
        match = re.search(rf"(?:^|;)\s*{key}\s*:\s*(?P<value>[0-9.]+)\s*(?P<unit>pt|px|in|cm|mm)?", style or "", re.IGNORECASE)
        if not match:
            return None
        value = float(match.group("value"))
        unit = (match.group("unit") or "px").lower()
        factors = {"px": 1, "pt": 96 / 72, "in": 96, "cm": 96 / 2.54, "mm": 96 / 25.4}
        factor = factors.get(unit)
        return int(round(value * factor)) if factor else None

    def _emu_to_px(self, value: Any) -> Optional[int]:

        try:
            return int(round(int(value) / 9525))
        except (TypeError, ValueError):
            return None

    def _get_image_dimensions(self, blob: bytes) -> tuple[Optional[int], Optional[int]]:
        try:
            with Image.open(BytesIO(blob)) as image:
                return image.width, image.height
        except Exception:
            return None, None

    def _local_name(self, tag: str) -> str:
        return str(tag).split("}", 1)[-1]


def extract_docx_blocks(path: Path, output_dir: Path, word_export_docx_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    extractor = DocxRichContentExtractor(output_dir)
    return [{"text": block.text, "render": block.render} for block in extractor.extract(path, word_export_path=word_export_docx_path)]

