import json
import os
from typing import List
from .utils import call_api, extract_json
from shared.prompt_step_config import get_seed_prompt_text

# Import from models.py directly to avoid circular import
import sys
from pathlib import Path
current_dir = Path(__file__).parent
models_py_path = current_dir / "models.py"
if models_py_path.exists():
    import importlib.util
    spec = importlib.util.spec_from_file_location("models_module", models_py_path)
    models_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(models_module)
    ExamPage = models_module.ExamPage
else:
    raise ImportError(f"models.py not found at {models_py_path}")

class PageClassifier:
    def __init__(self, model: str = None, prompt: str = None):
        self.model = model
        self.prompt = prompt or get_seed_prompt_text("preprocessor.page_classification.default") or ""

    def classify(self, image_paths: List[str] | str, api_key: str, model_name: str, api_url: str, logger=None, max_retries: int = 3) -> List[ExamPage] | ExamPage:
        print(f"[DEBUG-TRACE] Entered 'classifier.classify' with:")
        print(f"[DEBUG-TRACE]   - image_paths type: {type(image_paths)}")
        print(f"[DEBUG-TRACE]   - api_key is None: {api_key is None}")
        print(f"[DEBUG-TRACE]   - model_name: {model_name}")
        print(f"[DEBUG-TRACE]   - api_url: {api_url}")
        print(f"[DEBUG-TRACE]   - max_retries: {max_retries}")
        if isinstance(image_paths, str):
            # Handle single image path, return a single ExamPage object
            results = self.classify([image_paths], api_key=api_key, model_name=model_name, api_url=api_url, max_retries=max_retries)
            return results[0] if results else ExamPage(image_path=image_paths, page_type="other", page_index=0)
            
        pages = []
        for i, path in enumerate(image_paths):
            prompt = self.prompt
            attempt = 0
            content = None
            
            # 重试循环
            while attempt < max_retries:
                attempt += 1
                
                if attempt == 1:
                    print(f"  [尝试] 第 1 次调用分类 {os.path.basename(path)}（共{max_retries}次机会）")
                else:
                    print(f"  [重试] 第 {attempt} 次重试分类 {os.path.basename(path)}（共{max_retries}次机会）")
                
                try:
                    content = call_api(
                        prompt=prompt,
                        image_path=path,
                        api_url=api_url,
                        api_key=api_key,
                        model_name=model_name,
                        logger=logger,
                        step_name="page_classification",
                        min_content_length=30  # 分类结果需要 JSON，设置适中的最小长度
                    )
                    break  # 成功则跳出重试循环
                except Exception as e:
                    if attempt < max_retries:
                        print(f"  [警告] 第 {attempt} 次调用失败：{e}，准备重试...")
                    else:
                        print(f"  [错误] 已达最大重试次数 ({max_retries})，分类失败：{e}")
                        content = None
            
            # 如果所有重试都失败，使用默认值
            if not content:
                print(f"  [错误] 分类 {os.path.basename(path)} 失败，使用默认类型 'other'")
                pages.append(ExamPage(
                    image_path=path,
                    page_type="other",
                    page_index=i
                ))
                continue
            
            json_str = extract_json(content)
            try:
                result = json.loads(json_str)
            except json.JSONDecodeError:
                print(f"  [错误] 无法解析分类模型返回的 JSON: {json_str}")
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
