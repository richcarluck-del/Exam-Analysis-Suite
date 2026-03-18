# 提示词数据库统一管理方案（完整版）

## 📋 目标

将**整个 pipeline 中所有步骤**使用的提示词统一在数据库中进行管理，包括：
- **步骤 1**：透视矫正（识别四个角点）
- **步骤 2**：页面分类（判断试卷/答题纸）
- **步骤 3**：布局分析（A3 分割）
- **步骤 4**：内容提取（识别题目和答案）
- **步骤 6**：绘制输出（可选，如果有提示词指导）

实现：
1. **单一数据源**：所有提示词都从数据库读取
2. **多维度管理**：版本、场景、作用对象、步骤等
3. **分类清晰**：按步骤、类型、用途分类
4. **易于扩展**：支持新步骤、新场景

---

## 🎯 完整需求分析

### 一、Pipeline 中的所有提示词

#### 步骤 1：透视矫正 (Perspective Correction)
**用途**：识别试卷/答题纸的四个角点
**提示词示例**：
- `perspective_correction_v1` - 基础版本
- `perspective_correction_v2` - 优化版本（更精确的角点检测）

**属性**：
- **步骤**：1
- **作用对象**：exam_paper, answer_sheet
- **场景**：perspective_correction
- **输出**：四个角点坐标

#### 步骤 2：页面分类 (Page Classification)
**用途**：判断是试卷还是答题纸
**提示词示例**：
- `page_classification_v1` - 基础版本
- `page_classification_v2` - 优化版本（更准确的分类）

**属性**：
- **步骤**：2
- **作用对象**：full_page
- **场景**：classification
- **输出**：page_type (exam_paper / answer_sheet / mixed)

#### 步骤 3：布局分析 (Layout Analysis)
**用途**：识别 A3 页面是否需要分割
**提示词示例**：
- `layout_analysis_v1` - 基础版本
- `layout_analysis_v2` - 优化版本（更准确的分割线检测）

**属性**：
- **步骤**：3
- **作用对象**：exam_paper, answer_sheet
- **场景**：layout_analysis, a3_split
- **输出**：分割信息（left/right/full）

#### 步骤 4：内容提取 (Content Extraction)
**用途**：识别题目、答案区域
**提示词示例**：
- `content_extraction_v1` ~ `content_extraction_v7` - 7 个版本

**属性**：
- **步骤**：4
- **作用对象**：question_paper, answer_sheet, mixed
- **场景**：question_detection, answer_detection
- **输出**：题目/答案区域的边界框

#### 步骤 6：绘制输出 (Draw Output) - 可选
**用途**：指导如何绘制最终输出
**提示词示例**：
- `draw_output_v1` - 基础版本

**属性**：
- **步骤**：6
- **作用对象**：all_types
- **场景**：output_rendering
- **输出**：绘制指导信息

---

## 💡 全面的设计方案

### 一、数据库结构设计（多维度）

#### 1. 核心模型设计

```python
class Prompt(Base):
    """
    提示词主表 - 每个 Prompt 代表一个唯一的提示词
    """
    __tablename__ = 'prompts'
    
    id = Column(Integer, primary_key=True)
    
    # 基本信息
    name = Column(String(100), unique=True, nullable=False)  # 如 "perspective_correction_v1"
    display_name = Column(String(200))  # 显示名称，如 "透视矫正 V1"
    description = Column(Text)  # 详细描述
    
    # 多维度分类
    pipeline_step = Column(Integer)  # 所属步骤：1, 2, 3, 4, 6
    category = Column(String(50))  # 类别：'perspective_correction', 'classification', 'layout_analysis', 'content_extraction', 'draw_output'
    target_type = Column(String(50))  # 作用对象：'exam_paper', 'answer_sheet', 'mixed', 'full_page', 'all_types'
    scenario = Column(String(100))  # 场景：'corner_detection', 'page_type', 'a3_split', 'question_detection'
    
    # 版本管理
    version = Column(Integer, default=1)  # 版本号：1, 2, 3...
    is_latest = Column(Boolean, default=False)  # 是否最新版本
    is_active = Column(Boolean, default=True)  # 是否启用
    
    # 元数据
    created_by = Column(String(100))  # 创建者
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    # 关联
    versions = relationship("PromptVersion", back_populates="prompt", cascade="all, delete-orphan", lazy="selectin")

class PromptVersion(Base):
    """
    提示词版本表 - 存储实际的提示词文本内容
    支持一个 Prompt 有多个版本（草稿、审核中、已发布等）
    """
    __tablename__ = 'prompt_versions'
    
    id = Column(Integer, primary_key=True)
    
    # 关联
    prompt_id = Column(Integer, ForeignKey('prompts.id'), nullable=False)
    
    # 版本信息
    version = Column(Integer, nullable=False)  # 版本号
    prompt_text = Column(Text, nullable=False)  # 提示词完整内容
    
    # 状态
    status = Column(String(20), default='draft')  # 'draft', 'review', 'published', 'deprecated'
    
    # 元数据
    created_by = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)
    change_log = Column(Text)  # 变更说明
    
    # 关联
    prompt = relationship("Prompt", back_populates="versions")
```

#### 2. 枚举定义

```python
from enum import Enum

class PipelineStep(Enum):
    """Pipeline 步骤枚举"""
    PERSPECTIVE_CORRECTION = 1
    PAGE_CLASSIFICATION = 2
    LAYOUT_ANALYSIS = 3
    CONTENT_EXTRACTION = 4
    MERGE_RESULTS = 5  # 可能不需要提示词
    DRAW_OUTPUT = 6

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
```

---

### 二、命名规范

#### 1. 完整命名规则

格式：`{category}_{target_type}_v{version}`

示例：

**步骤 1、3、6（通用类型）**：
- `perspective_correction_all_types_v1` - 透视矫正 V1（通用）
- `layout_analysis_all_types_v1` - 布局分析 V1（通用）
- `draw_output_all_types_v1` - 绘制输出 V1（通用）

**步骤 2（整页分类）**：
- `page_classification_full_page_v2` - 页面分类 V2

**步骤 4（区分类型）**：
- `content_extraction_exam_paper_v7` - 试卷内容提取 V7
- `content_extraction_answer_sheet_v5` - 答题纸内容提取 V5
- `content_extraction_mixed_v3` - 混合类型内容提取 V3

#### 2. 简化命名（用于显示）

- `perspective_v1` - 透视矫正 V1
- `classification_v2` - 分类 V2
- `extraction_v7` - 提取 V7

---

### 三、查询和获取方法

#### 1. 根据步骤和类型获取

```python
def get_prompt_for_step(step: int, target_type: str = None, version: str = "latest") -> PromptVersion:
    """
    获取指定步骤的提示词
    
    Args:
        step: Pipeline 步骤 (1-6)
        target_type: 作用对象
            - 步骤 1、3、6: "all_types"（通用）
            - 步骤 2: "full_page"（整页分类）
            - 步骤 4: "exam_paper" | "answer_sheet" | "mixed"（根据分类结果）
        version: 版本号或 "latest"
    
    Returns:
        PromptVersion 对象
    """
    query = db.query(Prompt).filter(
        Prompt.pipeline_step == step,
        Prompt.is_active == True
    )
    
    # 步骤 1、2、3、6 使用固定的 target_type
    # 步骤 4 根据分类结果动态选择
    if target_type:
        query = query.filter(Prompt.target_type == target_type)
    
    if version == "latest":
        query = query.filter(Prompt.is_latest == True)
    else:
        query = query.filter(Prompt.version == version)
    
    prompt = query.first()
    if not prompt:
        raise ValueError(f"Prompt not found for step={step}, target_type={target_type}, version={version}")
    
    # 获取已发布的版本
    published_version = next((v for v in prompt.versions if v.status == 'published'), None)
    if not published_version:
        published_version = max(prompt.versions, key=lambda v: v.version)
    
    return published_version
```

#### 2. 根据场景获取

```python
def get_prompt_by_scenario(scenario: str, target_type: str = None) -> List[Prompt]:
    """
    根据场景获取提示词列表
    
    Args:
        scenario: 场景名称
        target_type: 可选的作用对象过滤
    
    Returns:
        Prompt 列表
    """
    query = db.query(Prompt).filter(
        Prompt.scenario == scenario,
        Prompt.is_active == True
    )
    
    if target_type:
        query = query.filter(Prompt.target_type == target_type)
    
    return query.order_by(Prompt.version.desc()).all()
```

#### 3. 获取所有可用的提示词（用于前端显示）

```python
def get_all_prompts(category: str = None, step: int = None) -> List[Dict]:
    """
    获取所有可用的提示词（用于前端下拉列表）
    
    Returns:
        字典列表，包含提示词的基本信息
    """
    query = db.query(Prompt).filter(Prompt.is_active == True)
    
    if category:
        query = query.filter(Prompt.category == category)
    if step:
        query = query.filter(Prompt.pipeline_step == step)
    
    prompts = query.order_by(Prompt.pipeline_step, Prompt.category, Prompt.version).all()
    
    result = []
    for p in prompts:
        latest_version = max(p.versions, key=lambda v: v.version)
        result.append({
            "id": p.id,
            "name": p.name,
            "display_name": p.display_name,
            "category": p.category,
            "pipeline_step": p.pipeline_step,
            "target_type": p.target_type,
            "scenario": p.scenario,
            "version": p.version,
            "is_latest": p.is_latest,
            "description": p.description,
            "prompt_text_preview": latest_version.prompt_text[:100] + "..."
        })
    
    return result
```

---

### 四、数据迁移方案

#### 1. 现有提示词整理

**步骤 1 - 透视矫正**：
- 当前：在 `task_perspective_correction.py` 中硬编码
- 迁移：创建 `perspective_correction_exam_paper_v1`, `perspective_correction_answer_sheet_v1`

**步骤 2 - 页面分类**：
- 当前：在 `task_classify_page.py` 或 classifier.py 中硬编码
- 迁移：创建 `page_classification_full_page_v1`, `page_classification_full_page_v2`

**步骤 3 - 布局分析**：
- 当前：在 `task_analyze_layout.py` 中硬编码
- 迁移：创建 `layout_analysis_exam_paper_v1`

**步骤 4 - 内容提取**：
- 当前：数据库中已有 `extract_content_v1` ~ `v7`
- 迁移：重命名为 `content_extraction_question_paper_v1` ~ `v7` 等

**步骤 6 - 绘制输出**：
- 当前：在 `task_draw_output.py` 中硬编码
- 迁移：创建 `draw_output_all_types_v1`

#### 2. 迁移脚本

```python
# migrate_all_prompts_to_db.py

def migrate_step1_prompts():
    """迁移步骤 1 的提示词"""
    from src.prompts import PERSPECTIVE_CORRECTION_PROMPT
    
    prompt = Prompt(
        name="perspective_correction_exam_paper_v1",
        display_name="透视矫正 V1（试卷）",
        description="识别试卷的四个角点",
        pipeline_step=1,
        category="perspective_correction",
        target_type="exam_paper",
        scenario="corner_detection",
        version=1,
        is_latest=True,
        is_active=True
    )
    
    version = PromptVersion(
        version=1,
        prompt_text=PERSPECTIVE_CORRECTION_PROMPT,
        status='published'
    )
    
    prompt.versions.append(version)
    db.add(prompt)

def migrate_step2_prompts():
    """迁移步骤 2 的提示词"""
    # 类似步骤 1...

def migrate_step4_prompts():
    """迁移步骤 4 的提示词（重命名现有的）"""
    existing = db.query(Prompt).filter(
        Prompt.name.like("extract_content_v%")
    ).all()
    
    for prompt in existing:
        # 重命名
        old_name = prompt.name  # extract_content_v7
        new_name = old_name.replace("extract_content_", "content_extraction_mixed_")
        prompt.name = new_name
        prompt.category = "content_extraction"
        prompt.target_type = "mixed"
        prompt.scenario = "question_detection"
    
    db.commit()

# 执行所有迁移
if __name__ == "__main__":
    migrate_step1_prompts()
    migrate_step2_prompts()
    migrate_step3_prompts()
    migrate_step4_prompts()
    migrate_step6_prompts()
```

---

### 五、代码修改方案

#### 1. 修改 main.py - 统一管理所有提示词

```python
class PromptManager:
    """提示词管理器 - 统一管理所有步骤的提示词"""
    
    def __init__(self, db_session):
        self.db = db_session
    
    def get_prompt(self, step: int, target_type: str, version: str = "latest") -> str:
        """
        获取指定步骤的提示词
        
        Args:
            step: Pipeline 步骤 (1-6)
            target_type: 作用对象
            version: 版本号或 "latest"
        
        Returns:
            提示词文本
        """
        prompt = self.db.query(Prompt).filter(
            Prompt.pipeline_step == step,
            Prompt.target_type == target_type,
            Prompt.is_active == True
        )
        
        if version == "latest":
            prompt = prompt.filter(Prompt.is_latest == True)
        else:
            prompt = prompt.filter(Prompt.version == int(version))
        
        prompt = prompt.first()
        if not prompt:
            raise ValueError(f"Prompt not found for step={step}, target_type={target_type}")
        
        # 获取已发布的版本
        published_version = next((v for v in prompt.versions if v.status == 'published'), None)
        if not published_version:
            published_version = max(prompt.versions, key=lambda v: v.version)
        
        print(f"Using prompt: {prompt.name} (step={step}, target={target_type})")
        return published_version.prompt_text


# 在 main.py 中使用
prompt_manager = PromptManager(db)

# 步骤 1：获取透视矫正提示词
perspective_prompt = prompt_manager.get_prompt(step=1, target_type="exam_paper")

# 步骤 2：获取页面分类提示词
classification_prompt = prompt_manager.get_prompt(step=2, target_type="full_page")

# 步骤 4：获取内容提取提示词（从用户选择）
extraction_prompt = prompt_manager.get_prompt(
    step=4, 
    target_type=page_type,  # 根据步骤 2 的结果
    version=args.prompt_version
)
```

#### 2. 修改各个任务文件

**task_perspective_correction.py**：
```python
def run_perspective_correction(
    image_paths: list[str], 
    output_path: str, 
    api_key: str, 
    model_name: str, 
    api_url: str,
    prompt_text: str = None,  # 从 main.py 传入
    image_path_manager=None
):
    # 使用传入的 prompt_text，不再硬编码
    if not prompt_text:
        raise ValueError("Prompt text is required")
    
    # 使用 prompt_text 调用 API
    corner_result = corrector.detect_corners(
        image_path, 
        api_key, 
        model_name, 
        api_url,
        prompt=prompt_text  # 使用传入的提示词
    )
```

**task_classify_page.py**：
```python
def run_classification(
    correction_map_path: str, 
    output_path: str, 
    api_key: str, 
    model_name: str, 
    api_url: str,
    prompt_text: str = None,  # 从 main.py 传入
    image_path_manager=None
):
    # 使用传入的 prompt_text
    if not prompt_text:
        raise ValueError("Prompt text is required")
    
    # 使用 prompt_text 调用 API
    page_result = classifier.classify(
        image_path, 
        api_key=api_key, 
        model_name=model_name, 
        api_url=api_url,
        prompt=prompt_text
    )
```

---

### 六、API 设计（完整版）

#### 1. 获取所有提示词（带过滤）

```
GET /api/prompts?category=content_extraction&step=4&target_type=question_paper
```

**返回**：
```json
[
  {
    "id": 7,
    "name": "content_extraction_question_paper_v7",
    "display_name": "内容提取 V7（试卷）",
    "category": "content_extraction",
    "pipeline_step": 4,
    "target_type": "question_paper",
    "scenario": "question_detection",
    "version": 7,
    "is_latest": true,
    "description": "一道题=一个框",
    "prompt_text_preview": "你是一个专业的试卷题目识别 AI..."
  },
  {
    "id": 6,
    "name": "content_extraction_question_paper_v6",
    "display_name": "内容提取 V6（试卷）",
    "category": "content_extraction",
    "pipeline_step": 4,
    "target_type": "question_paper",
    "scenario": "question_detection",
    "version": 6,
    "is_latest": false,
    "description": "宁可重叠，不可切割",
    "prompt_text_preview": "你是一个专业的试卷分析 AI..."
  }
]
```

#### 2. 获取特定提示词内容

```
GET /api/prompts/content_extraction_question_paper_v7/versions/latest
```

**返回**：
```json
{
  "id": 7,
  "name": "content_extraction_question_paper_v7",
  "version": 7,
  "prompt_text": "你是一个专业的试卷题目识别 AI...",
  "status": "published",
  "created_at": "2026-03-16T12:00:00"
}
```

#### 3. 获取 Pipeline 配置

```
GET /api/pipeline/config
```

**返回**：
```json
{
  "steps": [
    {
      "step_number": 1,
      "name": "perspective_correction",
      "available_prompts": [
        {
          "name": "perspective_correction_exam_paper_v1",
          "display_name": "透视矫正 V1（试卷）",
          "is_default": true
        }
      ]
    },
    {
      "step_number": 2,
      "name": "page_classification",
      "available_prompts": [
        {
          "name": "page_classification_full_page_v2",
          "display_name": "页面分类 V2",
          "is_default": true
        }
      ]
    },
    {
      "step_number": 4,
      "name": "content_extraction",
      "available_prompts": [
        {
          "name": "content_extraction_question_paper_v7",
          "display_name": "内容提取 V7（试卷）",
          "is_default": true
        },
        {
          "name": "content_extraction_answer_sheet_v5",
          "display_name": "内容提取 V5（答题纸）"
        }
      ]
    }
  ]
}
```

---

### 七、前端显示方案

#### 1. 按步骤分组显示

```
📌 步骤 1：透视矫正
  - 透视矫正 V1（试卷）✅ (默认)
  - 透视矫正 V1（答题纸）

📌 步骤 2：页面分类
  - 页面分类 V2 ✅ (默认)

📌 步骤 3：布局分析
  - 布局分析 V1（A3 分割）✅ (默认)

📌 步骤 4：内容提取
  按类型分组：
  
  📄 试卷类型:
    - 内容提取 V7（一道题=一个框）✅ (默认)
    - 内容提取 V6（宁可重叠）
    - 内容提取 V5（完整包含）
  
  📝 答题纸类型:
    - 内容提取 V5（答题纸）✅ (默认)
  
  🔀 混合类型:
    - 内容提取 V3（混合）

📌 步骤 6：绘制输出
  - 绘制指导 V1 ✅ (默认)
```

#### 2. 高级配置模式

提供"高级模式"，允许用户为每个步骤单独选择提示词版本：

```
[ ] 使用高级模式（为每个步骤单独配置提示词）

步骤 1：[透视矫正 V1（试卷）▼]
步骤 2：[页面分类 V2 ▼]
步骤 3：[布局分析 V1 ▼]
步骤 4：[内容提取 V7（试卷）▼]
步骤 6：[绘制指导 V1 ▼]
```

---

## 📅 实施步骤（完整版）

### 阶段一：数据库设计（2-3 小时）
1. ✅ 设计多维度数据模型
2. ⏳ 创建 SQLAlchemy 模型类
3. ⏳ 创建数据库迁移脚本
4. ⏳ 执行迁移

### 阶段二：数据迁移（2-3 小时）
1. ⏳ 整理所有步骤的提示词
2. ⏳ 创建迁移脚本 `migrate_all_prompts_to_db.py`
3. ⏳ 执行迁移，验证数据
4. ⏳ 重命名现有的 extract_content 系列

### 阶段三：核心管理器（2-3 小时）
1. ⏳ 创建 `PromptManager` 类
2. ⏳ 实现 `get_prompt()` 方法
3. ⏳ 实现多维度查询方法
4. ⏳ 单元测试

### 阶段四：修改 main.py（2-3 小时）
1. ⏳ 集成 `PromptManager`
2. ⏳ 为每个步骤获取对应的提示词
3. ⏳ 传递提示词到各个任务
4. ⏳ 删除旧的获取逻辑

### 阶段五：修改任务文件（3-4 小时）
1. ⏳ 修改 `task_perspective_correction.py`
2. ⏳ 修改 `task_classify_page.py`
3. ⏳ 修改 `task_analyze_layout.py`
4. ⏳ 修改 `task_extract_content.py`
5. ⏳ 修改 `task_draw_output.py`
6. ⏳ 删除对 `prompts.py` 的依赖

### 阶段六：API 开发（3-4 小时）
1. ⏳ 实现 `GET /api/prompts`（带过滤）
2. ⏳ 实现 `GET /api/prompts/{name}/versions/{version}`
3. ⏳ 实现 `GET /api/pipeline/config`
4. ⏳ 实现 `POST /api/prompts`（创建新提示词）
5. ⏳ API 测试

### 阶段七：管理工具（2-3 小时）
1. ⏳ 创建 `prompt_manager.py` CLI 工具
2. ⏳ 实现 list/show/add/deactivate/compare 命令
3. ⏳ 测试管理工具

### 阶段八：前端优化（2-3 小时）
1. ⏳ 修改前端 API 调用
2. ⏳ 按步骤分组显示
3. ⏳ 实现高级模式
4. ⏳ 显示版本信息

### 阶段九：测试验证（2-3 小时）
1. ⏳ 单元测试（所有 PromptManager 方法）
2. ⏳ 集成测试（完整 Pipeline）
3. ⏳ 端到端测试（前端 + 后端）
4. ⏳ 性能测试（大量提示词时的查询性能）

---

## ✅ 验收标准（完整版）

### 1. 数据库完整性
- [ ] 数据库包含所有 6 个步骤的提示词
- [ ] 每个提示词都有正确的 category、target_type、scenario
- [ ] 版本管理正常工作

### 2. 代码重构
- [ ] 所有任务文件都从 PromptManager 获取提示词
- [ ] 删除了所有对 prompts.py 的引用
- [ ] 没有硬编码的提示词文本

### 3. 查询功能
- [ ] 可以按步骤查询
- [ ] 可以按类别查询
- [ ] 可以按作用对象查询
- [ ] 可以按场景查询
- [ ] 可以获取最新版本

### 4. 前端显示
- [ ] 按步骤分组显示
- [ ] 显示类别、作用对象、场景信息
- [ ] 支持高级模式
- [ ] 显示版本历史

### 5. 管理工具
- [ ] 可以列出所有提示词
- [ ] 可以按条件过滤
- [ ] 可以添加新提示词
- [ ] 可以停用旧提示词
- [ ] 可以比较不同版本

---

## 🔮 未来扩展

### 1. 提示词测试框架
- A/B 测试不同版本
- 收集准确率指标
- 自动推荐最佳版本

### 2. 提示词模板系统
- 支持变量（如 `{side}`, `{question_type}`）
- 支持条件逻辑
- 支持多语言

### 3. 权限管理
- 角色：Admin, Editor, Viewer
- 审核流程
- 版本回滚

### 4. 性能优化
- Redis 缓存
- 预加载机制
- 批量查询优化

---

## 📝 关键设计决策

### 1. 为什么需要多维度？
- **步骤维度**：明确提示词属于哪个处理阶段
- **类别维度**：便于分类管理和查询
- **作用对象维度**：针对不同输入类型使用不同提示词
- **场景维度**：支持同一类别下的不同用途

### 2. 为什么分离 Prompt 和 PromptVersion？
- **支持多版本**：一个 Prompt 可以有多个版本（草稿、审核、发布）
- **版本控制**：可以回滚到历史版本
- **审计追踪**：记录谁在什么时候修改了什么

### 3. 为什么需要 is_latest 和 is_active？
- **is_latest**：快速找到最新版本，不需要每次计算 MAX(version)
- **is_active**：软删除，保留历史记录但不显示

---

## 🎯 总结

这个设计方案实现了：
1. ✅ **全步骤覆盖**：管理所有 6 个步骤的提示词
2. ✅ **多维度管理**：步骤、类别、作用对象、场景
3. ✅ **版本控制**：支持多版本、版本回滚
4. ✅ **统一管理**：单一数据源，删除本地文件依赖
5. ✅ **易于扩展**：支持新步骤、新场景、新类型

现在整个系统的提示词管理会非常清晰，不会再出现"不知道在改啥用啥"的问题！
