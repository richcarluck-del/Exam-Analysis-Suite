# 前端构建说明

## 📦 构建命令

```bash
cd preprocessor/preprocessor_test_ui/frontend
npm run build
```

## ✅ 最近一次构建

- **时间**: 2026-03-16
- **状态**: ✅ 成功
- **构建工具**: Vite v8.0.0
- **构建文件数**: 886 modules
- **构建时间**: 1.92s
- **输出文件**:
  - `dist/index.html` (0.45 kB)
  - `dist/assets/index-UBnxcqZ8.js`
  - `dist/assets/index-nqMpL4T3.css`

## 🔄 何时需要重新构建

当修改了以下文件后，需要重新构建前端：
- `frontend/src/App.jsx`
- `frontend/src/main.jsx`
- 任何其他 `frontend/src/` 下的文件

## 🚀 部署

构建完成后，后端会自动从 `frontend/dist/` 目录提供静态文件。

访问 `http://localhost:8001` 即可看到更新后的界面。

## 📝 本次更新内容

- ✅ 添加了 Tabs 组件显示三种类型的提示词
- ✅ 修改了下拉菜单选择逻辑（选择版本号而不是具体提示词 ID）
- ✅ 优化了提示词显示区域

## 🔍 验证

刷新浏览器后，应该能看到：
1. 提示词下拉框中有 v7, v6, v5 等版本选项
2. 选择版本后，下方显示三个 Tab：
   - 📄 试卷页面
   - 📝 答题纸页面
   - 🔀 混合页面
3. 每个 Tab 显示对应类型的实际提示词内容
