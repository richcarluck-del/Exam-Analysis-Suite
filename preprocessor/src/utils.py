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


def _should_retry_with_max_completion_tokens(status_code: int, error_text: str) -> bool:
    """判断是否需要把 `max_tokens` 切换为 `max_completion_tokens` 后重试。"""
    if status_code != 400 or not error_text:
        return False

    lowered = error_text.lower()
    return (
        "max_tokens" in lowered
        and "max_completion_tokens" in lowered
        and (
            "unsupported parameter" in lowered
            or "not supported with this model" in lowered
            or "unsupported_parameter" in lowered
        )
    )


def _build_openai_payload(model_name: str, content: list, temperature: float, seed: int, max_tokens: int, token_param: str = "max_tokens") -> dict:
    """构建 OpenAI 兼容格式 payload，并允许切换 token 参数名。"""
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": content}],
        "temperature": temperature,
        "seed": seed,
    }
    payload[token_param] = max_tokens
    return payload


def call_api(prompt: str, api_url: str, api_key: str, model_name: str, image_path: str = None, retries: int = 5, logger=None, step_name: str = "unknown", min_content_length: int = 10) -> str:
    """
    调用大模型 API (兼容 OpenAI 和火山引擎格式)，包含重试机制
    
    Args:
        prompt: 提示词
        api_url: API URL
        api_key: API 密钥
        model_name: 模型名称
        image_path: 图片路径
        retries: 最大重试次数（默认 5 次）
        logger: 日志记录器
        step_name: 步骤名称
        min_content_length: 最小内容长度（默认 10 个字符，少于这个长度会重试）
        
    Returns:
        大模型返回的内容
        
    Raises:
        ValueError: 当 API 配置不完整时
        Exception: 当所有重试都失败时
    """
    if not api_key or not api_url or not model_name:
        raise ValueError("API URL, Key, and Model Name must be provided to call_api.")

    print(f"\n>>>> [大模型 API 调用中] <<<<")
    print(f"  [API URL]: {api_url}")
    print(f"  [模型名称]: {model_name}")
    print(f"  [步骤名称]: {step_name}")
    if image_path:
        print(f"  [入参图片]: {image_path}")
    print(f"  [入参 Prompt]: {prompt.strip()}")
    print(f"  [最小内容长度]: {min_content_length}")
    print(f"--------------------------------")
    
    # 判断是否是火山引擎 API（使用 /api/v3/responses 端点）
    is_volcengine = "/api/v3/responses" in api_url
    print(f"[DEBUG] is_volcengine: {is_volcengine}")
    print(f"[DEBUG] api_url: {api_url}")
    
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
            
            if is_volcengine:
                # 火山引擎格式：input_image 和 input_text
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{mime_type};base64,{base64_image}"
                })
            else:
                # OpenAI 格式：image_url
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                })
            print("[DEBUG] Image added to content payload.")
        except Exception as e:
            print(f"[Error] Failed to encode image {image_path}: {e}")

    # API 调用参数（包含温度和随机种子）
    temperature = 0.1  # 固定温度值
    seed = int(time.time() * 1000) % 1000000  # 基于时间的随机种子
    max_tokens = 4000
    
    if is_volcengine:
        # 火山引擎格式：使用 input 而不是 messages
        payload = {
            "model": model_name,
            "input": [{"role": "user", "content": content}]
        }
        token_limit_param = None
    else:
        # OpenAI 格式
        token_limit_param = "max_tokens"
        payload = _build_openai_payload(
            model_name=model_name,
            content=content,
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens,
            token_param=token_limit_param,
        )
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    print(f"  [Temperature]: {temperature}")
    print(f"  [Seed]: {seed}")
    if token_limit_param:
        print(f"  [Token Limit Param]: {token_limit_param}")
    print(f"  [Max Tokens]: {max_tokens}")
    print("--------------------------------")
    
    start_time = time.time()
    
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
                error_text = response.text[:500]
                if (
                    not is_volcengine
                    and token_limit_param == "max_tokens"
                    and _should_retry_with_max_completion_tokens(response.status_code, error_text)
                ):
                    token_limit_param = "max_completion_tokens"
                    payload = _build_openai_payload(
                        model_name=model_name,
                        content=content,
                        temperature=temperature,
                        seed=seed,
                        max_tokens=max_tokens,
                        token_param=token_limit_param,
                    )
                    print("  [API] 当前模型不支持 `max_tokens`，切换为 `max_completion_tokens` 后重试...")
                    continue
                raise Exception(f"API 调用失败：{response.status_code} - {error_text}")
            
            # 解析响应
            if is_volcengine:
                # 火山引擎格式：output 数组中包含 message
                result_data = response.json()
                output_list = result_data.get("output", [])
                result_content = None
                for item in output_list:
                    if item.get("type") == "message":
                        content_list = item.get("content", [])
                        for c in content_list:
                            if c.get("type") == "output_text":
                                result_content = c.get("text")
                                break
                        break
                if not result_content:
                    raise Exception("无法从火山引擎响应中提取结果")
            else:
                # OpenAI 格式
                result_content = response.json()["choices"][0]["message"]["content"]
            
            # 检查返回内容是否为空或字数过少
            result_content_stripped = result_content.strip()
            if not result_content_stripped:
                raise Exception(f"API 返回空结果")
            
            if len(result_content_stripped) < min_content_length:
                raise Exception(f"API 返回内容字数过少（{len(result_content_stripped)} 字 < {min_content_length} 字要求）")
            
            duration = time.time() - start_time
            
            print(f"  [出参结果]: {result_content_stripped}")
            print(f"  [结果长度]: {len(result_content_stripped)} 字符")
            print(f"<<<< [API 调用完成] >>>>\n")
            
            # 记录到日志
            if logger:
                logger.log_llm_call(
                    step_name=step_name,
                    prompt=prompt,
                    image_path=image_path,
                    response=result_content,
                    api_config={
                        "model_name": model_name,
                        "api_url": api_url,
                        "temperature": temperature,
                        "seed": seed,
                        "max_tokens": max_tokens,
                        "token_limit_param": token_limit_param or "max_tokens",
                        "token_limit_value": max_tokens,
                    },
                    duration=duration
                )
            
            return result_content
            
        except Exception as e:
            print(f"  API 调用异常 (尝试 {attempt+1}/{retries}): {e}")
            if attempt == retries - 1:
                raise
            time.sleep(2)

def _escape_control_chars_in_json_strings(text: str) -> str:
    """转义 JSON 字符串内部的裸控制字符，避免 `json.loads` 失败。"""
    result = []
    in_string = False
    escape = False

    for char in text:
        if in_string:
            if escape:
                result.append(char)
                escape = False
                continue

            if char == "\\":
                result.append(char)
                escape = True
                continue

            if char == '"':
                result.append(char)
                in_string = False
                continue

            if char == "\n":
                result.append("\\n")
                continue
            if char == "\r":
                result.append("\\r")
                continue
            if char == "\t":
                result.append("\\t")
                continue
            if ord(char) < 32:
                result.append(f"\\u{ord(char):04x}")
                continue

            result.append(char)
            continue

        result.append(char)
        if char == '"':
            in_string = True

    return ''.join(result)


def extract_json(text: str) -> str:
    """从文本中提取 JSON 字符串，兼容带有或不带有 markdown 代码块标记的情况"""
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
    else:
        match = re.search(r"```\n(.*?)\n```", text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        else:
            json_str = text.strip()

    json_str = _escape_control_chars_in_json_strings(json_str)
    return json_str


def crop_with_padding(image, points, padding=None):
    """
    带扩展的切片函数（容错设计）
    
    Args:
        image: 原图（OpenCV 读取的 numpy 数组）
        points: 坐标点 {top_left, top_right, bottom_right, bottom_left}（归一化坐标，0-1000）
        padding: 扩展像素 [top, bottom, left, right]，默认 [15, 25, 15, 15]
            - 上边：15 像素（避免包含上一题）
            - 下边：25 像素（防止切掉公式下标、化学式下标等）
            - 左边：15 像素
            - 右边：15 像素
    
    Returns:
        切片后的图片（numpy 数组）
    """
    if padding is None:
        padding = [15, 25, 15, 15]  # 上、下、左、右
    
    h, w = image.shape[:2]
    
    # 将归一化坐标转换为像素坐标
    x_min = int(min(points['top_left'][0], points['bottom_left'][0]) / 1000 * w)
    y_min = int(min(points['top_left'][1], points['top_right'][1]) / 1000 * h)
    x_max = int(max(points['top_right'][0], points['bottom_right'][0]) / 1000 * w)
    y_max = int(max(points['bottom_left'][1], points['bottom_right'][1]) / 1000 * h)
    
    # 应用扩展（确保不超出图片边界）
    x_min = max(0, x_min - padding[2])  # 左
    y_min = max(0, y_min - padding[0])  # 上
    x_max = min(w, x_max + padding[3])  # 右
    y_max = min(h, y_max + padding[1])  # 下
    
    # 切片
    crop = image[y_min:y_max, x_min:x_max]
    
    return crop


def save_crop_with_quality(crop, output_path, quality=95):
    """
    保存切片图片，指定 JPEG 质量
    
    Args:
        crop: 切片后的图片（numpy 数组）
        output_path: 输出路径
        quality: JPEG 质量（0-100），默认 95
    """
    # 确保目录存在
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # 保存为 JPEG 格式，指定质量
    cv2.imwrite(output_path, crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
