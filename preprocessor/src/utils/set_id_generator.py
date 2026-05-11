import uuid
from datetime import datetime

def generate_set_id() -> str:
    """
    生成唯一的套编号
    
    格式：SET_YYYYMMDD_XXXX
    - SET: 固定前缀
    - YYYYMMDD: 日期
    - XXXX: UUID 的后 4 位
    
    示例：SET_20260320_A1B2
    """
    date_str = datetime.now().strftime("%Y%m%d")
    unique_suffix = uuid.uuid4().hex[:4].upper()
    return f"SET_{date_str}_{unique_suffix}"
