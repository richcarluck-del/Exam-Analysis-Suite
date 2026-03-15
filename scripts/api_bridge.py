#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek-V3 API 桥接模块
封装 API 调用，支持图片上传和 Markdown 格式诊断报告返回
"""

import os
import time
import logging
import requests
from typing import Optional, Dict, Any
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 2  # 秒
DEFAULT_TIMEOUT = 60  # 秒


class DeepSeekAPIBridge:
    """DeepSeek-V3 API 桥接类"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.deepseek.com/v1/chat/completions",
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: int = DEFAULT_RETRY_DELAY,
        timeout: int = DEFAULT_TIMEOUT
    ):
        """
        初始化 API 桥接
        
        Args:
            api_key: DeepSeek API Key，如果为 None 则从环境变量 DEEPSEEK_API_KEY 读取
            base_url: API 基础 URL
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
            timeout: 请求超时时间（秒）
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("未找到 API Key，请设置 DEEPSEEK_API_KEY 环境变量或在初始化时传入")
        
        self.base_url = base_url
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        })
        
        logger.info("DeepSeek API Bridge 初始化完成")
    
    def _make_request_with_retry(
        self,
        payload: Dict[str, Any],
        endpoint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        带重试逻辑的 API 请求
        
        Args:
            payload: 请求体
            endpoint: API 端点，如果为 None 则使用 base_url
        
        Returns:
            API 响应 JSON 数据
        
        Raises:
            requests.RequestException: 请求失败
        """
        url = endpoint or self.base_url
        last_error = None
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"发送请求 (尝试 {attempt}/{self.max_retries}): {url}")
                response = self.session.post(
                    url,
                    json=payload,
                    timeout=self.timeout
                )
                response.raise_for_status()
                
                result = response.json()
                logger.info(f"请求成功: {result.get('id', 'unknown')}")
                return result
                
            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(f"请求超时 (尝试 {attempt}/{self.max_retries}): {e}")
                
            except requests.exceptions.HTTPError as e:
                last_error = e
                status_code = e.response.status_code if e.response else None
                
                # 4xx 错误不重试（除了 429 Too Many Requests）
                if status_code and 400 <= status_code < 500 and status_code != 429:
                    logger.error(f"客户端错误，不重试: {e}")
                    raise
                
                logger.warning(f"HTTP 错误 (尝试 {attempt}/{self.max_retries}): {e}")
                
            except requests.exceptions.RequestException as e:
                last_error = e
                logger.warning(f"请求失败 (尝试 {attempt}/{self.max_retries}): {e}")
            
            # 等待后重试
            if attempt < self.max_retries:
                wait_time = self.retry_delay * attempt  # 指数退避
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
        
        # 所有重试都失败
        logger.error(f"请求失败，已重试 {self.max_retries} 次")
        raise requests.RequestException(f"请求失败: {last_error}") from last_error
    
    def _encode_image_to_base64(self, image_path: str) -> str:
        """
        将图片编码为 base64
        
        Args:
            image_path: 图片路径
        
        Returns:
            base64 编码的图片字符串
        """
        import base64
        
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def analyze_image(
        self,
        image_path: str,
        prompt: str = "请分析这张试卷题目图片，提供详细的诊断报告，包括：题目类型、难度评估、知识点分析、常见错误点、解题思路建议。请使用 Markdown 格式输出。",
        model: str = "deepseek-chat"
    ) -> str:
        """
        分析图片并返回 Markdown 格式的诊断报告
        
        Args:
            image_path: 图片路径
            prompt: 提示词，默认要求返回 Markdown 格式诊断报告
            model: 使用的模型，默认为 deepseek-chat
        
        Returns:
            Markdown 格式的诊断报告
        
        Raises:
            FileNotFoundError: 图片文件不存在
            requests.RequestException: API 请求失败
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"图片文件不存在: {image_path}")
        
        logger.info(f"开始分析图片: {image_path}")
        
        # 编码图片
        base64_image = self._encode_image_to_base64(image_path)
        
        # 构建请求体
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        # 发送请求
        try:
            response = self._make_request_with_retry(payload)
            
            # 提取回复内容
            if "choices" in response and len(response["choices"]) > 0:
                content = response["choices"][0]["message"]["content"]
                logger.info("成功获取诊断报告")
                return content
            else:
                raise ValueError("API 响应格式异常，未找到 choices 字段")
                
        except Exception as e:
            logger.error(f"分析图片失败: {e}")
            raise
    
    def analyze_multiple_images(
        self,
        image_paths: list[str],
        prompt: Optional[str] = None,
        model: str = "deepseek-chat"
    ) -> Dict[str, str]:
        """
        批量分析多张图片
        
        Args:
            image_paths: 图片路径列表
            prompt: 提示词，如果为 None 则使用默认提示词
            model: 使用的模型
        
        Returns:
            字典，键为图片路径，值为诊断报告
        """
        results = {}
        
        for idx, image_path in enumerate(image_paths, 1):
            try:
                logger.info(f"处理图片 {idx}/{len(image_paths)}: {image_path}")
                report = self.analyze_image(image_path, prompt, model)
                results[image_path] = report
            except Exception as e:
                logger.error(f"分析图片失败 ({image_path}): {e}")
                results[image_path] = f"分析失败: {str(e)}"
        
        return results


def main():
    """命令行测试入口"""
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python api_bridge.py <图片路径> [提示词]")
        print("环境变量: DEEPSEEK_API_KEY (必需)")
        sys.exit(1)
    
    image_path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else None
    
    try:
        bridge = DeepSeekAPIBridge()
        report = bridge.analyze_image(image_path, prompt)
        print("\n" + "=" * 50)
        print("诊断报告:")
        print("=" * 50)
        print(report)
    except Exception as e:
        logger.error(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
