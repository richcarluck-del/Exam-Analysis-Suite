import logging
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zipfile

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

try:
    import pythoncom
    from win32com.client import DispatchEx, gencache
except Exception:
    pythoncom = None
    DispatchEx = None
    gencache = None


logger = logging.getLogger(__name__)

WORD_SAVE_AS_DOCX = 16
WORD_WRAP_BEHIND_TEXT = 5
VALID_SANITIZE_MODES = {"conservative", "aggressive"}
VALID_SANITIZE_BACKENDS = {"auto", "word", "xml"}
WATERMARK_KEYWORDS = (
    "watermark",
    "水印",
    "高考资源网",
    "学科网",
    "组卷网",
    "21世纪教育",
    "菁优网",
    "金太阳",
    "中学学科网",
)
DOCX_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
PACKAGE_REL_NS = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass
class DocxSanitizationResult:
    output_path: Path
    enabled: bool
    applied: bool
    mode: str
    backend: str
    removed_total: int = 0
    removed_body_shapes: int = 0
    removed_header_shapes: int = 0
    removed_footer_shapes: int = 0
    removed_header_inline_shapes: int = 0
    removed_footer_inline_shapes: int = 0
    removed_xml_nodes: int = 0
    reason_counts: Dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None


class DocxSanitizer:
    def __init__(
        self,
        enabled: bool = False,
        mode: str = "conservative",
        backend: str = "auto",
    ) -> None:
        self.enabled = bool(enabled)
        normalized_mode = str(mode or "conservative").strip().lower()
        self.mode = normalized_mode if normalized_mode in VALID_SANITIZE_MODES else "conservative"
        normalized_backend = str(backend or "auto").strip().lower()
        self.backend = normalized_backend if normalized_backend in VALID_SANITIZE_BACKENDS else "auto"

    def sanitize(self, source_path: Path, output_path: Path) -> DocxSanitizationResult:
        source_path = Path(source_path)
        output_path = Path(output_path)
        if not self.enabled:
            return DocxSanitizationResult(
                output_path=source_path,
                enabled=False,
                applied=False,
                mode=self.mode,
                backend="disabled",
            )

        logger.info(
            "Docx sanitize start: source_path=%s output_path=%s mode=%s backend=%s",
            source_path,
            output_path,
            self.mode,
            self.backend,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        backend_order = [self.backend] if self.backend != "auto" else ["word", "xml"]
        last_error: Optional[str] = None
        for backend in backend_order:
            try:
                if backend == "word":
                    return self._sanitize_with_word(source_path, output_path)
                if backend == "xml":
                    return self._sanitize_with_xml(source_path, output_path)
            except Exception as exc:
                last_error = str(exc)
                logger.exception(
                    "Docx sanitize backend failed: source_path=%s output_path=%s mode=%s backend=%s",
                    source_path,
                    output_path,
                    self.mode,
                    backend,
                )

        logger.warning(
            "Docx sanitize skipped after backend failures: source_path=%s output_path=%s mode=%s backend=%s error=%s",
            source_path,
            output_path,
            self.mode,
            self.backend,
            last_error,
        )
        return DocxSanitizationResult(
            output_path=source_path,
            enabled=True,
            applied=False,
            mode=self.mode,
            backend="failed_open",
            error=last_error,
        )

    def _sanitize_with_word(self, source_path: Path, output_path: Path) -> DocxSanitizationResult:
        if pythoncom is None or (DispatchEx is None and gencache is None):
            raise RuntimeError("pythoncom 或 Word COM 不可用")

        shutil.copy2(source_path, output_path)
        app = None
        document = None
        started_at = time.perf_counter()
        result = DocxSanitizationResult(
            output_path=output_path,
            enabled=True,
            applied=True,
            mode=self.mode,
            backend="word",
        )
        try:
            pythoncom.CoInitialize()
            app = self._create_word_application()
            app.Visible = False
            app.DisplayAlerts = 0
            app.ScreenUpdating = False
            document = self._word_call(lambda: app.Documents.Open(str(output_path), ReadOnly=False, AddToRecentFiles=False))
            time.sleep(0.6)

            self._remove_main_document_shapes(document, result)
            self._remove_header_footer_shapes(document, result)
            self._word_call(lambda: document.Save())
            logger.info(
                "Docx sanitize via Word done: source_path=%s output_path=%s mode=%s removed_total=%s reasons=%s elapsed=%s",
                source_path,
                output_path,
                self.mode,
                result.removed_total,
                result.reason_counts,
                f"{time.perf_counter() - started_at:.2f}s",
            )
            return result
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
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

    def _remove_main_document_shapes(self, document, result: DocxSanitizationResult) -> None:
        shape_count = int(self._safe_word_value(lambda: document.Shapes.Count, 0) or 0)
        for index in range(shape_count, 0, -1):
            shape = self._safe_word_value(lambda index=index: document.Shapes(index))
            if shape is None:
                continue
            reason = self._decide_body_shape_removal_reason(shape)
            if not reason:
                continue
            self._log_word_removal(scope="body", shape_kind="floating", index=index, reason=reason, shape=shape)
            self._word_call(lambda current_shape=shape: current_shape.Delete(), retries=12, delay_seconds=0.2)
            result.removed_total += 1
            result.removed_body_shapes += 1
            result.reason_counts[reason] = result.reason_counts.get(reason, 0) + 1


    def _remove_header_footer_shapes(self, document, result: DocxSanitizationResult) -> None:
        section_count = int(self._safe_word_value(lambda: document.Sections.Count, 0) or 0)
        for section_index in range(1, section_count + 1):
            section = self._safe_word_value(lambda section_index=section_index: document.Sections(section_index))
            if section is None:
                continue
            self._remove_header_footer_collection(section, "header", result)
            self._remove_header_footer_collection(section, "footer", result)

    def _remove_header_footer_collection(self, section, part_name: str, result: DocxSanitizationResult) -> None:
        collection = self._safe_word_value(lambda: section.Headers if part_name == "header" else section.Footers)
        if collection is None:
            return
        item_count = int(self._safe_word_value(lambda: collection.Count, 0) or 0)
        for item_index in range(1, item_count + 1):
            part = self._safe_word_value(lambda item_index=item_index: collection(item_index))
            if part is None:
                continue
            if self._safe_word_value(lambda part=part: part.Exists, True) is False:
                continue
            self._remove_shape_collection(part, part_name, result)
            self._remove_inline_shape_collection(part, part_name, result)

    def _remove_shape_collection(self, part, part_name: str, result: DocxSanitizationResult) -> None:
        shape_count = int(self._safe_word_value(lambda: part.Shapes.Count, 0) or 0)
        for index in range(shape_count, 0, -1):
            shape = self._safe_word_value(lambda index=index: part.Shapes(index))
            if shape is None:
                continue
            reason = f"{part_name}_floating"
            self._log_word_removal(scope=part_name, shape_kind="floating", index=index, reason=reason, shape=shape)
            self._word_call(lambda current_shape=shape: current_shape.Delete(), retries=12, delay_seconds=0.2)
            result.removed_total += 1
            if part_name == "header":
                result.removed_header_shapes += 1
            else:
                result.removed_footer_shapes += 1
            result.reason_counts[reason] = result.reason_counts.get(reason, 0) + 1


    def _remove_inline_shape_collection(self, part, part_name: str, result: DocxSanitizationResult) -> None:
        inline_count = int(self._safe_word_value(lambda: part.Range.InlineShapes.Count, 0) or 0)
        for index in range(inline_count, 0, -1):
            inline_shape = self._safe_word_value(lambda index=index: part.Range.InlineShapes(index))
            if inline_shape is None:
                continue
            reason = f"{part_name}_inline"
            self._log_word_removal(scope=part_name, shape_kind="inline", index=index, reason=reason, shape=inline_shape)
            self._word_call(lambda current_shape=inline_shape: current_shape.Delete(), retries=12, delay_seconds=0.2)
            result.removed_total += 1
            if part_name == "header":
                result.removed_header_inline_shapes += 1
            else:
                result.removed_footer_inline_shapes += 1
            result.reason_counts[reason] = result.reason_counts.get(reason, 0) + 1


    def _decide_body_shape_removal_reason(self, shape) -> Optional[str]:
        if self.mode == "aggressive":
            return "body_floating_aggressive"
        if self._shape_has_watermark_keyword(shape):
            return "watermark_keyword"
        wrap_type = self._safe_word_value(lambda: shape.WrapFormat.Type)
        if wrap_type == WORD_WRAP_BEHIND_TEXT:
            return "behind_text"
        visible = self._safe_word_value(lambda: shape.Visible)
        if visible == 0:
            return "hidden_shape"
        return None

    def _shape_has_watermark_keyword(self, shape) -> bool:
        metadata = " ".join(
            str(value or "")
            for value in (
                self._safe_word_value(lambda: shape.Name, ""),
                self._safe_word_value(lambda: shape.AlternativeText, ""),
                self._safe_word_value(lambda: shape.Title, ""),
            )
        ).lower()
        return any(keyword.lower() in metadata for keyword in WATERMARK_KEYWORDS)

    def _log_word_removal(self, scope: str, shape_kind: str, index: int, reason: str, shape) -> None:
        logger.info(
            "Docx sanitize remove Word object: scope=%s shape_kind=%s index=%s reason=%s name=%s title=%s alt=%s wrap_type=%s visible=%s size=%sx%s anchor_start=%s",
            scope,
            shape_kind,
            index,
            reason,
            self._safe_word_value(lambda: shape.Name, ""),
            self._safe_word_value(lambda: shape.Title, ""),
            self._safe_word_value(lambda: shape.AlternativeText, ""),
            self._safe_word_value(lambda: shape.WrapFormat.Type),
            self._safe_word_value(lambda: shape.Visible),
            self._safe_word_value(lambda: round(float(shape.Width), 2)),
            self._safe_word_value(lambda: round(float(shape.Height), 2)),
            self._safe_word_value(lambda: shape.Anchor.Start),
        )

    @staticmethod
    def _safe_word_value(func, default=None):

        try:
            value = func()
        except Exception:
            return default
        return default if value is None else value

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
                if pythoncom is not None:
                    try:
                        pythoncom.PumpWaitingMessages()
                    except Exception:
                        pass
                time.sleep(delay_seconds)
        raise last_error

    def _sanitize_with_xml(self, source_path: Path, output_path: Path) -> DocxSanitizationResult:
        removed_rel_ids_by_part: Dict[str, Set[str]] = {}
        modified_payloads: Dict[str, bytes] = {}
        result = DocxSanitizationResult(
            output_path=output_path,
            enabled=True,
            applied=True,
            mode=self.mode,
            backend="xml",
        )
        with zipfile.ZipFile(source_path, "r") as input_zip:
            for part_name in input_zip.namelist():
                if not self._is_supported_xml_part(part_name):
                    continue
                payload = input_zip.read(part_name)
                is_header_footer = self._is_header_footer_part(part_name)
                updated_payload, removed_nodes, removable_rel_ids = self._sanitize_xml_part(payload, part_name, is_header_footer)

                if removed_nodes <= 0 and not removable_rel_ids:
                    continue
                modified_payloads[part_name] = updated_payload
                result.removed_total += removed_nodes
                result.removed_xml_nodes += removed_nodes
                if removable_rel_ids:
                    rels_part_name = self._relationship_part_name(part_name)
                    removed_rel_ids_by_part.setdefault(rels_part_name, set()).update(removable_rel_ids)
                    scope = "header" if "header" in part_name else "footer" if "footer" in part_name else "body"
                    result.reason_counts[f"{scope}_xml"] = result.reason_counts.get(f"{scope}_xml", 0) + removed_nodes

            for rels_part_name, removable_rel_ids in removed_rel_ids_by_part.items():
                if rels_part_name not in input_zip.namelist() or not removable_rel_ids:
                    continue
                modified_payloads[rels_part_name] = self._sanitize_relationships_part(input_zip.read(rels_part_name), removable_rel_ids)

            with zipfile.ZipFile(output_path, "w") as output_zip:
                for info in input_zip.infolist():
                    payload = modified_payloads.get(info.filename)
                    if payload is None:
                        payload = input_zip.read(info.filename)
                    output_zip.writestr(info, payload)

        logger.info(
            "Docx sanitize via XML done: source_path=%s output_path=%s mode=%s removed_total=%s reasons=%s",
            source_path,
            output_path,
            self.mode,
            result.removed_total,
            result.reason_counts,
        )

        return result

    def _sanitize_xml_part(self, payload: bytes, part_name: str, is_header_footer: bool) -> Tuple[bytes, int, Set[str]]:
        root = ET.fromstring(payload)
        removed_rel_ids: Set[str] = set()
        removed_count = self._remove_nodes_recursively(root, part_name, is_header_footer, removed_rel_ids)
        if removed_count <= 0:
            return payload, 0, set()
        remaining_rel_ids = self._collect_rel_ids(root)
        removable_rel_ids = removed_rel_ids - remaining_rel_ids
        return ET.tostring(root, encoding="utf-8", xml_declaration=True), removed_count, removable_rel_ids

    def _remove_nodes_recursively(self, parent: ET.Element, part_name: str, is_header_footer: bool, removed_rel_ids: Set[str]) -> int:
        removed_count = 0
        for child in list(parent):
            reason = self._get_xml_removal_reason(child, is_header_footer)
            if reason:
                rel_ids = self._collect_rel_ids(child)
                removed_rel_ids.update(rel_ids)
                self._log_xml_removal(part_name, child, reason, rel_ids)
                parent.remove(child)
                removed_count += 1
                continue
            removed_count += self._remove_nodes_recursively(child, part_name, is_header_footer, removed_rel_ids)
        return removed_count

    def _get_xml_removal_reason(self, node: ET.Element, is_header_footer: bool) -> Optional[str]:
        local_name = self._local_name(node.tag)
        if local_name == "drawing":
            has_anchor = any(self._local_name(desc.tag) == "anchor" for desc in node.iter())
            has_inline = any(self._local_name(desc.tag) == "inline" for desc in node.iter())
            if self.mode == "aggressive":
                if has_anchor:
                    return "aggressive_anchor"
                if is_header_footer and has_inline and self._contains_image_reference(node):
                    return "header_footer_inline"
                return None
            if is_header_footer and has_inline and self._contains_image_reference(node):
                return "header_footer_inline"
            if has_anchor and self._drawing_is_behind_text(node):
                return "behind_text_anchor"
            if has_anchor and self._node_has_watermark_keyword(node):
                return "watermark_anchor"
            return None

        if local_name == "pict":
            if self.mode == "aggressive":
                if is_header_footer:
                    return "header_footer_pict"
                if self._vml_is_positioned_or_hidden(node):
                    return "positioned_vml"
                if self._node_has_watermark_keyword(node):
                    return "watermark_pict"
                return None
            if is_header_footer and self._contains_image_reference(node):
                return "header_footer_pict"
            if self._vml_is_positioned_or_hidden(node):
                return "positioned_vml"
            if self._node_has_watermark_keyword(node):
                return "watermark_pict"

        return None


    def _contains_image_reference(self, node: ET.Element) -> bool:
        return any(self._local_name(desc.tag) in {"blip", "imagedata"} for desc in node.iter())

    def _drawing_is_behind_text(self, node: ET.Element) -> bool:
        for anchor in node.iter():
            if self._local_name(anchor.tag) != "anchor":
                continue
            behind_doc = str(anchor.attrib.get("behindDoc") or "").strip().lower()
            if behind_doc in {"1", "true", "on"}:
                return True
        return False

    def _vml_is_positioned_or_hidden(self, node: ET.Element) -> bool:
        for shape in node.iter():
            local_name = self._local_name(shape.tag)
            if local_name not in {"shape", "rect", "image"}:
                continue
            style = str(shape.attrib.get("style") or "").replace(" ", "").lower()
            if "position:absolute" in style:
                return True
            z_index_match = re.search(r"z-index:([-0-9]+)", style)
            if z_index_match:
                try:
                    if int(z_index_match.group(1)) < 0:
                        return True
                except ValueError:
                    pass
        return False

    def _node_has_watermark_keyword(self, node: ET.Element) -> bool:
        texts = []
        for desc in node.iter():
            texts.extend(str(value or "") for value in desc.attrib.values())
            if desc.text:
                texts.append(desc.text)
        haystack = " ".join(texts).lower()
        return any(keyword.lower() in haystack for keyword in WATERMARK_KEYWORDS)

    def _log_xml_removal(self, part_name: str, node: ET.Element, reason: str, rel_ids: Set[str]) -> None:
        logger.info(
            "Docx sanitize remove XML node: part=%s tag=%s reason=%s rel_ids=%s preview=%s",
            part_name,
            self._local_name(node.tag),
            reason,
            sorted(rel_ids),
            self._preview_xml_node(node),
        )

    def _preview_xml_node(self, node: ET.Element) -> str:
        text_fragments = []
        for desc in node.iter():
            if desc.text:
                stripped = str(desc.text).strip()
                if stripped:
                    text_fragments.append(stripped)
            if len(text_fragments) >= 3:
                break
        attr_fragments = []
        for desc in node.iter():
            for attr_name, attr_value in desc.attrib.items():
                local_attr_name = self._local_name(attr_name)
                if local_attr_name in {"name", "title", "descr", "style", "id", "embed", "link", "behindDoc"}:
                    attr_fragments.append(f"{local_attr_name}={str(attr_value)[:80]}")
                if len(attr_fragments) >= 4:
                    break
            if len(attr_fragments) >= 4:
                break
        preview = " | ".join(attr_fragments + text_fragments)
        return preview[:240]

    def _sanitize_relationships_part(self, payload: bytes, removable_rel_ids: Set[str]) -> bytes:

        root = ET.fromstring(payload)
        for relationship in list(root.findall("pr:Relationship", PACKAGE_REL_NS)):
            relation_id = str(relationship.attrib.get("Id") or "")
            if relation_id in removable_rel_ids:
                root.remove(relationship)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _collect_rel_ids(self, node: ET.Element) -> Set[str]:
        rel_ids: Set[str] = set()
        for desc in node.iter():
            for attr_name, attr_value in desc.attrib.items():
                if not attr_value:
                    continue
                if attr_name.endswith("}embed") or attr_name.endswith("}id") or attr_name.endswith("}link"):
                    rel_ids.add(str(attr_value))
        return rel_ids

    @staticmethod
    def _is_supported_xml_part(part_name: str) -> bool:
        return part_name == "word/document.xml" or bool(re.match(r"word/(header|footer)\d+\.xml$", part_name))

    @staticmethod
    def _is_header_footer_part(part_name: str) -> bool:
        return bool(re.match(r"word/(header|footer)\d+\.xml$", part_name))

    @staticmethod
    def _relationship_part_name(part_name: str) -> str:
        part_file_name = Path(part_name).name
        return f"word/_rels/{part_file_name}.rels"

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def sanitize_docx_document(
    source_path: Path,
    output_path: Path,
    *,
    enabled: bool = False,
    mode: str = "conservative",
    backend: str = "auto",
) -> DocxSanitizationResult:
    sanitizer = DocxSanitizer(enabled=enabled, mode=mode, backend=backend)
    return sanitizer.sanitize(source_path, output_path)
