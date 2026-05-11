import json
import os
from copy import deepcopy


def load_config(config_path: str = None) -> dict:
    """
    加载配置文件
    
    Args:
        config_path: 配置文件路径，默认为 preprocessor/config/config.json
        
    Returns:
        配置字典
    """
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            '..', 'config', 'config.json'
        )
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_classification_method(config: dict) -> str:
    """获取分类方式配置"""
    return config.get('classification', {}).get('method', 'single_page')


DEFAULT_CROP_REFINEMENT_CONFIG = {
    'enabled': True,
    'preserve_original_points': True,
    'record_debug': True,
    'trim_whitespace': True,
    'trim_padding': 6,
    'question_padding_ratio': {
        'left': 0.10,
        'right': 0.10,
        'top': 0.15,
        'bottom': 0.20
    },
    'answer_padding_ratio': {
        'left': 0.06,
        'right': 0.06,
        'top': 0.08,
        'bottom': 0.12
    },
    'min_padding_pixels': {
        'left': 12,
        'right': 12,
        'top': 12,
        'bottom': 16
    },
    'text_block_expansion': {
        'enabled': True,
        'overlap_margin': 12,
        'disable_on_opencv_fallback': True,
        'max_side_expand_ratio_x': 0.22,
        'max_side_expand_ratio_y': 0.18,
        'min_overlap_ratio_x': 0.55,
        'min_overlap_ratio_y': 0.55,
        'guard_override': {
            'enabled': True,
            'overlap_margin': 18,
            'max_side_expand_ratio_x': 0.34,
            'max_side_expand_ratio_y': 0.30,
            'min_overlap_ratio_x': 0.70,
            'min_overlap_ratio_y': 0.70,
            'max_block_area_ratio': 2.4
        }
    },
    'neighbor_guard': {
        'enabled': True,
        'min_gap_px': 8,
        'horizontal_min_gap_px': 8,
        'vertical_min_gap_px': 2,
        'same_row_overlap_ratio': 0.28,
        'same_column_overlap_ratio': 0.20,
        'horizontal_mid_gap_ratio': 0.50,
        'vertical_gap_keep_ratio_question': 0.15,
        'vertical_gap_keep_ratio_answer': 0.25,
        'priority_relax_question': {
            'enabled': True,
            'left_px': 18,
            'top_px': 12,
            'right_px': 0,
            'bottom_px': 0
        }
    },
    'question_short_box': {
        'enabled': True,
        'max_height_px': 110,
        'top_padding_px': 18,
        'bottom_padding_px': 22
    },
    'question_anchor': {
        'enabled': True,
        'top_buffer_px': 10,
        'search_above_px': 120,
        'column_tolerance_ratio': 0.35
    },
    'edge_safety': {
        'enabled': True,
        'margin_px': 5,
        'binary_threshold': 200,
        'density_threshold': 0.15,
        'ignore_corner_ratio': 0.12,
        'expand_step_px': 8,
        'max_iterations': 4,
        'max_expand_ratio': 0.18,
        'max_horizontal_expand_ratio': 0.08,
        'max_vertical_expand_ratio': 0.18
    },
    'page_ocr': {
        'enabled': True,
        'backend': 'auto',
        'cache_to_disk': True,
        'detect_text_blocks': True,
        'detect_question_anchors': True,
        'min_block_area': 80,
        'min_block_width': 8,
        'min_block_height': 8,
        'merge_gap_x': 18,
        'merge_gap_y': 10,
        'anchor_min_score': 0.45,
        'anchor_patterns': [
            r'第\\s*(\\d{1,3})\\s*题',
            r'^\\s*(\\d{1,3})\\s*[\\.、．:]',
            r'^\\s*[（(]\\s*(\\d{1,3})\\s*[)）]'
        ]
    },
    'box_debug_visualization': {
        'enabled': True
    }
}


def get_crop_refinement_config(config: dict = None) -> dict:
    merged = deepcopy(DEFAULT_CROP_REFINEMENT_CONFIG)
    user_config = (config or {}).get('crop_refinement', {})
    _deep_merge_dict(merged, user_config)
    return merged


def _deep_merge_dict(target: dict, source: dict) -> None:
    for key, value in (source or {}).items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_dict(target[key], value)
        else:
            target[key] = value
