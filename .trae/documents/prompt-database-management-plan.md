# 提示词数据库统一管理方案

## 📋 目标

将所有提示词（包括试卷、答题纸、混合类型）统一在数据库中进行管理，废弃从本地 `prompts.py` 文件获取的方式，实现：
1. **单一数据源**：所有提示词都从数据库读取
2. **版本管理**：支持提示词的多版本管理
3. **分类清晰**：明确区分试卷、答题纸、混合类型的提示词
4. **易于维护**：提供清晰的管理工具和 API

---

## 🎯 当前问题分析

### 1. 数据源混乱
- **数据库**：存储了 `extract_content_v1` 到 `extract_content_v7`
- **本地文件**：`prompts.py` 中也有对应的提示词定义
- **测试页面**：从数据库读取，但实际运行时可能混用

### 2. 提示词类型不明确
- 当前数据库中的提示词只有 `answer_sheet` 类型
- `question_paper` 类型的提示词仍在 `prompts.py` 中定义
- 没有统一的分类和管理

### 3. 获取逻辑复杂
- `main.py` 中的获取逻辑需要兼容数据库和本地文件
- 需要处理 fallback 逻辑
- 难以调试和维护

---

## 💡 设计方案

### 一、数据库结构设计

#### 1. 扩展现有的 Prompt 模型

**当前结构**：
```python
class Prompt(Base):
    __tablename__ = 'prompts'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)  # 如 "extract_content_v1"
    description = Column(Text)
    versions = relationship("PromptVersion", back_populates="prompt")

class PromptVersion(Base):
    __tablename__ = 'prompt_versions'
    
    id = Column(Integer, primary_key=True)
    version = Column(Integer)
    prompt_text = Column(Text)
    prompt_id = Column(Integer, ForeignKey('prompts.id'))
```

**问题**：
- 没有区分提示词类型（试卷/答题纸/混合）
- 没有标记哪个版本是最新的
- 没有记录创建时间和作者

**新的结构**：
```python
class Prompt(Base):
    __tablename__ = 'prompts'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)  # 如 "exam_paper_v1", "answer_sheet_v7"
    category = Column(String(50))  # 枚举：'exam_paper', 'answer_sheet', 'mixed'
    description = Column(Text)
    is_active = Column(Boolean, default=True)  # 标记是否启用
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)
    
    versions = relationship("PromptVersion", back_populates="prompt", cascade="all, delete-orphan")

class PromptVersion(Base):
    __tablename__ = 'prompt_versions'
    
    id = Column(Integer, primary_key=True)
    version = Column(Integer)  # 版本号：1, 2, 3...
    prompt_text = Column(Text)
    prompt_id = Column(Integer, ForeignKey('prompts.id'))
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(100))  # 创建者
    
    prompt = relationship("Prompt", back_populates="versions")
```

#### 2. 新增 PromptCategory 枚举

```python
from enum import Enum

class PromptCategory(Enum):
    EXAM_PAPER = "exam_paper"      # 试卷
    ANSWER_SHEET = "answer_sheet"  # 答题纸
    MIXED = "mixed"                # 混合
```

---

### 二、命名规范

#### 1. 提示词命名规则

格式：`{category}_v{version}`

示例：
- `exam_paper_v1` - 试卷提示词 V1
- `answer_sheet_v7` - 答题纸提示词 V7
- `mixed_v3` - 混合提示词 V3

#### 2. 版本管理规则

- 每个 Prompt 可以有多个版本
- 版本号从 1 开始递增
- 默认使用最新版本（version 最大）
- 可以指定使用特定版本

---

### 三、数据迁移方案

#### 1. 从 prompts.py 导入所有提示词到数据库

创建迁移脚本 `migrate_prompts_to_db.py`：

```python
# 迁移步骤
1. 读取 prompts.py 中的 PROMPTS 字典
2. 遍历所有版本（v1-v7）
3. 为每个 category 创建 Prompt 记录
4. 为每个 Prompt 添加 PromptVersion 记录
5. 标记最新版本为 active
```

#### 2. 清理重复数据

- 删除数据库中旧的 `extract_content_v*` 格式
- 统一改为新的命名规范

---

### 四、API 设计

#### 1. 获取提示词 API

**端点**：`GET /api/prompts`

**查询参数**：
- `category` (可选): 过滤类别 (`exam_paper`, `answer_sheet`, `mixed`)
- `include_inactive` (可选): 是否包含未启用的提示词

**返回格式**：
```json
[
  {
    "id": 1,
    "name": "exam_paper_v1",
    "category": "exam_paper",
    "description": "试卷提示词 V1",
    "is_active": true,
    "latest_version": 1,
    "created_at": "2026-03-16T10:00:00"
  },
  {
    "id": 7,
    "name": "answer_sheet_v7",
    "category": "answer_sheet",
    "description": "V7 prompt: 一道题=一个框",
    "is_active": true,
    "latest_version": 1,
    "created_at": "2026-03-16T12:00:00"
  }
]
```

#### 2. 获取特定提示词内容 API

**端点**：`GET /api/prompts/{prompt_id}/versions/{version}`

**返回格式**：
```json
{
  "id": 7,
  "name": "answer_sheet_v7",
  "category": "answer_sheet",
  "version": 1,
  "prompt_text": "你是一个专业的试卷题目识别 AI..."
}
```

#### 3. 创建/更新提示词 API（未来扩展）

**端点**：`POST /api/prompts`

**请求体**：
```json
{
  "name": "answer_sheet_v8",
  "category": "answer_sheet",
  "description": "V8 优化版本",
  "prompt_text": "..."
}
```

---

### 五、代码修改方案

#### 1. 修改 main.py 的提示词获取逻辑

**当前逻辑**：
```python
# 从数据库获取，fallback 到本地文件
selected_prompt = db.query(Prompt).filter(Prompt.name == args.prompt_version).first()
if not selected_prompt:
    # Fallback to prompts.py
```

**新逻辑**：
```python
# 只从数据库获取，没有 fallback
selected_prompt = db.query(Prompt).filter(
    Prompt.name == args.prompt_version,
    Prompt.is_active == True
).first()

if not selected_prompt:
    raise ValueError(f"Prompt '{args.prompt_version}' not found in database")

# 获取最新版本
latest_version = max(selected_prompt.versions, key=lambda v: v.version)
content_extraction_prompt = latest_version.prompt_text
```

#### 2. 修改 task_extract_content.py

**当前逻辑**：
```python
if '{' in prompt_or_version and '}' in prompt_or_version:
    # 使用完整文本
    base_prompt_text = prompt_or_version
else:
    # 从 prompts.py 加载
    prompt_set = PROMPTS[prompt_or_version]
```

**新逻辑**：
```python
# 始终使用完整文本（从 main.py 传入）
base_prompt_text = prompt_or_version

# 不再支持从 prompts.py 加载
```

#### 3. 删除 prompts.py 的依赖

- 从 `task_extract_content.py` 中删除 `from src.prompts import PROMPTS`
- 从其他任务文件中删除对 `prompts.py` 的引用
- 最终可以考虑删除或归档 `prompts.py`

---

### 六、管理工具

#### 1. 创建提示词管理脚本

**文件**：`prompt_manager.py`

**功能**：
- `list` - 列出所有提示词
- `show <name>` - 显示特定提示词内容
- `add <name> <category> <file>` - 从文件添加新提示词
- `deactivate <name>` - 停用提示词
- `compare <name1> <name2>` - 比较两个提示词

**使用示例**：
```bash
# 列出所有启用的提示词
python prompt_manager.py list

# 显示 answer_sheet_v7 的内容
python prompt_manager.py show answer_sheet_v7

# 从文件添加新的试卷提示词
python prompt_manager.py add exam_paper_v2 exam_paper exam_paper_v2.txt

# 停用旧的提示词
python prompt_manager.py deactivate exam_paper_v1

# 比较两个版本
python prompt_manager.py compare answer_sheet_v6 answer_sheet_v7
```

#### 2. 创建数据库初始化脚本

**文件**：`init_prompts_db.py`

**功能**：
- 从 prompts.py 导入所有提示词
- 设置正确的 category
- 标记最新版本为 active

---

### 七、测试页面集成

#### 1. 修改前端显示

**当前**：
- 只显示提示词名称
- 不区分类型

**新的**：
- 按类别分组显示
- 显示版本号
- 显示描述信息
- 标记是否为最新版本

**示例**：
```
📄 试卷提示词
  - V1: 基础版本
  - V2: 优化版本 (最新)

📝 答题纸提示词
  - V5: 完整包含
  - V6: 宁可重叠
  - V7: 一道题=一个框 (最新)

🔀 混合提示词
  - V3: 混合版本
```

---

## 📅 实施步骤

### 阶段一：数据库结构升级（1-2 小时）
1. ✅ 设计新的数据库模型
2. ⏳ 创建 SQLAlchemy migration 脚本
3. ⏳ 执行迁移

### 阶段二：数据迁移（1 小时）
1. ⏳ 创建 `migrate_prompts_to_db.py` 脚本
2. ⏳ 从 prompts.py 导入所有提示词
3. ⏳ 验证迁移结果

### 阶段三：API 开发（2-3 小时）
1. ⏳ 实现 `GET /api/prompts`
2. ⏳ 实现 `GET /api/prompts/{id}/versions/{version}`
3. ⏳ 测试 API

### 阶段四：代码重构（2-3 小时）
1. ⏳ 修改 `main.py` 的提示词获取逻辑
2. ⏳ 修改 `task_extract_content.py`
3. ⏳ 删除对 `prompts.py` 的依赖
4. ⏳ 更新所有相关文件

### 阶段五：管理工具（1-2 小时）
1. ⏳ 创建 `prompt_manager.py`
2. ⏳ 创建 `init_prompts_db.py`
3. ⏳ 测试管理工具

### 阶段六：前端优化（1-2 小时）
1. ⏳ 修改前端 API 调用
2. ⏳ 按类别分组显示
3. ⏳ 显示版本信息

### 阶段七：测试验证（1-2 小时）
1. ⏳ 单元测试
2. ⏳ 集成测试
3. ⏳ 端到端测试

---

## ✅ 验收标准

1. **所有提示词都在数据库中**
   - [ ] 数据库中有 `exam_paper_v*` 系列
   - [ ] 数据库中有 `answer_sheet_v*` 系列
   - [ ] 数据库中有 `mixed_v*` 系列

2. **不再依赖 prompts.py**
   - [ ] 代码中没有 `from src.prompts import PROMPTS`
   - [ ] 所有提示词都从数据库读取
   - [ ] 删除 fallback 逻辑

3. **版本管理正常**
   - [ ] 可以获取最新版本
   - [ ] 可以指定特定版本
   - [ ] 版本号递增正确

4. **分类清晰**
   - [ ] 按 category 过滤
   - [ ] 前端按类别分组显示
   - [ ] 命名规范统一

5. **管理工具有效**
   - [ ] 可以列出所有提示词
   - [ ] 可以添加新提示词
   - [ ] 可以停用旧提示词

---

## 🔮 未来扩展

1. **提示词模板系统**
   - 支持变量替换
   - 支持条件逻辑
   - 支持多语言

2. **提示词测试框架**
   - A/B 测试不同版本
   - 收集效果指标
   - 自动推荐最佳版本

3. **权限管理**
   - 谁可以创建/修改提示词
   - 审核流程
   - 版本回滚

4. **性能优化**
   - 提示词缓存
   - 预加载机制

---

## 📝 注意事项

1. **向后兼容**
   - 保留旧的 API 接口一段时间
   - 提供迁移指南

2. **数据备份**
   - 迁移前备份数据库
   - 保留 prompts.py 作为归档

3. **文档更新**
   - 更新 README
   - 编写使用指南
   - 提供示例代码

4. **团队协作**
   - 通知所有开发者
   - 培训使用方法
   - 收集反馈
