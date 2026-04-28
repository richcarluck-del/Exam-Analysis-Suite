from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session, joinedload

from shared import models


PROMPT_DEFINITIONS = [
    {
        "prompt_key": "preprocessor.perspective_correction.default",
        "display_name": "透视矫正",
        "module_name": "preprocessor",
        "description": "识别试卷/答题卡四角并输出归一化坐标。",
        "category": "perspective_correction",
        "target_type": "all_types",
        "pipeline_step": 1,
        "seed_versions": {
            1: """你是一个专业的文档图像矫正助手。请精确识别这张图片中【试卷】或【答题卡】的四个顶点。\n\n### 核心任务\n找到试卷/答题卡最外围可见边缘的四个角点，并输出归一化坐标（0-1000 范围）。\n\n### 角点定位标准\n1. 左上角：试卷左边缘和上边缘的交点\n2. 右上角：试卷右边缘和上边缘的交点\n3. 右下角：试卷右边缘和下边缘的交点\n4. 左下角：试卷左边缘和下边缘的交点\n\n### 几何约束\n- top_left.y 与 top_right.y 的差值尽量小\n- bottom_left.y 与 bottom_right.y 的差值尽量小\n- top_left.x 与 bottom_left.x 的差值尽量小\n- top_right.x 与 bottom_right.x 的差值尽量小\n- 四点必须构成凸四边形\n\n### 输出格式\n请只返回 JSON，不要输出其他说明：\n```json\n{\n  "corners": {\n    "top_left": [x, y],\n    "top_right": [x, y],\n    "bottom_right": [x, y],\n    "bottom_left": [x, y]\n  },\n  "has_perspective_distortion": true\n}\n```\n\n### 注意事项\n- 坐标必须是整数，范围 0-1000\n- 如果有轻微折叠或弯曲，请选择最接近理想矩形的四个角点\n- 精确性非常重要，不要输出模糊描述""",
        },
        "legacy_selectors": [
            {"pipeline_step": 1, "target_type": "all_types"},
            {"name_like": "%perspective%"},
        ],
    },
    {
        "prompt_key": "preprocessor.page_classification.default",
        "display_name": "页面分类-单页",
        "module_name": "preprocessor",
        "description": "判断页面是试卷、答题纸还是混合页。",
        "category": "page_classification",
        "target_type": "full_page",
        "pipeline_step": 2,
        "seed_versions": {
            1: """请判断这张图片是试卷页、答题纸页、混合页还是其他页面。\n\n### 分类标准\n1. question_paper：以题干、题目文字、选项、图表、公式为主。\n2. answer_sheet：以作答区域、填涂区、答题框、个人信息区为主。\n3. mixed：同一页内同时明显出现题目内容和作答区域。\n4. other：无法判定为以上三类。\n\n### 输出要求\n只返回 JSON：\n```json\n{\n  "is_exam_paper": true,\n  "page_type": "question_paper",\n  "confidence": "high",\n  "reason": "简短说明主要依据"\n}\n```\n\n### 约束\n- reason 只写当前页直接可见的证据\n- 不要输出 JSON 之外的文字""",
        },
        "legacy_selectors": [
            {"pipeline_step": 2, "target_type": "full_page"},
            {"category": "page_classification"},
        ],
    },
    {
        "prompt_key": "preprocessor.long_image_classification.default",
        "display_name": "页面分类-长图",
        "module_name": "preprocessor",
        "description": "对拼接长图中的每张物理纸张分别判断类型。",
        "category": "page_classification",
        "target_type": "stitched_page",
        "pipeline_step": 2,
        "seed_versions": {
            1: """你是一个严格的试卷纸版面分类器。下面是一张由 [[num_sheets]] 张试卷纸水平拼接而成的长图，相邻纸张之间有明显的黑色间隔带。\n\n你的任务是：对每一张物理纸张分别判断类型。\n\n### 硬性要求\n- 长图中一共有且只有 [[num_sheets]] 张纸，你必须且只能输出 [[num_sheets]] 个结果\n- 每条结果只对应一张纸，禁止跨越黑色间隔带借用别的纸张信息\n- physical_index 表示物理位置：按长图从左到右编号，最左边是 0\n- order 表示内容逻辑顺序，可以与 physical_index 不同，但不能混淆\n\n### 类型定义\n1. 题目纸：以题干、题目文字、选项、图表、公式等内容为主。\n2. 答题纸：以答题框、基本信息区、大片手写作答区为主。\n3. 题目和答题混合纸：同一张纸内同时明显出现题目内容与答题区域。\n\n### 输出格式\n只返回 JSON 数组：\n```json\n[\n  {\n    "type": "题目纸",\n    "order": 1,\n    "physical_index": 0,\n    "reason": "简短版面依据"\n  }\n]\n```\n\n### 约束\n- 必须覆盖全部 [[num_sheets]] 张纸\n- 每个 physical_index 只能出现一次\n- reason 不要引用别的纸张信息\n- 禁止输出 JSON 之外的内容""",
            2: """你是一个严格的试卷纸版面分类器。下面是一张由 [[num_sheets]] 张试卷纸水平拼接而成的长图，相邻纸张之间有明显的黑色间隔带。

你的任务是：对每一张**物理纸张**分别判断类型。

**硬性要求**：
- 长图中一共有且只有 [[num_sheets]] 张纸，你必须且只能输出 [[num_sheets]] 个结果
- 每条结果只对应一张纸，禁止跨越黑色间隔带借用别的纸张信息
- `physical_index` 表示物理位置：按长图从左到右编号，最左边是 0
- `order` 表示内容逻辑顺序，可以与 `physical_index` 不同，但不能混淆

**如何理解“一张纸”**：
- 两条黑色间隔带之间的完整区域，就是一张物理纸张
- 如果一张 A3 纸左右两面都落在同一物理区域内，它仍然只算一张纸
- 你判断的单位是“纸张”，不是印刷页码

**类型定义**：
1. `题目纸`：以题干、题目文字、选项、图表、公式等内容为主，未见明确独立答题卡版式。印刷体文字面积远大于手写文字。
2. `答题纸`：以答题框、基本信息区、大片手写作答区为主。手写区面积+空白面积远大于印刷体文字面积。
3. `题目和答题混合纸`：同一张纸内同时明显出现题目内容与答题区域。并且本张图片中的其它试卷纸没有“答题纸”和“题目纸”，都是“题目和答题混合纸”。

**判断规则**：
- 先按黑色间隔带切分，再逐张独立判断
- 如果一张纸以题目内容为主，只夹杂少量手写批注或草稿，不要仅因为少量手写就判为混合纸
- 不要把左边纸张的特征拼到右边纸张上，也不要把不相邻纸张的信息合并解释

**reason 字段的强约束**：
- `reason` 只能写当前这张纸内**直接可见**的版面证据
- 允许描述：题干文字、填涂区、答题框、手写作答、答题卡字样、密封线、基本信息区
- 除非页码或题号在当前纸内**清晰可见**，否则不要写具体页码、题号
- 看不清就不要猜，不要根据整套卷的逻辑顺序补写页码/题号，不要引用其他纸张内容
- `reason` 请尽量简短，控制在 40 个字以内

**输出格式（必须严格遵守）**：
```json
[
  {
    "type": "题目纸 | 答题纸 | 题目和答题混合纸",
    "order": 1,
    "physical_index": 0,
    "reason": "左侧有填涂区，右侧有题干文字和答题框"
  }
]
```

**再次强调**：
- 必须覆盖全部 [[num_sheets]] 张纸
- 每个 `physical_index` 只能出现一次
- 禁止输出任何 JSON 之外的内容""",
        },
    },
    {
        "prompt_key": "preprocessor.extract_content.exam_paper",
        "display_name": "内容提取-试卷",
        "module_name": "preprocessor",
        "description": "从试卷页中识别题目框与题干描述。",
        "category": "content_extraction",
        "target_type": "exam_paper",
        "pipeline_step": 4,
        "seed_versions": {
            1: """你是一个试卷题目识别助手。请识别图片中的每一道完整题目，并输出结构化 JSON。\n\n### 识别原则\n- 每道完整题目只输出一个对象\n- 必须尽量完整包含题号、题干、选项、图表、公式\n- 如果图片是 A3 分页切片，当前图片可能是 [[side]] 半边，请仅识别本切片内可见且完整的题目\n\n### 输出格式\n只返回 JSON：\n```json\n{\n  "questions": [\n    {\n      "number": "1",\n      "type": "question",\n      "description": "题目简述",\n      "points": {\n        "top_left": [0, 0],\n        "top_right": [1000, 0],\n        "bottom_right": [1000, 1000],\n        "bottom_left": [0, 1000]\n      }\n    }\n  ]\n}\n```\n\n### 约束\n- 坐标使用 0-1000 归一化坐标\n- 不要输出 JSON 之外的文字\n- 如果没有识别到题目，返回 {"questions": []}""",
        },
        "legacy_selectors": [{"pipeline_step": 4, "category": "content_extraction", "target_type": "exam_paper"}],
    },
    {
        "prompt_key": "preprocessor.extract_content.answer_sheet",
        "display_name": "内容提取-答题纸",
        "module_name": "preprocessor",
        "description": "从答题纸中识别答题区域、涂卡区等结构。",
        "category": "content_extraction",
        "target_type": "answer_sheet",
        "pipeline_step": 4,
        "seed_versions": {
            1: """你是一个答题纸结构识别助手。请识别图片中的答题区域、选择题涂卡区、题号范围与关键说明文字，并输出结构化 JSON。\n\n### 识别目标\n- 主观题答题框/作答区域\n- 选择题涂卡区\n- 题号或题号范围\n- 与区域直接相关的说明文字\n\n### 输出格式\n只返回 JSON：\n```json\n{\n  "questions": [\n    {\n      "number": "1-5",\n      "type": "objective_choice",\n      "description": "选择题涂卡区",\n      "points": {\n        "top_left": [0, 0],\n        "top_right": [1000, 0],\n        "bottom_right": [1000, 1000],\n        "bottom_left": [0, 1000]\n      }\n    }\n  ]\n}\n```\n\n### 约束\n- 仅输出当前图中直接可见的信息\n- 坐标使用 0-1000 归一化坐标\n- 不要输出 JSON 之外的内容""",
        },
        "legacy_selectors": [{"pipeline_step": 4, "category": "content_extraction", "target_type": "answer_sheet"}],
    },
    {
        "prompt_key": "preprocessor.extract_content.mixed",
        "display_name": "内容提取-混合页",
        "module_name": "preprocessor",
        "description": "从混合页中同时识别题目与答题区域。",
        "category": "content_extraction",
        "target_type": "mixed",
        "pipeline_step": 4,
        "seed_versions": {
            1: """你是一个混合页结构识别助手。请同时识别图片中的题目区域与答题区域，并输出结构化 JSON。\n\n### 识别原则\n- 同时识别题目与作答区域\n- 每个对象都要给出 number、type、description、points\n- type 可用 question、answer_area、objective_choice 等简洁标签\n\n### 输出格式\n只返回 JSON：\n```json\n{\n  "questions": [\n    {\n      "number": "12",\n      "type": "question",\n      "description": "题目区域或答题区域说明",\n      "points": {\n        "top_left": [0, 0],\n        "top_right": [1000, 0],\n        "bottom_right": [1000, 1000],\n        "bottom_left": [0, 1000]\n      }\n    }\n  ]\n}\n```\n\n### 约束\n- 坐标使用 0-1000 归一化坐标\n- 不要输出 JSON 之外的任何文字\n- 无法确定时保持保守，不要臆造不可见内容""",
        },
        "legacy_selectors": [{"pipeline_step": 4, "category": "content_extraction", "target_type": "mixed"}],
    },
    {
        "prompt_key": "preprocessor.answer_card_recognition.default",
        "display_name": "涂卡识别",
        "module_name": "preprocessor",
        "description": "识别答题卡切片中的客观题答案。",
        "category": "answer_card_recognition",
        "target_type": "answer_card",
        "seed_versions": {
            1: """你是一个答题卡识别助手。请识别这张答题卡图片中每道题的填涂答案。\n\n### 识别要求\n1. 识别每道题的题号\n2. 识别每道题被填涂的选项（A/B/C/D）\n3. 如果某题未填涂，标记为 EMPTY\n4. 如果某题多选，选择填涂最深的那个选项\n\n### 输出格式\n请只返回 JSON：\n```json\n{\n  "1": "A",\n  "2": "C",\n  "3": "EMPTY"\n}\n```\n\n### 约束\n- 题号从 1 开始连续编号\n- 选项只能是 A/B/C/D/EMPTY\n- 不要输出 JSON 之外的内容""",
        },
    },
    {
        "prompt_key": "preprocessor.whole_page_detection.default",
        "display_name": "整页画框-题目识别",
        "module_name": "preprocessor",
        "description": "从整张长图中识别所有完整题目与边界框。",
        "category": "whole_page_detection",
        "target_type": "stitched_page",
        "seed_versions": {
            1: """你是一个专业的试卷题目识别助手。你的任务是识别这张完整试卷长图中的每一道完整题目，并为每道题画出一个边界框。\n\n### 核心要求\n1. 每道题一个框：每道完整题目只用一个矩形框框起来\n2. 完整包含：框要包含题号、题干、选项、图表、公式及配套作答区域（若同题紧邻）\n3. 不要把相邻两题合并成一个框\n4. number 字段尽量输出明确题号，不要随意写 unknown\n\n### 输出格式\n只返回 JSON：\n```json\n{\n  "questions": [\n    {\n      "number": "1",\n      "question_bbox": [0, 0, 500, 500],\n      "answer_bbox": [520, 0, 900, 500]\n    }\n  ]\n}\n```\n\n### 约束\n- 坐标使用像素坐标，基于当前整张输入图\n- 若没有单独答案区，可省略 answer_bbox\n- 不要输出 JSON 之外的文字""",
        },
    },
    {
        "prompt_key": "preprocessor.question_solver_recognition.default",
        "display_name": "题目求解-题目识别",
        "module_name": "question_solver",
        "description": "识别单题图片中的题干与结构信息。",
        "category": "question_solver",
        "target_type": "question_image",
        "seed_versions": {
            1: """请准确识别并转录这张题目图片中的所有内容。\n\n### 识别要求\n1. 完整题号：包括 1.、（1）、一、等标记\n2. 完整题干：包括文字、公式、化学方程式、图表说明\n3. 如果是选择题，完整列出选项内容\n4. 标记是否包含图示、公式\n\n### 输出格式\n请只返回 JSON：\n```json\n{\n  "question_number": "题号",\n  "question_content": "完整题干",\n  "question_type": "选择题/填空题/计算题/实验题",\n  "options": {"A": "", "B": "", "C": "", "D": ""},\n  "has_diagram": false,\n  "has_formula": false,\n  "recognition_confidence": 0.9\n}\n```\n\n### 约束\n- 按原意转录，不要自行改写\n- 不要输出 JSON 之外的说明文字""",
        },
    },
    {
        "prompt_key": "preprocessor.question_solver_solving.default",
        "display_name": "题目求解-解题推理",
        "module_name": "question_solver",
        "description": "生成结构化的化学题讲解与解题结论。",
        "category": "question_solver",
        "target_type": "question_text",
        "seed_versions": {
            1: """你是一名优秀的高中化学老师，请仔细解答以下化学题目。\n\n### 题目信息\n- 题号：[[question_number]]\n- 题型：[[question_type]]\n- 题目内容：[[question_content]][[options_text]]\n\n### 请按以下结构作答\n1. 题目分析\n2. 解题思路\n3. 详细解答步骤\n4. 最终答案\n5. 易错点提示\n6. 化学方程式/公式（如适用）\n\n### 要求\n- 语言简洁明了，逻辑清晰\n- 化学方程式书写规范\n- 计算过程完整\n- 适合高中生理解\n\n请直接开始解答。""",
        },
    },
    {
        "prompt_key": "analyzer.retrieval_keyword_extraction.default",
        "display_name": "分析器-检索关键词提取",
        "module_name": "analyzer",
        "description": "从问题中提取适合知识检索的关键词。",
        "category": "analyzer",
        "target_type": "text_query",
        "seed_versions": {
            1: """你是检索规划助手。请从下面的问题中提取 3-6 个最适合知识检索的关键词，仅返回 JSON：{"keywords": ["..."]}。\n\n问题：[[query]]""",
        },
    },
    {
        "prompt_key": "analyzer.question_vlm.default",
        "display_name": "分析器-题级 VLM",
        "module_name": "analyzer",
        "description": "结合题图和检索证据分析作答状态、知识点与疑似错因。",
        "category": "analyzer",
        "target_type": "question_bundle",
        "seed_versions": {
            1: """你是一名试题分析助手。请优先根据图片中的完整单元内容理解题目与学生作答，再结合补充文字与检索证据做谨慎判断。\n\n请只返回 JSON 对象，不要输出额外说明。\nJSON schema:\n{"question_summary":"","answer_observation":"","answer_status_assessment":"answered|uncertain|unanswered","correctness":"correct|incorrect|uncertain|unknown","knowledge_points":[""],"suspected_error_causes":[""],"reasoning_basis":[""],"recommended_next_action":"","confidence":0.0}\n\n补充题干文字：[[question_text]]\n结构化学生答案：[[student_answer]]\n当前答案状态：[[answer_status]]\n检索证据：[[retrieval_context]]\n\n要求：如果仅凭当前图片和证据无法确认正误，就将 correctness 设为 uncertain 或 unknown，不要臆测。""",
        },
    },
    {
        "prompt_key": "analyzer.final_conclusion.default",
        "display_name": "分析器-最终逐题结论",
        "module_name": "analyzer",
        "description": "融合检索结果与题级 VLM 观察，生成最终结论。",
        "category": "analyzer",
        "target_type": "analysis_payload",
        "seed_versions": {
            1: """你是一名试卷分析助手。请把检索结果 retrieval_result 与题级 VLM 观察 vlm_result 融合成最终逐题结论。\n\n只允许依据提供的证据作答；如果证据不足，请保留 uncertain 或 unknown，不要臆造标准答案。\n请只返回 JSON 对象，不要输出额外说明。\nJSON schema:\n{"summary":"","answer_status":"answered|uncertain|unanswered","correctness":"correct|incorrect|uncertain|unknown","mastery_level":"mastered|partial|weak|unknown","knowledge_points":[""],"error_causes":[""],"explanation":"","study_advice":[""],"supporting_evidence":[""],"recommended_next_action":"","confidence":0.0}\n\n输入数据：\n[[prompt_payload_json]]""",
        },
    },
    {
        "prompt_key": "analyzer.knowledge_extraction.default",
        "display_name": "分析器-知识抽取",
        "module_name": "analyzer",
        "description": "从文本中抽取实体与关系。",
        "category": "analyzer",
        "target_type": "knowledge_text",
        "seed_versions": {
            1: """Extract key entities and their relationships from the text below. Return the data as a JSON object with two keys: entities (a list of objects, each with name and a context snippet) and relationships (a list of objects, each with source, target, and type). Ensure the JSON is well-formed.\n\nText: [[text]]\n\nJSON output:""",
        },
    },
    {
        "prompt_key": "analyzer.topic_docx_block_points.default",
        "display_name": "分析器-专题DOCX块级知识点",
        "module_name": "analyzer",
        "description": "根据专题内容块文本列出可教学、可命题的知识点短语。",
        "category": "analyzer",
        "target_type": "topic_docx_segments",
        "seed_versions": {
            1: """你是一名中学教研助手。下面 JSON 的 blocks 数组中，每个元素是一段教辅/专题正文的片段（含 block_order、section_title、plain_text）。请**仅依据** plain_text 与 section_title，为该段列出本段涉及的核心知识点名称。

要求：
1. 只输出一个 JSON 对象，不要 Markdown、不要代码围栏、不要解释性文字。
2. 顶层结构必须为：{"blocks":[{"block_order":整数,"knowledge_point_names":["短语1","短语2",...]}]}。
3. knowledge_point_names 为 2～12 个字符串为宜；每个短语 2～24 个汉字为主，可含必要公式符号；不要整句照抄正文。
4. 必须与输入中的 block_order 一一对应；若某段无明确知识点可写空数组 []。
5. 不要编造输入中未体现的内容；宁可略少勿滥。

输入数据：
[[blocks_json]]""",
        },
    },
    {
        "prompt_key": "analyzer.topic_docx_question_bridge.default",
        "display_name": "分析器-专题题知识点桥接",
        "module_name": "analyzer",
        "description": "从本包候选知识点 ID 中为多选题干挑选最相关项。",
        "category": "analyzer",
        "target_type": "topic_question_bridge",
        "seed_versions": {
            1: """你是一名中学教研助手。下面给出一道题的文字（题干等）以及**仅限**下列候选知识点（每条含 knowledge_point_id 与 canonical_name）。请判断本题主要考查哪些知识点。

硬性规则：
1. 只输出一个 JSON 对象，不要 Markdown、不要代码围栏、不要解释。
2. 顶层结构必须为：{"knowledge_point_ids":[整数,...]}，数组元素必须全部来自候选中的 knowledge_point_id，禁止编造 ID。
3. 按相关性从高到低排列，最多输出 [[max_pick]] 个；若无法判断可输出空数组 []。
4. 宁缺毋滥：只有题干/选项/解析中确有依据时才选入。

专题标题：[[package_title]]

题干与题面文字：
[[question_text]]

候选知识点 JSON：
[[candidates_json]]""",
            2: """你是一名中学教研助手。下面给出一道题的文字（题干、选项、解析等）以及**仅限**下列候选知识点（每条含 knowledge_point_id 与 canonical_name）。请判断本题与哪些知识点相关，并给出**你自己判断的**关联强度。

硬性规则：
1. 只输出一个 JSON 对象，不要 Markdown、不要代码围栏、不要解释性文字。
2. 顶层结构必须为：{"links":[{"knowledge_point_id":整数,"relevance":0到1的小数,"confidence":0到1的小数}, ...]}。
   - links 可为空数组 []：当你认为候选中没有任何知识点与本题有足够依据相关时。
   - 最多 [[max_links]] 条；宁缺毋滥，不要为凑条数硬塞弱相关项。
   - knowledge_point_id 必须全部来自候选 JSON 中的 id，禁止编造。
   - relevance：0～1，表示本题与该知识点的相关程度（越高越相关）。
   - confidence：0～1，表示你对该判断的确信程度（可与 relevance 不同，例如概念模糊时 confidence 应偏低）。
3. 按 relevance 从高到低排列 links；不要输出除上述字段外的其它键。

专题标题：[[package_title]]

题干与题面文字：
[[question_text]]

候选知识点 JSON：
[[candidates_json]]""",
        },
    },
    {
        "prompt_key": "analyzer.knowledge_derivative.default",
        "display_name": "分析器-知识点衍生内容",
        "module_name": "analyzer",
        "description": "按知识点源快照 + 目标受众 + 衍生类型，生成结构化衍生内容。",
        "category": "analyzer",
        "target_type": "knowledge_derivative",
        "seed_versions": {
            1: """你是一名经验丰富的中学教研/命题教师。请基于【source_snapshot】中的知识点与已有教材块内容，面向 [[target_audience]] 产出类型为 [[derivative_type]] 的衍生内容。

硬性规则：
1. 只输出一个 JSON 对象，不要 Markdown、不要代码围栏、不要解释性文字。
2. 顶层结构必须为：
   {"title": "...", "summary": "...", "bullets": ["...", "..."], "body": "...", "quality": {"groundedness": 0到1, "coverage": 0到1}, "notes": "..."}
   - title：一句话命名（≤20 字），要能作为卡片/条目的标题。
   - summary：2~4 句话的摘要，面向目标受众的通俗语言。
   - bullets：3~6 条要点，每条≤40 字；不要机械罗列正文，要有「提炼」。
   - body：完整的衍生正文，80~400 字；对 student/parent 用通俗语言并尽量举例，对 teacher 侧重命题点/易错点/讲法。
   - quality.groundedness：本衍生内容与 source_snapshot 的贴合度（越贴近原文事实越高）。
   - quality.coverage：对知识点核心要点的覆盖面。
   - notes：可选，若 source_snapshot 明显信息不足或有歧义，写一句提醒；否则 ""。
3. 禁止编造 source_snapshot 中没有的定义、公式、数值或题目；允许做通俗化解释与类比，但要与原文一致。
4. 不要输出除上述字段外的其它键。

derivative_type 语义参考：
- concept_explainer：通俗化讲解，配合类比/例子。
- exam_cheatsheet：考点速记卡，强调公式/要点/典型题型。
- common_pitfalls：常见错误与纠正建议。
- comparison：与易混知识点/概念的对比。
- memory_tip：口诀/联想/图示思路的记忆方法。

知识点：[[knowledge_point_name]]
学科/学段：[[subject_grade]]
目标受众（target_audience）：[[target_audience]]
衍生类型（derivative_type）：[[derivative_type]]

源快照 JSON（source_snapshot）：
[[source_snapshot]]""",
        },
    },
    {
        "prompt_key": "analyzer.ask.answer_generation.default",
        "display_name": "分析器-问答生成",
        "module_name": "analyzer",
        "description": "基于检索上下文回答用户问题。",
        "category": "analyzer",
        "target_type": "qa_context",
        "seed_versions": {
            1: """你是一名知识库问答助手。请严格基于下面提供的检索上下文回答用户问题；如果上下文不足，请明确说明。\n\nContext:\n[[context]]\n\nQuestion: [[question]]\n\nAnswer:""",
        },
    },
]


PROMPT_DEFINITION_MAP = {
    definition["prompt_key"]: definition for definition in PROMPT_DEFINITIONS
}


PROMPT_STEP_DEFINITIONS = [
    {
        "step_key": "preprocessor.perspective_correction",
        "step_label": "预处理-透视矫正",
        "module_name": "preprocessor",
        "step_order": "1",
        "description": "预处理主流程透视矫正使用的提示词。",
        "prompt_key": "preprocessor.perspective_correction.default",
    },
    {
        "step_key": "preprocessor.classify",
        "step_label": "预处理-页面分类（单页）",
        "module_name": "preprocessor",
        "step_order": "2",
        "description": "预处理主流程单页分类使用的提示词。",
        "prompt_key": "preprocessor.page_classification.default",
    },
    {
        "step_key": "preprocessor.long_image_classification",
        "step_label": "预处理-页面分类（长图）",
        "module_name": "preprocessor",
        "step_order": "2-long-image",
        "description": "预处理主流程长图分类使用的提示词。",
        "prompt_key": "preprocessor.long_image_classification.default",
    },
    {
        "step_key": "preprocessor.extract_content.exam_paper",
        "step_label": "预处理-内容提取（试卷）",
        "module_name": "preprocessor",
        "step_order": "4-exam",
        "description": "内容提取步骤在试卷页场景使用的提示词。",
        "prompt_key": "preprocessor.extract_content.exam_paper",
    },
    {
        "step_key": "preprocessor.extract_content.answer_sheet",
        "step_label": "预处理-内容提取（答题纸）",
        "module_name": "preprocessor",
        "step_order": "4-answer-sheet",
        "description": "内容提取步骤在答题纸场景使用的提示词。",
        "prompt_key": "preprocessor.extract_content.answer_sheet",
    },
    {
        "step_key": "preprocessor.extract_content.mixed",
        "step_label": "预处理-内容提取（混合页）",
        "module_name": "preprocessor",
        "step_order": "4-mixed",
        "description": "内容提取步骤在混合页场景使用的提示词。",
        "prompt_key": "preprocessor.extract_content.mixed",
    },
    {
        "step_key": "preprocessor.answer_card_recognition",
        "step_label": "预处理-涂卡识别",
        "module_name": "preprocessor",
        "step_order": "6",
        "description": "答题卡识别步骤使用的提示词。",
        "prompt_key": "preprocessor.answer_card_recognition.default",
    },
    {
        "step_key": "preprocessor.whole_page_perspective_correction",
        "step_label": "整页画框-透视矫正",
        "module_name": "preprocessor",
        "step_order": "whole-page:2",
        "description": "整页画框流程的透视矫正提示词。",
        "prompt_key": "preprocessor.perspective_correction.default",
    },
    {
        "step_key": "preprocessor.whole_page_detection",
        "step_label": "整页画框-题目识别",
        "module_name": "preprocessor",
        "step_order": "whole-page:4",
        "description": "整页画框流程的题目识别提示词。",
        "prompt_key": "preprocessor.whole_page_detection.default",
    },
    {
        "step_key": "preprocessor.question_solver_recognition",
        "step_label": "题目求解-题目识别",
        "module_name": "question_solver",
        "step_order": "question-solver:recognize",
        "description": "题目求解工具中的题图识别提示词。",
        "prompt_key": "preprocessor.question_solver_recognition.default",
    },
    {
        "step_key": "preprocessor.question_solver_solving",
        "step_label": "题目求解-解题推理",
        "module_name": "question_solver",
        "step_order": "question-solver:solve",
        "description": "题目求解工具中的解题提示词。",
        "prompt_key": "preprocessor.question_solver_solving.default",
    },
    {
        "step_key": "analyzer.retrieval_keyword_extraction",
        "step_label": "分析器-检索关键词提取",
        "module_name": "analyzer",
        "step_order": "retrieval-keywords",
        "description": "分析器检索规划使用的关键词提取提示词。",
        "prompt_key": "analyzer.retrieval_keyword_extraction.default",
    },
    {
        "step_key": "analyzer.question_vlm",
        "step_label": "分析器-题级 VLM",
        "module_name": "analyzer",
        "step_order": "question-vlm",
        "description": "分析器逐题图片分析使用的提示词。",
        "prompt_key": "analyzer.question_vlm.default",
    },
    {
        "step_key": "analyzer.final_conclusion",
        "step_label": "分析器-最终逐题结论",
        "module_name": "analyzer",
        "step_order": "final-conclusion",
        "description": "分析器融合检索与 VLM 结果生成最终结论的提示词。",
        "prompt_key": "analyzer.final_conclusion.default",
    },
    {
        "step_key": "analyzer.knowledge_extraction",
        "step_label": "分析器-知识抽取",
        "module_name": "analyzer",
        "step_order": "knowledge-extraction",
        "description": "分析器构建知识图谱时使用的知识抽取提示词。",
        "prompt_key": "analyzer.knowledge_extraction.default",
    },
    {
        "step_key": "analyzer.topic_docx_block_points",
        "step_label": "分析器-专题DOCX块级知识点",
        "module_name": "analyzer",
        "step_order": "topic-docx-block-points",
        "description": "专题 DOCX 按块调用大模型补充知识点名称（与正则规则互补）。",
        "prompt_key": "analyzer.topic_docx_block_points.default",
    },
    {
        "step_key": "analyzer.topic_docx_question_bridge",
        "step_label": "分析器-专题题知识点桥接",
        "module_name": "analyzer",
        "step_order": "topic-docx-question-bridge",
        "description": "专题材料每道题从候选知识点中由大模型挑选最相关项。",
        "prompt_key": "analyzer.topic_docx_question_bridge.default",
    },
    {
        "step_key": "analyzer.knowledge_derivative_generation",
        "step_label": "分析器-知识点衍生内容",
        "module_name": "analyzer",
        "step_order": "knowledge-derivative",
        "description": "知识点衍生层按类型+受众生成内容时使用的提示词。",
        "prompt_key": "analyzer.knowledge_derivative.default",
    },
    {
        "step_key": "analyzer.ask.answer_generation",
        "step_label": "分析器-问答生成",
        "module_name": "analyzer",
        "step_order": "ask-answer",
        "description": "分析器问答接口使用的回答生成提示词。",
        "prompt_key": "analyzer.ask.answer_generation.default",
    },
]


PROMPT_STEP_DEFINITION_MAP = {
    definition["step_key"]: definition for definition in PROMPT_STEP_DEFINITIONS
}


_TEMPLATE_PATTERN = re.compile(r"\[\[\s*([a-zA-Z0-9_]+)\s*\]\]")


def ensure_prompt_step_config_table(bind) -> None:
    models.PromptStepConfig.__table__.create(bind=bind, checkfirst=True)


def _query_prompt_by_key(db: Session, prompt_key: str) -> Optional[models.Prompt]:
    return (
        db.query(models.Prompt)
        .options(joinedload(models.Prompt.versions))
        .filter(models.Prompt.name == prompt_key)
        .first()
    )


def _query_all_registered_prompts(db: Session) -> list[models.Prompt]:
    records = (
        db.query(models.Prompt)
        .options(joinedload(models.Prompt.versions))
        .filter(models.Prompt.name.in_(list(PROMPT_DEFINITION_MAP.keys())))
        .all()
    )
    sort_index = {definition["prompt_key"]: index for index, definition in enumerate(PROMPT_DEFINITIONS)}
    return sorted(records, key=lambda item: sort_index.get(item.name, 9999))


def _query_step_config(db: Session, step_key: str) -> Optional[models.PromptStepConfig]:
    return db.query(models.PromptStepConfig).filter(models.PromptStepConfig.step_key == step_key).first()


def _query_all_step_configs(db: Session) -> list[models.PromptStepConfig]:
    records = db.query(models.PromptStepConfig).all()
    sort_index = {definition["step_key"]: index for index, definition in enumerate(PROMPT_STEP_DEFINITIONS)}
    return sorted(records, key=lambda item: sort_index.get(item.step_key, 9999))


def _extract_legacy_versions(db: Session, definition: Dict[str, Any]) -> Dict[int, str]:
    version_map: Dict[int, str] = {}
    selectors = definition.get("legacy_selectors") or []
    for selector in selectors:
        query = db.query(models.Prompt).options(joinedload(models.Prompt.versions))
        if selector.get("pipeline_step") is not None:
            query = query.filter(models.Prompt.pipeline_step == selector["pipeline_step"])
        if selector.get("category"):
            query = query.filter(models.Prompt.category == selector["category"])
        if selector.get("target_type"):
            query = query.filter(models.Prompt.target_type == selector["target_type"])
        if selector.get("name_like"):
            query = query.filter(models.Prompt.name.like(selector["name_like"]))

        for legacy_prompt in query.all():
            if legacy_prompt.name == definition["prompt_key"]:
                continue
            for version in legacy_prompt.versions or []:
                if version.prompt_text and version.version not in version_map:
                    version_map[int(version.version)] = version.prompt_text
    return version_map


def _ensure_prompt_versions(db: Session, prompt: models.Prompt, version_map: Dict[int, str]) -> bool:
    existing_map = {int(item.version): item for item in prompt.versions or []}
    changed = False
    for version_number, prompt_text in sorted(version_map.items()):
        if not prompt_text:
            continue
        if version_number in existing_map:
            continue
        db.add(
            models.PromptVersion(
                prompt_id=prompt.id,
                version=int(version_number),
                prompt_text=prompt_text,
                status="published",
                created_by="system",
                change_log="system seed",
            )
        )
        changed = True
    if version_map:
        max_version = max(int(item) for item in version_map.keys())
        if prompt.version != max_version:
            prompt.version = max_version
            changed = True
    if prompt.is_latest is not True:
        prompt.is_latest = True
        changed = True
    if prompt.is_active is not True:
        prompt.is_active = True
        changed = True
    return changed


def sync_prompt_catalog(db: Session) -> list[Dict[str, Any]]:
    existing_map = {record.name: record for record in _query_all_registered_prompts(db)}
    changed = False

    for definition in PROMPT_DEFINITIONS:
        prompt = existing_map.get(definition["prompt_key"])
        if prompt is None:
            prompt = models.Prompt(
                name=definition["prompt_key"],
                display_name=definition.get("display_name"),
                description=definition.get("description"),
                pipeline_step=definition.get("pipeline_step"),
                category=definition.get("category"),
                target_type=definition.get("target_type"),
                scenario=definition.get("scenario"),
                version=1,
                is_latest=True,
                is_active=True,
                created_by="system",
            )
            db.add(prompt)
            db.flush()
            existing_map[prompt.name] = prompt
            changed = True
        else:
            if definition.get("display_name") and prompt.display_name != definition.get("display_name"):
                prompt.display_name = definition.get("display_name")
                changed = True
            if prompt.description != definition.get("description"):
                prompt.description = definition.get("description")
                changed = True
            if prompt.pipeline_step != definition.get("pipeline_step"):
                prompt.pipeline_step = definition.get("pipeline_step")
                changed = True
            if prompt.category != definition.get("category"):
                prompt.category = definition.get("category")
                changed = True
            if prompt.target_type != definition.get("target_type"):
                prompt.target_type = definition.get("target_type")
                changed = True
            if prompt.scenario != definition.get("scenario"):
                prompt.scenario = definition.get("scenario")
                changed = True

        version_map = _extract_legacy_versions(db, definition)
        if not version_map:
            version_map = {int(version): text for version, text in (definition.get("seed_versions") or {}).items()}
        if _ensure_prompt_versions(db, prompt, version_map):
            changed = True

    if changed:
        db.commit()

    return [serialize_prompt(record) for record in _query_all_registered_prompts(db)]


def sync_prompt_step_configs(db: Session) -> list[Dict[str, Any]]:
    ensure_prompt_step_config_table(db.bind)
    sync_prompt_catalog(db)

    existing_map = {record.step_key: record for record in db.query(models.PromptStepConfig).all()}
    changed = False
    for definition in PROMPT_STEP_DEFINITIONS:
        record = existing_map.get(definition["step_key"])
        if record is None:
            record = models.PromptStepConfig(
                step_key=definition["step_key"],
                step_label=definition["step_label"],
                module_name=definition["module_name"],
                step_order=definition.get("step_order"),
                description=definition.get("description"),
                prompt_key=definition["prompt_key"],
                is_active=True,
                selected_version=None,
            )
            db.add(record)
            changed = True
            continue

        for field_name in ["step_label", "module_name", "step_order", "description", "prompt_key"]:
            expected = definition.get(field_name)
            if getattr(record, field_name) != expected:
                setattr(record, field_name, expected)
                changed = True

    if changed:
        db.commit()

    return [serialize_prompt_step_config(db, record) for record in _query_all_step_configs(db)]


def list_prompt_step_configs(db: Session, *, version_override: Optional[Any] = None) -> list[Dict[str, Any]]:
    sync_prompt_step_configs(db)
    return [serialize_prompt_step_config(db, record, version_override=version_override) for record in _query_all_step_configs(db)]



def get_prompt_step_config(db: Session, step_key: str) -> Optional[models.PromptStepConfig]:
    sync_prompt_step_configs(db)
    return _query_step_config(db, step_key)


def list_registered_prompts(db: Session) -> list[Dict[str, Any]]:
    sync_prompt_catalog(db)
    return [serialize_prompt(record) for record in _query_all_registered_prompts(db)]


def _select_prompt_version(prompt: Optional[models.Prompt], requested_version: Optional[int] = None) -> tuple[Optional[models.PromptVersion], str]:
    if not prompt:
        return None, "prompt_not_found"

    versions = sorted(prompt.versions or [], key=lambda item: int(item.version), reverse=True)
    if not versions:
        return None, "version_not_found"

    if requested_version is not None:
        for version in versions:
            if int(version.version) == int(requested_version):
                return version, "requested"

    published_versions = [item for item in versions if (item.status or "published") == "published"]
    if published_versions:
        return published_versions[0], "highest_published"
    return versions[0], "highest_version"


def serialize_prompt(prompt: models.Prompt) -> Dict[str, Any]:
    definition = PROMPT_DEFINITION_MAP.get(prompt.name, {})
    versions = sorted(prompt.versions or [], key=lambda item: int(item.version), reverse=True)
    latest = versions[0] if versions else None
    bound_steps = [item for item in PROMPT_STEP_DEFINITIONS if item["prompt_key"] == prompt.name]
    return {
        "id": prompt.id,
        "name": prompt.name,
        "display_name": prompt.display_name,
        "description": prompt.description,
        "module_name": definition.get("module_name"),
        "category": prompt.category,
        "target_type": prompt.target_type,
        "pipeline_step": prompt.pipeline_step,
        "version": prompt.version,
        "is_active": prompt.is_active,
        "updated_at": prompt.updated_at.isoformat() if getattr(prompt, "updated_at", None) else None,
        "created_at": prompt.created_at.isoformat() if getattr(prompt, "created_at", None) else None,
        "prompt_text": latest.prompt_text if latest else "",
        "version_count": len(versions),
        "available_versions": [int(item.version) for item in versions],
        "step_keys": [item["step_key"] for item in bound_steps],
        "step_labels": [item["step_label"] for item in bound_steps],
    }


def serialize_prompt_step_config(
    db: Session,
    record: models.PromptStepConfig,
    *,
    version_override: Optional[Any] = None,
) -> Dict[str, Any]:
    prompt = _query_prompt_by_key(db, record.prompt_key)
    selected_version = int(record.selected_version) if record.selected_version is not None else None
    override_version = parse_prompt_version(version_override)
    requested_version = override_version if override_version is not None else selected_version
    resolved_version, source = _select_prompt_version(prompt, requested_version)
    available_versions = sorted([int(item.version) for item in (prompt.versions or [])], reverse=True) if prompt else []
    return {
        "id": record.id,
        "step_key": record.step_key,
        "step_label": record.step_label,
        "module_name": record.module_name,
        "step_order": record.step_order,
        "description": record.description,
        "prompt_key": record.prompt_key,
        "prompt_id": prompt.id if prompt else None,
        "prompt_display_name": prompt.display_name if prompt else None,
        "selected_version": selected_version,
        "selected_version_mode": "fixed" if selected_version is not None else "latest",
        "requested_version": requested_version,
        "resolved_version": int(resolved_version.version) if resolved_version else None,
        "resolution_source": source,
        "config_source": "version_override" if override_version is not None else ("prompt_step_config" if selected_version is not None else "highest_version"),
        "available_versions": available_versions,
        "is_active": record.is_active,
        "config_complete": bool(prompt and available_versions),
        "resolved_prompt_text": resolved_version.prompt_text if resolved_version else None,
        "resolved_prompt_status": resolved_version.status if resolved_version else None,
        "resolved_prompt_change_log": resolved_version.change_log if resolved_version else None,
    }



def update_prompt_step_config(
    db: Session,
    step_key: str,
    *,
    selected_version: Optional[int] = None,
    is_active: bool = True,
) -> Dict[str, Any]:
    record = get_prompt_step_config(db, step_key)
    if not record:
        raise ValueError(f"Unknown step_key: {step_key}")

    prompt = _query_prompt_by_key(db, record.prompt_key)
    if not prompt:
        raise ValueError(f"Prompt not found for step: {record.prompt_key}")

    if selected_version is not None:
        _, source = _select_prompt_version(prompt, int(selected_version))
        if source != "requested":
            raise ValueError(f"版本 v{selected_version} 在提示词 `{record.prompt_key}` 中不存在")
        record.selected_version = int(selected_version)
    else:
        record.selected_version = None

    record.is_active = bool(is_active)
    db.commit()
    return serialize_prompt_step_config(db, record)


def get_prompt_detail(db: Session, prompt_id: int) -> Optional[Dict[str, Any]]:
    sync_prompt_catalog(db)
    prompt = (
        db.query(models.Prompt)
        .options(joinedload(models.Prompt.versions))
        .filter(models.Prompt.id == prompt_id, models.Prompt.name.in_(list(PROMPT_DEFINITION_MAP.keys())))
        .first()
    )
    if not prompt:
        return None

    versions = sorted(prompt.versions or [], key=lambda item: int(item.version), reverse=True)
    payload = serialize_prompt(prompt)
    payload["versions"] = [
        {
            "id": item.id,
            "version": int(item.version),
            "prompt_text": item.prompt_text,
            "status": item.status,
            "change_log": item.change_log,
            "created_at": item.created_at.isoformat() if item.created_at else None,
            "created_by": item.created_by,
        }
        for item in versions
    ]
    return payload


def create_prompt_version(
    db: Session,
    prompt_id: int,
    *,
    prompt_text: str,
    version: int,
    status: str = "published",
    change_log: str = "",
) -> Dict[str, Any]:
    sync_prompt_catalog(db)
    prompt = (
        db.query(models.Prompt)
        .options(joinedload(models.Prompt.versions))
        .filter(models.Prompt.id == prompt_id, models.Prompt.name.in_(list(PROMPT_DEFINITION_MAP.keys())))
        .first()
    )
    if not prompt:
        raise ValueError("提示词不存在")
    if not prompt_text or len(prompt_text.strip()) < 10:
        raise ValueError("提示词内容太短（至少 10 个字符）")
    if int(version) <= 0:
        raise ValueError("版本号必须是正整数")
    if any(int(item.version) == int(version) for item in prompt.versions or []):
        raise ValueError(f"版本 v{version} 已存在")

    db.add(
        models.PromptVersion(
            prompt_id=prompt.id,
            version=int(version),
            prompt_text=prompt_text,
            status=status,
            change_log=change_log,
            created_by="admin",
        )
    )
    prompt.version = max(int(prompt.version or 0), int(version))
    prompt.is_latest = True
    prompt.is_active = True
    db.commit()
    return get_prompt_detail(db, prompt.id)


def list_available_prompt_versions(db: Session) -> list[Dict[str, Any]]:
    sync_prompt_catalog(db)
    version_counts: Dict[int, int] = {}
    for prompt in _query_all_registered_prompts(db):
        for version in prompt.versions or []:
            version_counts[int(version.version)] = version_counts.get(int(version.version), 0) + 1
    return [
        {"version": version, "count": count, "label": f"版本 v{version} ({count}个提示词)"}
        for version, count in sorted(version_counts.items(), reverse=True)
    ]


def _render_prompt_text(prompt_text: str, variables: Optional[Dict[str, Any]] = None) -> str:
    if not variables:
        return prompt_text

    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        value = variables.get(key)
        return "" if value is None else str(value)

    return _TEMPLATE_PATTERN.sub(replacer, prompt_text)


def get_seed_prompt_text(
    prompt_key: str,
    *,
    version: Optional[Any] = None,
    variables: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    definition = PROMPT_DEFINITION_MAP.get(prompt_key)
    if not definition:
        return None

    seed_versions = {int(item_version): item_text for item_version, item_text in (definition.get("seed_versions") or {}).items()}
    if not seed_versions:
        return None

    requested_version = parse_prompt_version(version)
    if requested_version is None or requested_version not in seed_versions:
        requested_version = max(seed_versions.keys())

    prompt_text = seed_versions.get(requested_version)
    if not prompt_text:
        return None
    return _render_prompt_text(prompt_text, variables=variables)


def parse_prompt_version(value: Any) -> Optional[int]:
    if value in (None, "", "latest"):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    normalized = str(value).strip().lower()
    if not normalized or normalized == "latest":
        return None
    if normalized.startswith("v"):
        normalized = normalized[1:]
    if normalized.isdigit():
        parsed = int(normalized)
        return parsed if parsed > 0 else None
    return None



def resolve_step_prompt(
    db: Session,
    step_key: str,
    *,
    version_override: Optional[Any] = None,
    variables: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    record = get_prompt_step_config(db, step_key)
    if not record or not record.is_active:
        return None

    prompt = _query_prompt_by_key(db, record.prompt_key)
    requested_version = parse_prompt_version(version_override)
    if requested_version is None:
        requested_version = int(record.selected_version) if record.selected_version is not None else None

    resolved_version, source = _select_prompt_version(prompt, requested_version)
    if not prompt or not resolved_version:
        return None

    rendered_text = _render_prompt_text(resolved_version.prompt_text, variables=variables)
    return {
        "step_key": step_key,
        "step_label": record.step_label,
        "prompt_key": record.prompt_key,
        "prompt_id": prompt.id,
        "prompt_display_name": prompt.display_name,
        "prompt_text": rendered_text,
        "resolved_version": int(resolved_version.version),
        "requested_version": requested_version,
        "version_source": source,
        "config_source": "prompt_step_config" if record.selected_version is not None else "highest_version",
    }


def get_prompt_summary_by_step(db: Session, step_keys: Iterable[str], version_override: Optional[Any] = None) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for step_key in step_keys:
        resolved = resolve_step_prompt(db, step_key, version_override=version_override)
        if resolved:
            summary[step_key] = {
                "prompt_key": resolved["prompt_key"],
                "resolved_version": resolved["resolved_version"],
                "version_source": resolved["version_source"],
            }
    return summary
