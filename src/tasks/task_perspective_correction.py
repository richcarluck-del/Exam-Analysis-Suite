
import argparse
import json
import os
import sys
import cv2
import numpy as np
from pathlib import Path

# Add project root to Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.utils import call_api, extract_json

class PerspectiveCorrector:
    """试卷视角矫正器：利用 VLM 定位四角并进行透视变换"""
    
    def __init__(self):
        self.prompt = """你是一个图像处理助手。请识别这张图片中【试卷】或【答题卡】的四个顶点。

### 任务要求：
1. 找到试卷的最外围边缘的四个角。
2. 按照以下顺序输出归一化坐标 [x, y] (范围 0-1000)：
   - 左上角 (top_left)
   - 右上角 (top_right)
   - 右下角 (bottom_right)
   - 左下角 (bottom_left)
3. 确保坐标的几何正确性：
   - top_left.x < top_right.x
   - bottom_left.x < bottom_right.x
   - top_left.y < bottom_left.y
   - top_right.y < bottom_right.y
   - abs(top_left.y - top_right.y) <= 15  // 顶部边缘应大致水平
   - abs(bottom_left.y - bottom_right.y) <= 15 // 底部边缘应大致水平
   - abs(top_left.x - bottom_left.x) <= 15  // 左侧边缘应大致垂直
   - abs(top_right.x - bottom_right.x) <= 15 // 右侧边缘应大致垂直

### 输出格式：
请仅返回 JSON：
{
  "corners": {
    "top_left": [x, y],
    "top_right": [x, y],
    "bottom_right": [x, y],
    "bottom_left": [x, y]
  },
  "has_perspective_distortion": true/false
}
        """

    def detect_corners(self, image_path: str, api_key: str, model_name: str, api_url: str) -> dict:
        """调用 VLM 检测四角"""
        content = call_api(
            prompt=self.prompt, 
            image_path=image_path, 
            api_url=api_url, 
            api_key=api_key, 
            model_name=model_name
        )
        json_str = extract_json(content)
        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError:
            print(f"      [错误] 无法解析 VLM 返回的 JSON: {json_str}")
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
        
        # 3. 估算目标尺寸
        width_top = np.linalg.norm(pts1[0] - pts1[1])
        width_bottom = np.linalg.norm(pts1[2] - pts1[3])
        max_width = int(max(width_top, width_bottom))
        
        height_left = np.linalg.norm(pts1[0] - pts1[3])
        height_right = np.linalg.norm(pts1[1] - pts1[2])
        max_height = int(max(height_left, height_right))
        
        pts2 = np.float32([
            [0, 0],
            [max_width, 0],
            [max_width, max_height],
            [0, max_height]
        ])
        
        # 4. 矩阵变换
        matrix = cv2.getPerspectiveTransform(pts1, pts2)
        result = cv2.warpPerspective(img, matrix, (max_width, max_height))
            
        cv2.imwrite(output_path, result)
        print(f"  [成功] 视角矫正完成，已保存至: {output_path}")
        return output_path

def run_perspective_correction(image_paths: list[str], output_path: str, api_key: str, model_name: str, api_url: str):
    """
    对输入的原始图片列表进行视角矫正。
    """
    print(f"  Starting perspective correction for {len(image_paths)} raw images...")
    
    corrector = PerspectiveCorrector()
    correction_map = []
    
    corrected_images_dir = os.path.join(os.path.dirname(output_path), 'corrected_images')
    os.makedirs(corrected_images_dir, exist_ok=True)

    for image_path in image_paths:
        print(f"    Processing: {os.path.basename(image_path)}")
        
        try:
            corner_result = corrector.detect_corners(image_path, api_key, model_name, api_url)
            
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

        except Exception as e:
            print(f"      [错误] 在处理 '{os.path.basename(image_path)}' 时发生异常: {e}")
            print("        将使用原始图片继续流程。")
            correction_map.append({
                "original_image_path": image_path,
                "corrected_image_path": image_path
            })

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(correction_map, f, indent=2, ensure_ascii=False)
        
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
