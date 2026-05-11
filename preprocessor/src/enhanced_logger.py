#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
增强版日志记录器 - 记录所有可能影响结果的信息
"""

import os
import json
import time
import hashlib
from datetime import datetime
from PIL import Image
import cv2
import numpy as np

class EnhancedLogger:
    """增强版日志记录器"""
    
    def __init__(self, workspace_dir: str):
        self.workspace_dir = workspace_dir
        self.start_time = datetime.now()
        self.llm_calls = []
        self.image_info = {}
        self.prompt_contents = {}
        
    def log_llm_call(self, step_name: str, prompt: str, image_path: str, 
                     response: str, api_config: dict, duration: float):
        """记录 LLM 调用信息"""
        token_limit_param = api_config.get("token_limit_param", "max_tokens")
        token_limit_value = api_config.get("token_limit_value", api_config.get("max_tokens", 4000))
        normalized_api_config = {
            "model": api_config.get("model_name"),
            "api_url": api_config.get("api_url"),
            "temperature": api_config.get("temperature", 0.1),
            "seed": api_config.get("seed"),
        }
        normalized_api_config[token_limit_param] = token_limit_value

        call_info = {
            "timestamp": datetime.now().isoformat(),
            "step": step_name,
            "prompt": prompt,
            "image_path": image_path,
            "image_hash": self._get_file_hash(image_path) if image_path else None,
            "response": response,
            "api_config": normalized_api_config,
            "duration_seconds": duration
        }
        self.llm_calls.append(call_info)
        
    def log_image_info(self, image_path: str, metadata: dict):
        """记录图片信息"""
        if not os.path.exists(image_path):
            return
            
        try:
            img = Image.open(image_path)
            file_size = os.path.getsize(image_path)
            
            self.image_info[image_path] = {
                "width": img.width,
                "height": img.height,
                "format": img.format,
                "mode": img.mode,
                "file_size_bytes": file_size,
                "hash": self._get_file_hash(image_path),
                "metadata": metadata
            }
        except Exception as e:
            print(f"Error logging image info: {e}")
            
    def save_prompt(self, step_name: str, prompt: str, image_path: str):
        """保存提示词到文件"""
        filename = f"prompt_used_for_{os.path.basename(image_path).replace('.jpg', '.txt')}"
        filepath = os.path.join(self.workspace_dir, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(prompt)
            
        self.prompt_contents[step_name] = {
            "prompt": prompt,
            "filepath": filepath,
            "image_path": image_path
        }
        
    def save_all_logs(self):
        """保存所有日志到文件"""
        end_time = datetime.now()
        duration = (end_time - self.start_time).total_seconds()
        
        # 1. 完整日志文件
        log_data = {
            "run_info": {
                "start_time": self.start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_seconds": duration,
                "workspace": self.workspace_dir
            },
            "llm_calls": self.llm_calls,
            "image_info": self.image_info,
            "prompts_used": self.prompt_contents
        }
        
        log_file = os.path.join(self.workspace_dir, "complete_run_log.json")
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
            
        # 2. 简化版日志（只包含关键信息）
        summary_log = {
            "run_info": log_data["run_info"],
            "llm_calls_summary": [
                {
                    "step": call["step"],
                    "timestamp": call["timestamp"],
                    "duration": call["duration_seconds"],
                    "model": call["api_config"]["model"],
                    "temperature": call["api_config"]["temperature"],
                    "image_hash": call["image_hash"]
                }
                for call in self.llm_calls
            ]
        }
        
        summary_file = os.path.join(self.workspace_dir, "run_summary.json")
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_log, f, ensure_ascii=False, indent=2)
            
        # 3. 人类可读的文本日志
        text_log_file = os.path.join(self.workspace_dir, "run_log.txt")
        with open(text_log_file, 'w', encoding='utf-8') as f:
            f.write("="*80 + "\n")
            f.write("测试运行日志\n")
            f.write("="*80 + "\n\n")
            
            f.write(f"开始时间：{self.start_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"结束时间：{end_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"总耗时：{duration:.2f} 秒\n")
            f.write(f"工作目录：{self.workspace_dir}\n\n")
            
            f.write("="*80 + "\n")
            f.write("LLM 调用记录\n")
            f.write("="*80 + "\n\n")
            
            for i, call in enumerate(self.llm_calls, 1):
                f.write(f"[{i}] {call['step']}\n")
                f.write(f"    时间：{call['timestamp']}\n")
                f.write(f"    模型：{call['api_config']['model']}\n")
                f.write(f"    Temperature: {call['api_config']['temperature']}\n")
                f.write(f"    Seed: {call['api_config']['seed']}\n")
                f.write(f"    耗时：{call['duration_seconds']:.2f}秒\n")
                f.write(f"    输入图片：{call['image_path']}\n")
                f.write(f"    图片 Hash: {call['image_hash']}\n\n")
                
        print(f"\n✅ 日志已保存到：{self.workspace_dir}")
        print(f"   - complete_run_log.json (完整日志)")
        print(f"   - run_summary.json (简化摘要)")
        print(f"   - run_log.txt (文本日志)")
        
    def _get_file_hash(self, filepath: str) -> str:
        """计算文件 SHA256 哈希值"""
        if not os.path.exists(filepath):
            return "N/A"
            
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
