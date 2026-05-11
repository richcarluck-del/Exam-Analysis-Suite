# 提示词管理工具 - 快速启动指南

## 🚀 最简单的启动方式

### 步骤 1：打开两个终端窗口

**终端 1** - 启动后端服务
```bash
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui
python main.py
```

**终端 2** - 启动前端服务
```bash
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui\frontend
npm run dev
```

### 步骤 2：打开浏览器

访问前端终端显示的地址（通常是 `http://localhost:5173`）

### 步骤 3：打开提示词管理

在测试页面顶部工具栏，点击 **✏️ 提示词管理** 按钮

---

## 📝 详细说明

### 首次使用需要安装依赖

如果前端终端提示缺少模块，执行：
```bash
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui\frontend
npm install
```

### 查看服务状态

**后端服务**：
- 应该显示：`Uvicorn running on http://localhost:8000`
- 按 Ctrl+C 停止

**前端服务**：
- 应该显示：`Local: http://localhost:5173/`
- 按 Ctrl+C 停止

---

## 🔧 常见问题

### 问题 1：npm 未安装

**症状**：提示 'npm' 不是内部或外部命令

**解决**：安装 Node.js（https://nodejs.org/）

### 问题 2：端口被占用

**症状**：启动失败，提示端口已占用

**解决**：
- 后端：编辑 `main.py`，修改 `port=8000` 为其他端口
- 前端：编辑 `frontend/vite.config.js`，修改 `server.port`

### 问题 3：缺少 Python 依赖

**症状**：导入错误

**解决**：
```bash
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui
pip install -r requirements.txt
```

---

## ✅ 验证功能

1. 打开浏览器后，应该看到测试页面
2. 点击顶部的 ✏️ 图标
3. 应该显示提示词列表（16 个提示词）
4. 点击任意一行的"编辑"按钮
5. 应该弹出编辑对话框

---

## 📞 需要帮助？

查看完整文档：`PROMPT_EDITOR_GUIDE.md`
