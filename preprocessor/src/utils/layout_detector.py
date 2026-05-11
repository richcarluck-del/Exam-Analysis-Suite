from PIL import Image
import sys
from pathlib import Path

# Import LayoutType directly from sheet_metadata.py to avoid circular import
current_dir = Path(__file__).parent
sheet_metadata_path = current_dir.parent / "models" / "sheet_metadata.py"
if sheet_metadata_path.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sheet_metadata_module", sheet_metadata_path)
    sheet_metadata_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sheet_metadata_module)
    LayoutType = sheet_metadata_module.LayoutType
else:
    raise ImportError(f"sheet_metadata.py not found at {sheet_metadata_path}")

def detect_sheet_layout(image_path: str) -> str:
    """
    检测试卷纸的布局类型
    
    Args:
        image_path: 图片路径
        
    Returns:
        LayoutType 枚举值
        
    判断逻辑：
    1. 检测图片宽高比
    2. 如果 width/height ≈ 2 (A3 横向)，返回 LEFT_RIGHT
    3. 如果 width/height ≈ 0.5 (A3 纵向)，需要进一步判断左右页
    4. 否则返回 FULL_PAGE (A4)
    """
    with Image.open(image_path) as img:
        width, height = img.size
        aspect_ratio = width / height
        
        if 1.8 <= aspect_ratio <= 2.2:
            # A3 横向展开
            return LayoutType.LEFT_RIGHT
        elif aspect_ratio < 0.7:
            # A3 纵向，可能是左页或右页
            # TODO: 通过内容分析判断是左页还是右页
            return LayoutType.LEFT_PAGE  # 暂时默认左页
        else:
            # A4 或接近正方形
            return LayoutType.FULL_PAGE
