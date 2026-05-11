"""
使用大模型(VLM)识别涂卡区答案

功能：
1. 调用 Gemini 等大模型 API 识别涂卡区
2. 解析返回的 JSON 格式答案
3. 集成到现有流程中
4. 支持从数据库读取配置
"""

import json
import os
from typing import Dict, Optional
from src.utils import call_api
from shared.prompt_step_config import get_seed_prompt_text


def recognize_answer_card_with_vlm(
    crop_image_path: str,
    api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    model_name: Optional[str] = None,
    api_key_decrypted: bool = True,  # 新增参数，标记 API Key 是否已解密
    prompt_override: Optional[str] = None,
) -> Dict[str, str]:
    """
    使用大模型识别涂卡区答案
    
    Args:
        crop_image_path: 涂卡区切片图片路径
        api_url: API 端点（可选，默认从数据库读取）
        api_key: API 密钥（可选，默认从数据库读取）
        model_name: 模型名称（可选，默认从数据库读取）
        api_key_decrypted: API Key 是否已解密（默认 True）
        
    Returns:
        答案字典：{'1': 'A', '2': 'C', ...}
    """
    # 从数据库获取配置（如果参数未提供）
    if not all([api_url, api_key, model_name]):
        from src.answer_card.vlm_config import get_vlm_config
        config = get_vlm_config(model_name=model_name)
        
        if not config:
            print("  [VLM 识别] 错误：无法从数据库获取 VLM 配置")
            return {}
        
        api_url = api_url or config.api_url
        api_key = api_key or config.api_key
        model_name = model_name or config.model_name
    
    print(f"  [VLM 识别] 使用模型: {model_name}")
    print(f"  [VLM 识别] 图片: {crop_image_path}")
    
    # 构建提示词
    prompt = prompt_override or get_seed_prompt_text("preprocessor.answer_card_recognition.default") or ""

    try:
        # 重试逻辑
        max_retries = 3
        response = None
        attempt = 0
        
        while attempt < max_retries:
            attempt += 1
            
            if attempt == 1:
                print(f"  [VLM 识别] 第 1 次调用涂卡识别（共{max_retries}次机会）")
            else:
                print(f"  [VLM 识别] 第 {attempt} 次重试涂卡识别（共{max_retries}次机会）")
            
            try:
                response = call_api(
                    prompt=prompt,
                    api_url=api_url,
                    api_key=api_key,
                    model_name=model_name,
                    image_path=crop_image_path,
                    step_name="answer_card_vlm_recognition",
                    min_content_length=15  # 涂卡识别需要返回 JSON，设置较低的最小长度
                )
                print(f"  [VLM 识别] 第 {attempt} 次调用成功，API 返回内容长度：{len(response)}")
                break  # 成功则跳出重试循环
            except Exception as api_error:
                if attempt < max_retries:
                    print(f"  [VLM 识别] 第 {attempt} 次调用失败：{api_error}，准备重试...")
                else:
                    print(f"  [VLM 识别] 已达最大重试次数 ({max_retries})，涂卡识别失败：{api_error}")
                    return {}
        
        # 提取 JSON
        answers = extract_json_from_response(response)
        
        print(f"  [VLM 识别] 成功识别 {len(answers)} 个答案")
        
        return answers
        
    except Exception as e:
        print(f"  [VLM 识别] 错误：{e}")
        return {}


def extract_json_from_response(response: str) -> Dict[str, str]:
    """
    从 API 响应中提取 JSON
    
    Args:
        response: API 返回的文本
        
    Returns:
        解析后的字典
    """
    import re
    
    # 清理响应文本（移除多余的换行和空格）
    cleaned_response = response.strip()
    
    # 尝试直接解析
    try:
        return json.loads(cleaned_response)
    except json.JSONDecodeError:
        pass
    
    # 尝试提取 ```json 代码块
    json_match = re.search(r'```json\s*(.*?)\s*```', cleaned_response, re.DOTALL)
    if json_match:
        try:
            json_str = json_match.group(1).strip()
            # 清理 JSON 字符串中的多余换行和空格
            json_str = re.sub(r'\n\s*', '', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"  [DEBUG] JSON 解析失败: {e}")
            pass
    
    # 尝试提取 ``` 代码块
    json_match = re.search(r'```\s*(.*?)\s*```', cleaned_response, re.DOTALL)
    if json_match:
        try:
            json_str = json_match.group(1).strip()
            json_str = re.sub(r'\n\s*', '', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    # 尝试提取 { } 包裹的内容
    json_match = re.search(r'\{.*\}', cleaned_response, re.DOTALL)
    if json_match:
        try:
            json_str = json_match.group(0).strip()
            json_str = re.sub(r'\n\s*', '', json_str)
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass
    
    raise ValueError(f"无法从响应中提取 JSON: {response[:200]}")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='使用 VLM 识别涂卡区')
    parser.add_argument('--image', required=True, help='涂卡区图片路径')
    parser.add_argument('--api-url', help='API URL（可选，默认从数据库读取）')
    parser.add_argument('--api-key', help='API Key（可选，默认从数据库读取）')
    parser.add_argument('--model', help='模型名称（可选，默认从数据库读取）')
    args = parser.parse_args()
    
    print("=" * 60)
    print("涂卡区 VLM 识别")
    print("=" * 60)
    
    results = recognize_answer_card_with_vlm(
        crop_image_path=args.image,
        api_url=args.api_url,
        api_key=args.api_key,
        model_name=args.model
    )
    
    print("\n识别结果:")
    for q_num in sorted(results.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        print(f"  第{q_num}题: {results[q_num]}")
