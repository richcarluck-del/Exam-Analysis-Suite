#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
题目解题模块
使用DeepSeek-Coder-V2进行化学题目解答
"""

import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional

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


class QuestionSolver:

    """题目解题器"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "deepseek-chat"):
        """
        初始化解题器
        
        Args:
            api_key: API密钥，如不提供则优先从数据库步骤配置读取，再回退环境变量
            model: 使用的模型名称
        """
        self.model = model
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.api_url = "https://api.deepseek.com/v1/chat/completions"

        if not self.api_key:
            db = SessionLocal()
            try:
                step_config = resolve_step_llm_config(
                    db,
                    "preprocessor.question_solver_solving",
                    fallback_model_name=model,
                    allow_generic_fallback=True,
                )
            finally:
                db.close()

            if step_config:
                self.model = step_config["model_name"]
                self.api_key = step_config["api_key"]
                self.api_url = step_config["api_url"]

        if not self.api_key:
            raise ValueError("请设置数据库步骤模型配置、环境变量 DEEPSEEK_API_KEY，或在初始化时提供API密钥")

        
    def _build_payload(self, prompt: str, max_tokens: int, token_param: str = "max_tokens") -> Dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "text": prompt
                }
            ],
            "temperature": 0.1,
            "stream": False
        }
        payload[token_param] = max_tokens
        return payload

    def call_solver_api(self, prompt: str, max_tokens: int = 2000) -> str:
        """
        调用解题API
        
        Args:
            prompt: 提示词
            max_tokens: 最大输出token数
            
        Returns:
            API返回的文本内容
        """
        payload = self._build_payload(prompt, max_tokens)
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            response = requests.post(self.api_url, json=payload, headers=headers, timeout=120)
            if _should_retry_with_max_completion_tokens(response.status_code, response.text):
                logger.info("当前模型不支持 `max_tokens`，切换为 `max_completion_tokens` 后重试")
                payload = self._build_payload(prompt, max_tokens, token_param="max_completion_tokens")
                response = requests.post(self.api_url, json=payload, headers=headers, timeout=120)

            response.raise_for_status()
            
            result = response.json()
            return result["choices"][0]["message"]["content"]
            
        except requests.exceptions.RequestException as e:
            logger.error(f"解题API请求失败: {e}")
            raise
        except Exception as e:
            logger.error(f"解题API响应解析失败: {e}")
            raise

    
    def build_chemistry_prompt(self, question_data: Dict[str, Any]) -> str:
        """
        构建化学题目解题提示词
        
        Args:
            question_data: 题目数据
            
        Returns:
            构建好的提示词
        """
        question_number = question_data.get('question_number', '未知')
        question_content = question_data.get('question_content', '')
        question_type = question_data.get('question_type', '未知类型')
        
        # 构建选项部分
        options_text = ""
        options = question_data.get('options', {})
        if options and any(options.values()):
            options_text = "\n选项内容："
            for key, value in options.items():
                if value and value.strip():
                    options_text += f"\n{key}. {value}"
        
        db = SessionLocal()
        try:
            prompt_config = resolve_step_prompt(
                db,
                "preprocessor.question_solver_solving",
                variables={
                    "question_number": question_number,
                    "question_type": question_type,
                    "question_content": question_content,
                    "options_text": options_text,
                },
            )
        finally:
            db.close()

        if not prompt_config:
            raise ValueError("未找到题目解答提示词配置")

        return prompt_config["prompt_text"]

    
    def solve_chemistry_question(self, question_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解答化学题目
        
        Args:
            question_data: 题目数据
            
        Returns:
            包含解答结果的字典
        """
        try:
            # 构建提示词
            prompt = self.build_chemistry_prompt(question_data)
            
            # 调用API
            solution = self.call_solver_api(prompt)
            
            # 解析解答结果
            parsed_solution = self.parse_solution_response(solution)
            
            return {
                "question_number": question_data.get('question_number'),
                "solution_raw": solution,
                "solution_parsed": parsed_solution,
                "solving_confidence": 0.9,  # 可以根据解析质量调整
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"解答题目 {question_data.get('question_number')} 失败: {e}")
            return {
                "question_number": question_data.get('question_number'),
                "error": str(e),
                "solving_confidence": 0.0,
                "status": "failed"
            }
    
    def parse_solution_response(self, solution_text: str) -> Dict[str, Any]:
        """
        解析解答结果
        
        Args:
            solution_text: 原始解答文本
            
        Returns:
            结构化的解答结果
        """
        # 简单的文本解析，可以后续增强
        sections = {
            "题目分析": "",
            "解题思路": "", 
            "详细解答步骤": "",
            "最终答案": "",
            "易错点提示": "",
            "化学方程式": ""
        }
        
        current_section = None
        lines = solution_text.split('\n')
        
        for line in lines:
            line = line.strip()
            
            # 检测章节标题
            for section in sections.keys():
                if line.startswith(section) or line.replace(' ', '').startswith(section.replace(' ', '')):
                    current_section = section
                    continue
            
            # 添加到当前章节
            if current_section and line:
                if sections[current_section]:
                    sections[current_section] += "\n" + line
                else:
                    sections[current_section] = line
        
        return sections
    
    def batch_solve_questions(self, recognized_questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量解答题目
        
        Args:
            recognized_questions: 识别后的题目列表
            
        Returns:
            包含解答结果的题目列表
        """
        solved_questions = []
        
        for question in recognized_questions:
            try:
                question_number = question['question_number']
                
                # 检查识别质量
                confidence = question.get('recognition_confidence', 0)
                if confidence < 0.5:
                    logger.warning(f"题目 {question_number} 识别质量低，跳过解答")
                    continue
                
                logger.info(f"正在解答题目 {question_number}...")
                
                # 解答题目
                solution_result = self.solve_chemistry_question(question)
                
                # 合并结果
                combined_result = {
                    **question,
                    **solution_result
                }
                
                solved_questions.append(combined_result)
                
                solving_status = solution_result.get('status', 'unknown')
                logger.info(f"题目 {question_number} 解答完成，状态: {solving_status}")
                
            except Exception as e:
                logger.error(f"解答题目 {question.get('question_number')} 失败: {e}")
                # 添加错误信息但继续处理其他题目
                error_result = {
                    **question,
                    "error": str(e),
                    "solving_confidence": 0.0,
                    "status": "failed"
                }
                solved_questions.append(error_result)
        
        # 统计解答成功率
        success_count = sum(1 for q in solved_questions if q.get('status') == 'success')
        logger.info(f"批量解答完成: 成功 {success_count}/{len(solved_questions)} 道题目")
        
        return solved_questions
    
    def generate_final_report(self, solved_questions: List[Dict[str, Any]]) -> str:
        """
        生成最终解答报告
        
        Args:
            solved_questions: 解答后的题目列表
            
        Returns:
            Markdown格式的报告
        """
        report_lines = ["# 化学试卷解答报告\n"]
        
        total_questions = len(solved_questions)
        success_count = sum(1 for q in solved_questions if q.get('status') == 'success')
        
        report_lines.append(f"**总题目数:** {total_questions}")
        report_lines.append(f"**成功解答:** {success_count}")
        report_lines.append(f"**成功率:** {success_count/total_questions*100:.1f}%\n")
        
        for question in solved_questions:
            question_number = question.get('question_number', '未知')
            status = question.get('status', 'unknown')
            
            report_lines.append(f"## 第{question_number}题")
            
            if status == 'success':
                solution = question.get('solution_parsed', {})
                
                for section, content in solution.items():
                    if content:
                        report_lines.append(f"### {section}")
                        report_lines.append(content)
                        report_lines.append("")
            else:
                report_lines.append("**解答状态:** 失败")
                report_lines.append(f"**错误信息:** {question.get('error', '未知错误')}")
            
            report_lines.append("---\n")
        
        return "\n".join(report_lines)