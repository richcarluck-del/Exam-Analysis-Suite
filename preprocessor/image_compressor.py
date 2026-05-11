"""
图片压缩工具类 - 适配 Qwen-VL 模型
目标：在保证识别准确性的前提下，减少图片体积和 Token 消耗
"""
import os
from PIL import Image
import io

class ImageCompressor:
    """图片压缩器，针对 Qwen-VL 模型优化"""
    
    # Qwen-VL 的最佳像素配置
    MAX_PIXELS_DEFAULT = 3686400  # 默认上限：2560×1440（优化后）
    MAX_PIXELS_HIGH = 5760000     # 高分辨率上限：3200×1800（优化后）
    
    # 压缩质量建议（2026-03-16 更新 - 提升质量减少模糊）
    QUALITY_HIGH = 98      # 超高质量（接近无损，适合有细小文字）
    QUALITY_MEDIUM = 92    # 中高质量（清晰度和体积平衡，新推荐）
    QUALITY_LOW = 85       # 中等质量（体积优先，适合简单场景）
    
    @staticmethod
    def compress_image(
        image_path: str, 
        output_path: str = None,
        max_width: int = 1920,
        max_height: int = 1080,
        quality: int = 85,
        return_info: bool = False
    ):
        """
        压缩图片，优化用于 Qwen-VL 模型
        
        Args:
            image_path: 原始图片路径
            output_path: 输出图片路径（可选，如果为 None 则返回 bytes）
            max_width: 最大宽度（默认 2560，优化后）
            max_height: 最大高度（默认 1440，优化后）
            quality: JPEG 压缩质量（1-100，推荐 92，优化后）
            return_info: 是否返回压缩信息
            
        Returns:
            如果 output_path 为 None，返回压缩后的 bytes
            否则返回输出路径
            如果 return_info 为 True，返回 (result, info_dict)
        """
        # 打开图片
        with Image.open(image_path) as img:
            # 获取原始信息
            original_width, original_height = img.size
            original_size = os.path.getsize(image_path)
            original_pixels = original_width * original_height
            
            # 转换为 RGB（处理 PNG 等格式）
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # 计算缩放比例
            scale = min(max_width / original_width, max_height / original_height, 1.0)
            
            # 应用缩放
            if scale < 1.0:
                new_width = int(original_width * scale)
                new_height = int(original_height * scale)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 确保像素不超过上限
            current_pixels = img.width * img.height
            if current_pixels > ImageCompressor.MAX_PIXELS_DEFAULT:
                scale_factor = (ImageCompressor.MAX_PIXELS_DEFAULT / current_pixels) ** 0.5
                new_width = int(img.width * scale_factor)
                new_height = int(img.height * scale_factor)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # 压缩并保存
            buffer = io.BytesIO()
            img.save(
                buffer, 
                format='JPEG', 
                quality=quality, 
                optimize=True, 
                progressive=True
            )
            
            # 获取压缩后大小
            compressed_size = len(buffer.getvalue())
            compressed_pixels = img.width * img.height
            
            # 准备信息
            info = {
                'original': {
                    'width': original_width,
                    'height': original_height,
                    'size': original_size,
                    'pixels': original_pixels
                },
                'compressed': {
                    'width': img.width,
                    'height': img.height,
                    'size': compressed_size,
                    'pixels': compressed_pixels
                },
                'reduction': {
                    'size_ratio': f"{(1 - compressed_size / original_size) * 100:.1f}%",
                    'pixel_ratio': f"{(1 - compressed_pixels / original_pixels) * 100:.1f}%",
                    'estimated_token_reduction': f"{(1 - compressed_pixels / original_pixels) * 100:.1f}%"
                }
            }
            
            # 保存或返回
            if output_path:
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(buffer.getvalue())
                result = output_path
            else:
                result = buffer.getvalue()
            
            if return_info:
                return result, info
            return result
    
    @staticmethod
    def estimate_tokens(image_path: str):
        """
        估算图片的视觉 Token 数量
        
        Token 计算规则：每 32×32 = 1024 像素 = 1 个 Token
        
        Args:
            image_path: 图片路径
            
        Returns:
            估算的 Token 数量
        """
        with Image.open(image_path) as img:
            width, height = img.size
            pixels = width * height
            # 每 1024 像素 = 1 Token
            tokens = pixels // 1024
            return tokens


def test_compression():
    """测试压缩效果"""
    import sys
    
    # 测试图片路径
    test_image = r"D:\10739\Exam-Analysis-Suite\preprocessor\my_test_images\1.jpg"
    
    if not os.path.exists(test_image):
        print(f"测试图片不存在：{test_image}")
        return
    
    print("="*60)
    print("图片压缩测试")
    print("="*60)
    
    # 原始信息
    original_size = os.path.getsize(test_image)
    original_tokens = ImageCompressor.estimate_tokens(test_image)
    print(f"\n原始图片:")
    print(f"  大小：{original_size / 1024:.2f} KB")
    print(f"  Token 估算：{original_tokens:,}")
    
    # 测试不同质量
    for quality in [95, 85, 75]:
        print(f"\n--- 质量：{quality}% ---")
        compressed, info = ImageCompressor.compress_image(
            test_image,
            max_width=1920,
            max_height=1080,
            quality=quality,
            return_info=True
        )
        
        print(f"  压缩后大小：{info['compressed']['size'] / 1024:.2f} KB")
        print(f"  体积减少：{info['reduction']['size_ratio']}")
        print(f"  像素减少：{info['reduction']['pixel_ratio']}")
        print(f"  Token 减少：{info['reduction']['estimated_token_reduction']}")
        print(f"  估算 Token: {ImageCompressor.estimate_tokens(test_image):,}")
    
    print("\n" + "="*60)
    print("推荐配置 (2026-03-16 更新):")
    print("  - 标准质量：92%（清晰度和体积平衡，新推荐）")
    print("  - 标准分辨率：2560×1440（优化后，减少模糊）")
    print("  - 高分辨率：3200×1800 + 质量 98%（有细小文字）")
    print("  - 低体积模式：85%（体积优先，简单场景）")
    print("="*60)


if __name__ == "__main__":
    test_compression()
