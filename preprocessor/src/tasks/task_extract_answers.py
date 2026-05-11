"""
答案区域物理切片任务

功能：
1. 从内容提取结果中识别答题纸上的答案区域
2. 物理切片答案区域并保存到单独目录
3. 在数据中记录答案切片路径
4. 使用带扩展的切片函数（容错设计）
"""

import argparse
import json
import os
import sys
from copy import deepcopy
import numpy as np
from PIL import Image

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils import crop_with_padding, save_crop_with_quality, analyze_page_ocr, refine_region_and_crop, save_box_debug_visualizations
from src.utils.config_loader import get_crop_refinement_config


def run_answer_extraction(
    content_output_path: str,
    output_path: str,
    workspace_dir: str,
    crop_refinement_config: dict = None,
    logger=None
):
    """
    从答题纸上提取并切片答案区域
    
    Args:
        content_output_path: 内容提取结果 JSON 路径（04_content_output.json）
        output_path: 输出路径（与 content_output_path 相同，更新原文件）
        workspace_dir: 工作目录
    """
    print("\n" + "=" * 60)
    print("答案区域物理切片")
    print("=" * 60)
    
    # 读取内容提取结果
    with open(content_output_path, 'r', encoding='utf-8') as f:
        content_results = json.load(f)

    resolved_crop_refinement_config = get_crop_refinement_config({
        'crop_refinement': crop_refinement_config or {}
    })
    
    total_sliced = 0
    
    for part in content_results:
        # 只处理答题纸
        sheet_type = part.get('sheet_type', '')
        if sheet_type not in ['answer_sheet', '答题纸']:
            continue
        
        sheet_id = part.get('sheet_id', 'unknown')
        source_corrected_image = part.get('source_corrected_image')
        vlm_output = part.get('vlm_output', {})
        questions = vlm_output.get('questions', [])
        
        print(f"\n处理答题纸：{sheet_id}")
        print(f"  矫正图片：{source_corrected_image}")
        print(f"  识别到 {len(questions)} 个区域")
        
        # 检查矫正图片是否存在
        if not source_corrected_image or not os.path.exists(source_corrected_image):
            print(f"  [WARNING] 矫正图片不存在：{source_corrected_image}")
            continue
        
        # 读取矫正后的图片
        try:
            corrected_image = Image.open(source_corrected_image)
            corrected_image = np.array(corrected_image)
        except Exception as e:
            print(f"  [ERROR] 无法读取矫正图片：{e}")
            continue
        
        answer_slices_dir = os.path.join(workspace_dir, 'answer_slices', sheet_id)
        os.makedirs(answer_slices_dir, exist_ok=True)

        page_ocr_result = None
        page_ocr_config = resolved_crop_refinement_config.get('page_ocr', {})
        if page_ocr_config.get('enabled', True):
            page_ocr_result = analyze_page_ocr(
                source_corrected_image,
                workspace_dir=workspace_dir,
                config=page_ocr_config,
                logger=logger
            )
        part['page_ocr_backend'] = page_ocr_result.get('backend', 'disabled') if page_ocr_result else 'disabled'
        
        sliced_count = 0
        used_numbers = set()
        crop_area = part.get('crop_area')
        box_debug_items = []
        for answer_area in questions:
            if answer_area.get('number') == '涂卡区':
                continue
            
            try:
                points = answer_area.get('points')
                if not points:
                    continue

                original_points = deepcopy(points)
                try:
                    refine_result = refine_region_and_crop(
                        image=corrected_image,
                        points=points,
                        crop_area=crop_area,
                        question_number=answer_area.get('number'),
                        mode='answer',
                        page_ocr_result=page_ocr_result,
                        config=resolved_crop_refinement_config,
                        peer_points_list=[
                            candidate.get('points')
                            for candidate in questions
                            if candidate is not answer_area and candidate.get('number') != '涂卡区' and candidate.get('points')
                        ]
                    )
                    crop = refine_result['crop']
                except Exception as refine_error:
                    print(f"    [WARNING] Refine failed for answer area {answer_area.get('number')}: {refine_error}")
                    crop = crop_with_padding(corrected_image, points)
                    refine_result = {
                        'points': original_points,
                        'refine_flags': ['fallback_crop_with_padding'],
                        'crop_debug': {
                            'mode': 'answer',
                            'refined': False,
                            'reason': str(refine_error),
                            'crop_area': crop_area
                        }
                    }
                
                original_number = str(answer_area.get('number', 'unknown'))
                q_num = original_number
                suffix = 1
                while q_num in used_numbers:
                    if '续' in q_num:
                        q_num = f"{original_number}-{suffix}"
                    else:
                        q_num = f"{original_number}-{suffix}"
                    suffix += 1
                used_numbers.add(q_num)
                
                q_num_formatted = q_num.zfill(3)
                crop_output_path = os.path.join(answer_slices_dir, f'A{q_num_formatted}.jpg')
                save_crop_with_quality(crop, crop_output_path)

                if resolved_crop_refinement_config.get('preserve_original_points', True):
                    answer_area['original_points'] = original_points
                answer_area['points'] = refine_result['points']
                answer_area['answer_slice_path'] = crop_output_path
                answer_area['source_image_for_crop'] = source_corrected_image
                if resolved_crop_refinement_config.get('record_debug', True):
                    answer_area['crop_debug'] = refine_result.get('crop_debug', {})
                    answer_area['refine_flags'] = refine_result.get('refine_flags', [])
                if q_num != original_number:
                    answer_area['original_number'] = original_number
                box_debug_items.append({
                    'number': answer_area.get('number'),
                    'original_points': original_points,
                    'refined_points': refine_result.get('points', original_points)
                })
                sliced_count += 1
                
                print(f"    切片：{answer_area.get('number')} -> {crop_output_path}")
                
            except Exception as e:
                print(f"    [WARNING] 切片失败 {answer_area.get('number')}: {e}")
        
        box_debug_config = resolved_crop_refinement_config.get('box_debug_visualization', {})
        if box_debug_config.get('enabled', True) and box_debug_items:
            save_box_debug_visualizations(
                image_path=source_corrected_image,
                crop_area=crop_area,
                regions=box_debug_items,
                output_dir=os.path.join(workspace_dir, 'box_debug', 'answers'),
                filename_prefix=f"{sheet_id}_{os.path.splitext(os.path.basename(source_corrected_image))[0]}"
            )
        print(f"  成功切片 {sliced_count} 个答案区域")
        total_sliced += sliced_count
    
    print("\n" + "=" * 60)
    print(f"答案切片完成：共切片 {total_sliced} 个区域")
    print("=" * 60)
    
    # 保存更新后的内容提取结果（包含答案切片路径）
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(content_results, f, indent=2, ensure_ascii=False)
    
    print(f"\n更新后的内容提取结果已保存：{output_path}")
    
    return output_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='答案区域物理切片')
    parser.add_argument('--content-output-path', required=True, help='内容提取结果 JSON 路径')
    parser.add_argument('--output-path', required=True, help='输出路径')
    parser.add_argument('--workspace-dir', required=True, help='工作目录')
    args = parser.parse_args()
    
    run_answer_extraction(
        content_output_path=args.content_output_path,
        output_path=args.output_path,
        workspace_dir=args.workspace_dir
    )
