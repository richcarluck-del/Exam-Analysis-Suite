import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import analyze_page_ocr, refine_region_and_crop, save_crop_with_quality
from src.utils.config_loader import load_config, get_crop_refinement_config


QUESTION_PAGE_TYPES = {'question_paper', 'mixed', '题目纸', '题目和答题混合纸'}
ANSWER_PAGE_TYPES = {'answer_sheet', '答题纸'}


def main():
    parser = argparse.ArgumentParser(description='评估切图精修结果')
    parser.add_argument('--content-output', required=True, help='04_content_output.json 路径')
    parser.add_argument('--output-dir', required=True, help='评估输出目录')
    parser.add_argument('--include-answer-areas', action='store_true', help='同时评估答题区切片')
    args = parser.parse_args()

    content_output_path = Path(args.content_output).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(content_output_path, 'r', encoding='utf-8') as f:
        content_results = json.load(f)

    full_config = load_config()
    crop_refinement_config = get_crop_refinement_config(full_config)
    page_ocr_config = crop_refinement_config.get('page_ocr', {})

    summary = {
        'content_output': str(content_output_path),
        'output_dir': str(output_dir),
        'parts': len(content_results),
        'processed_regions': 0,
        'skipped_regions': 0,
        'backend_counter': {},
        'refine_flag_counter': {},
        'samples': []
    }

    backend_counter = Counter()
    flag_counter = Counter()
    page_ocr_cache = {}
    image_cache = {}

    for part in content_results:
        sheet_id = part.get('sheet_id', 'unknown')
        sheet_type = part.get('sheet_type', '')
        page_type = part.get('page_type', '')
        source_corrected_image = part.get('source_corrected_image')
        crop_area = part.get('crop_area')
        questions = part.get('vlm_output', {}).get('questions', [])

        if not source_corrected_image or not os.path.exists(source_corrected_image):
            continue

        if source_corrected_image not in image_cache:
            image = cv2.imread(source_corrected_image)
            if image is None:
                continue
            image_cache[source_corrected_image] = image
        corrected_image = image_cache[source_corrected_image]

        if source_corrected_image not in page_ocr_cache:
            page_ocr_cache[source_corrected_image] = analyze_page_ocr(
                source_corrected_image,
                workspace_dir=str(output_dir),
                config=page_ocr_config
            )
        page_ocr_result = page_ocr_cache[source_corrected_image]
        backend_counter[page_ocr_result.get('backend', 'unknown')] += 1

        part_dir = output_dir / sheet_id
        part_dir.mkdir(parents=True, exist_ok=True)

        for question in questions:
            number = str(question.get('number', 'unknown'))
            points = question.get('points')
            if not points or number == '涂卡区':
                summary['skipped_regions'] += 1
                continue

            mode = None
            filename_prefix = None
            if page_type in QUESTION_PAGE_TYPES:
                mode = 'question'
                filename_prefix = 'Q'
            elif args.include_answer_areas and sheet_type in ANSWER_PAGE_TYPES:
                mode = 'answer'
                filename_prefix = 'A'
            else:
                summary['skipped_regions'] += 1
                continue

            try:
                refine_result = refine_region_and_crop(
                    image=corrected_image,
                    points=points,
                    crop_area=crop_area,
                    question_number=number,
                    mode=mode,
                    page_ocr_result=page_ocr_result,
                    config=crop_refinement_config,
                    peer_points_list=[
                        candidate.get('points')
                        for candidate in questions
                        if candidate is not question and candidate.get('number') != '涂卡区' and candidate.get('points')
                    ]
                )

            except Exception:
                summary['skipped_regions'] += 1
                continue

            sample_name = f"{filename_prefix}{number.replace('/', '_').replace(' ', '_')}.jpg"
            sample_path = part_dir / sample_name
            save_crop_with_quality(refine_result['crop'], str(sample_path))

            flags = refine_result.get('refine_flags', [])
            for flag in flags:
                flag_counter[flag] += 1

            summary['processed_regions'] += 1
            summary['samples'].append({
                'sheet_id': sheet_id,
                'number': number,
                'mode': mode,
                'page_ocr_backend': page_ocr_result.get('backend', 'unknown'),
                'refine_flags': flags,
                'page_box': refine_result.get('page_box'),
                'sample_path': str(sample_path)
            })

    summary['backend_counter'] = dict(backend_counter)
    summary['refine_flag_counter'] = dict(flag_counter)

    summary_path = output_dir / 'crop_refinement_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print('=' * 60)
    print('切图精修评估完成')
    print('=' * 60)
    print(f"输入文件: {content_output_path}")
    print(f"输出目录: {output_dir}")
    print(f"处理区域: {summary['processed_regions']}")
    print(f"跳过区域: {summary['skipped_regions']}")
    print(f"OCR 后端统计: {summary['backend_counter']}")
    print(f"精修标记统计: {summary['refine_flag_counter']}")
    print(f"汇总文件: {summary_path}")


if __name__ == '__main__':
    main()
