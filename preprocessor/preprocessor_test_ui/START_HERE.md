# 提示词管理工具 - 最简启动步骤

## ⚡ 快速启动（推荐）

### 第一步：安装前端依赖（仅首次需要）

打开 PowerShell，执行：
```powershell
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui\frontend
npm install
```

### 第二步：启动前端开发服务器（包含后端代理）

```powershell
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui\frontend
npm run dev
```

等待看到类似输出：
```
  VITE v8.0.0  ready in 500 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

### 第三步：打开浏览器

访问：**http://localhost:5173**

### 第四步：点击提示词管理按钮

在页面顶部工具栏，找到并点击 **✏️** 图标

---

## 🔧 如果遇到问题

### 错误 1：'npm' 不是内部或外部命令

**原因**：未安装 Node.js

**解决**：下载安装 https://nodejs.org/ （选择 LTS 版本）

### 错误 2：缺少模块

**原因**：依赖未安装

**解决**：
```powershell
cd D:\10739\Exam-Analysis-Suite\preprocessor\preprocessor_test_ui\frontend
npm install
```

### 错误 3：端口被占用

**原因**：5173 端口已被使用

**解决**：
1. 关闭其他前端服务
2. 或者编辑 `frontend/vite.config.js`，修改端口为其他值（如 5174）

---

## ✅ 验证功能正常

1. 打开浏览器后，应该看到测试页面
2. 页面顶部有 **✏️ 提示词管理** 按钮
3. 点击后显示提示词列表（应该有 16 个提示词）
4. 点击任意一行的"编辑"按钮
5. 弹出编辑对话框，显示提示词内容

---

## 📝 功能说明

- **查看**：浏览所有提示词
- **筛选**：按步骤、类型、类别筛选
- **搜索**：输入关键词搜索
- **编辑**：修改提示词内容
- **保存**：创建新版本（保留历史）
- **版本历史**：查看最近 5 个版本

---

## 🎯 使用示例

### 优化 v8 提示词

1. 点击 ✏️ 打开提示词管理
2. 筛选：步骤=4，类型=exam_paper
3. 找到 `content_extraction_exam_paper_v8`
4. 点击"编辑"
5. 修改提示词内容
6. 填写变更日志
7. 点击"保存为新版本"
8. 回到测试页面选择新版本

---

## 📞 需要更多帮助？

查看完整文档：
- `QUICK_START.md` - 快速启动指南
- `PROMPT_EDITOR_GUIDE.md` - 详细使用指南
- `IMPLEMENTATION_COMPLETE.md` - 功能总结
