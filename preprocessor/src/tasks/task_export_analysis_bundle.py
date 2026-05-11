"""
步骤9：导出 analyzer 可消费的标准试卷 bundle

输出：
- manifest.json
- questions.json
"""

import json
import os
import re
from datetime import datetime, timezone

from typing import Any, Dict, List, Optional, Tuple


ASSET_ANCHORS = [
    'question_slices',
    'answer_slices',
    'corrected_images',
    'compressed_images',
    'stitched_images',
    'answer_card_areas',
    'complete_unit_images',
    '06_final_output',
    '07_complete_units',
    '08_annotated_images'
]


def run_export_analysis_bundle(
    workspace_dir: str,
    output_path: str,
    exam_context: Optional[Dict[str, Any]] = None,
    producer: Optional[Dict[str, Any]] = None
) -> str:
    """导出标准交接 bundle。"""
    manifest_path = os.path.abspath(output_path)
    workspace_dir = os.path.abspath(workspace_dir)
    questions_path = os.path.join(workspace_dir, 'questions.json')
    content_path = os.path.join(workspace_dir, '04_content_output.json')
    merged_path = os.path.join(workspace_dir, '05_merged_output.json')
    complete_units_path = os.path.join(workspace_dir, 'complete_units.json')

    for required_path in (content_path, merged_path, complete_units_path):
        if not os.path.exists(required_path):
            raise FileNotFoundError(f"Bundle export prerequisite not found: {required_path}")

    with open(content_path, 'r', encoding='utf-8') as f:
        content_output = json.load(f)
    with open(merged_path, 'r', encoding='utf-8') as f:
        merged_output = json.load(f)
    with open(complete_units_path, 'r', encoding='utf-8') as f:
        complete_units = json.load(f)

    warnings: List[str] = []
    exam_context = _build_exam_context(workspace_dir, exam_context)
    producer_info = _build_producer_info(workspace_dir, producer)
    content_lookup, sheets = _build_content_lookup(content_output, workspace_dir)
    merged_lookup = _build_merged_lookup(merged_output, workspace_dir)

    questions: List[Dict[str, Any]] = []
    for question_no, unit_data in sorted(complete_units.items(), key=lambda item: _question_sort_key(item[0])):
        question_no = str(question_no).strip()
        if _is_special_entry(question_no, unit_data):
            continue

        question_record, question_warnings = _build_question_record(
            question_no=question_no,
            unit_data=unit_data,
            merged_entry=merged_lookup.get(question_no, {}),
            content_entries=content_lookup.get(question_no, []),
            workspace_dir=workspace_dir
        )
        questions.append(question_record)
        warnings.extend(question_warnings)

    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(questions_path, 'w', encoding='utf-8') as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)

    manifest = {
        'schema_version': '1.0',
        'bundle_id': _build_bundle_id(workspace_dir, exam_context),
        'run_id': os.path.basename(workspace_dir),
        'created_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),

        'producer': producer_info,
        'exam_context': exam_context,
        'files': {
            'questions': 'questions.json',
            'complete_units': 'complete_units.json',
            'merged_results': '05_merged_output.json',
            'content_output': '04_content_output.json'
        },
        'assets': _build_assets_manifest(workspace_dir),
        'sheets': sheets,
        'stats': _build_stats(questions, sheets),
        'status': 'partial_success' if warnings else 'success',
        'warnings': sorted(set(warnings))
    }

    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"  Analyzer bundle manifest saved to: {manifest_path}")
    print(f"  Analyzer bundle questions saved to: {questions_path}")
    print(f"  Bundle stats: {manifest['stats']}")
    return manifest_path


def _build_exam_context(workspace_dir: str, exam_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    context = {
        'exam_id': None,
        'paper_id': None,
        'student_id': None,
        'subject': None,
        'grade': None,
        'class_id': None,
        'organization_id': None,
        'source_mode': 'unknown'
    }
    if exam_context:
        context.update(exam_context)
    context['workspace_name'] = os.path.basename(workspace_dir)
    return context


def _build_producer_info(workspace_dir: str, producer: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    version_path = os.path.join(project_root, 'VERSION')
    version = None
    if os.path.exists(version_path):
        with open(version_path, 'r', encoding='utf-8') as f:
            version = f.read().strip() or None

    producer_info = {
        'module': 'preprocessor',
        'entry': 'preprocessor/main.py',
        'workspace_dir': workspace_dir,
        'version': version
    }
    if producer:
        producer_info.update(producer)
    return producer_info


def _build_content_lookup(content_output: List[Dict[str, Any]], workspace_dir: str) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]]]:
    lookup: Dict[str, List[Dict[str, Any]]] = {}
    sheets: List[Dict[str, Any]] = []

    for item in content_output:
        questions = ((item.get('vlm_output') or {}).get('questions') or [])
        sheet_question_numbers = []
        for question in questions:
            question_no = str(question.get('number') or '').strip()
            if not question_no:
                continue
            lookup.setdefault(question_no, []).append({
                'question': question,
                'sheet_id': item.get('sheet_id'),
                'sheet_type': item.get('sheet_type'),
                'page_index': item.get('page_index'),
                'order': item.get('order'),
                'part_type': item.get('part_type'),
                'crop_area': item.get('crop_area'),
                'divider_x': item.get('divider_x'),
                'source_image_path': item.get('source_image_path'),
                'source_corrected_image': item.get('source_corrected_image'),
                'part_image_path': item.get('part_image_path')
            })
            if question_no != '0':
                sheet_question_numbers.append(question_no)

        sheets.append({
            'sheet_id': item.get('sheet_id'),
            'sheet_type': item.get('sheet_type'),
            'page_index': item.get('page_index'),
            'order': item.get('order'),
            'page_type': item.get('page_type'),
            'part_type': item.get('part_type'),
            'crop_area': item.get('crop_area'),
            'divider_x': item.get('divider_x'),
            'source_image_path': _to_bundle_relative_path(item.get('source_image_path'), workspace_dir),
            'source_corrected_image': _to_bundle_relative_path(item.get('source_corrected_image'), workspace_dir),
            'part_image_path': _to_bundle_relative_path(item.get('part_image_path'), workspace_dir),
            'question_numbers': sorted(set(sheet_question_numbers), key=_question_sort_key)
        })

    return lookup, sheets


def _build_merged_lookup(merged_output: Dict[str, Any], workspace_dir: str) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for question_no, fragments in merged_output.items():
        normalized_no = str(question_no).strip()
        question_fragments = []
        answer_fragments = []
        for fragment in fragments or []:
            fragment_copy = dict(fragment)
            fragment_copy['question_slice_path'] = _to_bundle_relative_path(fragment.get('question_slice_path'), workspace_dir)
            fragment_copy['answer_slice_path'] = _to_bundle_relative_path(fragment.get('answer_slice_path'), workspace_dir)
            fragment_copy['source_original_image'] = _to_bundle_relative_path(fragment.get('source_original_image'), workspace_dir)
            fragment_copy['source_corrected_image'] = _to_bundle_relative_path(fragment.get('source_corrected_image'), workspace_dir)
            fragment_copy['source_part_image'] = _to_bundle_relative_path(fragment.get('source_part_image'), workspace_dir)
            if _is_question_fragment(fragment):
                question_fragments.append(fragment_copy)
            if _is_answer_fragment(fragment):
                answer_fragments.append(fragment_copy)

        lookup[normalized_no] = {
            'fragments': [dict(fragment) for fragment in fragments or []],
            'question_fragments': question_fragments,
            'answer_fragments': answer_fragments
        }
    return lookup


def _build_question_record(
    question_no: str,
    unit_data: Dict[str, Any],
    merged_entry: Dict[str, Any],
    content_entries: List[Dict[str, Any]],
    workspace_dir: str
) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    question_fragments = merged_entry.get('question_fragments') or []
    answer_fragments = merged_entry.get('answer_fragments') or []
    primary_question_fragment = question_fragments[0] if question_fragments else {}
    primary_content_entry = content_entries[0] if content_entries else {}
    primary_content_question = primary_content_entry.get('question') or {}

    question_id = unit_data.get('question_id') or _fallback_question_id(
        unit_data.get('sheet_id') or primary_question_fragment.get('sheet_id') or primary_content_entry.get('sheet_id'),
        question_no
    )
    question_text = (
        unit_data.get('question_text')
        or primary_question_fragment.get('description')
        or primary_content_question.get('description')
        or ''
    )
    question_type = (
        primary_question_fragment.get('type')
        or primary_content_question.get('type')
        or None
    )

    question_image_path = _pick_first_path(
        workspace_dir,
        unit_data.get('question_slice_path'),
        primary_question_fragment.get('question_slice_path'),
        primary_content_question.get('question_slice_path'),
        unit_data.get('question_image')
    )
    complete_unit_image_path = _pick_first_path(workspace_dir, unit_data.get('complete_unit_image_path'))

    answer_image_paths = _collect_answer_image_paths(unit_data, answer_fragments, workspace_dir)
    answer_image_path = answer_image_paths[0] if answer_image_paths else None
    answer_source = unit_data.get('answer_source') or _derive_answer_source(unit_data, answer_fragments)
    answer_status = _derive_answer_status(unit_data, answer_source, answer_image_paths)

    needs_manual_review = bool(
        not question_text
        or not question_image_path
        or answer_status == 'uncertain'
        or (answer_source == 'none' and not answer_image_paths)
    )

    if not question_image_path:
        warnings.append(f"Question {question_no} is missing a question image path.")
    if not question_text:
        warnings.append(f"Question {question_no} is missing question text.")

    question_record = {
        'question_no': question_no,
        'question_id': question_id,
        'sheet_id': unit_data.get('sheet_id') or primary_question_fragment.get('sheet_id') or primary_content_entry.get('sheet_id'),
        'question_type': question_type,
        'question_text': question_text,
        'student_answer': unit_data.get('answer'),
        'answer_source': answer_source,
        'answer_status': answer_status,
        'question_image_path': question_image_path,
        'answer_image_path': answer_image_path,
        'answer_image_paths': answer_image_paths,
        'complete_unit_image_path': complete_unit_image_path,
        'source_complete_unit_key': question_no,
        'source_merged_number': question_no if merged_entry else None,
        'needs_manual_review': needs_manual_review,
        'confidence': {
            'has_question_text': bool(question_text),
            'has_question_image': bool(question_image_path),
            'has_complete_unit_image': bool(complete_unit_image_path),
            'answer_image_count': len(answer_image_paths),
            'merged_fragment_count': len(merged_entry.get('fragments') or []),
            'answer_fragment_count': len(answer_fragments)
        },
        'tags': [],
        'source': {
            'question_points': primary_question_fragment.get('points') or primary_content_question.get('points'),
            'question_crop_area': primary_question_fragment.get('crop_area') or primary_content_entry.get('crop_area'),
            'answer_points': [fragment.get('points') for fragment in answer_fragments if fragment.get('points')],
            'source_corrected_image': _pick_first_path(
                workspace_dir,
                primary_question_fragment.get('source_corrected_image'),
                primary_content_entry.get('source_corrected_image'),
                unit_data.get('question_image')
            ),
            'source_part_image': _pick_first_path(
                workspace_dir,
                primary_question_fragment.get('source_part_image'),
                primary_content_entry.get('part_image_path')
            )
        }
    }
    return question_record, warnings


def _build_assets_manifest(workspace_dir: str) -> Dict[str, Optional[str]]:
    preferred_complete_units_dir = '07_complete_units' if os.path.isdir(os.path.join(workspace_dir, '07_complete_units')) else None
    complete_unit_images_dir = 'complete_unit_images' if os.path.isdir(os.path.join(workspace_dir, 'complete_unit_images')) else None
    annotated_images_dir = '08_annotated_images' if os.path.isdir(os.path.join(workspace_dir, '08_annotated_images')) else None
    return {
        'question_slices_dir': 'question_slices' if os.path.isdir(os.path.join(workspace_dir, 'question_slices')) else None,
        'answer_slices_dir': 'answer_slices' if os.path.isdir(os.path.join(workspace_dir, 'answer_slices')) else None,
        'answer_card_areas_dir': 'answer_card_areas' if os.path.isdir(os.path.join(workspace_dir, 'answer_card_areas')) else None,
        'complete_unit_images_dir': complete_unit_images_dir,
        'final_complete_units_dir': preferred_complete_units_dir,
        'annotated_images_dir': annotated_images_dir
    }


def _build_stats(questions: List[Dict[str, Any]], sheets: List[Dict[str, Any]]) -> Dict[str, int]:
    answered = sum(1 for question in questions if question.get('answer_status') == 'answered')
    unanswered = sum(1 for question in questions if question.get('answer_status') == 'unanswered')
    uncertain = sum(1 for question in questions if question.get('answer_status') == 'uncertain')
    manual_review = sum(1 for question in questions if question.get('needs_manual_review'))
    return {
        'total_questions': len(questions),
        'answered_questions': answered,
        'unanswered_questions': unanswered,
        'uncertain_questions': uncertain,
        'manual_review_questions': manual_review,
        'sheet_count': len([sheet for sheet in sheets if sheet.get('sheet_id')])
    }


def _build_bundle_id(workspace_dir: str, exam_context: Dict[str, Any]) -> str:
    exam_id = exam_context.get('exam_id')
    paper_id = exam_context.get('paper_id')
    workspace_name = os.path.basename(workspace_dir)
    if exam_id and paper_id:
        return f"{exam_id}_{paper_id}_{workspace_name}"
    if exam_id:
        return f"{exam_id}_{workspace_name}"
    return workspace_name


def _fallback_question_id(sheet_id: Optional[str], question_no: str) -> str:
    sheet_prefix = sheet_id or 'UNKNOWN_SHEET'
    if question_no.isdigit():
        return f"{sheet_prefix}_Q{int(question_no):03d}"
    safe_question_no = re.sub(r'[^0-9A-Za-z_-]+', '_', question_no)
    return f"{sheet_prefix}_{safe_question_no}"


def _pick_first_path(workspace_dir: str, *paths: Optional[str]) -> Optional[str]:
    for path in paths:
        relative_path = _to_bundle_relative_path(path, workspace_dir)
        if relative_path:
            return relative_path
    return None


def _collect_answer_image_paths(unit_data: Dict[str, Any], answer_fragments: List[Dict[str, Any]], workspace_dir: str) -> List[str]:
    candidates: List[str] = []
    for path in unit_data.get('answer_slice_paths') or []:
        relative_path = _to_bundle_relative_path(path, workspace_dir)
        if relative_path:
            candidates.append(relative_path)

    for path in [
        unit_data.get('answer_slice_path'),
        unit_data.get('answer_card_image')
    ]:
        relative_path = _to_bundle_relative_path(path, workspace_dir)
        if relative_path:
            candidates.append(relative_path)

    for fragment in answer_fragments:
        relative_path = _to_bundle_relative_path(fragment.get('answer_slice_path'), workspace_dir)
        if relative_path:
            candidates.append(relative_path)

    unique_paths: List[str] = []
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    return unique_paths


def _derive_answer_source(unit_data: Dict[str, Any], answer_fragments: List[Dict[str, Any]]) -> str:
    if unit_data.get('is_mixed_mode'):
        return 'mixed'
    if unit_data.get('answer_card_image'):
        return 'answer_card'
    if answer_fragments or unit_data.get('answer_slice_paths') or unit_data.get('answer_slice_path'):
        return 'answer_area'
    return 'none'


def _derive_answer_status(unit_data: Dict[str, Any], answer_source: str, answer_image_paths: List[str]) -> str:
    answer = unit_data.get('answer')
    if answer not in (None, '', 'EMPTY'):
        return 'answered'
    if answer_source == 'answer_card':
        return 'unanswered'
    if answer_source in {'answer_area', 'mixed'} and answer_image_paths:
        return 'uncertain'
    return 'unanswered'


def _is_special_entry(question_no: str, unit_data: Dict[str, Any]) -> bool:
    question_text = str(unit_data.get('question_text') or '')
    if question_no in {'', '0'}:
        return True
    if '涂卡区' in question_text:
        return True
    return False


def _is_question_fragment(fragment: Dict[str, Any]) -> bool:
    if fragment.get('is_question_sheet'):
        return True
    return str(fragment.get('sheet_type') or '').lower() in {'question_paper', 'mixed', '题目纸', '混合纸'}


def _is_answer_fragment(fragment: Dict[str, Any]) -> bool:
    if fragment.get('is_answer_sheet'):
        return True
    return str(fragment.get('sheet_type') or '').lower() in {'answer_sheet', '答题纸'} or fragment.get('type') == 'answer_area'


def _question_sort_key(question_no: str) -> Tuple[int, Any]:
    text = str(question_no).strip()
    if text.isdigit():
        return (0, int(text))
    match = re.match(r'^(\d+)(.*)$', text)
    if match:
        return (1, int(match.group(1)), match.group(2))
    return (2, text)


def _to_bundle_relative_path(path: Optional[str], workspace_dir: str) -> Optional[str]:
    if not path:
        return None

    normalized_path = os.path.normpath(path)
    path_parts = normalized_path.split(os.sep)
    lower_parts = [part.lower() for part in path_parts]

    for anchor in ASSET_ANCHORS:
        anchor_lower = anchor.lower()
        if anchor_lower in lower_parts:
            anchor_index = lower_parts.index(anchor_lower)
            return os.path.join(*path_parts[anchor_index:]).replace('\\', '/')

    if os.path.isabs(normalized_path):
        try:
            relative_path = os.path.relpath(normalized_path, workspace_dir)
            return relative_path.replace('\\', '/')
        except ValueError:
            return normalized_path.replace('\\', '/')

    return normalized_path.replace('\\', '/')
