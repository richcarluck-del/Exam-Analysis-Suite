# 提示词手工编辑工具实施计划

## 📋 需求概述

在 8001 端口的测试页面中添加提示词编辑功能：
- 点击按钮弹出新页面
- 显示数据库中所有提示词列表
- 选择提示词后展示内容并可编辑
- 保存后更新到数据库
- 使用场景：人工调整和优化提示词

## 🎯 功能需求

### 1. 入口入口
- 在现有测试页面（8001 端口）添加"提示词管理"按钮
- 点击后打开提示词编辑页面

### 2. 提示词列表页面
- 显示所有提示词的表格/列表
- 列信息：名称、版本、类型、步骤、状态、操作
- 支持筛选：按步骤、按类型、按版本
- 支持搜索：按名称搜索
- 支持排序

### 3. 提示词编辑功能
- 选择提示词后显示完整内容
- 可编辑提示词文本
- 可修改元数据（版本、状态等）
- 实时显示字符数
- 支持预览格式（Markdown 渲染）

### 4. 保存功能
- 保存时创建新版本记录
- 保留历史版本
- 记录变更日志
- 支持标记为"最新"版本

## 🏗️ 技术架构

### 后端（FastAPI）

#### 新增 API 端点

1. **GET /api/prompts/all**
   - 获取所有提示词列表
   - 支持筛选参数：step, category, target_type, version
   - 返回：提示词列表（含版本信息）

2. **GET /api/prompts/{prompt_id}**
   - 获取单个提示词详情
   - 返回：提示词信息 + 所有版本历史

3. **PUT /api/prompts/{prompt_id}**
   - 更新提示词
   - 入参：prompt_text, version, status, change_log, is_latest
   - 创建新的 PromptVersion 记录

4. **POST /api/prompts**
   - 创建新提示词
   - 入参：name, display_name, pipeline_step, category, target_type, prompt_text

5. **DELETE /api/prompts/{prompt_id}**
   - 软删除提示词（设置 is_active=False）

#### 后端文件

**新增文件**：`preprocessor/preprocessor_test_ui/prompt_editor_api.py`
- 实现上述 API 端点
- 数据库操作
- 数据验证

**修改文件**：`preprocessor/preprocessor_test_ui/main.py`
- 导入并注册新的 API 路由
- 挂载静态文件（前端页面）

### 前端（React）

#### 新增页面组件

**新增文件**：`preprocessor/preprocessor_test_ui/frontend/src/PromptEditor.jsx`
- 提示词列表页面
- 编辑对话框/页面
- API 调用逻辑

**修改文件**：`preprocessor/preprocessor_test_ui/frontend/src/App.jsx`
- 添加路由：`/prompt-editor`
- 添加入口按钮

#### 页面布局

```
┌─────────────────────────────────────────────┐
│  提示词管理                      [关闭]      │
├─────────────────────────────────────────────┤
│  筛选：[步骤▼] [类型▼] [版本▼]  🔍 [搜索]   │
├─────────────────────────────────────────────┤
│  名称          │版本│步骤│类型    │状态│操作  │
│  ─────────────────────────────────────────  │
│  content_...v8 │ 8  │ 4  │exam_...│✓  │编辑  │
│  content_...v7 │ 7  │ 4  │exam_...│   │编辑  │
│  ...                                        │
└─────────────────────────────────────────────┘

编辑对话框：
┌─────────────────────────────────────────────┐
│  编辑：content_extraction_exam_paper_v8     │
├─────────────────────────────────────────────┤
│  名称：[content_extraction_exam_paper_v8]   │
│  版本：[8]  状态：[Published▼]              │
│  步骤：[4 - 内容提取]                        │
│  类型：[exam_paper]                          │
│                                             │
│  提示词内容：                                │
│  ┌─────────────────────────────────────┐   │
│  │ 你是一个试卷题目识别助手...          │   │
│  │                                     │   │
│  │ [可编辑的文本区域]                  │   │
│  │                                     │   │
│  └─────────────────────────────────────┘   │
│  字符数：2220                               │
│                                             │
│  变更日志：[本次修改说明]_________________  │
│                                             │
│  [取消]  [保存为新版本]                      │
└─────────────────────────────────────────────┘
```

## 📝 实施步骤

### 阶段 1：后端 API 开发
1. 创建 `prompt_editor_api.py` 文件
2. 实现获取提示词列表 API
3. 实现获取单个提示词 API
4. 实现更新提示词 API
5. 实现创建提示词 API
6. 在 `main.py` 中注册路由

### 阶段 2：前端基础框架
1. 创建 `PromptEditor.jsx` 组件
2. 实现提示词列表展示
3. 实现筛选和搜索功能
4. 在 `App.jsx` 中添加路由

### 阶段 3：编辑功能
1. 实现编辑对话框组件
2. 实现文本编辑区域
3. 实现字符数统计
4. 实现表单验证

### 阶段 4：保存功能
1. 实现保存 API 调用
2. 实现版本管理逻辑
3. 实现变更日志记录
4. 实现成功/错误提示

### 阶段 5：测试和优化
1. 测试完整流程
2. 优化用户体验
3. 添加加载状态
4. 处理边界情况

## 🔧 数据库操作要点

### 更新提示词时的逻辑

```python
# 1. 更新 Prompt 表
prompt.prompt_text = new_text
prompt.version = new_version
prompt.is_latest = is_latest
prompt.updated_at = datetime.now()

# 2. 创建新的 PromptVersion 记录
version_record = PromptVersion(
    prompt_id=prompt.id,
    version=new_version,
    prompt_text=new_text,
    status=status,
    change_log=change_log,
    created_at=datetime.now()
)

# 3. 如果标记为最新，更新其他版本为 False
if is_latest:
    other_prompts = db.query(Prompt).filter(
        Prompt.pipeline_step == prompt.pipeline_step,
        Prompt.category == prompt.category,
        Prompt.target_type == prompt.target_type,
        Prompt.id != prompt.id
    ).all()
    for p in other_prompts:
        p.is_latest = False

# 4. 提交事务
db.commit()
```

## 🎨 UI/UX 要求

1. **响应式设计**：适配不同屏幕尺寸
2. **加载状态**：API 调用时显示加载动画
3. **错误处理**：网络错误、验证错误友好提示
4. **确认对话框**：保存前确认修改
5. **自动保存草稿**：可选功能
6. **快捷键支持**：Ctrl+S 保存

## 🔒 安全考虑

1. **权限控制**：仅允许管理员编辑
2. **输入验证**：防止 SQL 注入、XSS 攻击
3. **操作日志**：记录谁在什么时候修改了什么
4. **版本回滚**：支持恢复到历史版本

## 📊 数据验证规则

1. **名称**：必填，唯一，符合命名规范
2. **版本**：必填，正整数
3. **提示词文本**：必填，最小长度 10 字符
4. **状态**：draft | review | published | deprecated
5. **变更日志**：建议填写，最大长度 500 字符

## 🚀 后续扩展功能（可选）

1. **版本对比**：Diff 查看两个版本的差异
2. **版本回滚**：一键恢复到历史版本
3. **批量操作**：批量更新、删除
4. **导入导出**：JSON 格式导入导出提示词
5. **使用统计**：显示每个提示词的使用次数
6. **测试功能**：直接在编辑页面测试提示词效果

## 📅 开发时间估算

- 后端 API：2-3 小时
- 前端列表：2 小时
- 前端编辑：3-4 小时
- 测试优化：2 小时
- **总计**：9-11 小时

## ✅ 验收标准

1. ✅ 能在测试页面打开提示词管理入口
2. ✅ 能正确显示所有提示词
3. ✅ 能筛选和搜索提示词
4. ✅ 能编辑并保存提示词
5. ✅ 保存后创建新版本记录
6. ✅ 能在前端看到更新后的内容
7. ✅ 实际操作中能影响大模型输出
