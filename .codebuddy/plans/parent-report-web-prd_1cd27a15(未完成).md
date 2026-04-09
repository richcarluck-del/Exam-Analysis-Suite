---
name: parent-report-web-prd
overview: 为“家长查看试卷整体分析结果”的网页整理一份产品设计文档，明确页面目标、信息架构、核心模块、数据映射、交互流程与视觉原则，并结合现有仓库的数据输出与前端基础给出落地方案。
design:
  architecture:
    framework: react
  styleKeywords:
    - 教育感高级报告
    - 阅读优先
    - 温和渐变
    - 卡片分层
    - 清晰锚点导航
  fontSystem:
    fontFamily: PingFang SC
    heading:
      size: 32px
      weight: 700
    subheading:
      size: 20px
      weight: 600
    body:
      size: 15px
      weight: 400
  colorSystem:
    primary:
      - "#5B6CFF"
      - "#7C87FF"
      - "#38BDF8"
    background:
      - "#F6F8FC"
      - "#FFFFFF"
      - "#EEF2FF"
    text:
      - "#0F172A"
      - "#475569"
      - "#94A3B8"
    functional:
      - "#10B981"
      - "#EF4444"
      - "#F59E0B"
      - "#2563EB"
todos:
  - id: confirm-scope
    content: 使用 [subagent:code-explorer] 复核报告入口、数据源与图片资产边界
    status: pending
  - id: draft-prd
    content: 编写 docs/parent-report-prd.md 的信息架构与阅读流程
    status: pending
    dependencies:
      - confirm-scope
  - id: map-data-ui
    content: 定义分析字段到页面区块的映射与异常展示规则
    status: pending
    dependencies:
      - confirm-scope
  - id: finalize-design
    content: 完善视觉规范、页面线框和后续前端落地建议
    status: pending
    dependencies:
      - draft-prd
      - map-data-ui
---

## User Requirements

- 为家长提供一个网页，集中查看一次试卷的整体分析结果，现有分析产物都能在页面中完整呈现。
- 页面阅读顺序要符合自然理解方式：先看整卷结论，再看重点风险与待复核题，再逐题查看原因、讲解和学习建议。
- 页面需要美观、清晰、易读，避免内部工具或后台风格；图片证据、错因说明、知识点和后续建议都要容易理解。

## Product Overview

该网页适合做成单页式分析报告。页面首屏先用摘要卡片快速说明本次试卷表现，再通过整卷预览和风险分组帮助家长快速定位重点，随后进入逐题分析区查看题目截图、学生作答、对错判断、讲解说明、错因和建议。整体视觉应温和、有层次、留白充足，兼顾数据感与阅读舒适度。

## Core Features

- 整卷概览：展示题量、完成率、正确情况、待复核题和总体结论。
- 整卷预览与定位：展示整页标注图和题目切图，支持快速定位到重点题目。
- 逐题分析：按题号输出作答情况、掌握度、讲解、错因、知识点、学习建议和证据图片。
- 重点筛选：支持查看错题、待人工复核题、高风险题，减少家长查找成本。
- 后续行动建议：把分散的题目建议整理成可执行的复盘清单，便于家长陪学。

## Tech Stack Selection

- 已确认现有可复用前端基座位于 `d:/10739/Exam-Analysis-Suite/analyzer/client-app`，技术栈为 React 18、Vite、react-router-dom、Tailwind CSS 4。
- 已确认另一个前端 `d:/10739/Exam-Analysis-Suite/preprocessor/preprocessor_test_ui/frontend` 使用 React 19 与 MUI 7，但当前定位是内部测试工具，视觉与交互不适合家长端报告页。
- 已确认报告核心数据源来自现有结构化输出：
- `preprocessor/temp/run_20260325_133128/analyzer_output_graphrag_real/analysis_report.json`
- `preprocessor/temp/run_20260325_133128/analyzer_output_graphrag_real/question_analyses.json`
- `preprocessor/temp/run_20260325_133128/manifest.json`
- `preprocessor/temp/run_20260325_133128/questions.json`

## Implementation Approach

先产出面向实现的产品设计文档，再按文档把家长端报告页落在现有 `analyzer/client-app` 中，避免新建第三套前端。页面以单页只读报告为主，通过一个数据适配层把总览数据、逐题分析和图片资产归一化，再按“总览、定位、逐题、行动建议”的阅读顺序渲染。

关键技术决策：

- 复用 `analyzer/client-app/src/App.jsx` 的现有路由体系，后续新增独立报告路由，保持 `/`、`/admin`、`/chat` 兼容，降低改动面。
- 用 `analysis_report.json` 提供整卷摘要，用 `question_analyses.json` 提供逐题结论，用 `manifest.json` 和 `questions.json` 补充图片目录、题号顺序和原始题面信息。
- 在前端增加轻量 `adapter` 层，隔离原始 JSON 与 UI。这样当分析字段演进时，只需调整映射逻辑，不必重写页面结构。
- 数据整理复杂度为 O(Q)，Q 为题目数量；图片是主要性能瓶颈，应优先采用缩略预览、按需展开与延迟加载，避免首屏一次性加载所有题图。

## Implementation Notes

- 已确认当前 `analyzer/client-app/src/App.jsx` 只有 `/`、`/admin`、`/chat`，尚无家长报告页，后续应以新增路由方式落地，不改动现有登录和管理流程。
- 已确认样例中存在 `needs_manual_review`、`uncertain`、空的学科年级字段，以及相对图片路径；文档中需明确这些异常与缺省状态的展示文案。
- 样例里整卷统计与逐题字段可能存在后续演进空间，建议在文档中约定“摘要计数优先级”和“字段缺失回退策略”，避免页面与分析结果口径不一致。
- 页面先做本地只读报告，不引入写操作、编辑操作和复杂权限，控制首轮范围与风险。
- 不直接沿用内部测试 UI 的深色控制台风格，家长端应使用阅读优先的浅色报告布局。

## Architecture Design

- 数据输入层：读取 `analysis_report.json`、`question_analyses.json`、`manifest.json`、`questions.json`。
- 适配层：生成统一视图模型，包括整卷摘要、风险分组、整页预览、逐题卡片、学习行动清单。
- 页面层：按阅读顺序组织为首屏摘要、整卷定位、重点筛选、逐题分析、复盘建议。
- 资源层：消费 `07_complete_units`、`08_annotated_images`、`question_slices` 等相对路径图片资源。

## Directory Structure

本轮交付以设计文档为主；若进入页面实现，建议沿用现有 `analyzer/client-app/src` 的平铺式结构，最小化新增文件。

- `d:/10739/Exam-Analysis-Suite/docs/parent-report-prd.md`  [NEW] 家长端试卷分析网页产品设计文档。沉淀用户视角、信息架构、区块说明、字段映射、状态文案与视觉规范，是本轮核心交付物。
- `d:/10739/Exam-Analysis-Suite/analyzer/client-app/src/App.jsx`  [MODIFY] 后续实现阶段新增家长报告路由入口，并保持现有登录、管理、聊天路由不受影响。
- `d:/10739/Exam-Analysis-Suite/analyzer/client-app/src/ParentReportPage.jsx`  [NEW] 后续实现阶段的报告页主容器，按“总览、整卷、逐题、建议”编排页面。
- `d:/10739/Exam-Analysis-Suite/analyzer/client-app/src/reportAdapter.js`  [NEW] 后续实现阶段的数据适配层，统一处理统计字段、题目列表、风险标记、图片路径和缺省值。
- `d:/10739/Exam-Analysis-Suite/analyzer/client-app/src/index.css`  [MODIFY] 后续实现阶段补充阅读型报告所需的全局排版、卡片层级、图片浏览和打印样式。

## Design Style

采用“教育感高级报告”风格，桌面端优先，整体以浅色背景、柔和渐变、分层卡片和稳定网格组织内容。页面强调先总览后下钻，避免信息一股脑堆叠；数据卡、图像证据和文字解释分区清晰，让家长在几分钟内看懂重点。

## Page Planning

### 页面1：家长端试卷分析报告页

- 顶部导航：左侧品牌与报告标题，中间锚点导航，右侧学生信息、报告时间、打印入口。
- 首屏总览：大号结论卡配关键指标，突出正确情况、完成率、待复核数和一句话总结。
- 整卷预览：显示标注整页缩略图与题号索引，点击可跳转对应题目分析。
- 风险摘要：用分组卡展示错题、待复核题、薄弱知识点和高风险提醒。
- 逐题分析：按题号纵向排列卡片，内含题图、作答、结论、讲解、错因、建议和证据。
- 底部导航：固定复盘操作栏，汇总今日重点、打印清单和返回顶部入口。

## Layout and Interaction

- 桌面端采用 12 栏布局，首屏双列，逐题区单列长文阅读，右侧保留吸附式快捷目录。
- 卡片支持悬停轻抬升，题图支持点击放大，筛选项使用胶囊标签切换错题、复核题和全部题目。
- 动效保持克制，重点用于区块切换、锚点跳转和图片放大，避免影响阅读。
- 1024px 以下自动纵向堆叠，但仍以桌面阅读体验为主。

## Agent Extensions

### SubAgent

- **code-explorer**
- Purpose: 复核现有前端入口、路由结构、样例 JSON 字段与图片资产位置，确保设计文档与仓库现状一致。
- Expected outcome: 产出准确的页面落点、数据映射清单、受影响文件范围和实现边界。