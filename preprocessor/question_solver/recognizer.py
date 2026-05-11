#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目识别模块
使用多模态大模型识别题目内容
"""

import os
import json
import logging
import requests
import base64
from pathlib import Path
from typing import Dict, Any, Optional
from PIL import Image

from shared.database import SessionLocal
from shared.llm_step_config import resolve_step_llm_config
from shared.prompt_step_config import resolve_step_prompt



# 配置日志
logger = logging.getLogger(__name__)


def _should_retry_with_max_completion_tokens(status_code: int, error_text: str) -> bool:
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


class QuestionRecognizer:

    """题目识别器"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "Qwen/Qwen3-VL-32B-Instruct"):
        """
        初始化识别器
        
        Args:
            api_key: API密钥，如不提供则优先从数据库步骤配置读取，再回退环境变量
            model: 使用的模型名称
        """
        self.model = model
        self.api_key = api_key or os.environ.get("SILICONFLOW_API_KEY")
        self.api_url = "https://api.siliconflow.cn/v1/chat/completions"

        if not self.api_key:
            db = SessionLocal()
            try:
                step_config = resolve_step_llm_config(
                    db,
                    "preprocessor.question_solver_recognition",
                    fallback_model_name=model,
                    allow_generic_fallback=True,
                    prefer_vision_fallback=True,
                )
            finally:
                db.close()

            if step_config:
                self.model = step_config["model_name"]
                self.api_key = step_config["api_key"]
                self.api_url = step_config["api_url"]

        if not self.api_key:
            raise ValueError("请设置数据库步骤模型配置、环境变量 SILICONFLOW_API_KEY，或在初始化时提供API密钥")

        
    def encode_image_to_base64(self, image_path: str) -> str:
        """将图片编码为base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def _build_payload(self, image_path: str, prompt: str, max_tokens: int, token_param: str = "max_tokens") -> Dict[str, Any]:
        base64_image = self.encode_image_to_base64(image_path)
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ],
            "temperature": 0.1  # 低温度确保输出稳定
        }
        payload[token_param] = max_tokens
        return payload

    def call_vlm_api(self, image_path: str, prompt: str, max_tokens: int = 2000) -> str:
        """
        调用VLM API进行识别
        
        Args:
            image_path: 图片路径
            prompt: 提示词
            max_tokens: 最大输出token数
            
        Returns:
            API返回的文本内容
        """
        payload = self._build_payload(image_path, prompt, max_tokens)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=60)
            if _should_retry_with_max_completion_tokens(response.status_code, response.text):
                logger.info("当前模型不支持 `max_tokens`，切换为 `max_completion_tokens` 后重试")
                payload = self._build_payload(image_path, prompt, max_tokens, token_param="max_completion_tokens")
                response = requests.post(self.api_url, json=payload, headers=headers, timeout=60)

            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}")
            raise
        except Exception as e:
            logger.error(f"API响应解析失败: {e}")
            raise

    
    def recognize_question_content(self, image_path: str) -> Dict[str, Any]:
        """
        识别题目内容
        
        Args:
            image_path: 题目图片路径
            
        Returns:
            包含识别结果的字典
        """
        db = SessionLocal()
        try:
            prompt_config = resolve_step_prompt(db, "preprocessor.question_solver_recognition")
        finally:
            db.close()

        prompt = prompt_config.get("prompt_text") if prompt_config else None
        if not prompt:
            raise ValueError("未找到题目识别提示词配置")

        
        try:
            content = self.call_vlm_api(image_path, prompt)
            
            # 提取JSON内容
            json_match = self.extract_json_from_response(content)
            if json_match:
                result = json.loads(json_match)
                result["raw_response"] = content
                return result
            else:
                # 如果无法提取JSON，返回原始内容
                return {
                    "question_content": content,
                    "recognition_confidence": 0.5,
                    "raw_response": content,
                    "error": "无法解析JSON格式"
                }
                
        except Exception as e:
            logger.error(f"题目识别失败 {image_path}: {e}")
            return {
                "error": str(e),
                "recognition_confidence": 0.0
            }
    
    def extract_json_from_response(self, text: str) -> Optional[str]:
        """从响应文本中提取JSON内容"""
        # 尝试提取代码块中的JSON
        import re
        
        # 匹配 ```json ... ``` 格式
        json_pattern = r'```json\s*(.*?)\s*```'
        match = re.search(json_pattern, text, re.DOTALL)
        if match:
            return match.group(1).strip()
        
        # 匹配 { ... } 格式
        brace_pattern = r'\{(?:[^{}]|(?R))*\}'
        match = re.search(brace_pattern, text, re.DOTALL)
        if match:
            return match.group(0)
        
        return None
    
    def batch_recognize_questions(self, cropped_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量识别题目内容
        
        Args:
            cropped_questions: 切图后的题目列表
            
        Returns:
            包含识别结果的题目列表
        """
        recognized_questions = []
        
        for question in cropped_questions:
            try:
                image_path = question['cropped_image_path']
                question_number = question['question_number']
                
                logger.info(f"正在识别题目 {question_number}...")
                
                # 识别题目内容
                recognition_result = self.recognize_question_content(image_path)
                
                # 合并结果
                combined_result = {
                    **question,
                    **recognition_result
                }
                
                recognized_questions.append(combined_result)
                
                confidence = recognition_result.get('recognition_confidence', 0)
                logger.info(f"题目 {question_number} 识别完成，置信度: {confidence:.2f}")
                
            except Exception as e:
                logger.error(f"识别题目 {question.get('question_number')} 失败: {e}")
                # 添加错误信息但继续处理其他题目
                error_result = {
                    **question,
                    "error": str(e),
                    "recognition_confidence": 0.0
                }
                recognized_questions.append(error_result)
        
        # 统计识别成功率
        success_count = sum(1 for q in recognized_questions if q.get('recognition_confidence', 0) > 0.5)
        logger.info(f"批量识别完成: 成功 {success_count}/{len(recognized_questions)} 道题目")
        
        return recognized_questions
    
    def validate_recognition_quality(self, recognized_questions: List[Dict[str, Any]], 
                                   min_confidence: float = 0.6) -> List[Dict[str, Any]]:
        """
        验证识别质量
        
        Args:
            recognized_questions: 识别后的题目列表
            min_confidence: 最小置信度阈值
            
        Returns:
            质量合格的题目列表
        """
        valid_questions = []
        
        for question in recognized_questions:
            confidence = question.get('recognition_confidence', 0)
            
            if confidence >= min_confidence and 'error' not in question:
                valid_questions.append(question)
            else:
                logger.warning(f"题目 {question.get('question_number')} 识别质量不合格: 置信度 {confidence}")
        
        logger.info(f"识别质量验证完成: 合格 {len(valid_questions)}/{len(recognized_questions)} 道题目")
        return valid_questions