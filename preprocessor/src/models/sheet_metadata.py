from dataclasses import dataclass
from typing import Optional
from enum import Enum

class SheetType(Enum):
    QUESTION_PAGE = "question_page"      # 题目页
    ANSWER_SHEET = "answer_sheet"        # 答题纸
    MIXED_PAGE = "mixed_page"           # 混合页

class LayoutType(Enum):
    LEFT_PAGE = "left"       # 左页（A3 左半部分）
    RIGHT_PAGE = "right"      # 右页（A3 右半部分）
    FULL_PAGE = "full"        # 整页（A4 或 A3 整张）
    LEFT_RIGHT = "left_right" # 左右双页（A3 展开）

@dataclass
class SheetMetadata:
    """
    试卷纸元数据
    
    Attributes:
        set_id: 套编号，唯一标识一套试卷（如 "SET_20260320_001"）
        sheet_id: 张编号，物理层面的试卷纸编号（如 "SHEET_001"）
        order: 张顺序（由大模型根据内容逻辑判断，从 1 开始）
        original_order: 原始输入顺序（仅作为参考，不用于最终排序）
        sheet_type: 张类型（题目页/答题纸/混合页）
        layout: 布局类型（左页/右页/整页/左右双页）
        original_image: 原始图片路径
        corrected_image: 矫正后图片路径
        bbox_in_stitched: 在拼接长图中的边界坐标 [x1, y1, x2, y2]
    """
    set_id: str
    sheet_id: str
    order: Optional[int] = None  # 由大模型判断
    original_order: int = 0      # 原始输入顺序，仅供参考
    sheet_type: Optional[SheetType] = None
    layout: Optional[LayoutType] = None
    original_image: str = ""
    corrected_image: str = ""
    bbox_in_stitched: Optional[list] = None
    
    def to_dict(self) -> dict:
        return {
            'set_id': self.set_id,
            'sheet_id': self.sheet_id,
            'order': self.order,
            'original_order': self.original_order,
            'sheet_type': self.sheet_type.value if self.sheet_type else None,
            'layout': self.layout.value if self.layout else None,
            'original_image': self.original_image,
            'corrected_image': self.corrected_image,
            'bbox_in_stitched': self.bbox_in_stitched
        }
