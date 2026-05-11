import os
from PIL import Image

class PagePart:
    def __init__(self, part_type, image_path, crop_area):
        self.part_type = part_type
        self.image_path = image_path
        self.crop_area = crop_area

class A3Splitter:
    """
    A3 试卷分割器，支持两种模式：
    - split: 分割成左右两部分（方案 A）
    - whole: 整体识别，不分割（方案 B）
    """
    
    def __init__(self, strategy='split'):
        """
        Args:
            strategy: 'split' | 'whole'
                - split: 分割成左右两部分
                - whole: 整体识别，不分割
        """
        self.strategy = strategy

    def process_a3_page(self, image_path):
        """
        统一入口，根据策略决定处理方式
        
        Returns:
            - split 模式：[PagePart(left), PagePart(right)]
            - whole 模式：[PagePart(whole)]
        """
        if self.strategy == 'split':
            return self.split_a3_page(image_path)
        elif self.strategy == 'whole':
            return self.treat_as_whole(image_path)
        else:
            # 默认使用 split 模式
            return self.split_a3_page(image_path)
    
    def treat_as_whole(self, image_path):
        """将 A3 作为整体处理（不分割）"""
        if not os.path.exists(image_path):
            raise ValueError(f"Image not found: {image_path}")
        
        with Image.open(image_path) as img:
            width, height = img.size
        
        # 返回整个图像作为一个 part
        return [
            PagePart(
                part_type='whole',
                image_path=image_path,
                crop_area=(0, 0, width, height)
            )
        ]

    def split_a3_page(self, image_path):
        if not os.path.exists(image_path):
            raise ValueError(f"Image not found: {image_path}")

        with Image.open(image_path) as img:
            width, height = img.size

            # 稳定逻辑：检测是否为 A3 双页（宽高比 > 1.4）
            if width / height > 1.4:  # A3 横向假设
                # 添加 gutter_overlap (5% 重叠)
                gutter_overlap = int(width * 0.05)
                mid = width // 2

                left_crop = (0, 0, mid + gutter_overlap, height)
                right_crop = (mid - gutter_overlap, 0, width, height)

                # 保存临时分割图像
                base_dir = os.path.dirname(image_path)
                # Get the file extension
                base_name, ext = os.path.splitext(os.path.basename(image_path))
                left_path = os.path.join(base_dir, f"{base_name}_left{ext}")
                right_path = os.path.join(base_dir, f"{base_name}_right{ext}")

                img.crop(left_crop).save(left_path)
                img.crop(right_crop).save(right_path)

                return [
                    PagePart("left", left_path, left_crop),
                    PagePart("right", right_path, right_crop)
                ]
            else:
                # 非 A3，返回 None 或单部分
                return None

    def analyze_layout(self, image_path):
        """
        分析布局，根据策略返回不同的 parts
        
        Returns:
            dict: {
                "original_image_path": str,
                "is_a3": bool,
                "strategy": str,  # 'split' | 'whole'
                "parts": list
            }
        """
        parts = self.process_a3_page(image_path)
        layout = {
            "original_image_path": image_path,
            "is_a3": bool(parts),
            "strategy": self.strategy,
            "parts": []
        }
        
        for part in parts:
            layout["parts"].append({
                "part_type": part.part_type,
                "image_path": part.image_path,
                "crop_area": part.crop_area
            })
        
        return layout
