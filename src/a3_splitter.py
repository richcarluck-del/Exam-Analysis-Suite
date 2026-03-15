import os
from PIL import Image

class PagePart:
    def __init__(self, part_type, image_path, crop_area):
        self.part_type = part_type
        self.image_path = image_path
        self.crop_area = crop_area

class A3Splitter:
    def __init__(self):
        pass  # 可以添加 VLM 或其他初始化，如果需要

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
        parts = self.split_a3_page(image_path)
        layout = {
            "original_image_path": image_path,
            "is_a3": bool(parts),
            "parts": []
        }
        if parts:
            for part in parts:
                layout["parts"].append({
                    "part_type": part.part_type,
                    "image_path": part.image_path,
                    "crop_area": part.crop_area
                })
        else:
            with Image.open(image_path) as img:
                width, height = img.size
            layout["parts"].append({
                "part_type": "full",
                "image_path": image_path,
                "crop_area": (0, 0, width, height)
            })
        return layout
