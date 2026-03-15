import os
import base64
import requests
import json
import re
import time
import cv2
import numpy as np
from pathlib import Path
from PIL import Image

# This file no longer depends on load_dotenv or any global API variables.

def encode_image_to_base64(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def get_image_mime_type(image_path: str) -> str:
    """获取图片 MIME 类型"""
    ext = Path(image_path).suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")

def call_api(prompt: str, api_url: str, api_key: str, model_name: str, image_path: str = None, retries: int = 5) -> str:
    """调用大模型 API (兼容 OpenAI 格式)，包含重试机制"""
    if not api_key or not api_url or not model_name:
        raise ValueError("API URL, Key, and Model Name must be provided to call_api.")

    print(f"\n>>>> [大模型 API 调用中] <<<<")
    print(f"  [API URL]: {api_url}")
    print(f"  [模型名称]: {model_name}")
    if image_path:
        print(f"  [入参图片]: {image_path}")
    print(f"  [入参Prompt]: {prompt.strip()}")
    print(f"--------------------------------")
    
    content = [{"type": "text", "text": prompt}]
    
    if image_path:
        try:
            if not os.path.exists(image_path):
                print(f"[DEBUG] Image path does not exist: {image_path}")
            else:
                print(f"[DEBUG] Image path exists: {image_path}")
            base64_image = encode_image_to_base64(image_path)
            if len(base64_image) == 0:
                print("[DEBUG] Base64 encoding is empty!")
            else:
                print(f"[DEBUG] Base64 encoded length: {len(base64_image)}")
            mime_type = get_image_mime_type(image_path)
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
            })
            print("[DEBUG] Image added to content payload.")
        except Exception as e:
            print(f"[Error] Failed to encode image {image_path}: {e}")

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.1,
        "max_tokens": 4000
    }
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    for attempt in range(retries):
        try:
            proxies = {"http": None, "https": None}
            response = requests.post(api_url, headers=headers, json=payload, timeout=300, proxies=proxies)
            
            if response.status_code == 429:
                wait_time = 2 ** (attempt + 1)
                print(f"  [API] 429 限流，等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
                continue
                
            if response.status_code != 200:
                raise Exception(f"API 调用失败: {response.status_code} - {response.text[:500]}")
            
            result_content = response.json()["choices"][0]["message"]["content"]
            print(f"  [出参结果]: {result_content.strip()}")
            print(f"<<<< [API 调用完成] >>>>\n")
            return result_content
            
        except Exception as e:
            print(f"  API 调用异常 (尝试 {attempt+1}/{retries}): {e}")
            if attempt == retries - 1:
                raise
            time.sleep(2)

def extract_json(text: str) -> str:
    """从文本中提取 JSON 字符串，兼容带有或不带有 markdown 代码块标记的情况"""
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    match = re.search(r"```\n(.*?)\n```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    return text.strip()
