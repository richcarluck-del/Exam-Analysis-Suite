def generate_sheet_id(set_id: str, sheet_number: int) -> str:
    """
    生成张编号
    
    Args:
        set_id: 套编号
        sheet_number: 张序号（从 1 开始）
        
    Returns:
        张编号，格式：{set_id}_SHEET_XXX
        
    示例：
        generate_sheet_id("SET_20260320_A1B2", 1) 
        -> "SET_20260320_A1B2_SHEET_001"
    """
    return f"{set_id}_SHEET_{sheet_number:03d}"
