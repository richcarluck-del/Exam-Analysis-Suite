import json
import os
from typing import List
from .utils import call_api, extract_json
from .models import ExamPage

class PageClassifier:
    def __init__(self, model: str = None):
        self.model = model

    def classify(self, image_paths: List[str] | str, api_key: str, model_name: str, api_url: str) -> List[ExamPage] | ExamPage:
        print(f"[DEBUG-TRACE] Entered 'classifier.classify' with:")
        print(f"[DEBUG-TRACE]   - image_paths type: {type(image_paths)}")
        print(f"[DEBUG-TRACE]   - api_key is None: {api_key is None}")
        print(f"[DEBUG-TRACE]   - model_name: {model_name}")
        print(f"[DEBUG-TRACE]   - api_url: {api_url}")
        if isinstance(image_paths, str):
            # Handle single image path, return a single ExamPage object
            results = self.classify([image_paths], api_key=api_key, model_name=model_name, api_url=api_url)
            return results[0] if results else ExamPage(image_path=image_paths, page_type="other", page_index=0)
            
        pages = []
        for i, path in enumerate(image_paths):
            prompt = """请判断这张图片是否是一张**试卷**或**考试题目**。

**页面类型判断标准**：
1. **question_paper (试卷)**：
   - 包含完整的**题干内容**（题目文字描述）。
   - 可能包含选项描述、插图、公式。
   - 特征：文字量大，描述性强。

2. **answer_sheet (答题纸)**：
   - 主要由**作答区域**或**考场信息区**组成。
   - **客观题区**：成排的 A, B, C, D 涂卡圆圈或方框。
   - **主观题区**：大片的空白框、填空线，旁边标有题号。
   - **基本信息区**：姓名、准考证号、条形码粘贴区、考试标题。
   - 特征：有大量矩形框或重复的选项符号，或者包含“答题纸/答题卡”字样的标题页。

3. **mixed (混合)**：一张图中既有大量题干又有大量答题区域。

请输出 JSON 格式：
```json
{
  "is_exam_paper": true/false,
  "page_type": "question_paper" 或 "answer_sheet" 或 "mixed" 或 "other",
  "confidence": "high/medium/low",
  "reason": "简短的判断依据（请重点区分是‘题干文字’还是‘作答区域’）"
}
```"""
            try:
                content = call_api(
                    prompt=prompt,
                    image_path=path,
                    api_url=api_url,
                    api_key=api_key,
                    model_name=model_name
                )
                json_str = extract_json(content)
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError:
                    print(f"  [错误] 无法解析分类模型返回的JSON: {json_str}")
                    result = {} # or handle error appropriately
                
                print(f"  [Debug] {os.path.basename(path)} 分类结果: {result}")
                
                is_exam = result.get("is_exam_paper", False)
                page_type = result.get("page_type", "other")
                if not is_exam and page_type != "other":
                    page_type = "other"
                elif is_exam and page_type == "other":
                    page_type = "question_paper"
                
                pages.append(ExamPage(
                    image_path=path,
                    page_type=page_type,
                    page_index=i
                ))
                print(f"  [分类] {os.path.basename(path)}: {page_type} ({result.get('reason', '')})")
            except Exception as e:
                print(f"  [错误] 分类图片 {path} 失败: {e}")
                pages.append(ExamPage(
                    image_path=path,
                    page_type="other",
                    page_index=i
                ))
        return pages
