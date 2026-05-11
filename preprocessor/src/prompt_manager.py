"""
提示词管理器 - 统一管理所有步骤的提示词

功能：
1. 根据步骤和类型获取对应的提示词
2. 支持多维度查询（步骤、类别、作用对象、场景）
3. 管理版本控制
4. 提供缓存机制
"""

from enum import Enum
from typing import Dict, List, Optional
from shared.database import SessionLocal
from shared.models import Prompt, PromptVersion


class PipelineStep(Enum):
    """Pipeline 步骤枚举"""
    PERSPECTIVE_CORRECTION = 1  # 透视矫正
    PAGE_CLASSIFICATION = 2     # 页面分类
    LAYOUT_ANALYSIS = 3         # 布局分析
    CONTENT_EXTRACTION = 4      # 内容提取
    MERGE_RESULTS = 5           # 合并结果
    DRAW_OUTPUT = 6             # 绘制输出


class PromptCategory(Enum):
    """提示词类别枚举"""
    PERSPECTIVE_CORRECTION = "perspective_correction"
    PAGE_CLASSIFICATION = "page_classification"
    LAYOUT_ANALYSIS = "layout_analysis"
    CONTENT_EXTRACTION = "content_extraction"
    DRAW_OUTPUT = "draw_output"


class TargetType(Enum):
    """作用对象枚举"""
    
    # 通用类型（用于步骤 1、3、6 - 不需要区分试卷/答题纸）
    ALL_TYPES = "all_types"      # 所有类型通用
    FULL_PAGE = "full_page"      # 整页（用于步骤 2 分类）
    
    # 特定类型（用于步骤 4 - 需要区分试卷/答题纸）
    EXAM_PAPER = "exam_paper"      # 试卷
    ANSWER_SHEET = "answer_sheet"  # 答题纸
    MIXED = "mixed"                # 混合


class Scenario(Enum):
    """场景枚举"""
    # 步骤 1
    CORNER_DETECTION = "corner_detection"
    
    # 步骤 2
    PAGE_TYPE = "page_type"
    
    # 步骤 3
    A3_SPLIT = "a3_split"
    
    # 步骤 4
    QUESTION_DETECTION = "question_detection"
    ANSWER_DETECTION = "answer_detection"
    
    # 步骤 6
    OUTPUT_RENDERING = "output_rendering"


class PromptManager:
    """提示词管理器"""
    
    def __init__(self):
        self._cache = {}  # 简单缓存
        self._db_session = None
    
    def get_db_session(self):
        """获取数据库会话"""
        if not self._db_session:
            self._db_session = SessionLocal()
        return self._db_session
    
    def close_db_session(self):
        """关闭数据库会话"""
        if self._db_session:
            self._db_session.close()
            self._db_session = None
    
    def get_prompt(
        self, 
        step: int, 
        target_type: str = None, 
        category: str = None,
        version: str = "latest"
    ) -> Optional[str]:
        """
        获取指定条件的提示词
        
        Args:
            step: Pipeline 步骤 (1-6)
            target_type: 作用对象
                - 步骤 1、3、6: "all_types"（通用）
                - 步骤 2: "full_page"（整页分类）
                - 步骤 4: "exam_paper" | "answer_sheet" | "mixed"（根据分类结果）
            category: 提示词类别（可选）
            version: 版本号或 "latest"
        
        Returns:
            提示词文本，如果未找到返回 None
        """
        cache_key = f"{step}_{target_type}_{category}_{version}"
        
        # 检查缓存
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        db = self.get_db_session()
        
        try:
            query = db.query(Prompt).filter(
                Prompt.pipeline_step == step,
                Prompt.is_active == True
            )
            
            # 根据步骤设置默认的 target_type
            if step in [1, 3, 6] and target_type is None:
                target_type = "all_types"
            elif step == 2 and target_type is None:
                target_type = "full_page"
            elif step == 4 and target_type is None:
                # 步骤 4 必须指定 target_type
                pass
            
            # 应用 target_type 过滤
            if target_type:
                query = query.filter(Prompt.target_type == target_type)
            
            # 应用 category 过滤
            if category:
                query = query.filter(Prompt.category == category)
            
            # 应用版本过滤
            if version == "latest":
                query = query.filter(Prompt.is_latest == True)
            
            # 获取所有匹配的提示词
            prompts = query.all()
            
            if not prompts:
                return None
            
            # 获取指定版本的提示词
            if version == "latest":
                # 使用第一个提示词（is_latest=True 应该只有一个）
                prompt = prompts[0]
                # 获取最新的已发布版本
                published_versions = [v for v in prompt.versions if v.status == 'published']
                if published_versions:
                    target_version = max(published_versions, key=lambda v: v.version)
                else:
                    # 如果没有已发布版本，使用版本号最高的
                    target_version = max(prompt.versions, key=lambda v: v.version)
            else:
                # 遍历所有匹配的提示词，查找指定版本
                target_version = None
                target_prompt = None
                
                for p in prompts:
                    for v in p.versions:
                        if v.version == int(version):
                            target_version = v
                            target_prompt = p
                            break
                    if target_version:
                        break
                
                if not target_version:
                    return None
                
                prompt = target_prompt
            
            # 缓存结果
            result = target_version.prompt_text
            self._cache[cache_key] = result
            
            return result
            
        except Exception as e:
            print(f"获取提示词失败: {e}")
            return None
    
    def get_prompts_by_category(self, category: str, step: int = None) -> List[Dict]:
        """
        根据类别获取提示词列表
        
        Args:
            category: 提示词类别
            step: 可选的步骤过滤
        
        Returns:
            提示词信息列表
        """
        db = self.get_db_session()
        
        try:
            query = db.query(Prompt).filter(
                Prompt.category == category,
                Prompt.is_active == True
            )
            
            if step:
                query = query.filter(Prompt.pipeline_step == step)
            
            prompts = query.order_by(Prompt.version.desc()).all()
            
            result = []
            for p in prompts:
                latest_version = max(p.versions, key=lambda v: v.version)
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "display_name": p.display_name,
                    "pipeline_step": p.pipeline_step,
                    "target_type": p.target_type,
                    "version": p.version,
                    "is_latest": p.is_latest,
                    "description": p.description,
                    "prompt_text_preview": latest_version.prompt_text[:100] + "..." if len(latest_version.prompt_text) > 100 else latest_version.prompt_text
                })
            
            return result
            
        except Exception as e:
            print(f"获取提示词列表失败: {e}")
            return []
    
    def get_available_prompts_for_step(self, step: int) -> List[Dict]:
        """
        获取指定步骤的所有可用提示词
        
        Args:
            step: Pipeline 步骤
        
        Returns:
            该步骤的提示词列表
        """
        db = self.get_db_session()
        
        try:
            prompts = db.query(Prompt).filter(
                Prompt.pipeline_step == step,
                Prompt.is_active == True
            ).order_by(Prompt.target_type, Prompt.version.desc()).all()
            
            result = []
            for p in prompts:
                latest_version = max(p.versions, key=lambda v: v.version)
                result.append({
                    "id": p.id,
                    "name": p.name,
                    "display_name": p.display_name,
                    "target_type": p.target_type,
                    "version": p.version,
                    "is_latest": p.is_latest,
                    "description": p.description,
                    "prompt_text_preview": latest_version.prompt_text[:100] + "..." if len(latest_version.prompt_text) > 100 else latest_version.prompt_text
                })
            
            return result
            
        except Exception as e:
            print(f"获取步骤 {step} 的提示词失败: {e}")
            return []
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()


# 全局实例
prompt_manager = PromptManager()


if __name__ == "__main__":
    # 测试
    print("提示词管理器测试:")
    
    # 测试获取内容提取提示词
    content_prompt = prompt_manager.get_prompt(step=4, target_type="exam_paper")
    if content_prompt:
        print(f"✓ 试卷内容提取提示词长度: {len(content_prompt)}")
    else:
        print("⚠ 未找到试卷内容提取提示词")
    
    # 测试获取透视矫正提示词
    perspective_prompt = prompt_manager.get_prompt(step=1, target_type="all_types")
    if perspective_prompt:
        print(f"✓ 透视矫正提示词长度: {len(perspective_prompt)}")
    else:
        print("⚠ 未找到透视矫正提示词")
    
    # 测试获取所有内容提取提示词
    content_prompts = prompt_manager.get_prompts_by_category("content_extraction")
    print(f"✓ 内容提取提示词数量: {len(content_prompts)}")
    
    print("✓ 提示词管理器测试完成")