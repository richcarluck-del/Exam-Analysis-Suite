
import argparse
import json
import os
import sys
import cv2
import numpy as np
from pathlib import Path

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from ..utils import call_api, extract_json
from ..utils.set_id_generator import generate_set_id
from ..utils.sheet_id_generator import generate_sheet_id
from ..utils.layout_detector import detect_sheet_layout
from shared.prompt_step_config import get_seed_prompt_text


# Import SheetMetadata directly from sheet_metadata.py to avoid circular import
current_dir = Path(__file__).parent
sheet_metadata_path = current_dir.parent / "models" / "sheet_metadata.py"
if sheet_metadata_path.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sheet_metadata_module", sheet_metadata_path)
    sheet_metadata_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sheet_metadata_module)
    SheetMetadata = sheet_metadata_module.SheetMetadata
else:
    raise ImportError(f"sheet_metadata.py not found at {sheet_metadata_path}")

class PerspectiveCorrector:
    """试卷视角矫正器：利用 VLM 定位四角并进行透视变换"""
    
    def __init__(self, prompt=None):
        self.prompt = prompt or get_seed_prompt_text("preprocessor.perspective_correction.default") or ""


    def detect_corners(self, image_path: str, api_key: str, model_name: str, api_url: str, logger=None, max_retries: int = 3) -> dict:
        """
        调用 VLM 检测四角（带重试机制）
        
        Args:
            image_path: 图片路径
            api_key: API 密钥
            model_name: 模型名称
            api_url: API 地址
            logger: 日志记录器
            max_retries: 最大重试次数（默认 3 次）
            
        Returns:
            包含角点信息的字典，失败返回空字典
        """
        attempt = 0
        last_error = None
        
        while attempt < max_retries:
            attempt += 1
            
            if attempt == 1:
                print(f"      [尝试] 第 1 次调用（共{max_retries}次机会）")
            else:
                print(f"      [重试] 第 {attempt} 次重试（共{max_retries}次机会）")
            
            try:
                content = call_api(
                    prompt=self.prompt, 
                    image_path=image_path, 
                    api_url=api_url, 
                    api_key=api_key, 
                    model_name=model_name,
                    logger=logger,
                    step_name="perspective_correction",
                    min_content_length=50  # 透视矫正需要返回 JSON，设置较高的最小长度
                )
                
                # 注意：空结果和少字数判断已经在 call_api 中处理，这里保留检查作为双重保障
                if not content or content.strip() == "":
                    if attempt < max_retries:
                        print(f"      [警告] 第 {attempt} 次调用返回空结果，准备重试...")
                        continue
                    else:
                        print(f"      [错误] 已达最大重试次数 ({max_retries})，API 仍返回空结果")
                        return {}
                
                json_str = extract_json(content)
                
                if not json_str:
                    if attempt < max_retries:
                        print(f"      [警告] 第 {attempt} 次调用无法提取 JSON，准备重试...")
                        continue
                    else:
                        print(f"      [错误] 已达最大重试次数 ({max_retries})，仍无法提取 JSON")
                        return {}
                
                try:
                    data = json.loads(json_str)
                    print(f"      [成功] 第 {attempt} 次调用成功解析 JSON")
                    return data
                except json.JSONDecodeError as e:
                    last_error = e
                    if attempt < max_retries:
                        print(f"      [警告] 第 {attempt} 次调用 JSON 解析失败：{e}，准备重试...")
                        continue
                    else:
                        print(f"      [错误] 已达最大重试次数 ({max_retries})，JSON 解析失败：{e}")
                        return {}
                        
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    print(f"      [警告] 第 {attempt} 次调用异常：{e}，准备重试...")
                    continue
                else:
                    print(f"      [错误] 已达最大重试次数 ({max_retries})，异常：{e}")
                    return {}
        
        # 理论上不会到这里，但为了完整性
        print(f"      [错误] 所有 {max_retries} 次尝试均失败")
        return {}

    def warp_perspective(self, image_path: str, corners: dict, output_path: str, padding_ratio: float = 0.01) -> str:
        """执行透视变换，包含外扩安全垫逻辑"""
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图片: {image_path}")
            
        h, w = img.shape[:2]
        
        # 1. 归一化坐标转像素坐标
        def to_pixel(point):
            return np.array([float(point[0] * w / 1000), float(point[1] * h / 1000)])
            
        pts_orig = np.array([
            to_pixel(corners["top_left"]),
            to_pixel(corners["top_right"]),
            to_pixel(corners["bottom_right"]),
            to_pixel(corners["bottom_left"])
        ], dtype=np.float32)

        # 2. 核心优化：向外推移顶点 (Padding 逻辑)
        center = np.mean(pts_orig, axis=0)
        
        pts_padded = []
        for pt in pts_orig:
            vec = pt - center
            pt_new = center + vec * (1.0 + padding_ratio)
            pt_new[0] = np.clip(pt_new[0], 0, w - 1)
            pt_new[1] = np.clip(pt_new[1], 0, h - 1)
            pts_padded.append(pt_new)
        
        pts1 = np.array(pts_padded, dtype=np.float32)
        
        # 3. 估算目标尺寸（使用平均值，减少畸变）
        width_top = np.linalg.norm(pts1[0] - pts1[1])
        width_bottom = np.linalg.norm(pts1[2] - pts1[3])
        avg_width = int((width_top + width_bottom) / 2)
        
        height_left = np.linalg.norm(pts1[0] - pts1[3])
        height_right = np.linalg.norm(pts1[1] - pts1[2])
        avg_height = int((height_left + height_right) / 2)
        
        # 4. 构建严格矩形的目标坐标（确保垂直和水平）
        pts2 = np.float32([
            [0, 0],
            [avg_width, 0],
            [avg_width, avg_height],
            [0, avg_height]
        ])
        
        # 5. 矩阵变换
        matrix = cv2.getPerspectiveTransform(pts1, pts2)
        result = cv2.warpPerspective(img, matrix, (avg_width, avg_height))
            
        cv2.imwrite(output_path, result)
        print(f"  [成功] 视角矫正完成，已保存至: {output_path}")
        return output_path

def run_perspective_correction(image_paths: list[str], output_path: str, prompt=None, api_key: str = None, model_name: str = None, api_url: str = None, image_path_manager=None, logger=None):
    """
    对输入的图片列表进行视角矫正，并生成套-张编号系统。
    
    Args:
        image_paths: 图片路径列表（可能是压缩后的路径）
        output_path: 输出文件路径
        prompt: 提示词（可选，如果为 None 则使用默认提示词）
        api_key: API 密钥
        model_name: 模型名称
        api_url: API URL
        image_path_manager: ImagePathManager 实例，用于获取原始图片路径（用于透视矫正需要高清图片）
    """
    print(f"  Starting perspective correction for {len(image_paths)} images...")
    
    # 1. 生成套编号
    set_id = generate_set_id()
    print(f"  Generated set ID: {set_id}")
    
    corrector = PerspectiveCorrector(prompt)
    correction_map = []
    sheet_metadata_list = []
    
    corrected_images_dir = os.path.join(os.path.dirname(output_path), 'corrected_images')
    os.makedirs(corrected_images_dir, exist_ok=True)

    for idx, image_path in enumerate(image_paths, start=1):
        print(f"    Processing: {os.path.basename(image_path)}")
        
        # 2. 生成张编号
        sheet_id = generate_sheet_id(set_id, idx)
        
        # 透视矫正需要高清图片，使用原始图片路径
        if image_path_manager:
            original_image_path = image_path_manager.get_image_path(image_path, use_original=True)
        else:
            original_image_path = image_path
        
        try:
            corner_result = corrector.detect_corners(
                original_image_path, 
                api_key, 
                model_name, 
                api_url, 
                logger,
                max_retries=3  # 最多重试 3 次
            )
            
            if not corner_result or "corners" not in corner_result:
                print(f"      [警告] VLM 未能检测到 '{os.path.basename(image_path)}' 的角点，跳过矫正。")
                corrected_image_path = image_path
            else:
                p = Path(image_path)
                corrected_filename = f"{p.stem}_corrected{p.suffix}"
                corrected_image_output_path = os.path.join(corrected_images_dir, corrected_filename)
                
                corrected_image_path = corrector.warp_perspective(
                    image_path, 
                    corner_result["corners"], 
                    corrected_image_output_path
                )

            correction_map.append({
                "original_image_path": image_path,
                "corrected_image_path": corrected_image_path
            })

            # 3. 检测布局
            layout = detect_sheet_layout(image_path)
            
            # 4. 创建元数据（order 暂时为 None，等待大模型判断）
            metadata = SheetMetadata(
                set_id=set_id,
                sheet_id=sheet_id,
                order=None,  # 暂时为空
                original_order=idx,  # 记录原始输入顺序
                layout=layout,
                original_image=image_path,
                corrected_image=corrected_image_path
            )
            
            sheet_metadata_list.append(metadata.to_dict())

        except Exception as e:
            print(f"      [错误] 在处理 '{os.path.basename(image_path)}' 时发生异常: {e}")
            print("        将使用原始图片继续流程。")
            corrected_image_path = image_path
            
            correction_map.append({
                "original_image_path": image_path,
                "corrected_image_path": corrected_image_path
            })
            
            # 即使出错也要创建元数据
            layout = detect_sheet_layout(image_path)
            metadata = SheetMetadata(
                set_id=set_id,
                sheet_id=sheet_id,
                order=None,
                original_order=idx,
                layout=layout,
                original_image=image_path,
                corrected_image=corrected_image_path
            )
            sheet_metadata_list.append(metadata.to_dict())

    # 5. 构建输出结果
    output = {
        'set_id': set_id,
        'correction_map': correction_map,
        'sheet_metadata': sheet_metadata_list
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        
    print(f"  Perspective correction results saved to: {output_path}")
    return output_path

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Run perspective correction on raw images.')
    parser.add_argument('--input-dir', required=True, help='Directory containing the raw images.')
    parser.add_argument('--output', required=True, help='Path to save the output JSON map file.')
    parser.add_argument('--api-key', required=True, help='API key for the VLM service.')
    parser.add_argument('--model-name', default='qwen-vl-max', help='Model name for the VLM service.')
    parser.add_argument('--api-url', default='https://dashscope.aliyuncs.com/api/v1/services/multimodal/generation/generation', help='API URL for the VLM service.')
    args = parser.parse_args()

    image_files = [os.path.join(args.input_dir, f) for f in os.listdir(args.input_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    run_perspective_correction(
        image_paths=image_files, 
        output_path=args.output,
        api_key=args.api_key,
        model_name=args.model_name,
        api_url=args.api_url
    )
