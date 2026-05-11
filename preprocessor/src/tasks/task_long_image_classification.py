import json
import os
import re
import sys
from pathlib import Path
from PIL import Image

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ..utils import call_api, extract_json
from shared.prompt_step_config import get_seed_prompt_text

def load_correction_output(workspace_dir: str) -> dict:
    """
    加载透视矫正输出结果
    
    Args:
        workspace_dir: 工作目录
        
    Returns:
        矫正结果字典
    """
    correction_output_path = os.path.join(workspace_dir, '01_correction_output.json')
    with open(correction_output_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def stitch_images(sheet_metadata_list: list, output_path: str) -> tuple:
    """
    拼接图片成长图（水平拼接 + 黑色间隔条）
    
    Args:
        sheet_metadata_list: 试卷纸元数据列表
        output_path: 输出路径
        
    Returns:
        (拼接图路径，bbox 字典 {sheet_id: [x1, y1, x2, y2]})
    """
    # 确保输出目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # 读取所有图片
    images = []
    max_height = 0
    total_width = 0
    
    # 黑色间隔条配置
    SEPARATOR_WIDTH = 50  # 黑色间隔条宽度（像素）
    
    for sheet_meta in sheet_metadata_list:
        img_path = sheet_meta['corrected_image']
        if os.path.exists(img_path):
            img = Image.open(img_path)
            images.append(img)
            max_height = max(max_height, img.height)
            total_width += img.width
    
    # 添加间隔条的宽度（n-1 个间隔）
    if len(images) > 1:
        total_width += SEPARATOR_WIDTH * (len(images) - 1)
    
    # 创建拼接图（水平方向）并记录 bbox
    bbox_dict = {}
    if images:
        stitched = Image.new('RGB', (total_width, max_height), color='black')  # 黑色背景
        current_width = 0
        
        for i, img in enumerate(images):
            sheet_meta = sheet_metadata_list[i]
            sheet_id = sheet_meta.get('sheet_id', f'sheet_{i}')
            
            # 粘贴图片（居中对齐）
            y_offset = (max_height - img.height) // 2
            stitched.paste(img, (current_width, y_offset))
            
            # 记录 bbox [x1, y1, x2, y2]
            bbox_dict[sheet_id] = [
                current_width,
                y_offset,
                current_width + img.width,
                y_offset + img.height
            ]
            
            # 移动到下一个位置（图片宽度 + 间隔条宽度）
            current_width += img.width
            if i < len(images) - 1:  # 最后一张图片后面不需要间隔
                current_width += SEPARATOR_WIDTH
        
        stitched.save(output_path)
        print(f"  拼接长图已保存至：{output_path}")
        print(f"  拼接方式：水平拼接（{len(images)}张图片，间隔条宽度={SEPARATOR_WIDTH}px）")
    else:
        print("  警告：没有图片可拼接")
    
    return output_path, bbox_dict

def find_sheet_by_bbox(sheet_metadata_list: list, bbox: list) -> dict:
    """
    通过边界框找到对应的试卷纸元数据
    
    Args:
        sheet_metadata_list: 试卷纸元数据列表
        bbox: 边界框 [x1, y1, x2, y2]
        
    Returns:
        对应的试卷纸元数据
    """
    # 简化匹配：根据原始顺序匹配
    # 实际项目中可能需要更复杂的匹配逻辑
    for sheet_meta in sheet_metadata_list:
        return sheet_meta
    return None

def parse_api_response(response: str) -> list:
    """
    解析大模型 API 响应
    
    Args:
        response: API 响应
        
    Returns:
        分类结果列表
    """
    json_str = extract_json(response)
    if json_str:
        result = json.loads(json_str)
        # 确保返回格式正确
        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and 'sheets' in result:
            return result['sheets']
    return []


def _safe_int(value, default=None):
    """安全地将值转换为整数。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _next_available_physical_index(used_indices: set, total_sheets: int) -> int:
    """获取尚未使用的物理位置索引。"""
    for candidate in range(total_sheets):
        if candidate not in used_indices:
            return candidate
    return max(total_sheets - 1, 0)


def normalize_classification_results(classification_results: list, total_sheets: int) -> list:
    """
    规范化长图分类结果。

    重点保证：
    - `physical_index` 永远指向长图中的物理位置（从左到右，0-based）
    - 返回数组允许按逻辑顺序排列，但后续绑定图片时必须用 `physical_index`
    """
    normalized_results = []
    used_indices = set()

    for fallback_idx, result in enumerate(classification_results):
        normalized_result = dict(result) if isinstance(result, dict) else {}

        physical_index = _safe_int(normalized_result.get('physical_index'))
        if physical_index is None or physical_index < 0 or physical_index >= total_sheets or physical_index in used_indices:
            replacement_index = _next_available_physical_index(used_indices, total_sheets)
            print(
                f"  [警告] 第 {fallback_idx + 1} 个分类结果的 physical_index={normalized_result.get('physical_index')} 无效，"
                f"回退为 {replacement_index}"
            )
            physical_index = replacement_index

        used_indices.add(physical_index)
        normalized_result['physical_index'] = physical_index
        normalized_result['order'] = _safe_int(normalized_result.get('order'), fallback_idx + 1)
        normalized_results.append(normalized_result)

    return normalized_results


def _default_reason(chinese_type: str) -> str:
    if chinese_type == '答题纸':
        return '该纸以答题区域或手写作答内容为主'
    if chinese_type == '题目和答题混合纸':
        return '该纸同时出现题目内容与答题区域'
    return '该纸以题目内容为主，未见明确独立答题卡版式'


def _dedupe_features(features: list[str]) -> list[str]:
    seen = set()
    result = []
    for feature in features:
        if feature and feature not in seen:
            seen.add(feature)
            result.append(feature)
    return result


def sanitize_reason(reason: str, chinese_type: str) -> str:
    source = (reason or '').strip()
    if not source:
        return _default_reason(chinese_type)

    features = []
    if re.search(r'答题卡|填涂', source):
        features.append('填涂区')
    if re.search(r'答题框|答题区域|作答区域|作答区|基本信息区|非选择题', source):
        features.append('答题区域')
    if re.search(r'手写|解答过程|作答', source):
        features.append('手写作答')
    if re.search(r'题目|题干|选择题|填空题|解答题|题号', source):
        features.append('题目内容')
    if re.search(r'密封线', source):
        features.append('密封线')
    if re.search(r'姓名|准考证|条形码|基本信息', source):
        features.append('基本信息区')

    features = _dedupe_features(features)

    if chinese_type == '答题纸':
        preferred = [feature for feature in ['填涂区', '答题区域', '手写作答', '基本信息区'] if feature in features]
        if not preferred:
            return _default_reason(chinese_type)
        return f"该纸以{'、'.join(preferred[:3])}为主"

    if chinese_type == '题目和答题混合纸':
        preferred = [feature for feature in ['题目内容', '填涂区', '答题区域', '手写作答'] if feature in features]
        if len(preferred) < 2:
            return _default_reason(chinese_type)
        return f"该纸同时出现{'、'.join(preferred[:3])}"

    preferred = [feature for feature in ['题目内容', '密封线', '基本信息区'] if feature in features]
    if '题目内容' not in preferred:
        preferred.insert(0, '题目内容')
    return f"该纸以{'、'.join(_dedupe_features(preferred)[:3])}为主，未见明确独立答题卡版式"


def save_classification_output(workspace_dir: str, output: dict):
    """
    保存分类结果
    
    Args:
        workspace_dir: 工作目录
        output: 分类结果
    """
    output_path = os.path.join(workspace_dir, '02_classify_output.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"  分类结果已保存至：{output_path}")

def run_long_image_classification(workspace_dir: str, image_path_manager=None, db_session=None, prompt=None, api_key=None, model_name=None, api_url=None, logger=None) -> dict:
    """
    基于拼接长图的页面类型分类
    
    Args:
        workspace_dir: 工作目录
        image_path_manager: 图片路径管理器
        db_session: 数据库会话
        api_key: API 密钥
        model_name: 模型名称
        api_url: API URL
        logger: 日志记录器
        
    Returns:
        分类结果字典
    """
    print("  Starting long image classification...")
    
    # 1. 从步骤 1 获取矫正结果和元数据
    correction_output = load_correction_output(workspace_dir)
    set_id = correction_output['set_id']
    sheet_metadata_list = correction_output['sheet_metadata']
    
    print(f"  Set ID: {set_id}")
    print(f"  Processing {len(sheet_metadata_list)} sheets")
    
    # 2. 按任意顺序拼接成长图（拼接顺序不影响最终顺序判断）
    stitched_image_path = os.path.join(workspace_dir, 'stitched_images', f'{set_id}_stitched.jpg')
    stitched_image_path, bbox_dict = stitch_images(
        sheet_metadata_list, 
        output_path=stitched_image_path
    )
    
    # 填充 bbox_in_stitched 字段
    for sheet_meta in sheet_metadata_list:
        sheet_id = sheet_meta.get('sheet_id')
        if sheet_id and sheet_id in bbox_dict:
            sheet_meta['bbox_in_stitched'] = bbox_dict[sheet_id]
    
    # 3. 调用大模型 API
    num_sheets = len(sheet_metadata_list)
    if prompt:
        prompt = prompt.replace('[[num_sheets]]', str(num_sheets))
    else:
        prompt = get_seed_prompt_text(
            "preprocessor.long_image_classification.default",
            variables={"num_sheets": num_sheets},
        )
    if not prompt:
        raise ValueError("未找到长图分类提示词")
    
    print("  Calling API for long image classification...")
    
    # 重试逻辑
    max_retries = 3
    api_response = None
    attempt = 0
    
    while attempt < max_retries:
        attempt += 1
        
        if attempt == 1:
            print(f"  [尝试] 第 1 次调用长图分类（共{max_retries}次机会）")
        else:
            print(f"  [重试] 第 {attempt} 次重试长图分类（共{max_retries}次机会）")
        
        try:
            api_response = call_api(
                prompt=prompt,
                image_path=stitched_image_path,
                api_url=api_url,
                api_key=api_key,
                model_name=model_name,
                logger=logger,
                step_name="long_image_classification",
                min_content_length=100  # 长图分类需要返回多个结果，设置较高的最小长度
            )
            print(f"  [成功] 第 {attempt} 次调用成功")
            break  # 成功则跳出重试循环
        except Exception as e:
            if attempt < max_retries:
                print(f"  [警告] 第 {attempt} 次调用失败：{e}，准备重试...")
            else:
                print(f"  [错误] 已达最大重试次数 ({max_retries})，长图分类失败：{e}")
                raise  # 所有重试都失败，抛出异常
    
    # 4. 解析返回结果
    classification_results = parse_api_response(api_response)
    
    # 保存大模型的原始返回
    raw_response_path = os.path.join(workspace_dir, '02_classify_raw_response.json')
    os.makedirs(os.path.dirname(raw_response_path), exist_ok=True)
    with open(raw_response_path, 'w', encoding='utf-8') as f:
        json.dump({
            'raw_api_response': api_response,
            'parsed_results': classification_results
        }, f, ensure_ascii=False, indent=2)
    print(f"  大模型原始返回已保存至：{raw_response_path}")
    
    # 5. 关联元数据
    # 关键原则：classification_results 允许按逻辑顺序返回，但图片绑定必须使用 physical_index
    # 中文类型到英文类型的映射（用于数据库提示词查找）
    type_mapping = {
        '题目纸': 'question_paper',
        '答题纸': 'answer_sheet',
        '题目和答题混合纸': 'mixed'
    }
    normalized_results = normalize_classification_results(classification_results, len(sheet_metadata_list))
    assigned_sheet_ids = set()

    for fallback_idx, result in enumerate(normalized_results):
        physical_index = result.get('physical_index', fallback_idx)
        if physical_index >= len(sheet_metadata_list):
            continue

        sheet_meta = sheet_metadata_list[physical_index]
        assigned_sheet_ids.add(sheet_meta.get('sheet_id'))

        chinese_type = result.get('type', '题目纸')
        english_type = type_mapping.get(chinese_type, 'question_paper')
        raw_reason = result.get('reason', '')
        sheet_meta['sheet_type'] = english_type
        sheet_meta['sheet_type_cn'] = chinese_type
        sheet_meta['order'] = _safe_int(result.get('order'), fallback_idx + 1)
        sheet_meta['physical_index'] = physical_index
        sheet_meta['reason'] = sanitize_reason(raw_reason, chinese_type)
        # bbox_in_stitched 已经在拼接时填充，不需要从大模型返回

    for physical_index, sheet_meta in enumerate(sheet_metadata_list):
        if sheet_meta.get('sheet_id') in assigned_sheet_ids:
            continue

        print(f"  [警告] 试卷纸 {sheet_meta.get('sheet_id')} 未获得分类结果，使用默认兜底值")
        sheet_meta.setdefault('sheet_type', 'question_paper')
        sheet_meta.setdefault('sheet_type_cn', '题目纸')
        sheet_meta.setdefault('order', sheet_meta.get('original_order', physical_index + 1))
        sheet_meta.setdefault('physical_index', physical_index)
        sheet_meta.setdefault('reason', '缺少有效分类结果，已按默认题目纸处理')

    # 6. 按照大模型判断的逻辑顺序重新排序
    sheet_metadata_list.sort(key=lambda x: (x.get('order', 9999), x.get('physical_index', 9999)))
    
    # 7. 保存结果
    output = {
        'set_id': set_id,
        'stitched_image_path': stitched_image_path,
        'sheets': sheet_metadata_list
    }
    
    save_classification_output(workspace_dir, output)
    
    print(f"  Long image classification completed successfully")
    return output

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Run long image classification')
    parser.add_argument('--workspace-dir', required=True, help='Workspace directory')
    parser.add_argument('--api-key', required=True, help='API key')
    parser.add_argument('--model-name', default='qwen3.5-plus', help='Model name')
    parser.add_argument('--api-url', default='https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions', help='API URL')
    args = parser.parse_args()
    
    run_long_image_classification(
        workspace_dir=args.workspace_dir,
        api_key=args.api_key,
        model_name=args.model_name,
        api_url=args.api_url
    )
